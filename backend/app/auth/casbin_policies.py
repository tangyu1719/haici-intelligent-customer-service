"""Casbin API 策略种子（角色 → 路径 → HTTP 方法正则）。"""

from __future__ import annotations

# (role, obj, act_regex)
VIEWER_API_POLICIES: list[tuple[str, str, str]] = [
    ("viewer", "/api/v1/auth/*", "GET|POST|PATCH|PUT|DELETE"),
    ("viewer", "/api/v1/chat/*", "GET|POST"),
    ("viewer", "/api/v1/sessions", "GET|POST"),
    ("viewer", "/api/v1/sessions/*", "GET|POST|PATCH|DELETE"),
    ("viewer", "/api/v1/knowledge", "GET|POST"),
    ("viewer", "/api/v1/knowledge/*", "GET|POST|DELETE"),
    ("viewer", "/api/v1/multimodal", "GET|POST"),
    ("viewer", "/api/v1/multimodal/*", "GET|POST"),
    ("viewer", "/api/v1/multimodal-tasks", "GET|POST|DELETE"),
    ("viewer", "/api/v1/multimodal-tasks/*", "GET|POST|DELETE"),
    ("viewer", "/api/v1/structured/*", "GET|PUT|POST"),
    ("viewer", "/api/v1/knowledge-bases", "GET|POST"),
    ("viewer", "/api/v1/knowledge-bases/*", "GET|POST|PUT|DELETE"),
    ("viewer", "/api/v1/feedback/*", "GET|POST"),
    ("viewer", "/api/v1/user-profiles/*", "GET|PUT"),
    ("viewer", "/api/v1/system/llm-gateway", "GET"),
    ("viewer", "/api/v1/system/platform/health", "GET"),
]

ADMIN_API_POLICIES: list[tuple[str, str, str]] = [
    ("admin", "/api/v1/*", "GET|POST|PUT|PATCH|DELETE"),
]

ALL_API_POLICIES = VIEWER_API_POLICIES + ADMIN_API_POLICIES

# Casbin 中间件放行（无需 Token）
PUBLIC_API_ROUTES: set[tuple[str, str]] = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/send-code"),
    ("POST", "/api/v1/auth/refresh"),
}
