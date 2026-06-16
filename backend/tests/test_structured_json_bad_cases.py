"""模块1：structured_json — Greedy JSON 解析 BAD CASE 回归。

覆盖生产常见漏网：Markdown 包裹、前后缀废话、尾随逗号、非法意图、空字段、
数组/对象混用、严重损坏 JSON 等。不调用真实 LLM。
"""

from __future__ import annotations

import os
import sys

import pytest

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.services.structured_json import (
    GREEDY_DECODE_PARAMS,
    build_repair_prompt,
    extract_json_candidate,
    loads_json,
    openai_json_response_format,
    parse_follow_up_items,
    parse_intent_suggest_items,
    parse_preprocess_output,
    repair_json_text,
    strip_markdown_fence,
)


# ── 基准 GOOD CASE ──────────────────────────────────────────────

VALID_PREPROCESS = (
    '{"intent":"after_sale","rewritten_query":"如何办理退换货",'
    '"query_keywords":["退货","换货"],"retrieval_terms":["退换货政策"]}'
)


class TestGreedyDecodeParams:
    def test_temperature_zero(self):
        assert GREEDY_DECODE_PARAMS["temperature"] == 0.0
        assert GREEDY_DECODE_PARAMS["top_p"] == 1.0


class TestPreprocessGoodCases:
    def test_clean_json(self):
        out = parse_preprocess_output(VALID_PREPROCESS)
        assert out is not None
        assert out["intent"] == "after_sale"
        assert out["rewritten_query"] == "如何办理退换货"
        assert "退货" in out["query_keywords"]


# ── BAD CASE：查询预处理 JSON ───────────────────────────────────

class TestPreprocessBadCases:
    """TC-JSON-001 ~ TC-JSON-010：预处理 parse_preprocess_output"""

    def test_markdown_code_fence(self):
        raw = f"```json\n{VALID_PREPROCESS}\n```"
        out = parse_preprocess_output(raw)
        assert out is not None
        assert out["intent"] == "after_sale"

    def test_prefix_explanation_suffix(self):
        raw = f"好的，以下是分析结果：\n{VALID_PREPROCESS}\n希望对你有帮助。"
        out = parse_preprocess_output(raw)
        assert out is not None
        assert "退换货" in out["rewritten_query"]

    def test_trailing_comma_repair(self):
        raw = (
            '{"intent":"product_consult","rewritten_query":"云盒网络配置步骤",'
            '"query_keywords":["云盒"],'
            '"retrieval_terms":[],}'
        )
        out = parse_preprocess_output(raw)
        assert out is not None
        assert out["rewritten_query"] == "云盒网络配置步骤"

    def test_invalid_intent_coerced_to_product_consult(self):
        raw = (
            '{"intent":"order_logistics","rewritten_query":"查物流",'
            '"query_keywords":[],"retrieval_terms":[]}'
        )
        out = parse_preprocess_output(raw)
        assert out is not None
        assert out["intent"] == "product_consult"

    def test_empty_rewritten_query_rejected(self):
        raw = '{"intent":"after_sale","rewritten_query":"","query_keywords":[],"retrieval_terms":[]}'
        assert parse_preprocess_output(raw) is None

    def test_missing_rewritten_query_rejected(self):
        raw = '{"intent":"after_sale","query_keywords":[],"retrieval_terms":[]}'
        assert parse_preprocess_output(raw) is None

    def test_plain_text_no_json(self):
        assert parse_preprocess_output("这是普通说明文字，没有 JSON") is None

    def test_empty_string(self):
        assert parse_preprocess_output("") is None

    def test_severely_broken_json(self):
        assert parse_preprocess_output('{"intent": after_sale, rewritten') is None

    def test_json_array_instead_of_object(self):
        assert parse_preprocess_output('["退货","换货"]') is None


# ── BAD CASE：追问建议 JSON 数组 ────────────────────────────────

class TestFollowUpBadCases:
    """TC-JSON-011 ~ TC-JSON-015：追问 parse_follow_up_items"""

    def test_markdown_array(self):
        raw = '```json\n["还能退吗","运费谁承担","多久到账"]\n```'
        items = parse_follow_up_items(raw)
        assert items == ["还能退吗", "运费谁承担", "多久到账"]

    def test_prefix_noise(self):
        raw = '以下是追问建议：["第一步怎么做","第二步注意事项"]'
        items = parse_follow_up_items(raw)
        assert len(items) == 2

    def test_trailing_comma_in_array(self):
        raw = '["追问一","追问二",]'
        items = parse_follow_up_items(raw)
        assert items == ["追问一", "追问二"]

    def test_truncates_long_item_to_20_chars(self):
        raw = '["这是一句超过二十个字的中文追问建议应该被截断"]'
        items = parse_follow_up_items(raw)
        assert len(items) == 1
        assert len(items[0]) == 20

    def test_non_array_returns_empty(self):
        assert parse_follow_up_items('{"not":"array"}') == []
        assert parse_follow_up_items("随便说说") == []


# ── BAD CASE：意图纠偏 JSON 数组 ────────────────────────────────

class TestIntentSuggestBadCases:
    """TC-JSON-016 ~ TC-JSON-020：纠偏 parse_intent_suggest_items"""

    VALID_ITEM = (
        '[{"code":"after_sale","label":"售后退换货","summary":"用户在问退货流程"}]'
    )

    def test_valid_array(self):
        out = parse_intent_suggest_items(self.VALID_ITEM)
        assert len(out) == 1
        assert out[0]["code"] == "after_sale"
        assert out[0]["label"] == "售后退换货"

    def test_invalid_code_becomes_unknown(self):
        raw = '[{"code":"erp_order","label":"订单问题","summary":"问ERP"}]'
        out = parse_intent_suggest_items(raw)
        assert len(out) == 1
        assert out[0]["code"] == "unknown"

    def test_label_truncated_to_16_chars(self):
        raw = '[{"code":"complaint","label":"这是一段超过十六个字的投诉类意图标签","summary":""}]'
        out = parse_intent_suggest_items(raw)
        assert len(out[0]["label"]) == 16

    def test_skips_non_dict_elements(self):
        raw = '["无效项",{"code":"chitchat","label":"闲聊","summary":""}]'
        out = parse_intent_suggest_items(raw)
        assert len(out) == 1
        assert out[0]["code"] == "chitchat"

    def test_empty_label_skipped(self):
        raw = '[{"code":"after_sale","label":"","summary":"无理由"}]'
        out = parse_intent_suggest_items(raw)
        assert out == []


# ── 工具函数 BAD CASE ───────────────────────────────────────────

class TestJsonUtilityBadCases:
    def test_strip_markdown_fence_nested(self):
        raw = "```json\n{\"a\":1}\n```"
        assert strip_markdown_fence(raw).startswith("{")

    def test_repair_json_extracts_embedded_object(self):
        raw = "分析完成 → " + VALID_PREPROCESS + " ← 结束"
        repaired = repair_json_text(raw)
        assert "after_sale" in repaired

    def test_loads_json_object_vs_array(self):
        assert loads_json("[1,2]", kind="object") is None
        assert loads_json('{"a":1}', kind="array") is None

    def test_extract_json_candidate_none(self):
        assert extract_json_candidate("无 JSON") is None

    def test_build_repair_prompt_contains_bad_snippet(self):
        bad = '{"intent": broken'
        prompt = build_repair_prompt("原始提示", bad)
        assert "broken" in prompt
        assert "修正后的 JSON" in prompt

    def test_openai_json_response_format(self):
        assert openai_json_response_format() == {"type": "json_object"}


# ── 参数化：典型 LLM 漏网样本表 ─────────────────────────────────

@pytest.mark.parametrize(
    "raw,should_pass",
    [
        (VALID_PREPROCESS, True),
        (f"```\n{VALID_PREPROCESS}\n```", True),
        (
            '{"intent":"chitchat","rewritten_query":"你好",'
            '"query_keywords":[],"retrieval_terms":[],}',
            True,
        ),
        ('{"intent":"x","rewritten_query":""}', False),
        ("Sure! Here is the JSON:", False),
    ],
    ids=[
        "clean",
        "fence_no_lang",
        "trailing_comma_chitchat",
        "empty_rewrite",
        "no_json_at_all",
    ],
)
def test_preprocess_parametrized_bad_cases(raw: str, should_pass: bool):
    result = parse_preprocess_output(raw)
    if should_pass:
        assert result is not None
        assert result.get("rewritten_query")
    else:
        assert result is None
