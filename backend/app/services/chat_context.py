"""对话上下文预算：字符裁剪、滑动窗口、全量/摘要模式选取。"""

from __future__ import annotations

from app.config import settings


def history_char_budget(session_budget: int | None = None) -> int:
    """可用于多轮历史的字符预算（总上下文减去预留）。"""
    if session_budget is not None:
        return max(1024, int(session_budget))
    reserve = max(0, int(settings.CHAT_CONTEXT_RESERVE_CHARS))
    total = max(0, int(settings.CHAT_MAX_CONTEXT_CHARS))
    return max(1024, total - reserve)


def count_history_chars(rows: list) -> int:
    total = 0
    for item in rows:
        content = item.content if hasattr(item, "content") else (item.get("content") or "")
        role = item.role if hasattr(item, "role") else item.get("role")
        if role in ("user", "assistant") and str(content).strip():
            total += len(str(content))
    return total


def select_history_messages(rows: list, *, budget_chars: int | None = None) -> list:
    """
    从最新消息向前累加，直到达到字符预算（全量模式，预算内尽量多保留）。
    rows: ORM ChatMessage 或 dict(role, content)，需按时间升序传入。
    """
    budget = budget_chars if budget_chars is not None else history_char_budget()
    max_turns = max(1, int(settings.CHAT_HISTORY_TURNS))

    items: list = list(rows)
    if not items:
        return []

    newest_first = items[::-1]
    picked: list = []
    used = 0
    for item in newest_first:
        content = item.content if hasattr(item, "content") else (item.get("content") or "")
        clen = len(str(content))
        if picked and used + clen > budget:
            break
        if len(picked) >= max_turns * 2:
            break
        picked.append(item)
        used += clen

    picked.reverse()
    return picked


def select_sliding_window_messages(rows: list, *, budget_chars: int | None = None) -> list:
    """滑动窗口：仅保留最近 N 轮对话，并在预算内裁剪。"""
    budget = budget_chars if budget_chars is not None else history_char_budget()
    max_turns = max(1, int(settings.CHAT_SLIDING_WINDOW_TURNS))
    items: list = list(rows)
    if not items:
        return []

    window = items[-(max_turns * 2) :]
    newest_first = window[::-1]
    picked: list = []
    used = 0
    for item in newest_first:
        content = item.content if hasattr(item, "content") else (item.get("content") or "")
        clen = len(str(content))
        if picked and used + clen > budget:
            break
        picked.append(item)
        used += clen
    picked.reverse()
    return picked


def rows_to_hist_dicts(rows: list) -> list[dict]:
    out: list[dict] = []
    for m in rows:
        role = m.role if hasattr(m, "role") else m.get("role")
        content = (m.content if hasattr(m, "content") else m.get("content")) or ""
        if role in ("user", "assistant") and content.strip():
            out.append({"role": role, "content": content})
    return out


def trim_messages_to_budget(messages: list[dict], budget_chars: int) -> list[dict]:
    """从最新消息向前保留，用于 LLM 网关层最终裁剪。"""
    if not messages:
        return []
    picked: list[dict] = []
    used = 0
    for m in reversed(messages):
        c = str(m.get("content", ""))
        if picked and used + len(c) > budget_chars:
            remain = budget_chars - used
            if remain > 80:
                picked.insert(0, {**m, "content": c[:remain]})
            break
        picked.insert(0, m)
        used += len(c)
    return picked
