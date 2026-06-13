"""适配器注册表 — 根据 provider 名称获取适配器实例。

支持: ark, claude, qwen, openai, openai_compatible
"""

from __future__ import annotations

import logging
from typing import Any

from .base import AdapterConfig, BaseAdapter, LLMMessage, LLMResponse
from .ark_adapter import ArkAdapter
from .claude_adapter import ClaudeAdapter
from .openai_adapter import OpenAIAdapter
from .qwen_adapter import QwenAdapter

logger = logging.getLogger(__name__)

# 适配器类注册表
_ADAPTER_CLASSES: dict[str, type[BaseAdapter]] = {
    "ark": ArkAdapter,
    "claude": ClaudeAdapter,
    "anthropic": ClaudeAdapter,
    "qwen": QwenAdapter,
    "openai": OpenAIAdapter,
    "openai_compatible": OpenAIAdapter,
}


class AdapterRegistry:
    """适配器注册表，管理所有 LLM 适配器实例。

    用法:
        registry = AdapterRegistry()
        adapter = registry.get_or_create(
            provider="ark",
            api_key="xxx",
            base_url="https://...",
            model="ep-xxx",
        )
        response = adapter.invoke(messages)
    """

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}

    def _make_key(self, provider: str, model: str) -> str:
        return f"{provider}:{model}"

    def get_or_create(self, **kwargs: Any) -> BaseAdapter:
        provider = str(kwargs.get("provider", "openai")).lower()
        model = str(kwargs.get("model", ""))
        key = self._make_key(provider, model)

        if key in self._adapters:
            return self._adapters[key]

        adapter_cls = _ADAPTER_CLASSES.get(provider)
        if adapter_cls is None:
            logger.warning(f"未知的 provider '{provider}'，回退到 OpenAI 适配器")
            adapter_cls = OpenAIAdapter

        config = AdapterConfig(
            provider=provider,
            api_key=str(kwargs.get("api_key", "")),
            base_url=str(kwargs.get("base_url", "")),
            model=model,
            timeout_seconds=int(kwargs.get("timeout_seconds", 120)),
            max_tokens=int(kwargs.get("max_tokens", 4096)),
            temperature=float(kwargs.get("temperature", 0.7)),
            extra=kwargs.get("extra", {}),
        )

        adapter = adapter_cls(config)
        self._adapters[key] = adapter
        logger.info(f"[AdapterRegistry] 创建适配器: {key} ({adapter_cls.__name__})")
        return adapter

    def invoke(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        messages: list[LLMMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        adapter = self.get_or_create(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        return adapter.invoke(messages)

    def health_check(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        adapter = self.get_or_create(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        return adapter.health_check()


# 全局单例
_registry: AdapterRegistry | None = None


def get_adapter(**kwargs: Any) -> BaseAdapter:
    """获取适配器的便捷函数"""
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry.get_or_create(**kwargs)
