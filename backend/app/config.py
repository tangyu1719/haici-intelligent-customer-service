import json
import os
from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # ── 通义千问 DashScope（OpenAI 兼容） ──
    QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", os.getenv("LLM_API_KEY", "")))
    QWEN_BASE_URL: str = os.getenv(
        "QWEN_BASE_URL",
        os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    QWEN_MODEL: str = os.getenv("QWEN_MODEL", os.getenv("LLM_MODEL", "qwen-turbo"))

    # ── 火山方舟 ARK（OpenAI 兼容） ──
    ARK_API_KEY: str = os.getenv("ARK_API_KEY", os.getenv("VOLC_API_KEY", os.getenv("VOLCENGINE_API_KEY", "")))
    ARK_BASE_URL: str = os.getenv(
        "ARK_BASE_URL",
        os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
    )
    LLM_MODEL_QA: str = os.getenv("LLM_MODEL_QA", "")
    LLM_MODEL_REASON: str = os.getenv("LLM_MODEL_REASON", "")

    # ── 网关路由（对齐 web_rebuild_v2 / src/agent/config.json） ──
    GATEWAY_PROVIDER: str = os.getenv("GATEWAY_PROVIDER", "ark")
    GATEWAY_ROUTE_MODE: str = os.getenv("GATEWAY_ROUTE_MODE", "task_type")
    GATEWAY_TASK_TYPE_ROUTE: str = os.getenv("GATEWAY_TASK_TYPE_ROUTE", "")
    LLM_GATEWAY_CONFIG: str = os.getenv("LLM_GATEWAY_CONFIG", "../src/agent/config.json")

    # 兼容旧版单接入点
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-turbo")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

    # ── RAG 嵌入（对齐上级 kb_manager_fast：优先本地 BGE 快照） ──
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
    EMBEDDING_MODEL_PATH: str = os.getenv("EMBEDDING_MODEL_PATH", os.getenv("SBA_BGE_SNAPSHOT_PATH", ""))
    EMBEDDING_MODEL_CACHE_DIR: str = os.getenv(
        "EMBEDDING_MODEL_CACHE_DIR",
        "../src/agent/knowledge_base/models",
    )

    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3307"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "ecommerce123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "haici_cs")

    CHROMA_HOST: str = os.getenv("CHROMA_HOST", "127.0.0.1")
    CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8001"))

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    USER_NO_HASH_SECRET: str = os.getenv("USER_NO_HASH_SECRET", "")

    DAILY_QUESTION_LIMIT: int = int(os.getenv("DAILY_QUESTION_LIMIT", "100"))
    MAX_QUESTION_LENGTH: int = int(os.getenv("MAX_QUESTION_LENGTH", "500"))
    # 模型上下文窗口（字符级预算，可按接入点 max_tokens 换算调整）
    CHAT_MAX_CONTEXT_CHARS: int = int(os.getenv("CHAT_MAX_CONTEXT_CHARS", str(256 * 1024)))
    CHAT_CONTEXT_RESERVE_CHARS: int = int(os.getenv("CHAT_CONTEXT_RESERVE_CHARS", "32768"))
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "4"))
    RAG_SCORE_THRESHOLD: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.35"))
    CHAT_HISTORY_TURNS: int = int(os.getenv("CHAT_HISTORY_TURNS", "50"))

    # ── 知识库分块（对齐 web_rebuild slice_method） ──
    KB_DEFAULT_SLICE_METHOD: str = os.getenv("KB_DEFAULT_SLICE_METHOD", "auto")
    KB_CHUNK_SIZE: int = int(os.getenv("KB_CHUNK_SIZE", "500"))
    KB_CHUNK_OVERLAP: int = int(os.getenv("KB_CHUNK_OVERLAP", "80"))
    KB_CHUNK_MAX_TOKENS: int = int(os.getenv("KB_CHUNK_MAX_TOKENS", "350"))
    KB_DYNAMIC_MAX_CHARS: int = int(os.getenv("KB_DYNAMIC_MAX_CHARS", "800"))

    # ── 文档标准化 / 图片 OCR·VLM（对齐 SPEC-RAG文档标准化） ──
    BAIDU_OCR_ENABLED: bool = os.getenv("BAIDU_OCR_ENABLED", "true").lower() in ("1", "true", "yes")
    BAIDU_OCR_APP_ID: str = os.getenv("BAIDU_OCR_APP_ID", "")
    BAIDU_OCR_API_KEY: str = os.getenv("BAIDU_OCR_API_KEY", "")
    BAIDU_OCR_SECRET_KEY: str = os.getenv("BAIDU_OCR_SECRET_KEY", "")
    VLM_IMAGE_ENABLED: bool = os.getenv("VLM_IMAGE_ENABLED", "true").lower() in ("1", "true", "yes")
    MAX_IMAGES_PER_DOC: int = int(os.getenv("MAX_IMAGES_PER_DOC", "30"))
    KB_NORMALIZE_ENABLED: bool = os.getenv("KB_NORMALIZE_ENABLED", "true").lower() in ("1", "true", "yes")

    # ── 大规模上下文防稀释 (PRD 加分项5) ──
    ANTI_DILUTION_ENABLED: bool = os.getenv("ANTI_DILUTION_ENABLED", "true").lower() in ("1", "true", "yes")
    ANTI_DILUTION_THRESHOLD: int = int(os.getenv("ANTI_DILUTION_THRESHOLD", "8"))
    ANTI_DILUTION_MAX_GROUPS: int = int(os.getenv("ANTI_DILUTION_MAX_GROUPS", "5"))

    # 反馈看板：无真实数据时返回标注 demo_mode 的演示统计（默认开启，便于联调 UI）
    FEEDBACK_DEMO_FALLBACK: bool = os.getenv("FEEDBACK_DEMO_FALLBACK", "true").lower() in ("1", "true", "yes")

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:8010,http://127.0.0.1:5173,http://localhost:5173",
    )

    FALLBACK_NO_CONTEXT: str = (
        "抱歉，我在知识库中没有找到与您问题相关的信息，无法为您提供准确回答。"
        "请尝试换种问法，或联系人工客服。"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]

    @property
    def resolved_gateway_config_path(self) -> Path | None:
        raw = (self.LLM_GATEWAY_CONFIG or "").strip()
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        return p

    @property
    def gateway_task_type_route_map(self) -> dict[str, str]:
        if self.GATEWAY_TASK_TYPE_ROUTE.strip():
            try:
                data = json.loads(self.GATEWAY_TASK_TYPE_ROUTE)
                if isinstance(data, dict):
                    return {str(k).lower(): str(v) for k, v in data.items() if v}
            except json.JSONDecodeError:
                pass
        route: dict[str, str] = {}
        if self.LLM_MODEL_QA:
            route["qa"] = self.LLM_MODEL_QA
            route["chat"] = self.LLM_MODEL_QA
        if self.LLM_MODEL_REASON:
            route["summary"] = self.LLM_MODEL_REASON
            route["reason"] = self.LLM_MODEL_REASON
        return route

    def ensure_dirs(self) -> None:
        Path(self.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


settings = Settings()
