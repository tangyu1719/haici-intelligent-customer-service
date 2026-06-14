"""运维四类日志写入。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SysLogApiCall, SysLogError, SysLogOperation

logger = logging.getLogger(__name__)

MAX_BODY = 2000


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def _clip(text: str | None, limit: int = MAX_BODY) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "…"


def write_operation_log(
    *,
    operate_no: str,
    user_id: int | None,
    user_no: str | None,
    module: str,
    menu_permission: str,
    url: str,
    method: str,
    input_value: str,
    return_value: str,
    client_ip: str,
    time_consume_ms: int,
    status: int,
    trace_id: str,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            SysLogOperation(
                operate_no=operate_no,
                user_id=user_id,
                user_no=user_no,
                module=module,
                menu_permission=menu_permission,
                url=url,
                method=method,
                input_value=_clip(input_value),
                return_value=_clip(return_value),
                client_ip=client_ip,
                time_consume_ms=time_consume_ms,
                status=status,
                trace_id=trace_id,
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("[登录模块-运维日志|audit_log|操作日志|硬编执行|失败] err=%s", exc)
        db.rollback()
    finally:
        db.close()


def write_error_log(
    *,
    operate_no: str,
    error_type: int,
    url: str,
    module: str,
    error_message: str,
    trace_id: str,
    client_ip: str,
    input_value: str = "",
) -> None:
    db = SessionLocal()
    try:
        db.add(
            SysLogError(
                operate_no=operate_no,
                error_type=error_type,
                url=url,
                module=module,
                error_message=_clip(error_message, 4000),
                trace_id=trace_id,
                client_ip=client_ip,
                input_value=_clip(input_value),
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("[登录模块-运维日志|audit_log|异常日志|硬编执行|失败] err=%s", exc)
        db.rollback()
    finally:
        db.close()


def write_api_call_log(
    *,
    trace_id: str,
    api_type: str,
    target_url: str,
    method: str,
    request_summary: str,
    response_summary: str,
    status_code: int,
    time_consume_ms: int,
    success: int,
    error_message: str = "",
    user_id: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            SysLogApiCall(
                trace_id=trace_id,
                api_type=api_type,
                target_url=target_url,
                method=method,
                request_summary=_clip(request_summary),
                response_summary=_clip(response_summary),
                status_code=status_code,
                time_consume_ms=time_consume_ms,
                success=success,
                error_message=_clip(error_message, 1000),
                user_id=user_id,
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("[登录模块-运维日志|audit_log|API调用日志|硬编执行|失败] err=%s", exc)
        db.rollback()
    finally:
        db.close()


def module_from_path(path: str) -> str:
    parts = path.strip("/").split("/")
    if len(parts) >= 3:
        return parts[2]
    return "system"


def permission_from_path(path: str) -> str:
    mapping = {
        "auth": "profile:view",
        "chat": "chat:view",
        "sessions": "session:view",
        "knowledge": "kb:view",
        "feedback": "chat:feedback",
        "admin": "system:log:operation",
        "system": "chat:view",
    }
    mod = module_from_path(path)
    return mapping.get(mod, "")


def serialize_body(body: bytes | None) -> str:
    if not body:
        return ""
    try:
        text = body.decode("utf-8", errors="replace")
        json.loads(text)
        return text
    except Exception:
        return "<binary>"
