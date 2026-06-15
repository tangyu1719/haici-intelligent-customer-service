"""EVAL 评测看板 API — RAGAS 指标 + Span追踪 + Pass@K。"""
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


@router.get("/rag-metrics")
def rag_metrics(
    limit: int = Query(50, ge=1, le=500),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """RAG对话完整评测指标（含Pass@K、分数分布、意图分布、Span信息）"""
    from app.services.rag_eval_service import build_rag_metrics
    return build_rag_metrics(db, limit=limit, days=days)


@router.get("/rag-metrics/full-report")
def rag_full_report(
    limit: int = Query(100, ge=1, le=500),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """RAG完整评测报告 — 三层指标+管道可视化+每条指标定义/公式/阈值"""
    from app.services.rag_eval_service import build_full_eval_report
    return build_full_eval_report(db, limit=limit, days=days)


@router.get("/rag-metrics/report")
def rag_metrics_report(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """RAG评测摘要报告（不含items详情，仅聚合指标）"""
    from app.services.rag_eval_service import build_rag_metrics
    data = build_rag_metrics(db, limit=200, days=days)
    return {
        "period_days": days,
        "total": data["total"],
        "success_count": data["success_count"],
        "fail_rate": data["fail_rate"],
        "avg_top_score": data["avg_top_score"],
        "avg_citations": data["avg_citations"],
        "avg_latency_ms": data["avg_latency_ms"],
        "avg_answer_length": data["avg_answer_length"],
        "pass_at_1": data["pass_at_1"],
        "pass_at_3": data["pass_at_3"],
        "pass_at_5": data["pass_at_5"],
        "avg_faithfulness": data["avg_faithfulness"],
        "avg_answer_relevancy": data["avg_answer_relevancy"],
        "avg_context_precision": data["avg_context_precision"],
        "avg_context_recall": data["avg_context_recall"],
        "score_distribution": data["score_distribution"],
        "intent_distribution": data["intent_distribution"],
        "anti_dilution_count": data["anti_dilution_count"],
        "generated_at": data["generated_at"],
    }
