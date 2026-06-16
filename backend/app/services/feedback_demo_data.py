"""反馈看板演示数据（无真实反馈时可选启用，须标注 demo_mode）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.term_dictionary import INTENT_LABELS


def _intent_label(code: str) -> str:
    return INTENT_LABELS.get(code, code or "未知")


def _date_range(days: int) -> list[str]:
    today = datetime.now(UTC).replace(tzinfo=None).date()
    span = min(max(1, days), 14)
    start = today - timedelta(days=span - 1)
    out: list[str] = []
    cur = start
    while cur <= today:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def build_demo_feedback_analytics(*, days: int = 30, pipeline_counts: dict | None = None) -> dict:
    """生成可驱动饼图/折线/流程图的演示统计；漏斗优先使用库内真实会话/消息计数。"""
    counts = pipeline_counts or {
        "active_sessions": 0,
        "assistant_replies": 0,
        "intent_labeled_replies": 0,
        "rag_cited_replies": 0,
        "user_feedback": 0,
    }
    has_real_pipeline = counts["active_sessions"] > 0 or counts["assistant_replies"] > 0

    dates = _date_range(days)
    seed = [3, 5, 2, 8, 6, 4, 7, 9, 5, 6, 8, 4, 7, 5]
    positive_line = [{"date": d, "count": seed[i % len(seed)]} for i, d in enumerate(dates)]

    intent_pie = [
        {"intent": "product_consult", "label": _intent_label("product_consult"), "count": 42},
        {"intent": "after_sale", "label": _intent_label("after_sale"), "count": 28},
        {"intent": "chitchat", "label": _intent_label("chitchat"), "count": 15},
        {"intent": "complaint", "label": _intent_label("complaint"), "count": 8},
    ]

    intent_ratings = [
        {"intent": "product_consult", "label": _intent_label("product_consult"), "avg_rating": 4.6, "count": 42, "like_rate": 0.86},
        {"intent": "after_sale", "label": _intent_label("after_sale"), "avg_rating": 4.1, "count": 28, "like_rate": 0.71},
        {"intent": "chitchat", "label": _intent_label("chitchat"), "avg_rating": 4.8, "count": 15, "like_rate": 0.93},
        {"intent": "complaint", "label": _intent_label("complaint"), "avg_rating": 3.2, "count": 8, "like_rate": 0.38},
    ]

    failed_rank = [
        {"intent": "complaint", "label": _intent_label("complaint"), "fail_count": 5, "total": 8},
        {"intent": "after_sale", "label": _intent_label("after_sale"), "fail_count": 8, "total": 28},
        {"intent": "product_consult", "label": _intent_label("product_consult"), "fail_count": 6, "total": 42},
    ]

    demo_feedback_total = 93
    assist = counts["assistant_replies"] or 142
    intent = counts["intent_labeled_replies"] or int(assist * 0.96)
    rag = counts["rag_cited_replies"] or int(assist * 0.88)
    sessions = counts["active_sessions"] or 156

    flow_pipeline = {
        "title": "用户反馈处理流程（演示 · 漏斗来自库内会话/消息）" if has_real_pipeline else "用户反馈处理流程（演示）",
        "stages": [
            {"id": "session", "label": "活跃会话", "count": sessions, "desc": "chat_sessions 周期内计数" if has_real_pipeline else "近30天活跃对话"},
            {"id": "intent", "label": "意图识别", "count": intent, "desc": "助手消息 intent_label 非空"},
            {"id": "answer", "label": "RAG 回答", "count": rag, "desc": "citations_json 非空"},
            {"id": "feedback", "label": "用户反馈", "count": demo_feedback_total, "desc": "演示：合成反馈样本"},
            {"id": "dashboard", "label": "看板聚合", "count": demo_feedback_total, "desc": "演示：合成统计"},
        ],
    }

    return {
        "period_days": days,
        "total_feedback": demo_feedback_total,
        "intent_pie": intent_pie,
        "intent_ratings": intent_ratings,
        "failed_intent_rank": failed_rank,
        "corrected_intent_rank": [{"label": "投诉", "count": 4}, {"label": "售后问题", "count": 2}],
        "positive_review_trend": positive_line,
        "rating_distribution": [
            {"rating": 1, "count": 3},
            {"rating": 2, "count": 2},
            {"rating": 3, "count": 8},
            {"rating": 4, "count": 35},
            {"rating": 5, "count": 45},
        ],
        "flow_pipeline": flow_pipeline,
        "data_extraction": {
            "period_days": days,
            "demo": True,
            "note": "周期内无 message_feedback 记录；意图/评分/失败排行为合成演示，漏斗前两段可来自真实会话与消息表",
            "coverage": {
                "feedback_rate": round(demo_feedback_total / assist, 4) if assist else None,
            },
        },
        "summary": {
            "avg_rating": 4.35,
            "intent_like_rate": 0.78,
            "low_rating_count": 5,
            "high_rating_count": 80,
        },
        "demo_mode": True,
        "demo_note": "当前为演示数据；产生真实用户点赞/点踩后将自动切换为库内统计。",
    }
