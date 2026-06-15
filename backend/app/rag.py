"""减重版 RAG：Chroma 向量检索 + 大规模上下文防稀释 + 文献引用。"""

import logging
from typing import Dict, List

from langchain_core.documents import Document

from app.config import settings
from app.llms import get_llm
from app.services.chat_context import history_char_budget
from app.services.rag_slice_utils import (
    build_rag_llm_blocks,
    normalize_rag_slices_from_docs,
)

logger = logging.getLogger(__name__)


def retrieve(query: str, tenant_id: str = "default") -> List[Document]:
    from app.vectorstore import search as vec_search

    docs = vec_search(query, k=settings.RAG_TOP_K, tenant_id=tenant_id)
    filtered = []
    for d in docs:
        score = float(d.metadata.get("score", 0))
        if score >= settings.RAG_SCORE_THRESHOLD:
            filtered.append(d)
    return filtered


def retrieve_merged(rag_query: str, tenant_id: str = "default") -> List[Document]:
    queries_done: set[str] = set()
    content_seen: set[str] = set()
    merged: list[Document] = []
    candidates = [rag_query.strip()] + [t for t in rag_query.split() if len(t.strip()) >= 2][:5]
    for q in candidates:
        q = q.strip()
        if not q or q in queries_done:
            continue
        queries_done.add(q)
        for d in retrieve(q, tenant_id):
            key = d.page_content[:80]
            if key in content_seen:
                continue
            content_seen.add(key)
            merged.append(d)
    merged.sort(key=lambda x: float(x.metadata.get("score", 0)), reverse=True)
    return merged[: settings.RAG_TOP_K]


def safe_retrieve_merged(
    rag_query: str, tenant_id: str = "default", apply_anti_dilution: bool = True
) -> tuple[List[Document], str | None]:
    """Agent 编排入口：合并多路 RAG 检索 + 大规模上下文防稀释。

    返回 (docs, anti_dilution_summary)。
    anti_dilution_summary 为 None 表示未触发防稀释机制。
    """
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


def _format_history_block(history: List[dict]) -> str:
    budget = history_char_budget()
    lines: list[str] = []
    used = 0
    for h in reversed(history):
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        line = f"{role}:{content}"
        if lines and used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    lines.reverse()
    return "\n".join(lines)


def build_prompt_messages(
    query: str,
    docs: List[Document],
    history: List[dict],
    intent: str,
    anti_dilution_summary: str | None = None,
) -> list[dict[str, str]]:
    """构建 Prompt 消息，支持防稀释上下文。"""
    if not docs:
        return []
    if anti_dilution_summary:
        from app.services.context_anti_dilution import build_anti_dilution_prompt_messages as _ad_build

        return _ad_build(query, docs, history, intent, anti_dilution_summary)

    slices = rag_slices_from_docs(docs)
    rag_context, cite_instr = build_rag_llm_blocks(slices, rag_query=query)
    hist = _format_history_block(history)
    system = (
        "你是企业智能客服。只能依据知识库片段回答，不得编造。\n"
        "若资料不足请明确说明无法回答。\n"
        "回答中插图须紧扣用户问题：仅插入与问题相关的 picture 块（仅 url，不带 description），"
        "并用结合问题的简短说明点明图中关键位置（可引用 description 中的区块/标记编号）。\n\n"
        + cite_instr
    )
    user = f"意图:{intent}\n历史:\n{hist or '无'}\n\n{rag_context}\n\n问题:{query}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def citations_from_docs(docs: List[Document]) -> list[dict]:
    """SSE 下发完整文献切片（供前端折叠面板）。"""
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
