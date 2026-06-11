"""规则引擎意图识别（减重：不加载本地 1.5B 模型）。"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class IntentType(Enum):
    PRODUCT = "product_consult"
    AFTER_SALE = "after_sale"
    CHITCHAT = "chitchat"
    COMPLAINT = "complaint"


FAQ_ANSWERS = {
    "你好": "您好，我是智能客服助手，请问有什么可以帮您？",
    "您好": "您好，我是智能客服助手，请问有什么可以帮您？",
    "谢谢": "不客气，还有其他问题随时问我。",
    "再见": "再见，祝您生活愉快！",
}


PRODUCT_KEYWORDS = ("产品", "功能", "参数", "价格", "规格", "介绍", "怎么用")
AFTER_SALE_KEYWORDS = ("退货", "退款", "换货", "保修", "售后", "运费", "包邮", "配送")
COMPLAINT_KEYWORDS = ("投诉", "差评", "不满意", "太慢", "举报")
CHITCHAT_KEYWORDS = ("你好", "您好", "在吗", "谢谢", "再见", "你是谁")


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    faq_answer: str = ""


class IntentRecognizer:
    def _rule_classify(self, query: str) -> Optional[IntentResult]:
        text = query.strip()
        lower = text.lower()
        if text in FAQ_ANSWERS:
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.99, faq_answer=FAQ_ANSWERS[text])
        if any(k in text for k in COMPLAINT_KEYWORDS):
            return IntentResult(intent=IntentType.COMPLAINT, confidence=0.9)
        if any(k in text for k in AFTER_SALE_KEYWORDS):
            return IntentResult(intent=IntentType.AFTER_SALE, confidence=0.85)
        if any(k in text for k in PRODUCT_KEYWORDS):
            return IntentResult(intent=IntentType.PRODUCT, confidence=0.85)
        if len(text) <= 12 and any(k in lower or k in text for k in CHITCHAT_KEYWORDS):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.8)
        return None

    def recognize(self, query: str, has_image: bool = False) -> IntentResult:
        rule = self._rule_classify(query)
        if rule:
            return rule
        return IntentResult(intent=IntentType.PRODUCT, confidence=0.6)


_recognizer: Optional[IntentRecognizer] = None


def get_recognizer() -> IntentRecognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = IntentRecognizer()
        logger.info("[智能客服-对话|intent|规则引擎|硬编执行|初始化] 仅规则模式，无本地小模型")
    return _recognizer
