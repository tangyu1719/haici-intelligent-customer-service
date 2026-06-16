"""文档处理服务 —— + SPEC-RAG 标准化流水线。"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve()
_AGENT_DIR = None
for _p in _HERE.parents:
    _candidate = _p / "src" / "agent"
    if _candidate.is_dir():
        _AGENT_DIR = _candidate.resolve()
        break
if _AGENT_DIR and str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from document_processor import DocumentProcessor, ProcessingResult
from mineru_processor import MinerUProcessor, MinerUResult, process_with_mineru as _run_mineru

logger = logging.getLogger(__name__)

_doc_processor: Optional[DocumentProcessor] = None
_mineru_processor: Optional[MinerUProcessor] = None


def _get_doc_processor() -> DocumentProcessor:
    global _doc_processor
    if _doc_processor is None:
        _doc_processor = DocumentProcessor()
    return _doc_processor


def _get_mineru_processor(vlm_api_key: str = None) -> MinerUProcessor:
    global _mineru_processor
    if _mineru_processor is None:
        _mineru_processor = MinerUProcessor(vlm_api_key=vlm_api_key)
    return _mineru_processor


def detect_document_type(file_path: str) -> str:
    dp = _get_doc_processor()
    doc_type = dp.detect_type(file_path)
    return doc_type.value if hasattr(doc_type, "value") else str(doc_type)


def _processor_fallback(file_path: str, *, doc_type_hint: str = "") -> Dict[str, Any]:
    """SPEC P2：DocumentProcessor 纯文本兜底（错误可见）。"""
    t0 = time.time()
    dp = _get_doc_processor()
    result: ProcessingResult = dp.process(file_path)
    text = result.content.text if result.content else ""
    return {
        "ok": result.success and bool(text.strip()),
        "doc_type": doc_type_hint or str(result.doc_type),
        "text": text,
        "error": result.error or ("" if text.strip() else "DocumentProcessor 未提取到正文"),
        "file_path": result.file_path or file_path,
        "file_size": result.file_size or (Path(file_path).stat().st_size if Path(file_path).is_file() else 0),
        "processing_time": result.processing_time or (time.time() - t0),
        "pipeline": "document_processor_p2",
        "normalized": False,
    }


def _chunk_preview(text: str, file_path: str, **kwargs) -> tuple[list, dict]:
    """可选分块预览。"""
    chunk_mode = str(kwargs.get("slice_method") or kwargs.get("chunk_mode") or "auto")
    if not text.strip():
        return [], {"mode": chunk_mode, "count": 0}
    try:
        from app.services.kb_chunk_service import chunk_text_with_meta

        stats = chunk_text_with_meta(
            text,
            mode=chunk_mode,
            chunk_size=int(kwargs.get("chunk_size") or 500),
            overlap=int(kwargs.get("overlap") or 80),
            max_tokens=int(kwargs.get("max_tokens") or 350),
            dynamic_max_chars=int(kwargs.get("dynamic_max_chars") or 800),
            source=str(file_path),
        )
        return stats.get("chunks") or [], stats
    except Exception as exc:
        return [], {"mode": chunk_mode, "count": 0, "error": str(exc)}


def convert_document(
    file_path: str,
    *,
    tenant_id: str | int = 0,
    job_id: str | None = None,
    **kwargs,
) -> Dict[str, Any]:
    """多模态 / 工具调用：优先 SPEC 标准化，失败再 DocumentProcessor 兜底。"""
    from app.config import settings
    from app.services.doc_inspector import inspect_document
    from app.services.doc_normalizer import normalize_document

    p = Path(file_path).resolve()
    if not p.is_file():
        return {"ok": False, "doc_type": "", "text": "", "error": "文件不存在", "file_path": str(p)}

    suffix = p.suffix.lower()
    inspect = inspect_document(p)
    doc_type = inspect.get("file_type") or p.suffix.lstrip(".") or detect_document_type(str(p))
    t0 = time.time()

    if settings.KB_NORMALIZE_ENABLED and (
        inspect.get("requires_normalization") or suffix in {".txt", ".md", ".markdown"}
    ):
        asset_id = job_id or f"mm_{uuid.uuid4().hex[:12]}"
        norm = normalize_document(p, tenant_id=tenant_id, doc_id=asset_id)
        if norm.ok and norm.text.strip():
            txt_path = Path(norm.normalized_md_path).with_suffix(".txt")
            pipeline_note = (norm.manifest or {}).get("pipeline_note") or "doc_normalizer"
            return {
                "ok": True,
                "doc_type": doc_type,
                "text": norm.text,
                "error": None,
                "file_path": str(p),
                "file_size": inspect.get("file_size_bytes") or p.stat().st_size,
                "processing_time": time.time() - t0,
                "pipeline": pipeline_note,
                "normalized": True,
                "assets_dir": norm.assets_dir,
                "manifest_path": norm.manifest_path,
                "manifest": norm.manifest,
                "normalized_md_path": norm.normalized_md_path,
                "normalized_txt_path": str(txt_path) if txt_path.is_file() else "",
                "image_count": int((norm.manifest or {}).get("image_count") or 0),
                "truncated": bool((norm.manifest or {}).get("truncated")),
            }
        err = norm.error or "文档标准化失败"
        logger.warning(
            "[RAG-文档标准化|document.convert_document|doc_normalizer|硬编执行|降级] path=%s; err=%s",
            p.name,
            str(err)[:200],
        )
        if p.suffix.lower() in {".docx", ".doc", ".csv"}:
            fb = _processor_fallback(str(p), doc_type_hint=doc_type)
            fb["normalize_error"] = err
            fb["pipeline"] = "document_processor_p2_after_normalize_fail"
            return fb
        return {
            "ok": False,
            "doc_type": doc_type,
            "text": "",
            "error": err,
            "file_path": str(p),
            "file_size": inspect.get("file_size_bytes") or 0,
            "processing_time": time.time() - t0,
            "pipeline": "doc_normalizer_failed",
            "normalized": False,
        }

    if p.suffix.lower() in {".txt", ".md", ".markdown"}:
        text = p.read_text(encoding="utf-8", errors="ignore")
        return {
            "ok": bool(text.strip()),
            "doc_type": doc_type,
            "text": text,
            "error": None if text.strip() else "空文件",
            "file_path": str(p),
            "file_size": p.stat().st_size,
            "processing_time": time.time() - t0,
            "pipeline": "plain_text",
            "normalized": False,
        }

    return _processor_fallback(str(p), doc_type_hint=doc_type)


def analyze_document(file_path: str, **kwargs) -> Dict[str, Any]:
    """/api/doc/process：标准化正文 + 分块预览。"""
    base = convert_document(
        file_path,
        tenant_id=kwargs.pop("tenant_id", 0),
        job_id=kwargs.pop("job_id", None),
        **kwargs,
    )
    text = str(base.get("text") or "")
    chunks, chunk_stats = _chunk_preview(text, file_path, **kwargs)
    base["chunks"] = chunks
    base["chunk_stats"] = chunk_stats
    return base


def process_with_mineru(file_path: str, output_dir: str = None, vlm_api_key: str = None) -> Dict[str, Any]:
    result: MinerUResult = _run_mineru(file_path, output_dir=output_dir, vlm_api_key=vlm_api_key)
    return {
        "ok": result.success,
        "content": result.content,
        "markdown": result.markdown,
        "metadata": result.metadata,
        "images": result.images,
        "tables": result.tables,
        "image_descriptions": result.image_descriptions,
        "error": result.error,
    }


def get_supported_formats() -> list:
    mp = _get_mineru_processor()
    return mp.get_supported_formats()
