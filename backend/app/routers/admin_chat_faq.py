"""系统管理 - 对话 FAQ 配置（仅 ADMIN）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import ChatFaq, User
from app.services.chat_faq import faq_to_dict, get_chat_faq_items, invalidate_faq_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/chat-faq", tags=["系统管理-FAQ"])


class ChatFaqUpsertBody(BaseModel):
    category: str = Field(default="通用", max_length=64)
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=8000)
    sort_order: int = Field(default=0, ge=0, le=9999)
    enabled: bool = True


@router.get("")
def list_chat_faq(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return {"ok": True, "items": get_chat_faq_items(db, include_disabled=True)}


@router.post("")
def create_chat_faq(
    body: ChatFaqUpsertBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = ChatFaq(
        category=body.category.strip() or "通用",
        question=body.question.strip(),
        answer=body.answer.strip(),
        sort_order=body.sort_order,
        enabled=1 if body.enabled else 0,
        updated_by=admin.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    invalidate_faq_cache()
    logger.info(
        "[智能客服-FAQ|admin_chat_faq.create|faq_id=%s|硬编执行|完成] admin_id=%s",
        row.id,
        admin.id,
    )
    return {"ok": True, "item": faq_to_dict(row)}


@router.put("/{faq_id}")
def update_chat_faq(
    faq_id: int,
    body: ChatFaqUpsertBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = db.get(ChatFaq, faq_id)
    if not row:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    row.category = body.category.strip() or "通用"
    row.question = body.question.strip()
    row.answer = body.answer.strip()
    row.sort_order = body.sort_order
    row.enabled = 1 if body.enabled else 0
    row.updated_by = admin.id
    db.commit()
    db.refresh(row)
    invalidate_faq_cache()
    logger.info(
        "[智能客服-FAQ|admin_chat_faq.update|faq_id=%s|硬编执行|完成] admin_id=%s",
        faq_id,
        admin.id,
    )
    return {"ok": True, "item": faq_to_dict(row)}


@router.delete("/{faq_id}")
def delete_chat_faq(
    faq_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = db.get(ChatFaq, faq_id)
    if not row:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    db.delete(row)
    db.commit()
    invalidate_faq_cache()
    logger.info(
        "[智能客服-FAQ|admin_chat_faq.delete|faq_id=%s|硬编执行|完成] admin_id=%s",
        faq_id,
        admin.id,
    )
    return {"ok": True}
