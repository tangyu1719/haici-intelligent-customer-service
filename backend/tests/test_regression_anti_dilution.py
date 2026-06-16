"""大规模上下文防稀释 + 梯度检索 + ReAct 回归测试。"""

import os
import sys

import pytest

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from langchain_core.documents import Document


def _make_doc(content: str, source: str, score: float, **meta) -> Document:
    m = {"document_name": source, "score": score}
    m.update(meta)
    return Document(page_content=content, metadata=m)


class TestGroupDocsBySource:
    def test_group_by_source(self):
        from app.services.context_anti_dilution import _group_docs_by_source

        docs = [
            _make_doc("内容A1", "文档A", 0.8),
            _make_doc("内容A2", "文档A", 0.6),
            _make_doc("内容B1", "文档B", 0.7),
        ]
        groups = _group_docs_by_source(docs)
        assert len(groups) == 2
        assert len(groups["文档A"]) == 2


class TestRankDocsByPriority:
    def test_rank_by_score_and_keywords(self):
        from app.services.context_anti_dilution import _rank_docs_by_priority

        query = "产品退换货政策"
        docs = [
            _make_doc("退换货政策：7天内无条件退货", "政策", 0.9),
            _make_doc("产品介绍：这是一款新产品", "介绍", 0.5),
        ]
        ranked = _rank_docs_by_priority(docs, query)
        assert ranked[0].metadata["score"] >= ranked[1].metadata["score"]


class TestExtractKeyRules:
    def test_extract_numbered_rules(self):
        from app.services.context_anti_dilution import _extract_key_rules

        text = "1. 所有商品7天内可退换\n2. 退货需保留原包装"
        rules = _extract_key_rules(text)
        assert len(rules) >= 2

    def test_extract_must_not_rules(self):
        from app.services.context_anti_dilution import _extract_key_rules

        text = "不得在未授权情况下修改订单\n禁止使用虚假信息注册"
        rules = _extract_key_rules(text)
        assert len(rules) >= 1


class TestRuleConflictDetection:
    def test_polarity_conflict_detected(self):
        from app.services.context_anti_dilution import detect_rule_conflicts, resolve_rule_conflicts

        groups = {
            "旧版政策2023": [_make_doc("必须7天内退货", "旧版政策2023", 0.7)],
            "新版政策2025": [_make_doc("不得7天内无理由退货", "新版政策2025", 0.85)],
        }
        conflicts = detect_rule_conflicts(groups)
        assert len(conflicts) >= 1
        resolution = resolve_rule_conflicts(conflicts)
        assert resolution["has_conflicts"] is True
        assert resolution["unified_rules"]

    def test_numeric_conflict_detected(self):
        from app.services.context_anti_dilution import detect_rule_conflicts

        groups = {
            "文档A": [_make_doc("1. 保修期15天", "文档A", 0.6)],
            "文档B": [_make_doc("1. 保修期7天", "文档B", 0.8)],
        }
        conflicts = detect_rule_conflicts(groups)
        assert any(c["type"] == "numeric_conflict" for c in conflicts)


class TestAntiDilutionThreshold:
    def test_below_threshold_no_trigger(self):
        from app.services.context_anti_dilution import apply_anti_dilution, get_anti_dilution_threshold

        threshold = get_anti_dilution_threshold()
        docs = [_make_doc(f"片段{i}", f"文档{i % 3}.md", 0.5) for i in range(threshold - 1)]
        result_docs, summary = apply_anti_dilution(docs, "测试查询")
        assert summary is None
        assert len(result_docs) == len(docs)

    def test_above_threshold_triggers(self, monkeypatch):
        from app.services.context_anti_dilution import apply_anti_dilution, get_anti_dilution_threshold
        from app.services import context_anti_dilution as cad

        monkeypatch.setattr(
            cad,
            "_generate_layer_summary_with_llm",
            lambda layers, query, cr=None: '{"summary":"t","priority_rules":["r1"],"confidence":70}',
        )

        threshold = get_anti_dilution_threshold()
        docs = [_make_doc(f"片段{i}", f"文档{i % 3}.md", 0.5 + 0.01 * i) for i in range(threshold + 2)]
        result_docs, summary = apply_anti_dilution(docs, "测试查询")
        assert summary is not None


class TestGradientFilter:
    def test_pool_ceiling_smart_mode(self):
        from app.services.rag_gradient_filter import parse_gradient_k, pool_size_ceiling

        tiers = parse_gradient_k()
        assert pool_size_ceiling(100, tiers) == tiers[0]

    def test_pool_ceiling_hard_mode(self, monkeypatch):
        from app.services import system_settings as ss
        from app.services.rag_gradient_filter import pool_size_ceiling

        monkeypatch.setattr(ss, "load_system_settings", lambda: {
            "session_active_persist_interval_minutes": 10,
            "rag_pool_ceiling_mode": "hard",
            "rag_pool_ceiling_map": "100:10,50:5,20:3",
        })
        assert pool_size_ceiling(100) == 10
        assert pool_size_ceiling(50) == 5
        assert pool_size_ceiling(25) == 3
        assert pool_size_ceiling(5) == 3

    def test_parse_pool_ceiling_map(self):
        from app.services.system_settings import parse_pool_ceiling_map

        pairs = parse_pool_ceiling_map("100:10,50:5,20:3")
        assert pairs[0] == (100, 10)
        assert pairs[-1] == (20, 3)

    def test_adaptive_high_quality_keeps_ceiling(self):
        from app.services.rag_gradient_filter import adaptive_gradient_topk

        docs = [_make_doc(f"c{i}", f"d{i}.md", 0.92 - i * 0.01) for i in range(80)]
        out, meta = adaptive_gradient_topk(docs, coarse_count=100)
        assert meta["quality"] == "high"
        assert meta["final_k"] == meta["ceiling"]
        assert len(out) == meta["final_k"]

    def test_adaptive_smaller_pool_lower_ceiling(self):
        from app.services.rag_gradient_filter import adaptive_gradient_topk, pool_size_ceiling, parse_gradient_k

        tiers = parse_gradient_k()
        ceiling_50 = pool_size_ceiling(50, tiers)
        docs = [_make_doc(f"c{i}", f"d{i}.md", 0.88 - i * 0.005) for i in range(45)]
        out, meta = adaptive_gradient_topk(docs, coarse_count=50)
        assert meta["ceiling"] == ceiling_50
        assert len(out) <= ceiling_50

    def test_gap_truncates_tail(self):
        from app.services.rag_gradient_filter import adaptive_gradient_topk

        docs = [
            _make_doc("high1", "a", 0.95),
            _make_doc("high2", "b", 0.90),
            _make_doc("low1", "c", 0.35),
            _make_doc("low2", "d", 0.30),
        ]
        out, meta = adaptive_gradient_topk(docs, coarse_count=80)
        assert len(out) <= 3
        assert out[0].metadata["score"] >= 0.88


class TestHybridScorer:
    def test_bm25_boosts_keyword_match(self):
        from app.services.rag_hybrid_scorer import hybrid_rescore

        docs = [
            _make_doc("产品介绍", "a", 0.6),
            _make_doc("退换货政策：7天内可退", "b", 0.58),
        ]
        ranked = hybrid_rescore("退换货政策", docs)
        assert "bm25_score" in ranked[0].metadata
        assert ranked[0].page_content.startswith("退换货")


class TestRagTool:
    def test_rag_tool_schema(self):
        from app.services.rag_tool import RAG_SEARCH_TOOL

        assert RAG_SEARCH_TOOL["function"]["name"] == "rag_search"

    def test_format_observe_empty(self):
        from app.services.rag_tool import format_observe_text

        text = format_observe_text({"summary": "无结果", "citations": []})
        assert "观察" in text


class TestReactComplexity:
    def test_complex_query_detected(self):
        from app.services.react_agent import is_complex_query

        assert is_complex_query("请分别说明退换货政策和配送流程，以及两者的区别？") is True
        assert is_complex_query("你好") is False

    def test_tool_definitions(self):
        from app.services.react_agent import get_rag_tool_definitions

        tools = get_rag_tool_definitions()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "rag_search"
