from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user
from app.services.llm_gateway import get_llm_gateway
from app.services.platform_health import run_platform_health

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/llm-gateway")
def llm_gateway_status(_user=Depends(get_current_user)):
    """返回 LLM 网关接入点信息（脱敏），需登录。"""
    return get_llm_gateway().public_snapshot()


@router.get("/platform/health")
def platform_health(
    refresh: int = Query(0, ge=0, le=1),
    probe_llm: int = Query(1, ge=0, le=1),
    _user=Depends(get_current_user),
):
    """平台健康检查（对齐 web_rebuild /api/platform/health）。"""
    _ = refresh  # 预留强制刷新；当前每次均为实时探测
    return run_platform_health(probe_llm=bool(probe_llm))
