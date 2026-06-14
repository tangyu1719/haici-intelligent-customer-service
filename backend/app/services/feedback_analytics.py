"""用户反馈数据分析 + AI 评测 Agent。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import MessageFeedback
from app.services.feedback_demo_data import build_demo_feedback_analytics
from app.services.feedback_detail import build_feedback_detail
from app.services.term_dictionary import INTENT_LABELS

FEEDBACK_AI_PERSONA = {
    "agent_id": "feedback_analytics_agent",
    "display_name": "评测分析师 · 小析",
    "role": "HaiCi 智能客服运维评测分析师",
    "reply_style": "数据驱动、结构清晰、结论可执行",
    "layers": {
        "L0": "你是「小析」，专注用户反馈与意图数据的深度解读，语气专业但不生硬。",
        "L1": "从意图分布、满意度、失败意图、回答质量四维度输出洞察与改进建议。",
        "L2": "禁止编造数据；引用看板数字；输出 Markdown 结构化报告。",
    },
}


def _intent_label(code: str) -> str:
    return INTENT_LABELS.get(code, code or "未知")


def build_feedback_analytics(db: Session, *, days: int = 30) -> dict:
    since = datetime.utcnow() - timedelta(days=max(1, days))
    rows = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.created_at >= since)
        .order_by(MessageFeedback.created_at.asc())
        .all()
    )

    intent_counts: Counter[str] = Counter()
    intent_ratings: dict[str, list[int]] = defaultdict(list)
    intent_liked: dict[str, list[int]] = defaultdict(list)
    failed_intents: Counter[str] = Counter()
    corrected_intents: Counter[str] = Counter()
    daily_positive: dict[str, int] = defaultdict(int)

    for row in rows:
        detail = build_feedback_detail(db, row)
        intent = str(detail.get("intent") or "unknown")
        intent_counts[intent] += 1
        intent_ratings[intent].append(row.rating)
        if row.intent_liked is not None:
            intent_liked[intent].append(row.intent_liked)
        if row.intent_liked == 0:
            failed_intents[intent] += 1
            corrected = (detail.get("corrected_intent_label") or detail.get("corrected_intent") or "").strip()
            if corrected:
                corrected_intents[corrected] += 1
        day = row.created_at.strftime("%Y-%m-%d")
        if row.rating >= 4:
            daily_positive[day] += 1

    intent_pie = [{"intent": k, "label": _intent_label(k), "count": v} for k, v in intent_counts.most_common()]
    intent_score = [
        {
            "intent": k,
            "label": _intent_label(k),
            "avg_rating": round(sum(v) / len(v), 2),
            "count": len(v),
            "like_rate": round(sum(1 for x in intent_liked.get(k, []) if x == 1) / len(intent_liked[k]), 2)
            if intent_liked.get(k)
            else None,
        }
        for k, v in intent_ratings.items()
    ]
    intent_score.sort(key=lambda x: x["avg_rating"], reverse=True)

    failed_rank = [
        {"intent": k, "label": _intent_label(k), "fail_count": v, "total": intent_counts[k]}
        for k, v in failed_intents.most_common()
    ]

    corrected_rank = [{"label": k, "count": v} for k, v in corrected_intents.most_common()]

    positive_line = [{"date": d, "count": daily_positive.get(d, 0)} for d in sorted(daily_positive.keys())]

    if settings.FEEDBACK_DEMO_FALLBACK and len(rows) < 15:
        demo = build_demo_feedback_analytics(days=days)
        if rows:
            demo["demo_note"] = f"真实反馈仅 {len(rows)} 条，以下为演示数据补全图表（达 15 条后自动切换全量真实统计）。"
        return demo

    return {
        "period_days": days,
        "total_feedback": len(rows),
        "intent_pie": intent_pie,
        "intent_ratings": intent_score,
        "failed_intent_rank": failed_rank,
        "corrected_intent_rank": corrected_rank,
        "positive_review_trend": positive_line,
        "summary": {
            "avg_rating": round(sum(r.rating for r in rows) / len(rows), 2) if rows else 0,
            "intent_like_rate": round(sum(1 for r in rows if r.intent_liked == 1) / len(rows), 2) if rows else None,
        },
        "demo_mode": False,
    }


def build_ai_analysis_prompt(analytics: dict) -> str:
    import json

    return (
        f"你是 {FEEDBACK_AI_PERSONA['display_name']}（{FEEDBACK_AI_PERSONA['role']}）。\n"
        f"{FEEDBACK_AI_PERSONA['layers']['L0']}\n{FEEDBACK_AI_PERSONA['layers']['L1']}\n{FEEDBACK_AI_PERSONA['layers']['L2']}\n\n"
        "请基于以下看板 JSON 数据，输出一份全面的 Markdown 分析报告，包含：\n"
        "1. 总体结论（3-5 句）\n2. 意图维度洞察（分布、评分、失败意图）\n3. 回答满意度趋势解读\n4. 风险与异常\n5. 可执行改进建议（按优先级）\n\n"
        f"看板数据：\n{json.dumps(analytics, ensure_ascii=False)}"
    )


async def run_feedback_ai_analysis(db: Session, *, days: int = 30) -> dict:
    from app.llms import get_llm

    analytics = build_feedback_analytics(db, days=days)
    prompt = build_ai_analysis_prompt(analytics)
    text = get_llm().call(prompt, temperature=0.2, max_tokens=2048)
    return {
        "persona": FEEDBACK_AI_PERSONA,
        "analytics": analytics,
        "analysis_markdown": text,
        "llm_powered": True,
    }
