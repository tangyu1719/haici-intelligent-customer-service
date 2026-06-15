"""RAG 预取切片规范化与 LLM 引用块（对齐 web_rebuild rag_slice_utils）。

引用格式与插图规则已收敛到 prompt_segments 模块：
  - build_citation_format_block() → 完整引用格式指令
  - build_picture_answer_rules() → 插图规则指令
"""
from __future__ import annotations

import os
from typing import Any

from langchain_core.documents import Document


def normalize_rag_slices(hits: list[Any], *, max_slices: int = 8) -> list[dict[str, Any]]:
    """将检索命中转为前端/LLM 统一的文献切片结构。"""
    out: list[dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        content = str(hit.get("content") or hit.get("text") or hit.get("snippet") or "").strip()
        if not content:
            continue
        meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        src = str(hit.get("source_file") or hit.get("file") or hit.get("source") or "")
        title = (
            str(meta.get("title") or hit.get("title") or "").strip()
            or (os.path.basename(src) if src else "")
            or "知识库片段"
        )
        ref_id = len(out) + 1
        out.append(
            {
                "ref_id": ref_id,
                "title": title,
                "parent_document": title,
                "parent_name": title,
                "source_file": src,
                "chunk_id": hit.get("chunk_id"),
                "score": hit.get("score"),
                "content": content,
                "slice_content": content,
                "metadata": meta,
            }
        )
        if len(out) >= max_slices:
            break
    return out


def normalize_rag_slices_from_docs(docs: list[Document], *, max_slices: int = 8) -> list[dict[str, Any]]:
    hits = []
    for d in docs:
        name = str(d.metadata.get("document_name") or "未知文档")
        hits.append(
            {
                "content": d.page_content,
                "metadata": d.metadata,
                "source_file": name,
                "title": name,
                "score": d.metadata.get("score"),
                "chunk_id": d.metadata.get("document_id"),
            }
        )
    return normalize_rag_slices(hits, max_slices=max_slices)


def picture_answer_rules() -> str:
    """供 RAG / 防稀释等多条回答链路复用的插图规则。

    段式指令变量来自 prompt_segments.build_picture_answer_rules()。
    """
    from app.services.prompt_segments import build_picture_answer_rules as _build

    return _build()


def _citation_format_block() -> str:
    """完整引用格式指令块。

    段式指令变量来自 prompt_segments.build_citation_format_block()。
    """
    from app.services.prompt_segments import build_citation_format_block as _build

    return _build()


def build_rag_llm_blocks(
    rag_slices: list[dict[str, Any]],
    *,
    prefetch_error: str = "",
    rag_query: str = "",
) -> tuple[str, str]:
    cite_lines = [_citation_format_block()]
    slices = [s for s in (rag_slices or []) if isinstance(s, dict) and s.get("content")]
    if not slices:
        ctx = "编排段知识库预检索：未命中切片。"
        if prefetch_error:
            ctx += f" 原因：{prefetch_error[:300]}"
        if rag_query:
            ctx += f" 检索词：{rag_query[:200]}"
        return ctx, cite_lines[0]

    doc_lines = ["【预检索文献 · 原文切片（编号供正文句末引用）】"]
    if rag_query:
        doc_lines.append(f"检索词：{rag_query[:200]}")
    for sl in slices:
        rid = sl.get("ref_id")
        parent = sl.get("parent_document") or sl.get("title") or "片段"
        src = sl.get("source_file") or ""
        score = sl.get("score")
        score_s = f" score={score:.4f}" if isinstance(score, (int, float)) else ""
        doc_lines.append(f"\n[{rid}] 父文档：《{parent}》{score_s}")
        if src:
            doc_lines.append(f"父文档路径：{src}")
        doc_lines.append("切片全文：")
        doc_lines.append(str(sl.get("content") or ""))

    return "\n".join(doc_lines), cite_lines[0]
