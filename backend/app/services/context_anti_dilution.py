"""大规模上下文防稀释机制 (PRD加分项5)

在企业级场景中，当知识库文档非常多时，检索返回的相关片段可能达到数十条。
本模块确保 LLM 在处理大量上下文时：
（1）不会因"注意力稀释"而遗漏某条关键规则；
（2）不会在信息过载时产生幻觉；
（3）对跨文档规则冲突给出差异说明与置信度。
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from langchain_core.documents import Document

from app.config import settings
from app.llms import get_llm

logger = logging.getLogger(__name__)

SLICES_PER_GROUP_SUMMARY = 3  # 每组取 Top-N 片段用于摘要


def get_anti_dilution_threshold() -> int:
    return settings.ANTI_DILUTION_THRESHOLD


def get_max_doc_groups() -> int:
    return settings.ANTI_DILUTION_MAX_GROUPS


def _group_docs_by_source(docs: list[Document]) -> dict[str, list[Document]]:
    """按来源文档名称对检索结果分组。"""
    groups: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        src = str(d.metadata.get("document_name") or d.metadata.get("source") or "未知文档")
        groups[src].append(d)
    return groups


def _rank_docs_by_priority(docs: list[Document], query: str) -> list[Document]:
    """基于关键词命中数和相似度分数对片段进行优先级排序。"""
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
        re.compile(r"^\d+[\.\、\)]\s*(.+)", re.UNICODE),
        re.compile(r"^[一二三四五六七八九十]+[\.\、\)]\s*(.+)", re.UNICODE),
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


def _normalize_rule_key(rule: str) -> str:
    """规则归一化键：提取约束动词+核心名词，用于冲突检测。"""
    rule = rule.strip()
    for prefix in ("必须", "应当", "务必", "不得", "禁止", "严禁", "可以", "允许"):
        if rule.startswith(prefix):
            return prefix + rule[len(prefix):][:40]
    return rule[:40]


def _rule_polarity(rule: str) -> str | None:
    """判断规则极性：positive（必须/应当）或 negative（禁止/不得）。"""
    for neg in ("不得", "禁止", "严禁"):
        if neg in rule[:6]:
            return "negative"
    for pos in ("必须", "应当", "务必"):
        if pos in rule[:6]:
            return "positive"
    return None


def _parse_doc_timestamp(doc_name: str, metadata: dict | None = None) -> float:
    """从文档名或 metadata 推断时间戳（越大越新）。"""
    meta = metadata or {}
    for key in ("updated_at", "created_at", "document_updated_at"):
        val = meta.get(key)
        if val:
            try:
                if isinstance(val, (int, float)):
                    return float(val)
                return datetime.fromisoformat(str(val).replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                pass
    # 从文件名提取日期 YYYYMMDD 或 YYYY-MM-DD
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", doc_name)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).timestamp()
        except ValueError:
            pass
    return 0.0


def detect_rule_conflicts(
    groups: dict[str, list[Document]],
) -> list[dict[str, Any]]:
    """检测跨文档规则冲突：positive/negative 矛盾或同主题数值差异。"""
    source_rules: list[dict[str, Any]] = []
    for src, docs in groups.items():
        merged = "\n".join(d.page_content for d in docs[:5])
        rules = _extract_key_rules(merged)
        top_score = max(float(d.metadata.get("score", 0)) for d in docs)
        ts = max(_parse_doc_timestamp(src, d.metadata) for d in docs)
        for rule in rules:
            source_rules.append({
                "rule": rule,
                "source": src,
                "score": top_score,
                "timestamp": ts,
                "polarity": _rule_polarity(rule),
            })

    conflicts: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, a in enumerate(source_rules):
        for b in source_rules[i + 1:]:
            if a["source"] == b["source"]:
                continue
            pair_key = tuple(sorted([a["source"], b["source"]]))
            if pair_key in seen_pairs:
                continue

            pol_a, pol_b = a["polarity"], b["polarity"]
            if pol_a and pol_b and pol_a != pol_b:
                # 检查主题词重叠
                words_a = set(re.findall(r"[\u4e00-\u9fff]{2,}", a["rule"]))
                words_b = set(re.findall(r"[\u4e00-\u9fff]{2,}", b["rule"]))
                overlap = words_a & words_b
                if overlap or ("退货" in a["rule"] and "退货" in b["rule"]):
                    seen_pairs.add(pair_key)
                    newer = a if (a["timestamp"], a["score"]) >= (b["timestamp"], b["score"]) else b
                    conflicts.append({
                        "topic_key": "|".join(sorted(overlap))[:60] or "规则冲突",
                        "type": "polarity_conflict",
                        "entries": [a, b],
                        "recommended_source": newer["source"],
                        "recommended_rule": newer["rule"],
                        "confidence": min(95, 60 + int(newer["score"] * 30)),
                        "resolution": (
                            f"文档《{a['source']}》与《{b['source']}》规则矛盾，"
                            f"建议以较新/相关度更高的《{newer['source']}》为准：{newer['rule'][:80]}"
                        ),
                    })
                    continue

            # 数值型冲突
            nums_a = re.findall(r"(\d+)\s*(天|日|小时|个月|年)", a["rule"])
            nums_b = re.findall(r"(\d+)\s*(天|日|小时|个月|年)", b["rule"])
            if nums_a and nums_b:
                unit_a = nums_a[0][1]
                unit_b = nums_b[0][1]
                val_a = int(nums_a[0][0])
                val_b = int(nums_b[0][0])
                if unit_a == unit_b and val_a != val_b:
                    seen_pairs.add(pair_key)
                    newer = a if (a["timestamp"], a["score"]) >= (b["timestamp"], b["score"]) else b
                    conflicts.append({
                        "topic_key": f"{unit_a}数值",
                        "type": "numeric_conflict",
                        "entries": [a, b],
                        "recommended_source": newer["source"],
                        "recommended_rule": newer["rule"],
                        "confidence": min(90, 55 + int(newer["score"] * 35)),
                        "resolution": (
                            f"不同文档 {unit_a} 数不一致（{val_a}{unit_a} vs {val_b}{unit_b}），"
                            f"建议以《{newer['source']}》为准：{newer['rule'][:60]}"
                        ),
                    })

    return conflicts


def resolve_rule_conflicts(conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总冲突解析结果，供 Prompt 与 LLM 摘要使用。"""
    if not conflicts:
        return {"has_conflicts": False, "conflicts": [], "unified_rules": []}

    unified: list[str] = []
    for c in conflicts:
        unified.append(c.get("resolution") or c.get("recommended_rule", ""))

    avg_conf = sum(c.get("confidence", 60) for c in conflicts) / len(conflicts)
    return {
        "has_conflicts": True,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "unified_rules": unified,
        "overall_confidence": round(avg_conf, 1),
    }


def _build_layered_summary(
    groups: dict[str, list[Document]],
    query: str,
    conflict_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建分层摘要结构。"""
    layers: dict[str, Any] = {
        "total_groups": len(groups),
        "total_slices": sum(len(v) for v in groups.values()),
        "groups": [],
        "conflict_resolution": conflict_resolution or {},
    }

    for src_name, docs in groups.items():
        ranked = _rank_docs_by_priority(docs, query)
        top_slices = ranked[:SLICES_PER_GROUP_SUMMARY]

        merged_text = "\n\n".join(d.page_content[:600] for d in top_slices)
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


def _generate_layer_summary_with_llm(
    layers: dict[str, Any],
    query: str,
    conflict_resolution: dict[str, Any] | None = None,
) -> str:
    """使用 LLM 对分层结果生成综合摘要；失败则规则级 fallback。"""
    if not layers["groups"]:
        return ""

    group_descriptions: list[str] = []
    for g in layers["groups"]:
        rules_text = "\n  - ".join(g["key_rules"][:5]) or "无显式规则"
        group_descriptions.append(
            f"文档《{g['source']}》(相关度={g['top_score']:.3f}):\n"
            f"  关键规则/要点:\n  - {rules_text}"
        )

    conflict_block = ""
    if conflict_resolution and conflict_resolution.get("has_conflicts"):
        conflict_block = (
            "\n\n【已检测到的跨文档规则冲突及建议】\n"
            + "\n".join(f"- {r}" for r in conflict_resolution.get("unified_rules", []))
        )

    from app.services.prompt_segments import build_anti_dilution_summary_prompt as _build_summary_prompt
    prompt = _build_summary_prompt(query, group_descriptions) + conflict_block

    try:
        llm = get_llm()
        response = llm.call(prompt)
        data = json.loads(response) if isinstance(response, str) else response
        if conflict_resolution and conflict_resolution.get("has_conflicts"):
            data["rule_conflicts"] = conflict_resolution.get("conflicts", [])
            data["conflict_resolutions"] = conflict_resolution.get("unified_rules", [])
            data["confidence"] = min(
                data.get("confidence", 70),
                conflict_resolution.get("overall_confidence", 70),
            )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(
            "[智能客服-RAG|context_anti_dilution|layer_summary|Agent执行|降级] error_type=%s",
            type(exc).__name__,
        )
        pr = [r for g in layers["groups"] for r in g["key_rules"][:2]][:5]
        if conflict_resolution and conflict_resolution.get("unified_rules"):
            pr = list(dict.fromkeys(conflict_resolution["unified_rules"] + pr))[:8]
        fallback = {
            "summary": "；".join(
                f"{g['source']}: {g['key_rules'][0]}"
                for g in layers["groups"] if g["key_rules"]
            )[:200],
            "priority_rules": pr,
            "confidence": conflict_resolution.get("overall_confidence", 60) if conflict_resolution else 60,
            "needs_clarification": len(layers["groups"]) > get_max_doc_groups(),
            "rule_conflicts": (conflict_resolution or {}).get("conflicts", []),
        }
        return json.dumps(fallback, ensure_ascii=False, indent=2)


def _build_anti_dilution_context(
    layers: dict[str, Any],
    llm_summary: str,
) -> tuple[str, str]:
    """构建防稀释后的上下文和引用指令。"""
    parts: list[str] = []
    parts.append("【分层摘要（防注意力稀释）】")
    parts.append(f"共检索到 {layers['total_groups']} 个文档组的 {layers['total_slices']} 个相关片段。\n")

    try:
        summary_data = json.loads(llm_summary) if isinstance(llm_summary, str) else llm_summary
        parts.append(f"综合摘要：{summary_data.get('summary', '')}")
        pr = summary_data.get("priority_rules", [])
        if pr:
            parts.append("\n优先规则（必须遵循，已去冲突）：")
            for i, rule in enumerate(pr, 1):
                parts.append(f"  {i}. {rule}")
        resolutions = summary_data.get("conflict_resolutions") or []
        if resolutions:
            parts.append("\n【跨文档冲突解析】")
            for r in resolutions:
                parts.append(f"  ⚠ {r}")
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

    from app.services.prompt_segments import build_anti_dilution_cite_instruction as _build_instr

    cite_instr = _build_instr()
    return "\n".join(parts), cite_instr


def apply_anti_dilution(
    docs: list[Document],
    query: str,
) -> tuple[list[Document], str | None]:
    """对 RAG 检索结果应用防稀释处理。"""
    threshold = get_anti_dilution_threshold()
    if len(docs) <= threshold:
        return docs, None

    logger.info(
        "[智能客服-RAG|context_anti_dilution|apply|硬编执行|触发] slices=%s; threshold=%s",
        len(docs),
        threshold,
    )

    groups = _group_docs_by_source(docs)
    max_groups = get_max_doc_groups()

    if len(groups) > max_groups:
        group_scores = {
            src: max(float(d.metadata.get("score", 0)) for d in gdocs)
            for src, gdocs in groups.items()
        }
        sorted_groups = sorted(group_scores.items(), key=lambda x: x[1], reverse=True)
        selected = {src for src, _ in sorted_groups[:max_groups]}
        groups = {src: gdocs for src, gdocs in groups.items() if src in selected}

    conflicts = detect_rule_conflicts(groups)
    conflict_resolution = resolve_rule_conflicts(conflicts)

    layers = _build_layered_summary(groups, query, conflict_resolution)
    llm_summary = _generate_layer_summary_with_llm(layers, query, conflict_resolution)

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
    """构建包含防稀释上下文的 Prompt 消息。"""
    from app.services.rag_slice_utils import build_rag_llm_blocks, normalize_rag_slices_from_docs

    if not docs:
        return []

    if llm_summary:
        groups = _group_docs_by_source(docs)
        conflict_resolution = resolve_rule_conflicts(detect_rule_conflicts(groups))
        layers = _build_layered_summary(groups, query, conflict_resolution)
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

    from app.services.prompt_segments import build_rag_system_prompt, build_rag_user_prompt

    system = build_rag_system_prompt(cite_instr, include_picture_rule=True)
    user = build_rag_user_prompt(intent, hist_block, rag_context, query)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
