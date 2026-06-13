"""网关错误处理 — 统一错误码体系 (SPEC §5)

将所有 LLM 提供商的原生错误转换为标准错误码，
并给出对应的重试/降级策略。

支持的提供商: ARK / Claude / Qwen / OpenAI
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """标准LLM错误码"""
    LLM_TIMEOUT = "LLM_TIMEOUT"           # 连接超时
    LLM_QUOTA = "LLM_QUOTA"               # 额度耗尽
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"     # 请求限流
    LLM_MALFORMED = "LLM_MALFORMED"       # 响应乱码/结构异常
    LLM_INVALID_REQUEST = "LLM_INVALID_REQUEST"  # 入参错误
    LLM_CONTENT_FILTER = "LLM_CONTENT_FILTER"    # 内容审查拦截
    LLM_QUALITY_LOW = "LLM_QUALITY_LOW"          # 回答质量偏差
    LLM_CONTEXT_OVERFLOW = "LLM_CONTEXT_OVERFLOW" # Token超限
    LLM_AUTH_ERROR = "LLM_AUTH_ERROR"     # 认证失败
    LLM_UNKNOWN = "LLM_UNKNOWN"           # 未知错误


# ── 错误码 → 策略 ──────────────────────────────────────────

@dataclass
class ErrorStrategy:
    retry: bool          # 是否重试
    max_retries: int     # 最大重试次数
    backoff_seconds: int # 退避秒数
    degrade_node: bool   # 是否降级节点
    switch_node: bool    # 是否切换节点
    message: str         # 用户提示


STRATEGY_MAP: dict[ErrorCode, ErrorStrategy] = {
    ErrorCode.LLM_TIMEOUT: ErrorStrategy(True, 2, 3, False, True, "请求超时，正在重试..."),
    ErrorCode.LLM_QUOTA: ErrorStrategy(False, 0, 0, True, True, "服务暂时不可用，已切换备用节点"),
    ErrorCode.LLM_RATE_LIMIT: ErrorStrategy(True, 1, 5, True, True, "请求过于频繁，稍后重试"),
    ErrorCode.LLM_MALFORMED: ErrorStrategy(True, 1, 1, False, True, "响应异常，尝试重新请求"),
    ErrorCode.LLM_INVALID_REQUEST: ErrorStrategy(False, 0, 0, False, False, "请求参数有误"),
    ErrorCode.LLM_CONTENT_FILTER: ErrorStrategy(False, 0, 0, False, False, "内容不符合安全策略，请修改后重试"),
    ErrorCode.LLM_QUALITY_LOW: ErrorStrategy(False, 0, 0, False, False, "回答质量未达预期"),
    ErrorCode.LLM_CONTEXT_OVERFLOW: ErrorStrategy(True, 1, 0, False, False, "上下文过长，已自动截断重试"),
    ErrorCode.LLM_AUTH_ERROR: ErrorStrategy(False, 0, 0, True, True, "认证失败，请检查API Key"),
    ErrorCode.LLM_UNKNOWN: ErrorStrategy(True, 1, 2, False, True, "未知错误，尝试切换节点"),
}


# ── ARK 错误模式（优先适配） ──────────────────────────────

ARK_ERROR_PATTERNS: list[tuple[ErrorCode, list[str]]] = [
    (ErrorCode.LLM_TIMEOUT, ["ReadTimeout", "ConnectTimeout", "timed out", "RequestTimeout"]),
    (ErrorCode.LLM_QUOTA, ["AccountBalanceInsufficient", "InsufficientBalance", "quota exceeded", "insufficient_quota", "out of quota"]),
    (ErrorCode.LLM_RATE_LIMIT, ["Throttling.RateLimit", "TooManyRequests", "RateLimitExceeded", "throttling", "rate limit"]),
    (ErrorCode.LLM_INVALID_REQUEST, ["InvalidParameter", "InvalidModel", "invalid_request_error", "model_not_found", "invalid model"]),
    (ErrorCode.LLM_CONTEXT_OVERFLOW, ["ContextLengthExceeded", "context length", "maximum context", "max_tokens", "token limit"]),
    (ErrorCode.LLM_CONTENT_FILTER, ["ContentFilter", "content policy", "content filter", "safety"]),
    (ErrorCode.LLM_AUTH_ERROR, ["AuthenticationError", "InvalidApiKey", "Unauthorized", "auth", "permission"]),
]

# ── Claude/Anthropic 错误模式 ──────────────────────────────

CLAUDE_ERROR_PATTERNS: list[tuple[ErrorCode, list[str]]] = [
    (ErrorCode.LLM_TIMEOUT, ["RequestTimeout", "timed out"]),
    (ErrorCode.LLM_QUOTA, ["overloaded_error", "capacity", "overloaded"]),
    (ErrorCode.LLM_RATE_LIMIT, ["rate_limit_error", "too many requests"]),
    (ErrorCode.LLM_INVALID_REQUEST, ["invalid_request_error", "Invalid model"]),
    (ErrorCode.LLM_CONTEXT_OVERFLOW, ["context_window", "too many tokens"]),
    (ErrorCode.LLM_CONTENT_FILTER, ["content_policy", "safety"]),
    (ErrorCode.LLM_AUTH_ERROR, ["authentication_error", "invalid x-api-key"]),
]

# ── Qwen/DashScope 错误模式 ────────────────────────────────

QWEN_ERROR_PATTERNS: list[tuple[ErrorCode, list[str]]] = [
    (ErrorCode.LLM_TIMEOUT, ["GatewayTimeout", "timed out"]),
    (ErrorCode.LLM_QUOTA, ["InvalidApiKey", "quota"]),
    (ErrorCode.LLM_RATE_LIMIT, ["Throttling", "rate limit"]),
    (ErrorCode.LLM_INVALID_REQUEST, ["InvalidParameter", "ModelNotFound"]),
    (ErrorCode.LLM_CONTEXT_OVERFLOW, ["Maximum token", "token exceeded"]),
    (ErrorCode.LLM_CONTENT_FILTER, ["OutputExceeded", "content filter"]),
    (ErrorCode.LLM_AUTH_ERROR, ["InvalidApiKey", "AuthFailure"]),
]

# ── OpenAI 错误模式 ────────────────────────────────────────

OPENAI_ERROR_PATTERNS: list[tuple[ErrorCode, list[str]]] = [
    (ErrorCode.LLM_TIMEOUT, ["timeout", "timed out"]),
    (ErrorCode.LLM_QUOTA, ["insufficient_quota", "billing"]),
    (ErrorCode.LLM_RATE_LIMIT, ["rate_limit_exceeded", "too many requests"]),
    (ErrorCode.LLM_INVALID_REQUEST, ["invalid_request_error", "model_not_found"]),
    (ErrorCode.LLM_CONTEXT_OVERFLOW, ["context_length_exceeded", "maximum context"]),
    (ErrorCode.LLM_CONTENT_FILTER, ["content_filter", "safety system"]),
    (ErrorCode.LLM_AUTH_ERROR, ["invalid_api_key", "incorrect api key"]),
]

PROVIDER_PATTERNS: dict[str, list[tuple[ErrorCode, list[str]]]] = {
    "ark": ARK_ERROR_PATTERNS,
    "claude": CLAUDE_ERROR_PATTERNS,
    "anthropic": CLAUDE_ERROR_PATTERNS,
    "qwen": QWEN_ERROR_PATTERNS,
    "openai": OPENAI_ERROR_PATTERNS,
    "openai_compatible": OPENAI_ERROR_PATTERNS,
}


def normalize_error(provider: str, status_code: int, response_body: str, exception_msg: str = "") -> tuple[ErrorCode, str]:
    """将不同LLM的原生错误统一转换为标准错误码。

    Args:
        provider: 提供商标识 (ark/claude/qwen/openai)
        status_code: HTTP 状态码
        response_body: 响应体文本
        exception_msg: 异常消息

    Returns:
        (ErrorCode, human_readable_message)
    """
    combined = f"{response_body or ''} {exception_msg or ''}".lower()

    # 先按 HTTP 状态码粗略分类
    if status_code == 429:
        return ErrorCode.LLM_RATE_LIMIT, "请求频率超限 (HTTP 429)"

    if status_code in (401, 403):
        return ErrorCode.LLM_AUTH_ERROR, f"认证失败 (HTTP {status_code})"

    if status_code == 400:
        # 400 可能是多种错误，需要进一步分析
        pass

    if status_code >= 500:
        # 5xx 通常是服务端临时故障
        return ErrorCode.LLM_TIMEOUT, f"服务端故障 (HTTP {status_code})，可重试"

    # 按提供商特定模式匹配
    patterns = PROVIDER_PATTERNS.get(provider.lower(), ARK_ERROR_PATTERNS)
    for code, keywords in patterns:
        for kw in keywords:
            if kw.lower() in combined:
                return code, _default_message(code, kw)

    # 响应内容检查
    if combined and status_code == 200:
        # HTTP200 但内容异常 → MALFORMED
        if _is_malformed(response_body):
            return ErrorCode.LLM_MALFORMED, "LLM返回了无效内容"

    return ErrorCode.LLM_UNKNOWN, f"未知错误 (HTTP {status_code}): {combined[:200]}"


def _is_malformed(body: str) -> bool:
    """检查响应是否异常"""
    if not body or len(body.strip()) < 2:
        return True
    # 尝试JSON解析
    if body.strip().startswith("{"):
        import json
        try:
            json.loads(body)
            # 能解析但关键字段缺失
            if '"content"' not in body and '"text"' not in body and '"message"' not in body:
                pass  # 可能是其他结构的JSON
        except json.JSONDecodeError:
            return True
    return False


def _default_message(code: ErrorCode, keyword: str) -> str:
    msgs = {
        ErrorCode.LLM_TIMEOUT: "请求超时，请稍后重试",
        ErrorCode.LLM_QUOTA: "API额度不足，请联系管理员",
        ErrorCode.LLM_RATE_LIMIT: "请求频率过高，请稍后重试",
        ErrorCode.LLM_MALFORMED: "模型返回异常，已自动重试",
        ErrorCode.LLM_INVALID_REQUEST: "请求参数错误",
        ErrorCode.LLM_CONTENT_FILTER: "内容不符合安全策略",
        ErrorCode.LLM_QUALITY_LOW: "回答质量未达预期",
        ErrorCode.LLM_CONTEXT_OVERFLOW: "输入内容过长",
        ErrorCode.LLM_AUTH_ERROR: "API Key验证失败",
        ErrorCode.LLM_UNKNOWN: "未知错误",
    }
    return msgs.get(code, f"错误: {keyword}")


def get_strategy(code: ErrorCode) -> ErrorStrategy:
    """获取错误码对应的处理策略"""
    return STRATEGY_MAP.get(code, STRATEGY_MAP[ErrorCode.LLM_UNKNOWN])


def describe_error(error_code: ErrorCode, provider: str, detail: str = "") -> dict:
    """生成结构化的错误描述，供日志和前端使用"""
    strategy = get_strategy(error_code)
    return {
        "error_code": error_code.value,
        "provider": provider,
        "detail": detail[:500],
        "retry": strategy.retry,
        "max_retries": strategy.max_retries,
        "backoff_seconds": strategy.backoff_seconds,
        "degrade_node": strategy.degrade_node,
        "switch_node": strategy.switch_node,
        "user_message": strategy.message,
    }
