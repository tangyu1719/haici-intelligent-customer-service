import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import KnowledgeBase, KnowledgeDocument, User
from app.schemas import KnowledgeDocumentItem, KnowledgePageResponse
from app.services.list_query import (
    ListQuery,
    apply_date_range,
    apply_id_filter,
    apply_keyword,
    apply_like,
    apply_sort,
    list_query_params,
    page_result,
    paginate,
)
from app.services.haici_output import kb_assets_dir
from app.services.knowledge_processor import ingest_uploaded_document
from app.vectorstore import delete_by_document

router = APIRouter(prefix="/knowledge", tags=["知识库"])
ALLOWED = {
    ".txt", ".md", ".markdown", ".pdf",
    ".doc", ".docx", ".csv",
    ".xls", ".xlsx", ".ppt", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
}


class ChunkPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    slice_method: str = "auto"
    chunk_size: int = Field(default=500, ge=100, le=4000)
    overlap: int = Field(default=80, ge=0, le=800)
    max_tokens: int = Field(default=350, ge=50, le=2000)
    dynamic_max_chars: int = Field(default=800, ge=200, le=4000)


def _load_manifest(tenant_id: int, doc_id: int) -> dict | None:
    mp = kb_assets_dir(tenant_id, doc_id) / "manifest.json"
    if not mp.is_file():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _doc_to_item(doc: KnowledgeDocument) -> KnowledgeDocumentItem:
    manifest = _load_manifest(doc.user_id, doc.id)
    inspect = (manifest or {}).get("inspect") or {}
    path = Path(doc.storage_path)
    file_size = path.stat().st_size if path.is_file() else 0
    kb_name = None
    if doc.kb_id:
        from app.database import SessionLocal
        _db = SessionLocal()
        try:
            _kb = _db.get(KnowledgeBase, doc.kb_id)
            if _kb:
                kb_name = _kb.name
        finally:
            _db.close()
    return KnowledgeDocumentItem(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        file_type=inspect.get("file_type") or path.suffix.lstrip(".") or "unknown",
        file_size_bytes=int(inspect.get("file_size_bytes") or file_size),
        file_size_human=inspect.get("file_size_human") or "",
        image_count=int((manifest or {}).get("image_count") or inspect.get("processed_image_count") or inspect.get("estimated_image_count") or 0),
        vlm_limit=int((manifest or {}).get("vlm_limit") or settings.MAX_IMAGES_PER_DOC),
        truncated=bool((manifest or {}).get("truncated")),
        assets_dir=str(kb_assets_dir(doc.user_id, doc.id)) if manifest else None,
        kb_id=doc.kb_id,
        kb_name=kb_name,
    )


@router.get("/config")
def kb_config(_user: User = Depends(get_current_user)):
    return {
        "ok": True,
        "max_images_per_doc": settings.MAX_IMAGES_PER_DOC,
        "vlm_image_enabled": settings.VLM_IMAGE_ENABLED,
        "baidu_ocr_enabled": settings.BAIDU_OCR_ENABLED,
        "normalize_enabled": settings.KB_NORMALIZE_ENABLED,
    }


@router.get("/slice-methods")
def list_slice_methods(_user: User = Depends(get_current_user)):
    from app.services.kb_chunk_service import list_slice_methods as _list

    return {"ok": True, "default": settings.KB_DEFAULT_SLICE_METHOD, "methods": _list()}


@router.post("/chunk-preview")
def chunk_preview(body: ChunkPreviewRequest, _user: User = Depends(get_current_user)):
    from app.services.kb_chunk_service import chunk_text_with_meta

    stats = chunk_text_with_meta(
        body.text,
        mode=body.slice_method,
        chunk_size=body.chunk_size,
        overlap=body.overlap,
        max_tokens=body.max_tokens,
        dynamic_max_chars=body.dynamic_max_chars,
        source="preview",
    )
    return {"ok": True, **stats}


@router.get("", response_model=KnowledgePageResponse)
def list_docs(
    qry: ListQuery = Depends(list_query_params),
    status: str = Query("", description="文档状态 processing|ready|failed"),
    kb_id: int | None = Query(None, description="按知识库ID筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == current_user.id)
    q = apply_id_filter(q, KnowledgeDocument.id, qry)
    if qry.name:
        q = apply_like(q, KnowledgeDocument.filename, qry.name)
    q = apply_keyword(q, qry, [KnowledgeDocument.filename])
    q = apply_date_range(q, KnowledgeDocument.created_at, qry)
    st = (status or "").strip()
    if st:
        q = q.filter(KnowledgeDocument.status == st)
    if kb_id is not None:
        q = q.filter(KnowledgeDocument.kb_id == kb_id)
    sort_map = {
        "id": KnowledgeDocument.id,
        "filename": KnowledgeDocument.filename,
        "created_at": KnowledgeDocument.created_at,
        "updated_at": KnowledgeDocument.updated_at,
        "status": KnowledgeDocument.status,
        "chunk_count": KnowledgeDocument.chunk_count,
    }
    q = apply_sort(q, KnowledgeDocument, qry, sort_map, KnowledgeDocument.created_at)
    rows, total = paginate(q, qry)
    return KnowledgePageResponse(**page_result([_doc_to_item(d) for d in rows], total, qry))


@router.get("/{document_id}/manifest")
def get_manifest(document_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.get(KnowledgeDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    manifest = _load_manifest(current_user.id, document_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="暂无标准化 manifest")
    return {"ok": True, "manifest": manifest}


@router.get("/{document_id}/normalized")
def get_normalized(document_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.get(KnowledgeDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    md_path = kb_assets_dir(current_user.id, document_id) / "normalized.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="暂无标准化 Markdown")
    return {"ok": True, "path": str(md_path), "content": md_path.read_text(encoding="utf-8", errors="ignore")}


@router.get("/{document_id}/assets")
def get_assets(document_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """SPEC §3.5：返回 manifest 与图片 public_url 列表。"""
    doc = db.get(KnowledgeDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    manifest = _load_manifest(current_user.id, document_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="暂无标准化产物")
    images = manifest.get("images") or []
    return {
        "ok": True,
        "assets_dir": str(kb_assets_dir(current_user.id, document_id)),
        "manifest": manifest,
        "images": [
            {
                "image_id": img.get("image_id"),
                "public_url": img.get("public_url"),
                "image_type": img.get("image_type"),
                "pipeline": img.get("pipeline"),
            }
            for img in images
        ],
    }


@router.post("/upload", response_model=KnowledgeDocumentItem)
async def upload(
    file: UploadFile = File(...),
    slice_method: str = Form(default=""),
    kb_id: int | None = Form(default=None, description="关联的知识库ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings.ensure_dirs()
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail="不支持的文件格式，请使用文本/PDF/Office/图片等常见文档")

    # 验证 kb_id 归属
    if kb_id is not None:
        kb = db.get(KnowledgeBase, kb_id)
        if not kb or kb.user_id != current_user.id:
            raise HTTPException(status_code=400, detail="知识库不存在")
    else:
        # 未指定时自动关联默认知识库
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
        filename=file.filename,
        storage_path=str(path),
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 创建多模态任务追踪
    from app.services.multimodal_task_manager import create_task, update_task
    task = create_task(filename=doc.filename, file_path=str(path),
                       document_id=doc.id, tenant_id=current_user.id)
    task_id = task["task_id"]
    update_task(task_id, status="running")

    try:
        summary = ingest_uploaded_document(
            path,
            document_id=doc.id,
            document_name=doc.filename,
            tenant_id=current_user.id,
            slice_method=mode,
            task_id=task_id,
        )
        doc.status = "ready"
        doc.chunk_count = int(summary.get("chunk_count") or 0)
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.error_message = str(exc)[:500]
        from app.services.multimodal_task_manager import update_task as _ut
        _ut(task_id, status="failed", error=str(exc)[:300])
    db.commit()
    db.refresh(doc)
    return _doc_to_item(doc)


@router.delete("/{document_id}")
def delete_doc(document_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.get(KnowledgeDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    delete_by_document(document_id, tenant_id=str(current_user.id))
    Path(doc.storage_path).unlink(missing_ok=True)
    asset_root = kb_assets_dir(current_user.id, document_id)
    if asset_root.is_dir():
        shutil.rmtree(asset_root, ignore_errors=True)
    db.delete(doc)
    db.commit()
    return {"ok": True}
