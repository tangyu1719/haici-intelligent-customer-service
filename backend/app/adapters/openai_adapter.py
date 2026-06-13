"""OpenAI 适配器 — 标准 OpenAI Chat Completions API。

支持 OpenAI 官方 API 及所有兼容 OpenAI 协议的第三方服务。
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


class OpenAIAdapter(BaseAdapter):
    """OpenAI 适配器 — 标准 Chat Completions API"""

    provider = "openai"

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

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
        }
        body.update(self.config.extra)
        return body

    def _parse_response(self, raw: dict[str, Any]) -> LLMResponse:
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
