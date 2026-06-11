import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM（OpenAI 兼容：通义 / OpenAI / Ollama）
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", os.getenv("GEMINI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("GEMINI_MODEL", "qwen-turbo"))
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3307"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "ecommerce123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "haici_cs")

    CHROMA_HOST: str = os.getenv("CHROMA_HOST", "127.0.0.1")
    CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8001"))

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    DAILY_QUESTION_LIMIT: int = int(os.getenv("DAILY_QUESTION_LIMIT", "100"))
    MAX_QUESTION_LENGTH: int = int(os.getenv("MAX_QUESTION_LENGTH", "500"))
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "4"))
    RAG_SCORE_THRESHOLD: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.35"))
    CHAT_HISTORY_TURNS: int = int(os.getenv("CHAT_HISTORY_TURNS", "5"))

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")

    FALLBACK_NO_CONTEXT: str = (
        "抱歉，我在知识库中没有找到与您问题相关的信息，无法为您提供准确回答。"
        "请尝试换种问法，或联系人工客服。"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]

    def ensure_dirs(self) -> None:
        Path(self.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


settings = Settings()
