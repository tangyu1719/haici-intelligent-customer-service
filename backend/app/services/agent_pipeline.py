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
    from app.llms import get_pipeline_llm

    # 优先用 Ollama(10s超时，失败自动降级)，否则走主网关
    pipeline_node = get_pipeline_llm()
    if pipeline_node:
        try:
            result = _call_llm_with_node(pipeline_node, query, history, timeout=8.0)
            if result:
                return result
        except Exception:
            logger.warning("[AI问答-Pipeline|Ollama|超时/失败|降级至网关]")
    return _call_llm_default(query, history)


def _call_llm_with_node(node, query: str, history: list[dict], timeout: float = 10.0) -> dict | None:
    """用指定网关节点调用 LLM（短超时，失败自动降级）"""
    import httpx

    hist = "\n".join([f"{h['role']}:{h['content'][:120]}" for h in history[-6:]])
    from app.services.prompt_segments import build_preprocess_prompt
    prompt = build_preprocess_prompt(hist, query)
    url = node.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": node.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 256,
    }
    try:
        resp = httpx.post(url, json=payload, headers={
            "Authorization": f"Bearer {node.api_key}",
            "Content-Type": "application/json",
        }, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            m = _JSON_RE.search(content)
            if m:
                result = json.loads(m.group())
                if isinstance(result, dict) and result.get("rewritten_query"):
                    node_name = getattr(node, 'name', 'ollama')
                    logger.info("[AI问答-Pipeline|%s|快速预处理] ok", node_name)
                    return result
    except Exception as exc:
        logger.warning("[AI问答-Pipeline|本地LLM|降级] err=%s", str(exc)[:120])
    return None


def _call_llm_default(query: str, history: list[dict]) -> dict | None:
    """通过主网关调用 LLM"""
    llm = get_llm()
    hist = "\n".join([f"{h['role']}:{h['content'][:120]}" for h in history[-6:]])
    from app.services.prompt_segments import build_preprocess_prompt
    prompt = build_preprocess_prompt(hist, query)
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
