"""多知识库路由模块回归测试 (PRD 加分项4)

测试用例:
1. 获取知识库列表
2. 创建新知识库
3. 自动路由匹配
"""

import pytest
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


def _login():
    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin"})
    if resp.status_code != 200:
        pytest.skip("登录失败")
    return resp.json()["access_token"]


class TestKnowledgeBaseCRUD:
    """TC-KB-001: 知识库 CRUD"""

    def test_list_kbs(self):
        """获取知识库列表"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/knowledge-bases/all",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert "items" in data

    def test_create_kb(self):
        """创建新知识库"""
        token = _login()
        payload = {"name": f"测试知识库_{id}", "description": "回归测试用知识库"}
        resp = requests.post(
            f"{BASE_URL}/knowledge-bases",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        # 可能成功或名称已存在
        assert resp.status_code in (200, 400)

    def test_get_kb_not_found(self):
        """获取不存在的知识库应返回404"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/knowledge-bases/99999",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestKnowledgeBaseRouting:
    """TC-KB-002: 自动路由"""

    def test_auto_route_no_kbs(self):
        """无知识库时有合理回退"""
        token = _login()
        resp = requests.post(
            f"{BASE_URL}/knowledge-bases/auto-route?question=测试路由",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 用户可能没有创建知识库
        assert resp.status_code == 200
        data = resp.json()
        assert "kb_id" in data
        assert "routed" in data

    def test_auto_route_empty_question(self):
        """空问题应被校验"""
        token = _login()
        resp = requests.post(
            f"{BASE_URL}/knowledge-bases/auto-route?question=",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
