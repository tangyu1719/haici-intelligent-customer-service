"""追问建议（PRD 加分项）。"""

from __future__ import annotations

import json
import logging
import re

from app.llms import get_llm

logger = logging.getLogger(__name__)
_JSON_ARR = re.compile(r"\[[\s\S]*\]")


def _parse_follow_up_items(raw: str) -> list[str]:
    """从 LLM 输出中提取追问 JSON 数组（兼容 markdown 代码块）。"""
    text = (raw or "").strip()
    if not text or text.startswith("【配置错误】") or text.startswith("服务暂时不可用"):
        return []
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            if block.startswith("["):
                text = block
                break
    candidates = [text]
    m = _JSON_ARR.search(text)
    if m:
        candidates.append(m.group())
    for candidate in candidates:
        try:
            arr = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(arr, list):
            items = [str(x).strip() for x in arr if str(x).strip()]
            if items:
                return items[:3]
    return []


def generate_follow_ups(question: str, answer: str, intent: str) -> list[str]:
    if not answer or len(answer) < 20:
        return []
    from app.services.prompt_segments import build_follow_up_prompt

    prompt = build_follow_up_prompt(intent, question, answer)
    try:
        raw = get_llm().call(prompt, temperature=0.3, max_tokens=200)
        items = _parse_follow_up_items(raw)
        if items:
            logger.info(
                "[AI问答-对话|follow_up|追问建议|Agent执行|完成] count=%s; intent=%s",
                len(items),
                intent,
            )
            return items
        logger.warning(
            "[AI问答-对话|follow_up|追问建议|Agent执行|空结果] intent=%s; raw_len=%s",
            intent,
            len(raw or ""),
        )
    except Exception as exc:
        logger.warning(
            "[AI问答-对话|follow_up|追问建议|Agent执行|跳过] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:80],
        )
    return []
