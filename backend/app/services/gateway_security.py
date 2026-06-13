"""安全与合规 (SPEC §2) — PII脱敏 + 敏感词过滤"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── PII 脱敏规则 ───────────────────────────────────────────

PII_PATTERNS: list[tuple[str, str, str]] = [
    # (名称, 正则, 替换模板)
    ("手机号", r"\b1[3-9]\d{9}\b", lambda m: m.group()[:3] + "****" + m.group()[-4:]),
    ("身份证", r"\b\d{17}[\dXx]\b", lambda m: m.group()[:3] + "***********" + m.group()[-4:]),
    ("邮箱", r"\b[\w.-]+@[\w.-]+\.\w+\b", lambda m: m.group().split("@")[0][:2] + "***@" + m.group().split("@")[1]),
    ("银行卡", r"\b\d{16,19}\b", lambda m: m.group()[:4] + "****" + m.group()[-4:]),
]

SENSITIVE_KEYWORDS: list[str] = [
    # 政治敏感
    "颠覆国家", "分裂国家", "邪教", "恐怖主义",
    # 色情
    "色情", "裸体", "性交",
    # 暴力
    "杀人", "炸弹制作", "枪支买卖",
    # 赌博
    "赌博", "赌场", "博彩",
    # 毒品
    "毒品", "吸毒", "贩毒",
]


def mask_pii(text: str) -> tuple[str, int]:
    """对文本中的PII进行脱敏。

    返回: (脱敏后文本, 脱敏数量)
    """
    count = 0
    result = text
    for name, pattern, replacer in PII_PATTERNS:
        new_result, n = re.subn(pattern, replacer, result)
        if n > 0:
            count += n
            result = new_result
            logger.info(f"[安全-PII] {name} 脱敏 {n} 处")
    return result, count


def check_sensitive(text: str) -> tuple[bool, list[str]]:
    """检查文本是否包含敏感词。

    返回: (是否包含敏感词, 命中词列表)
    """
    hits = [kw for kw in SENSITIVE_KEYWORDS if kw in text]
    if hits:
        logger.warning(f"[安全-敏感词] 命中: {hits}")
    return len(hits) > 0, hits


def sanitize_request(text: str) -> tuple[str, bool, str]:
    """请求安全处理：PII脱敏 + 敏感词检查。

    返回: (处理后文本, 是否通过, 拦截原因)
    """
    # 1. PII脱敏
    masked, count = mask_pii(text)

    # 2. 敏感词检查
    has_sensitive, hits = check_sensitive(masked)
    if has_sensitive:
        return masked, False, f"内容包含敏感词: {', '.join(hits)}"

    return masked, True, ""


def sanitize_response(text: str) -> str:
    """响应安全处理：PII脱敏"""
    masked, _ = mask_pii(text)
    return masked
