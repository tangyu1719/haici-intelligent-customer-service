"""认证路由：密码/短信登录、邮箱注册、Refresh、菜单。"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.rbac import assign_role, build_menu_tree, get_user_permissions, get_user_roles
from app.auth.security import (
    create_access_token,
    hash_password,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    unusable_password_hash,
    verify_password,
)
from app.auth.user_no import default_sms_nickname, generate_user_no
from app.auth.verify_code import send_code, verify_code
from app.database import get_db
from app.deps import get_current_user
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])

_PHONE_RE = re.compile(r"^1\d{10}$")


class LoginRequest(BaseModel):
    login_type: str = Field(default="password", description="password | sms")
    identifier: str
    credential: str


class SendCodeRequest(BaseModel):
    target: str
    code_type: str = "email"
    purpose: str = "login"


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=64)
    code: str
    nickname: str | None = None
    username: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = None
    phone: str | None = None
    phone_code: str | None = None


def _user_dict(user: User, roles: list[str], permissions: list[str]) -> dict:
    return {
        "id": user.id,
        "user_no": user.user_no,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "nickname": user.nickname,
        "roles": roles,
        "permissions": permissions,
    }


def _issue_tokens(db: Session, user: User) -> dict:
    roles = get_user_roles(db, user.id)
    perms = get_user_permissions(db, user.id)
    access = create_access_token(user, roles)
    refresh = issue_refresh_token(db, user.id)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": _user_dict(user, roles, perms),
    }


def _find_by_identifier(db: Session, identifier: str) -> User | None:
    ident = identifier.strip()
    if "@" in ident:
        return db.query(User).filter(User.email == ident).first()
    if _PHONE_RE.match(ident):
        return db.query(User).filter(User.phone == ident).first()
    return db.query(User).filter((User.username == ident) | (User.email == ident) | (User.phone == ident)).first()


@router.post("/send-code")
def route_send_code(body: SendCodeRequest, db: Session = Depends(get_db)):
    target = body.target.strip()
    if not target:
        raise HTTPException(400, "请输入手机号或邮箱")
    send_code(db, target, body.code_type, body.purpose)
    return {"ok": True, "message": "验证码已发送（开发环境见后端日志）"}


@router.post("/login")
def route_login(body: LoginRequest, db: Session = Depends(get_db)):
    ident = body.identifier.strip()
    if not ident:
        raise HTTPException(400, "请输入手机号或邮箱")

    if body.login_type == "sms":
        if not _PHONE_RE.match(ident):
            raise HTTPException(400, "短信登录请使用大陆 11 位手机号")
        ok, msg = verify_code(db, ident, "sms", "login", body.credential)
        if not ok:
            raise HTTPException(400, msg)
        user = db.query(User).filter(User.phone == ident).first()
        created = False
        if not user:
            user_no = generate_user_no(db)
            user = User(
                user_no=user_no,
                phone=ident,
                nickname=default_sms_nickname(user_no),
                password_hash=unusable_password_hash(),
                status=1,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            assign_role(db, user.id, "viewer")
            created = True
            logger.info("[登录模块-认证|auth|短信静默注册|Agent执行|完成] phone=%s; user_no=%s", ident, user_no)
        if user.status != 1:
            raise HTTPException(403, "账号已被禁用")
        out = _issue_tokens(db, user)
        out["is_new_user"] = created
        return out

    user = _find_by_identifier(db, ident)
    if not user or not user.password_hash:
        raise HTTPException(400, "账号不存在或未设置密码，请注册或使用手机验证码登录")
    if not verify_password(body.credential, user.password_hash):
        raise HTTPException(400, "账号或密码错误")
    if user.status != 1:
        raise HTTPException(403, "账号已被禁用")
    return _issue_tokens(db, user)


@router.post("/register")
def route_register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "邮箱格式不正确")
    ok, msg = verify_code(db, email, "email", "register", body.code)
    if not ok:
        raise HTTPException(400, msg)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "该邮箱已注册")
    user_no = generate_user_no(db)
    user = User(
        user_no=user_no,
        email=email,
        username=(body.username or email).strip() or email,
        nickname=(body.nickname or "").strip(),
        password_hash=hash_password(body.password),
        status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    assign_role(db, user.id, "viewer")
    return _issue_tokens(db, user)


@router.post("/refresh")
def route_refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    rotated = rotate_refresh_token(db, body.refresh_token)
    if not rotated:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh Token 无效或已过期")
    user_id, new_refresh = rotated
    user = db.get(User, int(user_id))
    if not user or user.status != 1:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不可用")
    roles = get_user_roles(db, user.id)
    perms = get_user_permissions(db, user.id)
    return {
        "access_token": create_access_token(user, roles),
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "user": _user_dict(user, roles, perms),
    }


@router.post("/logout")
def route_logout(body: RefreshRequest, db: Session = Depends(get_db)):
    revoke_refresh_token(db, body.refresh_token)
    return {"ok": True}


@router.get("/me")
def route_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    roles = get_user_roles(db, current_user.id)
    perms = get_user_permissions(db, current_user.id)
    return _user_dict(current_user, roles, perms)


@router.get("/menus")
def route_menus(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"items": build_menu_tree(db, current_user.id)}


@router.patch("/profile")
def route_profile(
    body: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.nickname is not None:
        current_user.nickname = body.nickname.strip()
    if body.phone:
        phone = body.phone.strip()
        if not _PHONE_RE.match(phone):
            raise HTTPException(400, "手机号格式不正确")
        if body.phone_code:
            ok, msg = verify_code(db, phone, "sms", "bind", body.phone_code)
            if not ok:
                raise HTTPException(400, msg)
        else:
            raise HTTPException(400, "绑定手机需要验证码")
        exists = db.query(User).filter(User.phone == phone, User.id != current_user.id).first()
        if exists:
            raise HTTPException(400, "该手机号已被其他账号绑定")
        current_user.phone = phone
    db.commit()
    db.refresh(current_user)
    roles = get_user_roles(db, current_user.id)
    return _user_dict(current_user, roles, get_user_permissions(db, current_user.id))
