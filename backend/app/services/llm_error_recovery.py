"""LLM 错误恢复 — 规则重试 + 网关节点切换 + 运维 Agent 调参（SPEC §5）

调用方收到 ARK/OpenAI 兼容错误后：
1. normalize_error → 标准错误码
2. plan_recovery → 恢复动作（规则 / 切换节点 / ops_agent）
3. execute 层按 plan 重试或降级
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from app.services.gateway_circuit_breaker import breaker
from app.services.gateway_error_handler import (
    ErrorCode,
    ErrorStrategy,
    describe_error,
    get_strategy,
    normalize_error,
)

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


class RecoveryAction(str, Enum):
    """错误恢复动作"""
    RETRY = "retry"                      # 规则：同节点退避重试
    SWITCH_NODE = "switch_node"          # 规则：切换网关节点（限流/配额/熔断）
    TRUNCATE_RETRY = "truncate_retry"    # 规则：截断上下文后重试
    OPS_AGENT = "ops_agent"              # 智能运维：诊断并修正入参
    ABORT = "abort"                      # 不可自动恢复


class LLMCallError(Exception):
    """带标准错误码的 LLM 调用失败"""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        *,
        provider: str = "",
        node_id: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.provider = provider
        self.node_id = node_id
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        base = describe_error(self.error_code, self.provider, self.detail)
        base["node_id"] = self.node_id
        return base


@dataclass
class RecoveryPlan:
    """单次错误对应的恢复计划"""
    action: RecoveryAction
    error_code: ErrorCode
    strategy: ErrorStrategy
    message: str
    backoff_seconds: int = 0
    attempt: int = 1
    max_attempts: int = 1
    ops_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpsDiagnosis:
    """运维 Agent 诊断结果（结构化）"""
    fault_type: str = ""
    root_cause: str = ""
    fix_actions: list[str] = field(default_factory=list)
    param_patches: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""

    @property
    def has_param_patches(self) -> bool:
        return bool(self.param_patches)


def plan_recovery(
    error_code: ErrorCode,
    *,
    attempt: int = 1,
    retries_used: int = 0,
    switches_used: int = 0,
    ops_used: bool = False,
    context: dict[str, Any] | None = None,
) -> RecoveryPlan:
    """根据错误码与已消耗次数，决定下一步恢复动作。"""
    strategy = get_strategy(error_code)
    ctx = context or {}

    # ── 规则：超时 / 服务端故障 → 同节点退避重试 ──
    if error_code == ErrorCode.LLM_TIMEOUT:
        if retries_used < strategy.max_retries:
            return RecoveryPlan(
                action=RecoveryAction.RETRY,
                error_code=error_code,
                strategy=strategy,
                message=strategy.message,
                backoff_seconds=strategy.backoff_seconds,
                attempt=attempt,
                max_attempts=strategy.max_retries + 1,
            )
        if switches_used < 1:
            return RecoveryPlan(
                action=RecoveryAction.SWITCH_NODE,
                error_code=error_code,
                strategy=strategy,
                message="超时后切换备用节点",
                attempt=attempt,
            )
        return _abort_plan(error_code, strategy, "超时重试与切换节点均已用尽")

    # ── 规则：限流 / 配额 → 网关智能切换节点 ──
    if error_code in (ErrorCode.LLM_RATE_LIMIT, ErrorCode.LLM_QUOTA):
        if switches_used < max(1, strategy.max_retries + 1):
            backoff = strategy.backoff_seconds if error_code == ErrorCode.LLM_RATE_LIMIT else 0
            return RecoveryPlan(
                action=RecoveryAction.SWITCH_NODE,
                error_code=error_code,
                strategy=strategy,
                message=strategy.message,
                backoff_seconds=backoff,
                attempt=attempt,
            )
        return _abort_plan(error_code, strategy, "限流/配额：备用节点已尝试")

    # ── 规则：响应乱码 → 重试一次再切换 ──
    if error_code == ErrorCode.LLM_MALFORMED:
        if retries_used < strategy.max_retries:
            return RecoveryPlan(
                action=RecoveryAction.RETRY,
                error_code=error_code,
                strategy=strategy,
                message=strategy.message,
                backoff_seconds=strategy.backoff_seconds,
                attempt=attempt,
            )
        if switches_used < 1:
            return RecoveryPlan(
                action=RecoveryAction.SWITCH_NODE,
                error_code=error_code,
                strategy=strategy,
                message="响应异常，切换节点重试",
                attempt=attempt,
            )
        return _abort_plan(error_code, strategy, "响应异常无法恢复")

    # ── 规则：上下文过长 → 截断后重试 ──
    if error_code == ErrorCode.LLM_CONTEXT_OVERFLOW:
        if retries_used < strategy.max_retries:
            return RecoveryPlan(
                action=RecoveryAction.TRUNCATE_RETRY,
                error_code=error_code,
                strategy=strategy,
                message=strategy.message,
                attempt=attempt,
            )
        return _abort_plan(error_code, strategy, "上下文截断后仍超限")

    # ── 智能运维：入参错误 → ops_agent 调参 ──
    if error_code == ErrorCode.LLM_INVALID_REQUEST:
        if not ops_used:
            return RecoveryPlan(
                action=RecoveryAction.OPS_AGENT,
                error_code=error_code,
                strategy=strategy,
                message="请求参数有误，调用运维 Agent 诊断调参",
                attempt=attempt,
                ops_context=ctx,
            )
        return _abort_plan(error_code, strategy, "运维 Agent 调参后仍失败")

    # ── 未知错误：重试 + 切换 ──
    if error_code == ErrorCode.LLM_UNKNOWN:
        if retries_used < strategy.max_retries:
            return RecoveryPlan(
                action=RecoveryAction.RETRY,
                error_code=error_code,
                strategy=strategy,
                message=strategy.message,
                backoff_seconds=strategy.backoff_seconds,
                attempt=attempt,
            )
        if switches_used < 1:
            return RecoveryPlan(
                action=RecoveryAction.SWITCH_NODE,
                error_code=error_code,
                strategy=strategy,
                message="未知错误，切换节点重试",
                attempt=attempt,
            )
        return _abort_plan(error_code, strategy, "未知错误无法恢复")

    # 内容审查 / 鉴权 / 质量 → 直接终止
    return _abort_plan(error_code, strategy, strategy.message)


def _abort_plan(code: ErrorCode, strategy: ErrorStrategy, message: str) -> RecoveryPlan:
    return RecoveryPlan(
        action=RecoveryAction.ABORT,
        error_code=code,
        strategy=strategy,
        message=message,
    )


def classify_http_error(
    provider: str,
    node_id: str,
    status_code: int,
    response_body: str,
    exception_msg: str = "",
) -> tuple[ErrorCode, str, dict[str, Any]]:
    """标准化错误并更新熔断器，返回 (code, message, breaker_result)。"""
    error_code, message = normalize_error(provider, status_code, response_body, exception_msg)
    breaker_result = breaker.handle_response(
        node_id, provider, status_code, response_body, exception_msg
    )
    logger.warning(
        "[智能客服-LLM|llm_error_recovery|classify|硬编执行|完成] node=%s; code=%s; retry=%s; switch=%s",
        node_id,
        error_code.value,
        get_strategy(error_code).retry,
        get_strategy(error_code).switch_node,
    )
    return error_code, message, breaker_result


def apply_context_truncation(messages: list[dict[str, str]], ratio: float = 0.7) -> list[dict[str, str]]:
    """按字符比例截断 user/assistant 历史，保留 system 与最后一条 user。"""
    if not messages or ratio >= 1.0:
        return list(messages)
    out: list[dict[str, str]] = []
    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    out.extend(system_msgs)
    if not rest:
        return out
    keep_from = max(0, int(len(rest) * (1.0 - ratio)))
    trimmed = rest[keep_from:]
    if trimmed and trimmed[0].get("role") != "user":
        for i, m in enumerate(rest):
            if m.get("role") == "user":
                trimmed = rest[i:]
                break
    for m in trimmed:
        content = str(m.get("content") or "")
        max_len = max(256, int(len(content) * ratio))
        if len(content) > max_len:
            out.append({"role": m["role"], "content": content[:max_len]})
        else:
            out.append(dict(m))
    return out


def apply_param_patches(
    messages: list[dict[str, str]],
    patches: dict[str, Any],
    *,
    max_tokens: int,
    temperature: float,
) -> tuple[list[dict[str, str]], int, float]:
    """应用运维 Agent 建议的参数修正。"""
    new_messages = list(messages)
    new_max_tokens = max_tokens
    new_temperature = temperature

    if patches.get("truncate_context"):
        new_messages = apply_context_truncation(new_messages, float(patches.get("truncate_ratio") or 0.6))

    if patches.get("max_tokens"):
        try:
            new_max_tokens = max(128, min(int(patches["max_tokens"]), max_tokens))
        except (TypeError, ValueError):
            pass

    if patches.get("temperature") is not None:
        try:
            new_temperature = float(patches["temperature"])
        except (TypeError, ValueError):
            pass

    # 移除超长单条 user 内容
    max_chars = patches.get("max_user_chars")
    if max_chars:
        try:
            limit = int(max_chars)
            fixed: list[dict[str, str]] = []
            for m in new_messages:
                content = str(m.get("content") or "")
                if m.get("role") == "user" and len(content) > limit:
                    fixed.append({"role": "user", "content": content[:limit]})
                else:
                    fixed.append(dict(m))
            new_messages = fixed
        except (TypeError, ValueError):
            pass

    return new_messages, new_max_tokens, new_temperature


def _parse_ops_json(text: str) -> OpsDiagnosis:
    diagnosis = OpsDiagnosis(raw_text=text)
    if not text:
        return diagnosis
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return diagnosis
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return diagnosis
    if not isinstance(data, dict):
        return diagnosis
    diagnosis.fault_type = str(data.get("fault_type") or "")
    diagnosis.root_cause = str(data.get("root_cause") or "")
    actions = data.get("fix_actions") or []
    if isinstance(actions, list):
        diagnosis.fix_actions = [str(a) for a in actions if str(a).strip()]
    patches = data.get("param_patches") or {}
    if isinstance(patches, dict):
        diagnosis.param_patches = patches
    return diagnosis


def invoke_ops_agent_diagnosis(
    *,
    error_code: ErrorCode,
    provider: str,
    node_id: str,
    status_code: int,
    response_body: str,
    messages: list[dict[str, str]],
    task_type: str,
    llm_call: Callable[[str, str], str] | None = None,
) -> OpsDiagnosis:
    """调用 ops_agent 生成调参建议。llm_call 可注入 mock（测试用）。"""
    from app.services.agent_prompt_registry import render_agent_prompt

    error_log = (
        f"error_code={error_code.value}; provider={provider}; node={node_id}; "
        f"http={status_code}; body={response_body[:800]}"
    )
    system_state = json.dumps(breaker.get(node_id).to_dict() if breaker.get(node_id) else {}, ensure_ascii=False)
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = str(m.get("content") or "")[:500]
            break
    context = f"task_type={task_type}; last_user={last_user}"

    base_prompt = render_agent_prompt(
        "ops_agent",
        error_log=error_log,
        system_state=system_state,
        context=context,
    )
    if not base_prompt:
        base_prompt = (
            "你是系统运维诊断 Agent。根据错误日志给出 JSON："
            '{"fault_type":"","root_cause":"","fix_actions":[],"param_patches":{}}'
        )

    prompt = (
        f"{base_prompt}\n\n"
        "【输出要求】仅输出一个 JSON 对象，字段：fault_type, root_cause, fix_actions(数组), "
        "param_patches(可含 max_tokens, temperature, truncate_context, truncate_ratio, max_user_chars)。"
    )

    if llm_call is None:
        from app.llms import get_llm

        raw = get_llm().call(prompt, temperature=0.1, max_tokens=512, task_type="reason")
    else:
        raw = llm_call(prompt, task_type)

    diagnosis = _parse_ops_json(raw)
    logger.info(
        "[智能客服-LLM|llm_error_recovery|ops_agent|Agent执行|完成] code=%s; patches=%s; actions=%s",
        error_code.value,
        list(diagnosis.param_patches.keys()),
        len(diagnosis.fix_actions),
    )
    return diagnosis


@dataclass
class RecoveryState:
    """跨重试循环的可变状态"""
    retries_used: int = 0
    switches_used: int = 0
    ops_used: bool = False
    exclude_node_ids: set[str] = field(default_factory=set)
    last_plan: RecoveryPlan | None = None
    last_diagnosis: OpsDiagnosis | None = None


def run_recovery_step(
    plan: RecoveryPlan,
    state: RecoveryState,
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    task_type: str,
    error_code: ErrorCode,
    provider: str,
    node_id: str,
    status_code: int,
    response_body: str,
    llm_call: Callable[[str, str], str] | None = None,
) -> tuple[list[dict[str, str]], int, float, str | None]:
    """执行单步恢复动作，返回 (messages, max_tokens, temperature, new_node_id)。"""
    state.last_plan = plan

    if plan.backoff_seconds > 0:
        time.sleep(plan.backoff_seconds)

    if plan.action == RecoveryAction.RETRY:
        state.retries_used += 1
        logger.info(
            "[智能客服-LLM|llm_error_recovery|retry|硬编执行|重试] code=%s; retry=%s",
            error_code.value,
            state.retries_used,
        )
        return messages, max_tokens, temperature, None

    if plan.action == RecoveryAction.SWITCH_NODE:
        state.switches_used += 1
        state.exclude_node_ids.add(node_id)
        from app.services.llm_gateway import get_llm_gateway

        fallback = get_llm_gateway().choose_fallback(task_type, exclude=state.exclude_node_ids)
        if not fallback:
            raise LLMCallError(
                error_code,
                "无可用备用网关节点",
                provider=provider,
                node_id=node_id,
                detail=response_body[:300],
            )
        logger.info(
            "[智能客服-LLM|llm_error_recovery|switch_node|硬编执行|切换] from=%s; to=%s; code=%s",
            node_id,
            fallback.id,
            error_code.value,
        )
        return messages, max_tokens, temperature, fallback.id

    if plan.action == RecoveryAction.TRUNCATE_RETRY:
        state.retries_used += 1
        truncated = apply_context_truncation(messages)
        logger.info(
            "[智能客服-LLM|llm_error_recovery|truncate|硬编执行|截断] msgs=%s→%s",
            len(messages),
            len(truncated),
        )
        return truncated, max_tokens, temperature, None

    if plan.action == RecoveryAction.OPS_AGENT:
        state.ops_used = True
        diagnosis = invoke_ops_agent_diagnosis(
            error_code=error_code,
            provider=provider,
            node_id=node_id,
            status_code=status_code,
            response_body=response_body,
            messages=messages,
            task_type=task_type,
            llm_call=llm_call,
        )
        state.last_diagnosis = diagnosis
        if diagnosis.has_param_patches:
            new_msgs, new_max, new_temp = apply_param_patches(
                messages, diagnosis.param_patches, max_tokens=max_tokens, temperature=temperature
            )
            return new_msgs, new_max, new_temp, None
        state.retries_used += 1
        return messages, max_tokens, temperature, None

    raise LLMCallError(
        error_code,
        plan.message,
        provider=provider,
        node_id=node_id,
        detail=response_body[:300],
    )
