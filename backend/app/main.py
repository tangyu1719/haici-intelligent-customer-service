import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import (
    admin_chat_faq,
    admin_eval,
    admin_feedback,
    admin_logs,
    admin_rbac,
    admin_sessions,
    admin_system,
    admin_user_profiles,
    agent_settings,
    auth,
    chat,
    feedback,
    knowledge,
    knowledge_base,
    multimodal,
    multimodal_tasks,
    sessions,
    structured_processing,
    system,
    user_profiles,
)
from app.auth.bootstrap import ensure_auth_ready
from app.middleware.audit_middleware import AuditCasbinMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
settings.ensure_dirs()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
SERVE_FRONTEND_DIR = FRONTEND_DIST if FRONTEND_DIST.exists() else FRONTEND_DIR

app = FastAPI(title="HaiCi 智能客服 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuditCasbinMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin_logs.router, prefix="/api/v1")
app.include_router(admin_feedback.router, prefix="/api/v1")
app.include_router(admin_sessions.router, prefix="/api/v1")
app.include_router(admin_eval.router, prefix="/api/v1")
app.include_router(admin_rbac.router, prefix="/api/v1")
app.include_router(admin_system.router, prefix="/api/v1")
app.include_router(admin_user_profiles.router, prefix="/api/v1")
app.include_router(user_profiles.router, prefix="/api/v1")
app.include_router(admin_chat_faq.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(knowledge_base.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(agent_settings.router, prefix="/api/v1")
app.include_router(multimodal.router, prefix="/api/v1")
app.include_router(multimodal_tasks.router, prefix="/api/v1")
app.include_router(structured_processing.router, prefix="/api/v1")

_OUTPUT_DIR = PROJECT_ROOT / "output"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_OUTPUT_DIR)), name="output")


@app.on_event("startup")
def on_startup() -> None:
    from app.database import engine
    from app.services.sql_trace import register_sql_listeners

    _log = logging.getLogger(__name__)
    register_sql_listeners(engine)
    ensure_auth_ready()

    # 启动时同步预加载 BGE，避免首条 RAG 请求冷启动超时
    try:
        from app.llms import get_embedder
        _log.info("[启动预加载|main.on_startup|BGE|硬编执行|开始] 嵌入模型加载中")
        get_embedder()
        _log.info("[启动预加载|main.on_startup|BGE|硬编执行|完成] 嵌入模型就绪")
    except Exception as exc:
        _log.warning(
            "[启动预加载|main.on_startup|BGE|硬编执行|失败] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:120],
        )

if SERVE_FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(SERVE_FRONTEND_DIR / "assets"), check_dir=False), name="assets")


@app.get("/")
async def serve_frontend():
    index = SERVE_FRONTEND_DIR / "index.html"
    if not index.exists():
        index = FRONTEND_DIR / "index.html"
    return FileResponse(str(index))


@app.get("/health")
def health():
    return {"status": "ok"}
