import hashlib

import json

import logging

from collections.abc import AsyncIterator

from typing import Dict, Optional



import httpx



from app.config import settings

from app.embedding_loader import load_embedder

from app.services.llm_gateway import GatewayNode, get_llm_gateway



logger = logging.getLogger(__name__)



RESPONSE_CACHE: Dict[str, str] = {}

CACHE_MAX_SIZE = 500





def _normalize_base_url(base_url: str) -> str:

    u = (base_url or "").strip().rstrip("/")

    for suffix in ("/chat/completions", "/responses"):

        if u.endswith(suffix):

            u = u[: -len(suffix)].rstrip("/")

    return u





def _openai_chat_url(base_url: str) -> str:

    return f"{_normalize_base_url(base_url)}/chat/completions"





class LLMWrapper:

    def __init__(self):

        self._last_node: GatewayNode | None = None



    @property

    def last_node(self) -> GatewayNode | None:

        return self._last_node



    def _resolve_node(self, task_type: str = "qa") -> GatewayNode | None:

        node = get_llm_gateway().choose(task_type)

        self._last_node = node

        return node



    def _get_cache_key(self, prompt: str, temperature: float) -> str:

        return hashlib.md5(f"{prompt}:{temperature}".encode()).hexdigest()



    def _sync_chat(self, node: GatewayNode, messages: list[dict], temperature: float, max_tokens: int) -> str:

        payload = {

            "model": node.model,

            "messages": messages,

            "stream": False,

            "temperature": temperature,

            "max_tokens": max_tokens,

        }

        url = _openai_chat_url(node.base_url)

        headers = {

            "Authorization": f"Bearer {node.api_key}",

            "Content-Type": "application/json",

        }

        with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS, trust_env=False) as client:
            import time

            from app.services.agent_call_logger import log_agent_call

            t0 = time.perf_counter()
            ok = True
            err = ""
            try:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    ok = False
                    err = f"HTTP {resp.status_code}"
                    raise httpx.HTTPStatusError(err, request=resp.request, response=resp)
                data = resp.json()
                content = str(data["choices"][0]["message"]["content"]).strip()
                usage = data.get("usage") or {}
                tokens = int(usage.get("total_tokens") or len(content) // 2)
                log_agent_call(
                    api_type="llm",
                    target=f"{node.provider}:{node.model}",
                    request_summary=payload["messages"][-1]["content"][:500] if payload.get("messages") else "",
                    response_summary=content[:500],
                    time_consume_ms=int((time.perf_counter() - t0) * 1000),
                    success=ok,
                    error_message=err,
                    tokens=tokens,
                )
                return content
            except Exception as exc:
                log_agent_call(
                    api_type="llm",
                    target=f"{node.provider}:{node.model}",
                    request_summary=str(payload.get("messages", ""))[:500],
                    response_summary="",
                    time_consume_ms=int((time.perf_counter() - t0) * 1000),
                    success=False,
                    error_message=str(exc)[:300],
                )
                raise



    def call(self, prompt: str, temperature: float = 0.1, max_tokens: int = 1024, task_type: str = "qa") -> str:

        cache_key = self._get_cache_key(prompt, temperature)

        if cache_key in RESPONSE_CACHE:

            return RESPONSE_CACHE[cache_key]

        node = self._resolve_node(task_type)

        if not node or not node.api_key:

            return "【配置错误】请在 .env 中配置 QWEN_API_KEY 或 ARK_API_KEY。"

        try:

            result = self._sync_chat(

                node,

                [{"role": "user", "content": prompt}],

                temperature,

                max_tokens,

            )

            if len(RESPONSE_CACHE) >= CACHE_MAX_SIZE:

                RESPONSE_CACHE.clear()

            RESPONSE_CACHE[cache_key] = result

            return result

        except Exception as e:

            logger.error(

                "[智能客服-对话|llms|LLM|工具执行|同步] 调用失败; provider=%s; model=%s; error=%s",

                node.provider,

                node.model,

                e,

            )

            return "服务暂时不可用，请稍后重试。"



    async def stream_chat(self, messages: list[dict[str, str]], task_type: str = "qa") -> AsyncIterator[str]:

        node = self._resolve_node(task_type)

        if not node or not node.api_key:

            yield "【配置错误】请在 .env 中配置 QWEN_API_KEY 或 ARK_API_KEY。"

            return



        # 限制输入大小避免超出豆包4K上下文
        trimmed = []
        total = 0
        max_in = 3000
        for m in reversed(messages):
            c = str(m.get("content", ""))
            if total + len(c) > max_in:
                r = max_in - total
                if r > 50: trimmed.insert(0, {**m, "content": c[:r]})
                break
            trimmed.insert(0, m)
            total += len(c)

        payload = {
            "model": node.model,
            "messages": trimmed,
            "stream": True,
            "temperature": 0.2,
            "max_tokens": 1024,
        }

        url = _openai_chat_url(node.base_url)

        headers = {

            "Authorization": f"Bearer {node.api_key}",

            "Content-Type": "application/json",

        }

        try:
            import time

            from app.services.agent_call_logger import log_agent_call

            t0 = time.perf_counter()
            parts: list[str] = []
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS, trust_env=False) as client:

                async with client.stream("POST", url, headers=headers, json=payload) as resp:

                    if resp.status_code >= 400:

                        body = await resp.aread()

                        logger.error(

                            "[智能客服-对话|llms|LLM|工具执行|流式] HTTP错误; status=%s; provider=%s; model=%s; body=%s",

                            resp.status_code,

                            node.provider,

                            node.model,

                            body[:300],

                        )

                        yield f"【服务异常】大模型暂时不可用（{node.name}）。"

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
                                parts.append(delta)
                                yield delta

                        except (json.JSONDecodeError, KeyError, IndexError):

                            continue

        except httpx.TimeoutException:

            yield "【请求超时】大模型响应超时，请稍后重试。"

        except httpx.HTTPError as exc:

            logger.error(

                "[智能客服-对话|llms|LLM|工具执行|流式] 网络错误; provider=%s; error=%s",

                node.provider,

                exc,

            )

            yield "【网络错误】无法连接大模型服务，请检查网络或 API Key。"
        finally:
            try:
                from app.services.agent_call_logger import log_agent_call

                full = "".join(parts)
                log_agent_call(
                    api_type="llm",
                    target=f"{node.provider}:{node.model}",
                    request_summary=str(messages[-1].get("content", ""))[:500] if messages else "",
                    response_summary=full[:500],
                    time_consume_ms=int((time.perf_counter() - t0) * 1000),
                    success=bool(full),
                    tokens=max(1, len(full) // 2),
                )
            except Exception:
                pass





_llm_wrapper: Optional[LLMWrapper] = None





def get_llm() -> LLMWrapper:

    global _llm_wrapper

    if _llm_wrapper is None:

        _llm_wrapper = LLMWrapper()

    return _llm_wrapper





_embedder = None


def get_pipeline_llm():
    """意图识别/Query改写专用LLM：优先Ollama本地模型(快)，否则走网关"""
    ollama_base = os.getenv("OLLAMA_BASE_URL", "").strip()
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen2:0.5b").strip()
    if ollama_base and ollama_model:
        from app.services.llm_gateway import GatewayNode
        node = GatewayNode(
            id="ollama_pipeline", name="Ollama Pipeline", provider="openai_compatible",
            base_url=ollama_base, api_key="ollama", model=ollama_model,
            priority=1, weight=100, status="active",
        )
        logger.info("[LLM-Pipeline] 使用Ollama本地模型: %s @ %s", ollama_model, ollama_base)
        return node
    return None





def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = _instrument_embedder(load_embedder())
    return _embedder


def _instrument_embedder(embedder):
    """为嵌入模型方法挂载 EVAL 装饰器（RAG 链路的 embedding 步骤）。"""
    from app.config import settings
    from app.services.agent_call_logger import track_agent_call

    target = settings.EMBEDDING_MODEL or "bge"

    class _InstrumentedEmbeddings:
        """包装嵌入器，避免 Pydantic v2 模型禁止 setattr 导致 embed_query 挂载失败。"""

        def __init__(self, inner):
            self._inner = inner
            self.embed_query = track_agent_call(
                api_type="embedding",
                target=target,
                tool_name="embed_query",
                request_fn=lambda a, k: str(a[0] if a else k.get("text", ""))[:300],
                extra_fn=lambda vec, a, k: {"dims": len(vec) if isinstance(vec, list) else 0},
            )(inner.embed_query)
            self.embed_documents = track_agent_call(
                api_type="embedding",
                target=target,
                tool_name="embed_documents",
                request_fn=lambda a, k: f"batch={len(a[0]) if a and a[0] else len(k.get('texts') or [])}",
                extra_fn=lambda vecs, a, k: {"doc_count": len(vecs) if isinstance(vecs, list) else 0},
            )(inner.embed_documents)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    try:
        embedder.embed_query = track_agent_call(
            api_type="embedding",
            target=target,
            tool_name="embed_query",
            request_fn=lambda a, k: str(a[0] if a else k.get("text", ""))[:300],
            extra_fn=lambda vec, a, k: {"dims": len(vec) if isinstance(vec, list) else 0},
        )(embedder.embed_query)

        embedder.embed_documents = track_agent_call(
            api_type="embedding",
            target=target,
            tool_name="embed_documents",
            request_fn=lambda a, k: f"batch={len(a[0]) if a and a[0] else len(k.get('texts') or [])}",
            extra_fn=lambda vecs, a, k: {"doc_count": len(vecs) if isinstance(vecs, list) else 0},
        )(embedder.embed_documents)
        return embedder
    except (AttributeError, TypeError, ValueError):
        return _InstrumentedEmbeddings(embedder)

