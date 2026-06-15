"""登录模块回归测试：Casbin / 日志 / 会话详情。"""

from __future__ import annotations

import random
import uuid

from fastapi.testclient import TestClient

from app.auth.rbac import assign_role
from app.auth.security import hash_password
from app.database import SessionLocal
from app.main import app
from app.models import RbacVerifyCode, User

client = TestClient(app)


def _rand_phone(prefix: str = "138") -> str:
    return prefix + "".join(str(random.randint(0, 9)) for _ in range(8))


def _sms_login(phone: str) -> dict:
    client.post("/api/v1/auth/send-code", json={"target": phone, "code_type": "sms", "purpose": "login"})
    db = SessionLocal()
    code = db.query(RbacVerifyCode).filter(RbacVerifyCode.target == phone).order_by(RbacVerifyCode.id.desc()).first().code
    db.close()
    r = client.post("/api/v1/auth/login", json={"login_type": "sms", "identifier": phone, "credential": code})
    assert r.status_code == 200, r.text
    return r.json()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_sms_login_and_user_no():
    phone = _rand_phone("138")
    data = _sms_login(phone)
    assert len(data["user"]["user_no"]) == 10
    assert data["user"]["nickname"].startswith("小鱼儿_")


def test_viewer_denied_admin_logs():
    phone = _rand_phone("139")
    tok = _sms_login(phone)["access_token"]
    r = client.get("/api/v1/admin/logs/operation", headers=_auth_headers(tok))
    assert r.status_code == 403


def test_admin_can_read_logs():
    db = SessionLocal()
    from app.auth.seed import ensure_roles

    ensure_roles(db)
    email = f"admin_test_{uuid.uuid4().hex[:6]}@haici.com"
    user = User(email=email, password_hash=hash_password("Admin123!"), status=1, nickname="测试管理员")
    db.add(user)
    db.commit()
    db.refresh(user)
    from app.auth.user_no import generate_user_no

    user.user_no = generate_user_no(db)
    db.commit()
    assign_role(db, user.id, "admin")
    db.close()

    r = client.post(
        "/api/v1/auth/login",
        json={"login_type": "password", "identifier": email, "credential": "Admin123!"},
    )
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    r2 = client.get("/api/v1/admin/logs/operation", headers=_auth_headers(tok))
    assert r2.status_code == 200, r2.text
    assert "items" in r2.json()


def test_session_detail_with_messages():
    phone = _rand_phone("137")
    tok = _sms_login(phone)["access_token"]
    h = _auth_headers(tok)
    created = client.post("/api/v1/sessions", headers=h)
    assert created.status_code == 200
    sid = created.json()["id"]
    detail = client.get(f"/api/v1/sessions/{sid}", headers=h)
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == sid
    assert "messages" in body
    assert body["message_count"] == 0


def test_admin_password_login():
    db = SessionLocal()
    from app.auth.seed import ensure_bootstrap_admin, ensure_roles

    ensure_roles(db)
    ensure_bootstrap_admin(db)
    db.close()
    r = client.post(
        "/api/v1/auth/login",
        json={"login_type": "password", "identifier": "admin", "credential": "admin"},
    )
    assert r.status_code == 200, r.text
    assert "admin" in (r.json()["user"].get("roles") or [])


def test_chat_config_includes_daily_quota():
    phone = _rand_phone("135")
    tok = _sms_login(phone)["access_token"]
    r = client.get("/api/v1/chat/config", headers=_auth_headers(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("daily_question_limit") == 100
    assert "daily_questions_used" in body
    assert body.get("daily_quota_unlimited") is False


def test_viewer_denied_admin_rbac_users():
    phone = _rand_phone("134")
    tok = _sms_login(phone)["access_token"]
    r = client.get("/api/v1/admin/rbac/users", headers=_auth_headers(tok))
    assert r.status_code == 403


def test_admin_can_manage_users():
    db = SessionLocal()
    from app.auth.seed import ensure_roles

    ensure_roles(db)
    email = f"rbac_admin_{uuid.uuid4().hex[:6]}@haici.com"
    admin_user = User(email=email, password_hash=hash_password("Admin123!"), status=1, nickname="RBAC管理员")
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    from app.auth.user_no import generate_user_no

    admin_user.user_no = generate_user_no(db)
    db.commit()
    assign_role(db, admin_user.id, "admin")

    viewer_email = f"viewer_{uuid.uuid4().hex[:6]}@haici.com"
    viewer = User(email=viewer_email, password_hash=hash_password("Viewer123!"), status=1, nickname="测试用户")
    db.add(viewer)
    db.commit()
    db.refresh(viewer)
    viewer.user_no = generate_user_no(db)
    db.commit()
    assign_role(db, viewer.id, "viewer")
    viewer_id = viewer.id
    db.close()

    r = client.post(
        "/api/v1/auth/login",
        json={"login_type": "password", "identifier": email, "credential": "Admin123!"},
    )
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    h = _auth_headers(tok)

    r2 = client.get("/api/v1/admin/rbac/users", headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["total"] >= 1

    r3 = client.put(
        f"/api/v1/admin/rbac/users/{viewer_id}/roles",
        headers=h,
        json={"roles": ["viewer", "admin"]},
    )
    assert r3.status_code == 200, r3.text
    assert "admin" in r3.json()["roles"]

    r4 = client.put(
        f"/api/v1/admin/rbac/users/{viewer_id}/roles",
        headers=h,
        json={"roles": ["viewer"]},
    )
    assert r4.status_code == 200, r4.text
    assert r4.json()["roles"] == ["viewer"]


def test_agent_pipeline_rule():
    from app.services.agent_pipeline import run_agent_pipeline

    p = run_agent_pipeline("退货政策是什么", [])
    assert p.intent == "after_sale"
    assert p.rag_query
    assert p.retrieval_terms


def test_api_call_log_written():
    phone = _rand_phone("136")
    tok = _sms_login(phone)["access_token"]
    client.get("/api/v1/auth/me", headers=_auth_headers(tok))
    db = SessionLocal()
    from app.models import SysLogApiCall

    cnt = db.query(SysLogApiCall).count()
    db.close()
    assert cnt >= 1


if __name__ == "__main__":
    test_sms_login_and_user_no()
    test_viewer_denied_admin_logs()
    test_admin_can_read_logs()
    test_admin_password_login()
    test_chat_config_includes_daily_quota()
    test_viewer_denied_admin_rbac_users()
    test_admin_can_manage_users()
    test_session_detail_with_messages()
    test_agent_pipeline_rule()
    test_api_call_log_written()
    print("ALL REGRESSION TESTS PASSED")
