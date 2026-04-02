import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "EMPTY")
    GEMINI_BASE_URL: str = os.getenv("GEMINI_BASE_URL", "http://localhost:8900/v1")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "qwen2.5-72b-awq")
    
    # 阿里云 DashScope API Key，用于 Qwen-VL 图片解析
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")

    EMBEDDING_MODEL_PATH: str = os.getenv("EMBEDDING_MODEL_PATH", "/datadisk/home/lsr/.cache/huggingface/hub/models--BAAI--bge-large-zh-v1.5/snapshots/79e7739b6ab944e86d6171e44d24c997fc1e0116")

    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3307"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "ecommerce123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "ecommerce")

    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6381"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "1"))
    REDIS_SESSION_TTL: int = int(os.getenv("REDIS_SESSION_TTL", "3600"))
    MEMORY_WINDOW_SIZE: int = int(os.getenv("MEMORY_WINDOW_SIZE", "10"))

    CHROMA_HOST: str = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8001"))

    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_INDEX: str = os.getenv("ES_INDEX", "ecommerce_kb")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
