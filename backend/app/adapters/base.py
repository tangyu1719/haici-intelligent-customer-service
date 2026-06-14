"""LLM 适配器基类 — 定义统一 Schema 和适配器接口。

所有 LLM 适配器（Ark/Claude/Qwen/OpenAI）必须实现此接口，
确保不同 LLM 的请求/响应格式转换到系统统一 Schema。
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import requests

logger = logging.getLogger(__name__)


# ── 统一 Schema ──────────────────────────────────────────────


@dataclass
class LLMMessage:
    """统一消息格式"""
    role: str  # system / user / assistant
    content: str


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式（所有适配器输出此格式）"""
    content: str
    model: str = ""
    provider: str = ""
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=lambda: {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    })
    raw_response: Any = None
    error: str | None = None
    latency_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class LLMStreamChunk:
    """统一的流式响应块"""
    content: str
    finish_reason: str | None = None
    index: int = 0


@dataclass
class AdapterConfig:
    """适配器配置"""
    provider: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 120
    max_tokens: int = 4096
    temperature: float = 0.7
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)


# ── 基类适配器 ──────────────────────────────────────────────


class BaseAdapter(ABC):
    """LLM 适配器抽象基类。

    每个具体适配器负责：
    1. 将统一 LLMMessage 转换为该 LLM 的原生请求格式
    2. 调用 LLM API
    3. 将原生响应转换为统一 LLMResponse
    """

    provider: str = "base"

    def __init__(self, config: AdapterConfig):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update(self._build_headers())

    @abstractmethod
    def _build_headers(self) -> dict[str, str]:
        """构建 HTTP 请求头"""
        ...

    @abstractmethod
    def _build_request_body(
        self, messages: list[LLMMessage], stream: bool = False
    ) -> dict[str, Any]:
        """将统一消息转换为该 LLM 的原生请求体"""
        ...

    @abstractmethod
    def _parse_response(self, raw: dict[str, Any]) -> LLMResponse:
        """将原生响应转换为统一 LLMResponse"""
        ...

    @abstractmethod
    async def _parse_stream_response(
        self, raw_text: str
    ) -> LLMStreamChunk | None:
        """解析 SSE 流中的一行数据，返回统一 LLMStreamChunk"""
        ...

    def invoke(self, messages: list[LLMMessage]) -> LLMResponse:
        """同步调用 LLM"""
        t0 = time.perf_counter()
        try:
            body = self._build_request_body(messages, stream=False)
            url = self._chat_url()
            resp = self._session.post(url, json=body, timeout=self.config.timeout_seconds)
            latency = (time.perf_counter() - t0) * 1000

            if not resp.ok:
                return LLMResponse(
                    content="",
                    provider=self.provider,
                    error=f"HTTP {resp.status_code}: {(resp.text or '')[:500]}",
                    latency_ms=latency,
                )

            data = resp.json()
            result = self._parse_response(data)
            result.latency_ms = latency
            result.provider = self.provider
            result.model = self.config.model
            return result
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            logger.exception(f"[{self.provider}] 调用失败: {exc}")
            return LLMResponse(
                content="",
                provider=self.provider,
                error=str(exc)[:500],
                latency_ms=latency,
            )

    async def stream_invoke(
        self, messages: list[LLMMessage]
    ) -> AsyncIterator[LLMStreamChunk]:
        """异步流式调用 LLM，逐块返回统一 LLMStreamChunk"""
        import aiohttp

        t0 = time.perf_counter()
        try:
            body = self._build_request_body(messages, stream=True)
            url = self._chat_url()
            headers = self._build_headers()

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds),
                ) as resp:
                    if not resp.ok:
                        text = await resp.text()
                        yield LLMStreamChunk(
                            content=f"[{self.provider} 错误: HTTP {resp.status}]",
                            finish_reason="error",
                        )
                        return

                    buffer = ""
                    async for line_bytes in resp.content:
                        line = line_bytes.decode("utf-8", errors="replace")
                        if not line.strip():
                            continue
                        # SSE 格式: data: {...}
                        buffer += line
                        if "\n" in buffer:
                            lines = buffer.split("\n")
                            buffer = lines.pop(-1) or ""
                            for l in lines:
                                l = l.strip()
                                if l.startswith("data: "):
                                    chunk = await self._parse_stream_response(l[6:])
                                    if chunk is not None:
                                        yield chunk
        except Exception as exc:
            logger.exception(f"[{self.provider}] 流式调用失败: {exc}")
            yield LLMStreamChunk(
                content=f"[流式调用异常: {str(exc)[:200]}]",
                finish_reason="error",
            )

    @abstractmethod
    def _chat_url(self) -> str:
        """返回 Chat API 端点 URL"""
        ...

    def health_check(self) -> dict[str, Any]:
        """健康检查：发送最小请求验证连通性"""
        t0 = time.perf_counter()
        try:
            msg = LLMMessage(role="user", content="ping")
            body = self._build_request_body([msg], stream=False)
            # 使用最小 max_tokens
            body["max_tokens"] = 1
            url = self._chat_url()
            resp = self._session.post(url, json=body, timeout=15)
            latency = (time.perf_counter() - t0) * 1000
            if not resp.ok:
                err_text = (resp.text or "").strip()
                return {
                    "provider": self.provider,
                    "model": self.config.model,
                    "ok": False,
                    "status_code": resp.status_code,
                    "error": f"HTTP {resp.status_code}: {err_text[:300]}" if err_text else f"HTTP {resp.status_code}",
                    "latency_ms": round(latency, 1),
                }
            return {
                "provider": self.provider,
                "model": self.config.model,
                "ok": resp.ok,
                "status_code": resp.status_code,
                "latency_ms": round(latency, 1),
            }
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            return {
                "provider": self.provider,
                "model": self.config.model,
                "ok": False,
                "error": str(exc)[:200],
                "latency_ms": round(latency, 1),
            }
