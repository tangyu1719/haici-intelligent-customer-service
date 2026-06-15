from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import settings
from app.deps import get_current_user
from app.services.llm_gateway import get_llm_gateway
from app.services.platform_health import run_platform_health

router = APIRouter(prefix="/system", tags=["系统"])


class FallbackUpdateBody(BaseModel):
    content: str


@router.get("/settings/fallback")
def get_fallback(_user=Depends(get_current_user)):
    """获取兜底话术模板"""
    return {"ok": True, "content": settings.FALLBACK_NO_CONTEXT}


@router.put("/settings/fallback")
def update_fallback(body: FallbackUpdateBody, _user=Depends(get_current_user)):
    """更新兜底话术模板（运行时生效，重启后恢复为环境变量或默认值）"""
    if body.content.strip():
        settings.FALLBACK_NO_CONTEXT = body.content.strip()
    return {"ok": True, "content": settings.FALLBACK_NO_CONTEXT}


@router.get("/llm-gateway")
def llm_gateway_status(_user=Depends(get_current_user)):
    return get_llm_gateway().public_snapshot()


@router.get("/platform/health")
def platform_health(
    refresh: int = Query(0, ge=0, le=1),
    probe_llm: int = Query(1, ge=0, le=1),
    _user=Depends(get_current_user),
):
    _ = refresh
    return run_platform_health(probe_llm=bool(probe_llm))
