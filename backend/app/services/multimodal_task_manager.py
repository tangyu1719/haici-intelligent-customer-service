"""多模态文档处理任务管理器 — 文件粒度任务+进度+日志+中间产物。

模仿 web_rebuild_v2/task_manager.py 的 Pipeline 任务模式。
每个上传的文档创建一个独立任务，跟踪所有处理步骤。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TASK_STORE_FILE = BACKEND_ROOT / "data" / "multimodal_tasks.json"

_tasks: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
# 取消标记独立于任务记录，避免 UI 删除后后台线程无法感知
_cancel_flags: dict[str, bool] = {}


class TaskCancelledError(Exception):
    """用户主动取消多模态处理任务。"""


def is_cancel_requested(task_id: str) -> bool:
    if not task_id:
        return False
    if _cancel_flags.get(task_id):
        return True
    task = _tasks.get(task_id)
    return bool(task and task.get("status") == "cancelled")


def ensure_not_cancelled(task_id: str) -> None:
    if is_cancel_requested(task_id):
        raise TaskCancelledError(f"任务 {task_id} 已被用户取消")


def request_cancel(task_id: str) -> bool:
    """请求取消任务（运行中任务会在流水线检查点退出）。"""
    task = _tasks.get(task_id)
    if not task:
        _cancel_flags[task_id] = True
        return False
    _cancel_flags[task_id] = True
    if task.get("status") in ("pending", "running"):
        now = datetime.now(timezone.utc).isoformat()
        task["status"] = "cancelled"
        task["stage_label"] = "用户已取消"
        task["updated_at"] = now
        task["completed_at"] = now
        add_log(task_id, "用户已请求取消，正在停止后台处理…", "WARN")
        with _lock:
            _persist()
        logger.info(
            "[多模态文档-任务取消|multimodal_task_manager.request_cancel|task_id=%s|硬编执行|已标记] status=cancelled",
            task_id,
        )
        return True
    return False


def clear_cancel_flag(task_id: str) -> None:
    _cancel_flags.pop(task_id, None)

# ── 文档处理阶段定义 ──────────────────────────────────────

PIPELINE_STAGES: list[dict[str, str]] = [
    {"id": "upload", "label": "文件上传", "progress_range": "0-10"},
    {"id": "inspect", "label": "文档检查（类型/大小/页数）", "progress_range": "10-15"},
    {"id": "normalize", "label": "文档标准化（PDF→MD / DOCX→MD）", "progress_range": "15-40"},
    {"id": "extract_images", "label": "图片提取与分类", "progress_range": "40-50"},
    {"id": "ocr", "label": "OCR 文字识别", "progress_range": "50-60"},
    {"id": "vlm_describe", "label": "VLM 图片描述", "progress_range": "60-75"},
    {"id": "assemble_md", "label": "Markdown 组装（图片→文字回插）", "progress_range": "75-85"},
    {"id": "chunk", "label": "分块切割", "progress_range": "85-92"},
    {"id": "vectorize", "label": "向量化存储", "progress_range": "92-98"},
    {"id": "complete", "label": "完成", "progress_range": "98-100"},
]

STAGE_PROGRESS: dict[str, int] = {
    "upload": 5, "inspect": 12, "normalize": 30,
    "extract_images": 45, "ocr": 55, "vlm_describe": 70,
    "assemble_md": 80, "chunk": 88, "vectorize": 95, "complete": 100,
}


def create_task(filename: str, file_path: str, **meta: Any) -> dict[str, Any]:
    """创建一个新任务"""
    task_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    task: dict[str, Any] = {
        "task_id": task_id,
        "filename": filename,
        "file_path": file_path,
        "status": "pending",
        "progress": 0,
        "stage": "",
        "stage_label": "等待处理",
        "pipeline_stages": {},
        "output_dir": "",
        "output_md": "",
        "output_txt": "",
        "output_manifest": "",
        "logs": [],
        "error": None,
        "error_stage": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "queue_seq": len(_tasks),
        "document_id": None,  # 关联的 KnowledgeDocument ID
        **meta,
    }
    # 初始化所有阶段
    for s in PIPELINE_STAGES:
        task["pipeline_stages"][s["id"]] = {
            "status": "pending", "label": s["label"],
            "started_at": None, "completed_at": None,
            "result": None, "error": None,
        }
    with _lock:
        _tasks[task_id] = task
        _persist()
    logger.info(f"[多模态任务] 创建 task_id={task_id}; file={filename}")
    return task


def get_task(task_id: str) -> dict[str, Any] | None:
    return _tasks.get(task_id)


def list_tasks(
    status: str = "",
    limit: int = 50,
    tenant_id: int | None = None,
) -> list[dict[str, Any]]:
    """列出任务，按创建时间倒序；可按用户 tenant_id 过滤。"""
    with _lock:
        tasks = list(_tasks.values())
    if tenant_id is not None:
        tasks = [t for t in tasks if t.get("tenant_id") == tenant_id]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    tasks.sort(key=lambda t: t["created_at"], reverse=True)
    return tasks[:limit]


def update_task(task_id: str, **kwargs: Any) -> None:
    """更新任务字段"""
    task = _tasks.get(task_id)
    if not task or task["status"] in ("completed", "cancelled"):
        return
    if is_cancel_requested(task_id):
        return
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    task.update(kwargs)
    with _lock:
        _persist()


def start_stage(task_id: str, stage_id: str) -> None:
    """标记一个处理阶段开始"""
    if is_cancel_requested(task_id):
        return
    task = _tasks.get(task_id)
    if not task:
        return
    now = datetime.now(timezone.utc).isoformat()
    stage = task["pipeline_stages"].get(stage_id, {})
    stage["status"] = "in_progress"
    stage["started_at"] = now
    # 找阶段定义
    label = stage.get("label", stage_id)
    for s in PIPELINE_STAGES:
        if s["id"] == stage_id:
            label = s["label"]; break
    progress = STAGE_PROGRESS.get(stage_id, 0)
    update_task(task_id, status="running", progress=progress,
                stage=stage_id, stage_label=label)
    add_log(task_id, f"[开始] {label}")


def complete_stage(task_id: str, stage_id: str, result: Any = None) -> None:
    """标记一个处理阶段完成"""
    task = _tasks.get(task_id)
    if not task:
        return
    now = datetime.now(timezone.utc).isoformat()
    stage = task["pipeline_stages"].get(stage_id, {})
    stage["status"] = "completed"
    stage["completed_at"] = now
    stage["result"] = result
    label = stage.get("label", stage_id)
    progress = STAGE_PROGRESS.get(stage_id, task["progress"])
    update_task(task_id, progress=progress)
    add_log(task_id, f"[完成] {label}")
    if stage_id == "complete":
        update_task(task_id, status="completed", progress=100,
                    stage_label="处理完成", completed_at=now)


def fail_stage(task_id: str, stage_id: str, error: str) -> None:
    """标记阶段失败"""
    task = _tasks.get(task_id)
    if not task:
        return
    now = datetime.now(timezone.utc).isoformat()
    stage = task["pipeline_stages"].get(stage_id, {})
    stage["status"] = "failed"
    stage["error"] = error
    label = stage.get("label", stage_id)
    update_task(task_id, status="failed", error=error,
                error_stage=stage_id, stage_label=f"失败: {label}")
    add_log(task_id, f"[失败] {label}: {error}", "ERROR")


def add_log(task_id: str, message: str, level: str = "INFO") -> None:
    """向任务追加日志"""
    task = _tasks.get(task_id)
    if not task:
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    task["logs"].append(entry)
    if len(task["logs"]) > 500:
        task["logs"] = task["logs"][-500:]
    with _lock:
        _persist()


def cancel_task(task_id: str) -> bool:
    """取消并移除任务记录；运行中任务保留取消标记供后台线程退出。"""
    was_active = request_cancel(task_id)
    return delete_task(task_id, keep_cancel_flag=was_active)


def delete_task(task_id: str, *, keep_cancel_flag: bool = False) -> bool:
    with _lock:
        if task_id in _tasks:
            del _tasks[task_id]
            _persist()
            if not keep_cancel_flag:
                clear_cancel_flag(task_id)
            return True
    if not keep_cancel_flag:
        clear_cancel_flag(task_id)
    return False


def _persist() -> None:
    try:
        TASK_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TASK_STORE_FILE.write_text(json.dumps(
            list(_tasks.values()), ensure_ascii=False, indent=2
        ), encoding="utf-8")
    except OSError as e:
        logger.warning(f"[多模态任务] 持久化失败: {e}")


def load_from_disk() -> None:
    """启动时从磁盘恢复任务"""
    if not TASK_STORE_FILE.is_file():
        return
    try:
        data = json.loads(TASK_STORE_FILE.read_text(encoding="utf-8"))
        with _lock:
            for t in data:
                if isinstance(t, dict) and "task_id" in t:
                    _tasks[t["task_id"]] = t
        logger.info(f"[多模态任务] 恢复 {len(_tasks)} 个历史任务")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[多模态任务] 恢复失败: {e}")
