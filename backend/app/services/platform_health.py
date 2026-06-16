"""平台健康检查（/api/platform/health 响应形态）。"""

from __future__ import annotations

import logging
import os
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
    try:
        from app.embedding_loader import resolve_embedding_model_path
        snap = resolve_embedding_model_path()
        ms = int((time.perf_counter() - t0) * 1000)
        if snap and snap.is_dir():
            return {
                "id": "embedding", "label": "嵌入模型", "status": "ok",
                "latency_ms": ms, "detail": {"path": str(snap), "model": settings.EMBEDDING_MODEL},
            }
        return {
            "id": "embedding", "label": "嵌入模型", "status": "warn",
            "latency_ms": ms, "error": "未找到本地模型快照", "detail": {"model": settings.EMBEDDING_MODEL},
        }
    except Exception as exc:
        return {
            "id": "embedding", "label": "嵌入模型", "status": "warn",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc)[:200], "detail": {"model": settings.EMBEDDING_MODEL},
        }


def _probe_ollama() -> HealthItem:
    """探测 Ollama 本地推理服务"""
    t0 = time.perf_counter()
    base = (os.getenv("OLLAMA_BASE_URL", "") or settings.OLLAMA_BASE_URL).strip()
    model = (os.getenv("OLLAMA_MODEL", "") or settings.OLLAMA_MODEL).strip()
    if not base:
        return {"id": "ollama", "label": "Ollama 本地", "status": "warn",
                "error": "未配置 OLLAMA_BASE_URL", "latency_ms": 0,
                "detail": {"hint": "意图识别将使用 API 网关", "settings_href": "/admin/pipeline"}}
    try:
        resp = httpx.get(base.replace("/v1", "") + "/api/tags", timeout=5.0)
        ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 200:
            models = [m.get("name", "?") for m in resp.json().get("models", [])]
            return {"id": "ollama", "label": "Ollama 本地", "status": "ok",
                    "latency_ms": ms,
                    "detail": {"url": base, "model": model, "installed": models}}
        return {"id": "ollama", "label": "Ollama 本地", "status": "warn",
                "latency_ms": ms, "error": f"HTTP {resp.status_code}",
                "detail": {"hint": "意图识别将使用 API 网关", "settings_href": "/admin/pipeline"}}
    except Exception as exc:
        return {"id": "ollama", "label": "Ollama 本地", "status": "warn",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "error": str(exc)[:120],
                "detail": {"hint": "意图识别将使用 API 网关", "settings_href": "/admin/pipeline"}}


def run_platform_health(*, probe_llm: bool = True) -> dict[str, Any]:
    """异步并发执行依赖探测，不阻塞主流程。"""
    import concurrent.futures

    probes = [
        ("mysql", _probe_mysql),
        ("chroma", _probe_chroma),
        ("embedding", _probe_embedding),
        ("ollama", _probe_ollama),
    ]
    if probe_llm:
        probes.append(("llm_gateway", _probe_llm_gateway))

    items: list[HealthItem] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(probes)) as pool:
        futures = {pool.submit(fn): name for name, fn in probes}
        for fut in concurrent.futures.as_completed(futures):
            try:
                items.append(fut.result())
            except Exception as exc:
                name = futures[fut]
                items.append({"id": name, "label": name, "status": "error", "error": str(exc)[:200]})

    summary = {"ok": 0, "warn": 0, "error": 0}
    for it in items:
        st = _status_bucket(str(it.get("status") or "error"))
        summary[st] = summary.get(st, 0) + 1

    all_ok = summary["error"] == 0
    logger.info(
        "[智能客服-运维|platform_health|探测|硬编执行|完成] ok=%s; warn=%s; error=%s",
        summary["ok"], summary["warn"], summary["error"],
    )
    return {"ready": True, "all_ok": all_ok, "summary": summary, "items": items}
