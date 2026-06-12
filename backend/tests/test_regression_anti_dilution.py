"""大规模上下文防稀释模块回归测试 (PRD 加分项5)

测试用例:
1. 文档分组逻辑
2. 优先级排序逻辑
3. 分层摘要构建
4. 关键规则提取
"""

import pytest
import sys
import os

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from langchain_core.documents import Document


def _make_doc(content: str, source: str, score: float) -> Document:
    return Document(
        page_content=content,
        metadata={"document_name": source, "score": score},
    )


class TestGroupDocsBySource:
    """TC-ANTIDILUTION-001: 文档分组"""

    def test_group_by_source(self):
        """验证按来源文档分组正确"""
        from app.services.context_anti_dilution import _group_docs_by_source

        docs = [
            _make_doc("内容A1", "文档A", 0.8),
            _make_doc("内容A2", "文档A", 0.6),
            _make_doc("内容B1", "文档B", 0.7),
        ]
        groups = _group_docs_by_source(docs)
        assert len(groups) == 2
        assert len(groups["文档A"]) == 2
        assert len(groups["文档B"]) == 1

    def test_single_doc_one_group(self):
        """单个文档应归为一组"""
        from app.services.context_anti_dilution import _group_docs_by_source

        docs = [_make_doc("单文档", "单文档.md", 0.9)]
        groups = _group_docs_by_source(docs)
        assert len(groups) == 1


class TestRankDocsByPriority:
    """TC-ANTIDILUTION-002: 优先级排序"""

    def test_rank_by_score_and_keywords(self):
        """高分+关键词匹配度高的文档应排在前面"""
        from app.services.context_anti_dilution import _rank_docs_by_priority

        query = "产品退换货政策"
        docs = [
            _make_doc("退换货政策：7天内无条件退货", "政策", 0.9),
            _make_doc("产品介绍：这是一款新产品", "介绍", 0.5),
        ]
        ranked = _rank_docs_by_priority(docs, query)
        assert ranked[0].metadata["score"] >= ranked[1].metadata["score"]

    def test_empty_docs_no_error(self):
        """空文档列表不报错"""
        from app.services.context_anti_dilution import _rank_docs_by_priority

        ranked = _rank_docs_by_priority([], "查询")
        assert ranked == []


class TestExtractKeyRules:
    """TC-ANTIDILUTION-003: 关键规则提取"""

    def test_extract_numbered_rules(self):
        """编号列表应被提取为规则"""
        from app.services.context_anti_dilution import _extract_key_rules

        text = "1. 所有商品7天内可退换\n2. 退货需保留原包装\n3. 运费由买家承担"
        rules = _extract_key_rules(text)
        assert len(rules) >= 2

    def test_extract_must_not_rules(self):
        """禁止性规则应被识别"""
        from app.services.context_anti_dilution import _extract_key_rules

        text = "不得在未授权情况下修改订单\n禁止使用虚假信息注册"
        rules = _extract_key_rules(text)
        assert len(rules) >= 1

    def test_extract_chinese_numbered_rules(self):
        """中文编号规则应被提取"""
        from app.services.context_anti_dilution import _extract_key_rules

        text = "一、退换货流程\n二、退款时效\n三、客服联系方式"
        rules = _extract_key_rules(text)
        assert len(rules) >= 2


class TestAntiDilutionThreshold:
    """TC-ANTIDILUTION-004: 阈值触发"""

    def test_below_threshold_no_trigger(self):
        """低于阈值的文档列表不触发防稀释"""
        from app.services.context_anti_dilution import apply_anti_dilution, ANTI_DILUTION_THRESHOLD

        docs = [_make_doc(f"片段{i}", f"文档{i % 3}.md", 0.5) for i in range(ANTI_DILUTION_THRESHOLD - 1)]
        result_docs, summary = apply_anti_dilution(docs, "测试查询")
        assert summary is None  # 未触发
        assert len(result_docs) == len(docs)

    def test_above_threshold_triggers(self):
        """超过阈值的文档列表应触发防稀释"""
        from app.services.context_anti_dilution import apply_anti_dilution, ANTI_DILUTION_THRESHOLD

        docs = [_make_doc(f"片段{i}", f"文档{i % 3}.md", 0.5 + 0.01 * i) for i in range(ANTI_DILUTION_THRESHOLD + 2)]
        result_docs, summary = apply_anti_dilution(docs, "测试查询")
        # 应该触发了防稀释（summary不为None 或 文档数量发生变化）
        assert summary is not None or len(result_docs) != len(docs)
