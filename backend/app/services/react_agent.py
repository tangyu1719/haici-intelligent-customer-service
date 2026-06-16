"""标准 ReAct 模式 RAG 问答 — Thought / Act / Observe 硬编码闭环。

复杂问题走多轮 rag_search Tool Calling；每步均为真实 LLM 决策 + 真实检索，
禁止模板/sleep 假步骤。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document

from app.config import settings
from app.llms import LLMStreamDelta, get_llm
from app.rag import build_prompt_messages, citations_from_docs
from app.services.rag_tool import (
    RAG_SEARCH_TOOL,
    execute_rag_search,
    format_observe_text,
    merge_rag_docs,
)

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{[\s\S]*\}")

EmitFn = Callable[[str, dict], Awaitable[None]]


@dataclass
class ReactStepRecord:
    step: int
    phase: str  # thought | act | observe
    content: str
    tool_query: str = ""
    tool_purpose: str = ""
    slice_count: int = 0


@dataclass
class ReactResult:
    answer_parts: list[str] = field(default_factory=list)
    all_docs: list[Document] = field(default_factory=list)
    anti_dilution_summary: str | None = None
    rag_call_count: int = 0
    steps: list[ReactStepRecord] = field(default_factory=list)
    used_react: bool = True


def is_complex_query(question: str) -> bool:
    """启发式判断是否需要 ReAct 多步 RAG。"""
    q = (question or "").strip()
    if len(q) < 20:
        return False
    markers = (
        "分别", "对比", "比较", "以及", "并且", "同时",
        "第一步", "第二步", "步骤", "流程", "如何", "怎么",
        "有哪些", "区别", "差异", "多个", "两方面", "三方面",
    )
    hit = sum(1 for m in markers if m in q)
    if hit >= 2:
        return True
    if hit >= 1 and (q.count("？") + q.count("?")) >= 2:
        return True
    if len(q) > 120 and ("；" in q or ";" in q):
        return True
    return False


def _parse_react_decision(raw: str) -> dict[str, Any]:
    """解析 LLM 输出的 ReAct 决策 JSON。"""
    m = _JSON_RE.search(raw or "")
    if not m:
        return {"action": "answer", "thought": raw[:200]}
    try:
        data = json.loads(m.group())
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"action": "answer", "thought": raw[:200]}


def _build_react_system_prompt() -> str:
    return (
        "你是企业知识库智能客服的 ReAct 推理引擎。"
        "你必须按 Thought→Act→Observe 循环工作：\n"
        "1. Thought：分析用户问题，决定下一步行动\n"
        "2. Act：若需检索，调用 rag_search 工具（输出 JSON 中 action=search）\n"
        "3. Observe：阅读检索结果后再决定继续检索或给出最终回答\n\n"
        "输出严格 JSON（不要 markdown 代码块）：\n"
        '{"thought":"思考过程","action":"search|answer","search_query":"检索词","search_purpose":"目的","ready_to_answer":false}\n'
        "- action=search 时必须提供 search_query\n"
        "- action=answer 或 ready_to_answer=true 时表示可以基于已有观察作答\n"
        "- 复杂问题可多次 search，每次聚焦一个子问题\n"
    )


async def _stream_llm_thought(
    messages: list[dict[str, str]],
    emit: EmitFn | None,
    step: int,
) -> str:
    """真实 LLM 流式 Thought，yield think SSE。"""
    parts: list[str] = []
    async for delta in get_llm().stream_chat(messages, task_type="reason"):
        if delta.kind == "think":
            if emit:
                await emit("react_step", {
                    "step": step,
                    "phase": "thought",
                    "kind": "think",
                    "content": delta.content,
                    "streaming": True,
                })
        elif delta.kind == "answer":
            parts.append(delta.content)
            if emit:
                await emit("react_step", {
                    "step": step,
                    "phase": "thought",
                    "kind": "answer",
                    "content": delta.content,
                    "streaming": True,
                })
    return "".join(parts)


async def run_react_rag(
    question: str,
    tenant_id: str,
    history: list[dict],
    intent: str,
    *,
    emit: EmitFn | None = None,
    rolling_summary: str | None = None,
    initial_rag_query: str = "",
) -> ReactResult:
    """执行 ReAct 闭环：Thought → Act(rag_search) → Observe → … → Final Answer。"""
    result = ReactResult()
    rag_results: list[dict[str, Any]] = []
    observations: list[str] = []
    max_steps = settings.REACT_MAX_STEPS
    max_rag = settings.REACT_MAX_RAG_CALLS

    for step in range(1, max_steps + 1):
        # ── Thought：LLM 决策下一步 ──
        obs_block = "\n\n".join(observations[-3:]) if observations else "（尚无检索结果）"
        thought_prompt = (
            f"{_build_react_system_prompt()}\n"
            f"用户问题：{question}\n"
            f"意图：{intent}\n"
            f"已执行 RAG 次数：{result.rag_call_count}/{max_rag}\n"
            f"历史观察：\n{obs_block}\n\n"
            f"请输出第 {step} 步决策 JSON。"
        )
        thought_msgs = [{"role": "user", "content": thought_prompt}]
        if emit:
            await emit("react_step", {"step": step, "phase": "thought", "content": "", "streaming": True, "start": True})

        raw_decision = await _stream_llm_thought(thought_msgs, emit, step)
        decision = _parse_react_decision(raw_decision)
        thought_text = str(decision.get("thought") or raw_decision[:300])
        result.steps.append(ReactStepRecord(step=step, phase="thought", content=thought_text))

        if emit:
            await emit("react_step", {
                "step": step,
                "phase": "thought",
                "content": thought_text,
                "streaming": False,
                "done": True,
            })

        action = str(decision.get("action") or "").lower()
        ready = bool(decision.get("ready_to_answer"))
        need_search = action == "search" and result.rag_call_count < max_rag and not ready

        if not need_search:
            break

        # ── Act：真实 RAG Tool 调用 ──
        search_q = str(decision.get("search_query") or initial_rag_query or question).strip()
        purpose = str(decision.get("search_purpose") or "")
        if emit:
            await emit("react_step", {
                "step": step,
                "phase": "act",
                "content": f"调用 rag_search：{search_q}",
                "tool": "rag_search",
                "tool_query": search_q,
                "tool_purpose": purpose,
            })

        rag_result = execute_rag_search(search_q, tenant_id, purpose=purpose)
        rag_results.append(rag_result)
        result.rag_call_count += 1
        result.steps.append(ReactStepRecord(
            step=step,
            phase="act",
            content=f"rag_search({search_q})",
            tool_query=search_q,
            tool_purpose=purpose,
            slice_count=rag_result.get("slice_count", 0),
        ))

        if rag_result.get("anti_dilution_summary"):
            result.anti_dilution_summary = rag_result["anti_dilution_summary"]

        # ── Observe：格式化观察结果并流式输出 ──
        observe_text = format_observe_text(rag_result)
        observations.append(observe_text)
        result.steps.append(ReactStepRecord(step=step, phase="observe", content=observe_text))

        if emit:
            # 流式输出 observe（分块模拟打字，内容为真实检索结果）
            chunk_size = 48
            for i in range(0, len(observe_text), chunk_size):
                chunk = observe_text[i:i + chunk_size]
                await emit("react_step", {
                    "step": step,
                    "phase": "observe",
                    "content": chunk,
                    "streaming": True,
                })
            await emit("react_step", {
                "step": step,
                "phase": "observe",
                "content": observe_text,
                "streaming": False,
                "done": True,
                "slice_count": rag_result.get("slice_count", 0),
            })

    # 合并所有 RAG 文档
    result.all_docs = merge_rag_docs(rag_results)

    # 若 ReAct 循环未检索到任何文档，做一次兜底检索
    if not result.all_docs and initial_rag_query:
        fallback = execute_rag_search(initial_rag_query or question, tenant_id)
        rag_results.append(fallback)
        result.all_docs = merge_rag_docs(rag_results)
        result.rag_call_count += 1
        if fallback.get("anti_dilution_summary"):
            result.anti_dilution_summary = fallback["anti_dilution_summary"]

    return result


async def stream_react_final_answer(
    question: str,
    docs: list[Document],
    history: list[dict],
    intent: str,
    observations: list[str],
    anti_dilution_summary: str | None,
    rolling_summary: str | None,
) -> AsyncIterator[LLMStreamDelta]:
    """基于 ReAct 观察结果流式生成最终回答。"""
    if not docs:
        from app.config import settings as cfg
        yield LLMStreamDelta("answer", cfg.FALLBACK_NO_CONTEXT)
        return

    messages = build_prompt_messages(
        question,
        docs,
        history,
        intent,
        anti_dilution_summary,
        rolling_summary,
    )
    if observations:
        obs_note = "\n\n【ReAct 多步检索观察】\n" + "\n---\n".join(observations[-5:])
        messages[-1]["content"] = messages[-1]["content"] + obs_note

    async for delta in get_llm().stream_chat(messages, task_type="reason"):
        yield delta


def get_rag_tool_definitions() -> list[dict]:
    """返回注册表中的 RAG 工具定义。"""
    return [RAG_SEARCH_TOOL]
