"""对话/RAG模块回归测试 (PRD §2)

测试用例:
1. 流式对话（SSE）
2. 空检索兜底话术
3. 超长问题拒绝
"""

import json

import pytest
import requests

from tests.http_regression_helpers import BASE_URL, collect_sse_text, login_password


def _login():
    return login_password()


def _create_session(token: str) -> int:
    resp = requests.post(f"{BASE_URL}/sessions", headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        pytest.skip("创建会话失败")
    return resp.json()["id"]


class TestChatStream:
    """TC-CHAT-001: 流式对话"""

    def test_stream_response(self):
        """发起流式对话并验证SSE事件格式"""
        token = _login()
        sid = _create_session(token)
        resp = requests.post(
            f"{BASE_URL}/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": sid, "question": "你好"},
            stream=True,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events_received = 0
        has_done = False
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
                events_received += 1
                if event_type == "done":
                    has_done = True
        assert events_received > 0
        assert has_done

    def test_empty_question_fallback(self):
        """空知识库问题应返回兜底话术"""
        token = _login()
        sid = _create_session(token)
        resp = requests.post(
            f"{BASE_URL}/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": sid, "question": "这是一个完全随机无意义的问题xyzabc123"},
            stream=True,
        )
        assert resp.status_code == 200
        full = collect_sse_text(resp)
        # 验证回答不为空（token 流或 done.content）
        assert len(full) > 0

    def test_overlong_question_rejected(self):
        """超过500字的问题应被拒绝"""
        token = _login()
        sid = _create_session(token)
        resp = requests.post(
            f"{BASE_URL}/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": sid, "question": "x" * 501},
            stream=True,
        )
        assert resp.status_code == 400


class TestChatConfig:
    """TC-CHAT-002: 对话配置"""

    def test_chat_config(self):
        """获取对话配置"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/chat/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert "max_question_length" in data


class TestIntentAlternatives:
    """TC-CHAT-003: 意图纠偏接口"""

    def test_intent_alternatives_no_message(self):
        """不存在的消息ID应返回404"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/chat/intent-alternatives?message_id=99999",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
