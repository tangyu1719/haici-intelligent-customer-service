"""反馈看板数据抽取单元测试。"""
from __future__ import annotations

from app.database import SessionLocal
from app.services.feedback_analytics import build_feedback_analytics, build_ai_analysis_prompt


def test_build_feedback_analytics_uses_real_data():
    db = SessionLocal()
    try:
        data = build_feedback_analytics(db, days=30)
    finally:
        db.close()

    assert data["demo_mode"] is False
    assert data["total_feedback"] > 0
    assert data["flow_pipeline"]["stages"]
    assert len(data["flow_pipeline"]["stages"]) == 5
    assert data["data_extraction"]["rules"]
    assert "intent_pie" in data
    assert sum(item["count"] for item in data["intent_pie"]) == data["total_feedback"]
    assert data["positive_review_trend"]
    assert len(data["positive_review_trend"]) >= 7


def test_ai_analysis_prompt_contains_extraction_and_numbers():
    db = SessionLocal()
    try:
        analytics = build_feedback_analytics(db, days=30)
        prompt = build_ai_analysis_prompt(analytics)
    finally:
        db.close()

    assert "data_extraction" in prompt or "数据抽取说明" in prompt
    assert str(analytics["total_feedback"]) in prompt
    assert "flow_pipeline" in prompt
