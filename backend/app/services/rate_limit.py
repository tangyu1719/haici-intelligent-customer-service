from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DailyQuestionUsage, User


def check_and_increment_daily_quota(db: Session, user: User) -> None:
    today = date.today()
    usage = (
        db.query(DailyQuestionUsage)
        .filter(DailyQuestionUsage.user_id == user.id, DailyQuestionUsage.usage_date == today)
        .first()
    )
    if not usage:
        usage = DailyQuestionUsage(user_id=user.id, usage_date=today, question_count=0)
        db.add(usage)
        db.flush()
    if usage.question_count >= settings.DAILY_QUESTION_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日提问次数已达上限（{settings.DAILY_QUESTION_LIMIT} 次）",
        )
    usage.question_count += 1
    db.commit()
