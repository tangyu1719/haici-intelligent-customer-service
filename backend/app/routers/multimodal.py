"""多模态文档处理（/api/doc/*）。"""



from __future__ import annotations



import logging

from pathlib import Path



from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from pydantic import BaseModel, Field



from app.deps import get_current_user

from app.models import User

from app.services.haici_output import get_output_dir, is_under_output_dir, mm_upload_dir

from app.services.multimodal_service import (

    detect_kind,

    kind_label,

    process_document_file,

    process_flowchart_file,

    save_text_upload,

)



logger = logging.getLogger(__name__)



router = APIRouter(prefix="/multimodal", tags=["多模态文档"])



_MM_UPLOAD_SUFFIXES = frozenset(

    {

        ".pdf", ".doc", ".docx", ".md", ".txt", ".markdown", ".csv",

        ".xlsx", ".xls", ".ppt", ".pptx",

        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",

        ".mp3", ".wav", ".m4a", ".flac", ".ogg",

    }

)

_MM_UPLOAD_MAX_BYTES = 100 * 1024 * 1024

_FS_WHITELIST = ("mm_uploads", "mm_exports", "kb_uploads", "flowchart_scoring_web", "mineru")





class ProcessBody(BaseModel):

    path: str

    export_md: bool = True

    export_txt: bool = True





class TextBody(BaseModel):

    title: str = Field(default="粘贴文本", max_length=120)

    content: str = Field(min_length=1, max_length=500_000)

    export_md: bool = True

    export_txt: bool = True

    process_now: bool = True





class FlowchartBody(BaseModel):

    path: str

    page: int = 1

    zoom: float = 2.0

    mineru_json: str = ""

    column_band_split: bool = True

    column_bands: int = 0

    min_band_h: int = 48

    skip_arrows: bool = True

    job_id: str = ""





def _resolve_readable_file(path_raw: str) -> Path:

    p = Path(path_raw).resolve()

    if not p.is_file():

        raise HTTPException(status_code=400, detail="路径无效或不是可读文件")

    if not is_under_output_dir(p):

        raise HTTPException(status_code=400, detail="仅允许访问 output 目录下的文件")

    return p





@router.get("/formats")

def supported_formats(_user: User = Depends(get_current_user)):

    from app.services.document import get_supported_formats



    return {

        "ok": True,

        "upload_suffixes": sorted(_MM_UPLOAD_SUFFIXES),

        "mineru_formats": get_supported_formats(),

        "pipelines": {

            "pdf": kind_label("pdf"),

            "docx": kind_label("docx"),

            "image": kind_label("image"),

            "text": kind_label("text"),

            "flowchart": "PDF/图片 → CV 分块得分 + 叠图预览（独立模式）",

        },

    }





@router.post("/upload")

async def upload(file: UploadFile = File(...), _user: User = Depends(get_current_user)):

    import uuid



    raw_name = Path(file.filename or "upload.bin").name

    suf = Path(raw_name).suffix.lower()

    if suf not in _MM_UPLOAD_SUFFIXES:

        raise HTTPException(status_code=400, detail=f"不支持的扩展名: {suf or '(无)'}")

    data = await file.read()

    if len(data) > _MM_UPLOAD_MAX_BYTES:

        raise HTTPException(status_code=400, detail="文件超过 100MB 上限")

    safe = "".join(c for c in raw_name if c.isalnum() or c in "._- ()[]")[:200] or "file.bin"

    dest = (mm_upload_dir() / f"{uuid.uuid4().hex[:14]}_{safe}").resolve()

    dest.write_bytes(data)

    kind = detect_kind(dest)

    return {

        "ok": True,

        "path": str(dest),

        "name": safe,

        "size": len(data),

        "kind": kind,

        "kind_label": kind_label(kind),

    }





@router.post("/text")

async def submit_text(body: TextBody, user: User = Depends(get_current_user)):

    """粘贴文本 → 落盘 mm_uploads → 可选立即标准化为 MD/TXT。"""

    try:

        path = save_text_upload(body.title, body.content)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc



    resp: dict = {

        "ok": True,

        "path": str(path),

        "name": path.name,

        "kind": "text",

        "kind_label": kind_label("text"),

    }

    if body.process_now:

        result = process_document_file(

            path,

            tenant_id=user.id,

            export_md=body.export_md,

            export_txt=body.export_txt,

        )

        resp["result"] = result

    return resp





@router.post("/process")

async def process(body: ProcessBody, user: User = Depends(get_current_user)):

    p = _resolve_readable_file(body.path)

    return process_document_file(

        p,

        tenant_id=user.id,

        export_md=body.export_md,

        export_txt=body.export_txt,

    )





@router.post("/flowchart/score")

async def flowchart_score(body: FlowchartBody, _user: User = Depends(get_current_user)):

    p = _resolve_readable_file(body.path)

    return process_flowchart_file(

        p,

        page=body.page,

        zoom=body.zoom,

        column_band_split=body.column_band_split,

        column_bands=body.column_bands,

        skip_arrows=body.skip_arrows,

        job_id=body.job_id,

    )





@router.get("/browse")

def browse(path: str = Query("", description="output 下相对路径")):

    root = get_output_dir().resolve()

    rel = (path or "").replace("\\", "/").strip().lstrip("/")

    target = (root / rel).resolve() if rel else root

    if not is_under_output_dir(target):

        raise HTTPException(status_code=400, detail="非法路径")

    if not target.exists():

        raise HTTPException(status_code=400, detail="路径不存在")

    if target.is_file():

        return {"ok": True, "path": str(target), "entries": []}

    entries = []

    try:

        for child in sorted(target.iterdir(), key=lambda x: x.name.lower()):

            if child.name.startswith("."):

                continue

            if child.is_dir() and child.name not in _FS_WHITELIST and rel == "":

                continue

            entries.append(

                {

                    "name": child.name,

                    "path": str(child.resolve()),

                    "is_dir": child.is_dir(),

                }

            )

    except OSError as exc:

        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True, "path": str(target), "entries": entries}





@router.get("/output-path")

def output_path(_user: User = Depends(get_current_user)):

    return {"ok": True, "path": str(get_output_dir())}


