"""用户长期记忆与 MD 画像：5 星/确认事实沉淀、归档会话写入。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.llms import get_llm
from app.models import ChatMessage, ChatSession, User

logger = logging.getLogger(__name__)

_SECTION_FACTS = "## 原子事实（用户确认）"
_SECTION_PREFS = "## 偏好与习惯"
_SECTION_MEMORY = "## 归档会话记忆"


def _profile_dir() -> Path:
    base = Path(settings.UPLOAD_DIR)
    if not base.is_absolute():
        base = (settings.project_root / "backend" / base).resolve()
    p = base.parent / "user_profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def profile_path(user_id: int) -> Path:
    return _profile_dir() / f"user_{user_id}.md"


def _ensure_profile_header(user: User) -> str:
    title = f"# 用户画像 — {user.nickname or user.username or user.user_no or user.id}"
    sub = f"\n\n> 用户ID: {user.id} | 用户号: {user.user_no or '-'} | 更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    return title + sub


def read_profile_md(user_id: int) -> str:
    path = profile_path(user_id)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def write_profile_md(
    user_id: int,
    markdown: str,
    *,
    user: User | None = None,
    editor_id: int | None = None,
) -> None:
    """手动写入/覆盖用户 MD 画像（用户自改或管理员代改）。"""
    content = markdown if markdown is not None else ""
    path = profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info(
        "[智能客服-用户画像|user_profile_memory|write_profile|硬编执行|完成] user_id=%s; editor_id=%s; chars=%s",
        user_id,
        editor_id,
        len(content),
    )


def _append_section(content: str, section: str, line: str) -> str:
    if section not in content:
        content = content.rstrip() + f"\n\n{section}\n"
    parts = content.split(section, 1)
    head = parts[0]
    tail = parts[1] if len(parts) > 1 else "\n"
    return head + section + tail.rstrip() + f"\n{line}\n"


def append_atomic_fact(
    user_id: int,
    fact: str,
    *,
    source_message_id: int | None = None,
    rating: int | None = None,
    source: str = "feedback",
) -> None:
    fact = (fact or "").strip()
    if not fact or len(fact) < 4:
        return
    path = profile_path(user_id)
    if path.is_file():
        body = path.read_text(encoding="utf-8")
    else:
        body = f"# 用户画像 — 用户{user_id}\n"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    src = f"消息#{source_message_id}" if source_message_id else source
    extra = f", {rating}星" if rating else ""
    line = f"- [{ts}] {fact} （来源: {src}{extra}）"
    body = _append_section(body, _SECTION_FACTS, line)
    path.write_text(body, encoding="utf-8")
    logger.info(
        "[智能客服-用户画像|user_profile_memory|append_fact|硬编执行|完成] user_id=%s; fact_len=%s",
        user_id,
        len(fact),
    )


def append_session_memory(
    user_id: int,
    session_title: str,
    summary: str,
    *,
    session_id: int | None = None,
    reason: str = "archive",
) -> None:
    summary = (summary or "").strip()
    if not summary:
        return
    path = profile_path(user_id)
    if path.is_file():
        body = path.read_text(encoding="utf-8")
    else:
        body = f"# 用户画像 — 用户{user_id}\n"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    sid = f" (会话#{session_id})" if session_id else ""
    block = f"\n### {session_title}{sid} [{ts}] ({reason})\n{summary}\n"
    if _SECTION_MEMORY not in body:
        body = body.rstrip() + f"\n\n{_SECTION_MEMORY}\n"
    body = body.rstrip() + block
    path.write_text(body, encoding="utf-8")
    logger.info(
        "[智能客服-用户画像|user_profile_memory|append_session|硬编执行|完成] user_id=%s; session_id=%s",
        user_id,
        session_id,
    )


def _extract_facts_prompt(question: str, answer: str, comment: str = "") -> str:
    return (
        "从以下客服问答中提取用户侧「原子事实」——可被长期记住的客观陈述（产品名、账号特征、偏好、"
        "已确认的需求等）。仅输出 JSON 数组，每项为字符串；无则输出 []。禁止编造。\n"
        f"用户问题：{question[:800]}\n助手回答：{answer[:1200]}\n"
        f"用户补充：{comment[:300] if comment else '无'}"
    )


def extract_atomic_facts_from_qa(question: str, answer: str, comment: str = "") -> list[str]:
    try:
        raw = get_llm().call(
            _extract_facts_prompt(question, answer, comment),
            temperature=0.0,
            max_tokens=512,
            task_type="summary",
        )
        text = (raw or "").strip()
        import json

        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        arr = json.loads(m.group())
        if not isinstance(arr, list):
            return []
        return [str(x).strip() for x in arr if str(x).strip() and len(str(x).strip()) >= 4][:5]
    except Exception as exc:
        logger.warning(
            "[智能客服-用户画像|user_profile_memory|extract_facts|Agent执行|失败] error_type=%s",
            type(exc).__name__,
        )
        return []


def archive_session_to_user_memory(db: Session, session: ChatSession, reason: str = "archive") -> None:
    """会话归档/删除时写入用户长期记忆库。"""
    user = db.get(User, session.user_id)
    if not user:
        return

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    meta = session.meta_json or {}
    summary = str(meta.get("rolling_summary") or "").strip()
    if not summary and rows:
        from app.services.session_context_manager import generate_rolling_summary

        summary = generate_rolling_summary(rows)

    if not summary:
        lines = []
        for m in rows[-20:]:
            if m.role in ("user", "assistant"):
                lines.append(f"{'用户' if m.role == 'user' else '助手'}：{m.content[:200]}")
        summary = "\n".join(lines)[:2000]

    path = profile_path(user.id)
    if not path.is_file():
        path.write_text(_ensure_profile_header(user), encoding="utf-8")

    append_session_memory(
        user.id,
        session.title or "未命名会话",
        summary,
        session_id=session.id,
        reason=reason,
    )


def get_profile_context_snippet(user_id: int, max_chars: int = 1500) -> str:
    """读取用户 MD 画像中的原子事实与近期归档记忆，注入对话上下文。"""
    md = read_profile_md(user_id)
    if not md.strip():
        return ""
    parts: list[str] = []
    for section in (_SECTION_FACTS, _SECTION_MEMORY):
        if section not in md:
            continue
        chunk = md.split(section, 1)[1]
        if _SECTION_PREFS in chunk:
            chunk = chunk.split(_SECTION_PREFS, 1)[0]
        elif _SECTION_MEMORY in chunk and section == _SECTION_FACTS:
            chunk = chunk.split(_SECTION_MEMORY, 1)[0]
        lines = [ln.strip() for ln in chunk.strip().splitlines() if ln.strip().startswith("-")]
        if lines:
            parts.append(section + "\n" + "\n".join(lines[-8:]))
    text = "\n\n".join(parts).strip()
    return text[:max_chars] if text else ""


def process_positive_feedback(
    db: Session,
    *,
    user_id: int,
    message_id: int,
    rating: int,
    comment: str | None,
) -> None:
    """5 星或用户确认正确时沉淀原子事实到 MD 画像。"""
    if rating < 5:
        return
    msg = db.get(ChatMessage, message_id)
    if not msg or msg.role != "assistant":
        return
    prev = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == msg.session_id,
            ChatMessage.id < msg.id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    question = (prev.content or "").strip() if prev else ""
    answer = (msg.content or "").strip()
    facts = extract_atomic_facts_from_qa(question, answer, comment or "")
    for fact in facts:
        append_atomic_fact(
            user_id,
            fact,
            source_message_id=message_id,
            rating=rating,
            source="5星反馈",
        )
