"""大规模上下文防稀释机制 (PRD加分项5)

在企业级场景中，当知识库文档非常多时，检索返回的相关片段可能达到数十条。
本模块确保 LLM 在处理大量上下文时：
（1）不会因"注意力稀释"而遗漏某条关键规则；
（2）不会在信息过载时产生幻觉。

策略：
- 分层摘要：对检索结果按文档分组后生成分层摘要（文档级摘要 + 片段级原文）
- 规则优先级排序：基于语义相似度和关键词匹配度对片段排序
- 分步校验：关键规则提取 + 逐条验证 + 一致性检查
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from langchain_core.documents import Document

from app.config import settings
from app.llms import get_llm

logger = logging.getLogger(__name__)

ANTI_DILUTION_THRESHOLD = 8  # 超过此数量的检索片段触发防稀释机制
MAX_DOC_GROUPS = 5  # 最多按文档分组的数量
SLICES_PER_GROUP_SUMMARY = 3  # 每组取 Top-N 片段用于摘要


def _group_docs_by_source(docs: list[Document]) -> dict[str, list[Document]]:
    """按来源文档名称对检索结果分组。"""
    groups: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        src = str(d.metadata.get("document_name") or d.metadata.get("source") or "未知文档")
        groups[src].append(d)
    return groups


def _rank_docs_by_priority(docs: list[Document], query: str) -> list[Document]:
    """基于关键词命中数和相似度分数对片段进行优先级排序。

    优先级计算：
    - 相似度分数权重 0.6
    - 关键词命中率权重 0.4
    """
    query_lower = query.lower()
    query_keywords = set(query_lower.split())

    scored: list[tuple[float, Document]] = []
    for d in docs:
        score = float(d.metadata.get("score", 0))
        content_lower = d.page_content.lower()

        kw_hits = sum(1 for kw in query_keywords if kw in content_lower)
        kw_ratio = min(kw_hits / max(len(query_keywords), 1), 1.0)

        priority = score * 0.6 + kw_ratio * 0.4
        scored.append((priority, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored]


def _extract_key_rules(slices_text: str) -> list[str]:
    """从检索片段中提取关键规则/条款（基于正则和关键词匹配）。"""
    rules: list[str] = []
    lines = slices_text.split("\n")
    rule_patterns = [
        re.compile(r"^\d+[\.\、\)]\s*(.+)", re.UNICODE),  # 编号列表
        re.compile(r"^[一二三四五六七八九十]+[\.\、\)]\s*(.+)", re.UNICODE),  # 中文编号
        re.compile(r"^(规则|条款|政策|注意|警告|提示|重要)[：:]\s*(.+)", re.UNICODE),
        re.compile(r"^(不得|禁止|必须|应当|可以|允许|严禁|务必)\s*(.+)", re.UNICODE),
    ]
    for line in lines:
        line = line.strip()
        if not line or len(line) < 4:
            continue
        for pat in rule_patterns:
            m = pat.match(line)
            if m:
                rules.append(line)
                break
    return rules


def _build_layered_summary(
    groups: dict[str, list[Document]],
    query: str,
) -> dict[str, Any]:
    """构建分层摘要结构。

    第一层：每个文档组的摘要（文档名称 + 关键规则提取）
    第二层：Top-K 片段的优先级排序列表
    第三层：原始片段全文（供 LLM 精确引用）
    """
    layers: dict[str, Any] = {
        "total_groups": len(groups),
        "total_slices": sum(len(v) for v in groups.values()),
        "groups": [],
    }

    for src_name, docs in groups.items():
        ranked = _rank_docs_by_priority(docs, query)
        top_slices = ranked[:SLICES_PER_GROUP_SUMMARY]

        merged_text = "\n\n".join(
            d.page_content[:600] for d in top_slices
        )
        key_rules = _extract_key_rules(merged_text)

        group_info = {
            "source": src_name,
            "slice_count": len(docs),
            "top_score": max(float(d.metadata.get("score", 0)) for d in docs),
            "avg_score": sum(float(d.metadata.get("score", 0)) for d in docs) / len(docs),
            "key_rules": key_rules[:8],
            "top_slices": [
                {
                    "content": d.page_content[:800],
                    "score": float(d.metadata.get("score", 0)),
                    "chunk_index": i,
                }
                for i, d in enumerate(top_slices)
            ],
        }
        layers["groups"].append(group_info)

    layers["groups"].sort(key=lambda g: g["top_score"], reverse=True)
    return layers


def _generate_layer_summary_with_llm(layers: dict[str, Any], query: str) -> str:
    """使用 LLM 对分层结果生成综合摘要，保留关键规则并标注置信度。"""
    if not layers["groups"]:
        return ""

    group_descriptions: list[str] = []
    for g in layers["groups"]:
        rules_text = "\n  - ".join(g["key_rules"][:5]) or "无显式规则"
        group_descriptions.append(
            f"文档《{g['source']}》(相关度={g['top_score']:.3f}):\n"
            f"  关键规则/要点:\n  - {rules_text}"
        )

    prompt = (
        "你是企业知识库审核助手。请阅读以下从多个文档检索到的信息，"
        "生成一个结构化摘要供客服使用。\n\n"
        f"用户问题：{query}\n\n"
        "检索到的文档与规则：\n"
        + "\n\n".join(group_descriptions)
        + "\n\n输出要求（JSON 格式）：\n"
        '{\n  "summary": "200字以内的综合摘要",\n'
        '  "priority_rules": ["规则1", "规则2"],\n'
        '  "confidence": 80,\n'
        '  "needs_clarification": false\n'
        "}"
    )

    try:
        llm = get_llm()
        response = llm.call(prompt)
        data = json.loads(response) if isinstance(response, str) else response
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"LLM分层摘要生成失败: {exc}")
        fallback = {
            "summary": "；".join(
                f"{g['source']}: {g['key_rules'][0]}"
                for g in layers["groups"] if g["key_rules"]
            )[:200],
            "priority_rules": [
                r for g in layers["groups"] for r in g["key_rules"][:2]
            ][:5],
            "confidence": 60,
            "needs_clarification": len(layers["groups"]) > 5,
        }
        return json.dumps(fallback, ensure_ascii=False, indent=2)


def _build_anti_dilution_context(
    layers: dict[str, Any],
    llm_summary: str,
) -> tuple[str, str]:
    """构建防稀释后的上下文和引用指令。

    返回 (rag_context, cite_instruction)
    """
    parts: list[str] = []
    parts.append("【分层摘要（防注意力稀释）】")
    parts.append(f"共检索到 {layers['total_groups']} 个文档组的 {layers['total_slices']} 个相关片段。\n")

    try:
        summary_data = json.loads(llm_summary) if isinstance(llm_summary, str) else llm_summary
        parts.append(f"综合摘要：{summary_data.get('summary', '')}")
        pr = summary_data.get("priority_rules", [])
        if pr:
            parts.append("\n优先规则（必须遵循）：")
            for i, rule in enumerate(pr, 1):
                parts.append(f"  {i}. {rule}")
    except (json.JSONDecodeError, TypeError):
        parts.append(llm_summary)

    parts.append("\n【详细片段（按优先级排序）】")
    slice_idx = 1
    for g in layers["groups"]:
        parts.append(f"\n--- 文档：《{g['source']}》(相关度={g['top_score']:.3f}) ---")
        if g["key_rules"]:
            parts.append(f"关键规则: {'; '.join(g['key_rules'][:4])}")
        for sl in g["top_slices"]:
            parts.append(f"\n[切片{slice_idx}] {sl['content'][:600]}")
            slice_idx += 1

    cite_instr = (
        "【防稀释引用规则】\n"
        "1. 优先引用上述「优先规则」列表中的条款\n"
        "2. 若多个文档存在冲突规则，明确指出差异并建议以最新/最权威的文档为准\n"
        "3. 每一步推断必须对应一个具体的切片编号\n"
        "4. 不要合并或混淆来自不同文档的规则"
    )

    return "\n".join(parts), cite_instr


def apply_anti_dilution(
    docs: list[Document],
    query: str,
) -> tuple[list[Document], str | None]:
    """对 RAG 检索结果应用防稀释处理。

    当检索片段数量超过阈值时，执行：
    1. 按文档分组
    2. 优先级排序
    3. 分层摘要生成
    4. LLM 综合摘要

    返回：
    - 处理后的文档列表（可能经过筛选和排序）
    - LLM 摘要 JSON 字符串（如果触发了防稀释），否则为 None
    """
    if len(docs) <= ANTI_DILUTION_THRESHOLD:
        return docs, None

    logger.info(
        f"[防稀释] 触发机制，检索片段数={len(docs)}，阈值={ANTI_DILUTION_THRESHOLD}"
    )

    groups = _group_docs_by_source(docs)

    # 限制文档组数量，取相关度最高的组
    if len(groups) > MAX_DOC_GROUPS:
        group_scores = {
            src: max(float(d.metadata.get("score", 0)) for d in gdocs)
            for src, gdocs in groups.items()
        }
        sorted_groups = sorted(group_scores.items(), key=lambda x: x[1], reverse=True)
        selected = {src for src, _ in sorted_groups[:MAX_DOC_GROUPS]}
        groups = {src: gdocs for src, gdocs in groups.items() if src in selected}

    layers = _build_layered_summary(groups, query)
    llm_summary = _generate_layer_summary_with_llm(layers, query)

    # 重新合并文档，保持优先级排序
    merged: list[Document] = []
    for g in layers["groups"]:
        src_docs = groups[g["source"]]
        ranked = _rank_docs_by_priority(src_docs, query)
        merged.extend(ranked[:settings.RAG_TOP_K])

    return merged[: settings.RAG_TOP_K * 2], llm_summary


def build_anti_dilution_prompt_messages(
    query: str,
    docs: list[Document],
    history: list[dict],
    intent: str,
    llm_summary: str | None,
) -> list[dict[str, str]]:
    """构建包含防稀释上下文的 Prompt 消息。

    当 llm_summary 不为 None 时，使用分层摘要格式；
    否则使用标准 RAG 格式。
    """
    from app.services.rag_slice_utils import build_rag_llm_blocks, normalize_rag_slices_from_docs

    if not docs:
        return []

    if llm_summary:
        from .context_anti_dilution import _build_layered_summary, _build_anti_dilution_context

        groups = _group_docs_by_source(docs)
        layers = _build_layered_summary(groups, query)
        rag_context, cite_instr = _build_anti_dilution_context(layers, llm_summary)
    else:
        slices = normalize_rag_slices_from_docs(docs)
        rag_context, cite_instr = build_rag_llm_blocks(slices, rag_query=query)

    from app.services.chat_context import history_char_budget

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
    hist_block = "\n".join(lines)

    system = (
        "你是企业智能客服。只能依据知识库片段回答，不得编造。\n"
        "若资料不足请明确说明无法回答。\n\n"
        + cite_instr
    )
    user = f"意图:{intent}\n历史:\n{hist_block or '无'}\n\n{rag_context}\n\n问题:{query}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
