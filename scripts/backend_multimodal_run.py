# -*- coding: utf-8 -*-
"""后端直跑多模态文档：标准化 → 分块 → 向量化（可选）→ 导出 MD/TXT。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_PDF = PROJECT_ROOT / "RAG测试文档" / "库存调整单-提交.pdf"
EXPORT_DIR = PROJECT_ROOT / "output" / "multimodal_exports"


def _ensure_env() -> None:
    import os

    os.environ.setdefault("MYSQL_PORT", "3306")
    os.environ.setdefault("MYSQL_PASSWORD", "123456")
    os.environ.setdefault(
        "CHROMA_PERSIST_PATH",
        str(PROJECT_ROOT / ".run" / "chroma_persist"),
    )


def run_normalize_only(source: Path, tenant_id: int = 1, doc_id: int = 9999) -> dict:
    from app.services.doc_normalizer import normalize_document
    from app.services.haici_output import kb_assets_dir

    asset_root = kb_assets_dir(tenant_id, doc_id)
    if asset_root.is_dir():
        shutil.rmtree(asset_root, ignore_errors=True)
    t0 = time.perf_counter()
    result = normalize_document(
        source,
        tenant_id=tenant_id,
        doc_id=doc_id,
        document_name=source.name,
        task_id="",
    )
    elapsed = round(time.perf_counter() - t0, 2)
    out: dict = {
        "mode": "normalize_only",
        "ok": result.ok,
        "elapsed_sec": elapsed,
        "source": str(source),
        "assets_dir": result.assets_dir,
        "normalized_md": result.normalized_md_path,
        "error": result.error or "",
        "pipeline_note": (result.manifest or {}).get("pipeline_note", ""),
        "image_count": len((result.manifest or {}).get("images") or []),
    }
    if result.ok and result.normalized_md_path:
        md_path = Path(result.normalized_md_path)
        txt_path = md_path.parent / "normalized.txt"
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        stem = source.stem
        md_export = EXPORT_DIR / f"{stem}.normalized.md"
        txt_export = EXPORT_DIR / f"{stem}.normalized.txt"
        shutil.copy2(md_path, md_export)
        if txt_path.is_file():
            shutil.copy2(txt_path, txt_export)
        out["export_md"] = str(md_export)
        out["export_txt"] = str(txt_export)
        out["md_chars"] = md_path.read_text(encoding="utf-8").__len__()
    return out


def run_full_ingest(source: Path, tenant_id: int = 1) -> dict:
    """走完整入库链路（含向量化）。"""
    from app.database import SessionLocal
    from app.models import KnowledgeBase, KnowledgeDocument, User
    from app.services.knowledge_processor import ingest_uploaded_document
    from app.services.multimodal_task_manager import create_task, fail_stage, get_task, update_task

    _ensure_env()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        if not user:
            raise RuntimeError("未找到 admin 用户，请先初始化数据库")
        kb = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.user_id == user.id, KnowledgeBase.is_default == 1)
            .first()
        )
        kb_id = kb.id if kb else None

        import uuid

        upload_dir = BACKEND_ROOT / "data" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
        shutil.copy2(source, dest)

        doc = KnowledgeDocument(
            user_id=user.id,
            kb_id=kb_id,
            filename=source.name,
            storage_path=str(dest),
            status="processing",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        task = create_task(
            filename=doc.filename,
            file_path=str(dest),
            document_id=doc.id,
            tenant_id=user.id,
        )
        task_id = task["task_id"]
        update_task(task_id, status="running", stage="normalize", stage_label="后端直跑处理中")

        t0 = time.perf_counter()
        try:
            result = ingest_uploaded_document(
                dest,
                document_id=doc.id,
                document_name=doc.filename,
                tenant_id=user.id,
                slice_method="auto",
                task_id=task_id,
            )
            elapsed = round(time.perf_counter() - t0, 2)
            task_snap = get_task(task_id) or {}
            from app.services.haici_output import kb_assets_dir

            assets = kb_assets_dir(user.id, doc.id)
            md_path = assets / "normalized.md"
            txt_path = assets / "normalized.txt"
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            stem = source.stem
            md_export = txt_export = ""
            if md_path.is_file():
                md_export = str(EXPORT_DIR / f"{stem}.normalized.md")
                shutil.copy2(md_path, md_export)
            if txt_path.is_file():
                txt_export = str(EXPORT_DIR / f"{stem}.normalized.txt")
                shutil.copy2(txt_path, txt_export)

            doc.status = "ready"
            db.commit()

            return {
                "mode": "full_ingest",
                "ok": task_snap.get("status") == "completed",
                "elapsed_sec": elapsed,
                "task_id": task_id,
                "document_id": doc.id,
                "chunk_count": result.get("chunk_count", 0),
                "assets_dir": str(assets),
                "export_md": md_export,
                "export_txt": txt_export,
                "status": task_snap.get("status"),
                "error": task_snap.get("error") or "",
            }
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            fail_stage(task_id, "vectorize", err[:2000])
            db.rollback()
            return {
                "mode": "full_ingest",
                "ok": False,
                "task_id": task_id,
                "document_id": doc.id,
                "error": err,
            }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="后端直跑多模态 PDF/DOCX 处理")
    parser.add_argument(
        "file",
        nargs="?",
        default=str(DEFAULT_PDF),
        help="待处理文件路径",
    )
    parser.add_argument(
        "--mode",
        choices=("normalize", "full", "flowchart"),
        default="full",
        help="normalize=仅标准化; full=完整入库; flowchart=强制流程图 Mermaid 管道",
    )
    args = parser.parse_args()
    source = Path(args.file).resolve()
    if not source.is_file():
        print(json.dumps({"ok": False, "error": f"文件不存在: {source}"}, ensure_ascii=False))
        sys.exit(1)

    _ensure_env()
    if args.mode == "flowchart":
        os.environ["PDF_FLOWCHART_PIPELINE"] = "always"
    print(f"[backend_multimodal_run] 开始处理 {source.name} mode={args.mode} @ {datetime.now().isoformat()}")
    if args.mode in ("normalize", "flowchart"):
        report = run_normalize_only(source)
    else:
        report = run_full_ingest(source)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report.get("ok") else 1)


if __name__ == "__main__":
    main()
