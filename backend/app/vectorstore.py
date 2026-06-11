import hashlib
import logging
from typing import List

from langchain_core.documents import Document

from app.config import settings

logger = logging.getLogger(__name__)

_client = None
_collection = None


def get_client():
    global _client
    if _client is None:
        import chromadb

        _client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
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
    collection = get_collection()
    try:
        collection.delete(where={"$and": [{"tenant_id": tenant_id}, {"document_id": document_id}]})
    except Exception as exc:
        logger.warning("[智能客服-知识库|vectorstore|Chroma|硬编执行|删除] 失败; doc_id=%s; error=%s", document_id, exc)


def search(query: str, k: int = 12, tenant_id: str = "default") -> List[Document]:
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
    docs = []
    if results and results["documents"]:
        for i, text in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 1
            similarity = 1 - distance
            meta["score"] = similarity
            docs.append(Document(page_content=text, metadata=meta))
    return docs
