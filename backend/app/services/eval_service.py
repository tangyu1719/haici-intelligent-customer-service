"""EVAL 评测：聚合 Agent 专链调用指标（LLM/RAG/工具/MCP/嵌入）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import SysLogApiCall
from app.services.agent_call_logger import AGENT_API_TYPES


def _parse_meta(summary: str | None) -> dict:
    if not summary:
        return {}
    try:
        data = json.loads(summary)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _aggregate_rows(rows: list[SysLogApiCall]) -> dict:
    total = len(rows)
    ok = sum(1 for r in rows if r.success == 1)
    fail = total - ok
    rtts = [r.time_consume_ms for r in rows if r.time_consume_ms]
    tokens = 0
    recall_vals: list[float] = []
    hit_vals: list[int] = []
    for r in rows:
        meta = _parse_meta(r.response_summary)
        tokens += int(meta.get("tokens") or 0)
        if "recall" in meta:
            recall_vals.append(float(meta["recall"]))
        if "hits" in meta:
            hit_vals.append(int(meta["hits"]))
    return {
        "call_count": total,
        "success_count": ok,
        "fail_count": fail,
        "fail_rate": round(fail / total, 4) if total else 0.0,
        "avg_rtt_ms": round(sum(rtts) / len(rtts), 1) if rtts else 0,
        "total_tokens": tokens,
        "avg_tokens": round(tokens / total, 1) if total else 0,
        "recall_rate": round(sum(recall_vals) / len(recall_vals), 4) if recall_vals else None,
        "accuracy_rate": round(ok / total, 4) if total else None,
        "avg_hits": round(sum(hit_vals) / len(hit_vals), 2) if hit_vals else None,
    }


def build_eval_overview(db: Session, *, days: int = 7) -> dict:
    since = datetime.utcnow() - timedelta(days=max(1, days))
    rows = (
        db.query(SysLogApiCall)
        .filter(SysLogApiCall.api_type.in_(AGENT_API_TYPES), SysLogApiCall.created_at >= since)
        .all()
    )
    by_type: dict[str, dict] = {}
    for t in AGENT_API_TYPES:
        by_type[t] = _aggregate_rows([r for r in rows if r.api_type == t])

    daily: list[dict] = []
    for d in range(days):
        day_start = (since + timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        day_rows = [r for r in rows if day_start <= r.created_at.replace(tzinfo=None) < day_end]
        daily.append(
            {
                "date": day_start.strftime("%Y-%m-%d"),
                "call_count": len(day_rows),
                "fail_count": sum(1 for r in day_rows if r.success != 1),
                "avg_rtt_ms": round(sum(r.time_consume_ms for r in day_rows) / len(day_rows), 1) if day_rows else 0,
            }
        )

    return {
        "period_days": days,
        "generated_at": datetime.utcnow().isoformat(),
        "summary": _aggregate_rows(rows),
        "by_type": by_type,
        "daily_trend": daily,
        "types": list(AGENT_API_TYPES),
    }


def build_rag_metrics(db: Session, *, limit: int = 50) -> dict:
    """提取最近的 RAG 对话指标详情"""
    rows = (
        db.query(SysLogApiCall)
        .filter(SysLogApiCall.api_type == "rag")
        .order_by(SysLogApiCall.created_at.desc())
        .limit(limit)
        .all()
    )
    items: list[dict] = []
    for r in rows:
        meta = _parse_meta(r.response_summary)
        items.append({
            "id": r.log_id,
            "trace_id": r.trace_id,
            "question": meta.get("question", "")[:200],
            "intent": meta.get("intent", ""),
            "intent_label": meta.get("intent_label", ""),
            "rewritten_query": meta.get("rewritten_query", "")[:200],
            "rag_query": meta.get("rag_query", "")[:200],
            "keywords": meta.get("keywords", []),
            "retrieval_terms": meta.get("retrieval_terms", []),
            "citations_count": meta.get("citations_count", 0),
            "top_score": meta.get("top_score", 0.0),
            "anti_dilution": meta.get("anti_dilution", False),
            "kb_id": meta.get("kb_id"),
            "auto_routed": meta.get("auto_routed", False),
            "llm_provider": meta.get("llm_provider", ""),
            "llm_model": meta.get("llm_model", ""),
            "llm_task_type": meta.get("llm_task_type", ""),
            "answer_length": meta.get("answer_length", 0),
            "follow_ups_count": meta.get("follow_ups_count", 0),
            "total_tokens": meta.get("total_tokens", 0),
            "time_consume_ms": r.time_consume_ms,
            "success": r.success == 1,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        })

    # 计算聚合指标
    success_count = sum(1 for i in items if i["success"])
    avg_top_score = round(sum(i["top_score"] for i in items) / len(items), 4) if items else 0
    avg_citations = round(sum(i["citations_count"] for i in items) / len(items), 4) if items else 0
    avg_latency = round(sum(i["time_consume_ms"] for i in items) / len(items), 0) if items else 0
    avg_answer_len = round(sum(i["answer_length"] for i in items) / len(items), 0) if items else 0
    anti_dilution_count = sum(1 for i in items if i["anti_dilution"])

    return {
        "total": len(items),
        "success_count": success_count,
        "fail_count": len(items) - success_count,
        "fail_rate": round((len(items) - success_count) / max(len(items), 1), 4),
        "avg_top_score": avg_top_score,
        "avg_citations": avg_citations,
        "avg_latency_ms": avg_latency,
        "avg_answer_length": avg_answer_len,
        "anti_dilution_count": anti_dilution_count,
        "items": items,
        "generated_at": datetime.utcnow().isoformat(),
    }
