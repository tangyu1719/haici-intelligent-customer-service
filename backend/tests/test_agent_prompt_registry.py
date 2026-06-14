"""Agent Prompt 注册表与多模态模板回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.agent_prompt_registry import (  # noqa: E402
    AGENT_CATALOG,
    describe_agent_for_image_type,
    extract_prompt_body,
    load_agent_prompt,
    load_agent_routing,
    render_agent_prompt,
)


def test_multimodal_agent_templates_exist():
    for key in (
        "image_type_classifier_agent",
        "image_describe_ui_menu_agent",
        "image_ocr_llm_enrich_agent",
    ):
        text = load_agent_prompt(key)
        assert text.strip(), f"缺少模板: {key}"
        assert "## Prompt" in text or "{" in text


def test_render_replaces_variables():
    rendered = render_agent_prompt(
        "image_type_classifier_agent",
        doc_context="售后政策章节",
        image_id="img_0001",
        file_name="shot.png",
    )
    assert "售后政策章节" in rendered
    assert "img_0001" in rendered
    assert "{doc_context}" not in rendered


def test_extract_prompt_body():
    md = load_agent_prompt("image_describe_general_agent")
    body = extract_prompt_body(md)
    assert body
    assert "文档插图" in body or "描述" in body


def test_describe_agent_routing_by_type():
    assert describe_agent_for_image_type("ui_menu") == "image_describe_ui_menu_agent"
    assert describe_agent_for_image_type("flowchart") == "image_describe_flowchart_agent"
    assert describe_agent_for_image_type("unknown") == "image_describe_general_agent"


def test_agent_routing_has_catalog_defaults():
    rules = load_agent_routing()
    for key in AGENT_CATALOG:
        assert key in rules
        assert "mode" in rules[key]


def test_ocr_enrich_template_has_ocr_placeholder():
    tpl = load_agent_prompt("image_ocr_llm_enrich_agent")
    assert "{ocr_text}" in tpl
    out = render_agent_prompt(
        "image_ocr_llm_enrich_agent",
        ocr_text="菜单：设置-账户",
        doc_context="用户手册",
        image_type="ui_menu",
        title_hint="设置页",
        vlm_draft="",
    )
    assert "菜单：设置-账户" in out
