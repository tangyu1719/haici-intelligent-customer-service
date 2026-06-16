import hashlib
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Dict, Literal, Optional


@dataclass(frozen=True)
class LLMStreamDelta:
    """流式增量：DeepSeek 等模型 reasoning 与正文分离。"""

    kind: Literal["think", "answer"]
    content: str

import httpx

from app.config import settings
from app.embedding_loader import load_embedder
from app.services.chat_context import trim_messages_to_budget
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





def _is_thinking_model(node: GatewayNode) -> bool:
    """判断是否支持 reasoning_content 深度思考流。"""
    blob = f"{node.name} {node.model}".lower()
    return any(k in blob for k in ("deepseek", "r1", "reason", "thinking"))


def _pick_stream_text(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for k in ("content", "text", "reasoning_content", "reasoning", "thinking_content"):
            if val.get(k):
                return str(val[k])
        return ""
    return str(val)


# 网关流式 delta / message 中「思考过程」与「正文」字段映射（OpenAI 兼容 + 火山方舟 DeepSeek）
REASONING_DELTA_KEYS = (
    "reasoning_content",
    "reasoning",
    "thinking_content",
    "thinking",
    "reasoning_text",
    "thought",
)
ANSWER_DELTA_KEYS = ("content", "text", "output_text")


def _split_stream_delta(delta_obj: dict, message_obj: dict | None = None) -> tuple[str, str]:
    """从 OpenAI 兼容 delta / message 中拆分思考与正文。"""
    reasoning = ""
    for key in REASONING_DELTA_KEYS:
        raw = delta_obj.get(key)
        if raw:
            reasoning = _pick_stream_text(raw)
            break
    if not reasoning and message_obj:
        for key in REASONING_DELTA_KEYS:
            raw = message_obj.get(key)
            if raw:
                reasoning = _pick_stream_text(raw)
                break

    content = ""
    for key in ANSWER_DELTA_KEYS:
        raw = delta_obj.get(key)
        if raw:
            content = _pick_stream_text(raw)
            break
    if not content and message_obj:
        for key in ANSWER_DELTA_KEYS:
            raw = message_obj.get(key)
            if raw:
                content = _pick_stream_text(raw)
                break

    return reasoning, content


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



    def _sync_chat(
        self,
        node: GatewayNode,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        task_type: str = "qa",
    ) -> str:
        from app.services.gateway_circuit_breaker import breaker
        from app.services.llm_error_recovery import (
            LLMCallError,
            RecoveryAction,
            RecoveryState,
            classify_http_error,
            plan_recovery,
            run_recovery_step,
        )

        url = _openai_chat_url(node.base_url)
        headers = {
            "Authorization": f"Bearer {node.api_key}",
            "Content-Type": "application/json",
        }
        state = RecoveryState()
        current_node = node
        current_messages = list(messages)
        current_max_tokens = max_tokens
        current_temperature = temperature
        max_loops = 6

        with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS, trust_env=False) as client:
            import time

            from app.services.agent_call_logger import log_agent_call

            t0 = time.perf_counter()
            last_exc: Exception | None = None

            for loop_idx in range(max_loops):
                payload = {
                    "model": current_node.model,
                    "messages": current_messages,
                    "stream": False,
                    "temperature": current_temperature,
                    "max_tokens": current_max_tokens,
                }
                try:
                    resp = client.post(url, headers={
                        **headers,
                        "Authorization": f"Bearer {current_node.api_key}",
                    }, json=payload)
                    if resp.status_code >= 400:
                        body = resp.text or ""
                        error_code, msg, _ = classify_http_error(
                            current_node.provider,
                            current_node.id,
                            resp.status_code,
                            body,
                        )
                        plan = plan_recovery(
                            error_code,
                            attempt=loop_idx + 1,
                            retries_used=state.retries_used,
                            switches_used=state.switches_used,
                            ops_used=state.ops_used,
                            context={"messages_count": len(current_messages)},
                        )
                        if plan.action == RecoveryAction.ABORT:
                            raise LLMCallError(
                                error_code,
                                msg,
                                provider=current_node.provider,
                                node_id=current_node.id,
                                detail=body[:300],
                            )
                        current_messages, current_max_tokens, current_temperature, new_node_id = run_recovery_step(
                            plan,
                            state,
                            messages=current_messages,
                            max_tokens=current_max_tokens,
                            temperature=current_temperature,
                            task_type=task_type,
                            error_code=error_code,
                            provider=current_node.provider,
                            node_id=current_node.id,
                            status_code=resp.status_code,
                            response_body=body,
                        )
                        if new_node_id:
                            fallback = get_llm_gateway().nodes.get(new_node_id)
                            if fallback:
                                current_node = fallback
                                self._last_node = fallback
                                url = _openai_chat_url(current_node.base_url)
                        continue

                    data = resp.json()
                    content = str(data["choices"][0]["message"]["content"]).strip()
                    usage = data.get("usage") or {}
                    tokens = int(usage.get("total_tokens") or len(content) // 2)
                    breaker.get_or_create(current_node.id).record_success()
                    log_agent_call(
                        api_type="llm",
                        target=f"{current_node.provider}:{current_node.model}",
                        request_summary=payload["messages"][-1]["content"][:500] if payload.get("messages") else "",
                        response_summary=content[:500],
                        time_consume_ms=int((time.perf_counter() - t0) * 1000),
                        success=True,
                        error_message="",
                        tokens=tokens,
                    )
                    return content
                except httpx.TimeoutException as exc:
                    last_exc = exc
                    error_code, msg, _ = classify_http_error(
                        current_node.provider,
                        current_node.id,
                        0,
                        "",
                        str(exc),
                    )
                    plan = plan_recovery(
                        error_code,
                        attempt=loop_idx + 1,
                        retries_used=state.retries_used,
                        switches_used=state.switches_used,
                        ops_used=state.ops_used,
                    )
                    if plan.action == RecoveryAction.ABORT:
                        raise LLMCallError(
                            error_code,
                            msg,
                            provider=current_node.provider,
                            node_id=current_node.id,
                            detail=str(exc)[:300],
                        ) from exc
                    current_messages, current_max_tokens, current_temperature, new_node_id = run_recovery_step(
                        plan,
                        state,
                        messages=current_messages,
                        max_tokens=current_max_tokens,
                        temperature=current_temperature,
                        task_type=task_type,
                        error_code=error_code,
                        provider=current_node.provider,
                        node_id=current_node.id,
                        status_code=0,
                        response_body="",
                    )
                    if new_node_id:
                        fallback = get_llm_gateway().nodes.get(new_node_id)
                        if fallback:
                            current_node = fallback
                            self._last_node = fallback
                            url = _openai_chat_url(current_node.base_url)
                    continue
                except LLMCallError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    log_agent_call(
                        api_type="llm",
                        target=f"{current_node.provider}:{current_node.model}",
                        request_summary=str(payload.get("messages", ""))[:500],
                        response_summary="",
                        time_consume_ms=int((time.perf_counter() - t0) * 1000),
                        success=False,
                        error_message=str(exc)[:300],
                    )
                    raise

            log_agent_call(
                api_type="llm",
                target=f"{current_node.provider}:{current_node.model}",
                request_summary=str(messages)[:500],
                response_summary="",
                time_consume_ms=int((time.perf_counter() - t0) * 1000),
                success=False,
                error_message=str(last_exc or "recovery_exhausted")[:300],
            )
            raise LLMCallError(
                classify_http_error(current_node.provider, current_node.id, 0, "", "recovery_exhausted")[0],
                "LLM 错误恢复次数已用尽",
                provider=current_node.provider,
                node_id=current_node.id,
            )



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

                task_type=task_type,

            )

            if len(RESPONSE_CACHE) >= CACHE_MAX_SIZE:

                RESPONSE_CACHE.clear()

            RESPONSE_CACHE[cache_key] = result

            return result

        except Exception as e:
            from app.services.llm_error_recovery import LLMCallError

            if isinstance(e, LLMCallError):
                logger.error(
                    "[智能客服-对话|llms|LLM|工具执行|同步] 恢复失败; code=%s; provider=%s; node=%s; error=%s",
                    e.error_code.value,
                    e.provider,
                    e.node_id,
                    e.message,
                )
                return f"AI服务异常 [{e.error_code.value}]: {e.message}"

            logger.error(

                "[智能客服-对话|llms|LLM|工具执行|同步] 调用失败; provider=%s; model=%s; error=%s",

                node.provider,

                node.model,

                e,

            )

            return "服务暂时不可用，请稍后重试。"



    def _resolve_input_budget(self, node: GatewayNode, task_type: str) -> tuple[int, int]:
        """按节点上下文上限计算输入字符预算与输出 token 上限。"""
        ctx = node.context_chars or int(settings.CHAT_MAX_CONTEXT_CHARS)
        reserve = max(0, int(settings.CHAT_CONTEXT_RESERVE_CHARS))
        out_tokens = node.max_output_tokens or (512 if task_type == "qa" else 1024)
        out_chars = out_tokens * 2
        max_in = max(2048, ctx - reserve - out_chars)
        return max_in, out_tokens

    async def stream_chat(self, messages: list[dict[str, str]], task_type: str = "qa") -> AsyncIterator[LLMStreamDelta]:

        node = self._resolve_node(task_type)

        if not node or not node.api_key:

            yield LLMStreamDelta("answer", "【配置错误】请在 .env 中配置 QWEN_API_KEY 或 ARK_API_KEY。")

            return



        # 按模型实际上下文上限裁剪输入（session_context 已做摘要+滑动窗口）
        max_in, max_out = self._resolve_input_budget(node, task_type)
        trimmed = trim_messages_to_budget(messages, max_in)

        payload = {
            "model": node.model,
            "messages": trimmed,
            "stream": True,
            "temperature": 0.2,
            "max_tokens": max_out,
        }
        if _is_thinking_model(node) and task_type not in ("qa",):
            payload["thinking"] = {"type": "enabled"}

        url = _openai_chat_url(node.base_url)

        headers = {

            "Authorization": f"Bearer {node.api_key}",

            "Content-Type": "application/json",

        }

        try:
            import time

            from app.services.agent_call_logger import log_agent_call

            t0 = time.perf_counter()
            answer_parts: list[str] = []
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS, trust_env=False) as client:

                async with client.stream("POST", url, headers=headers, json=payload) as resp:

                    if resp.status_code >= 400:

                        body_bytes = await resp.aread()
                        body = body_bytes.decode("utf-8", errors="replace")
                        from app.services.llm_error_recovery import (
                            LLMCallError,
                            RecoveryAction,
                            RecoveryState,
                            classify_http_error,
                            plan_recovery,
                            run_recovery_step,
                        )

                        error_code, msg, _ = classify_http_error(
                            node.provider, node.id, resp.status_code, body
                        )
                        state = RecoveryState()
                        plan = plan_recovery(error_code, ops_used=False)
                        if plan.action != RecoveryAction.ABORT:
                            try:
                                new_msgs, new_max, new_temp, new_node_id = run_recovery_step(
                                    plan,
                                    state,
                                    messages=trimmed,
                                    max_tokens=max_out,
                                    temperature=0.2,
                                    task_type=task_type,
                                    error_code=error_code,
                                    provider=node.provider,
                                    node_id=node.id,
                                    status_code=resp.status_code,
                                    response_body=body,
                                )
                                if new_node_id:
                                    fb = get_llm_gateway().nodes.get(new_node_id)
                                    if fb:
                                        node = fb
                                        self._last_node = fb
                                trimmed = new_msgs
                                max_out = new_max
                                payload["messages"] = trimmed
                                payload["max_tokens"] = max_out
                                payload["temperature"] = new_temp
                                url = _openai_chat_url(node.base_url)
                                headers["Authorization"] = f"Bearer {node.api_key}"
                                async with client.stream("POST", url, headers=headers, json=payload) as resp2:
                                    if resp2.status_code < 400:
                                        async for line in resp2.aiter_lines():
                                            if not line or not line.startswith("data:"):
                                                continue
                                            data = line[5:].strip()
                                            if data == "[DONE]":
                                                break
                                            try:
                                                chunk = json.loads(data)
                                                choice = chunk["choices"][0]
                                                delta_obj = choice.get("delta") or {}
                                                message_obj = choice.get("message") or {}
                                                reasoning, content = _split_stream_delta(delta_obj, message_obj)
                                                if reasoning:
                                                    yield LLMStreamDelta("think", reasoning)
                                                if content:
                                                    answer_parts.append(content)
                                                    yield LLMStreamDelta("answer", content)
                                            except (json.JSONDecodeError, KeyError, IndexError):
                                                continue
                                        return
                            except LLMCallError:
                                pass

                        logger.error(

                            "[智能客服-对话|llms|LLM|工具执行|流式] HTTP错误; status=%s; provider=%s; model=%s; code=%s; body=%s",

                            resp.status_code,

                            node.provider,

                            node.model,

                            error_code.value,

                            body[:300],

                        )

                        yield LLMStreamDelta("answer", f"AI服务异常 [{error_code.value}]: {msg}")

                        return

                    async for line in resp.aiter_lines():

                        if not line or not line.startswith("data:"):

                            continue

                        data = line[5:].strip()

                        if data == "[DONE]":

                            break

                        try:

                            chunk = json.loads(data)

                            choice = chunk["choices"][0]
                            delta_obj = choice.get("delta") or {}
                            message_obj = choice.get("message") or {}

                            reasoning, content = _split_stream_delta(delta_obj, message_obj)

                            if reasoning:
                                yield LLMStreamDelta("think", reasoning)
                            if content:
                                answer_parts.append(content)
                                yield LLMStreamDelta("answer", content)

                        except (json.JSONDecodeError, KeyError, IndexError):

                            continue

        except httpx.TimeoutException:
            from app.services.gateway_error_handler import ErrorCode
            from app.services.llm_error_recovery import classify_http_error

            code, msg, _ = classify_http_error(
                node.provider if node else "ark",
                node.id if node else "unknown",
                0,
                "",
                "timed out",
            )
            yield LLMStreamDelta("answer", f"AI服务异常 [{code.value}]: {msg}")

        except httpx.HTTPError as exc:

            logger.error(

                "[智能客服-对话|llms|LLM|工具执行|流式] 网络错误; provider=%s; error=%s",

                node.provider,

                exc,

            )

            yield LLMStreamDelta("answer", "【网络错误】无法连接大模型服务，请检查网络或 API Key。")
        finally:
            try:
                from app.services.agent_call_logger import log_agent_call

                full = "".join(answer_parts)
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
    """意图识别/Query 改写专用 LLM：优先 Ollama 本地（毫秒级），失败再走主网关。"""
    ollama_base = (os.getenv("OLLAMA_BASE_URL", "") or settings.OLLAMA_BASE_URL).strip()
    ollama_model = (os.getenv("OLLAMA_MODEL", "") or settings.OLLAMA_MODEL).strip()
    if not ollama_base or not ollama_model:
        return None
    from app.services.llm_gateway import GatewayNode

    node = GatewayNode(
        id="ollama_pipeline",
        name="Ollama Pipeline",
        provider="openai_compatible",
        base_url=ollama_base,
        api_key="ollama",
        model=ollama_model,
        priority=1,
        weight=100,
        status="active",
    )
    return node





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

