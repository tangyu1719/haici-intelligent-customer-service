"""嵌入模型加载：优先使用上级项目本地 BGE 快照，离线加载。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 上级项目 knowledge_base 默认缓存目录（与 kb_manager_fast.py 一致）
DEFAULT_KB_MODELS_DIR = (
    settings.project_root.parent / "src" / "agent" / "knowledge_base" / "models"
).resolve()

HUB_FOLDERS = (
    "models--BAAI--bge-large-zh-v1.5",
    "models--BAAI--bge-small-zh-v1.5",
    "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2",
)


def _resolve_hub_snapshot(cache_dir: Path, hub_folder: str) -> Path | None:
    base = cache_dir / hub_folder / "snapshots"
    if not base.is_dir():
        return None
    for name in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if name.is_dir() and (name / "config.json").is_file():
            return name
    return None


def resolve_embedding_model_path() -> Path | None:
    """解析本地嵌入模型目录（须含 config.json）。"""
    candidates: list[str] = [
        settings.EMBEDDING_MODEL_PATH,
        os.getenv("SBA_BGE_SNAPSHOT_PATH", ""),
    ]
    for raw in candidates:
        text = (raw or "").strip()
        if not text:
            continue
        p = Path(text)
        if not p.is_absolute():
            p = (settings.project_root / p).resolve()
        if (p / "config.json").is_file():
            return p

    search_dirs = [DEFAULT_KB_MODELS_DIR]
    extra = (settings.EMBEDDING_MODEL_CACHE_DIR or "").strip()
    if extra:
        p = Path(extra)
        if not p.is_absolute():
            p = (settings.project_root / p).resolve()
        search_dirs.insert(0, p)

    for cache_dir in search_dirs:
        if not cache_dir.is_dir():
            continue
        for hub in HUB_FOLDERS:
            snap = _resolve_hub_snapshot(cache_dir, hub)
            if snap:
                return snap
    return None


def load_embedder():
    """加载 HuggingFace 嵌入器；有本地快照时强制离线。"""
    snap = resolve_embedding_model_path()
    model_name = settings.EMBEDDING_MODEL
    load_target = str(snap) if snap else model_name

    if snap:
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        logger.info(
            "[智能客服-RAG|embedding_loader|BGE|硬编执行|离线加载] 使用本地快照; path=%s",
            snap,
        )
    else:
        logger.warning(
            "[智能客服-RAG|embedding_loader|BGE|硬编执行|在线加载] 未找到本地快照，将尝试下载; model=%s",
            model_name,
        )

    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings

    kwargs: dict = {
        "model_kwargs": {"device": "cpu"},
        "encode_kwargs": {"normalize_embeddings": True},
    }
    if snap:
        kwargs["model_kwargs"]["local_files_only"] = True

    return HuggingFaceEmbeddings(model_name=load_target, **kwargs)
