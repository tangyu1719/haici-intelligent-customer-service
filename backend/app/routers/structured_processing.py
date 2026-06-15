"""结构化处理 API — 摘要整理 + 元数据提取 + 结构化检查。

属于多模态处理链路的一环：
- 摘要整理：用AI提取文档核心主题描述（不是具体内容，是"讲了什么"）
- 元数据提取：用户定义JSON字段模板 → AI自动填充 → 人工确认修改
- 结构化检查：判断文档是否已有清晰结构，决定是否需要重整理
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/structured", tags=["结构化处理"])

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "data"
_CONFIG_PATH = _CONFIG_DIR / "structured_config.json"


# ── 配置IO ────────────────────────────────────────────────

def _load_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return _default_config()
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_config()


def _save_config(data: dict[str, Any]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_config() -> dict[str, Any]:
    from app.services.prompt_segments import build_doc_summary_default_prompt, build_doc_structure_check_default_prompt

    return {
        "summary": {
            "enabled": True,
            "prompt": build_doc_summary_default_prompt(),
            "max_length": 200,
        },
        "metadata": {
            "enabled": True,
            "fields": [
                {"key": "doc_type", "label": "文档类型", "description": "如：产品手册/技术文档/FAQ/政策文件/聊天记录/其他"},
                {"key": "department", "label": "所属部门", "description": "如：产品部/技术部/客服部/市场部"},
                {"key": "target_audience", "label": "目标读者", "description": "如：内部员工/客户/合作伙伴/开发者"},
                {"key": "effective_date", "label": "生效日期", "description": "文档的生效或发布日期，格式YYYY-MM-DD"},
                {"key": "version", "label": "版本号", "description": "如：v1.0 / v2.3"},
            ],
        },
        "structure_check": {
            "enabled": True,
            "prompt": build_doc_structure_check_default_prompt(),
            "min_size_bytes": 100,
            "max_images_check": 50,
        },
    }


# ── 请求/响应模型 ──────────────────────────────────────────


class SummaryConfig(BaseModel):
    enabled: bool = True
    prompt: str = ""
    max_length: int = Field(default=200, ge=50, le=1000)


class MetadataField(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=256)


class MetadataConfig(BaseModel):
    enabled: bool = True
    fields: list[MetadataField] = Field(default_factory=list)


class StructureCheckConfig(BaseModel):
    enabled: bool = True
    prompt: str = ""
    min_size_bytes: int = 100
    max_images_check: int = 50


class FullConfigResponse(BaseModel):
    summary: dict[str, Any]
    metadata: dict[str, Any]
    structure_check: dict[str, Any]


class SaveSummaryBody(BaseModel):
    enabled: bool | None = None
    prompt: str | None = None
    max_length: int | None = None


class SaveMetadataBody(BaseModel):
    enabled: bool | None = None
    fields: list[MetadataField] | None = None


class SaveStructureCheckBody(BaseModel):
    enabled: bool | None = None
    prompt: str | None = None
    min_size_bytes: int | None = None
    max_images_check: int | None = None


# ── API 端点 ────────────────────────────────────────────────


@router.get("/config", response_model=FullConfigResponse)
def get_config(_user=Depends(get_current_user)):
    """获取结构化处理全部配置"""
    cfg = _load_config()
    return FullConfigResponse(
        summary=cfg.get("summary", {}),
        metadata=cfg.get("metadata", {}),
        structure_check=cfg.get("structure_check", {}),
    )


# ── 摘要整理 ──

@router.put("/summary")
def save_summary(body: SaveSummaryBody, _user=Depends(get_current_user)):
    """保存摘要整理配置"""
    cfg = _load_config()
    summary = cfg.get("summary", {})
    if body.enabled is not None:
        summary["enabled"] = body.enabled
    if body.prompt is not None:
        summary["prompt"] = body.prompt
    if body.max_length is not None:
        summary["max_length"] = body.max_length
    cfg["summary"] = summary
    _save_config(cfg)
    return {"ok": True, "summary": summary}


# ── 元数据提取 ──

@router.put("/metadata")
def save_metadata(body: SaveMetadataBody, _user=Depends(get_current_user)):
    """保存元数据配置"""
    cfg = _load_config()
    metadata = cfg.get("metadata", {})
    if body.enabled is not None:
        metadata["enabled"] = body.enabled
    if body.fields is not None:
        metadata["fields"] = [f.model_dump() for f in body.fields]
    cfg["metadata"] = metadata
    _save_config(cfg)
    return {"ok": True, "metadata": metadata}


@router.post("/metadata/extract")
def extract_metadata(
    document_id: int,
    _user=Depends(get_current_user),
):
    """对指定文档执行 AI 元数据提取（需 DocumentProcessor 支持）"""
    # 此端点由 Pipeline 调用，先返回配置让前端确认
    cfg = _load_config()
    fields = cfg.get("metadata", {}).get("fields", [])
    return {
        "ok": True,
        "document_id": document_id,
        "fields_template": fields,
        "message": "元数据提取需在结构化处理 Pipeline 中执行，此端点返回字段模板供前端展示",
    }


# ── 结构化检查 ──

@router.put("/structure-check")
def save_structure_check(body: SaveStructureCheckBody, _user=Depends(get_current_user)):
    """保存结构化检查配置"""
    cfg = _load_config()
    sc = cfg.get("structure_check", {})
    if body.enabled is not None:
        sc["enabled"] = body.enabled
    if body.prompt is not None:
        sc["prompt"] = body.prompt
    if body.min_size_bytes is not None:
        sc["min_size_bytes"] = body.min_size_bytes
    if body.max_images_check is not None:
        sc["max_images_check"] = body.max_images_check
    cfg["structure_check"] = sc
    _save_config(cfg)
    return {"ok": True, "structure_check": sc}


@router.post("/structure-check/run")
def run_structure_check(document_id: int, _user=Depends(get_current_user)):
    """对指定文档执行结构化检查"""
    cfg = _load_config()
    sc = cfg.get("structure_check", {})
    return {
        "ok": True,
        "document_id": document_id,
        "config": {
            "enabled": sc.get("enabled"),
            "min_size_bytes": sc.get("min_size_bytes"),
            "max_images_check": sc.get("max_images_check"),
        },
        "message": "结构化检查将在文档导入后自动执行",
    }
