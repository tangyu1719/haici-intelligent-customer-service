import logging
from typing import Dict, Any
from rag import rag_query
from agent import get_agent
from intent import get_recognizer, FAQ_ANSWERS, IntentType

logger = logging.getLogger(__name__)

class DialogManager:
    def __init__(self):
        self.agent = get_agent()
        self.recognizer = get_recognizer()

    def process(self, query: str, session_id: str = "default", tenant_id: str = "default", image_data: bytes = None, skip_cache: bool = False, agent: bool = True) -> Dict[str, Any]:
        has_image = bool(image_data)
        final_query = query

        if image_data:
            from multimodal import get_processor
            try:
                img_desc = get_processor().process_image(image_data)
                final_query = f"系统提示: 用户上传了一张图片，内容如下\n{img_desc}\n\n用户提问:\n{query}"
            except Exception as e:
                logger.error("图片识别异常: %s", str(e))

        intent_res = self.recognizer.recognize(query, has_image=has_image)
        intent = intent_res.intent

        # 1. chitchat 命中 FAQ 直接返回
        if intent == IntentType.CHITCHAT:
            if query in FAQ_ANSWERS:
                return {
                    "answer": FAQ_ANSWERS[query],
                    "intent": "chitchat",
                    "context": [],
                    "score": 1.0,
                    "type": "fast_chitchat"
                }

        if agent:
            # 2. 将意图标签注入 Agent，让 Agent 根据标签选择工具
            intent_label = intent.value if hasattr(intent, "value") else str(intent)
            intent_hint = ""
            if intent == IntentType.RAG:
                intent_hint = "系统提示: 该问题已被识别为知识咨询类(rag)，请优先调用 search_knowledge 工具检索知识库回答。"
            elif intent == IntentType.TOOL_CALL:
                intent_hint = "系统提示: 该问题已被识别为业务操作类(tool_call)，请根据用户需求调用相应的业务工具(query_order/cancel_order/query_logistics/check_stock)。"
            elif intent == IntentType.CHITCHAT:
                intent_hint = "系统提示: 该问题已被识别为闲聊类(chitchat)，请直接友好回复，无需调用工具。"
            elif intent == IntentType.IMAGE_QUERY:
                intent_hint = "系统提示: 用户上传了图片，请结合图片内容回答问题。"
            else:
                intent_hint = "系统提示: 该问题意图未明确，请自行分析并选择合适的工具调用或直接回答。"

            agent_input = f"{intent_hint}\n用户问题: {final_query}" if intent_hint else final_query
            res = self.agent.run(agent_input, session_id=session_id, context="")

            return {
                "answer": res.answer,
                "intent": intent_label,
                "context": [],
                "score": 0.9,
                "type": "agent_reasoning"
            }

        return rag_query(final_query, tenant_id, skip_cache)

_manager = None

def get_manager() -> DialogManager:
    global _manager
    if not _manager:
        _manager = DialogManager()
    return _manager
