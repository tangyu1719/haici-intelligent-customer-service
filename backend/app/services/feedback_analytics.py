"""用户反馈数据分析 + AI 评测 Agent。"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ChatMessage, ChatSession, MessageFeedback
from app.services.feedback_demo_data import build_demo_feedback_analytics
from app.services.feedback_detail import build_feedback_detail
from app.services.term_dictionary import INTENT_LABELS

logger = logging.getLogger(__name__)

FEEDBACK_AI_PERSONA = {
    "agent_id": "feedback_analytics_agent",
    "display_name": "评测分析师 · 小析",
    "role": "HaiChi 智能客服运维评测分析师",
    "reply_style": "数据驱动、结构清晰、结论可执行",
    "layers": {
        "L0": "你是「小析」，专注用户反馈与意图数据的深度解读，语气专业但不生硬。",
        "L1": "从意图分布、满意度、失败意图、回答质量四维度输出洞察与改进建议。",
        "L2": "禁止编造数据；引用看板数字；输出 Markdown 结构化报告。",
    },
}


def _intent_label(code: str) -> str:
    return INTENT_LABELS.get(code, code or "未知")


def _period_since(days: int) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max(1, days))


def _date_range(days: int) -> list[str]:
    """统计周期内连续日期（含今天），用于折线图补零。"""
    today = datetime.now(UTC).replace(tzinfo=None).date()
    span = min(max(1, days), 90)
    start = today - timedelta(days=span - 1)
    out: list[str] = []
    cur = start
    while cur <= today:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _query_pipeline_counts(db: Session, since: datetime) -> dict[str, int]:
    """从会话/消息/反馈表抽取漏斗各阶段计数。"""
    session_count = (
        db.query(ChatSession)
        .filter(ChatSession.created_at >= since, ChatSession.user_deleted == 0)
        .count()
    )
    assistant_count = (
        db.query(ChatMessage)
        .filter(ChatMessage.created_at >= since, ChatMessage.role == "assistant")
        .count()
    )
    intent_labeled = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.created_at >= since,
            ChatMessage.role == "assistant",
            ChatMessage.intent_label.isnot(None),
            ChatMessage.intent_label != "",
        )
        .count()
    )
    rag_answer_count = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.created_at >= since,
            ChatMessage.role == "assistant",
            ChatMessage.citations_json.isnot(None),
        )
        .count()
    )
    feedback_count = db.query(MessageFeedback).filter(MessageFeedback.created_at >= since).count()
    return {
        "active_sessions": session_count,
        "assistant_replies": assistant_count,
        "intent_labeled_replies": intent_labeled,
        "rag_cited_replies": rag_answer_count,
        "user_feedback": feedback_count,
    }


def _build_flow_pipeline(counts: dict[str, int], *, period_days: int, demo: bool = False) -> dict:
    title = "用户反馈处理流程（演示）" if demo else f"用户反馈处理流程（近 {period_days} 天）"
    assist = counts["assistant_replies"]
    intent = counts["intent_labeled_replies"]
    rag = counts["rag_cited_replies"]
    fb = counts["user_feedback"]
    return {
        "title": title,
        "stages": [
            {
                "id": "session",
                "label": "活跃会话",
                "count": counts["active_sessions"],
                "desc": "chat_sessions.created_at 周期内且未删除",
            },
            {
                "id": "intent",
                "label": "意图识别",
                "count": intent,
                "desc": f"助手消息 intent_label 非空（占回复 {round(intent / assist * 100) if assist else 0}%）",
            },
            {
                "id": "answer",
                "label": "RAG 回答",
                "count": rag,
                "desc": f"citations_json 非空（占回复 {round(rag / assist * 100) if assist else 0}%）",
            },
            {
                "id": "feedback",
                "label": "用户反馈",
                "count": fb,
                "desc": f"message_feedback 周期内（反馈率 {round(fb / assist * 100, 1) if assist else 0}%）",
            },
            {
                "id": "dashboard",
                "label": "看板聚合",
                "count": fb,
                "desc": "本页 intent/rating 维度统计",
            },
        ],
    }


def _build_extraction_meta(
    *,
    period_days: int,
    since: datetime,
    counts: dict[str, int],
    feedback_rows: list[MessageFeedback],
) -> dict:
    """各指标抽取规则说明，供前端展示与 AI 分析引用。"""
    assist = counts["assistant_replies"]
    fb = counts["user_feedback"]
    intent_eval_rows = [r for r in feedback_rows if r.intent_liked is not None]
    return {
        "period_days": period_days,
        "since_utc": since.isoformat(timespec="seconds"),
        "sources": {
            "sessions": "chat_sessions（user_deleted=0）",
            "messages": "chat_messages（role=assistant）",
            "feedback": "message_feedback + context_snapshot_json / 消息回填",
        },
        "rules": [
            {
                "metric": "intent_pie",
                "rule": "按 message_feedback 关联助手消息的 intent（快照优先，缺失则从 chat_messages.intent_label 回填）计数",
            },
            {
                "metric": "intent_ratings",
                "rule": "同一 intent 下对 rating 求均值；intent_liked=1 计为意图点赞",
            },
            {
                "metric": "failed_intent_rank",
                "rule": "intent_liked=0 的反馈按原识别 intent 聚合计数，排序取 fail_count",
            },
            {
                "metric": "corrected_intent_rank",
                "rule": "intent_liked=0 且用户填写 corrected_intent_label 的纠偏意图计数",
            },
            {
                "metric": "positive_review_trend",
                "rule": "rating>=4 的反馈按 created_at 日期（UTC）分组，周期内无数据日期补 0",
            },
            {
                "metric": "flow_pipeline",
                "rule": "漏斗五段分别来自 sessions / intent_label 助手消息 / citations_json 助手消息 / feedback 表",
            },
        ],
        "coverage": {
            "feedback_rate": round(fb / assist, 4) if assist else None,
            "intent_eval_rate": round(len(intent_eval_rows) / fb, 4) if fb else None,
            "intent_label_coverage": round(counts["intent_labeled_replies"] / assist, 4) if assist else None,
        },
    }


def _aggregate_feedback_rows(db: Session, rows: list[MessageFeedback]) -> dict:
    intent_counts: Counter[str] = Counter()
    intent_ratings: dict[str, list[int]] = defaultdict(list)
    intent_liked: dict[str, list[int]] = defaultdict(list)
    failed_intents: Counter[str] = Counter()
    corrected_intents: Counter[str] = Counter()
    daily_positive: dict[str, int] = defaultdict(int)
    rating_dist: Counter[int] = Counter()
    low_rating_samples: list[dict] = []
    comment_samples: list[dict] = []

    for row in rows:
        detail = build_feedback_detail(db, row)
        intent = str(detail.get("intent") or "unknown")
        intent_counts[intent] += 1
        intent_ratings[intent].append(row.rating)
        rating_dist[row.rating] += 1
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
        if row.rating <= 2 and len(low_rating_samples) < 5:
            low_rating_samples.append(
                {
                    "feedback_id": row.id,
                    "rating": row.rating,
                    "intent": _intent_label(intent),
                    "comment": (row.comment or "")[:120],
                    "user_question": (detail.get("user_question") or "")[:80],
                }
            )
        if row.comment and len(comment_samples) < 5:
            comment_samples.append(
                {
                    "feedback_id": row.id,
                    "rating": row.rating,
                    "comment": row.comment[:200],
                }
            )

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

    intent_eval_rows = [r for r in rows if r.intent_liked is not None]
    return {
        "intent_pie": intent_pie,
        "intent_ratings": intent_score,
        "failed_intent_rank": failed_rank,
        "corrected_intent_rank": corrected_rank,
        "daily_positive": daily_positive,
        "rating_distribution": [{"rating": k, "count": rating_dist[k]} for k in sorted(rating_dist.keys())],
        "low_rating_samples": low_rating_samples,
        "comment_samples": comment_samples,
        "summary": {
            "avg_rating": round(sum(r.rating for r in rows) / len(rows), 2) if rows else 0,
            "intent_like_rate": round(sum(1 for r in intent_eval_rows if r.intent_liked == 1) / len(intent_eval_rows), 2)
            if intent_eval_rows
            else None,
            "low_rating_count": sum(1 for r in rows if r.rating <= 2),
            "high_rating_count": sum(1 for r in rows if r.rating >= 4),
        },
    }


def build_feedback_analytics(db: Session, *, days: int = 30) -> dict:
    since = _period_since(days)
    rows = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.created_at >= since)
        .order_by(MessageFeedback.created_at.asc())
        .all()
    )
    counts = _query_pipeline_counts(db, since)

    if settings.FEEDBACK_DEMO_FALLBACK and not rows:
        logger.info(
            "[运维评测-反馈看板|build_feedback_analytics|message_feedback|硬编执行|首次统计] "
            "无周期内反馈，返回演示数据; period_days=%s",
            days,
        )
        return build_demo_feedback_analytics(days=days, pipeline_counts=counts)

    agg = _aggregate_feedback_rows(db, rows)
    dates = _date_range(days)
    positive_line = [{"date": d, "count": agg["daily_positive"].get(d, 0)} for d in dates]
    extraction = _build_extraction_meta(
        period_days=days,
        since=since,
        counts=counts,
        feedback_rows=rows,
    )

    logger.info(
        "[运维评测-反馈看板|build_feedback_analytics|message_feedback|硬编执行|聚合完成] "
        "ok=true; total_feedback=%s; sessions=%s; assistant=%s",
        len(rows),
        counts["active_sessions"],
        counts["assistant_replies"],
    )

    return {
        "period_days": days,
        "total_feedback": len(rows),
        "intent_pie": agg["intent_pie"],
        "intent_ratings": agg["intent_ratings"],
        "failed_intent_rank": agg["failed_intent_rank"],
        "corrected_intent_rank": agg["corrected_intent_rank"],
        "positive_review_trend": positive_line,
        "rating_distribution": agg["rating_distribution"],
        "low_rating_samples": agg["low_rating_samples"],
        "comment_samples": agg["comment_samples"],
        "flow_pipeline": _build_flow_pipeline(counts, period_days=days),
        "data_extraction": extraction,
        "summary": agg["summary"],
        "demo_mode": False,
    }


def build_ai_analysis_prompt(analytics: dict) -> str:
    extraction = analytics.get("data_extraction") or {}
    samples = {
        "low_rating_samples": analytics.get("low_rating_samples") or [],
        "comment_samples": analytics.get("comment_samples") or [],
        "rating_distribution": analytics.get("rating_distribution") or [],
    }
    return (
        f"你是 {FEEDBACK_AI_PERSONA['display_name']}（{FEEDBACK_AI_PERSONA['role']}）。\n"
        f"{FEEDBACK_AI_PERSONA['layers']['L0']}\n{FEEDBACK_AI_PERSONA['layers']['L1']}\n{FEEDBACK_AI_PERSONA['layers']['L2']}\n\n"
        "请基于以下看板 JSON 数据，输出一份全面的 Markdown 分析报告，包含：\n"
        "1. 总体结论（3-5 句，必须引用 total_feedback、avg_rating、feedback_rate 等数字）\n"
        "2. 漏斗转化解读（flow_pipeline 各阶段数量与流失）\n"
        "3. 意图维度洞察（分布、评分、失败意图、纠偏意图）\n"
        "4. 回答满意度与趋势（rating_distribution、positive_review_trend）\n"
        "5. 低分/评论样本要点（low_rating_samples、comment_samples，勿编造未给出的内容）\n"
        "6. 风险与异常\n"
        "7. 可执行改进建议（按 P0/P1/P2 优先级）\n\n"
        f"数据抽取说明（请理解口径后再分析）：\n{json.dumps(extraction, ensure_ascii=False, indent=2)}\n\n"
        f"样本摘录：\n{json.dumps(samples, ensure_ascii=False, indent=2)}\n\n"
        f"看板汇总：\n{json.dumps({k: v for k, v in analytics.items() if k not in ('low_rating_samples', 'comment_samples')}, ensure_ascii=False)}"
    )


async def run_feedback_ai_analysis(db: Session, *, days: int = 30) -> dict:
    from app.llms import get_llm

    analytics = build_feedback_analytics(db, days=days)
    prompt = build_ai_analysis_prompt(analytics)
    text = get_llm().call(prompt, temperature=0.2, max_tokens=2048)
    logger.info(
        "[运维评测-反馈看板|run_feedback_ai_analysis|feedback_analytics|Agent执行|LLM完成] "
        "ok=true; llm_powered=true; analysis_len=%s; demo_mode=%s",
        len(text or ""),
        analytics.get("demo_mode"),
    )
    return {
        "persona": FEEDBACK_AI_PERSONA,
        "analytics": analytics,
        "analysis_markdown": text,
        "llm_powered": True,
    }
