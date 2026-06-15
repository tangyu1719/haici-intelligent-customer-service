"""系统管理：全局参数设置。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import require_admin
from app.models import User
from app.services.system_settings import load_system_settings, save_system_settings

router = APIRouter(prefix="/admin/system", tags=["系统管理-设置"])


class SystemSettingsResponse(BaseModel):
    session_active_persist_interval_minutes: int = Field(ge=1, le=120)


class SystemSettingsUpdateRequest(BaseModel):
    session_active_persist_interval_minutes: int | None = Field(default=None, ge=1, le=120)


@router.get("/settings", response_model=SystemSettingsResponse)
def get_settings(_admin: User = Depends(require_admin)):
    data = load_system_settings()
    return SystemSettingsResponse(
        session_active_persist_interval_minutes=int(data["session_active_persist_interval_minutes"]),
    )


@router.put("/settings", response_model=SystemSettingsResponse)
def update_settings(body: SystemSettingsUpdateRequest, _admin: User = Depends(require_admin)):
    patch: dict = {}
    if body.session_active_persist_interval_minutes is not None:
        patch["session_active_persist_interval_minutes"] = body.session_active_persist_interval_minutes
    data = save_system_settings(patch) if patch else load_system_settings()
    return SystemSettingsResponse(
        session_active_persist_interval_minutes=int(data["session_active_persist_interval_minutes"]),
    )
