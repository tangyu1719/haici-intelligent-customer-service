import hashlib

import logging

from pathlib import Path

from typing import List



from langchain_core.documents import Document



from app.config import settings



logger = logging.getLogger(__name__)



_client = None

_collection = None

_chroma_unavailable = False





def get_client():

    global _client, _chroma_unavailable

    if _chroma_unavailable:

        raise RuntimeError("Chroma 不可用")

    if _client is None:

        import chromadb

        try:
            persist = (settings.CHROMA_PERSIST_PATH or "").strip()
            if persist:
                Path(persist).mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=persist)
            else:
                _client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
                _client.heartbeat()

        except Exception as exc:

            _chroma_unavailable = True

            logger.warning(

                "[智能客服-知识库|vectorstore|Chroma|硬编执行|不可用] error_type=%s; error_message=%s",

                type(exc).__name__,

                str(exc)[:200],

            )

            raise

    return _client





def get_collection(name: str = "kb_main"):

    global _collection

    if _collection is None:

        client = get_client()

        _collection = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    return _collection





def doc_hash(content: str) -> str:

    return hashlib.md5(content.encode()).hexdigest()





def add_documents(docs: List[Document], tenant_id: str = "default"):

    if not docs:

        return 0

    from app.llms import get_embedder



    embedder = get_embedder()

    collection = get_collection()

    new_docs, new_ids = [], []

    existing_ids = set()

    all_ids = [f"{tenant_id}_{doc_hash(doc.page_content)}" for doc in docs]

    try:

        result = collection.get(ids=all_ids)

        if result and result["ids"]:

            existing_ids = set(result["ids"])

    except Exception:

        pass

    for doc in docs:

        doc_id = f"{tenant_id}_{doc_hash(doc.page_content)}"

        if doc_id not in existing_ids and doc_id not in new_ids:

            new_docs.append(doc)

            new_ids.append(doc_id)

    if not new_docs:

        return 0

    texts = [d.page_content for d in new_docs]

    embeddings = embedder.embed_documents(texts)

    metadatas = [{**d.metadata, "tenant_id": tenant_id} for d in new_docs]

    collection.add(ids=new_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    return len(new_docs)





def delete_by_document(document_id: int, tenant_id: str = "default"):
    """按 document_id 删除向量分块；Chroma 不可用时不阻断 MySQL 侧删除。"""
    try:
        collection = get_collection()
    except Exception as exc:
        logger.warning(
            "[智能客服-知识库|vectorstore|Chroma|硬编执行|删除] 向量库不可用，跳过向量清理; doc_id=%s; error_type=%s; error_message=%s",
            document_id,
            type(exc).__name__,
            str(exc)[:200],
        )
        return

    tid = str(tenant_id)
    # Chroma 元数据类型可能为 int 或 str，两种都尝试
    for doc_id_val in (document_id, str(document_id)):
        try:
            collection.delete(where={"$and": [{"tenant_id": tid}, {"document_id": doc_id_val}]})
        except Exception as exc:
            logger.warning(
                "[智能客服-知识库|vectorstore|Chroma|硬编执行|删除] 失败; doc_id=%s; meta_type=%s; error=%s",
                document_id,
                type(doc_id_val).__name__,
                exc,
            )





def _search_core(query: str, k: int = 12, tenant_id: str = "default") -> List[Document]:
    from app.llms import get_embedder

    embedder = get_embedder()
    collection = get_collection()
    query_embedding = embedder.embed_query(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        where={"tenant_id": tenant_id},
        include=["documents", "metadatas", "distances"],
    )
    docs: list[Document] = []
    if results and results["documents"]:
        for i, text in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 1
            similarity = 1 - distance
            meta["score"] = similarity
            docs.append(Document(page_content=text, metadata=meta))
    return docs


def _rag_search_extra(docs: list[Document], args: tuple, kwargs: dict) -> dict:
    k = int(kwargs.get("k") or (args[1] if len(args) > 1 else 12))
    hits = len(docs)
    return {"hits": hits, "recall": round(hits / max(k, 1), 4), "top_k": k}


from app.services.agent_call_logger import track_agent_call

search = track_agent_call(
    api_type="rag",
    target="chroma:kb_main",
    tool_name="rag_search",
    request_fn=lambda a, k: str(a[0] if a else k.get("query", ""))[:500],
    extra_fn=_rag_search_extra,
)(_search_core)

