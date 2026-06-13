"""LLM 适配器模块 — 统一 Ark/Claude/Qwen/OpenAI 四种 LLM 的输出格式。

适配器模式：所有适配器实现统一接口，将不同 LLM 的请求/响应格式
转换到系统标准 Schema。
"""

from .base import LLMResponse, BaseAdapter, AdapterConfig
from .registry import AdapterRegistry, get_adapter

__all__ = [
    "LLMResponse",
    "BaseAdapter",
    "AdapterConfig",
    "AdapterRegistry",
    "get_adapter",
]
