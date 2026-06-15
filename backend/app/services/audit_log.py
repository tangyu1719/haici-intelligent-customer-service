"""运维四类日志写入。"""

from __future__ import annotations

import json
import logging
import traceback
import uuid

from app.database import SessionLocal
from app.models import SysLogApiCall, SysLogError, SysLogOperation
from app.services.http_log_body import clip_text, mask_sensitive_json, pretty_json_text, serialize_http_body
from app.services.sql_trace import end_sql_capture, persist_sql_for_operation

logger = logging.getLogger(__name__)

MAX_BODY = 32_000


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def serialize_body(body: bytes | None, *, content_type: str = "") -> str:
    """兼容旧调用：请求体序列化。"""
    return serialize_http_body(body, content_type=content_type)


def format_log_body(text: str | None) -> str:
    if not text:
        return ""
    masked = mask_sensitive_json(text)
    return clip_text(pretty_json_text(masked) if masked.strip().startswith(("{", "[")) else masked)


def write_operation_log(
    *,
    operate_no: str,
    user_id: int | None,
    user_no: str | None,
    module: str,
    menu_permission: str,
    operate_desc: str = "",
    url: str,
    method: str,
    input_value: str,
    return_value: str,
    client_ip: str,
    time_consume_ms: int,
    status: int,
    trace_id: str,
) -> int | None:
    db = SessionLocal()
    try:
        row = SysLogOperation(
            operate_no=operate_no,
            user_id=user_id,
            user_no=user_no,
            module=module,
            menu_permission=menu_permission,
            operate_desc=(operate_desc or "")[:255],
            url=url[:512],
            method=method,
            input_value=format_log_body(input_value),
            return_value=format_log_body(return_value),
            client_ip=client_ip,
            time_consume_ms=time_consume_ms,
            status=status,
            trace_id=trace_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        log_id = int(row.log_id)
        persist_sql_for_operation(log_id, log_type=1, trace_id=trace_id)
        end_sql_capture()
        return log_id
    except Exception as exc:
        logger.warning("[登录模块-运维日志|audit_log|操作日志|硬编执行|失败] err=%s", exc)
        db.rollback()
        end_sql_capture()
        return None
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
    prog_impl: str = "",
    return_value: str = "",
) -> None:
    db = SessionLocal()
    try:
        final_msg = compose_error_message(
            error_message=error_message,
            return_value=return_value,
        )
        req_text = input_value.strip() if input_value else ""
        if not req_text and url:
            req_text = f"URL: {url}"
        db.add(
            SysLogError(
                operate_no=operate_no,
                error_type=error_type,
                url=url[:512],
                module=module,
                error_message=final_msg,
                trace_id=trace_id,
                client_ip=client_ip,
                input_value=format_log_body(req_text) or req_text,
                prog_impl=(prog_impl or "")[:512],
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
                target_url=target_url[:512],
                method=method,
                request_summary=format_log_body(request_summary),
                response_summary=format_log_body(response_summary),
                status_code=status_code,
                time_consume_ms=time_consume_ms,
                success=success,
                error_message=clip_text(error_message, limit=4000),
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


def exception_detail(exc: BaseException) -> tuple[str, str]:
    """返回 (完整堆栈+消息, 方法定位)。"""
    tb = traceback.format_exc()
    head = f"{exc.__class__.__name__}: {exc}"
    full = f"{head}\n\n{tb}" if tb.strip() else head
    loc = head
    if exc.__traceback__:
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            last = frames[-1]
            loc = f"{last.filename}:{last.lineno} in {last.name} — {exc}"
    return full, loc


def compose_error_message(
    *,
    error_message: str,
    return_value: str = "",
    method: str = "",
    url: str = "",
) -> str:
    """合并异常正文与响应体，供异常日志单字段展示。"""
    msg = (error_message or "").strip()
    body = format_log_body(return_value) if return_value else ""
    if body and body not in msg:
        msg = f"{msg}\n\n--- 响应体 ---\n{body}" if msg else body
    if method and url and method not in msg:
        msg = f"[{method} {url}]\n\n{msg}"
    return clip_text(msg, limit=16000)
