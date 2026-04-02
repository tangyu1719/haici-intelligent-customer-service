import json
import logging
from typing import Dict, List, Optional
import redis
from config import settings

logger = logging.getLogger(__name__)

class ChatMemory:
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self.expire_time = 7200
        self.window_size = 15

    @property
    def redis_client(self) -> Optional[redis.Redis]:
        if self._redis is None:
            try:
                self._redis = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    decode_responses=True
                )
            except Exception as e:
                logger.warning("Redis连接失败: %s", str(e))
        return self._redis

    def _get_key(self, session_id: str) -> str:
        return f"chat_history:{session_id}"

    def add_message(self, session_id: str, role: str, content: str):
        if not self.redis_client:
            return
        key = self._get_key(session_id)
        msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        try:
            pipe = self.redis_client.pipeline()
            pipe.rpush(key, msg)
            pipe.ltrim(key, -self.window_size * 2, -1)
            pipe.expire(key, self.expire_time)
            pipe.execute()
        except Exception as e:
            logger.warning("保存消息失败: %s", str(e))

    def get_history(self, session_id: str, window: int = None) -> List[Dict]:
        if not self.redis_client:
            return []
        window = window or self.window_size
        key = self._get_key(session_id)
        try:
            items = self.redis_client.lrange(key, -window * 2, -1)
            return [json.loads(item) for item in items]
        except Exception as e:
            logger.warning("获取历史失败: %s", str(e))
            return []

    def clear(self, session_id: str):
        if not self.redis_client:
            return
        try:
            self.redis_client.delete(self._get_key(session_id))
        except Exception as e:
            logger.warning("清除历史失败: %s", str(e))

_memory: Optional[ChatMemory] = None

def get_memory() -> ChatMemory:
    global _memory
    if _memory is None:
        _memory = ChatMemory()
    return _memory
