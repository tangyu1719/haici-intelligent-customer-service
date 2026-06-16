"""用户自服务：查看与编辑自己的 MD 画像。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.user_profile_memory import profile_path, read_profile_md, write_profile_md

router = APIRouter(prefix="/user-profiles", tags=["用户画像"])


class UserProfileMdResponse(BaseModel):
    user_id: int
    nickname: str = ""
    markdown: str
    profile_path: str


class UserProfileMdUpdateRequest(BaseModel):
    markdown: str = Field(default="", max_length=100_000)


@router.get("/me", response_model=UserProfileMdResponse)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    md = read_profile_md(current_user.id)
    return UserProfileMdResponse(
        user_id=current_user.id,
        nickname=current_user.nickname or "",
        markdown=md or "（尚无画像，可在下方编辑保存；5 星反馈或会话归档后也会自动沉淀）",
        profile_path=str(profile_path(current_user.id)),
    )


@router.put("/me", response_model=UserProfileMdResponse)
def update_my_profile(
    body: UserProfileMdUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    write_profile_md(current_user.id, body.markdown, user=current_user, editor_id=current_user.id)
    md = read_profile_md(current_user.id)
    return UserProfileMdResponse(
        user_id=current_user.id,
        nickname=current_user.nickname or "",
        markdown=md,
        profile_path=str(profile_path(current_user.id)),
    )
