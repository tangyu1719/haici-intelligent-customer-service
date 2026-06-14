"""Agent 专链 API 调用日志（LLM / RAG / 工具 / MCP / 嵌入）。"""
from __future__ import annotations

import functools
import json
import logging
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from app.services.audit_log import write_api_call_log

logger = logging.getLogger(__name__)

_trace_id: ContextVar[str] = ContextVar("agent_trace_id", default="")
_user_id: ContextVar[int | None] = ContextVar("agent_user_id", default=None)
_chain: ContextVar[str] = ContextVar("agent_chain", default="")

AGENT_API_TYPES = ("llm", "rag", "tool", "mcp", "embedding")


def set_agent_trace(trace_id: str = "", user_id: int | None = None) -> str:
    tid = trace_id or uuid.uuid4().hex[:16]
    _trace_id.set(tid)
    if user_id is not None:
        _user_id.set(user_id)
    return tid


def get_agent_trace() -> str:
    return _trace_id.get() or ""


def set_agent_chain(chain: str) -> None:
    _chain.set(chain or "")


def get_agent_chain() -> str:
    return _chain.get() or ""


def _default_request_fn(args: tuple, kwargs: dict) -> str:
    for key in ("query", "text", "prompt", "question", "rag_query"):
        if key in kwargs and kwargs[key]:
            return str(kwargs[key])[:500]
    if args:
        return str(args[0])[:500]
    return ""


def log_agent_call(
    *,
    api_type: str,
    target: str,
    method: str = "POST",
    request_summary: str = "",
    response_summary: str = "",
    status_code: int = 200,
    time_consume_ms: int = 0,
    success: bool = True,
    error_message: str = "",
    user_id: int | None = None,
    tokens: int | None = None,
    extra: dict | None = None,
) -> None:
    if api_type not in AGENT_API_TYPES:
        api_type = "tool"
    meta = dict(extra or {})
    chain = get_agent_chain()
    if chain and "chain" not in meta:
        meta["chain"] = chain
    if tokens is not None:
        meta["tokens"] = tokens
    resp = response_summary
    if meta:
        try:
            base = json.loads(response_summary) if response_summary.startswith("{") else {}
            if isinstance(base, dict):
                base.update(meta)
                resp = json.dumps(base, ensure_ascii=False)
            else:
                resp = json.dumps({"text": response_summary, **meta}, ensure_ascii=False)
        except Exception:
            resp = json.dumps({"text": response_summary, **meta}, ensure_ascii=False)
    try:
        write_api_call_log(
            trace_id=get_agent_trace() or uuid.uuid4().hex[:16],
            api_type=api_type,
            target_url=target[:512],
            method=method,
            request_summary=request_summary[:2000],
            response_summary=resp[:2000],
            status_code=status_code,
            time_consume_ms=time_consume_ms,
            success=1 if success else 0,
            error_message=error_message[:1000],
            user_id=user_id if user_id is not None else _user_id.get(),
        )
    except Exception as exc:
        logger.warning("[运维评测-EVAL|agent_call_logger|写入|硬编执行|失败] api_type=%s; err=%s", api_type, str(exc)[:120])


def log_rag_conversation(
    *,
    trace_id: str = "",
    user_id: int | None = None,
    question: str = "",
    intent: str = "",
    intent_label: str = "",
    rewritten_query: str = "",
    rag_query: str = "",
    keywords: list[str] | None = None,
    retrieval_terms: list[str] | None = None,
    citations_count: int = 0,
    top_score: float = 0.0,
    anti_dilution: bool = False,
    kb_id: int | None = None,
    auto_routed: bool = False,
    llm_provider: str = "",
    llm_model: str = "",
    llm_task_type: str = "",
    answer_length: int = 0,
    follow_ups: list[str] | None = None,
    follow_ups_count: int = 0,
    total_tokens: int = 0,
    time_consume_ms: int = 0,
    success: bool = True,
    error_message: str = "",
) -> None:
    """记录一次完整的 RAG 对话指标（异步写入，不阻塞 SSE）。"""
    import threading

    def _write() -> None:
        try:
            meta = {
                "question": question[:500],
                "intent": intent,
                "intent_label": intent_label,
                "rewritten_query": rewritten_query[:500],
                "rag_query": rag_query[:500],
                "keywords": keywords or [],
                "retrieval_terms": retrieval_terms or [],
                "citations_count": citations_count,
                "top_score": round(top_score, 4),
                "anti_dilution": anti_dilution,
                "kb_id": kb_id,
                "auto_routed": auto_routed,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "llm_task_type": llm_task_type,
                "answer_length": answer_length,
                "follow_ups": follow_ups or [],
                "follow_ups_count": follow_ups_count,
                "total_tokens": total_tokens,
            }
            log_agent_call(
                api_type="rag",
                target=f"chat/stream?session={trace_id[:8]}",
                request_summary=question[:1000],
                response_summary=json.dumps(meta, ensure_ascii=False),
                status_code=200 if success else 500,
                time_consume_ms=time_consume_ms,
                success=success,
                error_message=error_message[:500],
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("[RAG指标|agent_call_logger|异步写入|失败] %s", str(exc)[:120])

    threading.Thread(target=_write, daemon=True).start()


def track_agent_call(
    *,
    api_type: str,
    target: str | Callable[[tuple, dict], str] = "",
    tool_name: str = "",
    method: str = "POST",
    request_fn: Callable[[tuple, dict], str] | None = None,
    response_fn: Callable[[Any], str] | None = None,
    extra_fn: Callable[[Any, tuple, dict], dict] | None = None,
):
    """装饰器：拦截 Agent 编排链路中的 RAG/LLM/嵌入等调用并写入 EVAL 指标。"""

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            req = (request_fn or _default_request_fn)(args, kwargs)
            tgt = target(args, kwargs) if callable(target) else (target or fn.__qualname__)
            base_extra: dict[str, Any] = {}
            if tool_name:
                base_extra["tool_name"] = tool_name
            try:
                result = fn(*args, **kwargs)
                elapsed = int((time.perf_counter() - t0) * 1000)
                extra = dict(base_extra)
                if extra_fn:
                    extra.update(extra_fn(result, args, kwargs) or {})
                resp = (response_fn(result) if response_fn else "")[:500]
                log_agent_call(
                    api_type=api_type,
                    target=tgt,
                    method=method,
                    request_summary=req,
                    response_summary=resp,
                    time_consume_ms=elapsed,
                    success=True,
                    extra=extra or None,
                )
                return result
            except Exception as exc:
                elapsed = int((time.perf_counter() - t0) * 1000)
                log_agent_call(
                    api_type=api_type,
                    target=tgt,
                    method=method,
                    request_summary=req,
                    response_summary="",
                    time_consume_ms=elapsed,
                    success=False,
                    error_message=str(exc)[:300],
                    extra=base_extra or None,
                )
                raise

        return wrapper

    return decorator


class AgentCallTimer:
    def __init__(self) -> None:
        self.start = time.perf_counter()
        self.elapsed_ms = 0

    def __enter__(self) -> "AgentCallTimer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self.elapsed_ms = int((time.perf_counter() - self.start) * 1000)
