"""知识库静态资源访问控制（/output/kb_assets 需登录）。"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.auth.security import decode_access_token


class KbAssetsAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/output/kb_assets/"):
            token = self._extract_token(request)
            if not token or not decode_access_token(token):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "访问知识库资源需登录"},
                )
        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return request.cookies.get("access_token") or request.query_params.get("access_token")
