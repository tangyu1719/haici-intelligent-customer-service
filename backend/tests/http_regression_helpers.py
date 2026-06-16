"""HTTP 集成回归共用：对齐当前 auth API（identifier/credential）。"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest
import requests

from app.database import SessionLocal
from app.models import RbacVerifyCode

BASE_URL = os.getenv("HAICI_API_BASE", "http://127.0.0.1:8000/api/v1")


def login_password(identifier: str = "admin", credential: str = "admin") -> str:
    """密码登录，返回 access_token。"""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "login_type": "password",
            "identifier": identifier,
            "credential": credential,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        pytest.skip(f"登录失败: HTTP {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        pytest.skip("登录响应缺少 access_token")
    return token


def send_register_code(email: str) -> None:
    resp = requests.post(
        f"{BASE_URL}/auth/send-code",
        json={"target": email, "code_type": "email", "purpose": "register"},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text


def _latest_verify_code(email: str, purpose: str = "register") -> str:
    db = SessionLocal()
    try:
        row = (
            db.query(RbacVerifyCode)
            .filter(
                RbacVerifyCode.target == email.strip().lower(),
                RbacVerifyCode.type == "email",
                RbacVerifyCode.purpose == purpose,
            )
            .order_by(RbacVerifyCode.id.desc())
            .first()
        )
        if not row:
            raise AssertionError(f"未找到验证码记录: {email}")
        return row.code
    finally:
        db.close()


def register_with_email(email: str, password: str) -> requests.Response:
    """发送邮箱验证码并完成注册。"""
    send_register_code(email)
    code = _latest_verify_code(email)
    return requests.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": password, "code": code},
        timeout=30,
    )


def collect_sse_text(resp: requests.Response) -> str:
    """解析 SSE 流中的 token/done 正文。"""
    parts: list[str] = []
    current_event = ""
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
            continue
        if not line.startswith("data:"):
            continue
        try:
            data: dict[str, Any] = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if current_event == "token" and data.get("content"):
            parts.append(str(data["content"]))
        elif current_event == "done" and data.get("content"):
            parts.append(str(data["content"]))
    return "".join(parts)
