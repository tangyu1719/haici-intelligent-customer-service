"""用户认证模块回归测试 (PRD §1)

测试用例:
1. 注册新用户（邮箱+密码+验证码）
2. 密码登录（identifier/credential）
3. 无效凭证登录失败
"""

import time

import pytest
import requests

from tests.http_regression_helpers import BASE_URL, login_password, register_with_email


class TestAuthRegistration:
    """TC-AUTH-001: 用户注册"""

    def test_register_with_email(self):
        """通过邮箱注册新用户"""
        email = f"test_{int(time.time())}@example.com"
        resp = register_with_email(email, "testpass123")
        assert resp.status_code in (200, 400)  # 200=成功, 400=已存在
        if resp.status_code == 200:
            data = resp.json()
            assert "access_token" in data or "ok" in data

    def test_register_missing_email_and_phone(self):
        """注册时缺少邮箱与验证码应失败"""
        payload = {"password": "testpass123"}
        resp = requests.post(f"{BASE_URL}/auth/register", json=payload)
        assert resp.status_code == 422  # Pydantic 校验失败

    def test_register_weak_password(self):
        """密码过短应失败"""
        payload = {"email": "weak@example.com", "password": "12", "code": "123456"}
        resp = requests.post(f"{BASE_URL}/auth/register", json=payload)
        assert resp.status_code == 422


class TestAuthLogin:
    """TC-AUTH-002: 用户登录"""

    def test_login_with_password(self):
        """使用 admin 密码登录"""
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={
                "login_type": "password",
                "identifier": "admin",
                "credential": "admin",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data.get("token_type") == "bearer"

    def test_login_wrong_password(self):
        """错误密码登录应失败"""
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={
                "login_type": "password",
                "identifier": "admin",
                "credential": "wrongpassword",
            },
        )
        assert resp.status_code in (401, 403, 400)

    def test_refresh_token(self):
        """获取 access token 后验证 /auth/me 可访问"""
        token = login_password()
        me_resp = requests.get(
            f"{BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 200
        user = me_resp.json()
        assert user.get("username") == "admin" or "id" in user
