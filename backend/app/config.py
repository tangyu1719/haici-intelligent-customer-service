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

    # ── 网关路由（/ src/agent/config.json） ──
    GATEWAY_PROVIDER: str = os.getenv("GATEWAY_PROVIDER", "ark")
    GATEWAY_ROUTE_MODE: str = os.getenv("GATEWAY_ROUTE_MODE", "task_type")
    GATEWAY_TASK_TYPE_ROUTE: str = os.getenv("GATEWAY_TASK_TYPE_ROUTE", "")
    LLM_GATEWAY_CONFIG: str = os.getenv("LLM_GATEWAY_CONFIG", "../src/agent/config.json")

    # 兼容旧版单接入点
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-turbo")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

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
    # 本地持久化 Chroma（无 Docker / hnswlib 编译环境时使用）
    CHROMA_PERSIST_PATH: str = os.getenv("CHROMA_PERSIST_PATH", "")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    USER_NO_HASH_SECRET: str = os.getenv("USER_NO_HASH_SECRET", "")

    DAILY_QUESTION_LIMIT: int = int(os.getenv("DAILY_QUESTION_LIMIT", "100"))
    # 管理员每日上限；0 表示不限次（仍会计数）
    DAILY_QUESTION_LIMIT_ADMIN: int = int(os.getenv("DAILY_QUESTION_LIMIT_ADMIN", "0"))
    MAX_QUESTION_LENGTH: int = int(os.getenv("MAX_QUESTION_LENGTH", "500"))
    # 模型上下文窗口（字符级预算，可按接入点 max_tokens 换算调整）
    CHAT_MAX_CONTEXT_CHARS: int = int(os.getenv("CHAT_MAX_CONTEXT_CHARS", str(256 * 1024)))
    CHAT_CONTEXT_RESERVE_CHARS: int = int(os.getenv("CHAT_CONTEXT_RESERVE_CHARS", "32768"))
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "3"))
    # 粗筛大池：单路向量召回上限（如 100），精筛后再自适应落 10/8/5/3
    RAG_COARSE_POOL_K: int = int(os.getenv("RAG_COARSE_POOL_K", "100"))
    # 兼容旧名：未设 RAG_COARSE_POOL_K 时 retrieve 单路 fallback
    RAG_COARSE_TOP_K: int = int(os.getenv("RAG_COARSE_TOP_K", os.getenv("RAG_COARSE_POOL_K", "100")))
    # 精筛落档梯度：粗筛池大且分数高→高档；池小或分数分散→低档
    RAG_GRADIENT_K: str = os.getenv("RAG_GRADIENT_K", "10,8,5,3")
    RAG_SCORE_THRESHOLD: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.65"))
    # 精筛「高质量簇」判定：top 与多数片段 hybrid 分均高于此阈值时可顶格落档
    RAG_HIGH_SCORE_THRESHOLD: float = float(os.getenv("RAG_HIGH_SCORE_THRESHOLD", "0.65"))
    # 相邻片段分差超过此值视为断层，在精筛阶段截断
    RAG_SCORE_GAP_THRESHOLD: float = float(os.getenv("RAG_SCORE_GAP_THRESHOLD", "0.12"))
    # 精筛 BM25 混合权重（0=纯向量，0.3=向量0.7+BM25 0.3）
    RAG_BM25_WEIGHT: float = float(os.getenv("RAG_BM25_WEIGHT", "0.3"))
    RAG_HYBRID_ENABLED: bool = os.getenv("RAG_HYBRID_ENABLED", "true").lower() in ("1", "true", "yes")
    CHAT_HISTORY_TURNS: int = int(os.getenv("CHAT_HISTORY_TURNS", "50"))
    # 上下文摘要：占比达阈值或轮数超滑动窗口时触发
    CHAT_SUMMARY_THRESHOLD_RATIO: float = float(os.getenv("CHAT_SUMMARY_THRESHOLD_RATIO", "0.8"))
    CHAT_SLIDING_WINDOW_TURNS: int = int(os.getenv("CHAT_SLIDING_WINDOW_TURNS", "10"))
    CHAT_AUTO_SUMMARY_ENABLED: bool = os.getenv("CHAT_AUTO_SUMMARY_ENABLED", "true").lower() in ("1", "true", "yes")
    CHAT_SESSION_MAX_MESSAGES: int = int(os.getenv("CHAT_SESSION_MAX_MESSAGES", "200"))
    USER_PROFILE_DIR: str = os.getenv("USER_PROFILE_DIR", "./data/user_profiles")

    # ── 知识库分块（slice_method） ──
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
    # PDF 流程图：auto=线框/文本启发式命中走 flowchart_service；always=一律走；never=仅 MinerU 文本
    PDF_FLOWCHART_PIPELINE: str = os.getenv("PDF_FLOWCHART_PIPELINE", "auto")
    PDF_FLOWCHART_SKIP_LLM: bool = os.getenv("PDF_FLOWCHART_SKIP_LLM", "true").lower() in ("1", "true", "yes")
    # 图片 OCR/VLM 并行（API 调用为主，适度并发可显著缩短标准化耗时）
    IMAGE_PROCESS_PARALLEL: bool = os.getenv("IMAGE_PROCESS_PARALLEL", "true").lower() in ("1", "true", "yes")
    # ── Ollama 本地模型(用于意图识别/Query 改写加速) ──
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2:0.5b")
    # 预处理：Ollama 失败后是否再尝试网关大模型（Greedy JSON）；再失败才规则降级
    PIPELINE_GATEWAY_LLM_FALLBACK: bool = os.getenv(
        "PIPELINE_GATEWAY_LLM_FALLBACK", "true"
    ).lower() in ("1", "true", "yes")
    # 硬编码术语表映射（term_dictionary.py）；默认关闭，需结合业务树形分层后显式开启
    TERM_MAPPING_ENABLED: bool = os.getenv("TERM_MAPPING_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    IMAGE_PROCESS_WORKERS: int = int(os.getenv("IMAGE_PROCESS_WORKERS", "4"))
    # 默认关闭类型分类 VLM，每张图少一次网关调用（UI 手册场景收益大）
    IMAGE_CLASSIFY_ENABLED: bool = os.getenv("IMAGE_CLASSIFY_ENABLED", "false").lower() in ("1", "true", "yes")

    # ── 大规模上下文防稀释 (PRD 加分项5) ──
    ANTI_DILUTION_ENABLED: bool = os.getenv("ANTI_DILUTION_ENABLED", "true").lower() in ("1", "true", "yes")
    ANTI_DILUTION_THRESHOLD: int = int(os.getenv("ANTI_DILUTION_THRESHOLD", "8"))
    ANTI_DILUTION_MAX_GROUPS: int = int(os.getenv("ANTI_DILUTION_MAX_GROUPS", "5"))

    # ── ReAct + RAG Tool Calling（复杂多步问答，默认关闭，走简单 RAG；后续可 REACT_ENABLED=true 开启） ──
    REACT_ENABLED: bool = os.getenv("REACT_ENABLED", "false").lower() in ("1", "true", "yes")
    REACT_MAX_STEPS: int = int(os.getenv("REACT_MAX_STEPS", "3"))
    REACT_MAX_RAG_CALLS: int = int(os.getenv("REACT_MAX_RAG_CALLS", "3"))

    # 反馈看板：无真实数据时返回标注 demo_mode 的演示统计（默认开启，便于联调 UI）
    FEEDBACK_DEMO_FALLBACK: bool = os.getenv("FEEDBACK_DEMO_FALLBACK", "true").lower() in ("1", "true", "yes")

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:8010,http://127.0.0.1:5173,http://localhost:5173",
    )

    FALLBACK_NO_CONTEXT: str = os.getenv("FALLBACK_NO_CONTEXT", "") or (
        "非常抱歉，我目前的知识库中暂时没有找到与您问题直接相关的信息，无法为您提供准确的回答。\n\n"
        "🔍 建议您尝试以下方式：\n"
        "1. 换一种更简洁的表述方式重新提问\n"
        "2. 检查问题中的关键信息是否准确（如产品名、功能名等）\n"
        "3. 联系我们的专业人工客服团队获取一对一帮助\n\n"
        "💡 温馨提示：我们的知识库正在持续更新中，未来可能会覆盖更多您关心的话题。\n"
        "如需紧急帮助，请拨打客服热线或发送邮件至 support@haici.com。"
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
