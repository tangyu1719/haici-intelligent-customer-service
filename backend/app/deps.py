from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.rbac import enforce_api, get_user_roles
from app.auth.security import decode_access_token
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录，请先登录")
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if not user or user.status != 1:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


def get_token_payload(token: str | None = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    return payload


def require_api_permission(
    request: Request,
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
) -> None:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期")
    roles = payload.get("roles") or get_user_roles(db, int(payload["sub"]))
    if not enforce_api(roles, request.url.path, request.method):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权限，请向管理员申请权限")


def require_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    roles = get_user_roles(db, current_user.id)
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


def require_roles(*role_codes: str):
    allowed = set(role_codes)

    def _dep(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        roles = get_user_roles(db, current_user.id)
        if "admin" in roles or allowed.intersection(roles):
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限，请向管理员申请权限")

    return _dep
