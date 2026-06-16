"""多模态文档处理任务 API — 任务列表+进度+日志+SSE。

对齐 web_rebuild_v2 /api/process/queue 和 /api/process/logs/{task_id}
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import KnowledgeBase, KnowledgeDocument, User
from app.services.haici_output import kb_assets_dir
from app.services.multimodal_pipeline import run_ingest_in_background
from app.services.multimodal_task_manager import (
    cancel_task,
    create_task,
    get_task,
    list_tasks,
    load_from_disk,
    update_task,
)
from app.vectorstore import delete_by_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/multimodal-tasks", tags=["多模态任务"])

ALLOWED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".pdf",
    ".doc", ".docx", ".csv",
    ".xls", ".xlsx", ".ppt", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
}


class TaskListItem(BaseModel):
    task_id: str
    filename: str
    status: str
    progress: int
    stage: str
    stage_label: str
    error: str | None
    output_dir: str
    output_md: str
    document_id: int | None
    created_at: str
    completed_at: str | None


# 启动时恢复任务
load_from_disk()


@router.post("/upload")
async def upload_and_process(
    file: UploadFile = File(...),
    slice_method: str = Form(default="auto"),
    kb_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """上传文档并立即返回 task_id；MD 标准化在后台执行，前端可轮询/SSE 跟踪日志。"""
    settings.ensure_dirs()
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    from app.services.filename_utils import normalize_upload_filename

    safe_filename = normalize_upload_filename(file.filename)
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    if kb_id is not None:
        kb = db.get(KnowledgeBase, kb_id)
        if not kb or kb.user_id != current_user.id:
            raise HTTPException(status_code=400, detail="知识库不存在")
    else:
        default_kb = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.user_id == current_user.id, KnowledgeBase.is_default == 1)
            .first()
        )
        if default_kb:
            kb_id = default_kb.id

    mode = (slice_method or settings.KB_DEFAULT_SLICE_METHOD).strip() or "auto"
    path = Path(settings.UPLOAD_DIR) / f"{uuid.uuid4().hex}{suffix}"
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    doc = KnowledgeDocument(
        user_id=current_user.id,
        kb_id=kb_id,
        filename=safe_filename,
        storage_path=str(path),
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    task = create_task(
        filename=doc.filename,
        file_path=str(path),
        document_id=doc.id,
        tenant_id=current_user.id,
    )
    task_id = task["task_id"]
    update_task(task_id, status="running", stage="upload", stage_label="文件已接收，排队处理")

    run_ingest_in_background(
        task_id=task_id,
        file_path=path,
        document_id=doc.id,
        document_name=doc.filename,
        tenant_id=current_user.id,
        slice_method=mode,
    )

    logger.info(
        "[多模态文档-MD改造|multimodal_tasks.upload_and_process|doc_id=%s|硬编执行|已入队] task_id=%s; file=%s",
        doc.id,
        task_id,
        doc.filename,
    )
    return {
        "ok": True,
        "task_id": task_id,
        "document_id": doc.id,
        "filename": doc.filename,
        "status": "running",
    }


@router.get("")
def get_tasks(
    status: str = Query("", description="筛选状态 pending/running/completed/failed/cancelled"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """获取当前用户的多模态任务列表"""
    tasks = list_tasks(status=status, limit=limit, tenant_id=current_user.id)
    return {
        "ok": True,
        "tasks": [
            {
                "task_id": t["task_id"],
                "filename": t["filename"],
                "status": t["status"],
                "progress": t["progress"],
                "stage": t["stage"],
                "stage_label": t["stage_label"],
                "pipeline_stages": t.get("pipeline_stages", {}),
                "error": t.get("error"),
                "output_dir": t.get("output_dir", ""),
                "output_md": t.get("output_md", ""),
                "output_manifest": t.get("output_manifest", ""),
                "document_id": t.get("document_id"),
                "created_at": t["created_at"],
                "completed_at": t.get("completed_at"),
                "log_count": len(t.get("logs", [])),
            }
            for t in tasks
        ],
    }


@router.get("/{task_id}")
def get_task_detail(task_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """获取任务详情（含完整日志和阶段状态）"""
    t = get_task(task_id)
    if not t or t.get("tenant_id") != current_user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "ok": True,
        "task": {
            "task_id": t["task_id"],
            "filename": t["filename"],
            "file_path": t["file_path"],
            "status": t["status"],
            "progress": t["progress"],
            "stage": t["stage"],
            "stage_label": t["stage_label"],
            "pipeline_stages": t.get("pipeline_stages", {}),
            "error": t.get("error"),
            "error_stage": t.get("error_stage"),
            "output_dir": t.get("output_dir", ""),
            "output_md": t.get("output_md", ""),
            "output_txt": t.get("output_txt", ""),
            "output_manifest": t.get("output_manifest", ""),
            "document_id": t.get("document_id"),
            "created_at": t["created_at"],
            "completed_at": t.get("completed_at"),
            "logs": t.get("logs", [])[-100:],
        },
    }


@router.get("/{task_id}/logs")
async def stream_task_logs(task_id: str):
    """SSE 流式推送任务日志和进度（鉴权走中间件 ?token= 或 Bearer）。"""
    t = get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def generator():
        last_log_idx = 0
        last_progress = -1
        last_status = ""
        timeout = 120
        start = time.time()

        while time.time() - start < timeout:
            t = get_task(task_id)
            if not t:
                break

            # 发送新日志
            logs = t.get("logs", [])
            while last_log_idx < len(logs):
                entry = logs[last_log_idx]
                yield f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
                last_log_idx += 1

            # 进度变化
            current_progress = t.get("progress", 0)
            current_status = t.get("status", "")
            if current_progress != last_progress or current_status != last_status:
                yield f"event: progress\ndata: {json.dumps({'progress': current_progress, 'status': current_status, 'stage': t.get('stage_label', ''), 'pipeline_stages': t.get('pipeline_stages', {})}, ensure_ascii=False)}\n\n"
                last_progress = current_progress
                last_status = current_status

            # 完成/失败时发送最终事件
            if current_status in ("completed", "failed"):
                yield f"event: {current_status}\ndata: {json.dumps({'task_id': task_id, 'status': current_status, 'progress': current_progress}, ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.delete("/{task_id}")
def remove_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """取消/删除任务；运行中会停止后台处理并清理 processing 状态的关联文档。"""
    t = get_task(task_id)
    if not t or t.get("tenant_id") != current_user.id:
        raise HTTPException(status_code=404, detail="任务不存在")

    was_active = t.get("status") in ("pending", "running")
    doc_id = t.get("document_id")

    ok = cancel_task(task_id)

    if doc_id and was_active:
        doc = db.get(KnowledgeDocument, doc_id)
        if doc and doc.user_id == current_user.id and doc.status == "processing":
            delete_by_document(doc_id, tenant_id=str(current_user.id))
            try:
                Path(doc.storage_path).unlink(missing_ok=True)
            except OSError:
                pass
            asset_root = kb_assets_dir(current_user.id, doc_id)
            if asset_root.is_dir():
                shutil.rmtree(asset_root, ignore_errors=True)
            db.delete(doc)
            db.commit()
            logger.info(
                "[多模态文档-任务取消|multimodal_tasks.remove_task|doc_id=%s|硬编执行|已清理] task_id=%s",
                doc_id,
                task_id,
            )

    return {"ok": ok, "cancelled": was_active}
