"""RAG 检索 Tool Calling 封装 — 供 ReAct Agent 多次调用。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.documents import Document

from app.config import settings
from app.rag import citations_from_docs, safe_retrieve_merged

logger = logging.getLogger(__name__)

# OpenAI 兼容 tool schema
RAG_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "rag_search",
        "description": (
            "从企业知识库检索与问题相关的文档片段。"
            "复杂问题可多次调用，每次使用不同检索词以覆盖不同子问题。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索查询词，应简洁明确，可包含产品名、功能名、政策关键词",
                },
                "purpose": {
                    "type": "string",
                    "description": "本次检索目的，如「查退换货政策」「查操作步骤」",
                },
            },
            "required": ["query"],
        },
    },
}


def execute_rag_search(
    query: str,
    tenant_id: str = "default",
    *,
    purpose: str = "",
    apply_anti_dilution: bool = True,
) -> dict[str, Any]:
    """执行一次 RAG 检索（Tool Act 阶段），返回结构化观察结果。"""
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "query": q,
            "purpose": purpose,
            "slice_count": 0,
            "top_score": 0.0,
            "anti_dilution": False,
            "citations": [],
            "summary": "检索词为空，未执行检索。",
        }

    docs, ad_summary = safe_retrieve_merged(q, tenant_id, apply_anti_dilution=apply_anti_dilution)
    citations = citations_from_docs(docs)
    top_score = max((float(d.metadata.get("score", 0)) for d in docs), default=0.0)

    # 构建观察摘要（供 Observe 阶段回灌 LLM）
    if not docs:
        summary = f"检索「{q}」未找到相关知识库片段。"
    else:
        src_names = list(dict.fromkeys(
            str(d.metadata.get("document_name") or d.metadata.get("source") or "未知")
            for d in docs
        ))[:5]
        summary = (
            f"检索「{q}」命中 {len(docs)} 条片段（top_score={top_score:.3f}），"
            f"来源文档：{'、'.join(src_names)}。"
        )
        if ad_summary:
            summary += " 已启用防稀释分层摘要。"

    logger.info(
        "[智能客服-RAG|rag_tool|execute_rag_search|工具执行|完成] query=%s; slices=%s; anti_dilution=%s",
        q[:80],
        len(docs),
        ad_summary is not None,
    )

    return {
        "ok": bool(docs),
        "query": q,
        "purpose": purpose,
        "slice_count": len(docs),
        "top_score": top_score,
        "anti_dilution": ad_summary is not None,
        "anti_dilution_summary": ad_summary,
        "citations": citations,
        "docs": docs,
        "summary": summary,
    }


def format_observe_text(result: dict[str, Any]) -> str:
    """将 Tool 结果格式化为 Observe 文本（流式展示 + LLM 回灌）。"""
    lines = [f"【观察】{result.get('summary', '')}"]
    citations = result.get("citations") or []
    for i, c in enumerate(citations[:6], 1):
        content = str(c.get("slice_content") or c.get("content") or "")[:300]
        parent = str(c.get("parent_name") or c.get("document_name") or "未知文档")
        score = c.get("score")
        score_txt = f" score={score:.3f}" if isinstance(score, (int, float)) else ""
        lines.append(f"  [片段{i}] 《{parent}》{score_txt}\n  {content}")
    if len(citations) > 6:
        lines.append(f"  … 另有 {len(citations) - 6} 条片段未展开")
    return "\n".join(lines)


def merge_rag_docs(all_results: list[dict[str, Any]]) -> list[Document]:
    """合并多次 RAG 调用的文档，按分数去重。"""
    seen: set[str] = set()
    merged: list[Document] = []
    for res in all_results:
        for d in res.get("docs") or []:
            key = d.page_content[:80]
            if key in seen:
                continue
            seen.add(key)
            merged.append(d)
    merged.sort(key=lambda x: float(x.metadata.get("score", 0)), reverse=True)
    return merged[: settings.RAG_COARSE_TOP_K]
