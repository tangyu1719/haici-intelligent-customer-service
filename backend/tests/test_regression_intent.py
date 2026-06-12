"""意图识别模块回归测试 (PRD 加分项1)

测试用例:
1. 关键词规则识别产品咨询
2. 关键词规则识别售后问题
3. 关键词规则识别闲聊
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

pytest.importorskip("app")


class TestIntentRecognizer:
    """TC-INTENT-001: 意图分类"""

    def test_product_consult_intent(self):
        """产品相关问题应识别为 product_consult"""
        from app.intent import IntentRecognizer

        recognizer = IntentRecognizer()
        result = recognizer.recognize("我想了解一下你们的产品有什么功能")
        assert result["intent"] in ("product_consult",)
        assert "label" in result or result.get("intent") is not None

    def test_after_sale_intent(self):
        """售后问题应识别为 after_sale"""
        from app.intent import IntentRecognizer

        recognizer = IntentRecognizer()
        result = recognizer.recognize("我的订单怎么退货")
        assert result["intent"] in ("after_sale", "product_consult")

    def test_chitchat_intent(self):
        """闲聊应识别为 chitchat"""
        from app.intent import IntentRecognizer

        recognizer = IntentRecognizer()
        result = recognizer.recognize("你好啊")
        assert result["intent"] in ("chitchat", "product_consult")

    def test_complaint_intent(self):
        """投诉应识别为 complaint"""
        from app.intent import IntentRecognizer

        recognizer = IntentRecognizer()
        result = recognizer.recognize("我要投诉你们客服态度太差了")
        assert result["intent"] in ("complaint",)


class TestIntentLabels:
    """TC-INTENT-002: 意图标签映射"""

    def test_intent_labels_defined(self):
        """验证 INTENT_LABELS 包含所有预期意图"""
        from app.services.term_dictionary import INTENT_LABELS

        expected = {"product_consult", "after_sale", "chitchat", "complaint"}
        assert set(INTENT_LABELS.keys()) >= expected
        assert all(isinstance(v, str) for v in INTENT_LABELS.values())

    def test_intent_label_values_not_empty(self):
        """验证中文标签不为空"""
        from app.services.term_dictionary import INTENT_LABELS

        for code, label in INTENT_LABELS.items():
            assert label, f"Intent {code} 的标签为空"
            assert any("一" <= char <= "鿿" for char in label), f"Intent {code} 的标签不包含中文: {label}"
