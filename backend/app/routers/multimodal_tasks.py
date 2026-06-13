"""多模态文档处理任务 API — 任务列表+进度+日志+SSE。

对齐 web_rebuild_v2 /api/process/queue 和 /api/process/logs/{task_id}
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.deps import get_current_user
from app.services.multimodal_task_manager import (
    add_log,
    complete_stage,
    create_task,
    delete_task,
    fail_stage,
    get_task,
    list_tasks,
    start_stage,
    update_task,
    load_from_disk,
)

router = APIRouter(prefix="/multimodal-tasks", tags=["多模态任务"])


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


@router.get("")
def get_tasks(
    status: str = Query("", description="筛选状态 pending/running/completed/failed"),
    limit: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
) -> dict[str, Any]:
    """获取任务列表"""
    tasks = list_tasks(status=status, limit=limit)
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
def get_task_detail(task_id: str, _user=Depends(get_current_user)) -> dict[str, Any]:
    """获取任务详情（含完整日志和阶段状态）"""
    t = get_task(task_id)
    if not t:
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
async def stream_task_logs(task_id: str, _user=Depends(get_current_user)):
    """SSE 流式推送任务日志和进度"""
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
def remove_task(task_id: str, _user=Depends(get_current_user)) -> dict[str, Any]:
    """删除任务记录"""
    ok = delete_task(task_id)
    return {"ok": ok}
