"""梯度 Top-K：粗筛池大小 × 精筛分数质量 → 自适应落档（10/8/5/3）。"""

from __future__ import annotations

import logging

from langchain_core.documents import Document

from app.config import settings

logger = logging.getLogger(__name__)


def parse_gradient_k() -> list[int]:
    """解析 RAG_GRADIENT_K，如 '10,8,5,3'。"""
    raw = (settings.RAG_GRADIENT_K or "10,8,5,3").strip()
    tiers: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            tiers.append(int(part))
    return sorted(set(tiers), reverse=True) or [10, 8, 5, 3]


def pool_size_ceiling(coarse_count: int, tiers: list[int] | None = None) -> int:
    """粗筛池 → 精筛上限 ceiling。

    - hard：按系统配置映射表（如 100:10,50:5,20:3）
    - smart：按粗筛池占 RAG_COARSE_POOL_K 比例 + 梯度档位智能落档
    """
    from app.services.system_settings import get_rag_pool_ceiling_map_pairs, get_rag_pool_ceiling_mode

    tiers = tiers or parse_gradient_k()
    min_k = settings.RAG_TOP_K
    mode = get_rag_pool_ceiling_mode()

    if mode == "hard":
        pairs = get_rag_pool_ceiling_map_pairs()
        for pool_min, top_k in pairs:
            if coarse_count >= pool_min:
                return top_k
        if pairs:
            return min(k for _, k in pairs)
        return max(min_k, tiers[-1] if tiers else min_k)

    # smart：按粗筛池量分段映射到梯度档位
    if coarse_count >= settings.RAG_COARSE_POOL_K * 0.8:
        return tiers[0]
    if coarse_count >= settings.RAG_COARSE_POOL_K * 0.4:
        return tiers[1] if len(tiers) > 1 else tiers[0]
    if coarse_count >= settings.RAG_COARSE_POOL_K * 0.15:
        return tiers[2] if len(tiers) > 2 else tiers[-1]
    return max(min_k, tiers[-1] if tiers else min_k)


def _score_of(d: Document) -> float:
    return float(d.metadata.get("hybrid_score", d.metadata.get("score", 0)))


def _quality_tier(scores: list[float], ceiling: int) -> str:
    """根据精筛后分数簇判断质量档位：high / medium / low。"""
    if not scores:
        return "low"
    top = scores[0]
    head = scores[: min(ceiling, len(scores))]
    median = head[len(head) // 2]
    high_cnt = sum(1 for s in head if s >= settings.RAG_HIGH_SCORE_THRESHOLD)
    high_ratio = high_cnt / max(len(head), 1)

    if top >= settings.RAG_HIGH_SCORE_THRESHOLD and high_ratio >= 0.7:
        return "high"
    if median >= settings.RAG_SCORE_THRESHOLD:
        return "medium"
    return "low"


def adaptive_gradient_topk(
    docs: list[Document],
    coarse_count: int,
) -> tuple[list[Document], dict]:
    """精筛后自适应 Top-K。

    1. 按粗筛池大小确定上限 ceiling（100→10, 50→5~8 …）
    2. 按精筛分数质量决定实际落档（分数都高→顶格；一般→降档；差→min_k）
    3. 分数断层处截断，避免尾部噪声
    """
    meta: dict = {
        "coarse_count": coarse_count,
        "fine_in": len(docs),
        "ceiling": 0,
        "quality": "low",
        "final_k": 0,
        "ceiling_mode": "",
    }
    if not docs:
        return docs, meta

    tiers = parse_gradient_k()
    min_k = settings.RAG_TOP_K
    sorted_docs = sorted(docs, key=_score_of, reverse=True)
    scores = [_score_of(d) for d in sorted_docs]

    from app.services.system_settings import get_rag_pool_ceiling_mode

    ceiling = pool_size_ceiling(coarse_count, tiers)
    meta["ceiling"] = ceiling
    meta["ceiling_mode"] = get_rag_pool_ceiling_mode()

    quality = _quality_tier(scores, ceiling)
    meta["quality"] = quality

    if quality == "high":
        target = ceiling
    elif quality == "medium":
        # 降一档
        lower = [t for t in tiers if t < ceiling]
        target = lower[0] if lower else max(min_k, ceiling // 2)
    else:
        target = min_k

    target = min(target, len(sorted_docs))

    # 分数断层截断（尾部低于阈值或分差过大则丢弃）
    cut_at = len(scores)
    for i in range(len(scores) - 1):
        if scores[i] - scores[i + 1] > settings.RAG_SCORE_GAP_THRESHOLD:
            cut_at = i + 1
            break
    if cut_at < len(scores):
        head_min = min(scores[:cut_at]) if cut_at > 0 else scores[0]
        tail_max = max(scores[cut_at:]) if cut_at < len(scores) else 0.0
        if head_min - tail_max > settings.RAG_SCORE_GAP_THRESHOLD:
            target = min(target, cut_at)
    # 剔除低于阈值的尾部
    while target > min_k and target > 0 and scores[target - 1] < settings.RAG_SCORE_THRESHOLD:
        target -= 1
    target = max(1, target)
    meta["final_k"] = target

    logger.info(
        "[智能客服-RAG|rag_gradient|adaptive_topk|硬编执行|完成] coarse=%s; fine_in=%s; "
        "ceiling=%s; quality=%s; final_k=%s",
        coarse_count,
        len(docs),
        ceiling,
        quality,
        target,
    )
    return sorted_docs[:target], meta
