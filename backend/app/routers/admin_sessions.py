"""管理员：查看全部用户会话（含用户侧已删除）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import ChatMessage, ChatSession, User
from app.routers.sessions import _message_item, _messages_query, _session_item
from app.schemas import (
    AdminSessionDetailResponse,
    AdminSessionListResponse,
    AdminSessionPageResponse,
    MessagePageResponse,
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

router = APIRouter(prefix="/admin/sessions", tags=["运维评测-会话审计"])

_SESSION_SORT = {
    "id": ChatSession.id,
    "created_at": ChatSession.created_at,
    "updated_at": ChatSession.updated_at,
    "title": ChatSession.title,
    "user_id": ChatSession.user_id,
}


def _admin_session_item(
    db: Session,
    session: ChatSession,
    message_count: int,
    *,
    user: User | None = None,
) -> AdminSessionListResponse:
    if user is None:
        user = db.get(User, session.user_id)
    base = _session_item(session, message_count)
    return AdminSessionListResponse(
        **base.model_dump(),
        status=session.status,
        user_id=int(session.user_id),
        username=user.username if user else None,
        nickname=user.nickname if user else None,
        user_deleted=bool(session.user_deleted),
        user_deleted_at=session.user_deleted_at,
    )


@router.get("", response_model=AdminSessionPageResponse)
def list_all_sessions(
    qry: ListQuery = Depends(list_query_params),
    user_id: int | None = Query(None, description="用户 ID"),
    user_deleted: int | None = Query(None, ge=0, le=1, description="用户侧删除 1是0否"),
    status: int | None = Query(None, ge=0, le=1, description="会话状态 1正常0归档"),
    db: Session = Depends(get_db),
    _viewer: User = Depends(require_permission("system:session:view")),
):
    msg_counts = (
        db.query(ChatMessage.session_id.label("sid"), func.count(ChatMessage.id).label("message_count"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    q = (
        db.query(ChatSession, func.coalesce(msg_counts.c.message_count, 0).label("message_count"))
        .outerjoin(msg_counts, ChatSession.id == msg_counts.c.sid)
    )
    if user_id is not None:
        q = q.filter(ChatSession.user_id == user_id)
    if user_deleted is not None:
        q = q.filter(ChatSession.user_deleted == user_deleted)
    if status is not None:
        q = q.filter(ChatSession.status == status)
    q = apply_id_filter(q, ChatSession.id, qry)
    if qry.name:
        q = q.join(User, User.id == ChatSession.user_id).filter(
            (ChatSession.title.ilike(f"%{qry.name}%"))
            | (User.username.ilike(f"%{qry.name}%"))
            | (User.nickname.ilike(f"%{qry.name}%"))
        )
    else:
        q = apply_like(q, ChatSession.title, qry.name)
    q = apply_keyword(q, qry, [ChatSession.title, ChatSession.context_id])
    q = apply_date_range(q, ChatSession.updated_at, qry)
    sort_map = {**_SESSION_SORT, "message_count": msg_counts.c.message_count}
    q = apply_sort(q, ChatSession, qry, sort_map, ChatSession.updated_at)
    rows, total = paginate(q, qry)
    items = [_admin_session_item(db, session, int(message_count or 0)) for session, message_count in rows]
    return AdminSessionPageResponse(**page_result(items, total, qry))


@router.get("/{session_id}", response_model=AdminSessionDetailResponse)
def get_session_detail_admin(
    session_id: int,
    db: Session = Depends(get_db),
    _viewer: User = Depends(require_permission("system:session:view")),
):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    msg_count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session_id).scalar() or 0
    base = _admin_session_item(db, session, int(msg_count))
    msg_qry = ListQuery(page=1, size=50, sort_by="created_at", sort_order="asc")
    mq = _messages_query(db, session_id, msg_qry)
    rows, _ = paginate(mq, msg_qry)
    return AdminSessionDetailResponse(
        **base.model_dump(),
        messages=[_message_item(m) for m in rows],
    )


@router.get("/{session_id}/messages", response_model=MessagePageResponse)
def get_messages_admin(
    session_id: int,
    qry: ListQuery = Depends(list_query_params),
    db: Session = Depends(get_db),
    _viewer: User = Depends(require_permission("system:session:view")),
):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    q = _messages_query(db, session_id, qry)
    rows, total = paginate(q, qry)
    return MessagePageResponse(**page_result([_message_item(m) for m in rows], total, qry))
