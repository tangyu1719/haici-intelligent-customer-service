"""SQLAlchemy SQL 采集：对齐 WMS dw_log_operation_sql（cmdStatement / cmdParameters / cmdSeq）。"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.database import SessionLocal
from app.models import SysLogOperationSql
from app.services.http_log_body import clip_text, extract_table_from_sql

logger = logging.getLogger(__name__)

# 日志表自身写入不采集，避免递归
_SKIP_TABLE_MARKERS = (
    "sys_log_operation",
    "sys_log_error",
    "sys_log_api_call",
    "sys_log_schedule",
    "sys_log_operation_sql",
    "casbin_rule",
)

_capture_active: ContextVar[bool] = ContextVar("sql_capture_active", default=False)
_sql_buffer: ContextVar[list["_PendingSql"] | None] = ContextVar("sql_buffer", default=None)
_cmd_seq: ContextVar[int] = ContextVar("sql_cmd_seq", default=0)


@dataclass
class _PendingSql:
    cmd_seq: int
    cmd_statement: str
    cmd_parameters: str
    cmd_table: str


def begin_sql_capture() -> None:
    """在 HTTP 请求进入业务逻辑前开启 SQL 缓冲。"""
    _capture_active.set(True)
    _sql_buffer.set([])
    _cmd_seq.set(0)


def end_sql_capture() -> None:
    _capture_active.set(False)
    _sql_buffer.set(None)
    _cmd_seq.set(0)


def _should_skip_statement(statement: str) -> bool:
    lower = (statement or "").lower()
    return any(marker in lower for marker in _SKIP_TABLE_MARKERS)


def _format_parameters(parameters: Any) -> str:
    if parameters is None:
        return ""
    try:
        if isinstance(parameters, dict):
            return clip_text(json.dumps(parameters, ensure_ascii=False, default=str), limit=8000)
        if isinstance(parameters, (list, tuple)):
            return clip_text(json.dumps(list(parameters), ensure_ascii=False, default=str), limit=8000)
        return clip_text(str(parameters), limit=8000)
    except Exception:
        return clip_text(str(parameters), limit=8000)


def _append_sql(statement: str, parameters: Any) -> None:
    if not _capture_active.get():
        return
    stmt = (statement or "").strip()
    if not stmt or _should_skip_statement(stmt):
        return
    buf = _sql_buffer.get()
    if buf is None:
        return
    seq = _cmd_seq.get() + 1
    _cmd_seq.set(seq)
    buf.append(
        _PendingSql(
            cmd_seq=seq,
            cmd_statement=clip_text(stmt, limit=16000),
            cmd_parameters=_format_parameters(parameters),
            cmd_table=extract_table_from_sql(stmt),
        )
    )


def persist_sql_for_operation(operation_log_id: int, *, log_type: int = 1, trace_id: str = "") -> int:
    """将本次请求缓冲的 SQL 写入 sys_log_operation_sql（关联 operation_log_id）。"""
    buf = _sql_buffer.get() or []
    if not buf:
        return 0
    db = SessionLocal()
    try:
        for item in buf:
            db.add(
                SysLogOperationSql(
                    operation_log_id=operation_log_id,
                    log_type=log_type,
                    cmd_table=item.cmd_table,
                    cmd_statement=item.cmd_statement,
                    cmd_parameters=item.cmd_parameters,
                    cmd_seq=item.cmd_seq,
                    trace_id=trace_id or "",
                )
            )
        db.commit()
        count = len(buf)
        logger.debug(
            "[登录模块-运维日志|sql_trace|persist|硬编执行|完成] operation_log_id=%s; count=%s",
            operation_log_id,
            count,
        )
        return count
    except Exception as exc:
        logger.warning(
            "[登录模块-运维日志|sql_trace|persist|硬编执行|失败] operation_log_id=%s; err=%s",
            operation_log_id,
            str(exc)[:200],
        )
        db.rollback()
        return 0
    finally:
        db.close()


def list_sql_by_operation_log_id(operation_log_id: int) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(SysLogOperationSql)
            .filter(SysLogOperationSql.operation_log_id == operation_log_id)
            .order_by(SysLogOperationSql.cmd_seq.asc())
            .all()
        )
        return [
            {
                "log_id": r.log_id,
                "operation_log_id": r.operation_log_id,
                "log_type": r.log_type,
                "cmd_table": r.cmd_table,
                "cmd_statement": r.cmd_statement,
                "cmd_parameters": r.cmd_parameters,
                "cmd_seq": r.cmd_seq,
                "trace_id": r.trace_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def register_sql_listeners(engine: Engine) -> None:
    """注册 SQLAlchemy 全局 cursor 事件（幂等）。"""

    if getattr(engine, "_hc_sql_trace_registered", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        _append_sql(statement, parameters)

    engine._hc_sql_trace_registered = True  # type: ignore[attr-defined]
    logger.info("[登录模块-运维日志|sql_trace|register|硬编执行|完成] SQLAlchemy 采集已挂载")
