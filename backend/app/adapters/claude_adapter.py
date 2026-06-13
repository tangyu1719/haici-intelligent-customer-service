"""Claude（Anthropic）适配器。

Claude 使用 Anthropic Messages API，与 OpenAI Chat Completions 格式完全不同：
- 端点: /v1/messages
- 消息角色: user / assistant（无 system role，system 在顶层传递）
- 响应格式: content 数组（text + tool_use blocks）
- 流式: SSE 事件格式（不同的事件类型）
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


class ClaudeAdapter(BaseAdapter):
    """Anthropic Claude 适配器 — Messages API"""

    provider = "claude"

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _chat_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/messages"

    def _build_request_body(
        self, messages: list[LLMMessage], stream: bool = False
    ) -> dict[str, Any]:
        # Claude Messages API: system 在顶层，user/assistant 在 messages 数组
        system_prompts: list[str] = []
        chat_messages: list[dict[str, Any]] = []

        for m in messages:
            if m.role == "system":
                system_prompts.append(m.content)
            elif m.role in ("user", "assistant"):
                chat_messages.append({
                    "role": m.role,
                    "content": [{"type": "text", "text": m.content}],
                })

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": chat_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": stream,
        }

        if system_prompts:
            body["system"] = "\n\n".join(system_prompts)

        body.update(self.config.extra)
        return body

    def _parse_response(self, raw: dict[str, Any]) -> LLMResponse:
        # Anthropic 错误格式
        if "error" in raw:
            err = raw["error"]
            return LLMResponse(
                content="",
                error=f"Claude {err.get('type', 'error')}: {err.get('message', '')}",
                raw_response=raw,
            )

        # Anthropic 正常响应: content 是 [{type: "text", text: "..."}]
        content_blocks = raw.get("content") or []
        text_parts = [
            b.get("text", "") for b in content_blocks
            if b.get("type") == "text"
        ]
        content = "\n".join(text_parts)

        usage = raw.get("usage") or {}
        return LLMResponse(
            content=content,
            finish_reason=raw.get("stop_reason", "end_turn"),
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
            },
            raw_response=raw,
        )

    async def _parse_stream_response(self, raw_text: str) -> LLMStreamChunk | None:
        """解析 Anthropic SSE 流式事件

        Anthropic SSE 事件类型:
        - message_start: 消息开始（含 usage）
        - content_block_start: 内容块开始
        - content_block_delta: 内容增量（text_delta）
        - content_block_stop: 内容块结束
        - message_delta: 消息增量（含 stop_reason）
        - message_stop: 消息结束
        - ping: 心跳
        """
        if not raw_text.startswith("{"):
            return None
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return None

        event_type = data.get("type", "")

        if event_type == "content_block_delta":
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta":
                return LLMStreamChunk(content=delta.get("text", ""))

        elif event_type == "message_delta":
            delta = data.get("delta") or {}
            return LLMStreamChunk(
                content="",
                finish_reason=delta.get("stop_reason", "end_turn"),
            )

        elif event_type == "message_stop":
            return LLMStreamChunk(content="", finish_reason="end_turn")

        elif event_type == "ping":
            return None  # 心跳，忽略

        return None
