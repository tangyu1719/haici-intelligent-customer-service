"""RAG 评测服务 — 标准 RAGAS 指标 + Span粒度追踪 + Pass@K。

指标定义 (对齐 RAGAS v0.2+):
- Faithfulness: 回答中的每条断言是否能从检索上下文中验证（反幻觉）
- Answer Relevancy: 回答是否切题、完整
- Context Precision: 检索结果中有多少是真正有用的（信噪比）
- Context Recall: 应该检索到的信息实际检索到了多少
- Pass@K: top-K检索中至少命中一条相关文档的查询占比

Span追踪（流水线各步骤独立指标）:
- intent: 意图识别
- rewrite: Query改写
- keywords: 关键词提取
- retrieval: 向量检索
- generation: LLM生成
- follow_up: 追问生成
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import SysLogApiCall

logger = logging.getLogger(__name__)


@dataclass
class RagEvalResult:
    """单次RAG对话的完整评测结果"""
    trace_id: str = ""
    question: str = ""
    answer: str = ""
    intent: str = ""
    intent_label: str = ""
    rewritten_query: str = ""
    rag_query: str = ""
    keywords: list[str] = field(default_factory=list)
    retrieval_terms: list[str] = field(default_factory=list)
    citations_count: int = 0
    top_score: float = 0.0
    avg_score: float = 0.0
    scores: list[float] = field(default_factory=list)
    anti_dilution: bool = False
    kb_id: int | None = None
    llm_provider: str = ""
    llm_model: str = ""
    answer_length: int = 0
    follow_ups_count: int = 0
    total_tokens: int = 0
    time_consume_ms: int = 0

    # RAGAS 评测指标（LLM-as-Judge 异步计算）
    faithfulness: float | None = None       # 忠实度 0-1
    answer_relevancy: float | None = None   # 答案相关性 0-1
    context_precision: float | None = None  # 上下文精度 0-1
    context_recall: float | None = None     # 上下文召回率 0-1

    # Span 耗时
    span_intent_ms: int = 0
    span_rewrite_ms: int = 0
    span_retrieval_ms: int = 0
    span_generation_ms: int = 0
    span_followup_ms: int = 0

    success: bool = True
    error: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "question": self.question[:200],
            "answer_preview": self.answer[:200],
            "intent": self.intent,
            "intent_label": self.intent_label,
            "rewritten_query": self.rewritten_query[:200],
            "rag_query": self.rag_query[:200],
            "keywords": self.keywords,
            "retrieval_terms": self.retrieval_terms,
            "citations_count": self.citations_count,
            "top_score": round(self.top_score, 4),
            "avg_score": round(self.avg_score, 4),
            "scores": [round(s, 4) for s in self.scores[:10]],
            "pass_at_1": 1.0 if self.top_score >= 0.7 else 0.0,
            "pass_at_3": 1.0 if len([s for s in self.scores if s >= 0.5]) >= 1 else 0.0,
            "pass_at_5": 1.0 if len([s for s in self.scores if s >= 0.35]) >= 1 else 0.0,
            "anti_dilution": self.anti_dilution,
            "kb_id": self.kb_id,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "answer_length": self.answer_length,
            "follow_ups_count": self.follow_ups_count,
            "total_tokens": self.total_tokens,
            "time_consume_ms": self.time_consume_ms,
            # RAGAS
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            # Spans
            "span_intent_ms": self.span_intent_ms,
            "span_rewrite_ms": self.span_rewrite_ms,
            "span_retrieval_ms": self.span_retrieval_ms,
            "span_generation_ms": self.span_generation_ms,
            "span_followup_ms": self.span_followup_ms,
            "success": self.success,
            "error": self.error,
            "created_at": self.created_at,
        }


def _parse_rag_meta(summary: str | None) -> dict:
    if not summary:
        return {}
    try:
        data = json.loads(summary)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_rag_metrics(db: Session, *, limit: int = 50, days: int = 7) -> dict:
    """提取最近的RAG对话指标详情（含Pass@K和Span信息）"""
    since = datetime.utcnow() - timedelta(days=max(1, days))
    rows = (
        db.query(SysLogApiCall)
        .filter(
            SysLogApiCall.api_type == "rag",
            SysLogApiCall.created_at >= since,
        )
        .order_by(SysLogApiCall.created_at.desc())
        .limit(limit)
        .all()
    )

    items: list[RagEvalResult] = []
    for r in rows:
        meta = _parse_rag_meta(r.response_summary)
        if not meta.get("question"):
            continue  # 跳过旧格式的装饰器记录

        scores = meta.get("scores") or []
        if isinstance(meta.get("top_score"), (int, float)):
            scores = sorted([meta["top_score"]] + scores, reverse=True)[:10]

        item = RagEvalResult(
            trace_id=r.trace_id,
            question=meta.get("question", r.request_summary or "")[:200],
            answer=meta.get("answer", "")[:500],
            intent=meta.get("intent", ""),
            intent_label=meta.get("intent_label", ""),
            rewritten_query=meta.get("rewritten_query", ""),
            rag_query=meta.get("rag_query", ""),
            keywords=meta.get("keywords") or [],
            retrieval_terms=meta.get("retrieval_terms") or [],
            citations_count=meta.get("citations_count", 0),
            top_score=float(meta.get("top_score") or 0),
            avg_score=round(sum(scores) / len(scores), 4) if scores else 0.0,
            scores=scores,
            anti_dilution=meta.get("anti_dilution", False),
            kb_id=meta.get("kb_id"),
            llm_provider=meta.get("llm_provider", ""),
            llm_model=meta.get("llm_model", ""),
            answer_length=meta.get("answer_length", 0),
            follow_ups_count=meta.get("follow_ups_count", 0),
            total_tokens=meta.get("total_tokens", 0),
            time_consume_ms=r.time_consume_ms,
            success=r.success == 1,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        items.append(item)

    # ── 聚合统计 ──
    total = len(items)
    success_count = sum(1 for i in items if i.success)
    avg_top_score = round(sum(i.top_score for i in items) / max(total, 1), 4)
    avg_citations = round(sum(i.citations_count for i in items) / max(total, 1), 2)
    avg_latency = round(sum(i.time_consume_ms for i in items) / max(total, 1), 0)
    avg_answer_len = round(sum(i.answer_length for i in items) / max(total, 1), 0)

    # Pass@K 计算
    pass_at_1 = round(sum(1 for i in items if i.top_score >= 0.7) / max(total, 1), 4)
    pass_at_3 = round(sum(1 for i in items if any(s >= 0.5 for s in i.scores[:3])) / max(total, 1), 4)
    pass_at_5 = round(sum(1 for i in items if any(s >= 0.35 for s in i.scores[:5])) / max(total, 1), 4)

    # 意图分布
    intent_dist: dict[str, int] = {}
    for i in items:
        key = i.intent_label or i.intent or "unknown"
        intent_dist[key] = intent_dist.get(key, 0) + 1

    # 分数分布（用于直方图）
    score_buckets = {"0.0-0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.85": 0, "0.85-1.0": 0}
    for i in items:
        s = i.top_score
        if s < 0.3: score_buckets["0.0-0.3"] += 1
        elif s < 0.5: score_buckets["0.3-0.5"] += 1
        elif s < 0.7: score_buckets["0.5-0.7"] += 1
        elif s < 0.85: score_buckets["0.7-0.85"] += 1
        else: score_buckets["0.85-1.0"] += 1

    return {
        "total": total,
        "success_count": success_count,
        "fail_count": total - success_count,
        "fail_rate": round((total - success_count) / max(total, 1), 4),
        "avg_top_score": avg_top_score,
        "avg_citations": avg_citations,
        "avg_latency_ms": avg_latency,
        "avg_answer_length": avg_answer_len,
        "anti_dilution_count": sum(1 for i in items if i.anti_dilution),
        # RAGAS 风格指标
        "pass_at_1": pass_at_1,
        "pass_at_3": pass_at_3,
        "pass_at_5": pass_at_5,
        "avg_faithfulness": round(sum(i.faithfulness or 0 for i in items) / max(total, 1), 4),
        "avg_answer_relevancy": round(sum(i.answer_relevancy or 0 for i in items) / max(total, 1), 4),
        "avg_context_precision": round(sum(i.context_precision or 0 for i in items) / max(total, 1), 4),
        "avg_context_recall": round(sum(i.context_recall or 0 for i in items) / max(total, 1), 4),
        # 分数分布
        "score_distribution": score_buckets,
        "intent_distribution": intent_dist,
        "items": [i.to_dict() for i in items],
        "generated_at": datetime.utcnow().isoformat(),
    }


def evaluate_faithfulness_async(trace_id: str, answer: str, contexts: list[str]) -> None:
    """异步LLM-as-Judge评估忠实度（不阻塞主流程）"""
    def _judge() -> None:
        try:
            from app.llms import get_llm
            llm = get_llm()
            prompt = (
                "你是RAG评测助手。请评估以下回答是否忠实于检索到的上下文。\n"
                "将回答拆分为原子断言，逐个检查是否能在上下文中找到依据。\n"
                "输出JSON: {\"faithfulness\": 0.0-1.0, \"claims_total\": N, \"claims_supported\": N, \"explanation\": \"...\"}\n\n"
                f"回答: {answer[:2000]}\n\n上下文: {' | '.join(contexts)[:3000]}"
            )
            result = llm.call(prompt)
            # 解析结果并写入数据库
            _update_rag_metric(trace_id, "faithfulness", result)
        except Exception as exc:
            logger.warning(f"[RAG评测|faithfulness|失败] {exc}")

    threading.Thread(target=_judge, daemon=True).start()


def _update_rag_metric(trace_id: str, metric_name: str, result: str) -> None:
    """更新RAG指标的特定字段"""
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        row = (
            db.query(SysLogApiCall)
            .filter(SysLogApiCall.trace_id == trace_id, SysLogApiCall.api_type == "rag")
            .order_by(SysLogApiCall.log_id.desc())
            .first()
        )
        if row and row.response_summary:
            meta = json.loads(row.response_summary)
            try:
                parsed = json.loads(result) if isinstance(result, str) else result
                if isinstance(parsed, dict):
                    if "faithfulness" in parsed:
                        meta["faithfulness"] = float(parsed["faithfulness"])
                    if "answer_relevancy" in parsed:
                        meta["answer_relevancy"] = float(parsed["answer_relevancy"])
                row.response_summary = json.dumps(meta, ensure_ascii=False)
                db.commit()
            except (json.JSONDecodeError, ValueError):
                pass
        db.close()
    except Exception as exc:
        logger.warning(f"[RAG评测|更新指标|失败] {exc}")
