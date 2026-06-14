"""AI 问答固定节点 Pipeline（无 LangGraph，轻量串行）。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.intent import IntentType, get_recognizer
from app.llms import get_llm
from app.services.term_dictionary import INTENT_LABELS, map_retrieval_terms

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{[\s\S]*\}")


@dataclass
class PipelineResult:
    original_query: str
    intent: str
    intent_label: str
    rewritten_query: str
    query_keywords: list[str] = field(default_factory=list)
    retrieval_terms: list[str] = field(default_factory=list)
    rag_query: str = ""
    faq_answer: str = ""
    pipeline_source: str = "rule"  # rule | llm


def _extract_keywords(text: str) -> list[str]:
    q = (text or "").strip()
    keywords: list[str] = []
    for marker in ("退货", "退款", "换货", "保修", "产品", "价格", "功能", "投诉", "配送", "FAQ", "政策"):
        if marker in q and marker not in keywords:
            keywords.append(marker)
    for token in re.split(r"[\s，。；;、/?？]+", q):
        token = token.strip()
        if 2 <= len(token) <= 24 and token not in keywords:
            keywords.append(token)
    return keywords[:8]


def _rule_rewrite(query: str, history: list[dict]) -> str:
    q = query.strip()
    if any(p in q for p in ("这个", "那个", "刚才", "上面", "它")) and history:
        for h in reversed(history):
            if h.get("role") == "user" and h.get("content"):
                return f"{h['content'][:80]}；追问：{q}"
    return q


def _llm_preprocess(query: str, history: list[dict]) -> dict | None:
    llm = get_llm()
    hist = "\n".join([f"{h['role']}:{h['content'][:120]}" for h in history[-6:]])
    prompt = (
        "你是企业智能客服的查询预处理模块。根据用户问题输出 JSON，字段：\n"
        'intent 取值 product_consult|after_sale|chitchat|complaint；'
        "rewritten_query 为利于知识库检索的改写问句；"
        "query_keywords 为原问实体/关键词数组；"
        "retrieval_terms 为映射后的内部业务检索词数组。\n"
        "只输出 JSON，不要解释。\n"
        f"历史:\n{hist or '无'}\n\n问题:{query}"
    )
    try:
        raw = llm.call(prompt, temperature=0.1, max_tokens=512)
        m = _JSON_RE.search(raw)
        if not m:
            return None
        data = json.loads(m.group())
        if isinstance(data, dict) and data.get("rewritten_query"):
            return data
    except Exception as exc:
        logger.warning("[AI问答-Pipeline|agent_pipeline|LLM预处理|Agent执行|降级] err=%s", str(exc)[:120])
    return None


def run_agent_pipeline(query: str, history: list[dict] | None = None) -> PipelineResult:
    """固定节点：意图识别 → Query 改写 → 关键词提取 → 术语映射 → 组装 RAG 检索词。"""
    history = history or []
    q = query.strip()

    # 节点1：意图识别（规则优先，FAQ 直出）
    rule_intent = get_recognizer().recognize(q)
    if rule_intent.faq_answer:
        return PipelineResult(
            original_query=q,
            intent=rule_intent.intent.value,
            intent_label=INTENT_LABELS.get(rule_intent.intent.value, rule_intent.intent.value),
            rewritten_query=q,
            faq_answer=rule_intent.faq_answer,
            pipeline_source="rule",
        )

    # 闲聊不走 LLM 预处理，避免阻塞首 token
    if rule_intent.intent == IntentType.CHITCHAT:
        return PipelineResult(
            original_query=q,
            intent=rule_intent.intent.value,
            intent_label=INTENT_LABELS.get(rule_intent.intent.value, rule_intent.intent.value),
            rewritten_query=q,
            pipeline_source="rule",
        )

    llm_data = _llm_preprocess(q, history)
    if llm_data:
        intent = str(llm_data.get("intent") or rule_intent.intent.value)
        rewritten = str(llm_data.get("rewritten_query") or q).strip()
        keywords = [str(x) for x in (llm_data.get("query_keywords") or []) if x][:8]
        terms = [str(x) for x in (llm_data.get("retrieval_terms") or []) if x][:12]
        if not keywords:
            keywords = _extract_keywords(q)
        if not terms:
            terms = map_retrieval_terms(q, keywords)
        rag_query = " ".join(dict.fromkeys([rewritten, *keywords, *terms]))
        return PipelineResult(
            original_query=q,
            intent=intent,
            intent_label=INTENT_LABELS.get(intent, intent),
            rewritten_query=rewritten,
            query_keywords=keywords,
            retrieval_terms=terms,
            rag_query=rag_query,
            pipeline_source="llm",
        )

    # 规则降级链路
    rewritten = _rule_rewrite(q, history)
    keywords = _extract_keywords(q)
    terms = map_retrieval_terms(q, keywords)
    rag_query = " ".join(dict.fromkeys([rewritten, *keywords, *terms]))
    intent = rule_intent.intent.value

    return PipelineResult(
        original_query=q,
        intent=intent,
        intent_label=INTENT_LABELS.get(intent, intent),
        rewritten_query=rewritten,
        query_keywords=keywords,
        retrieval_terms=terms,
        rag_query=rag_query or q,
        pipeline_source="rule",
    )
