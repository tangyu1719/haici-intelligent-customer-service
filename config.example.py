import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "sk-jLHY9FFKlEwpBtZ7cOHtofdpomr254dOviV1IYKDXbJv2pev")
    GEMINI_BASE_URL: str = os.getenv("GEMINI_BASE_URL", "https://147ai.com")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "sk-b9f969f375024b7d932946826d19583f")
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "mysql")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "ecommerce123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "ecommerce")
    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "1"))
    REDIS_SESSION_TTL: int = int(os.getenv("REDIS_SESSION_TTL", "3600"))
    MEMORY_WINDOW_SIZE: int = int(os.getenv("MEMORY_WINDOW_SIZE", "10"))
    CHROMA_HOST: str = os.getenv("CHROMA_HOST", "chroma")
    CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8000"))
    ES_HOST: str = os.getenv("ES_HOST", "http://elasticsearch:9200")
    ES_INDEX: str = os.getenv("ES_INDEX", "ecommerce_kb")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
