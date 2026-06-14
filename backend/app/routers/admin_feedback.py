"""管理员：查看全部用户对话反馈（分页 + 筛选）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import MessageFeedback, User
from app.schemas import FeedbackAdminDetailResponse, FeedbackAdminItem, FeedbackAdminListResponse
from app.services.feedback_analytics import FEEDBACK_AI_PERSONA, build_feedback_analytics, run_feedback_ai_analysis
from app.services.feedback_detail import build_feedback_detail
from app.services.list_query import (
    ListQuery,
    apply_date_range,
    apply_id_filter,
    apply_keyword,
    apply_sort,
    list_query_params,
    page_result,
    paginate,
)

router = APIRouter(prefix="/admin/feedback", tags=["运维评测-用户反馈"])


@router.get("/analytics")
def feedback_analytics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_user),
):
    data = build_feedback_analytics(db, days=days)
    return {"ok": True, "persona_hint": FEEDBACK_AI_PERSONA, **data}


@router.post("/ai-analysis")
async def feedback_ai_analysis(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_user),
):
    return await run_feedback_ai_analysis(db, days=days)


@router.get("/persona")
def feedback_agent_persona(_admin: User = Depends(get_current_user)):
    return {"ok": True, "persona": FEEDBACK_AI_PERSONA}

_FEEDBACK_SORT = {
    "id": MessageFeedback.id,
    "created_at": MessageFeedback.created_at,
    "rating": MessageFeedback.rating,
    "user_id": MessageFeedback.user_id,
    "message_id": MessageFeedback.message_id,
}


def _to_admin_item(db: Session, row: MessageFeedback) -> FeedbackAdminItem:
    user = db.get(User, row.user_id)
    detail = build_feedback_detail(db, row)
    snap = row.context_snapshot_json or {}
    return FeedbackAdminItem(
        id=row.id,
        message_id=row.message_id,
        user_id=row.user_id,
        username=user.username if user else None,
        nickname=user.nickname if user else None,
        rating=row.rating,
        intent_liked=bool(row.intent_liked) if row.intent_liked is not None else None,
        comment=row.comment,
        context_snapshot=snap if snap else None,
        created_at=row.created_at,
        session_id=detail.get("session_id"),
        context_id=detail.get("context_id") or "",
        user_question=detail.get("user_question") or "",
        assistant_answer=detail.get("assistant_answer") or "",
        context_summary=detail.get("context_summary") or "",
        intent=detail.get("intent") or "",
        intent_label=detail.get("intent_label") or "",
        corrected_intent=detail.get("corrected_intent") or "",
        corrected_intent_label=detail.get("corrected_intent_label") or "",
        session_title=detail.get("session_title") or "",
    )


@router.get("", response_model=FeedbackAdminListResponse)
def list_all_feedback(
    qry: ListQuery = Depends(list_query_params),
    user_id: int | None = Query(None, description="用户 ID"),
    rating: int | None = Query(None, ge=1, le=5, description="满意度星级"),
    intent_liked: int | None = Query(None, ge=0, le=1, description="意图评价 1赞0踩"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_user),
):
    q = db.query(MessageFeedback)
    q = apply_id_filter(q, MessageFeedback.id, qry)
    if user_id is not None:
        q = q.filter(MessageFeedback.user_id == user_id)
    if rating is not None:
        q = q.filter(MessageFeedback.rating == rating)
    if intent_liked is not None:
        q = q.filter(MessageFeedback.intent_liked == intent_liked)
    if qry.name:
        q = q.join(User, User.id == MessageFeedback.user_id).filter(
            (User.username.ilike(f"%{qry.name}%")) | (User.nickname.ilike(f"%{qry.name}%"))
        )
    q = apply_keyword(q, qry, [MessageFeedback.comment])
    q = apply_date_range(q, MessageFeedback.created_at, qry)
    q = apply_sort(q, MessageFeedback, qry, _FEEDBACK_SORT, MessageFeedback.created_at)
    rows, total = paginate(q, qry)
    items = [_to_admin_item(db, row) for row in rows]
    return FeedbackAdminListResponse(**page_result(items, total, qry))


@router.get("/{feedback_id}", response_model=FeedbackAdminDetailResponse)
def get_feedback_detail(
    feedback_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_user),
):
    row = db.get(MessageFeedback, feedback_id)
    if not row:
        raise HTTPException(status_code=404, detail="反馈记录不存在")
    return FeedbackAdminDetailResponse(item=_to_admin_item(db, row))
