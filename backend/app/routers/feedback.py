from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ChatMessage, ChatSession, MessageFeedback, User
from app.schemas import FeedbackRequest

router = APIRouter(prefix="/feedback", tags=["反馈"])


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
    row = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.message_id == message_id, MessageFeedback.user_id == current_user.id)
        .first()
    )
    if row:
        row.rating = payload.rating
        row.comment = payload.comment
    else:
        db.add(MessageFeedback(message_id=message_id, user_id=current_user.id, rating=payload.rating, comment=payload.comment))
    db.commit()
    return {"ok": True}
