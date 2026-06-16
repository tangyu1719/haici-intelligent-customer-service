"""会话持久化：列表、详情、创建、编辑、用户侧软删除。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.auth.rbac import user_has_permission
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
from app.services.chat_session_store import sync_active_session_async
from app.services.session_context_manager import mark_session_archived
from app.services.user_profile_memory import archive_session_to_user_memory
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

logger = logging.getLogger(__name__)

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
        streaming=bool(data.get("streaming")),
    )


def _session_item(session: ChatSession, message_count: int, user: User | None = None) -> SessionListItem:
    return SessionListItem(
        id=session.id,
        context_id=session.context_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=message_count,
        meta=_meta_summary(session.meta_json, message_count),
        user_id=int(session.user_id) if session.user_id else None,
        username=user.username if user else None,
        nickname=user.nickname if user else None,
        user_no=user.user_no if user else None,
    )


def _can_view_all_sessions(db: Session, user: User) -> bool:
    return user_has_permission(db, user.id, "session:view:all")


def _accessible_session(
    db: Session,
    session_id: int,
    current_user: User,
    *,
    active_only: bool = True,
) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id == current_user.id:
        if active_only:
            if session.user_deleted_at is not None:
                raise HTTPException(status_code=404, detail="会话已删除")
            if session.status != 1:
                raise HTTPException(status_code=404, detail="会话不可用")
        return session
    if _can_view_all_sessions(db, current_user):
        return session
    raise HTTPException(status_code=404, detail="会话不存在")


def _user_visible_session_filter(q):
    """用户可见：未软删且状态正常。"""
    return q.filter(
        ChatSession.user_deleted == 0,
        ChatSession.user_deleted_at.is_(None),
        ChatSession.status == 1,
    )


def _owned_session(db: Session, session_id: int, user_id: int, *, active_only: bool = True) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if active_only:
        if session.user_deleted == 1 or session.user_deleted_at is not None:
            raise HTTPException(status_code=404, detail="会话已删除")
        if session.status != 1:
            raise HTTPException(status_code=404, detail="会话不可用")
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
    user_id: int | None = Query(None, description="筛选指定用户（需 session:view:all 权限）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    view_all = _can_view_all_sessions(db, current_user)
    if user_id is not None and not view_all:
        raise HTTPException(status_code=403, detail="无权按用户筛选会话")
    msg_counts = (
        db.query(ChatMessage.session_id.label("sid"), func.count(ChatMessage.id).label("message_count"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    q = (
        db.query(
            ChatSession,
            func.coalesce(msg_counts.c.message_count, 0).label("message_count"),
            User,
        )
        .outerjoin(msg_counts, ChatSession.id == msg_counts.c.sid)
        .outerjoin(User, User.id == ChatSession.user_id)
    )
    if view_all:
        q = q.filter(
            ChatSession.status == 1,
            ChatSession.user_deleted == 0,
            ChatSession.user_deleted_at.is_(None),
        )
        if user_id is not None:
            q = q.filter(ChatSession.user_id == user_id)
    else:
        q = q.filter(ChatSession.user_id == current_user.id)
        q = _user_visible_session_filter(q)
    q = apply_id_filter(q, ChatSession.id, qry)
    if qry.name:
        if view_all:
            q = q.filter(
                (ChatSession.title.ilike(f"%{qry.name}%"))
                | (User.username.ilike(f"%{qry.name}%"))
                | (User.nickname.ilike(f"%{qry.name}%"))
                | (User.user_no.ilike(f"%{qry.name}%"))
            )
        else:
            q = apply_like(q, ChatSession.title, qry.name)
    q = apply_keyword(q, qry, [ChatSession.title, ChatSession.context_id])
    q = apply_date_range(q, ChatSession.updated_at, qry)
    sort_map = {**_SESSION_SORT, "message_count": msg_counts.c.message_count, "user_id": ChatSession.user_id}
    q = apply_sort(q, ChatSession, qry, sort_map, ChatSession.updated_at)
    rows, total = paginate(q, qry)
    items = [_session_item(session, int(message_count or 0), user) for session, message_count, user in rows]
    return SessionPageResponse(**page_result(items, total, qry))


@router.get("/settings/persist-interval")
def get_persist_interval_public(_user: User = Depends(get_current_user)):
    """前端读取活跃会话落库间隔（分钟）。"""
    from app.services.system_settings import get_session_persist_interval_minutes

    return {"session_active_persist_interval_minutes": get_session_persist_interval_minutes()}


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = _accessible_session(db, session_id, current_user)
    msg_count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session_id).scalar() or 0
    owner = db.get(User, session.user_id)
    base = _session_item(session, int(msg_count), owner)
    msg_qry = ListQuery(page=1, size=50, sort_by="created_at", sort_order="asc")
    mq = _messages_query(db, session_id, msg_qry)
    rows, _ = paginate(mq, msg_qry)
    return SessionDetailResponse(
        **{k: v for k, v in base.model_dump().items() if k != "user_id"},
        status=session.status,
        user_id=session.user_id,
        messages=[_message_item(m) for m in rows],
    )


@router.get("/{session_id}/messages", response_model=MessagePageResponse)
def get_messages(
    session_id: int,
    qry: ListQuery = Depends(list_query_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _accessible_session(db, session_id, current_user)
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


@router.post("/{session_id}/archive")
def archive_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动归档会话：写入用户长期记忆并标记 status=0。"""
    session = _owned_session(db, session_id, current_user.id)
    if session.meta_json and isinstance(session.meta_json, dict) and session.meta_json.get("streaming"):
        raise HTTPException(status_code=409, detail="该会话正在生成回答，请稍候再归档")
    archive_session_to_user_memory(db, session, reason="manual_archive")
    mark_session_archived(db, session, "manual_archive")
    return {"ok": True, "id": session_id, "archived": True}


@router.delete("/{session_id}")
def user_delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用户界面删除（软删）：从智能对话/会话历史隐藏，消息与审计记录保留。"""
    session = _owned_session(db, session_id, current_user.id)
    if session.meta_json and isinstance(session.meta_json, dict) and session.meta_json.get("streaming"):
        raise HTTPException(status_code=409, detail="该会话正在生成回答，请稍候再删除")
    session.user_deleted = 1
    session.user_deleted_at = datetime.utcnow()
    try:
        archive_session_to_user_memory(db, session, reason="user_delete")
    except Exception as exc:
        logger.warning(
            "[会话持久化|sessions.user_delete|archive_memory|硬编执行|失败] session_id=%s; error_type=%s",
            session_id,
            type(exc).__name__,
        )
    db.commit()
    logger.info(
        "[会话持久化|sessions.user_delete|session_id=%s|硬编执行|完成] user_id=%s",
        session_id,
        current_user.id,
    )
    return {
        "ok": True,
        "id": session_id,
        "user_deleted": True,
        "message": "已从您的界面隐藏，管理员审计记录仍保留",
    }


class SessionSyncRequest(BaseModel):
    reason: str = Field(default="interval", max_length=32)


@router.post("/{session_id}/sync")
async def sync_session(
    session_id: int,
    body: SessionSyncRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """活跃会话定时/切换/退出落库：刷新会话元数据供历史查询。"""
    _owned_session(db, session_id, current_user.id)
    reason = (body.reason if body else "interval") or "interval"
    ok = await sync_active_session_async(session_id=session_id, user_id=current_user.id, reason=reason)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不可用")
    return {"ok": True, "session_id": session_id, "reason": reason}
