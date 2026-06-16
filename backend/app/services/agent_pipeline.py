"""AI 问答固定节点 Pipeline（无 LangGraph，轻量串行）。

主链路（默认）：
  意图识别（规则 + 小模型/网关大模型 Greedy JSON）
  → 问句改写 + 关键词
  → 组装 rag_query（不含硬编码术语表）

术语表映射（term_dictionary）默认关闭，需 TERM_MAPPING_ENABLED=true 且业务树形分层就绪后启用。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.intent import IntentType, get_recognizer, has_business_or_technical_signal
from app.llms import get_llm
from app.services.structured_json import (
    GREEDY_DECODE_PARAMS,
    build_repair_prompt,
    openai_json_response_format,
    parse_preprocess_output,
)
from app.services.term_dictionary import INTENT_LABELS, map_retrieval_terms

logger = logging.getLogger(__name__)


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
    pipeline_source: str = "rule"  # rule | llm | llm_gateway


def _coerce_intent(intent: str, query: str, fallback: str) -> str:
    """LLM/规则若误判 chitchat，含业务/技术信号时强制走 RAG。"""
    code = (intent or fallback or "product_consult").strip()
    if code == "chitchat" and has_business_or_technical_signal(query):
        logger.info(
            "[AI问答-Pipeline|agent_pipeline|意图纠正|硬编执行|降级] chitchat→product_consult; query=%s",
            query[:80],
        )
        return "product_consult"
    return code or fallback


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


def _resolve_retrieval_terms(
    query: str,
    keywords: list[str],
    llm_terms: list[str] | None,
) -> list[str]:
    """检索词：默认仅采纳 LLM JSON 的 retrieval_terms；硬编码术语表需显式开启。"""
    terms: list[str] = []
    for t in llm_terms or []:
        t = str(t).strip()
        if t and t not in terms:
            terms.append(t)
    if settings.TERM_MAPPING_ENABLED:
        for t in map_retrieval_terms(query, keywords):
            if t not in terms:
                terms.append(t)
    return terms[:12]


def _build_rag_query(rewritten: str, keywords: list[str], terms: list[str]) -> str:
    parts = [rewritten.strip()]
    parts.extend(keywords)
    if settings.TERM_MAPPING_ENABLED or terms:
        parts.extend(terms)
    merged = " ".join(dict.fromkeys(p for p in parts if p))
    return merged or rewritten.strip()


def _parse_preprocess_raw(raw: str) -> dict | None:
    return parse_preprocess_output(raw)


def _call_llm_with_node(node, query: str, history: list[dict], timeout: float = 10.0) -> dict | None:
    """指定节点 Greedy JSON 预处理（小模型优先路径）。"""
    import httpx

    from app.llms import _openai_chat_url
    from app.services.prompt_segments import build_preprocess_prompt

    hist = "\n".join([f"{h['role']}:{h['content'][:120]}" for h in history[-6:]])
    prompt = build_preprocess_prompt(hist, query)
    url = _openai_chat_url(node.base_url)
    greedy = GREEDY_DECODE_PARAMS
    base_payload: dict = {
        "model": node.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": greedy["temperature"],
        "top_p": greedy["top_p"],
        "max_tokens": 256,
    }

    def _post(messages: list[dict], *, with_json_mode: bool) -> httpx.Response:
        payload = dict(base_payload)
        payload["messages"] = messages
        if with_json_mode:
            payload["response_format"] = openai_json_response_format()
        return httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {node.api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    try:
        resp = _post([{"role": "user", "content": prompt}], with_json_mode=True)
        if resp.status_code >= 400:
            resp = _post([{"role": "user", "content": prompt}], with_json_mode=False)
        if resp.status_code != 200:
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        result = _parse_preprocess_raw(content)
        if result:
            node_name = getattr(node, "name", "ollama")
            logger.info("[AI问答-Pipeline|%s|Greedy JSON 预处理|硬编执行|完成] ok", node_name)
            return result
        repair_prompt = build_repair_prompt(prompt, content)
        resp2 = _post([{"role": "user", "content": repair_prompt}], with_json_mode=True)
        if resp2.status_code >= 400:
            resp2 = _post([{"role": "user", "content": repair_prompt}], with_json_mode=False)
        if resp2.status_code == 200:
            content2 = resp2.json()["choices"][0]["message"]["content"]
            result2 = _parse_preprocess_raw(content2)
            if result2:
                logger.info("[AI问答-Pipeline|本地LLM|Greedy JSON 修复重试|硬编执行|完成] ok")
                return result2
    except Exception as exc:
        logger.warning("[AI问答-Pipeline|本地LLM|降级] err=%s", str(exc)[:120])
    return None


def _call_llm_gateway_preprocess(query: str, history: list[dict]) -> dict | None:
    """网关大模型 Greedy JSON 预处理（小模型失败后的第二级）。"""
    from app.services.prompt_segments import build_preprocess_prompt

    hist = "\n".join([f"{h['role']}:{h['content'][:120]}" for h in history[-6:]])
    prompt = build_preprocess_prompt(hist, query)
    greedy = GREEDY_DECODE_PARAMS
    try:
        raw = get_llm().call(
            prompt,
            temperature=greedy["temperature"],
            max_tokens=512,
            task_type="qa",
        )
        result = _parse_preprocess_raw(raw)
        if result:
            logger.info("[AI问答-Pipeline|网关LLM|Greedy JSON 预处理|Agent执行|完成] ok")
            return result
        repair_prompt = build_repair_prompt(prompt, raw)
        raw2 = get_llm().call(
            repair_prompt,
            temperature=greedy["temperature"],
            max_tokens=512,
            task_type="qa",
        )
        result2 = _parse_preprocess_raw(raw2)
        if result2:
            logger.info("[AI问答-Pipeline|网关LLM|Greedy JSON 修复重试|Agent执行|完成] ok")
        return result2
    except Exception as exc:
        logger.warning(
            "[AI问答-Pipeline|网关LLM|预处理|Agent执行|降级] err=%s",
            str(exc)[:120],
        )
    return None


def _llm_preprocess(query: str, history: list[dict]) -> tuple[dict | None, str]:
    """三级预处理：Ollama 小模型 → 网关大模型 → 规则（返回 data, source 标签）。"""
    from app.llms import get_pipeline_llm

    pipeline_node = get_pipeline_llm()
    if pipeline_node:
        try:
            result = _call_llm_with_node(pipeline_node, query, history, timeout=3.0)
            if result:
                return result, "llm"
        except Exception:
            logger.warning("[AI问答-Pipeline|Ollama|超时/失败|降级至网关或规则]")

    if settings.PIPELINE_GATEWAY_LLM_FALLBACK:
        result = _call_llm_gateway_preprocess(query, history)
        if result:
            return result, "llm_gateway"

    return None, "rule"


def _pipeline_result_from_llm(
    q: str,
    llm_data: dict,
    rule_intent_value: str,
    *,
    source: str,
) -> PipelineResult:
    intent = _coerce_intent(
        str(llm_data.get("intent") or rule_intent_value),
        q,
        rule_intent_value,
    )
    if intent == "chitchat":
        return PipelineResult(
            original_query=q,
            intent=intent,
            intent_label=INTENT_LABELS.get(intent, intent),
            rewritten_query=q,
            pipeline_source=source,
        )
    rewritten = str(llm_data.get("rewritten_query") or q).strip()
    keywords = [str(x) for x in (llm_data.get("query_keywords") or []) if x][:8]
    if not keywords:
        keywords = _extract_keywords(q)
    llm_terms = [str(x) for x in (llm_data.get("retrieval_terms") or []) if x]
    terms = _resolve_retrieval_terms(q, keywords, llm_terms)
    rag_query = _build_rag_query(rewritten, keywords, terms)
    return PipelineResult(
        original_query=q,
        intent=intent,
        intent_label=INTENT_LABELS.get(intent, intent),
        rewritten_query=rewritten,
        query_keywords=keywords,
        retrieval_terms=terms,
        rag_query=rag_query,
        pipeline_source=source,
    )


def run_agent_pipeline(query: str, history: list[dict] | None = None) -> PipelineResult:
    """固定节点：意图识别 → 问句改写/关键词（Greedy JSON）→ 组装 rag_query。"""
    history = history or []
    q = query.strip()

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

    if rule_intent.intent == IntentType.CHITCHAT and not has_business_or_technical_signal(q):
        return PipelineResult(
            original_query=q,
            intent=rule_intent.intent.value,
            intent_label=INTENT_LABELS.get(rule_intent.intent.value, rule_intent.intent.value),
            rewritten_query=q,
            pipeline_source="rule",
        )

    llm_data, llm_source = _llm_preprocess(q, history)
    if llm_data:
        return _pipeline_result_from_llm(q, llm_data, rule_intent.intent.value, source=llm_source)

    rewritten = _rule_rewrite(q, history)
    keywords = _extract_keywords(q)
    terms = _resolve_retrieval_terms(q, keywords, None)
    rag_query = _build_rag_query(rewritten, keywords, terms)
    intent = _coerce_intent(rule_intent.intent.value, q, "product_consult")

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
