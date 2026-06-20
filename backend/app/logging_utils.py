"""日志脱敏辅助。"""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|password|token|authorization)\s*[:=]\s*['\"]?([^'\"\s,}]+)", re.I),
    re.compile(r"Bearer\s+([^\s]+)", re.I),
]


def mask_secret(value: str, *, keep: int = 4) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= keep * 2:
        return "***"
    return f"{v[:keep]}...{v[-keep:]}"


def sanitize_log_text(text: str) -> str:
    """日志正文脱敏，避免 api_key / Bearer 泄露。"""
    out = text or ""
    bearer_pat = _SECRET_PATTERNS[1]
    key_pat = _SECRET_PATTERNS[0]
    out = bearer_pat.sub(lambda m: f"Bearer {mask_secret(m.group(1))}", out)
    out = key_pat.sub(
        lambda m: f"{m.group(1)}={mask_secret(m.group(2))}",
        out,
    )
    return out
