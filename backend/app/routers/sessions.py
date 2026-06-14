"""会话持久化：列表、详情、创建、编辑、归档。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.deps import get_current_user
from app.models import ChatMessage, ChatSession, User
from app.schemas import (
    MessageItem,
    MessagePageResponse,
    SessionDetailResponse,
    SessionListItem,
    SessionMetaSummary,
    SessionPageResponse,
    SessionUpdateRequest,
)
from app.services.list_query import (
    ListQuery,
    apply_date_range,
    apply_id_filter,
    apply_keyword,
    apply_like,
    apply_sort,
    list_query_params,
    page_result,
    paginate,
)

router = APIRouter(prefix="/sessions", tags=["会话"])

_SESSION_SORT = {
    "id": ChatSession.id,
    "created_at": ChatSession.created_at,
    "updated_at": ChatSession.updated_at,
    "title": ChatSession.title,
}


def _meta_summary(raw: dict | None, message_count: int = 0) -> SessionMetaSummary:
    data = raw if isinstance(raw, dict) else {}
    return SessionMetaSummary(
        last_intent=data.get("last_intent"),
        message_count=int(data.get("message_count") or message_count or 0),
        note=data.get("note"),
        pinned=bool(data.get("pinned")),
    )


def _session_item(session: ChatSession, message_count: int) -> SessionListItem:
    return SessionListItem(
        id=session.id,
        context_id=session.context_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=message_count,
        meta=_meta_summary(session.meta_json, message_count),
    )


def _owned_session(db: Session, session_id: int, user_id: int, *, active_only: bool = True) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if active_only and session.status != 1:
        raise HTTPException(status_code=404, detail="会话已归档")
    return session


def _message_item(m: ChatMessage) -> MessageItem:
    return MessageItem(
        id=m.id,
        role=m.role,
        content=m.content,
        intent_label=m.intent_label,
        citations=m.citations_json if isinstance(m.citations_json, list) else None,
        created_at=m.created_at,
    )


def _messages_query(db: Session, session_id: int, qry: ListQuery):
    q = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
    q = apply_id_filter(q, ChatMessage.id, qry)
    q = apply_keyword(q, qry, [ChatMessage.content])
    q = apply_date_range(q, ChatMessage.created_at, qry)
    msg_sort = {
        "id": ChatMessage.id,
        "created_at": ChatMessage.created_at,
    }
    q = apply_sort(q, ChatMessage, qry, msg_sort, ChatMessage.created_at)
    return q


@router.post("", response_model=SessionListItem)
def create_session(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = ChatSession(
        user_id=current_user.id,
        context_id=str(uuid.uuid4()),
        title="新对话",
        meta_json={"message_count": 0, "pinned": False},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_item(session, 0)


@router.get("", response_model=SessionPageResponse)
def list_sessions(
    qry: ListQuery = Depends(list_query_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg_counts = (
        db.query(ChatMessage.session_id.label("sid"), func.count(ChatMessage.id).label("message_count"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    q = (
        db.query(ChatSession, func.coalesce(msg_counts.c.message_count, 0).label("message_count"))
        .outerjoin(msg_counts, ChatSession.id == msg_counts.c.sid)
        .filter(ChatSession.user_id == current_user.id, ChatSession.status == 1)
    )
    q = apply_id_filter(q, ChatSession.id, qry)
    if qry.name:
        q = apply_like(q, ChatSession.title, qry.name)
    q = apply_keyword(q, qry, [ChatSession.title, ChatSession.context_id])
    q = apply_date_range(q, ChatSession.updated_at, qry)
    sort_map = {**_SESSION_SORT, "message_count": msg_counts.c.message_count}
    q = apply_sort(q, ChatSession, qry, sort_map, ChatSession.updated_at)
    rows, total = paginate(q, qry)
    items = [_session_item(session, int(message_count or 0)) for session, message_count in rows]
    return SessionPageResponse(**page_result(items, total, qry))


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = _owned_session(db, session_id, current_user.id)
    msg_count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session_id).scalar() or 0
    base = _session_item(session, int(msg_count))
    # 详情默认带最近 50 条消息（时间正序）；完整翻页走 /messages
    msg_qry = ListQuery(page=1, size=50, sort_by="created_at", sort_order="asc")
    mq = _messages_query(db, session_id, msg_qry)
    rows, _ = paginate(mq, msg_qry)
    return SessionDetailResponse(**base.model_dump(), messages=[_message_item(m) for m in rows])


@router.get("/{session_id}/messages", response_model=MessagePageResponse)
def get_messages(
    session_id: int,
    qry: ListQuery = Depends(list_query_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_session(db, session_id, current_user.id)
    q = _messages_query(db, session_id, qry)
    rows, total = paginate(q, qry)
    return MessagePageResponse(**page_result([_message_item(m) for m in rows], total, qry))


@router.patch("/{session_id}", response_model=SessionListItem)
def update_session(
    session_id: int,
    payload: SessionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = _owned_session(db, session_id, current_user.id)
    if payload.title is not None:
        session.title = payload.title
    if payload.note is not None or payload.pinned is not None:
        meta = dict(session.meta_json or {})
        if payload.note is not None:
            meta["note"] = payload.note
        if payload.pinned is not None:
            meta["pinned"] = payload.pinned
        session.meta_json = meta
        flag_modified(session, "meta_json")
    if payload.title is None and payload.note is None and payload.pinned is None:
        raise HTTPException(status_code=400, detail="请至少提供一项要更新的字段")
    db.commit()
    db.refresh(session)
    msg_count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session_id).scalar() or 0
    return _session_item(session, int(msg_count))


@router.delete("/{session_id}")
def archive_session(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = _owned_session(db, session_id, current_user.id)
    session.status = 0
    db.commit()
    return {"ok": True, "id": session_id, "archived": True}
