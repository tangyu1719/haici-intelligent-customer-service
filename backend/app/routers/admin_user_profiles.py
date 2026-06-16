"""管理员：用户 MD 画像与长期记忆查看。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import User
from app.services.list_query import ListQuery, apply_keyword, apply_sort, list_query_params, page_result, paginate
from app.services.user_profile_memory import profile_path, read_profile_md, write_profile_md

router = APIRouter(prefix="/admin/user-profiles", tags=["系统管理-用户画像"])


class UserProfileListItem(BaseModel):
    user_id: int
    user_no: str | None = None
    username: str | None = None
    nickname: str = ""
    has_profile: bool = False
    profile_chars: int = 0


class UserProfileListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[UserProfileListItem]


class UserProfileDetailResponse(BaseModel):
    user_id: int
    user_no: str | None = None
    username: str | None = None
    nickname: str = ""
    markdown: str
    profile_path: str


class UserProfileUpdateRequest(BaseModel):
    markdown: str = Field(default="", max_length=100_000)


@router.get("", response_model=UserProfileListResponse)
def list_user_profiles(
    qry: ListQuery = Depends(list_query_params),
    has_profile: bool | None = Query(None, description="仅显示已有画像的用户"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    q = db.query(User).filter(User.status == 1)
    q = apply_keyword(q, qry, [User.username, User.nickname, User.user_no, User.email, User.phone])
    sort_map = {"id": User.id, "created_at": User.created_at, "username": User.username}
    q = apply_sort(q, User, qry, sort_map, User.id)
    rows, total = paginate(q, qry)
    items: list[UserProfileListItem] = []
    for u in rows:
        md = read_profile_md(u.id)
        exists = bool(md.strip())
        if has_profile is True and not exists:
            continue
        if has_profile is False and exists:
            continue
        items.append(
            UserProfileListItem(
                user_id=u.id,
                user_no=u.user_no,
                username=u.username,
                nickname=u.nickname or "",
                has_profile=exists,
                profile_chars=len(md),
            )
        )
    if has_profile is not None:
        total = len(items)
    return UserProfileListResponse(**page_result(items, total, qry))


@router.get("/{user_id}", response_model=UserProfileDetailResponse)
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    md = read_profile_md(user_id)
    return UserProfileDetailResponse(
        user_id=user.id,
        user_no=user.user_no,
        username=user.username,
        nickname=user.nickname or "",
        markdown=md or "（该用户尚无画像，将在 5 星反馈或会话归档后自动生成）",
        profile_path=str(profile_path(user_id)),
    )


@router.put("/{user_id}", response_model=UserProfileDetailResponse)
def update_user_profile(
    user_id: int,
    body: UserProfileUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    write_profile_md(user_id, body.markdown, user=user, editor_id=admin.id)
    md = read_profile_md(user_id)
    return UserProfileDetailResponse(
        user_id=user.id,
        user_no=user.user_no,
        username=user.username,
        nickname=user.nickname or "",
        markdown=md,
        profile_path=str(profile_path(user_id)),
    )
