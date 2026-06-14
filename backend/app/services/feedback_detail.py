"""反馈详情补全：快照缺失时从会话/消息表回填。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, MessageFeedback
from app.services.term_dictionary import INTENT_LABELS


def _role_label(role: str) -> str:
    return "用户" if role == "user" else "助手"


def _build_context_summary(db: Session, session_id: int, upto_message_id: int, *, limit: int = 8) -> str:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id, ChatMessage.id <= upto_message_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    lines: list[str] = []
    for m in rows:
        text = (m.content or "").strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "…"
        lines.append(f"{_role_label(m.role)}: {text}")
    return "\n".join(lines)


def _find_user_question(db: Session, assistant_msg: ChatMessage) -> str:
    prev = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == assistant_msg.session_id,
            ChatMessage.id < assistant_msg.id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )
    return (prev.content or "").strip() if prev else ""


def build_feedback_detail(db: Session, row: MessageFeedback) -> dict:
    """合并前端快照 + 数据库回填，保证详情页字段完整。"""
    snap = dict(row.context_snapshot_json or {})
    assistant_msg = db.get(ChatMessage, row.message_id)
    session = None
    if assistant_msg:
        session = db.get(ChatSession, assistant_msg.session_id)

    session_id = int(snap.get("session_id") or (assistant_msg.session_id if assistant_msg else 0) or 0)
    context_id = str(snap.get("context_id") or (session.context_id if session else "") or "")
    user_question = str(snap.get("user_question") or "").strip()
    assistant_answer = str(snap.get("assistant_answer") or "").strip()
    context_summary = str(snap.get("context_summary") or "").strip()
    intent_code = str(snap.get("intent") or (assistant_msg.intent_label if assistant_msg else "") or "").strip()
    intent_label = str(snap.get("intent_label") or INTENT_LABELS.get(intent_code, intent_code) or "").strip()

    if assistant_msg:
        if not assistant_answer:
            assistant_answer = (assistant_msg.content or "").strip()
        if not user_question:
            user_question = _find_user_question(db, assistant_msg)
        if not context_summary and session_id:
            context_summary = _build_context_summary(db, session_id, assistant_msg.id)
        if not intent_code and assistant_msg.intent_label:
            intent_code = assistant_msg.intent_label
            intent_label = INTENT_LABELS.get(intent_code, intent_code)

    return {
        "feedback_id": row.id,
        "message_id": row.message_id,
        "session_id": session_id,
        "context_id": context_id,
        "user_question": user_question,
        "assistant_answer": assistant_answer,
        "context_summary": context_summary,
        "intent": intent_code,
        "intent_label": intent_label,
        "detected_intent": str(snap.get("detected_intent") or intent_code or ""),
        "detected_intent_label": str(snap.get("detected_intent_label") or intent_label or ""),
        "corrected_intent": str(snap.get("corrected_intent") or ""),
        "corrected_intent_label": str(snap.get("corrected_intent_label") or ""),
        "session_title": (session.title if session else "") or "",
    }
