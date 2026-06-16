"""系统管理：全局参数设置。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.deps import require_admin
from app.models import User
from app.services.system_settings import (
    DEFAULT_POOL_CEILING_MAP,
    format_pool_ceiling_map,
    load_system_settings,
    parse_pool_ceiling_map,
    save_system_settings,
)

router = APIRouter(prefix="/admin/system", tags=["系统管理-设置"])


class SystemSettingsResponse(BaseModel):
    session_active_persist_interval_minutes: int = Field(ge=1, le=120)
    rag_pool_ceiling_mode: Literal["smart", "hard"] = "smart"
    rag_pool_ceiling_map: str = DEFAULT_POOL_CEILING_MAP


class SystemSettingsUpdateRequest(BaseModel):
    session_active_persist_interval_minutes: int | None = Field(default=None, ge=1, le=120)
    rag_pool_ceiling_mode: Literal["smart", "hard"] | None = None
    rag_pool_ceiling_map: str | None = None

    @field_validator("rag_pool_ceiling_map")
    @classmethod
    def validate_map(cls, v: str | None) -> str | None:
        if v is None:
            return v
        pairs = parse_pool_ceiling_map(v.strip())
        if not pairs:
            raise ValueError("映射格式无效，示例：100:10,50:5,20:3")
        return format_pool_ceiling_map(pairs)


@router.get("/settings", response_model=SystemSettingsResponse)
def get_settings(_admin: User = Depends(require_admin)):
    data = load_system_settings()
    return SystemSettingsResponse(
        session_active_persist_interval_minutes=int(data["session_active_persist_interval_minutes"]),
        rag_pool_ceiling_mode=str(data.get("rag_pool_ceiling_mode", "smart")),  # type: ignore[arg-type]
        rag_pool_ceiling_map=str(data.get("rag_pool_ceiling_map", DEFAULT_POOL_CEILING_MAP)),
    )


@router.put("/settings", response_model=SystemSettingsResponse)
def update_settings(body: SystemSettingsUpdateRequest, _admin: User = Depends(require_admin)):
    patch: dict = {}
    if body.session_active_persist_interval_minutes is not None:
        patch["session_active_persist_interval_minutes"] = body.session_active_persist_interval_minutes
    if body.rag_pool_ceiling_mode is not None:
        patch["rag_pool_ceiling_mode"] = body.rag_pool_ceiling_mode
    if body.rag_pool_ceiling_map is not None:
        patch["rag_pool_ceiling_map"] = body.rag_pool_ceiling_map
    data = save_system_settings(patch) if patch else load_system_settings()
    return SystemSettingsResponse(
        session_active_persist_interval_minutes=int(data["session_active_persist_interval_minutes"]),
        rag_pool_ceiling_mode=str(data.get("rag_pool_ceiling_mode", "smart")),  # type: ignore[arg-type]
        rag_pool_ceiling_map=str(data.get("rag_pool_ceiling_map", DEFAULT_POOL_CEILING_MAP)),
    )
