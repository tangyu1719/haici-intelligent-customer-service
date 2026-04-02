import logging
import re
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class IntentType(Enum):
    CHITCHAT = "chitchat"
    TOOL_CALL = "tool_call"
    RAG = "rag"
    IMAGE_QUERY = "image_query"

FAQ_ANSWERS = {
    "你好": "您好，我是知微电商智能客服，请问有什么可以帮您？",
    "您好": "您好，我是知微电商智能客服，请问有什么可以帮您？",
    "hi": "您好，欢迎咨询，请问有什么可以帮您？",
    "hello": "您好，欢迎咨询，请问有什么可以帮您？",
    "在吗": "在的，请问有什么可以帮您？",
    "有人吗": "在的，我是智能客服，请问有什么需要帮助的？",
    "你是谁": "我是知微电商智能客服助手，可以帮您查询订单、物流、商品信息以及解答售后问题。",
    "你是机器人吗": "我是知微AI智能客服，可以7x24小时为您服务。",
    "你能做什么": "我可以帮您查询订单状态、物流跟踪、商品库存与价格、运费计算、退款进度，以及解答各类售后政策问题。",
    "你会什么": "我可以帮您处理订单查询、物流追踪、库存查询、退款咨询、商品对比等电商相关问题。",
    "谢谢": "不客气，还有问题随时问我。",
    "感谢": "不客气，很高兴能帮到您！",
    "谢谢你": "不客气，祝您购物愉快！",
    "再见": "再见，祝您购物愉快！",
    "拜拜": "再见，欢迎下次光临！",
    "没有了": "好的，祝您生活愉快，有需要随时找我。",
    "没问题了": "好的，感谢您的咨询，祝您一切顺利。",
    "好的": "好的，如果还有其他问题随时告诉我。",
    "知道了": "好的，有其他问题随时联系我。",
    "嗯": "好的，请问还有其他问题吗？",
    "哦": "好的，如果有其他疑问随时提问。",
    "ok": "好的，还有其他可以帮您的吗？",
}

ORDER_ID_PATTERN = re.compile(r'OD\d{10,}', re.IGNORECASE)
PRODUCT_ID_PATTERN = re.compile(r'\bP\d{3}\b', re.IGNORECASE)

@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    faq_answer: str = ""
    entities: Optional[dict] = None

class IntentRecognizer:
    def __init__(self):
        self.model_path = "./qwen/Qwen2.5-1.5B-Instruct"
        logger.info("初始化本地意图识别模型")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.float16,
                device_map={'': 0}
            )
            self.model.eval()
            logger.info("本地意图识别模型加载成功")
        except Exception as e:
            logger.error("意图模型加载失败: %s", str(e))
            self.model = None

    def _rule_classify(self, query: str) -> Optional[IntentResult]:
        cleaned = query.strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower in FAQ_ANSWERS or cleaned_lower in {
            "哈哈", "呵呵", "嘿嘿", "早上好", "晚上好", "下午好", "早安", "晚安"
        }:
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.99, entities={})

        if len(cleaned) <= 3 and not ORDER_ID_PATTERN.search(cleaned) and not PRODUCT_ID_PATTERN.search(cleaned):
            return IntentResult(intent=IntentType.CHITCHAT, confidence=0.95, entities={})

        has_order_id = bool(ORDER_ID_PATTERN.search(query))
        has_product_id = bool(PRODUCT_ID_PATTERN.search(query))

        if has_order_id:
            return IntentResult(intent=IntentType.TOOL_CALL, confidence=0.95, entities={})

        if has_product_id:
            return IntentResult(intent=IntentType.TOOL_CALL, confidence=0.95, entities={})

        # RAG 规则：检测到政策/知识类关键词且无具体订单号或商品编号时，直接标记为 rag
        RAG_KEYWORDS = [
            "运费", "包邮", "免邮", "配送费", "快递费",
            "退款", "退货", "退换", "售后", "退费", "返还",
            "保修", "质保", "保价", "换货",
            "政策", "规则", "流程", "规定", "说明", "条款",
            "怎么算", "多久", "多少天", "工作日", "到账",
            "续航", "抗风", "图传", "避障", "像素", "重量",
            "遥控器", "电池", "充电", "固件", "App",
            "满多少", "免运费", "包邮", "审核",
        ]
        if any(kw in cleaned for kw in RAG_KEYWORDS):
            return IntentResult(intent=IntentType.RAG, confidence=0.9, entities={})

        return None

    def recognize(self, query: str, context: List[str] = None, has_image: bool = False) -> IntentResult:
        if has_image:
            return IntentResult(intent=IntentType.IMAGE_QUERY, confidence=0.8, entities={})

        rule_result = self._rule_classify(query)
        if rule_result:
            return rule_result

        if not self.model:
            return None

        prompt = f"""你是电商客服意图分类器。将用户输入严格分为三类，只输出标签:

chitchat - 闲聊问候，如"你好""谢谢""在吗"
tool_call - 需要查数据库的具体操作，必须包含明确的订单号(如OD开头)或商品编号(如P001)，例如"查订单OD20240115001""P001库存多少"
rag - 咨询通用政策规则知识，如运费规则、退换货政策、商品参数说明、售后流程、保修期、配送规则等。注意：即使提到"退款""退货""物流""快递"等词，只要没有具体订单号或商品编号，就是rag

用户输入: {query}
标签: """

        messages = [
            {"role": "system", "content": "只输出一个标签: chitchat 或 tool_call 或 rag"},
            {"role": "user", "content": prompt}
        ]

        try:
            text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

            with torch.no_grad():
                generated_ids = self.model.generate(**inputs, max_new_tokens=10, temperature=0.1)

            input_length = inputs.input_ids.shape[1]
            new_tokens = generated_ids[0][input_length:]
            result = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip().lower()

            valid_intents = [e.value for e in IntentType if e != IntentType.IMAGE_QUERY]
            for intent in valid_intents:
                if intent in result:
                    return IntentResult(intent=IntentType(intent), confidence=0.85, entities={})

            return None
        except Exception as e:
            logger.error("意图推理异常: %s", str(e))
            return None

_recognizer: Optional[IntentRecognizer] = None

def get_recognizer() -> IntentRecognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = IntentRecognizer()
    return _recognizer
