"""上传前/入库初检：文件类型、大小、预估含图数。"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

OFFICE_MEDIA_SUFFIXES = frozenset({".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"})
NORMALIZE_SUFFIXES = OFFICE_MEDIA_SUFFIXES | frozenset({".pdf"}) | frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _count_zip_media(path: Path) -> int:
    media_prefixes = ("word/media/", "xl/media/", "ppt/media/")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return sum(
                1
                for name in zf.namelist()
                if name.startswith(media_prefixes)
                and not name.endswith("/")
            )
    except Exception:
        return 0


def _count_pdf_images(path: Path) -> int:
    try:
        import fitz

        doc = fitz.open(path)
        total = 0
        for page in doc:
            total += len(page.get_images(full=True))
        doc.close()
        return total
    except Exception as exc:
        logger.warning(
            "[智能客服-知识库|doc_inspector|pdf|硬编执行|计数] err=%s",
            str(exc)[:120],
        )
        return 0


def estimate_image_count(path: Path) -> int:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return 1
    if suffix in OFFICE_MEDIA_SUFFIXES:
        return _count_zip_media(path)
    if suffix == ".pdf":
        return _count_pdf_images(path)
    return 0


def inspect_document(path: Path) -> dict:
    p = path.resolve()
    suffix = p.suffix.lower()
    size = p.stat().st_size if p.is_file() else 0
    img_n = estimate_image_count(p) if p.is_file() else 0
    md_img_refs = 0
    if p.is_file() and suffix in {".md", ".markdown"}:
        try:
            from app.services.md_image_resolver import count_image_refs

            md_img_refs = count_image_refs(p.read_text(encoding="utf-8", errors="ignore"))
            img_n = max(img_n, md_img_refs)
        except Exception:
            pass
    return {
        "file_type": suffix.lstrip(".") or "unknown",
        "file_size_bytes": size,
        "file_size_human": _human_size(size),
        "estimated_image_count": img_n,
        "markdown_image_refs": md_img_refs,
        "requires_normalization": suffix in NORMALIZE_SUFFIXES or img_n > 0 or md_img_refs > 0,
        "vlm_limit": None,
    }
