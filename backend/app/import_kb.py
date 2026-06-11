import json
import logging
import sys
import os
from langchain_core.documents import Document

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s", 
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def main():
    from vectorstore import add_documents
    from es_client import bulk_index
    
    kb_path = "test_data/knowledge_base.json"
    if not os.path.exists(kb_path):
        logger.error(f"文件不存在: {kb_path}")
        return

    logger.info(f"读取知识库 {kb_path}")
    
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"共解析出 {len(data)} 条数据")
    except json.JSONDecodeError as e:
        logger.error(f"JSON格式错误: 行 {e.lineno} 列 {e.colno} - {e.msg}")
        return
    except Exception as e:
        logger.error(f"读取文件失败: {e}")
        return

    docs = []
    es_docs = []
    
    for item in data:
        content = item.get("content", "").strip()
        if not content:
            continue
            
        meta = {
            "category": item.get("category", "general"), 
            "source": "knowledge_base.json"
        }
        docs.append(Document(page_content=content, metadata=meta))
        es_docs.append({"content": content, **meta})

    if not docs:
        logger.warning("无有效数据，结束导入")
        return

    logger.info(f"正在写入向量库 共{len(docs)}条...")
    try:
        add_documents(docs)
        logger.info("向量库写入完成")
    except Exception as e:
        logger.error(f"向量库写入失败: {e}")

    logger.info("正在写入搜索引擎...")
    try:
        bulk_index(es_docs)
        logger.info("ES写入完成")
    except Exception as e:
        logger.error(f"ES写入失败: {e}")

    logger.info(f"知识库导入完成 总计{len(docs)}条")


if __name__ == "__main__":
    main()
