import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import KnowledgeDocument, User
from app.schemas import KnowledgeDocumentItem
from app.services.knowledge_processor import read_document_text, split_to_documents
from app.vectorstore import add_documents, delete_by_document

router = APIRouter(prefix="/knowledge", tags=["知识库"])
ALLOWED = {".txt", ".md", ".pdf"}


@router.get("", response_model=list[KnowledgeDocumentItem])
def list_docs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.user_id == current_user.id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )


@router.post("/upload", response_model=KnowledgeDocumentItem)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings.ensure_dirs()
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail="仅支持 .txt / .md / .pdf")
    path = Path(settings.UPLOAD_DIR) / f"{uuid.uuid4().hex}{suffix}"
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    doc = KnowledgeDocument(
        user_id=current_user.id,
        filename=file.filename,
        storage_path=str(path),
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        text = read_document_text(path)
        chunks = split_to_documents(text, doc.id, doc.filename)
        count = add_documents(chunks, tenant_id=str(current_user.id))
        doc.status = "ready"
        doc.chunk_count = count
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.error_message = str(exc)[:500]
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{document_id}")
def delete_doc(document_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.get(KnowledgeDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    delete_by_document(document_id, tenant_id=str(current_user.id))
    Path(doc.storage_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return {"ok": True}
