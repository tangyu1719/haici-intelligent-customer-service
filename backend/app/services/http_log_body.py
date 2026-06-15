"""HTTP 日志正文序列化：对齐 WMS 操作/API 日志的 inputValue / returnValue 完整落库。"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_BODY = 32_000

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "old_password",
        "new_password",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "authorization",
    }
)

# (method, path_prefix) -> 操作描述（对齐 WMS operateDesc）
_OPERATE_DESC_RULES: list[tuple[str, str, str]] = [
    ("POST", "/api/v1/auth/login", "用户登录"),
    ("POST", "/api/v1/auth/logout", "用户登出"),
    ("POST", "/api/v1/auth/register", "用户注册"),
    ("POST", "/api/v1/knowledge", "上传知识库文档"),
    ("DELETE", "/api/v1/knowledge/", "删除知识库文档"),
    ("POST", "/api/v1/knowledge-bases", "创建知识库"),
    ("PUT", "/api/v1/knowledge-bases/", "更新知识库"),
    ("DELETE", "/api/v1/knowledge-bases/", "删除知识库"),
    ("POST", "/api/v1/chat/stream", "智能客服对话（流式）"),
    ("POST", "/api/v1/sessions", "创建会话"),
    ("DELETE", "/api/v1/sessions/", "删除会话"),
    ("POST", "/api/v1/feedback", "提交回答反馈"),
    ("POST", "/api/v1/multimodal/upload", "多模态文件上传"),
    ("POST", "/api/v1/multimodal/process", "多模态文档处理"),
    ("POST", "/api/v1/settings/agents-md/", "保存 Agent Prompt"),
    ("POST", "/api/v1/settings/agent-routing/save", "保存 Agent 路由"),
    ("POST", "/api/v1/settings/gateway-nodes/upsert", "保存网关节点"),
    ("DELETE", "/api/v1/settings/gateway-nodes/", "删除网关节点"),
    ("POST", "/api/v1/admin/rbac/", "RBAC 权限变更"),
]


def clip_text(text: str | None, limit: int = MAX_BODY) -> str:
    if not text:
        return ""
    s = str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…（已截断，共 {len(s)} 字符）"


def _mask_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "***"
            else:
                out[k] = _mask_obj(v)
        return out
    if isinstance(obj, list):
        return [_mask_obj(x) for x in obj]
    return obj


def mask_sensitive_json(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        return json.dumps(_mask_obj(data), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw


def pretty_json_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw


def serialize_http_body(body: bytes | None, *, content_type: str = "", label: str = "") -> str:
    if not body:
        return ""
    ct = (content_type or "").lower()
    if "multipart/form-data" in ct:
        return f"[multipart/form-data 上传体，长度 {len(body)} 字节]"
    if "octet-stream" in ct or ct.startswith("application/") and "json" not in ct and "text" not in ct:
        if len(body) > 512:
            return f"[二进制 Content-Type={content_type or 'unknown'}，长度 {len(body)} 字节]"
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return f"[不可解码正文，长度 {len(body)} 字节]"
    if "json" in ct or text.lstrip().startswith(("{", "[")):
        return clip_text(mask_sensitive_json(text))
    return clip_text(text)


def serialize_request_body(body: bytes | None, headers: list[tuple[bytes, bytes]] | None = None) -> str:
    ct = _headers_get(headers or [], "content-type")
    return serialize_http_body(body, content_type=ct)


def serialize_inbound_request(
    method: str,
    url: str,
    body: bytes | None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> str:
    """完整请求快照：方法、URL、关键头、请求体（GET 无 body 时保留 URL 查询参数说明）。"""
    m = (method or "GET").upper()
    lines = [f"Method: {m}", f"URL: {url}"]
    ct = _headers_get(headers or [], "content-type")
    if ct:
        lines.append(f"Content-Type: {ct}")
    accept = _headers_get(headers or [], "accept")
    if accept:
        lines.append(f"Accept: {accept[:200]}")
    ua = _headers_get(headers or [], "user-agent")
    if ua:
        lines.append(f"User-Agent: {ua[:300]}")
    auth = _headers_get(headers or [], "authorization")
    if auth:
        lines.append("Authorization: Bearer ***" if auth.lower().startswith("bearer ") else "Authorization: ***")

    body_text = serialize_http_body(body, content_type=ct)
    if body_text:
        lines.extend(["", "--- 请求体 ---", body_text])
    elif m in ("GET", "HEAD", "OPTIONS"):
        if "?" in url:
            lines.extend(["", "（无请求体；查询参数已包含在 URL 中）"])
        else:
            lines.extend(["", "（无请求体）"])
    else:
        lines.extend(["", "（无请求体或为空）"])
    return clip_text("\n".join(lines))


def extract_api_error_detail(response_body: str) -> str:
    """从 FastAPI/Starlette JSON 响应中提取 detail 消息。"""
    raw = (response_body or "").strip()
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            detail = obj.get("detail")
            if detail is not None:
                if isinstance(detail, (dict, list)):
                    return json.dumps(detail, ensure_ascii=False, indent=2)
                return str(detail)
            if obj.get("message"):
                return str(obj["message"])
    except json.JSONDecodeError:
        pass
    return raw


def format_http_error_message(
    status_code: int,
    response_body: str,
    *,
    method: str,
    url: str,
) -> str:
    """HTTP 非 2xx 且无 Python 异常时的完整异常信息（含 MSG + 响应体）。"""
    detail = extract_api_error_detail(response_body)
    lines = [
        f"HTTP {status_code} {method} {url}",
        "",
        "【错误消息】",
        detail or f"HTTP {status_code}（响应无 detail 字段）",
    ]
    formatted_body = pretty_json_text(mask_sensitive_json(response_body)) if response_body else ""
    if formatted_body:
        lines.extend(["", "【响应体】", formatted_body])
    else:
        lines.extend(["", "【响应体】", "（未捕获到响应正文）"])
    return clip_text("\n".join(lines), limit=16000)


def http_error_prog_impl(status_code: int, method: str, path: str, response_body: str = "") -> str:
    detail = extract_api_error_detail(response_body)
    short = (detail or "")[:120].replace("\n", " ")
    return f"AuditCasbinMiddleware._wrap | {method} {path} | HTTP {status_code}" + (f" | {short}" if short else "")


def serialize_response_chunks(chunks: list[bytes], headers: dict[str, str] | None = None) -> str:
    if not chunks:
        return ""
    ct = (headers or {}).get("content-type", "")
    merged = b"".join(chunks)
    if "text/event-stream" in ct:
        text = merged.decode("utf-8", errors="replace")
        return clip_text(f"[SSE 流式响应，共 {len(chunks)} 块]\n{text}")
    return serialize_http_body(merged, content_type=ct)


def full_url(path: str, query_string: bytes | str | None) -> str:
    qs = query_string.decode("latin-1") if isinstance(query_string, (bytes, bytearray)) else (query_string or "")
    return path + (f"?{qs}" if qs else "")


def operate_desc_from(method: str, path: str) -> str:
    m = (method or "GET").upper()
    p = path or ""
    for rule_m, prefix, desc in _OPERATE_DESC_RULES:
        if m == rule_m and p.startswith(prefix):
            return desc
    mod = p.strip("/").split("/")
    if len(mod) >= 3:
        return f"{m} {mod[2]}"
    return f"{m} {p}"


def _headers_get(headers: list[tuple[bytes, bytes]], name: str) -> str:
    target = name.lower().encode()
    for raw_key, raw_val in headers:
        if raw_key.lower() == target:
            return raw_val.decode("latin-1", errors="replace")
    return ""


def parse_response_headers(message_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_key, raw_val in message_headers:
        k = raw_key.decode("latin-1").lower()
        out[k] = raw_val.decode("latin-1", errors="replace")
    return out


def extract_table_from_sql(statement: str) -> str:
    text = (statement or "").strip()
    patterns = [
        r"(?i)\bFROM\s+[`'\"]?(\w+)[`'\"]?",
        r"(?i)\bINTO\s+[`'\"]?(\w+)[`'\"]?",
        r"(?i)\bUPDATE\s+[`'\"]?(\w+)[`'\"]?",
        r"(?i)\bJOIN\s+[`'\"]?(\w+)[`'\"]?",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""
