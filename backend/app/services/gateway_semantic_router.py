"""语义路由 (SPEC §1.1) — 简单问题走小模型，复杂问题走大模型。

复杂度判定:
- 问题长度 <20字 + 无推理需求 → low (1-3)
- 问题长度 20-100字 + 需要检索 → medium (4-6)
- 问题长度 >100字 + 多步推理 → high (7-10)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COMPLEXITY_RULES = {
    "short": 1,        # <20字
    "has_multi_q": 3,  # 包含多个问号
    "needs_reason": 4, # 推理/分析/对比关键词
    "domain_specific": 2,# 专业领域关键词
    "long_text": 2,    # >100字
}

REASON_KEYWORDS = [
    "为什么", "如何", "怎么", "分析", "对比", "区别", "原因",
    "优化", "建议", "方案", "策略", "评估", "预测", "判断",
    "what if", "how to", "compare",
]

MULTI_Q_PATTERNS = ["？", "?", "吗", "呢"]


def estimate_complexity(question: str) -> int:
    """快速估算问题复杂度（1-10），不消耗LLM调用。

    返回: 1-10的整数
    """
    score = 1
    q = question.strip()
    if not q:
        return 1

    # 长度
    if len(q) < 20:
        score += COMPLEXITY_RULES["short"]
    elif len(q) > 100:
        score += COMPLEXITY_RULES["long_text"]

    # 多问题检测
    q_count = sum(1 for p in MULTI_Q_PATTERNS if q.count(p) > 0)
    if q_count >= 2:
        score += COMPLEXITY_RULES["has_multi_q"]

    # 推理关键词
    reason_hits = sum(1 for kw in REASON_KEYWORDS if kw in q.lower())
    if reason_hits >= 1:
        score += COMPLEXITY_RULES["needs_reason"]

    return min(score, 10)


def route_by_complexity(question: str) -> str:
    """根据复杂度返回推荐的任务类型。

    Returns:
        "qa" (简单/小模型), "summary" (中等), "reason" (复杂/大模型)
    """
    score = estimate_complexity(question)
    if score <= 3:
        return "qa"
    elif score <= 6:
        return "summary"
    else:
        return "reason"
