"""通义千问（Qwen / DashScope）适配器。

DashScope 使用 OpenAI 兼容模式 (compatible-mode/v1)，
但仍有一些差异需要处理：
1. enable_search / result_format 等千问特有参数
2. 错误格式不同
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import (
    AdapterConfig,
    BaseAdapter,
    LLMMessage,
    LLMResponse,
    LLMStreamChunk,
)

logger = logging.getLogger(__name__)


class QwenAdapter(BaseAdapter):
    """通义千问适配器 — DashScope OpenAI 兼容模式"""

    provider = "qwen"

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        # DashScope 兼容模式需要 X-DashScope 头部
        if "dashscope" in self.config.base_url.lower():
            headers["X-DashScope-OpenAISource"] = "haici"
        return headers

    def _chat_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/chat/completions"

    def _build_request_body(
        self, messages: list[LLMMessage], stream: bool = False
    ) -> dict[str, Any]:
        msgs = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": msgs,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": stream,
            # 千问特有参数
            "enable_search": False,
            "result_format": "message",
        }
        body.update(self.config.extra)
        return body

    def _parse_response(self, raw: dict[str, Any]) -> LLMResponse:
        # DashScope 错误格式
        if "code" in raw and raw.get("code") != "":
            code = raw.get("code", "")
            message = raw.get("message", "")
            return LLMResponse(
                content="",
                error=f"Qwen API {code}: {message}",
                raw_response=raw,
            )

        choice = (raw.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = raw.get("usage") or {}
        return LLMResponse(
            content=msg.get("content") or "",
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            raw_response=raw,
        )

    async def _parse_stream_response(self, raw_text: str) -> LLMStreamChunk | None:
        if raw_text.strip() == "[DONE]":
            return LLMStreamChunk(content="", finish_reason="stop")
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return None
        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        return LLMStreamChunk(
            content=delta.get("content") or "",
            finish_reason=choice.get("finish_reason"),
            index=choice.get("index", 0),
        )
