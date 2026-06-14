"""Casbin 鉴权 + 运维四类日志中间件（纯 ASGI，兼容 SSE 流式）。"""



from __future__ import annotations



import logging

import time



from starlette.requests import Request

from starlette.responses import JSONResponse

from starlette.types import ASGIApp, Message, Receive, Scope, Send



from app.auth.casbin_enforcer import enforce_api

from app.auth.casbin_policies import PUBLIC_API_ROUTES

from app.auth.security import decode_access_token

from app.services.audit_log import (

    module_from_path,

    new_trace_id,

    permission_from_path,

    serialize_body,

    write_api_call_log,

    write_error_log,

    write_operation_log,

)



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
    """Bearer 优先；EventSource 等场景可传 ?token=。"""
    token = _extract_bearer(headers)
    if token:
        return token
    qs = (scope.get("query_string") or b"").decode("latin-1")
    for part in qs.split("&"):
        if part.startswith("token="):
            from urllib.parse import unquote
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

        client_ip = ""

        if scope.get("client"):

            client_ip = scope["client"][0]



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



        req_summary = serialize_body(body_bytes)

        scope.setdefault("state", {})

        if isinstance(scope["state"], dict):

            scope["state"]["trace_id"] = trace_id



        if (method, path) in PUBLIC_API_ROUTES:

            await self._wrap(scope, replay_receive, send, path, method, trace_id, client_ip, req_summary, skip_auth=True)

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

                url=path,

                module=module_from_path(path),

                error_message="Casbin 拒绝访问",

                trace_id=trace_id,

                client_ip=client_ip,

                input_value=req_summary,

            )

            await JSONResponse(status_code=403, content={"detail": "无权限，请向管理员申请权限"})(scope, receive, send)

            return



        scope["state"]["user_id"] = user_id

        scope["state"]["user_no"] = user_no

        scope["state"]["roles"] = roles

        await self._wrap(scope, replay_receive, send, path, method, trace_id, client_ip, req_summary, skip_auth=False)



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



        start = time.perf_counter()

        status_code = 500



        async def send_wrapper(message: Message) -> None:

            nonlocal status_code

            if message["type"] == "http.response.start":

                status_code = int(message.get("status", 500))

            await send(message)



        try:

            await self.app(scope, receive, send_wrapper)

        except Exception as exc:

            write_error_log(

                operate_no=trace_id,

                error_type=1,

                url=path,

                module=module_from_path(path),

                error_message=str(exc),

                trace_id=trace_id,

                client_ip=client_ip,

                input_value="stream",

            )

            raise

        finally:

            elapsed = int((time.perf_counter() - start) * 1000)

            user_id = scope.get("state", {}).get("user_id") if isinstance(scope.get("state"), dict) else None

            ok = 1 if 200 <= status_code < 400 else 0

            write_api_call_log(

                trace_id=trace_id,

                api_type="inbound",

                target_url=path,

                method=method,

                request_summary="stream",

                response_summary=f"status={status_code}",

                status_code=status_code,

                time_consume_ms=elapsed,

                success=ok,

                error_message="",

                user_id=user_id,

            )



    async def _wrap(

        self,

        scope: Scope,

        receive: Receive,

        send: Send,

        path: str,

        method: str,

        trace_id: str,

        client_ip: str,

        req_summary: str,

        *,

        skip_auth: bool,

    ) -> None:

        start = time.perf_counter()

        status_code = 500

        exc_msg = ""



        async def send_wrapper(message: Message) -> None:

            nonlocal status_code

            if message["type"] == "http.response.start":

                status_code = int(message.get("status", 500))

            await send(message)



        try:

            await self.app(scope, receive, send_wrapper)

        except Exception as exc:

            exc_msg = str(exc)

            write_error_log(

                operate_no=trace_id,

                error_type=1,

                url=path,

                module=module_from_path(path),

                error_message=exc_msg,

                trace_id=trace_id,

                client_ip=client_ip,

                input_value=req_summary,

            )

            raise

        finally:

            elapsed = int((time.perf_counter() - start) * 1000)

            state = scope.get("state") if isinstance(scope.get("state"), dict) else {}

            user_id = state.get("user_id")

            user_no = state.get("user_no")

            ok = 1 if 200 <= status_code < 400 else 0



            if path.startswith("/api/v1/") and method != "OPTIONS":

                write_api_call_log(

                    trace_id=trace_id,

                    api_type="inbound",

                    target_url=path,

                    method=method,

                    request_summary=req_summary,

                    response_summary=f"status={status_code}",

                    status_code=status_code,

                    time_consume_ms=elapsed,

                    success=ok,

                    error_message=exc_msg,

                    user_id=user_id,

                )



            if method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/v1/"):

                write_operation_log(

                    operate_no=trace_id,

                    user_id=user_id,

                    user_no=user_no,

                    module=module_from_path(path),

                    menu_permission=permission_from_path(path),

                    url=path,

                    method=method,

                    input_value=req_summary,

                    return_value=f"status={status_code}",

                    client_ip=client_ip,

                    time_consume_ms=elapsed,

                    status=ok,

                    trace_id=trace_id,

                )



            if status_code >= 400 and not exc_msg:

                write_error_log(

                    operate_no=trace_id,

                    error_type=3,

                    url=path,

                    module=module_from_path(path),

                    error_message=f"HTTP {status_code}",

                    trace_id=trace_id,

                    client_ip=client_ip,

                    input_value=req_summary,

                )



        _ = skip_auth

