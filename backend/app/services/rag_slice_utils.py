"""RAG 预取切片规范化与 LLM 引用块（对齐 web_rebuild rag_slice_utils）。"""
from __future__ import annotations

import os
import re
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
    """供 RAG / 防稀释等多条回答链路复用的插图规则。"""
    return _picture_answer_rules()


def _picture_answer_rules() -> str:
    return "\n".join(
        [
            "四、含图切片与正文插图（picture 块 · 必须遵守）",
            "  · 切片中的 {picture_id:…; url:…; description:…} 中，description 与 picture_id 仅供你理解画面，"
            "禁止原文出现在用户可见正文中（前端不展示这两项）。",
            "  · 仅当某张图与用户问题**直接相关**时，才在对应步骤文字之后另起一行插入插图标记，格式：",
            "    {picture_id:图N-xxx; url:切片中的绝对路径;}",
            "    （不要带 description 字段；无关图片一律不插。）",
            "  · 插图前须用**一两句话**结合用户问题说明该图作用；可保留 description 里的**位置指示**"
            "（如「区块(1)」「第一处标记」「左侧按钮」），但禁止整段照搬 description/OCR 全文。",
            "  · 正文中不要写「见下图」「如上图所示」等空泛指代而不插图的句子。",
        ]
    )


def _citation_format_block() -> str:
    return "\n".join(
        [
            "【回答格式 · 按句引用 + 逻辑注释（必须严格遵守）】",
            "一、正文（按句为单位）",
            "  · 每一句依据知识库写出的论断，句末必须标注引用编号，格式为阿拉伯数字 1、2、3…（不用上标）。",
            "  · 同一句话可引用多个切片则写 1,2；编号对应下方预检索文献 [n]，禁止无编号的知识库论断。",
            "二、正文结束后依次输出两节（标题固定，不可省略）：",
            "  ## 文献切片明细",
            "  逐条列出本回答用到的切片（按 [n] 编号），每条须含：",
            "    - 切片[n]：所属父文档《父文档名》（父文档路径）",
            "    - 切片全文：（完整粘贴该切片正文，不可截断）",
            "    - 父文档全文：（写「见路径 xxx，前端可点击查看」）",
            "  ## 注释",
            "  按正文引用编号逐条写「处逻辑链路」（与正文句末编号一一对应，不可合并）：",
            "    1 处逻辑链路：摘录切片【1】原文「…关键句…」；因原文…，故正文第1句写成…。置信度：100",
            "  · 置信度为 0–100 整数。",
            "三、禁止编造未出现在切片中的事实。",
            _picture_answer_rules(),
        ]
    )


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
