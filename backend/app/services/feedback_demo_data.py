"""反馈看板演示数据（无真实反馈时可选启用，须标注 demo_mode）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.term_dictionary import INTENT_LABELS


def _intent_label(code: str) -> str:
    return INTENT_LABELS.get(code, code or "未知")


def build_demo_feedback_analytics(*, days: int = 30) -> dict:
    """生成可驱动饼图/折线/流程图的演示统计。"""
    today = datetime.utcnow().date()
    positive_line = []
    for i in range(min(days, 14)):
        d = today - timedelta(days=13 - i)
        positive_line.append({"date": d.isoformat(), "count": [3, 5, 2, 8, 6, 4, 7, 9, 5, 6, 8, 4, 7, 5][i]})

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

    flow_pipeline = {
        "title": "用户反馈处理流程（演示）",
        "stages": [
            {"id": "session", "label": "用户会话", "count": 156, "desc": "近30天活跃对话"},
            {"id": "intent", "label": "意图识别", "count": 148, "desc": "Pipeline 标注"},
            {"id": "answer", "label": "AI 回答", "count": 142, "desc": "含 RAG 引用"},
            {"id": "feedback", "label": "用户反馈", "count": 93, "desc": "点赞/点踩"},
            {"id": "dashboard", "label": "看板聚合", "count": 93, "desc": "本页统计"},
        ],
    }

    return {
        "period_days": days,
        "total_feedback": 93,
        "intent_pie": intent_pie,
        "intent_ratings": intent_ratings,
        "failed_intent_rank": failed_rank,
        "positive_review_trend": positive_line,
        "flow_pipeline": flow_pipeline,
        "summary": {
            "avg_rating": 4.35,
            "intent_like_rate": 0.78,
        },
        "demo_mode": True,
        "demo_note": "当前为演示数据；产生真实用户点赞/点踩后将自动切换为库内统计。",
    }
