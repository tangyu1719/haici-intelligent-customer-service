import logging
from typing import List
from langchain_core.documents import Document
from config import settings

logger = logging.getLogger(__name__)

_es = None

def get_client():
    global _es
    if _es:
        return _es
    try:
        from elasticsearch import Elasticsearch
        client = Elasticsearch(hosts=[settings.ES_HOST], request_timeout=5, max_retries=1)
        if client.ping():
            _es = client
            return _es
    except Exception as e:
        logger.warning("ES连接失败: %s", str(e))
    return None

def ensure_index(index_name: str):
    es = get_client()
    if not es:
        return
    try:
        if not es.indices.exists(index=index_name):
            es.indices.create(index=index_name, body={
                "settings": {"number_of_shards": 1, "refresh_interval": "1s"},
                "mappings": {
                    "properties": {
                        "content": {"type": "text", "analyzer": "standard"},
                        "category": {"type": "keyword"},
                        "tenant_id": {"type": "keyword"},
                        "parent_id": {"type": "keyword"},
                        "doc_type": {"type": "keyword"}
                    }
                }
            })
    except Exception as e:
        logger.warning("创建索引失败: %s", str(e))

def jieba_tokenize(text: str) -> List[str]:
    try:
        import jieba
        return list(jieba.cut(text, cut_all=False))
    except Exception:
        return text.split()

def bulk_index(docs: list, tenant_id: str = "default", index_name: str = None):
    index_name = index_name or settings.ES_INDEX
    es = get_client()
    if not es:
        return
    ensure_index(index_name)
    actions = []
    for doc in docs:
        action = {"index": {"_index": index_name}}
        if isinstance(doc, dict):
            content = doc.get("content", "")
            meta = {k: v for k, v in doc.items() if k != "content"}
        else:
            content = getattr(doc, "page_content", str(doc))
            meta = getattr(doc, "metadata", {})
        source = {"content": content, "tenant_id": tenant_id, **meta}
        actions.append(action)
        actions.append(source)
    if actions:
        try:
            es.bulk(body=actions, refresh=True)
        except Exception as e:
            logger.error("ES写入失败: %s", str(e))

def search(query: str, k: int = 10, tenant_id: str = "default", index_name: str = None) -> List[Document]:
    index_name = index_name or settings.ES_INDEX
    es = get_client()
    if not es:
        return []

    tokens = jieba_tokenize(query)
    expanded = " ".join(tokens)

    try:
        body = {
            "query": {
                "bool": {
                    "must": [{
                        "bool": {
                            "should": [
                                {"match_phrase": {"content": {"query": query, "boost": 5.0, "slop": 1}}},
                                {"match": {"content": {"query": expanded, "operator": "or", "minimum_should_match": "40%", "boost": 1.5}}},
                                {"match": {"content": {"query": query, "operator": "and", "boost": 3.0}}}
                            ],
                            "minimum_should_match": 1
                        }
                    }],
                    "filter": {"term": {"tenant_id": tenant_id}}
                }
            },
            "size": k,
            "min_score": 0.5
        }

        res = es.search(index=index_name, body=body)
        docs = []
        if res and "hits" in res and "hits" in res["hits"]:
            for hit in res["hits"]["hits"]:
                src = hit["_source"]
                content = src.pop("content", "")
                docs.append(Document(page_content=content, metadata={**src, "score": hit["_score"], "source": "es"}))
        return docs
    except Exception as e:
        logger.warning("ES搜索失败: %s", str(e))
        return []

def get_by_parent_ids(parent_ids: List[str], tenant_id: str = "default", index_name: str = None) -> List[Document]:
    index_name = index_name or settings.ES_INDEX
    es = get_client()
    if not es or not parent_ids:
        return []

    try:
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"terms": {"parent_id": parent_ids}},
                        {"term": {"tenant_id": tenant_id}}
                    ]
                }
            },
            "size": len(parent_ids)
        }
        res = es.search(index=index_name, body=body)
        docs = []
        if res and "hits" in res and "hits" in res["hits"]:
            for hit in res["hits"]["hits"]:
                src = hit["_source"]
                content = src.pop("content", "")
                docs.append(Document(page_content=content, metadata={**src, "source": "es_parent"}))
        return docs
    except Exception as e:
        logger.warning("ES父块召回失败: %s", str(e))
        return []
