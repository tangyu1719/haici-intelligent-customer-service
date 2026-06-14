"""多模态文档转化编排：PDF / DOCX / 图片 / 纯文本 / 流程图（对齐 SPEC + web_rebuild）。"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict

from app.services.haici_output import mm_export_dir, mm_upload_dir

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
DOCX_EXTS = frozenset({".docx", ".doc"})
TEXT_EXTS = frozenset({".txt", ".md", ".markdown"})
OFFICE_EXTS = frozenset({".xlsx", ".xls", ".pptx", ".ppt"})


def detect_kind(path: Path) -> str:
    sfx = path.suffix.lower()
    if sfx == ".pdf":
        return "pdf"
    if sfx in DOCX_EXTS:
        return "docx"
    if sfx in IMAGE_EXTS:
        return "image"
    if sfx in TEXT_EXTS:
        return "text"
    if sfx in OFFICE_EXTS:
        return "office"
    if sfx in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
        return "audio"
    if sfx == ".csv":
        return "csv"
    return "other"


def kind_label(kind: str) -> str:
    return {
        "pdf": "PDF（MinerU → MD/TXT，失败 PyMuPDF+OCR）",
        "docx": "Word（顺序解析 → 内嵌图 OCR/VLM）",
        "image": "图片（OCR + VLM 分类 → MD/TXT）",
        "text": "纯文本/Markdown（直接标准化）",
        "office": "Excel/PPT（抽图 + MinerU 降级）",
        "audio": "音频（转写文本）",
        "csv": "CSV（表格文本）",
        "other": "其他",
    }.get(kind, kind)


def save_text_upload(title: str, content: str) -> Path:
    """将粘贴文本落盘为 mm_uploads 下的 .md 文件。"""
    safe = "".join(c for c in (title or "粘贴文本") if c.isalnum() or c in "._- ()[]")[:80] or "paste"
    body = (content or "").strip()
    if not body:
        raise ValueError("文本内容不能为空")
    if not body.lstrip().startswith("#"):
        body = f"# {title or '粘贴文本'}\n\n{body}"
    dest = (mm_upload_dir() / f"{uuid.uuid4().hex[:12]}_{safe}.md").resolve()
    dest.write_text(body, encoding="utf-8")
    return dest


def _export_artifacts(stem: str, text: str, export_md: bool, export_txt: bool) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text.strip():
        return out
    export_root = mm_export_dir()
    safe = "".join(c for c in stem if c.isalnum() or c in "._- ()[]")[:120] or "document"
    tag = uuid.uuid4().hex[:8]
    if export_md:
        md_path = (export_root / f"{safe}_{tag}.md").resolve()
        md_path.write_text(text, encoding="utf-8")
        out["md_path"] = str(md_path)
        out["mm_export_md"] = str(md_path)
    if export_txt:
        txt_path = (export_root / f"{safe}_{tag}.txt").resolve()
        txt_path.write_text(text, encoding="utf-8")
        out["txt_path"] = str(txt_path)
        out["mm_export_txt"] = str(txt_path)
    return out


def process_document_file(
    path: Path,
    *,
    tenant_id: int | str,
    job_id: str | None = None,
    export_md: bool = True,
    export_txt: bool = True,
) -> Dict[str, Any]:
    """统一文档转化：返回 enrich 后的结果 + exports。"""
    from app.services.document import convert_document

    p = path.resolve()
    kind = detect_kind(p)
    jid = job_id or f"mm_{uuid.uuid4().hex[:12]}"
    result = convert_document(str(p), tenant_id=tenant_id, job_id=jid)

    manifest = result.get("manifest") or {}
    pipeline_note = manifest.get("pipeline_note") or result.get("pipeline") or ""
    result["kind"] = kind
    result["kind_label"] = kind_label(kind)
    result["pipeline"] = pipeline_note
    result["job_id"] = jid

    text = str(result.get("text") or "")
    exports: dict[str, str] = {}

    if result.get("normalized_md_path"):
        exports["md_path"] = str(result["normalized_md_path"])
        txt = result.get("normalized_txt_path")
        if txt:
            exports["txt_path"] = str(txt)
        elif Path(result["normalized_md_path"]).with_suffix(".txt").is_file():
            exports["txt_path"] = str(Path(result["normalized_md_path"]).with_suffix(".txt"))
        if result.get("assets_dir"):
            exports["assets_dir"] = str(result["assets_dir"])
        if result.get("manifest_path"):
            exports["manifest_path"] = str(result["manifest_path"])
        imgs = manifest.get("images") or []
        if imgs:
            result["preview_urls"] = [str(i.get("public_url") or "") for i in imgs if i.get("public_url")]
            exports["preview_urls"] = result["preview_urls"]
    elif text.strip():
        exports = _export_artifacts(p.stem, text, export_md, export_txt)
        exports["md_path"] = exports.get("mm_export_md") or exports.get("md_path", "")
        exports["txt_path"] = exports.get("mm_export_txt") or exports.get("txt_path", "")

    if text.strip() and result.get("normalized_md_path") and (export_md or export_txt):
        mirror = _export_artifacts(p.stem, text, export_md, export_txt)
        exports.update({k: v for k, v in mirror.items() if v})

    result["exports"] = exports
    return result


def process_flowchart_file(
    path: Path,
    *,
    page: int = 1,
    zoom: float = 2.0,
    column_band_split: bool = True,
    column_bands: int = 0,
    skip_arrows: bool = True,
    job_id: str = "",
) -> Dict[str, Any]:
    from app.services.flowchart_scoring_service import run_flowchart_score

    return run_flowchart_score(
        str(path.resolve()),
        page=page,
        zoom=zoom,
        column_band_split=column_band_split,
        column_bands=column_bands,
        skip_arrows=skip_arrows,
        artifact_subdir=job_id or f"fc_{uuid.uuid4().hex[:10]}",
    )
