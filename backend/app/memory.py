"""减重：使用进程内内存保存多轮上下文，不依赖 Redis。"""

import logging
from collections import defaultdict, deque
from typing import Deque, Dict, List

from app.config import settings

logger = logging.getLogger(__name__)


class ChatMemory:
    def __init__(self):
        self.window_size = settings.CHAT_HISTORY_TURNS
        self._store: Dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=self.window_size * 2))

    def add_message(self, session_key: str, role: str, content: str):
        self._store[session_key].append({"role": role, "content": content})

    def get_history(self, session_key: str, window: int | None = None) -> List[Dict]:
        window = window or self.window_size
        items = list(self._store.get(session_key, []))
        return items[-window * 2 :]

    def clear(self, session_key: str):
        self._store.pop(session_key, None)


_memory = None


def get_memory() -> ChatMemory:
    global _memory
    if _memory is None:
        _memory = ChatMemory()
        logger.info("[智能客服-对话|memory|内存会话|硬编执行|初始化] 已启用进程内会话缓存")
    return _memory
