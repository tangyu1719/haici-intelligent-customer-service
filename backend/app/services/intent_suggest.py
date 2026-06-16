"""意图纠偏：术语表备选 + 检索词提示 + LLM 推测（真实调用）。"""
from __future__ import annotations

import logging

from app.config import settings
from app.llms import get_llm
from app.services.structured_json import GREEDY_DECODE_PARAMS, parse_intent_suggest_items
from app.services.term_dictionary import INTENT_LABELS, map_retrieval_terms

logger = logging.getLogger(__name__)


def build_builtin_alternatives(detected_intent: str) -> list[dict]:
    """内置意图术语表（排除当前识别结果）。"""
    code = (detected_intent or "").strip()
    out: list[dict] = []
    for k, label in INTENT_LABELS.items():
        if k == code:
            continue
        out.append({"code": k, "label": label, "source": "builtin"})
    return out


def build_term_hints(question: str, retrieval_terms: list[str] | None = None) -> list[str]:
    """术语/检索词提示（意图纠偏侧栏，非主链路检索）。"""
    raw_terms: list[str] = list(retrieval_terms or [])
    if settings.TERM_MAPPING_ENABLED:
        for t in map_retrieval_terms(question):
            if t not in raw_terms:
                raw_terms.append(t)
    seen: set[str] = set()
    hints: list[str] = []
    for t in raw_terms:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            hints.append(t)
    return hints[:8]


def suggest_intents_llm(
    question: str,
    answer: str,
    detected_intent: str,
    detected_label: str,
) -> list[dict]:
    """大模型推测 1～2 个更贴切意图（Greedy JSON + Pydantic 校验）。"""
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or len(a) < 10:
        return []
    from app.services.prompt_segments import build_intent_suggest_prompt

    enum_text = "、".join(f"{k}={v}" for k, v in INTENT_LABELS.items())
    prompt = build_intent_suggest_prompt(q, a, detected_intent, detected_label, enum_text)
    greedy = GREEDY_DECODE_PARAMS
    try:
        raw = get_llm().call(prompt, temperature=greedy["temperature"], max_tokens=256)
        parsed = parse_intent_suggest_items(raw)
        out: list[dict] = []
        for item in parsed:
            code = item.get("code", "unknown")
            label = item.get("label") or ""
            summary = item.get("summary") or ""
            if not label:
                continue
            if code in INTENT_LABELS:
                label = INTENT_LABELS[code]
            out.append(
                {
                    "code": code,
                    "label": label,
                    "summary": summary,
                    "source": "llm",
                }
            )
        return out
    except Exception as exc:
        logger.warning(
            "[AI问答-意图纠偏|intent_suggest|LLM推测|Agent执行|跳过] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:120],
        )
        return []


def build_intent_alternatives(
    *,
    question: str,
    answer: str,
    detected_intent: str,
    detected_label: str,
    retrieval_terms: list[str] | None = None,
    include_llm: bool = True,
) -> dict:
    builtin = build_builtin_alternatives(detected_intent)
    term_hints = build_term_hints(question, retrieval_terms)
    suggested = suggest_intents_llm(question, answer, detected_intent, detected_label) if include_llm else []
    shown: list[str] = []
    for b in builtin:
        shown.append(f"builtin:{b['code']}")
    for s in suggested:
        shown.append(f"llm:{s.get('code')}:{s.get('label')}")
    for h in term_hints:
        shown.append(f"term:{h}")
    return {
        "detected_intent": detected_intent,
        "detected_intent_label": detected_label,
        "builtin": builtin,
        "suggested": suggested,
        "term_hints": term_hints,
        "intent_suggestions_shown": shown,
        "llm_powered": bool(suggested),
    }
