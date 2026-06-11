import logging
from typing import Any, Dict

from app.intent import IntentType, get_recognizer
from app.memory import get_memory
from app.rag import rag_query

logger = logging.getLogger(__name__)


class DialogManager:
    def __init__(self):
        self.recognizer = get_recognizer()
        self.memory = get_memory()

    def process(self, query: str, session_id: str = "default", tenant_id: str = "default") -> Dict[str, Any]:
        intent_res = self.recognizer.recognize(query)
        intent = intent_res.intent
        if intent == IntentType.CHITCHAT and intent_res.faq_answer:
            self.memory.add_message(session_id, "user", query)
            self.memory.add_message(session_id, "assistant", intent_res.faq_answer)
            return {
                "answer": intent_res.faq_answer,
                "intent": intent.value,
                "context": [],
                "citations": [],
                "type": "faq",
            }
        history = self.memory.get_history(session_id)
        result = rag_query(query, tenant_id=tenant_id, history=history, intent=intent.value)
        answer = result.get("answer", "")
        self.memory.add_message(session_id, "user", query)
        self.memory.add_message(session_id, "assistant", answer)
        return {
            "answer": answer,
            "intent": intent.value,
            "context": result.get("context", []),
            "citations": result.get("citations", []),
            "type": "rag",
        }


_manager = None


def get_manager() -> DialogManager:
    global _manager
    if _manager is None:
        _manager = DialogManager()
    return _manager
