"""会话管理模块回归测试 (PRD §1)

测试用例:
1. 创建新会话
2. 获取会话列表
3. 归档（软删除）会话
"""

import pytest
import requests

from tests.http_regression_helpers import BASE_URL, login_password


def _login():
    return login_password()


class TestSessionCreate:
    """TC-SESSION-001: 创建会话"""

    def test_create_session(self):
        """创建新会话并验证返回字段"""
        token = _login()
        resp = requests.post(
            f"{BASE_URL}/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "context_id" in data
        assert data.get("title") == "新对话"

    def test_create_session_unauthorized(self):
        """未登录创建会话应失败"""
        resp = requests.post(f"{BASE_URL}/sessions")
        assert resp.status_code in (401, 403)

    def test_get_session_list(self):
        """获取会话列表并验证分页"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/sessions?page=1&size=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)


class TestSessionArchive:
    """TC-SESSION-002: 归档会话"""

    def test_archive_session(self):
        """创建后归档会话"""
        token = _login()
        # 1. 创建
        resp = requests.post(
            f"{BASE_URL}/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            pytest.skip("创建会话失败")
        sid = resp.json()["id"]
        # 2. 归档（POST /archive，非 DELETE 软删）
        archive_resp = requests.post(
            f"{BASE_URL}/sessions/{sid}/archive",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert archive_resp.status_code == 200

    def test_get_archived_session_detail(self):
        """归档后会话 status=0，详情接口对普通用户返回 404（active_only）。"""
        token = _login()
        resp = requests.post(
            f"{BASE_URL}/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            pytest.skip("创建会话失败")
        sid = resp.json()["id"]
        requests.post(
            f"{BASE_URL}/sessions/{sid}/archive",
            headers={"Authorization": f"Bearer {token}"},
        )
        detail_resp = requests.get(
            f"{BASE_URL}/sessions/{sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail_resp.status_code == 404
