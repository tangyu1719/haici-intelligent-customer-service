"""RAG 评测服务 — 三层指标体系 + 管道可视化。

三层指标:
  第一层·检索质量: Recall@K, Precision@K, MRR, nDCG, Pass@K
  第二层·生成一致性: Faithfulness, Groundedness, Factual Consistency
  第三层·系统工程: Latency, Throughput, Cache Hit Rate, Error Rate, Rejection Rate

管道可视化:
  Question → Intent → Rewrite → Keywords → Retrieval → AntiDilution → LLM → FollowUps

每个指标含: 定义、计算公式、当前值、阈值建议
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import SysLogApiCall

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 指标定义（定义 + 公式 + 阈值）
# ═══════════════════════════════════════════════════════════════

METRIC_DEFINITIONS: dict[str, dict] = {
    # ── 第一层：检索质量 ──
    "recall_at_k": {
        "name": "Recall@K",
        "layer": "retrieval",
        "description": "检索结果中包含相关文档的比例，衡量系统覆盖面",
        "formula": "Recall@K = |相关文档 ∩ Top-K检索结果| / |相关文档总数|",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.70,
        "threshold_good": 0.85,
        "direction": "higher_better",
        "unit": "ratio",
    },
    "precision_at_k": {
        "name": "Precision@K",
        "layer": "retrieval",
        "description": "检索结果中真正相关的比例，信噪比指标",
        "formula": "Precision@K = |相关文档(score≥0.5) ∩ Top-K| / K",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.60,
        "threshold_good": 0.80,
        "direction": "higher_better",
        "unit": "ratio",
    },
    "mrr": {
        "name": "MRR (Mean Reciprocal Rank)",
        "layer": "retrieval",
        "description": "第一个正确答案出现排名的倒数均值，衡量排序能力",
        "formula": "MRR = (1/N) * Σ(1/rank_i), rank_i = 第一个score≥0.7的排名",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.50,
        "threshold_good": 0.75,
        "direction": "higher_better",
        "unit": "ratio",
    },
    "ndcg": {
        "name": "nDCG (Normalized Discounted Cumulative Gain)",
        "layer": "retrieval",
        "description": "加权排序指标，越靠前的相关文档权重越高，衡量排序质量",
        "formula": "DCG@K = Σ(rel_i / log2(i+1)); IDCG = 理想排序DCG; nDCG = DCG/IDCG",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.60,
        "threshold_good": 0.80,
        "direction": "higher_better",
        "unit": "ratio",
    },
    "pass_at_k": {
        "name": "Pass@K",
        "layer": "retrieval",
        "description": "Top-K中至少有一条相关文档(score≥阈值)的查询占比",
        "formula": "Pass@K = count(查询在Top-K中有score≥阈值的文档) / 总查询数",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.80,
        "threshold_good": 0.95,
        "direction": "higher_better",
        "unit": "ratio",
    },
    # ── 第二层：生成一致性 ──
    "faithfulness": {
        "name": "Faithfulness Score (忠实度)",
        "layer": "generation",
        "description": "计算生成答案与检索材料在语义空间的相似度，判断是否引用了相关内容",
        "formula": "Faithfulness = mean(cos_sim(answer_emb, chunk_emb) for chunk in top_chunks)",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.65,
        "threshold_good": 0.85,
        "direction": "higher_better",
        "unit": "cosine_similarity",
    },
    "groundedness": {
        "name": "Groundedness Score (扎根度)",
        "layer": "generation",
        "description": "判断模型输出每一条结论是否都能在检索片段中找到依据，逐句验证",
        "formula": "将回答拆为原子断言 → 每断言与检索片段计算最高cos_sim → 低于0.65标记为潜在幻觉",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.70,
        "threshold_good": 0.90,
        "direction": "higher_better",
        "unit": "ratio",
    },
    "factual_consistency": {
        "name": "Factual Consistency (事实一致性)",
        "layer": "generation",
        "description": "基于LLM自检，让另一个模型判断答案是否自洽、是否编造",
        "formula": "LLM-as-Judge: 逐句比对回答与检索片段，标记矛盾/编造/一致",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.75,
        "threshold_good": 0.90,
        "direction": "higher_better",
        "unit": "ratio",
    },
    # ── 第三层：系统工程 ──
    "latency_ms": {
        "name": "端到端延迟",
        "layer": "system",
        "description": "检索+生成全流程响应时间(ms)",
        "formula": "Latency = 意图识别耗时 + 检索耗时 + LLM生成耗时 + 追问生成耗时",
        "range": "0 - ∞",
        "threshold_ok": 60000,
        "threshold_good": 30000,
        "direction": "lower_better",
        "unit": "ms",
    },
    "throughput": {
        "name": "吞吐量 (QPS)",
        "layer": "system",
        "description": "高并发下每秒处理请求数",
        "formula": "QPS = 总请求数 / 时间窗口(秒)",
        "range": "0 - ∞",
        "threshold_ok": 0.1,
        "threshold_good": 0.5,
        "direction": "higher_better",
        "unit": "req/s",
    },
    "cache_hit_rate": {
        "name": "缓存命中率",
        "layer": "system",
        "description": "是否重复计算，命中缓存的比例",
        "formula": "Cache Hit Rate = 缓存命中次数 / 总请求数",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.20,
        "threshold_good": 0.50,
        "direction": "higher_better",
        "unit": "ratio",
    },
    "error_rate": {
        "name": "错误率",
        "layer": "system",
        "description": "生成失败或超时的比例",
        "formula": "Error Rate = 失败请求数 / 总请求数",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.10,
        "threshold_good": 0.02,
        "direction": "lower_better",
        "unit": "ratio",
    },
    "rejection_rate": {
        "name": "拒答率",
        "layer": "system",
        "description": "模型返回兜底话术的比例，反映知识覆盖不足",
        "formula": "Rejection Rate = 返回FALLBACK的请求数 / 总请求数",
        "range": "0.0 - 1.0",
        "threshold_ok": 0.30,
        "threshold_good": 0.10,
        "direction": "lower_better",
        "unit": "ratio",
    },
}

# 管道阶段定义（用于可视化）
PIPELINE_STAGES = [
    {"id": "question", "label": "用户问题", "icon": "❓"},
    {"id": "intent", "label": "意图识别", "icon": "🏷"},
    {"id": "rewrite", "label": "Query改写", "icon": "✏️"},
    {"id": "keywords", "label": "关键词提取", "icon": "🔑"},
    {"id": "retrieval", "label": "向量检索", "icon": "🔍"},
    {"id": "anti_dilution", "label": "防稀释", "icon": "🛡"},
    {"id": "generation", "label": "LLM生成", "icon": "🤖"},
    {"id": "follow_ups", "label": "追问生成", "icon": "💬"},
    {"id": "answer", "label": "最终回答", "icon": "✅"},
]


# ═══════════════════════════════════════════════════════════════
# 指标计算函数
# ═══════════════════════════════════════════════════════════════

def _calc_recall_at_k(scores: list[float], k: int = 4, threshold: float = 0.5) -> float:
    """Recall@K: Top-K中score≥threshold的比例"""
    if not scores:
        return 0.0
    relevant = sum(1 for s in scores[:k] if s >= threshold)
    total_relevant = sum(1 for s in scores if s >= threshold)
    if total_relevant == 0:
        return 0.0
    return relevant / total_relevant


def _calc_precision_at_k(scores: list[float], k: int = 4, threshold: float = 0.5) -> float:
    """Precision@K: Top-K中真正相关的比例"""
    if k == 0 or not scores:
        return 0.0
    relevant = sum(1 for s in scores[:k] if s >= threshold)
    return relevant / min(k, len(scores))


def _calc_mrr(all_scores: list[list[float]], threshold: float = 0.7) -> float:
    """MRR: 第一个正确答案排名的倒数均值"""
    if not all_scores:
        return 0.0
    rr_sum = 0.0
    for scores in all_scores:
        for rank, s in enumerate(scores, 1):
            if s >= threshold:
                rr_sum += 1.0 / rank
                break
    return rr_sum / len(all_scores)


def _calc_ndcg(scores: list[float], k: int = 4) -> float:
    """nDCG@K: 归一化折损累计增益"""
    if not scores:
        return 0.0
    # DCG
    dcg = sum(s / math.log2(i + 2) for i, s in enumerate(scores[:k]))
    # IDCG (理想排序)
    ideal = sorted(scores, reverse=True)[:k]
    idcg = sum(s / math.log2(i + 2) for i, s in enumerate(ideal))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def _parse_rag_meta(summary: str | None) -> dict:
    if not summary:
        return {}
    try:
        data = json.loads(summary)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════
# 主评测函数
# ═══════════════════════════════════════════════════════════════

def build_full_eval_report(db: Session, *, limit: int = 100, days: int = 7) -> dict:
    """构建完整RAG评测报告（三层指标+管道可视化+每条详情）"""
    since = datetime.utcnow() - timedelta(days=max(1, days))
    rows = (
        db.query(SysLogApiCall)
        .filter(SysLogApiCall.api_type == "rag", SysLogApiCall.created_at >= since)
        .order_by(SysLogApiCall.created_at.desc())
        .limit(limit)
        .all()
    )

    # 收集数据
    all_scores: list[list[float]] = []
    items: list[dict] = []
    total_latency = 0
    success_count = 0
    fail_count = 0

    for r in rows:
        meta = _parse_rag_meta(r.response_summary)
        if not meta.get("question"):
            continue

        scores = meta.get("scores") or []
        if isinstance(meta.get("top_score"), (int, float)):
            scores = sorted([meta["top_score"]] + list(scores), reverse=True)[:10]

        if scores:
            all_scores.append(scores)

        total_latency += r.time_consume_ms
        if r.success == 1:
            success_count += 1
        else:
            fail_count += 1

        items.append({
            "trace_id": r.trace_id,
            "question": meta.get("question", "")[:150],
            "intent_label": meta.get("intent_label", ""),
            "rewritten_query": meta.get("rewritten_query", "")[:100],
            "top_score": round(float(meta.get("top_score") or 0), 4),
            "scores": [round(s, 4) for s in scores[:10]],
            "citations_count": meta.get("citations_count", 0),
            "answer_length": meta.get("answer_length", 0),
            "latency_ms": r.time_consume_ms,
            "follow_ups": meta.get("follow_ups") or [],
            "success": r.success == 1,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        })

    total = len(items)
    if total == 0:
        return {"total": 0, "message": "暂无评测数据"}

    # ── 第一层：检索质量 ──
    K = 4
    recall_k = round(sum(_calc_recall_at_k(s, K) for s in all_scores) / max(len(all_scores), 1), 4)
    precision_k = round(sum(_calc_precision_at_k(s, K) for s in all_scores) / max(len(all_scores), 1), 4)
    mrr = round(_calc_mrr(all_scores), 4)
    ndcg = round(sum(_calc_ndcg(s, K) for s in all_scores) / max(len(all_scores), 1), 4)
    pass_1 = round(sum(1 for s in all_scores if s[0] >= 0.7) / max(len(all_scores), 1), 4) if all_scores else 0
    pass_3 = round(sum(1 for s in all_scores if any(x >= 0.5 for x in s[:3])) / max(len(all_scores), 1), 4) if all_scores else 0
    pass_5 = round(sum(1 for s in all_scores if any(x >= 0.35 for x in s[:5])) / max(len(all_scores), 1), 4) if all_scores else 0

    # ── 第二层：生成一致性 ──
    avg_faithfulness = round(sum(
        float(meta.get("faithfulness") or 0)
        for r in rows if _parse_rag_meta(r.response_summary).get("question")
    ) / max(total, 1), 4)
    avg_groundedness = round(sum(
        float(meta.get("groundedness") or 0)
        for r in rows if _parse_rag_meta(r.response_summary).get("question")
    ) / max(total, 1), 4)

    # ── 第三层：系统工程 ──
    avg_latency = round(total_latency / max(total, 1), 0)
    throughput = round(total / max(days * 86400, 1), 4)
    from app.services.gateway_cache import cache as gw_cache
    cache_stats = gw_cache.stats()
    cache_hit_rate = cache_stats.get("hit_rate", 0.0)
    error_rate = round(fail_count / max(total, 1), 4)
    rejection_count = sum(1 for i in items if i["citations_count"] == 0)
    rejection_rate = round(rejection_count / max(total, 1), 4)

    # ── 构建完整报告 ──
    def _metric_with_status(key: str, value: float) -> dict:
        """为指标附加状态（优秀/正常/需优化）"""
        defn = METRIC_DEFINITIONS.get(key, {})
        ok = defn.get("threshold_ok", 0.5)
        good = defn.get("threshold_good", 0.8)
        direction = defn.get("direction", "higher_better")
        if direction == "higher_better":
            status = "good" if value >= good else ("ok" if value >= ok else "warn")
        else:
            status = "good" if value <= good else ("ok" if value <= ok else "warn")
        return {
            **defn,
            "key": key,
            "value": value,
            "status": status,
            "display_value": f"{value*100:.1f}%" if defn.get("unit") == "ratio" else str(value),
        }

    report = {
        "total": total,
        "success_count": success_count,
        "fail_count": fail_count,
        "period_days": days,
        "generated_at": datetime.utcnow().isoformat(),

        # 管道阶段定义
        "pipeline_stages": PIPELINE_STAGES,

        # 第一层
        "layer1_retrieval": {
            "label": "第一层：检索质量",
            "description": "衡量检索系统是否找到了正确的文档，以及排序是否合理",
            "metrics": [
                _metric_with_status("recall_at_k", recall_k),
                _metric_with_status("precision_at_k", precision_k),
                _metric_with_status("mrr", mrr),
                _metric_with_status("ndcg", ndcg),
                _metric_with_status("pass_at_k", pass_1),
            ],
            "pass_at_1": pass_1,
            "pass_at_3": pass_3,
            "pass_at_5": pass_5,
        },

        # 第二层
        "layer2_generation": {
            "label": "第二层：生成一致性",
            "description": "衡量生成内容是否忠于检索材料，是否产生幻觉",
            "metrics": [
                _metric_with_status("faithfulness", avg_faithfulness),
                _metric_with_status("groundedness", avg_groundedness),
                _metric_with_status("factual_consistency", 0.0),  # LLM-as-Judge 待异步计算
            ],
        },

        # 第三层
        "layer3_system": {
            "label": "第三层：系统工程",
            "description": "衡量系统整体性能与稳定性",
            "metrics": [
                _metric_with_status("latency_ms", avg_latency),
                _metric_with_status("throughput", throughput),
                _metric_with_status("cache_hit_rate", cache_hit_rate),
                _metric_with_status("error_rate", error_rate),
                _metric_with_status("rejection_rate", rejection_rate),
            ],
        },

        "items": items,
    }

    return report
