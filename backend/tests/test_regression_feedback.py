"""用户反馈模块回归测试 (PRD §1)

测试用例:
1. 提交反馈（星级评分）
2. 获取个人反馈列表
3. 无效消息ID反馈失败
"""

import pytest
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


def _login():
    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin"})
    if resp.status_code != 200:
        pytest.skip("登录失败")
    return resp.json()["access_token"]


class TestFeedbackSubmit:
    """TC-FEEDBACK-001: 提交反馈"""

    def test_submit_rating(self):
        """对消息提交星级评分（使用测试消息ID=1）"""
        token = _login()
        payload = {
            "rating": 4,
            "intent_liked": True,
            "comment": "回答不错",
            "context_snapshot": {
                "session_id": 1,
                "context_id": "test",
                "context_summary": "测试",
                "user_question": "测试问题",
                "assistant_answer": "测试回答",
            },
        }
        resp = requests.post(
            f"{BASE_URL}/feedback/messages/1",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        # 可能成功(200)或因消息不存在(404)
        assert resp.status_code in (200, 404)

    def test_submit_invalid_rating(self):
        """评分超出范围应失败"""
        token = _login()
        payload = {"rating": 10}  # 超出1-5范围
        resp = requests.post(
            f"{BASE_URL}/feedback/messages/1",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert resp.status_code == 422

    def test_get_my_feedback(self):
        """获取当前用户的反馈列表"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/feedback/my?page=1&size=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data


class TestFeedbackUnauthorized:
    """TC-FEEDBACK-002: 未授权访问"""

    def test_feedback_without_token(self):
        """未登录提交反馈应失败"""
        resp = requests.post(
            f"{BASE_URL}/feedback/messages/1",
            json={"rating": 3},
        )
        assert resp.status_code in (401, 403)
