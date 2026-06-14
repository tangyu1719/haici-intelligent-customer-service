"""知识库文档读取与分块；复杂格式走 DocumentProcessor / MinerU。"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def read_document_text(file_path: Path, *, normalized_md: Path | None = None) -> str:
    if normalized_md and normalized_md.is_file():
        return normalized_md.read_text(encoding="utf-8", errors="ignore")

    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")

    try:
        from app.services.document import analyze_document

        result = analyze_document(str(file_path))
        if result.get("ok") and result.get("text"):
            return str(result["text"])
        if result.get("error"):
            logger.warning(
                "[智能客服-知识库|knowledge_processor|DocumentProcessor|硬编执行|降级] err=%s",
                str(result.get("error"))[:200],
            )
    except Exception as exc:
        logger.warning(
            "[智能客服-知识库|knowledge_processor|DocumentProcessor|硬编执行|异常] err=%s",
            str(exc)[:200],
        )

    if suffix == ".pdf":
        import fitz

        doc = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text

    raise ValueError(f"不支持的文件格式: {suffix}")


def save_parsed_exports(
    file_path: Path,
    text: str,
    *,
    document_name: str = "",
) -> dict[str, str]:
    """将解析结果落盘为 MD / TXT（多模态最终文档形态）。"""
    from app.services.haici_output import mm_export_dir

    if not text.strip():
        return {}
    export_root = mm_export_dir()
    stem = Path(document_name).stem if document_name else file_path.stem
    safe = "".join(c for c in stem if c.isalnum() or c in "._- ()[]")[:120] or "document"
    md_path = (export_root / f"{safe}.md").resolve()
    txt_path = (export_root / f"{safe}.txt").resolve()
    md_path.write_text(text, encoding="utf-8")
    txt_path.write_text(text, encoding="utf-8")
    return {"md_path": str(md_path), "txt_path": str(txt_path)}


def split_to_documents(
    text: str,
    document_id: int,
    document_name: str,
    *,
    slice_method: str = "auto",
    chunk_size: int | None = None,
    overlap: int | None = None,
    max_tokens: int | None = None,
    dynamic_max_chars: int | None = None,
):
    """按 web_rebuild 对齐的全量切割策略分块并转为 LangChain Document。"""
    from app.config import settings
    from app.services.kb_chunk_service import split_to_documents as _split

    return _split(
        text,
        document_id,
        document_name,
        mode=slice_method,
        chunk_size=chunk_size or settings.KB_CHUNK_SIZE,
        overlap=overlap or settings.KB_CHUNK_OVERLAP,
        max_tokens=max_tokens or settings.KB_CHUNK_MAX_TOKENS,
        dynamic_max_chars=dynamic_max_chars or settings.KB_DYNAMIC_MAX_CHARS,
    )


def ingest_uploaded_document(
    file_path: Path,
    *,
    document_id: int,
    document_name: str,
    tenant_id: str | int,
    slice_method: str = "auto",
    task_id: str = "",
) -> dict:
    """读取/标准化文档并分块，返回入库摘要（含初检元数据）。

    如果提供了 task_id，会自动推送进度到多模态任务管理器。
    """
    from app.config import settings
    from app.services.doc_inspector import inspect_document
    from app.services.doc_normalizer import normalize_document
    from app.services.multimodal_task_manager import (
        complete_stage,
        fail_stage,
        get_task,
        start_stage,
        update_task,
    )

    def _step(stage_id: str) -> None:
        if task_id:
            start_stage(task_id, stage_id)

    def _done(stage_id: str, result: object = None) -> None:
        if task_id:
            complete_stage(task_id, stage_id, result)

    try:
        _step("inspect")
        inspect = inspect_document(file_path)
        _done("inspect", inspect)
        norm_md: Path | None = None
        manifest: dict = {}

        if settings.KB_NORMALIZE_ENABLED and inspect.get("requires_normalization"):
            _step("normalize")
            norm = normalize_document(
                file_path,
                tenant_id=tenant_id,
                doc_id=document_id,
                document_name=document_name,
                task_id=task_id,
            )
            if not norm.ok:
                if task_id:
                    fail_stage(task_id, "normalize", norm.error or "标准化失败")
                raise ValueError(norm.error or "文档标准化失败")
            norm_md = Path(norm.normalized_md_path)
            manifest = norm.manifest
            inspect = norm.inspect
            text = norm.text
            _done("normalize", {"manifest": manifest})
            if task_id:
                update_task(
                    task_id,
                    output_dir=str(norm_md.parent) if norm_md else "",
                    output_md=str(norm_md) if norm_md else "",
                    output_manifest=str(Path(str(norm_md.parent)) / "manifest.json") if norm_md else "",
                )
        else:
            _step("normalize")
            text = read_document_text(file_path)
            _done("normalize", {"text_length": len(text)})

        _step("chunk")
        save_parsed_exports(file_path, text, document_name=document_name)
        chunks = split_to_documents(text, document_id, document_name, slice_method=slice_method)
        _done("chunk", {"chunk_count": len(chunks)})

        _step("vectorize")
        from app.vectorstore import add_documents

        count = add_documents(chunks, tenant_id=str(tenant_id))
        _done("vectorize", {"vector_count": count})

        _step("complete")
        _done("complete")

        return {
            "chunk_count": count,
            "inspect": inspect,
            "manifest": manifest,
            "normalized_md": str(norm_md) if norm_md else "",
            "text_length": len(text),
        }
    except Exception as e:
        if task_id:
            t = get_task(task_id) or {}
            fail_sid = t.get("stage") or "normalize"
            if fail_sid not in {"inspect", "normalize", "chunk", "vectorize"}:
                fail_sid = "normalize"
            fail_stage(task_id, fail_sid, str(e)[:300])
        raise
