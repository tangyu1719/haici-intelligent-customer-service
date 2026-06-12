"""管理后台模块回归测试 (PRD 加分项3)

测试用例:
1. 获取反馈分析统计
2. 获取EVAL概览
3. 获取操作日志
"""

import pytest
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


def _login():
    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin"})
    if resp.status_code != 200:
        pytest.skip("登录失败")
    return resp.json()["access_token"]


class TestAdminFeedback:
    """TC-ADMIN-001: 反馈分析"""

    def test_feedback_analytics(self):
        """获取反馈分析统计数据"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/admin/feedback/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "intent_pie" in data or "demo_mode" in data or "ok" in data

    def test_feedback_list(self):
        """获取反馈列表（管理视图）"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/admin/feedback?page=1&size=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data


class TestAdminEval:
    """TC-ADMIN-002: EVAL 评测"""

    def test_eval_overview(self):
        """获取 EVAL 评测概览"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/admin/eval/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data or "total_calls" in data


class TestAdminLogs:
    """TC-ADMIN-003: 运维日志"""

    def test_operation_logs(self):
        """获取操作日志列表"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/admin/logs/operation?page=1&size=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
