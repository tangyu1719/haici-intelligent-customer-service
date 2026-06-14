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
