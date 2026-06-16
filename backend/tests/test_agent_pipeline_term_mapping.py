"""AgentPipeline 术语表开关与 rag_query 组装回归。"""

from __future__ import annotations

import os
import sys

import pytest

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.config import settings
from app.services import agent_pipeline as ap


class TestResolveRetrievalTerms:
    def test_default_no_dictionary_mapping(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", False)
        terms = ap._resolve_retrieval_terms("显卡怎么配", ["显卡"], None)
        assert terms == []
        assert "图形处理器" not in terms

    def test_llm_terms_kept_when_mapping_off(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", False)
        terms = ap._resolve_retrieval_terms("显卡", ["显卡"], ["图形处理器"])
        assert terms == ["图形处理器"]

    def test_dictionary_merged_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", True)
        terms = ap._resolve_retrieval_terms("显卡问题", ["显卡"], [])
        assert "图形处理器" in terms


class TestBuildRagQuery:
    def test_default_excludes_empty_terms(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", False)
        q = ap._build_rag_query("云盒网络配置", ["云盒", "网络"], [])
        assert "云盒" in q
        assert "网络" in q
        assert "图形处理器" not in q

    def test_includes_llm_terms_without_dictionary(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", False)
        q = ap._build_rag_query("退货流程", ["退货"], ["退换货政策"])
        assert "退换货政策" in q


class TestRunAgentPipelineRuleFallback:
    def test_rule_path_no_dictionary_terms(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", False)
        monkeypatch.setattr(ap, "_llm_preprocess", lambda q, h: (None, "rule"))
        result = ap.run_agent_pipeline("显卡驱动怎么装")
        assert result.pipeline_source == "rule"
        assert "图形处理器" not in result.rag_query
        assert "显卡" in result.rag_query

    def test_rule_path_with_dictionary_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TERM_MAPPING_ENABLED", True)
        monkeypatch.setattr(ap, "_llm_preprocess", lambda q, h: (None, "rule"))
        result = ap.run_agent_pipeline("显卡驱动怎么装")
        assert "图形处理器" in result.rag_query
