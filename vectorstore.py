import logging
import hashlib
from typing import List, Optional
from langchain_core.documents import Document
from config import settings

logger = logging.getLogger(__name__)

_client = None
_collection = None

def get_client():
    global _client
    if _client is None:
        try:
            import chromadb
            _client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT
            )
        except Exception as e:
            logger.warning(f"Chroma连接失败: {e}")
    return _client

def get_collection(name: str = "kb_main"):
    global _collection
    if _collection is None:
        client = get_client()
        if client:
            _collection = client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"}
            )
    return _collection

def reset_collection(name: str = "kb_main"):
    """
    删除集合，用于数据清理
    """
    global _collection
    client = get_client()
    if client:
        try:
            client.delete_collection(name)
            logger.info(f"已删除集合 {name}")
        except Exception as e:
            logger.warning(f"删除集合失败: {e}")
        _collection = None

def doc_hash(content: str) -> str:
    return hashlib.md5(content.encode()).hexdigest()

def add_documents(docs: List[Document], tenant_id: str = "default"):
    if not docs:
        return
    
    from llms import get_embedder
    embedder = get_embedder()
    if not embedder:
        logger.warning("Embedder未初始化")
        return
    
    collection = get_collection()
    if not collection:
        return
    
    new_docs = []
    new_ids = []
    existing_ids = set()
    
    try:
        all_ids = [f"{tenant_id}_{doc_hash(doc.page_content)}" for doc in docs]
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
        logger.info("无新增文档")
        return
    
    texts = [doc.page_content for doc in new_docs]
    logger.info(f"生成向量 新增{len(texts)}条")
    
    embeddings = embedder.embed_documents(texts)
    metadatas = [{**doc.metadata, "tenant_id": tenant_id} for doc in new_docs]
    
    collection.add(
        ids=new_ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas
    )
    logger.info("向量写入完成")

def search(query: str, k: int = 12, tenant_id: str = "default") -> List[Document]:
    from llms import get_embedder
    embedder = get_embedder()
    if not embedder:
        return []
    
    collection = get_collection()
    if not collection:
        return []
    
    try:
        query_embedding = embedder.embed_query(query)
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where={"tenant_id": tenant_id},
            include=["documents", "metadatas", "distances"]
        )
        
        docs = []
        if results and results["documents"]:
            for i, text in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0
                similarity = 1 - distance
                if similarity > 0.2:
                    meta["score"] = similarity
                    meta["source"] = "vector"
                    docs.append(Document(page_content=text, metadata=meta))
        
        return docs
        
    except Exception as e:
        logger.warning(f"向量检索失败: {e}")
        return []
