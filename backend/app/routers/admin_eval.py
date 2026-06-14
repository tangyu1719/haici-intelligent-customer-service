"""EVAL 评测看板 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.eval_service import build_eval_overview

router = APIRouter(prefix="/admin/eval", tags=["运维评测-EVAL"])


@router.get("/overview")
def eval_overview(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return build_eval_overview(db, days=days)
