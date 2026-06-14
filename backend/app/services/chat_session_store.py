"""会话持久化：同步写入 + 异步后台落库。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models import ChatMessage, ChatSession

logger = logging.getLogger(__name__)


def touch_session_meta(db: Session, session: ChatSession, *, intent: str | None = None) -> None:
    meta = dict(session.meta_json or {})
    if intent:
        meta["last_intent"] = intent
    meta["message_count"] = (
        db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session.id).scalar() or 0
    )
    session.meta_json = meta
    flag_modified(session, "meta_json")


def _persist_user_message_sync(
    *,
    session_id: int,
    user_id: int,
    question: str,
    intent: str | None,
    auto_title: str | None,
) -> int | None:
    db = SessionLocal()
    try:
        sess = db.get(ChatSession, session_id)
        if not sess or sess.user_id != user_id or sess.status != 1:
            return None
        msg = ChatMessage(session_id=session_id, role="user", content=question, intent_label=intent)
        db.add(msg)
        if auto_title and sess.title == "新对话":
            sess.title = auto_title
        touch_session_meta(db, sess, intent=intent)
        db.commit()
        db.refresh(msg)
        logger.info(
            "[智能客服-会话持久化|chat_session_store|persist_user|硬编执行|完成] session_id=%s; message_id=%s",
            session_id,
            msg.id,
        )
        return int(msg.id)
    except Exception as exc:
        db.rollback()
        logger.exception(
            "[智能客服-会话持久化|chat_session_store|persist_user|硬编执行|失败] session_id=%s; error_type=%s",
            session_id,
            type(exc).__name__,
        )
        return None
    finally:
        db.close()


def _persist_assistant_message_sync(
    *,
    session_id: int,
    user_id: int,
    answer: str,
    intent: str | None,
    citations: list[dict] | None,
) -> int | None:
    db = SessionLocal()
    try:
        sess = db.get(ChatSession, session_id)
        if not sess or sess.user_id != user_id or sess.status != 1:
            return None
        msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer,
            intent_label=intent,
            citations_json=citations or None,
        )
        db.add(msg)
        touch_session_meta(db, sess, intent=intent)
        db.commit()
        db.refresh(msg)
        logger.info(
            "[智能客服-会话持久化|chat_session_store|persist_assistant|硬编执行|完成] session_id=%s; message_id=%s",
            session_id,
            msg.id,
        )
        return int(msg.id)
    except Exception as exc:
        db.rollback()
        logger.exception(
            "[智能客服-会话持久化|chat_session_store|persist_assistant|硬编执行|失败] session_id=%s; error_type=%s",
            session_id,
            type(exc).__name__,
        )
        return None
    finally:
        db.close()


async def persist_user_message_async(**kwargs: Any) -> int | None:
    return await asyncio.to_thread(_persist_user_message_sync, **kwargs)


async def persist_assistant_message_async(**kwargs: Any) -> int | None:
    return await asyncio.to_thread(_persist_assistant_message_sync, **kwargs)


def schedule_persist_user(**kwargs: Any) -> asyncio.Task:
    """后台异步落库用户消息，不阻塞 SSE。"""
    return asyncio.create_task(persist_user_message_async(**kwargs))


def schedule_persist_assistant(**kwargs: Any) -> asyncio.Task:
    """后台异步落库助手消息，不阻塞 SSE。"""
    return asyncio.create_task(persist_assistant_message_async(**kwargs))
