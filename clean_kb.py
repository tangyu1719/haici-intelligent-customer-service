import logging
import sys
from config import settings
from vectorstore import reset_collection
from es_client import get_client

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

def clean_all():
    logger.info("开始清理知识库数据...")

    # 1. 清理 ChromaDB (向量数据)
    try:
        reset_collection() # 调用 vectorstore.py 中的重置函数
        logger.info("[Success] ChromaDB 集合已删除")
    except Exception as e:
        logger.error(f"[Error] ChromaDB 清理失败: {e}")

    # 2. 清理 Elasticsearch (关键词数据)
    try:
        es = get_client()
        if es:
            if es.indices.exists(index=settings.ES_INDEX):
                es.indices.delete(index=settings.ES_INDEX)
                logger.info(f"[Success] ES 索引 {settings.ES_INDEX} 已删除")
            else:
                logger.info(f"[Skip] ES 索引 {settings.ES_INDEX} 不存在")
    except Exception as e:
        logger.error(f"[Error] ES 清理失败: {e}")

    # 3. 清理 Redis (对话缓存 & RAG缓存)
    try:
        import redis
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)
        r.flushdb()
        logger.info("[Success] Redis 缓存已清空")
    except Exception as e:
        logger.error(f"[Error] Redis 清理失败: {e}")

    logger.info("数据清理完成！现在可以运行 import 脚本重新导入了。")

if __name__ == "__main__":
    clean_all()
