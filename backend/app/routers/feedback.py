from datetime import datetime



from fastapi import APIRouter, Depends, HTTPException



from sqlalchemy.orm import Session



from app.database import get_db

from app.deps import get_current_user

from app.models import ChatMessage, ChatSession, MessageFeedback, User

from app.schemas import FeedbackAdminItem, FeedbackAdminListResponse, FeedbackRequest

from app.services.feedback_detail import build_feedback_detail

from app.services.list_query import ListQuery, apply_sort, list_query_params, page_result, paginate



router = APIRouter(prefix="/feedback", tags=["反馈"])





def _validate_intent_dislike(payload: FeedbackRequest) -> None:

    if payload.intent_liked is not True and payload.intent_liked is not False:

        return

    if payload.intent_liked is False:

        snap = payload.context_snapshot

        if not snap:

            raise HTTPException(status_code=400, detail="意图理解有误时，请选择您认为的正确意图")

        corrected = (snap.corrected_intent or "").strip() or (snap.corrected_intent_label or "").strip()

        if not corrected:

            raise HTTPException(status_code=400, detail="意图理解有误时，请选择您认为的正确意图或填写说明")





def _append_comment_history(merged: dict, text: str) -> None:

    hist = list(merged.get("comments_history") or [])

    hist.append({"text": text, "created_at": datetime.now().isoformat(timespec="seconds")})

    merged["comments_history"] = hist[-30:]





def _to_my_item(db: Session, row: MessageFeedback) -> FeedbackAdminItem:

    detail = build_feedback_detail(db, row)

    snap = row.context_snapshot_json or {}

    return FeedbackAdminItem(

        id=row.id,

        message_id=row.message_id,

        user_id=row.user_id,

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

    )





@router.get("/my", response_model=FeedbackAdminListResponse)

def my_feedback_list(

    qry: ListQuery = Depends(list_query_params),

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_user),

):

    """当前用户的回答反馈记录（含星级、补充说明历史）。"""

    q = db.query(MessageFeedback).filter(MessageFeedback.user_id == current_user.id)

    sort_map = {

        "id": MessageFeedback.id,

        "created_at": MessageFeedback.created_at,

        "rating": MessageFeedback.rating,

        "message_id": MessageFeedback.message_id,

    }

    q = apply_sort(q, MessageFeedback, qry, sort_map, MessageFeedback.created_at)

    rows, total = paginate(q, qry)

    items = [_to_my_item(db, row) for row in rows]

    return FeedbackAdminListResponse(**page_result(items, total, qry))





@router.post("/messages/{message_id}")

def submit_feedback(

    message_id: int,

    payload: FeedbackRequest,

    db: Session = Depends(get_db),

    current_user: User = Depends(get_current_user),

):

    message = db.get(ChatMessage, message_id)

    if not message or message.role != "assistant":

        raise HTTPException(status_code=404, detail="消息不存在")

    session = db.get(ChatSession, message.session_id)

    if not session or session.user_id != current_user.id:

        raise HTTPException(status_code=403, detail="无权反馈")



    fields_set = payload.model_fields_set

    snapshot = payload.context_snapshot.model_dump() if payload.context_snapshot else None

    intent_liked_val = None

    if payload.intent_liked is not None:

        intent_liked_val = 1 if payload.intent_liked else 0



    if "intent_liked" in fields_set:

        _validate_intent_dislike(payload)



    comment_text = ((payload.comment or "").strip() or None) if "comment" in fields_set else None



    row = (

        db.query(MessageFeedback)

        .filter(MessageFeedback.message_id == message_id, MessageFeedback.user_id == current_user.id)

        .first()

    )

    if row:

        if "rating" in fields_set and payload.rating is not None:

            row.rating = payload.rating

        if "comment" in fields_set:

            row.comment = comment_text

        if "intent_liked" in fields_set:

            row.intent_liked = intent_liked_val

        if snapshot is not None or comment_text:

            merged = dict(row.context_snapshot_json or {})

            if snapshot is not None:

                merged.update(snapshot)

            if comment_text:

                _append_comment_history(merged, comment_text)

            row.context_snapshot_json = merged

    else:

        rating_val = payload.rating

        if rating_val is None and "rating" not in fields_set:

            raise HTTPException(status_code=400, detail="请先为回答评分")

        if rating_val is None:

            raise HTTPException(status_code=400, detail="请先为回答评分")

        merged = dict(snapshot or {})

        if comment_text:

            _append_comment_history(merged, comment_text)

        db.add(

            MessageFeedback(

                message_id=message_id,

                user_id=current_user.id,

                rating=rating_val,

                comment=comment_text if "comment" in fields_set else None,

                intent_liked=intent_liked_val if "intent_liked" in fields_set else None,

                context_snapshot_json=merged or None,

            )

        )

    try:

        db.commit()

    except Exception as exc:

        db.rollback()

        raise HTTPException(status_code=500, detail=f"反馈保存失败：{type(exc).__name__}") from exc

    return {"ok": True}


