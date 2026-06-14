"""平台健康检查（对齐 web_rebuild /api/platform/health 响应形态）。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.llms import _openai_chat_url
from app.services.llm_gateway import get_llm_gateway

logger = logging.getLogger(__name__)

HealthItem = dict[str, Any]


def _status_bucket(status: str) -> str:
    return status if status in ("ok", "warn", "error") else "error"


def _probe_mysql() -> HealthItem:
    t0 = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "id": "mysql",
            "label": "MySQL",
            "status": "ok",
            "latency_ms": ms,
            "detail": {"host": settings.MYSQL_HOST, "port": settings.MYSQL_PORT, "db": settings.MYSQL_DATABASE},
        }
    except Exception as exc:
        return {
            "id": "mysql",
            "label": "MySQL",
            "status": "error",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc)[:200],
        }


def _probe_chroma() -> HealthItem:
    t0 = time.perf_counter()
    try:
        import chromadb

        client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        hb = client.heartbeat()
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "id": "chroma",
            "label": "Chroma 向量库",
            "status": "ok",
            "latency_ms": ms,
            "detail": {"host": settings.CHROMA_HOST, "port": settings.CHROMA_PORT, "heartbeat": hb},
        }
    except Exception as exc:
        return {
            "id": "chroma",
            "label": "Chroma 向量库",
            "status": "warn",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc)[:200],
            "detail": {"hint": "RAG 将降级为空检索，对话仍可用"},
        }


def _probe_llm_gateway() -> HealthItem:
    t0 = time.perf_counter()
    node = get_llm_gateway().choose("qa")
    if not node or not (node.api_key or "").strip():
        return {
            "id": "llm_gateway",
            "label": "LLM 网关",
            "status": "error",
            "error": "未配置可用 API Key（ARK_API_KEY / QWEN_API_KEY）",
            "settings_href": "/profile",
        }
    url = _openai_chat_url(node.base_url)
    headers = {"Authorization": f"Bearer {node.api_key}", "Content-Type": "application/json"}
    payload = {
        "model": node.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=min(12, settings.LLM_TIMEOUT_SECONDS), trust_env=False) as client:
            resp = client.post(url, headers=headers, json=payload)
        ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            return {
                "id": "llm_gateway",
                "label": "LLM 网关",
                "status": "error",
                "latency_ms": ms,
                "error": f"HTTP {resp.status_code}: {resp.text[:160]}",
                "detail": {"provider": node.provider, "name": node.name, "model": node.model},
            }
        return {
            "id": "llm_gateway",
            "label": "LLM 网关",
            "status": "ok",
            "latency_ms": ms,
            "detail": {"provider": node.provider, "name": node.name, "model": node.model},
        }
    except Exception as exc:
        return {
            "id": "llm_gateway",
            "label": "LLM 网关",
            "status": "error",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc)[:200],
            "detail": {"provider": node.provider, "name": node.name, "model": node.model},
        }


def _probe_embedding() -> HealthItem:
    t0 = time.perf_counter()
    path_raw = (settings.EMBEDDING_MODEL_PATH or "").strip()
    if path_raw:
        p = Path(path_raw)
        if not p.is_absolute():
            p = (Path(__file__).resolve().parents[2] / path_raw).resolve()
        if p.exists():
            return {
                "id": "embedding",
                "label": "嵌入模型",
                "status": "ok",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "detail": {"path": str(p), "model": settings.EMBEDDING_MODEL},
            }
        return {
            "id": "embedding",
            "label": "嵌入模型",
            "status": "warn",
            "error": f"本地模型路径不存在: {p}",
            "detail": {"model": settings.EMBEDDING_MODEL},
        }
    return {
        "id": "embedding",
        "label": "嵌入模型",
        "status": "warn",
        "error": "未配置 EMBEDDING_MODEL_PATH，首次检索可能较慢",
        "detail": {"model": settings.EMBEDDING_MODEL},
    }


def run_platform_health(*, probe_llm: bool = True) -> dict[str, Any]:
    """执行依赖探测并返回 web_rebuild 兼容结构。"""
    items: list[HealthItem] = [
        _probe_mysql(),
        _probe_chroma(),
        _probe_embedding(),
    ]
    if probe_llm:
        items.append(_probe_llm_gateway())

    summary = {"ok": 0, "warn": 0, "error": 0}
    for it in items:
        st = _status_bucket(str(it.get("status") or "error"))
        summary[st] = summary.get(st, 0) + 1

    all_ok = summary["error"] == 0
    logger.info(
        "[智能客服-运维|platform_health|探测|硬编执行|完成] ok=%s; warn=%s; error=%s",
        summary["ok"],
        summary["warn"],
        summary["error"],
    )
    return {
        "ready": True,
        "all_ok": all_ok,
        "summary": summary,
        "items": items,
    }
