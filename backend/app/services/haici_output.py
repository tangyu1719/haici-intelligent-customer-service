"""HaiChi 输出目录（对齐 web_rebuild output/ 布局）。"""

from __future__ import annotations

from pathlib import Path

from app.config import settings


def get_output_dir() -> Path:
    root = settings.project_root / "output"
    root.mkdir(parents=True, exist_ok=True)
    return root


def mm_upload_dir() -> Path:
    p = get_output_dir() / "mm_uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mm_export_dir() -> Path:
    p = get_output_dir() / "mm_exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def kb_upload_dir() -> Path:
    p = get_output_dir() / "kb_uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def kb_assets_dir(tenant_id: str | int, doc_id: int | str) -> Path:
    """知识库标准化产物根目录：output/kb_assets/{tenant}/{doc_id}/"""
    p = get_output_dir() / "kb_assets" / str(tenant_id) / str(doc_id)
    p.mkdir(parents=True, exist_ok=True)
    (p / "images").mkdir(parents=True, exist_ok=True)
    return p


def abs_path_to_public_url(abs_path: str | Path) -> str:
    """output 目录下绝对路径 → /output/...（前端与 RAG 均可 fetch）。"""
    p = Path(abs_path).resolve()
    root = get_output_dir().resolve()
    try:
        rel = p.relative_to(root).as_posix()
    except ValueError:
        return ""
    from urllib.parse import quote

    return "/output/" + quote(rel, safe="/")


def is_under_output_dir(abs_path: Path) -> bool:
    try:
        return abs_path.resolve().is_relative_to(get_output_dir().resolve())
    except ValueError:
        return False
