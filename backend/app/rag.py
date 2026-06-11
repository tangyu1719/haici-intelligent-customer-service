"""减重版 RAG：仅 Chroma 向量检索，移除 ES / Redis / Reranker / 查询扩展。"""

import logging
from typing import Dict, List, Tuple

from langchain_core.documents import Document

from app.config import settings
from app.llms import get_llm

logger = logging.getLogger(__name__)


def retrieve(query: str, tenant_id: str = "default") -> List[Document]:
    from app.vectorstore import search as vec_search

    docs = vec_search(query, k=settings.RAG_TOP_K, tenant_id=tenant_id)
    filtered = []
    for d in docs:
        score = float(d.metadata.get("score", 0))
        if score >= settings.RAG_SCORE_THRESHOLD:
            filtered.append(d)
    return filtered


def build_prompt_messages(query: str, docs: List[Document], history: List[dict], intent: str) -> list[dict[str, str]]:
    if not docs:
        return []
    ctx = "\n\n".join(
        [
            f"[{i+1}] 文档:{d.metadata.get('document_name', '未知')} 片段:{d.page_content[:300]}"
            for i, d in enumerate(docs)
        ]
    )
    hist = "\n".join([f"{h['role']}:{h['content'][:200]}" for h in history[-settings.CHAT_HISTORY_TURNS * 2 :]])
    system = (
        "你是企业智能客服。只能依据知识库片段回答，不得编造。"
        "若资料不足请明确说明无法回答。"
    )
    user = f"意图:{intent}\n历史:\n{hist or '无'}\n\n资料:\n{ctx}\n\n问题:{query}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def citations_from_docs(docs: List[Document]) -> list[dict]:
    return [
        {
            "document_name": d.metadata.get("document_name", "未知文档"),
            "snippet": d.page_content[:300],
            "score": d.metadata.get("score"),
        }
        for d in docs
    ]


def rag_query(query: str, tenant_id: str = "default", history: List[dict] | None = None, intent: str = "product_consult") -> Dict:
    history = history or []
    docs = retrieve(query, tenant_id)
    if not docs:
        return {
            "answer": settings.FALLBACK_NO_CONTEXT,
            "context": [],
            "citations": [],
            "score": 0.0,
            "has_context": False,
        }
    llm = get_llm()
    messages = build_prompt_messages(query, docs, history, intent)
    answer = llm.call(messages[-1]["content"]) if messages else settings.FALLBACK_NO_CONTEXT
    return {
        "answer": answer,
        "context": [{"content": d.page_content[:200]} for d in docs],
        "citations": citations_from_docs(docs),
        "score": 0.9,
        "has_context": True,
    }
