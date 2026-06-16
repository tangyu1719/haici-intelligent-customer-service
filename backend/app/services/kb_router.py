"""多知识库路由：权限过滤 → 智能选库 → 检索质量不足时二次路由。

流程（与意图 Pipeline 串联，在 RAG 检索前/后执行）：
1. 按用户权限列出可访问知识库（本人名下 status=1；admin 可访问全部启用库）
2. 未显式指定 kb_id 时，对各候选库做向量探针 + 元数据加权评分，选最优
3. 正式检索后若片段数 < RAG_TOP_K 或 top_score < RAG_SCORE_THRESHOLD，
   排除当前库，对剩余候选库做二次路由并重新检索
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.config import settings
from app.models import KnowledgeBase, KnowledgeDocument
from app.rag import retrieve_merged, safe_retrieve_merged

logger = logging.getLogger(__name__)

_FILENAME_HIT_WEIGHT = 0.15
_NAME_DESC_HIT_WEIGHT = 0.10


@dataclass
class KbRouteDecision:
    """单次知识库路由决策。"""

    kb_id: int | None
    kb_name: str | None
    tenant_id: str
    routed: bool
    route_score: float = 0.0
    reason: str = ""
    round_index: int = 0  # 0=首轮，1=二次回退
    excluded_kb_ids: list[int] = field(default_factory=list)
    all_scores: list[tuple[int, str, float]] = field(default_factory=list)


@dataclass
class KbRetrievalResult:
    """路由 + 检索合并结果。"""

    docs: list[Document]
    anti_dilution_summary: str | None
    decision: KbRouteDecision
    fallback_applied: bool = False
    primary_decision: KbRouteDecision | None = None


def list_accessible_knowledge_bases(
    db: Session,
    user_id: int,
    roles: list[str] | None = None,
) -> list[KnowledgeBase]:
    """按用户权限返回可参与路由的知识库列表。"""
    roles = roles or []
    q = db.query(KnowledgeBase).filter(KnowledgeBase.status == 1)
    if "admin" not in roles:
        q = q.filter(KnowledgeBase.user_id == user_id)
    return q.order_by(KnowledgeBase.is_default.desc(), KnowledgeBase.created_at.desc()).all()


def _kb_has_ready_docs(db: Session, kb_id: int) -> bool:
    return (
        db.query(KnowledgeDocument.id)
        .filter(KnowledgeDocument.kb_id == kb_id, KnowledgeDocument.status == "ready")
        .first()
        is not None
    )


def _metadata_boost(question: str, kb: KnowledgeBase, docs: list[KnowledgeDocument]) -> float:
    """文档名 / 库名 / 描述关键词轻量加分（辅助向量探针）。"""
    q_lower = (question or "").lower()
    tokens = [t for t in re.split(r"[\s，。；;、/?？]+", q_lower) if len(t) >= 2]
    if not tokens:
        return 0.0
    boost = 0.0
    name_desc = f"{kb.name or ''} {kb.description or ''}".lower()
    name_hits = sum(1 for t in tokens if t in name_desc)
    if name_hits:
        boost += min(_NAME_DESC_HIT_WEIGHT, name_hits * 0.03)
    if docs:
        file_hits = sum(
            1 for d in docs if any(t in (d.filename or "").lower() for t in tokens)
        )
        boost += min(_FILENAME_HIT_WEIGHT, (file_hits / len(docs)) * 0.3)
    return boost


def _probe_kb_score(
    db: Session,
    kb: KnowledgeBase,
    rag_query: str,
    question: str,
) -> tuple[float, list[Document]]:
    """对单个知识库做轻量向量探针，返回综合分与探针片段。"""
    docs_meta = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.kb_id == kb.id, KnowledgeDocument.status == "ready")
        .all()
    )
    if not docs_meta:
        return 0.0, []

    try:
        probe_docs = retrieve_merged(rag_query, str(kb.id))
    except Exception as exc:
        logger.warning(
            "[智能客服-知识库路由|kb_router|探针检索|硬编执行|失败] kb_id=%s; error_type=%s; error_message=%s",
            kb.id,
            type(exc).__name__,
            str(exc)[:120],
        )
        return _metadata_boost(question, kb, docs_meta), []

    if not probe_docs:
        return _metadata_boost(question, kb, docs_meta), []

    top_score = max(float(d.metadata.get("score", 0)) for d in probe_docs)
    count_factor = min(len(probe_docs), settings.RAG_TOP_K) / max(settings.RAG_TOP_K, 1)
    score = top_score * 0.75 + count_factor * 0.15 + _metadata_boost(question, kb, docs_meta)
    return min(score, 1.0), probe_docs


def rank_knowledge_bases(
    db: Session,
    kbs: list[KnowledgeBase],
    question: str,
    rag_query: str,
    *,
    exclude_kb_ids: set[int] | None = None,
) -> list[tuple[KnowledgeBase, float]]:
    """对候选知识库按探针分排序（高→低）。"""
    exclude = exclude_kb_ids or set()
    scored: list[tuple[KnowledgeBase, float]] = []
    for kb in kbs:
        if kb.id in exclude:
            continue
        if not _kb_has_ready_docs(db, kb.id):
            continue
        score, _ = _probe_kb_score(db, kb, rag_query, question)
        scored.append((kb, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def retrieval_sufficient(docs: list[Document]) -> tuple[bool, float, int]:
    """判断检索结果是否达到正常回答门槛。"""
    if not docs:
        return False, 0.0, 0
    top_score = max(float(d.metadata.get("hybrid_score", d.metadata.get("score", 0))) for d in docs)
    count = len(docs)
    ok = count >= settings.RAG_TOP_K and top_score >= settings.RAG_SCORE_THRESHOLD
    return ok, top_score, count


def select_kb_route(
    db: Session,
    user_id: int,
    question: str,
    rag_query: str,
    *,
    roles: list[str] | None = None,
    explicit_kb_id: int | None = None,
    exclude_kb_ids: set[int] | None = None,
    round_index: int = 0,
    fallback_user_tenant: str | None = None,
) -> KbRouteDecision:
    """选库：权限过滤 → 智能评分 → 决策。"""
    exclude = exclude_kb_ids or set()
    accessible = list_accessible_knowledge_bases(db, user_id, roles)

    if explicit_kb_id is not None and round_index == 0:
        kb = db.get(KnowledgeBase, explicit_kb_id)
        if kb and kb.status == 1 and (kb.user_id == user_id or (roles and "admin" in roles)):
            return KbRouteDecision(
                kb_id=kb.id,
                kb_name=kb.name,
                tenant_id=str(kb.id),
                routed=False,
                route_score=1.0,
                reason="用户显式指定知识库",
                round_index=round_index,
                excluded_kb_ids=list(exclude),
            )
        logger.warning(
            "[智能客服-知识库路由|kb_router|显式选库|硬编执行|无权] kb_id=%s; user_id=%s",
            explicit_kb_id,
            user_id,
        )

    if not accessible:
        tenant = fallback_user_tenant or str(user_id)
        return KbRouteDecision(
            kb_id=None,
            kb_name=None,
            tenant_id=tenant,
            routed=False,
            reason="无可访问知识库，回退 user_id 租户",
            round_index=round_index,
            excluded_kb_ids=list(exclude),
        )

    if len(accessible) == 1:
        kb = accessible[0]
        return KbRouteDecision(
            kb_id=kb.id,
            kb_name=kb.name,
            tenant_id=str(kb.id),
            routed=True,
            route_score=1.0,
            reason="仅一个可访问知识库",
            round_index=round_index,
            excluded_kb_ids=list(exclude),
        )

    ranked = rank_knowledge_bases(db, accessible, question, rag_query, exclude_kb_ids=exclude)
    all_scores = [(kb.id, kb.name, round(s, 4)) for kb, s in ranked]

    if not ranked:
        default = next((kb for kb in accessible if kb.is_default == 1), accessible[0])
        return KbRouteDecision(
            kb_id=default.id,
            kb_name=default.name,
            tenant_id=str(default.id),
            routed=False,
            route_score=0.0,
            reason="候选库均无就绪文档，使用默认知识库",
            round_index=round_index,
            excluded_kb_ids=list(exclude),
            all_scores=all_scores,
        )

    best_kb, best_score = ranked[0]
    min_route_score = settings.RAG_SCORE_THRESHOLD * 0.5
    if best_score < min_route_score:
        default = next((kb for kb in accessible if kb.id not in exclude and kb.is_default == 1), ranked[0][0])
        return KbRouteDecision(
            kb_id=default.id,
            kb_name=default.name,
            tenant_id=str(default.id),
            routed=False,
            route_score=best_score,
            reason="探针分过低，使用默认知识库",
            round_index=round_index,
            excluded_kb_ids=list(exclude),
            all_scores=all_scores,
        )

    reason = "二次路由命中" if round_index > 0 else "向量探针智能路由"
    return KbRouteDecision(
        kb_id=best_kb.id,
        kb_name=best_kb.name,
        tenant_id=str(best_kb.id),
        routed=True,
        route_score=best_score,
        reason=reason,
        round_index=round_index,
        excluded_kb_ids=list(exclude),
        all_scores=all_scores,
    )


def retrieve_with_kb_fallback(
    db: Session,
    user_id: int,
    question: str,
    rag_query: str,
    *,
    roles: list[str] | None = None,
    explicit_kb_id: int | None = None,
    apply_anti_dilution: bool = True,
    allow_fallback: bool = True,
) -> KbRetrievalResult:
    """完整链路：选库 → 检索 → 质量不足时排除当前库二次路由。"""
    primary = select_kb_route(
        db,
        user_id,
        question,
        rag_query,
        roles=roles,
        explicit_kb_id=explicit_kb_id,
        fallback_user_tenant=str(user_id),
    )
    docs, ad_summary = safe_retrieve_merged(
        rag_query,
        primary.tenant_id,
        apply_anti_dilution=apply_anti_dilution,
    )
    if not docs and question.strip() and question.strip() != rag_query.strip():
        docs, ad_summary = safe_retrieve_merged(
            question,
            primary.tenant_id,
            apply_anti_dilution=apply_anti_dilution,
        )

    sufficient, top_score, count = retrieval_sufficient(docs)
    logger.info(
        "[智能客服-知识库路由|kb_router|首轮检索|硬编执行|完成] kb_id=%s; slices=%s; top_score=%.3f; sufficient=%s; round=%s",
        primary.kb_id,
        count,
        top_score,
        sufficient,
        primary.round_index,
    )

    if sufficient or not allow_fallback or explicit_kb_id is not None:
        return KbRetrievalResult(
            docs=docs,
            anti_dilution_summary=ad_summary,
            decision=primary,
            fallback_applied=False,
            primary_decision=primary,
        )

    if primary.kb_id is None:
        return KbRetrievalResult(
            docs=docs,
            anti_dilution_summary=ad_summary,
            decision=primary,
            fallback_applied=False,
            primary_decision=primary,
        )

    exclude = {primary.kb_id}
    secondary = select_kb_route(
        db,
        user_id,
        question,
        rag_query,
        roles=roles,
        exclude_kb_ids=exclude,
        round_index=1,
        fallback_user_tenant=str(user_id),
    )
    if secondary.kb_id is None or secondary.kb_id == primary.kb_id:
        return KbRetrievalResult(
            docs=docs,
            anti_dilution_summary=ad_summary,
            decision=primary,
            fallback_applied=False,
            primary_decision=primary,
        )

    fb_docs, fb_ad = safe_retrieve_merged(
        rag_query,
        secondary.tenant_id,
        apply_anti_dilution=apply_anti_dilution,
    )
    fb_ok, fb_top, fb_count = retrieval_sufficient(fb_docs)
    logger.info(
        "[智能客服-知识库路由|kb_router|二次路由检索|硬编执行|完成] primary_kb=%s; fallback_kb=%s; "
        "slices=%s; top_score=%.3f; sufficient=%s",
        primary.kb_id,
        secondary.kb_id,
        fb_count,
        fb_top,
        fb_ok,
    )

    if fb_ok or (fb_count > count) or (fb_top > top_score):
        secondary.excluded_kb_ids = list(exclude)
        return KbRetrievalResult(
            docs=fb_docs,
            anti_dilution_summary=fb_ad,
            decision=secondary,
            fallback_applied=True,
            primary_decision=primary,
        )

    return KbRetrievalResult(
        docs=docs,
        anti_dilution_summary=ad_summary,
        decision=primary,
        fallback_applied=False,
        primary_decision=primary,
    )
