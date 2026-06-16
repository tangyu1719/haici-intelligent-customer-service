"""规则引擎意图识别（减重：不加载本地 1.5B 模型）。

闲聊 (chitchat) 定义：
- 仅用于纯寒暄/致谢/告别等「简单会话」，走一次性 LLM 或 FAQ 直出，**不调用 RAG**。
- 范围极窄：只有规则层或小模型**明确判定**为闲聊时才标 chitchat。
- 凡涉及技术、业务、产品、故障、编号、操作等问题，一律**不得**标 chitchat（即使知识库暂无答案）。
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# 业务/技术编号：61K69、OD20240115001、P001 等
_BUSINESS_CODE_RE = re.compile(
    r"(?<![\u4e00-\u9fff])"
    r"[A-Za-z]{1,4}\d{2,}[A-Za-z0-9\-_]*"
    r"|\b[A-Z]{2,}\d{6,}\b"
    r"|\b[A-Za-z0-9]{4,}\b",
)


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
    "在的": "在的，我是 HaiCi 智能客服助手，请问有什么可以帮您？",
    "打扰": "不客气，请说，我在这边。",
    "打扰一下": "不客气，请说，我在这边。",
}


PRODUCT_KEYWORDS = ("产品", "功能", "参数", "价格", "规格", "介绍", "怎么用", "能力", "哪些", "提供")
AFTER_SALE_KEYWORDS = ("退货", "退款", "换货", "保修", "售后", "运费", "包邮", "配送")
COMPLAINT_KEYWORDS = ("投诉", "差评", "不满意", "太慢", "举报")
CHITCHAT_KEYWORDS = ("你好", "您好", "在吗", "在的", "谢谢", "再见", "你是谁", "怎么了", "干嘛", "没事", "哈喽", "嗨", "打扰")
# 纯情感/社交短句（须无业务信号时才可标闲聊）
CHITCHAT_SOCIAL_KEYWORDS = (
    "夸", "赞", "厉害", "棒", "陪我", "喜欢", "不错", "哈哈", "呵呵", "有趣", "开心", "无聊", "孤单", "想你", "陪我聊",
)
# 业务/技术信号：出现任一则禁止标 chitchat
BUSINESS_TECH_KEYWORDS = (
    "库存", "占用", "物料", "单据", "条码", "履历", "仓库", "盘点", "入库", "出库", "发货", "订单", "单号",
    "报错", "错误", "异常", "故障", "排查", "日志", "系统", "模块", "接口", "配置", "账号", "登录", "权限",
    "云盒", "操作", "步骤", "流程", "怎么", "如何", "为什么", "能否", "是否可以", "导致", "原因", "解决",
    "安装", "升级", "版本", "设备", "终端", "网络", "连接", "同步", "导入", "导出", "打印", "扫描",
)


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    faq_answer: str = ""


def has_business_or_technical_signal(text: str) -> bool:
    """是否含业务/技术诉求（含编号、库存、故障排查等）。为真则禁止 chitchat。"""
    q = (text or "").strip()
    if not q:
        return False
    if any(k in q for k in (*PRODUCT_KEYWORDS, *AFTER_SALE_KEYWORDS, *COMPLAINT_KEYWORDS, *BUSINESS_TECH_KEYWORDS)):
        return True
    if _BUSINESS_CODE_RE.search(q):
        return True
    return False


class IntentRecognizer:
    def _has_business_signal(self, text: str) -> bool:
        return has_business_or_technical_signal(text)

    def _is_pure_greeting_or_farewell(self, text: str) -> bool:
        """仅问候/致谢/告别类极短句，且无业务诉求。"""
        if self._has_business_signal(text):
            return False
        norm = re.sub(r"[？?！!。.\s]+", "", text.strip())
        if norm in FAQ_ANSWERS:
            return True
        if len(text.strip()) <= 12 and any(k in text for k in CHITCHAT_KEYWORDS):
            return True
        return False

    def _is_social_chitchat(self, text: str) -> bool:
        """纯社交短句：须同时满足无业务信号 + 明确社交词。"""
        if self._has_business_signal(text):
            return False
        if not any(k in text for k in CHITCHAT_SOCIAL_KEYWORDS):
            return False
        # 社交词 + 极短（≤16 字）且无问句结构中的业务追问
        return len(text.strip()) <= 16

    def _rule_classify(self, query: str) -> Optional[IntentResult]:
        text = query.strip()
        norm = re.sub(r"[？?！!。.\s]+", "", text)
        lower = text.lower()
        if text in FAQ_ANSWERS or norm in FAQ_ANSWERS:
            ans = FAQ_ANSWERS.get(text) or FAQ_ANSWERS.get(norm, "")
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.99, faq_answer=ans)
        for key, ans in FAQ_ANSWERS.items():
            if key in text or key in norm:
                if not self._has_business_signal(text):
                    return IntentResult(intent=IntentType.CHITCHAT, confidence=0.95, faq_answer=ans)
        if any(k in text for k in COMPLAINT_KEYWORDS):
            return IntentResult(intent=IntentType.COMPLAINT, confidence=0.9)
        if any(k in text for k in AFTER_SALE_KEYWORDS):
            return IntentResult(intent=IntentType.AFTER_SALE, confidence=0.85)
        if any(k in text for k in PRODUCT_KEYWORDS):
            return IntentResult(intent=IntentType.PRODUCT, confidence=0.85)
        if self._has_business_signal(text):
            # 有业务/技术信号但未命中细分类 → 默认产品咨询走 RAG
            return IntentResult(intent=IntentType.PRODUCT, confidence=0.82)
        # 纯寒暄/告别
        if self._is_pure_greeting_or_farewell(text):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.88)
        if len(text) <= 16 and any(k in lower or k in text for k in CHITCHAT_KEYWORDS):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.8)
        if self._is_social_chitchat(text):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.78)
        return None

    def recognize(self, query: str, has_image: bool = False) -> IntentResult:
        rule = self._rule_classify(query)
        if rule:
            return rule
        if has_image:
            return IntentResult(intent=IntentType.PRODUCT, confidence=0.75)
        # 兜底：非明确闲聊一律走 RAG（产品咨询）
        return IntentResult(intent=IntentType.PRODUCT, confidence=0.6)


_recognizer: Optional[IntentRecognizer] = None


def get_recognizer() -> IntentRecognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = IntentRecognizer()
        logger.info("[智能客服-对话|intent|规则引擎|硬编执行|初始化] 仅规则模式，无本地小模型")
    return _recognizer
