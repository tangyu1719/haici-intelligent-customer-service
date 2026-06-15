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
    "你好": "您好，我是 HaiCi 智能客服助手，请问有什么可以帮您？",
    "您好": "您好，我是 HaiCi 智能客服助手，请问有什么可以帮您？",
    "你是谁": "我是 HaiCi 智能客服助手，可以帮您解答产品咨询、售后政策等问题。",
    "谢谢": "不客气，还有其他问题随时问我。",
    "再见": "再见，祝您生活愉快！",
    "你怎么了": "我一切正常，随时为您服务。请问有什么可以帮您？",
    "你还好吗": "我一切正常，随时为您服务。请问有什么可以帮您？",
    "在吗": "在的，我是 HaiCi 智能客服助手，请问有什么可以帮您？",
}


PRODUCT_KEYWORDS = ("产品", "功能", "参数", "价格", "规格", "介绍", "怎么用", "能力", "哪些", "提供")
AFTER_SALE_KEYWORDS = ("退货", "退款", "换货", "保修", "售后", "运费", "包邮", "配送")
COMPLAINT_KEYWORDS = ("投诉", "差评", "不满意", "太慢", "举报")
CHITCHAT_KEYWORDS = ("你好", "您好", "在吗", "谢谢", "再见", "你是谁", "怎么了", "干嘛", "没事", "哈喽", "嗨")
# 情感/社交类短句，规则直出闲聊，避免走 LLM 预处理
CHITCHAT_SOCIAL_KEYWORDS = (
    "夸", "赞", "厉害", "棒", "感觉", "交流", "聊天", "陪我", "喜欢", "深入",
    "不错", "哈哈", "呵呵", "有趣", "开心", "无聊", "孤单", "想你", "陪我聊",
)


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    faq_answer: str = ""


class IntentRecognizer:
    def _has_business_signal(self, text: str) -> bool:
        return any(
            k in text
            for k in (*PRODUCT_KEYWORDS, *AFTER_SALE_KEYWORDS, *COMPLAINT_KEYWORDS)
        )

    def _is_social_chitchat(self, text: str) -> bool:
        if any(k in text for k in CHITCHAT_SOCIAL_KEYWORDS):
            return True
        # 极短口语句（≤20 字、无业务词、带语气/人称）
        if len(text) <= 20 and not self._has_business_signal(text):
            if any(x in text for x in ("我", "你", "吗", "呢", "啊", "呀", "吧", "？", "?")):
                return True
        return False

    def _rule_classify(self, query: str) -> Optional[IntentResult]:
        text = query.strip()
        norm = re.sub(r"[？?！!。.\s]+", "", text)
        lower = text.lower()
        if text in FAQ_ANSWERS or norm in FAQ_ANSWERS:
            ans = FAQ_ANSWERS.get(text) or FAQ_ANSWERS.get(norm, "")
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.99, faq_answer=ans)
        for key, ans in FAQ_ANSWERS.items():
            if key in text or key in norm:
                return IntentResult(intent=IntentType.CHITCHAT, confidence=0.95, faq_answer=ans)
        if any(k in text for k in COMPLAINT_KEYWORDS):
            return IntentResult(intent=IntentType.COMPLAINT, confidence=0.9)
        if any(k in text for k in AFTER_SALE_KEYWORDS):
            return IntentResult(intent=IntentType.AFTER_SALE, confidence=0.85)
        if any(k in text for k in PRODUCT_KEYWORDS):
            return IntentResult(intent=IntentType.PRODUCT, confidence=0.85)
        # 短句闲聊：问候/状态确认等，不走 LLM 预处理
        if len(text) <= 16 and any(k in lower or k in text for k in CHITCHAT_KEYWORDS):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.8)
        if self._is_social_chitchat(text):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.78)
        return None

    def recognize(self, query: str, has_image: bool = False) -> IntentResult:
        rule = self._rule_classify(query)
        if rule:
            return rule
        if self._is_social_chitchat(query.strip()):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.72)
        return IntentResult(intent=IntentType.PRODUCT, confidence=0.6)


_recognizer: Optional[IntentRecognizer] = None


def get_recognizer() -> IntentRecognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = IntentRecognizer()
        logger.info("[智能客服-对话|intent|规则引擎|硬编执行|初始化] 仅规则模式，无本地小模型")
    return _recognizer
