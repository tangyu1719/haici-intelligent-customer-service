"""追问建议（PRD 加分项）。"""

from __future__ import annotations

import json
import logging
import re

from app.llms import get_llm

logger = logging.getLogger(__name__)
_JSON_ARR = re.compile(r"\[[\s\S]*?\]")


def generate_follow_ups(question: str, answer: str, intent: str) -> list[str]:
    if not answer or len(answer) < 20:
        return []
    from app.services.prompt_segments import build_follow_up_prompt
    prompt = build_follow_up_prompt(intent, question, answer)
    try:
        raw = get_llm().call(prompt, temperature=0.3, max_tokens=200)
        m = _JSON_ARR.search(raw)
        if not m:
            return []
        arr = json.loads(m.group())
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()][:3]
    except Exception as exc:
        logger.warning("[AI问答-对话|follow_up|追问建议|Agent执行|跳过] err=%s", str(exc)[:80])
    return []
