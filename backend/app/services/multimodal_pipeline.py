"""多模态文档后台处理：创建任务后立即返回，流水线在后台跑并写日志。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.database import SessionLocal
from app.models import KnowledgeDocument
from app.services.knowledge_processor import ingest_uploaded_document
from app.services.multimodal_task_manager import (
    TaskCancelledError,
    add_log,
    clear_cancel_flag,
    fail_stage,
    get_task,
    update_task,
)

logger = logging.getLogger(__name__)


def run_ingest_in_background(
    *,
    task_id: str,
    file_path: Path,
    document_id: int,
    document_name: str,
    tenant_id: int,
    slice_method: str,
) -> None:
    """后台线程执行 MD 标准化 + 分块 + 向量化，并推送任务日志。"""

    def _worker() -> None:
        db = SessionLocal()
        try:
            add_log(task_id, f"后台任务启动: {document_name}")
            update_task(task_id, status="running")
            summary = ingest_uploaded_document(
                file_path,
                document_id=document_id,
                document_name=document_name,
                tenant_id=tenant_id,
                slice_method=slice_method,
                task_id=task_id,
            )
            doc = db.get(KnowledgeDocument, document_id)
            if doc:
                doc.status = "ready"
                doc.chunk_count = int(summary.get("chunk_count") or 0)
                doc.error_message = None
                db.commit()
            add_log(task_id, f"处理完成: 分块 {summary.get('chunk_count', 0)} 条")
            logger.info(
                "[多模态文档-MD改造|multimodal_pipeline.run_ingest_in_background|doc_id=%s|Agent执行|完成] task_id=%s; chunks=%s",
                document_id,
                task_id,
                summary.get("chunk_count"),
            )
        except TaskCancelledError as exc:
            err = str(exc)[:500]
            logger.info(
                "[多模态文档-MD改造|multimodal_pipeline.run_ingest_in_background|doc_id=%s|硬编执行|用户取消] task_id=%s",
                document_id,
                task_id,
            )
            try:
                doc = db.get(KnowledgeDocument, document_id)
                if doc and doc.status == "processing":
                    doc.status = "failed"
                    doc.error_message = "用户已取消处理"
                    db.commit()
            except Exception:
                db.rollback()
            add_log(task_id, "任务已被用户取消", "WARN")
            update_task(task_id, status="cancelled", stage_label="用户已取消", error=err[:300])
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:500]
            logger.exception(
                "[多模态文档-MD改造|multimodal_pipeline.run_ingest_in_background|doc_id=%s|Agent执行|失败] task_id=%s; err=%s",
                document_id,
                task_id,
                err[:200],
            )
            try:
                doc = db.get(KnowledgeDocument, document_id)
                if doc:
                    doc.status = "failed"
                    doc.error_message = err
                    db.commit()
            except Exception:
                db.rollback()
            if task_id and not (get_task(task_id) or {}).get("error"):
                fail_stage(task_id, "vectorize", err[:2000])
        finally:
            clear_cancel_flag(task_id)
            db.close()

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f"mm-ingest-{task_id}",
    ).start()
