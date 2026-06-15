import logging
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DailyQuestionUsage, User

logger = logging.getLogger(__name__)


def resolve_daily_limit(roles: list[str] | None) -> int | None:
    """返回每日上限；None 表示不限次（管理员默认）。"""
    role_set = set(roles or [])
    if "admin" in role_set:
        admin_limit = settings.DAILY_QUESTION_LIMIT_ADMIN
        if admin_limit <= 0:
            return None
        return admin_limit
    return settings.DAILY_QUESTION_LIMIT


def get_today_usage(db: Session, user_id: int) -> int:
    today = date.today()
    usage = (
        db.query(DailyQuestionUsage)
        .filter(DailyQuestionUsage.user_id == user_id, DailyQuestionUsage.usage_date == today)
        .first()
    )
    return int(usage.question_count) if usage else 0


def get_daily_quota_status(db: Session, user: User, roles: list[str] | None = None) -> dict:
    limit = resolve_daily_limit(roles)
    used = get_today_usage(db, user.id)
    unlimited = limit is None
    remaining = None if unlimited else max(0, limit - used)
    return {
        "daily_question_limit": limit,
        "daily_questions_used": used,
        "daily_questions_remaining": remaining,
        "daily_quota_unlimited": unlimited,
    }


def check_and_increment_daily_quota(db: Session, user: User, roles: list[str] | None = None) -> None:
    limit = resolve_daily_limit(roles)
    today = date.today()
    usage = (
        db.query(DailyQuestionUsage)
        .filter(DailyQuestionUsage.user_id == user.id, DailyQuestionUsage.usage_date == today)
        .with_for_update()
        .first()
    )
    if not usage:
        usage = DailyQuestionUsage(user_id=user.id, usage_date=today, question_count=0)
        db.add(usage)
        db.flush()

    if limit is not None and usage.question_count >= limit:
        logger.info(
            "[智能对话-提问配额|rate_limit.check_and_increment_daily_quota|user:%s|硬编执行|拒绝] 今日提问已达上限; used=%s; limit=%s; ok=false",
            user.id,
            usage.question_count,
            limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日提问次数已达上限（{limit} 次）",
        )

    usage.question_count += 1
    db.commit()
    logger.info(
        "[智能对话-提问配额|rate_limit.check_and_increment_daily_quota|user:%s|硬编执行|计数] 提问计数+1; used=%s; limit=%s; ok=true",
        user.id,
        usage.question_count,
        limit if limit is not None else "unlimited",
    )
