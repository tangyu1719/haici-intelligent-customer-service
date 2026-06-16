"""模型上下文长度注册表：网关节点导入时查询并绑定字符预算。"""

from __future__ import annotations

import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

# 常见模型上下文（token 数）；字符预算按中文约 2 字符/token 估算
_MODEL_TOKEN_CONTEXT: dict[str, int] = {
    "qwen-turbo": 128_000,
    "qwen-plus": 128_000,
    "qwen-max": 32_768,
    "qwen2.5-72b-instruct": 131_072,
    "qwen2:0.5b": 32_768,
    "deepseek-v3": 64_000,
    "deepseek-r1": 64_000,
    "doubao-pro-32k": 32_768,
    "doubao-pro-4k": 4_096,
    "doubao-lite-4k": 4_096,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}

_CHARS_PER_TOKEN = 2


def _normalize_model_key(model: str) -> str:
    m = (model or "").strip().lower()
    # 火山方舟 endpoint_id 形如 ep-xxxx，无法直接映射，回退默认
    if re.match(r"^ep-[a-f0-9]+$", m):
        return m
    return m.split("/")[-1]


def lookup_context_tokens(model: str) -> int:
    """按模型名查询上下文 token 上限；未知模型回退全局默认。"""
    key = _normalize_model_key(model)
    if key in _MODEL_TOKEN_CONTEXT:
        return _MODEL_TOKEN_CONTEXT[key]
    for pattern, tokens in _MODEL_TOKEN_CONTEXT.items():
        if pattern in key:
            return tokens
    default_chars = max(4096, int(settings.CHAT_MAX_CONTEXT_CHARS))
    return default_chars // _CHARS_PER_TOKEN


def lookup_context_chars(model: str) -> int:
    tokens = lookup_context_tokens(model)
    return max(4096, tokens * _CHARS_PER_TOKEN)


def lookup_max_output_tokens(model: str, task_type: str = "qa") -> int:
    """按任务类型给出合理输出 token 上限。"""
    if task_type == "qa":
        return 512
    if task_type == "summary":
        return 2048
    return 1024


def register_model_context(model: str, context_tokens: int) -> None:
    """运行时注册自定义模型上下文（如从网关元数据拉取）。"""
    key = _normalize_model_key(model)
    _MODEL_TOKEN_CONTEXT[key] = max(1024, int(context_tokens))
    logger.info(
        "[智能客服-上下文|model_context_registry|register|硬编执行|完成] model=%s; context_tokens=%s",
        key,
        context_tokens,
    )
