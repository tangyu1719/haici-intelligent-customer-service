"""多知识库路由 (PRD 加分项4)

支持创建多个知识库，提问时自动判断路由到最相关的知识库。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import KnowledgeBase, KnowledgeDocument, User
from app.services.list_query import (
    ListQuery,
    apply_keyword,
    apply_sort,
    list_query_params,
    page_result,
    paginate,
)

router = APIRouter(prefix="/knowledge-bases", tags=["知识库管理"])


class KBCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="知识库名称")
    description: str | None = Field(default=None, max_length=512, description="知识库描述")
    is_default: int = Field(default=0, ge=0, le=1, description="是否设为默认知识库")


class KBUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    is_default: int | None = Field(default=None, ge=0, le=1)
    status: int | None = Field(default=None, ge=0, le=1)


class KBItemResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_default: int
    status: int
    doc_count: int
    created_at: str
    updated_at: str | None

    model_config = {"from_attributes": True}


class KBPageResponse(BaseModel):
    ok: bool = True
    items: list[KBItemResponse]
    total: int
    page: int
    page_size: int


def _kb_to_item(kb: KnowledgeBase, doc_count: int = 0) -> KBItemResponse:
    return KBItemResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        is_default=kb.is_default,
        status=kb.status,
        doc_count=doc_count,
        created_at=kb.created_at.isoformat() if kb.created_at else "",
        updated_at=kb.updated_at.isoformat() if kb.updated_at else None,
    )


@router.get("", response_model=KBPageResponse)
def list_kbs(
    qry: ListQuery = Depends(list_query_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取用户的所有知识库列表。"""
    q = db.query(KnowledgeBase).filter(
        KnowledgeBase.user_id == current_user.id,
        KnowledgeBase.status == 1,
    )
    q = apply_keyword(q, qry, [KnowledgeBase.name, KnowledgeBase.description])
    q = apply_sort(
        q, KnowledgeBase, qry,
        {"id": KnowledgeBase.id, "name": KnowledgeBase.name, "created_at": KnowledgeBase.created_at},
        KnowledgeBase.created_at,
    )
    rows, total = paginate(q, qry)

    items: list[KBItemResponse] = []
    for kb in rows:
        doc_count = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.kb_id == kb.id,
            KnowledgeDocument.status == "ready",
        ).count()
        items.append(_kb_to_item(kb, doc_count=doc_count))

    return KBPageResponse(**page_result(items, total, qry))


@router.get("/all")
def list_all_kbs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取用户所有知识库的简要列表（供下拉选择器使用）。"""
    kbs = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.user_id == current_user.id,
            KnowledgeBase.status == 1,
        )
        .order_by(KnowledgeBase.is_default.desc(), KnowledgeBase.created_at.desc())
        .all()
    )
    return {
        "ok": True,
        "items": [
            {
                "id": kb.id,
                "name": kb.name,
                "is_default": kb.is_default,
                "doc_count": db.query(KnowledgeDocument).filter(
                    KnowledgeDocument.kb_id == kb.id,
                    KnowledgeDocument.status == "ready",
                ).count(),
            }
            for kb in kbs
        ],
    }


@router.post("")
def create_kb(
    body: KBCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新知识库。"""
    existing = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.user_id == current_user.id, KnowledgeBase.name == body.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="知识库名称已存在")

    if body.is_default:
        db.query(KnowledgeBase).filter(
            KnowledgeBase.user_id == current_user.id, KnowledgeBase.is_default == 1
        ).update({"is_default": 0})

    kb = KnowledgeBase(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        is_default=body.is_default,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return {"ok": True, "item": _kb_to_item(kb, doc_count=0)}


@router.get("/{kb_id}")
def get_kb(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单个知识库详情。"""
    kb = db.get(KnowledgeBase, kb_id)
    if not kb or kb.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="知识库不存在")
    doc_count = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.kb_id == kb.id, KnowledgeDocument.status == "ready"
    ).count()
    return {"ok": True, "item": _kb_to_item(kb, doc_count=doc_count)}


@router.put("/{kb_id}")
def update_kb(
    kb_id: int,
    body: KBUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新知识库信息。"""
    kb = db.get(KnowledgeBase, kb_id)
    if not kb or kb.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if body.name is not None and body.name != kb.name:
        existing = (
            db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.user_id == current_user.id,
                KnowledgeBase.name == body.name,
                KnowledgeBase.id != kb_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="知识库名称已存在")
        kb.name = body.name

    if body.description is not None:
        kb.description = body.description
    if body.is_default is not None and body.is_default == 1:
        db.query(KnowledgeBase).filter(
            KnowledgeBase.user_id == current_user.id, KnowledgeBase.is_default == 1
        ).update({"is_default": 0})
        kb.is_default = 1
    if body.status is not None:
        kb.status = body.status

    db.commit()
    db.refresh(kb)
    doc_count = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.kb_id == kb.id, KnowledgeDocument.status == "ready"
    ).count()
    return {"ok": True, "item": _kb_to_item(kb, doc_count=doc_count)}


@router.delete("/{kb_id}")
def delete_kb(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除知识库（清除关联文档的 KB 关联）。"""
    kb = db.get(KnowledgeBase, kb_id)
    if not kb or kb.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 解除关联文档的 kb_id
    db.query(KnowledgeDocument).filter(KnowledgeDocument.kb_id == kb_id).update({"kb_id": None})
    db.delete(kb)
    db.commit()
    return {"ok": True, "message": "知识库已删除，关联文档已解除绑定"}


@router.post("/auto-route")
def auto_route_kb(
    question: str = Query(..., min_length=1, max_length=500, description="用户问题"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自动路由：根据问题内容判断最相关的知识库。

    优先匹配默认知识库，然后根据关键词匹配各知识库的文档名称。
    """
    question_lower = question.lower()

    kbs = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.user_id == current_user.id,
            KnowledgeBase.status == 1,
        )
        .all()
    )

    if not kbs:
        return {"ok": True, "kb_id": None, "kb_name": None, "routed": False}

    # 只有一个知识库时直接返回
    if len(kbs) == 1:
        return {"ok": True, "kb_id": kbs[0].id, "kb_name": kbs[0].name, "routed": True}

    # 多知识库时按文档关键词匹配度评分
    kb_scores: list[tuple[int, str, float]] = []
    for kb in kbs:
        docs = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.kb_id == kb.id,
                KnowledgeDocument.status == "ready",
            )
            .all()
        )
        if not docs:
            kb_scores.append((kb.id, kb.name, 0.0))
            continue

        keyword_hits = sum(
            1 for doc in docs
            if any(kw in doc.filename.lower() for kw in question_lower.split())
        )
        hit_ratio = keyword_hits / len(docs)
        kb_scores.append((kb.id, kb.name, hit_ratio))

    kb_scores.sort(key=lambda x: x[2], reverse=True)
    best_kb = kb_scores[0]

    if best_kb[2] < 0.1:
        # 所有知识库匹配度都低，使用默认知识库
        default_kb = next((kb for kb in kbs if kb.is_default == 1), kbs[0])
        return {
            "ok": True,
            "kb_id": default_kb.id,
            "kb_name": default_kb.name,
            "routed": False,
            "score": 0.0,
            "reason": "无明确匹配，使用默认知识库",
        }

    return {
        "ok": True,
        "kb_id": best_kb[0],
        "kb_name": best_kb[1],
        "routed": True,
        "score": best_kb[2],
        "all_scores": [(kid, name, round(s, 4)) for kid, name, s in kb_scores],
    }
