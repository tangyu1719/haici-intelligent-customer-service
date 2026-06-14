"""对话上下文预算：按字符上限选取历史消息。"""

from __future__ import annotations

from app.config import settings


def history_char_budget() -> int:
    """可用于多轮历史的字符预算（总上下文减去预留）。"""
    reserve = max(0, int(settings.CHAT_CONTEXT_RESERVE_CHARS))
    total = max(0, int(settings.CHAT_MAX_CONTEXT_CHARS))
    return max(1024, total - reserve)


def select_history_messages(rows: list, *, budget_chars: int | None = None) -> list:
    """
    从最新消息向前累加，直到达到字符预算。
    rows: ORM ChatMessage 或 dict(role, content)，需按时间升序或降序传入。
    """
    budget = budget_chars if budget_chars is not None else history_char_budget()
    max_turns = max(1, int(settings.CHAT_HISTORY_TURNS))

    items: list = list(rows)
    if not items:
        return []

    # 若已是升序，反转为从新到旧选取
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


def rows_to_hist_dicts(rows: list) -> list[dict]:
    out: list[dict] = []
    for m in rows:
        role = m.role if hasattr(m, "role") else m.get("role")
        content = (m.content if hasattr(m, "content") else m.get("content")) or ""
        if role in ("user", "assistant") and content.strip():
            out.append({"role": role, "content": content})
    return out
