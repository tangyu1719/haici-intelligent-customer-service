import logging
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Tuple
from langchain_core.documents import Document
from llms import get_llm, get_reranker
from config import settings

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8)

FAQ_PATTERNS = []

def get_redis_cache():
    try:
        import redis
        return redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_timeout=1.0
        )
    except Exception:
        return None

def cache_key(query: str) -> str:
    return "rag_v8:" + hashlib.md5(query.encode()).hexdigest()

def _vector_search(query: str, tenant_id: str, k: int) -> List[Document]:
    from vectorstore import search as vec_search
    try:
        return vec_search(query, k=k, tenant_id=tenant_id)
    except Exception:
        return []

def _es_search(query: str, tenant_id: str, k: int) -> List[Document]:
    from es_client import search as es_search
    try:
        return es_search(query, k=k, tenant_id=tenant_id)
    except Exception:
        return []


def expand_query(query: str, llm) -> List[str]:
    """查询改写扩展，提升召回"""
    queries = [query]
    try:
        prompt = f"""针对以下用户问题，生成2个语义相近但表述不同的改写版本，用于提升搜索召回。
每行输出一个改写，不要编号，不要解释。

用户问题: {query}
改写:"""
        result = llm.call(prompt, temperature=0.3, max_tokens=100)
        for line in result.strip().split("\n"):
            line = line.strip().lstrip("0123456789.、-) ")
            if len(line) > 4 and line != query:
                queries.append(line)
    except Exception as e:
        logger.debug("查询扩展跳过: %s", str(e))
    return queries[:3]

def retrieve_pipeline(query: str, tenant_id: str) -> List[Document]:
    llm = get_llm()
    queries = expand_query(query, llm)

    all_vec_docs = []
    all_es_docs = []
    futures_vec = [_executor.submit(_vector_search, q, tenant_id, 15) for q in queries]
    futures_es = [_executor.submit(_es_search, q, tenant_id, 15) for q in queries]
    for f in futures_vec:
        try:
            all_vec_docs.extend(f.result(timeout=3) or [])
        except Exception:
            pass
    for f in futures_es:
        try:
            all_es_docs.extend(f.result(timeout=3) or [])
        except Exception:
            pass
    vec_docs = all_vec_docs
    es_docs = all_es_docs

    if not vec_docs and not es_docs:
        return []

    parent_ids = set()
    for doc in vec_docs + es_docs:
        pid = doc.metadata.get("parent_id")
        if pid:
            parent_ids.add(pid)

    parent_map = {}
    if parent_ids:
        from es_client import get_by_parent_ids
        parent_docs = get_by_parent_ids(list(parent_ids), tenant_id)
        parent_map = {d.metadata.get("parent_id"): d for d in parent_docs}

    def rrf_score(rank, k=60):
        return 1.0 / (k + rank + 1)

    doc_scores = {}

    for rank, doc in enumerate(vec_docs):
        pid = doc.metadata.get("parent_id")
        final_doc = parent_map.get(pid) if pid else doc
        if final_doc:
            key = final_doc.page_content[:200]
            if key not in doc_scores:
                doc_scores[key] = [final_doc, 0.0]
            doc_scores[key][1] += rrf_score(rank)

    for rank, doc in enumerate(es_docs):
        pid = doc.metadata.get("parent_id")
        final_doc = parent_map.get(pid) if pid else doc
        if final_doc:
            key = final_doc.page_content[:200]
            if key not in doc_scores:
                doc_scores[key] = [final_doc, 0.0]
            doc_scores[key][1] += rrf_score(rank)

    rrf_ranked = sorted(doc_scores.values(), key=lambda x: x[1], reverse=True)
    unique_candidates = [doc for doc, _ in rrf_ranked[:15]]

    reranker = get_reranker()
    if reranker and unique_candidates:
        final_docs = reranker.rerank(query, unique_candidates, top_k=3)
    else:
        final_docs = unique_candidates[:3]

    return final_docs

def generate_answer(query: str, docs: List[Document], llm) -> Tuple[str, float]:
    if not docs:
        return "抱歉，未找到相关信息。", 0.0

    ctx_str = "\n".join([f"{i+1}. {d.page_content}" for i, d in enumerate(docs)])

    prompt = f"""你是电商客服助手。请严格基于以下资料回答用户问题。

重要规则：
1. 必须原样引用资料中的数字、金额、时间、距离等数据，绝对不能修改或推测
2. 资料中写"39元"就回答"39元"，写"99元"就回答"99元"，写"5级"就回答"5级"
3. 资料中写"1小时"就回答"1小时"，不能改成"1个工作日"
4. 尽可能完整覆盖资料中与问题相关的所有信息点
5. 如果资料中没有相关信息，直接说"未找到相关信息"

资料:
{ctx_str}

问题: {query}
回答:"""

    try:
        answer = llm.call(prompt, temperature=0.1, max_tokens=300)
        return answer, 0.95
    except Exception:
        return "系统繁忙", 0.0

def rag_query(query: str, tenant_id: str = "default", skip_cache: bool = False) -> Dict:
    ck = cache_key(query)
    redis_cache = get_redis_cache()

    if not skip_cache and redis_cache:
        try:
            cached = redis_cache.get(ck)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    for pattern, ans in FAQ_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return {"answer": ans, "context": [], "score": 1.0}

    llm = get_llm()
    final_docs = retrieve_pipeline(query, tenant_id)

    answer, score = generate_answer(query, final_docs, llm)

    result = {
        "answer": answer,
        "context": [{"content": d.page_content[:200]} for d in final_docs],
        "score": score
    }

    if not skip_cache and redis_cache and score > 0.6:
        try:
            redis_cache.setex(ck, 600, json.dumps(result))
        except Exception:
            pass

    return result
