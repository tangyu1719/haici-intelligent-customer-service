"""追问建议（PRD 加分项）。"""

from __future__ import annotations

import logging

from app.llms import get_llm
from app.services.structured_json import GREEDY_DECODE_PARAMS, parse_follow_up_items

logger = logging.getLogger(__name__)


def generate_follow_ups(question: str, answer: str, intent: str) -> list[str]:
    if not answer or len(answer) < 20:
        return []
    from app.services.prompt_segments import build_follow_up_prompt

    prompt = build_follow_up_prompt(intent, question, answer)
    greedy = GREEDY_DECODE_PARAMS
    try:
        raw = get_llm().call(
            prompt,
            temperature=greedy["temperature"],
            max_tokens=200,
        )
        items = parse_follow_up_items(raw)
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
