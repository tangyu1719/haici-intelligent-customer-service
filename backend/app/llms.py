import hashlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Dict, Optional

import httpx
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

RESPONSE_CACHE: Dict[str, str] = {}
CACHE_MAX_SIZE = 500


class LLMWrapper:
    def __init__(self):
        self._llm_instance = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm_instance is None:
            self._llm_instance = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "EMPTY",
                base_url=settings.LLM_BASE_URL,
                temperature=0.1,
                max_tokens=1024,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=1,
            )
        return self._llm_instance

    def _get_cache_key(self, prompt: str, temperature: float) -> str:
        return hashlib.md5(f"{prompt}:{temperature}".encode()).hexdigest()

    def call(self, prompt: str, temperature: float = 0.1, max_tokens: int = 1024) -> str:
        cache_key = self._get_cache_key(prompt, temperature)
        if cache_key in RESPONSE_CACHE:
            return RESPONSE_CACHE[cache_key]
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            result = response.content.strip()
            if len(RESPONSE_CACHE) >= CACHE_MAX_SIZE:
                RESPONSE_CACHE.clear()
            RESPONSE_CACHE[cache_key] = result
            return result
        except Exception as e:
            logger.error("[智能客服-对话|llms|LLM|工具执行|同步] 调用失败; error=%s", e)
            return "服务暂时不可用，请稍后重试。"

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not settings.LLM_API_KEY:
            yield "【配置错误】请在 .env 中设置 LLM_API_KEY。"
            return
        payload = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
        }
        url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        yield "【服务异常】大模型暂时不可用，请稍后重试。"
                        return
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content")
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except httpx.TimeoutException:
            yield "【请求超时】大模型响应超时，请稍后重试。"
        except httpx.HTTPError as exc:
            logger.error("[智能客服-对话|llms|LLM|工具执行|流式] 网络错误; error=%s", exc)
            yield "【网络错误】无法连接大模型服务。"


_llm_wrapper: Optional[LLMWrapper] = None


def get_llm() -> LLMWrapper:
    global _llm_wrapper
    if _llm_wrapper is None:
        _llm_wrapper = LLMWrapper()
    return _llm_wrapper


_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        model_name = settings.EMBEDDING_MODEL
        logger.info("[智能客服-RAG|llms|Embedding|硬编执行|初始化] 加载模型; model=%s", model_name)
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError:
            from langchain_community.embeddings import HuggingFaceEmbeddings
        _embedder = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedder
