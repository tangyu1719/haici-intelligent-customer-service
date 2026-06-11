import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import auth, chat, feedback, knowledge, sessions

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

app.include_router(auth.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")

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
