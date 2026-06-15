"""Casbin 鉴权 + 运维四类日志中间件（纯 ASGI，兼容 SSE 流式；完整请求/响应体 + SQL 采集）。"""

from __future__ import annotations

import logging
import time
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.casbin_enforcer import enforce_api
from app.auth.casbin_policies import PUBLIC_API_ROUTES
from app.auth.security import decode_access_token
from app.services.audit_log import (
    exception_detail,
    module_from_path,
    new_trace_id,
    permission_from_path,
    write_api_call_log,
    write_error_log,
    write_operation_log,
)
from app.services.http_log_body import (
    format_http_error_message,
    full_url,
    http_error_prog_impl,
    operate_desc_from,
    parse_response_headers,
    serialize_inbound_request,
    serialize_response_chunks,
)
from app.services.sql_trace import begin_sql_capture, end_sql_capture

logger = logging.getLogger(__name__)

STREAMING_SUFFIXES = ("/chat/stream",)


def _extract_bearer(headers: list[tuple[bytes, bytes]]) -> str | None:
    for raw_key, raw_val in headers:
        if raw_key.lower() == b"authorization":
            auth = raw_val.decode("latin-1")
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
    return None


def _extract_token(scope: Scope, headers: list[tuple[bytes, bytes]]) -> str | None:
    token = _extract_bearer(headers)
    if token:
        return token
    qs = (scope.get("query_string") or b"").decode("latin-1")
    for part in qs.split("&"):
        if part.startswith("token="):
            return unquote(part[6:], errors="replace").strip()
    return None


def _header_value(headers: list[tuple[bytes, bytes]], name: str) -> str:
    target = name.lower().encode()
    for raw_key, raw_val in headers:
        if raw_key.lower() == target:
            return raw_val.decode("latin-1")
    return ""


def _is_streaming_path(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in STREAMING_SUFFIXES)


class AuditCasbinMiddleware:
    """不使用 BaseHTTPMiddleware，避免截断 StreamingResponse。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = str(scope.get("method", "GET")).upper()
        headers = scope.get("headers") or []
        trace_id = _header_value(headers, "x-trace-id") or new_trace_id()
        client_ip = scope["client"][0] if scope.get("client") else ""

        if not path.startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return

        if _is_streaming_path(path):
            await self._handle_streaming(scope, receive, send, path, method, trace_id, client_ip, headers)
            return

        request = Request(scope, receive)
        body_bytes = await request.body()

        async def replay_receive() -> Message:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        url_with_qs = full_url(path, scope.get("query_string"))
        req_summary = serialize_inbound_request(method, url_with_qs, body_bytes, headers)

        scope.setdefault("state", {})
        if isinstance(scope["state"], dict):
            scope["state"]["trace_id"] = trace_id

        if (method, path) in PUBLIC_API_ROUTES:
            await self._wrap(
                scope,
                replay_receive,
                send,
                url_with_qs,
                method,
                trace_id,
                client_ip,
                req_summary,
                skip_auth=True,
            )
            return

        token = _extract_token(scope, headers)
        if not token:
            await JSONResponse(status_code=401, content={"detail": "未登录，请先登录"})(scope, receive, send)
            return

        payload = decode_access_token(token)
        if not payload:
            await JSONResponse(status_code=401, content={"detail": "登录已过期，请重新登录"})(scope, receive, send)
            return

        roles = payload.get("roles") or ["viewer"]
        user_id = int(payload["sub"]) if payload.get("sub") else None
        user_no = payload.get("user_no") or ""

        if not enforce_api(roles, path, method):
            write_error_log(
                operate_no=trace_id,
                error_type=2,
                url=url_with_qs,
                module=module_from_path(path),
                error_message="Casbin 拒绝访问",
                trace_id=trace_id,
                client_ip=client_ip,
                input_value=req_summary,
                prog_impl="AuditCasbinMiddleware.enforce_api",
            )
            await JSONResponse(status_code=403, content={"detail": "无权限，请向管理员申请权限"})(scope, receive, send)
            return

        scope["state"]["user_id"] = user_id
        scope["state"]["user_no"] = user_no
        scope["state"]["roles"] = roles
        await self._wrap(
            scope,
            replay_receive,
            send,
            url_with_qs,
            method,
            trace_id,
            client_ip,
            req_summary,
            skip_auth=False,
        )

    async def _handle_streaming(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        path: str,
        method: str,
        trace_id: str,
        client_ip: str,
        headers: list[tuple[bytes, bytes]],
    ) -> None:
        token = _extract_token(scope, headers)
        if not token:
            await JSONResponse(status_code=401, content={"detail": "未登录，请先登录"})(scope, receive, send)
            return
        payload = decode_access_token(token)
        if not payload:
            await JSONResponse(status_code=401, content={"detail": "登录已过期，请重新登录"})(scope, receive, send)
            return
        roles = payload.get("roles") or ["viewer"]
        if not enforce_api(roles, path, method):
            await JSONResponse(status_code=403, content={"detail": "无权限，请向管理员申请权限"})(scope, receive, send)
            return

        scope.setdefault("state", {})
        if isinstance(scope["state"], dict):
            scope["state"].update(
                {
                    "trace_id": trace_id,
                    "user_id": int(payload["sub"]) if payload.get("sub") else None,
                    "user_no": payload.get("user_no") or "",
                    "roles": roles,
                }
            )

        url_with_qs = full_url(path, scope.get("query_string"))
        begin_sql_capture()
        start = time.perf_counter()
        status_code = 500
        response_chunks: list[bytes] = []
        response_headers: dict[str, str] = {}

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                response_headers.update(parse_response_headers(message.get("headers") or []))
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_chunks.append(body)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            tb, loc = exception_detail(exc)
            write_error_log(
                operate_no=trace_id,
                error_type=1,
                url=url_with_qs,
                module=module_from_path(path),
                error_message=tb,
                trace_id=trace_id,
                client_ip=client_ip,
                input_value="[SSE 流式请求]",
                prog_impl=loc,
            )
            end_sql_capture()
            raise
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            user_id = scope.get("state", {}).get("user_id") if isinstance(scope.get("state"), dict) else None
            ok = 1 if 200 <= status_code < 400 else 0
            resp_body = serialize_response_chunks(response_chunks, response_headers)
            write_api_call_log(
                trace_id=trace_id,
                api_type="inbound",
                target_url=url_with_qs,
                method=method,
                request_summary="[SSE 流式请求体]",
                response_summary=resp_body or f"status={status_code}",
                status_code=status_code,
                time_consume_ms=elapsed,
                success=ok,
                error_message="",
                user_id=user_id,
            )
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                write_operation_log(
                    operate_no=trace_id,
                    user_id=user_id,
                    user_no=scope.get("state", {}).get("user_no") if isinstance(scope.get("state"), dict) else None,
                    module=module_from_path(path),
                    menu_permission=permission_from_path(path),
                    operate_desc=operate_desc_from(method, path),
                    url=url_with_qs,
                    method=method,
                    input_value="[SSE 流式请求体]",
                    return_value=resp_body or f"status={status_code}",
                    client_ip=client_ip,
                    time_consume_ms=elapsed,
                    status=ok,
                    trace_id=trace_id,
                )
            else:
                end_sql_capture()

    async def _wrap(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        url: str,
        method: str,
        trace_id: str,
        client_ip: str,
        req_summary: str,
        *,
        skip_auth: bool,
    ) -> None:
        path_only = url.split("?", 1)[0]
        begin_sql_capture()
        start = time.perf_counter()
        status_code = 500
        exc_msg = ""
        exc_loc = ""
        response_chunks: list[bytes] = []
        response_headers: dict[str, str] = {}

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                response_headers.update(parse_response_headers(message.get("headers") or []))
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_chunks.append(body)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            tb, loc = exception_detail(exc)
            exc_msg = tb
            exc_loc = loc
            write_error_log(
                operate_no=trace_id,
                error_type=1,
                url=url,
                module=module_from_path(path_only),
                error_message=tb,
                trace_id=trace_id,
                client_ip=client_ip,
                input_value=req_summary,
                prog_impl=loc,
            )
            raise
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            state = scope.get("state") if isinstance(scope.get("state"), dict) else {}
            user_id = state.get("user_id")
            user_no = state.get("user_no")
            ok = 1 if 200 <= status_code < 400 else 0
            resp_summary = serialize_response_chunks(response_chunks, response_headers)

            if path_only.startswith("/api/v1/") and method != "OPTIONS":
                write_api_call_log(
                    trace_id=trace_id,
                    api_type="inbound",
                    target_url=url,
                    method=method,
                    request_summary=req_summary,
                    response_summary=resp_summary or f"status={status_code}",
                    status_code=status_code,
                    time_consume_ms=elapsed,
                    success=ok,
                    error_message=exc_msg[:4000] if exc_msg else "",
                    user_id=user_id,
                )

            if method in ("POST", "PUT", "PATCH", "DELETE") and path_only.startswith("/api/v1/"):
                write_operation_log(
                    operate_no=trace_id,
                    user_id=user_id,
                    user_no=user_no,
                    module=module_from_path(path_only),
                    menu_permission=permission_from_path(path_only),
                    operate_desc=operate_desc_from(method, path_only),
                    url=url,
                    method=method,
                    input_value=req_summary,
                    return_value=resp_summary or f"status={status_code}",
                    client_ip=client_ip,
                    time_consume_ms=elapsed,
                    status=ok,
                    trace_id=trace_id,
                )
            elif not (method in ("POST", "PUT", "PATCH", "DELETE") and path_only.startswith("/api/v1/")):
                end_sql_capture()

            if status_code >= 400 and not exc_msg:
                http_err_msg = format_http_error_message(
                    status_code,
                    resp_summary,
                    method=method,
                    url=url,
                )
                write_error_log(
                    operate_no=trace_id,
                    error_type=3,
                    url=url,
                    module=module_from_path(path_only),
                    error_message=http_err_msg,
                    trace_id=trace_id,
                    client_ip=client_ip,
                    input_value=req_summary,
                    prog_impl=http_error_prog_impl(status_code, method, path_only, resp_summary),
                )

        _ = skip_auth
