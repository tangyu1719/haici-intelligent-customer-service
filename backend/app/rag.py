"""RAG 检索：粗筛大池 → BM25+向量精筛 → 自适应梯度 Top-K → 防稀释。"""

import logging
from typing import Dict, List

from langchain_core.documents import Document

from app.config import settings
from app.llms import get_llm
from app.services.chat_context import history_char_budget
from app.services.rag_gradient_filter import adaptive_gradient_topk
from app.services.rag_hybrid_scorer import hybrid_rescore
from app.services.rag_slice_utils import (
    build_rag_llm_blocks,
    normalize_rag_slices_from_docs,
)

logger = logging.getLogger(__name__)


def retrieve(query: str, tenant_id: str = "default", k: int | None = None) -> List[Document]:
    """粗筛：向量召回大池（默认 k=RAG_COARSE_POOL_K）。"""
    from app.vectorstore import search as vec_search

    fetch_k = k if k is not None else settings.RAG_COARSE_POOL_K
    docs = vec_search(query, k=fetch_k, tenant_id=tenant_id)
    filtered: list[Document] = []
    for d in docs:
        score = float(d.metadata.get("score", 0))
        if score >= settings.RAG_SCORE_THRESHOLD:
            filtered.append(d)
    return filtered


def fine_rank(query: str, docs: list[Document], coarse_count: int) -> tuple[list[Document], dict]:
    """精筛：BM25+向量混合重排 → 按粗筛池大小与分数质量自适应 Top-K。"""
    if not docs:
        return docs, {"coarse_count": coarse_count, "fine_in": 0, "final_k": 0}

    if settings.RAG_HYBRID_ENABLED:
        docs = hybrid_rescore(query, docs)
    else:
        docs = sorted(docs, key=lambda d: float(d.metadata.get("score", 0)), reverse=True)

    return adaptive_gradient_topk(docs, coarse_count)


def retrieve_merged(rag_query: str, tenant_id: str = "default") -> List[Document]:
    """多路粗筛合并 → 精筛（BM25+向量）→ 自适应梯度 Top-K。

    流程：
    1. 粗筛：每路 k=RAG_COARSE_POOL_K（默认 100），合并去重
    2. 精筛：BM25 + 向量 hybrid 重排
    3. 落档：粗筛 100 条且分数高 → 最多 10 条；粗筛 50 条且分数高 → 约 5~8 条
    """
    queries_done: set[str] = set()
    content_seen: set[str] = set()
    merged: list[Document] = []
    candidates = [rag_query.strip()] + [t for t in rag_query.split() if len(t.strip()) >= 2][:2]

    for q in candidates:
        q = q.strip()
        if not q or q in queries_done:
            continue
        queries_done.add(q)
        for d in retrieve(q, tenant_id, k=settings.RAG_COARSE_POOL_K):
            key = d.page_content[:80]
            if key in content_seen:
                continue
            content_seen.add(key)
            merged.append(d)

    coarse_count = len(merged)
    if not merged:
        return merged

    filtered, grad_meta = fine_rank(rag_query, merged, coarse_count)
    logger.info(
        "[智能客服-RAG|rag|retrieve_merged|硬编执行|完成] coarse=%s; fine_in=%s; "
        "ceiling=%s; quality=%s; out=%s; pool_k=%s",
        coarse_count,
        grad_meta.get("fine_in"),
        grad_meta.get("ceiling"),
        grad_meta.get("quality"),
        grad_meta.get("final_k"),
        settings.RAG_COARSE_POOL_K,
    )
    return filtered


def safe_retrieve_merged(
    rag_query: str, tenant_id: str = "default", apply_anti_dilution: bool = True
) -> tuple[List[Document], str | None]:
    """Agent 编排入口：粗筛+精筛 + 大规模上下文防稀释。"""
    try:
        docs = retrieve_merged(rag_query, tenant_id)
    except Exception as exc:
        logger.warning(
            "[智能客服-RAG|rag|retrieve_merged|硬编执行|降级] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        return [], None

    if not docs or not apply_anti_dilution or not settings.ANTI_DILUTION_ENABLED:
        return docs, None

    try:
        from app.services.context_anti_dilution import apply_anti_dilution as _apply

        processed_docs, llm_summary = _apply(docs, rag_query)
        return processed_docs, llm_summary
    except Exception as exc:
        logger.warning(
            "[智能客服-RAG|rag|anti_dilution|失败|降级] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        return docs, None


def rag_slices_from_docs(docs: List[Document]) -> list[dict]:
    return normalize_rag_slices_from_docs(docs)


def _format_history_block(history: List[dict], rolling_summary: str | None = None) -> str:
    budget = history_char_budget()
    lines: list[str] = []
    used = 0
    if rolling_summary:
        summary_line = f"【此前对话摘要】\n{rolling_summary}"
        lines.append(summary_line)
        used += len(summary_line)
    picked: list[str] = []
    for h in reversed(history):
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        line = f"{role}:{content}"
        if picked and used + len(line) > budget:
            break
        picked.append(line)
        used += len(line)
    picked.reverse()
    if lines and picked:
        return lines[0] + "\n" + "\n".join(picked)
    if lines:
        return lines[0]
    return "\n".join(picked)


def build_prompt_messages(
    query: str,
    docs: List[Document],
    history: List[dict],
    intent: str,
    anti_dilution_summary: str | None = None,
    rolling_summary: str | None = None,
) -> list[dict[str, str]]:
    if not docs:
        return []
    if anti_dilution_summary:
        from app.services.context_anti_dilution import build_anti_dilution_prompt_messages as _ad_build

        return _ad_build(query, docs, history, intent, anti_dilution_summary)

    from app.services.prompt_segments import build_rag_system_prompt, build_rag_user_prompt

    slices = rag_slices_from_docs(docs)
    slices = slices[:2]
    rag_context, cite_instr = build_rag_llm_blocks(slices, rag_query=query)
    hist_clean = [h for h in history if not (h.get("role") == "system" and "此前对话摘要" in str(h.get("content", "")))]
    hist = _format_history_block(hist_clean, rolling_summary)
    system = build_rag_system_prompt(cite_instr, include_picture_rule=True)
    user = build_rag_user_prompt(intent, hist, rag_context, query)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def citations_from_docs(docs: List[Document]) -> list[dict]:
    return rag_slices_from_docs(docs)


def rag_query(query: str, tenant_id: str = "default", history: List[dict] | None = None, intent: str = "product_consult") -> Dict:
    history = history or []
    docs = retrieve(query, tenant_id)
    if not docs:
        return {
            "answer": settings.FALLBACK_NO_CONTEXT,
            "context": [],
            "citations": [],
            "score": 0.0,
            "has_context": False,
        }
    llm = get_llm()
    messages = build_prompt_messages(query, docs, history, intent)
    answer = llm.call(messages[-1]["content"]) if messages else settings.FALLBACK_NO_CONTEXT
    return {
        "answer": answer,
        "context": [{"content": d.page_content[:200]} for d in docs],
        "citations": citations_from_docs(docs),
        "score": 0.9,
        "has_context": True,
    }
