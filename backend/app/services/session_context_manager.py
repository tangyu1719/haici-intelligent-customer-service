"""会话上下文编排：模型预算绑定、80% 自动摘要、滑动窗口、归档触发。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.llms import get_llm
from app.models import ChatMessage, ChatSession
from app.services.chat_context import (
    count_history_chars,
    history_char_budget,
    rows_to_hist_dicts,
    select_history_messages,
    select_sliding_window_messages,
)
from app.services.model_context_registry import lookup_context_chars, lookup_max_output_tokens
from app.services.llm_gateway import get_llm_gateway

logger = logging.getLogger(__name__)


@dataclass
class PreparedContext:
    """一次对话轮次提交给 LLM 的上下文包。"""

    hist_dicts: list[dict]
    rolling_summary: str | None
    mode: str  # full | sliding_summary
    budget_chars: int
    usage_ratio: float
    turn_count: int
    model_context_chars: int
    summarized: bool = False


def _session_turn_count(rows: list) -> int:
    return sum(
        1
        for r in rows
        if (r.role if hasattr(r, "role") else r.get("role")) in ("user", "assistant")
    ) // 2


def _get_rolling_summary(meta: dict) -> str:
    return str(meta.get("rolling_summary") or "").strip()


def _summary_prompt(old_lines: list[str], existing_summary: str) -> str:
    block = "\n".join(old_lines[-40:])
    prev = f"\n\n已有摘要（请合并去重后输出新摘要）：\n{existing_summary}" if existing_summary else ""
    return (
        "你是企业客服对话摘要助手。请将以下历史对话压缩为结构化摘要，保留：\n"
        "1. 用户明确提出的需求与问题\n"
        "2. 已确认的产品/账号/订单等关键实体\n"
        "3. 助手已给出的结论与待办\n"
        "4. 用户偏好（语言风格、关注点）\n"
        "禁止编造；无信息则写「无」。控制在 800 字以内，使用中文条目列表。"
        f"{prev}\n\n待摘要对话：\n{block}"
    )


def generate_rolling_summary(old_rows: list, existing_summary: str = "") -> str:
    """对超出滑动窗口的旧消息做 LLM 摘要。"""
    lines: list[str] = []
    for m in old_rows:
        role = m.role if hasattr(m, "role") else m.get("role")
        content = (m.content if hasattr(m, "content") else m.get("content")) or ""
        if role in ("user", "assistant") and content.strip():
            label = "用户" if role == "user" else "助手"
            lines.append(f"{label}：{content.strip()[:600]}")
    if not lines:
        return existing_summary
    try:
        result = get_llm().call(
            _summary_prompt(lines, existing_summary),
            temperature=0.1,
            max_tokens=1200,
            task_type="summary",
        )
        text = (result or "").strip()
        if text.startswith("【") and "错误" in text:
            return existing_summary
        return text[:4000]
    except Exception as exc:
        logger.warning(
            "[智能客服-上下文|session_context_manager|generate_summary|Agent执行|失败] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        return existing_summary


def resolve_session_budget(session: ChatSession, task_type: str = "qa") -> tuple[int, int]:
    """返回 (model_context_chars, history_budget_chars) 并写入会话 meta。"""
    node = get_llm_gateway().choose(task_type)
    model = node.model if node else settings.QWEN_MODEL
    ctx_chars = lookup_context_chars(model)
    reserve = max(0, int(settings.CHAT_CONTEXT_RESERVE_CHARS))
    budget = max(2048, ctx_chars - reserve)

    meta = dict(session.meta_json or {})
    if meta.get("model_context_chars") != ctx_chars or meta.get("context_model") != model:
        meta["model_context_chars"] = ctx_chars
        meta["context_model"] = model
        meta["context_budget_chars"] = budget
        meta["context_bound_at"] = datetime.utcnow().isoformat()
        session.meta_json = meta
        flag_modified(session, "meta_json")
    return ctx_chars, budget


def should_compress(rows: list, budget_chars: int, turn_count: int) -> tuple[bool, float]:
    """判断是否进入摘要+滑动窗口模式。"""
    total = count_history_chars(rows)
    ratio = total / max(budget_chars, 1)
    threshold = float(settings.CHAT_SUMMARY_THRESHOLD_RATIO)
    max_turns = max(1, int(settings.CHAT_SLIDING_WINDOW_TURNS))
    if ratio >= threshold:
        return True, ratio
    if turn_count > max_turns:
        return True, ratio
    return False, ratio


def maybe_update_rolling_summary(
    db: Session,
    session: ChatSession,
    all_rows: list,
    *,
    budget_chars: int,
    force: bool = False,
) -> str:
    """超阈值时对旧消息摘要并写入 meta_json.rolling_summary。"""
    if not settings.CHAT_AUTO_SUMMARY_ENABLED and not force:
        return _get_rolling_summary(session.meta_json or {})

    meta = dict(session.meta_json or {})
    existing = _get_rolling_summary(meta)
    max_turns = max(1, int(settings.CHAT_SLIDING_WINDOW_TURNS))
    window_size = max_turns * 2

    if len(all_rows) <= window_size and not force:
        return existing

    old_part = all_rows[:-window_size] if len(all_rows) > window_size else []
    if not old_part:
        return existing

    last_id = old_part[-1].id if hasattr(old_part[-1], "id") else None
    if not force and last_id and meta.get("summary_up_to_message_id") == last_id:
        return existing

    new_summary = generate_rolling_summary(old_part, existing)
    if new_summary:
        meta["rolling_summary"] = new_summary
        meta["summary_up_to_message_id"] = last_id
        meta["summary_updated_at"] = datetime.utcnow().isoformat()
        meta["summary_trigger_ratio"] = round(count_history_chars(all_rows) / max(budget_chars, 1), 3)
        session.meta_json = meta
        flag_modified(session, "meta_json")
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.info(
            "[智能客服-上下文|session_context_manager|rolling_summary|Agent执行|完成] session_id=%s; chars=%s",
            session.id,
            len(new_summary),
        )
    return new_summary or existing


def prepare_session_context(
    db: Session,
    session: ChatSession,
    all_rows: list,
    *,
    task_type: str = "qa",
) -> PreparedContext:
    """按会话与模型预算组装提交上下文：充裕则全量，紧张则摘要+滑动窗口。"""
    ctx_chars, budget = resolve_session_budget(session, task_type)
    turn_count = _session_turn_count(all_rows)
    compress, ratio = should_compress(all_rows, budget, turn_count)
    meta = dict(session.meta_json or {})
    rolling_summary = _get_rolling_summary(meta)
    summarized = False

    if compress:
        rolling_summary = maybe_update_rolling_summary(
            db, session, all_rows, budget_chars=budget, force=False
        )
        summarized = bool(rolling_summary)
        picked = select_sliding_window_messages(all_rows, budget_chars=budget)
        mode = "sliding_summary"
    else:
        picked = select_history_messages(all_rows, budget_chars=budget)
        mode = "full"

    hist_dicts = rows_to_hist_dicts(picked)
    return PreparedContext(
        hist_dicts=hist_dicts,
        rolling_summary=rolling_summary or None,
        mode=mode,
        budget_chars=budget,
        usage_ratio=round(ratio, 4),
        turn_count=turn_count,
        model_context_chars=ctx_chars,
        summarized=summarized,
    )


def inject_summary_prefix(hist_dicts: list[dict], summary: str | None) -> list[dict]:
    """将滚动摘要作为 system 前缀注入历史。"""
    if not summary:
        return hist_dicts
    prefix = {"role": "system", "content": f"【此前对话摘要】\n{summary}"}
    return [prefix, *hist_dicts]


def should_auto_archive(session: ChatSession, message_count: int) -> bool:
    limit = max(10, int(settings.CHAT_SESSION_MAX_MESSAGES))
    meta = session.meta_json or {}
    if message_count >= limit:
        return True
    if meta.get("context_usage_ratio", 0) >= float(settings.CHAT_SUMMARY_THRESHOLD_RATIO):
        return bool(meta.get("auto_archive_on_full"))
    return False


def mark_session_archived(db: Session, session: ChatSession, reason: str) -> None:
    meta = dict(session.meta_json or {})
    meta["archived"] = True
    meta["archived_at"] = datetime.utcnow().isoformat()
    meta["archive_reason"] = reason
    session.meta_json = meta
    session.status = 0
    flag_modified(session, "meta_json")
    db.commit()
