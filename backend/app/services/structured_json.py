"""大模型结构化 JSON 输出：Greedy 解码 + 模板绑定 + 分层校验 + 轻量修复。

适用场景：查询预处理、追问建议、意图纠偏、防稀释摘要等需机器可读 JSON 的分支。
主问答流式正文仍走自然语言 + 句末引用编号 [1][2]，不在此模块处理。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# Greedy 解码：temperature=0、top_p=1，关闭采样随机性，提高 JSON 格式稳定性
GREEDY_DECODE_PARAMS: dict[str, float] = {"temperature": 0.0, "top_p": 1.0}

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")

_VALID_INTENTS = frozenset({"product_consult", "after_sale", "chitchat", "complaint"})


class PreprocessJsonOutput(BaseModel):
    """查询预处理 JSON Schema（Pydantic 语义校验）。"""

    intent: str = "product_consult"
    rewritten_query: str
    query_keywords: list[str] = Field(default_factory=list)
    retrieval_terms: list[str] = Field(default_factory=list)

    @field_validator("intent")
    @classmethod
    def _intent_enum(cls, v: str) -> str:
        code = (v or "product_consult").strip()
        return code if code in _VALID_INTENTS else "product_consult"

    @field_validator("rewritten_query")
    @classmethod
    def _rewrite_nonempty(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("rewritten_query 不能为空")
        return text


class IntentSuggestItem(BaseModel):
    """意图纠偏单项。"""

    code: str
    label: str
    summary: str = ""

    @field_validator("code")
    @classmethod
    def _code_enum(cls, v: str) -> str:
        code = (v or "unknown").strip()
        if code not in _VALID_INTENTS and code != "unknown":
            return "unknown"
        return code

    @field_validator("label")
    @classmethod
    def _label_trim(cls, v: str) -> str:
        text = (v or "").strip()[:16]
        if not text:
            raise ValueError("label 不能为空")
        return text


T = TypeVar("T", bound=BaseModel)


def strip_markdown_fence(text: str) -> str:
    """去掉 ```json ... ``` 代码块包裹。"""
    raw = (text or "").strip()
    if "```" not in raw:
        return raw
    for block in raw.split("```"):
        block = block.strip()
        if block.lower().startswith("json"):
            block = block[4:].strip()
        if block.startswith("{") or block.startswith("["):
            return block
    return raw


def repair_json_text(text: str) -> str:
    """轻量 JSON 语法修复（尾随逗号、单引号键名等），不引入第三方 json-repair。"""
    s = strip_markdown_fence(text).strip()
    # 去掉 JSON 前后的解释性文字（保留首个 { 或 [ 至末个 } 或 ]）
    if s.startswith("{") or s.startswith("["):
        pass
    else:
        mobj = _JSON_OBJECT_RE.search(s) or _JSON_ARRAY_RE.search(s)
        if mobj:
            s = mobj.group()
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = s.replace("'", '"')
    return s


def extract_json_candidate(raw: str, *, kind: Literal["object", "array"] = "object") -> str | None:
    """从模型原文中提取 JSON 候选串。"""
    text = strip_markdown_fence(raw)
    if not text:
        return None
    if kind == "object":
        if text.startswith("{"):
            return text
        m = _JSON_OBJECT_RE.search(text)
        return m.group() if m else None
    if text.startswith("["):
        return text
    m = _JSON_ARRAY_RE.search(text)
    return m.group() if m else None


def loads_json(raw: str, *, kind: Literal["object", "array"] = "object") -> Any | None:
    """语法层：json.loads + 轻量修复。"""
    candidate = extract_json_candidate(raw, kind=kind)
    if not candidate:
        return None
    for attempt_text in (candidate, repair_json_text(candidate)):
        try:
            return json.loads(attempt_text)
        except json.JSONDecodeError:
            continue
    return None


def validate_model(data: Any, model: type[T]) -> T | None:
    """语义层：Pydantic Schema 校验。"""
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        logger.warning(
            "[AI问答-结构化JSON|structured_json|Schema校验|硬编执行|失败] model=%s; error=%s",
            model.__name__,
            str(exc)[:200],
        )
        return None


def parse_preprocess_output(raw: str) -> dict | None:
    """解析并校验查询预处理 JSON。"""
    data = loads_json(raw, kind="object")
    if not isinstance(data, dict):
        return None
    validated = validate_model(data, PreprocessJsonOutput)
    return validated.model_dump() if validated else None


def parse_follow_up_items(raw: str, *, max_items: int = 3, max_len: int = 20) -> list[str]:
    """解析追问建议 JSON 数组。"""
    data = loads_json(raw, kind="array")
    if not isinstance(data, list):
        return []
    items: list[str] = []
    for x in data:
        text = str(x).strip()
        if not text:
            continue
        items.append(text[:max_len])
        if len(items) >= max_items:
            break
    return items


def parse_intent_suggest_items(raw: str, *, max_items: int = 2) -> list[dict]:
    """解析意图纠偏 JSON 数组。"""
    data = loads_json(raw, kind="array")
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data[:max_items]:
        if not isinstance(item, dict):
            continue
        validated = validate_model(item, IntentSuggestItem)
        if validated:
            out.append(validated.model_dump())
    return out


def build_repair_prompt(original_prompt: str, bad_output: str) -> str:
    """二次修正提示：把错误 JSON 回灌，让模型自行修复（深度优化路径）。"""
    snippet = (bad_output or "")[:800]
    return (
        f"{original_prompt}\n\n"
        "你上一次输出不是合法 JSON 或字段不合规。请仅输出修正后的 JSON，不要解释。\n"
        f"错误输出片段：\n{snippet}"
    )


def openai_json_response_format() -> dict[str, Any]:
    """OpenAI 兼容接口：强制 JSON 对象输出（网关支持时启用）。"""
    return {"type": "json_object"}
