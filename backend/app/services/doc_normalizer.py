"""DOCX/PDF/XLS/图片 → normalized.md + manifest（kb_assets，对齐 SPEC-RAG文档标准化）。"""
from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.services.doc_asset_validator import validate_normalization_assets
from app.services.doc_image_pipeline import ImageProcessResult, process_image
from app.services.doc_inspector import inspect_document
from app.services.docx_ordered_parser import (
    SCREEN_MARKER_RE,
    extract_all_docx_media,
    format_table_markdown,
    parse_docx_ordered,
)
from app.services.md_image_resolver import (
    IMG_MD_RE,
    count_image_refs,
    iter_image_refs,
    materialize_all_refs,
)
from app.services.haici_output import kb_assets_dir

logger = logging.getLogger(__name__)

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})


@dataclass
class NormalizationResult:
    ok: bool
    text: str
    assets_dir: str
    manifest_path: str
    normalized_md_path: str
    inspect: Dict[str, Any]
    manifest: Dict[str, Any]
    error: str = ""


def _write_manifest(asset_root: Path, manifest: Dict[str, Any]) -> Path:
    path = asset_root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _finalize(
    asset_root: Path,
    full_text: str,
    inspect: Dict[str, Any],
    *,
    source: Path,
    pipeline_note: str,
    img_results: List[ImageProcessResult],
    truncated: bool,
    limit: int,
    document_title: str = "",
) -> NormalizationResult:
    title = document_title or source.stem
    manifest = {
        "ok": True,
        "source": str(source),
        "document_title": title,
        "inspect": inspect,
        "pipeline_note": pipeline_note,
        "truncated": truncated,
        "vlm_limit": limit,
        "image_count": len(img_results),
        "images": [r.to_manifest_entry(i + 1, source.suffix.lstrip(".")) for i, r in enumerate(img_results)],
    }
    validation = validate_normalization_assets(
        asset_root, full_text, img_results, source=source
    )
    manifest["validation"] = validation
    inspect["processed_image_count"] = len(img_results)
    inspect["truncated"] = truncated
    inspect["asset_validation"] = validation

    md_path = asset_root / "normalized.md"
    md_path.write_text(full_text, encoding="utf-8")
    (asset_root / "normalized.txt").write_text(full_text, encoding="utf-8")
    mp = _write_manifest(asset_root, manifest)

    norm_ok = validation.get("ok", True)
    if not norm_ok:
        err_msg = "; ".join(validation.get("errors") or ["资产校验失败"])
        logger.error(
            "[RAG-文档标准化|doc_normalizer|normalize_document|硬编执行|校验失败] source=%s; err=%s",
            source.name,
            err_msg[:500],
        )
        manifest["ok"] = False
        _write_manifest(asset_root, manifest)
        return NormalizationResult(
            ok=False,
            text=full_text,
            assets_dir=str(asset_root),
            manifest_path=str(mp),
            normalized_md_path=str(md_path),
            inspect=inspect,
            manifest=manifest,
            error=err_msg,
        )

    logger.info(
        "[RAG-文档标准化|doc_normalizer|normalize_document|硬编执行|完成] source=%s; pipeline=%s; images=%s; truncated=%s",
        source.name,
        pipeline_note,
        len(img_results),
        truncated,
    )
    return NormalizationResult(
        ok=True,
        text=full_text,
        assets_dir=str(asset_root),
        manifest_path=str(mp),
        normalized_md_path=str(md_path),
        inspect=inspect,
        manifest=manifest,
    )


def _extract_office_images(source: Path, images_dir: Path) -> List[Path]:
    out: List[Path] = []
    images_dir.mkdir(parents=True, exist_ok=True)
    prefixes = ("word/media/", "xl/media/", "ppt/media/")
    try:
        with zipfile.ZipFile(source, "r") as zf:
            idx = 0
            for name in zf.namelist():
                if not any(name.startswith(p) for p in prefixes) or name.endswith("/"):
                    continue
                idx += 1
                ext = Path(name).suffix.lower() or ".png"
                dest = images_dir / f"img_{idx:04d}{ext}"
                dest.write_bytes(zf.read(name))
                out.append(dest)
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|doc_normalizer|extract_office|硬编执行|失败] err=%s",
            str(exc)[:200],
        )
    return out


def _extract_pdf_images(source: Path, images_dir: Path, limit: int) -> List[Path]:
    out: List[Path] = []
    try:
        import fitz

        doc = fitz.open(source)
        idx = 0
        for page in doc:
            for img in page.get_images(full=True):
                if idx >= limit:
                    break
                xref = img[0]
                base = doc.extract_image(xref)
                idx += 1
                ext = f".{base.get('ext', 'png')}"
                dest = images_dir / f"img_{idx:04d}{ext}"
                dest.write_bytes(base["image"])
                out.append(dest)
            if idx >= limit:
                break
        doc.close()
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|doc_normalizer|extract_pdf|硬编执行|失败] err=%s",
            str(exc)[:200],
        )
    return out


def _resolve_mineru_output_dir(asset_root: Path, stem: str) -> Path:
    """定位 MinerU 磁盘产出目录（含 .md 与 images/）。"""
    root = asset_root / "_mineru_tmp"
    candidates: List[Path] = []
    if root.is_dir():
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            nested = sub / stem
            candidates.extend([nested, sub])
        candidates.extend([root / stem, root / "auto" / stem, root])
    for c in candidates:
        if not c.is_dir():
            continue
        if (c / f"{stem}.md").is_file() or (c / "images").is_dir():
            return c
    return root


def _mineru_to_text(source: Path, asset_root: Path) -> tuple[str, Path]:
    """MinerU 解析：返回 Markdown + 产出目录（切图与 ![](...) 已由 MinerU 完成）。"""
    from app.services.document import process_with_mineru

    out_dir = str(asset_root / "_mineru_tmp")
    # 标准化链路使用 doc_image_pipeline Agent；MinerU 侧关闭内置 VLM 避免重复描述
    result = process_with_mineru(str(source), output_dir=out_dir, vlm_api_key=None)
    if not result.get("ok") and not result.get("markdown"):
        raise RuntimeError(str(result.get("error") or "MinerU 解析失败"))
    md = str(result.get("markdown") or result.get("content") or "")
    meta = result.get("metadata") or {}
    out_path = str(meta.get("output_path") or "").strip()
    if out_path and Path(out_path).is_dir():
        base_dir = Path(out_path)
    else:
        base_dir = _resolve_mineru_output_dir(asset_root, source.stem)
    return md, base_dir


def _import_images_to_assets(
    sources: List[Path],
    asset_root: Path,
    *,
    limit: int,
) -> Tuple[List[Path], bool]:
    truncated = len(sources) > limit
    out: List[Path] = []
    images_dir = asset_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(sources[:limit], start=1):
        ext = src.suffix.lower() or ".png"
        dest = images_dir / f"img_{i:04d}{ext}"
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        out.append(dest)
    return out, truncated


def _process_images_batch(
    jobs: List[Tuple[Path, str, str]],
    *,
    source_format: str = "unknown",
    task_id: str = "",
) -> List[ImageProcessResult]:
    """Process multiple images in batch using process_image."""
    results: List[ImageProcessResult] = []
    for dest, img_id, doc_context in jobs:
        try:
            res = process_image(
                str(dest),
                image_id=img_id,
                doc_context=doc_context,
                source_format=source_format,
            )
            results.append(res)
        except Exception as exc:
            logger.warning(
                "[RAG-?????|doc_normalizer|_process_images_batch|????|????] img_id=%s; err=%s",
                img_id,
                str(exc)[:200],
            )
            # Create a minimal result for failed images
            results.append(
                ImageProcessResult(
                    image_id=img_id,
                    image_type="unknown",
                    rag_block="",
                    ocr_text="",
                    vlm_description="",
                    pipeline="failed",
                    public_url="",
                    degraded=True,
                    error=str(exc)[:200],
                )
            )
    return results


def _process_images_inline(
    image_paths: List[Path],
    *,
    asset_root: Path,
    source_format: str,
    doc_context: str,
    limit: int,
    task_id: str = "",
) -> Tuple[List[str], List[ImageProcessResult], bool]:
    md_parts: List[str] = []
    truncated = len(image_paths) > limit
    images_dir = asset_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    jobs: List[Tuple[Path, str, str]] = []
    for i, src in enumerate(image_paths[:limit], start=1):
        img_id = f"img_{i:04d}"
        dest = images_dir / f"{img_id}{src.suffix.lower() or '.png'}"
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        jobs.append((dest, img_id, doc_context))

    results = _process_images_batch(jobs, source_format=source_format, task_id=task_id)
    md_parts = [r.rag_block for r in results]
    return md_parts, results, truncated


def _inject_orphan_docx_images(
    parts: List[str],
    orphan_media: List[tuple[str, bytes]],
    *,
    asset_root: Path,
    doc_context: str,
    start_img_no: int,
    limit: int,
    source_format: str = "docx",
) -> Tuple[List[str], List[ImageProcessResult], bool]:
    """将 ZIP 中未被顺序解析消费的图片，在 ※作业画面 等标记后回插。"""
    if not orphan_media:
        return parts, [], False

    new_parts: List[str] = []
    results: List[ImageProcessResult] = []
    images_dir = asset_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    ctx = doc_context
    mi = 0
    img_no = start_img_no
    truncated = len(orphan_media) > max(0, limit - start_img_no)

    def _append_image(item: tuple[str, bytes]) -> None:
        nonlocal img_no, ctx, mi
        if img_no >= limit or mi >= len(orphan_media):
            return
        name, data = item
        mi += 1
        img_no += 1
        ext = Path(name).suffix.lower() or ".png"
        if ext not in IMAGE_EXTS:
            ext = ".png"
        img_id = f"img_{img_no:04d}"
        dest = images_dir / f"{img_id}{ext}"
        dest.write_bytes(data)
        res = process_image(
            str(dest),
            image_id=img_id,
            doc_context=ctx[-2000:],
            source_format=source_format,
        )
        results.append(res)
        new_parts.append(res.rag_block)
        ctx = f"{ctx}\n{res.vlm_description or res.ocr_text or ''}"

    for part in parts:
        new_parts.append(part)
        if mi >= len(orphan_media):
            continue
        if part and SCREEN_MARKER_RE.search(part):
            _append_image(orphan_media[mi])

    while mi < len(orphan_media) and img_no < limit:
        _append_image(orphan_media[mi])

    return new_parts, results, truncated


def _normalize_markdown_with_images(
    source: Path,
    asset_root: Path,
    text: str,
    *,
    limit: int,
    inspect: Dict[str, Any],
) -> NormalizationResult:
    """Markdown：下载/复制图片 → OCR/VLM → 链接 + 占位符 + BODY 回插。"""
    refs = iter_image_refs(text)
    img_results: List[ImageProcessResult] = []
    truncated = len(refs) > limit

    if not refs:
        manifest = {
            "ok": True,
            "source": str(source),
            "inspect": inspect,
            "pipeline_note": "plain_markdown",
            "images": [],
            "image_count": 0,
            "truncated": False,
        }
        md_path = asset_root / "normalized.md"
        md_path.write_text(text, encoding="utf-8")
        (asset_root / "normalized.txt").write_text(text, encoding="utf-8")
        mp = _write_manifest(asset_root, manifest)
        return NormalizationResult(
            ok=True,
            text=text,
            assets_dir=str(asset_root),
            manifest_path=str(mp),
            normalized_md_path=str(md_path),
            inspect=inspect,
            manifest=manifest,
        )

    images_dir = asset_root / "images"
    materialized = materialize_all_refs(
        refs,
        images_dir,
        base_dir=source.parent,
        limit=limit,
    )
    url_map: Dict[str, ImageProcessResult] = {}
    ctx = text[:2000]
    for i, (orig_url, _alt, local_path) in enumerate(materialized, start=1):
        img_id = f"img_{i:04d}"
        res = process_image(
            str(local_path),
            image_id=img_id,
            doc_context=ctx[-2000:],
            source_format="markdown",
        )
        img_results.append(res)
        url_map[orig_url] = res
        ctx = f"{ctx}\n{res.vlm_description or res.ocr_text or ''}"

    def _replace_img_ref(m: re.Match[str]) -> str:
        url = (m.group(2) or "").strip()
        res = url_map.get(url)
        if not res:
            return m.group(0)
        return res.rag_block

    full_text = IMG_MD_RE.sub(_replace_img_ref, text).strip()
    return _finalize(
        asset_root,
        full_text,
        inspect,
        source=source,
        pipeline_note="markdown_image_pipeline",
        img_results=img_results,
        truncated=truncated,
        limit=limit,
    )


def _normalize_docx_p0(
    source: Path,
    asset_root: Path,
    *,
    limit: int,
    inspect: Dict[str, Any],
    document_title: str = "",
    task_id: str = "",
) -> Optional[NormalizationResult]:
    parsed = parse_docx_ordered(source)
    if not parsed.ok:
        return None

    title = document_title or source.stem
    context_acc: List[str] = []
    final_parts: List[str] = [f"# {title}\n"]
    img_results: List[ImageProcessResult] = []
    img_cursor = 0
    truncated = False
    images_dir = asset_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    pending_images: List[Tuple[int, Path, str, str]] = []

    for block in parsed.blocks:
        if block.kind == "paragraph":
            final_parts.append(block.text)
            context_acc.append(block.text)
        elif block.kind == "table":
            final_parts.append(format_table_markdown(block))
            if block.rows and block.rows[0]:
                context_acc.append(block.rows[0][0])
        elif block.kind == "image":
            img_cursor += 1
            if img_cursor > limit:
                truncated = True
                continue
            ext = Path(block.media_zip_path).suffix.lower() or ".png"
            dest = images_dir / f"img_{img_cursor:04d}{ext}"
            dest.write_bytes(block.image_bytes)
            pending_images.append(
                (
                    len(final_parts),
                    dest,
                    f"img_{img_cursor:04d}",
                    "\n".join(context_acc)[-2000:],
                )
            )
            final_parts.append("")

    if pending_images:
        jobs = [(dest, img_id, ctx) for _, dest, img_id, ctx in pending_images]
        batch_results = _process_images_batch(
            jobs, source_format="docx", task_id=task_id
        )
        for (part_idx, _, _, _), res in zip(pending_images, batch_results):
            final_parts[part_idx] = res.rag_block
            img_results.append(res)

    all_media = extract_all_docx_media(source)
    if len(img_results) < len(all_media):
        consumed = len(img_results)
        orphans = all_media[consumed:]
        final_parts, orphan_res, orphan_trunc = _inject_orphan_docx_images(
            final_parts,
            orphans,
            asset_root=asset_root,
            doc_context="\n".join(context_acc),
            start_img_no=img_cursor,
            limit=limit,
        )
        img_results.extend(orphan_res)
        truncated = truncated or orphan_trunc
        if orphan_res:
            logger.info(
                "[RAG-文档标准化|doc_normalizer|docx_p0|硬编执行|orphan回插] count=%s",
                len(orphan_res),
            )

    full_text = "\n\n".join(p for p in final_parts if p).strip()
    if not full_text:
        return None

    return _finalize(
        asset_root,
        full_text,
        inspect,
        source=source,
        pipeline_note="docx_p0_ordered",
        img_results=img_results,
        truncated=truncated,
        limit=limit,
        document_title=title,
    )


def _docx_p2_fallback(source: Path) -> str:
    from app.services.document import _processor_fallback

    r = _processor_fallback(str(source), doc_type_hint="docx")
    if r.get("ok") and r.get("text"):
        return str(r["text"])
    raise RuntimeError(str(r.get("error") or "DocumentProcessor 兜底失败"))


def _normalize_docx(
    source: Path,
    asset_root: Path,
    *,
    limit: int,
    inspect: Dict[str, Any],
    document_title: str = "",
    task_id: str = "",
) -> NormalizationResult:
    p0 = _normalize_docx_p0(
        source,
        asset_root,
        limit=limit,
        inspect=inspect,
        document_title=document_title,
        task_id=task_id,
    )
    if p0 is not None:
        return p0

    logger.warning(
        "[RAG-文档标准化|doc_normalizer|docx|硬编执行|P1降级] source=%s",
        source.name,
    )
    try:
        md, mineru_dir = _mineru_to_text(source, asset_root)
        return _normalize_mineru_markdown(
            source,
            asset_root,
            md,
            mineru_dir,
            limit=limit,
            inspect=inspect,
            pipeline_note="mineru_docx_fallback",
        )
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|doc_normalizer|docx|硬编执行|P2降级] err=%s",
            str(exc)[:200],
        )
        text = _docx_p2_fallback(source)
        manifest = {
            "ok": True,
            "source": str(source),
            "inspect": inspect,
            "pipeline_note": "document_processor_p2",
            "degraded": True,
            "images": [],
            "image_count": 0,
            "truncated": False,
        }
        md_path = asset_root / "normalized.md"
        md_path.write_text(text, encoding="utf-8")
        (asset_root / "normalized.txt").write_text(text, encoding="utf-8")
        mp = _write_manifest(asset_root, manifest)
        return NormalizationResult(
            ok=True,
            text=text,
            assets_dir=str(asset_root),
            manifest_path=str(mp),
            normalized_md_path=str(md_path),
            inspect=inspect,
            manifest=manifest,
        )


def _describe_mineru_markdown(
    md: str,
    asset_root: Path,
    mineru_base_dir: Path,
    *,
    source_format: str,
    limit: int,
    doc_context_prefix: str = "",
) -> Tuple[str, List[ImageProcessResult], bool]:
    """MinerU 已产出 md 内图片链接与本地切图；此处仅 OCR/VLM 识别、描述与 SPEC 回插。"""
    refs = iter_image_refs(md)
    truncated = len(refs) > limit
    img_results: List[ImageProcessResult] = []

    if not refs:
        return md, [], False

    images_dir = asset_root / "images"
    materialized = materialize_all_refs(
        refs,
        images_dir,
        base_dir=mineru_base_dir,
        limit=limit,
    )
    url_map: Dict[str, ImageProcessResult] = {}
    ctx = (doc_context_prefix or md)[:2000]
    referenced_names: set[str] = set()

    for i, (orig_url, _alt, local_path) in enumerate(materialized, start=1):
        img_id = f"img_{i:04d}"
        referenced_names.add(local_path.name)
        res = process_image(
            str(local_path),
            image_id=img_id,
            doc_context=ctx[-2000:],
            source_format=source_format,
        )
        img_results.append(res)
        url_map[orig_url] = res
        ctx = f"{ctx}\n{res.vlm_description or res.ocr_text or ''}"

    def _replace_img_ref(m: re.Match[str]) -> str:
        url = (m.group(2) or "").strip()
        res = url_map.get(url)
        if not res:
            return m.group(0)
        return res.rag_block

    full_text = IMG_MD_RE.sub(_replace_img_ref, md).strip()

    # MinerU 切图目录中未被 md 引用的 orphan 图（少见）追加到文末
    orphan_parts: List[str] = []
    mineru_img_dir = mineru_base_dir / "images"
    if mineru_img_dir.is_dir():
        start_no = len(img_results)
        for f in sorted(mineru_img_dir.iterdir()):
            if f.suffix.lower() not in IMAGE_EXTS or f.name in referenced_names:
                continue
            if start_no >= limit:
                truncated = True
                break
            start_no += 1
            img_id = f"img_{start_no:04d}"
            dest = images_dir / f"{img_id}{f.suffix.lower()}"
            if f.resolve() != dest.resolve():
                shutil.copy2(f, dest)
            res = process_image(
                str(dest),
                image_id=img_id,
                doc_context=ctx[-2000:],
                source_format=source_format,
            )
            img_results.append(res)
            orphan_parts.append(res.rag_block)
            ctx = f"{ctx}\n{res.vlm_description or res.ocr_text or ''}"
    if orphan_parts:
        full_text = f"{full_text}\n\n## 文档插图与识别结果\n\n" + "\n\n".join(orphan_parts)

    return full_text, img_results, truncated


def _normalize_mineru_markdown(
    source: Path,
    asset_root: Path,
    md: str,
    mineru_base_dir: Path,
    *,
    limit: int,
    inspect: Dict[str, Any],
    pipeline_note: str,
    source_format: str = "pdf",
) -> NormalizationResult:
    full_text, img_results, truncated = _describe_mineru_markdown(
        md,
        asset_root,
        mineru_base_dir,
        source_format=source_format,
        limit=limit,
        doc_context_prefix=md[:2000],
    )
    if not full_text.strip():
        raise RuntimeError("MinerU 未产出正文")
    return _finalize(
        asset_root,
        full_text,
        inspect,
        source=source,
        pipeline_note=pipeline_note,
        img_results=img_results,
        truncated=truncated,
        limit=limit,
    )


def _normalize_pdf(
    source: Path,
    asset_root: Path,
    *,
    limit: int,
    inspect: Dict[str, Any],
    document_title: str = "",
    task_id: str = "",
) -> NormalizationResult:
    title = document_title or source.stem
    try:
        md, mineru_dir = _mineru_to_text(source, asset_root)
        return _normalize_mineru_markdown(
            source,
            asset_root,
            md,
            mineru_dir,
            limit=limit,
            inspect=inspect,
            pipeline_note="mineru_pdf",
            source_format="pdf",
        )
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|doc_normalizer|pdf|硬编执行|MinerU失败] err=%s",
            str(exc)[:200],
        )
        import fitz

        doc = fitz.open(source)
        doc_context = "\n".join(page.get_text() for page in doc)
        doc.close()
        body_parts = [f"# {title}\n\n{doc_context}"]
        image_paths = _extract_pdf_images(source, asset_root / "images", limit)
        md_parts, img_results, truncated = _process_images_inline(
            image_paths,
            asset_root=asset_root,
            source_format="pdf",
            doc_context=doc_context,
            limit=limit,
            task_id=task_id,
        )
        if md_parts:
            body_parts.append("\n## 文档插图与识别结果\n")
            body_parts.extend(md_parts)
        full_text = "\n\n".join(body_parts).strip()
        return _finalize(
            asset_root,
            full_text,
            inspect,
            source=source,
            pipeline_note="pymupdf_ocr_fallback",
            img_results=img_results,
            truncated=truncated,
            limit=limit,
            document_title=title,
        )


def _normalize_office_other(
    source: Path,
    asset_root: Path,
    *,
    limit: int,
    inspect: Dict[str, Any],
    document_title: str = "",
    task_id: str = "",
) -> NormalizationResult:
    title = document_title or source.stem
    image_paths = _extract_office_images(source, asset_root / "images")
    if not image_paths:
        try:
            md, mineru_dir = _mineru_to_text(source, asset_root)
            return _normalize_mineru_markdown(
                source,
                asset_root,
                md,
                mineru_dir,
                limit=limit,
                inspect=inspect,
                pipeline_note="mineru_office_fallback",
                source_format=source.suffix.lstrip(".") or "office",
            )
        except Exception as exc:
            logger.warning(
                "[RAG-文档标准化|doc_normalizer|office|硬编执行|失败] err=%s",
                str(exc)[:200],
            )

    body_parts = [f"# {title}\n"]
    md_parts, img_results, truncated = _process_images_inline(
        image_paths,
        asset_root=asset_root,
        source_format=source.suffix.lstrip("."),
        doc_context=title,
        limit=limit,
        task_id=task_id,
    )
    if md_parts:
        body_parts.append("\n## 文档插图与识别结果\n")
        body_parts.extend(md_parts)
    full_text = "\n\n".join(body_parts).strip()
    return _finalize(
        asset_root,
        full_text,
        inspect,
        source=source,
        pipeline_note="office_zip_images",
        img_results=img_results,
        truncated=truncated,
        limit=limit,
        document_title=title,
    )


def _resolve_document_title(source: Path, document_name: str | None = None) -> str:
    """Resolve a human-readable title from the document source."""
    if document_name:
        stem = Path(document_name).stem
        # Try to extract meaningful title (remove hash prefixes from MinerU output)
        if len(stem) > 32 and stem[:32].replace("-", "").isalnum():
            # Looks like a hash, use full filename
            return Path(document_name).name
        return stem
    return source.stem


def normalize_document(
    source: Path,
    *,
    tenant_id: str | int,
    doc_id: int | str,
    document_name: str | None = None,
    task_id: str = "",
) -> NormalizationResult:
    source = source.resolve()
    doc_title = _resolve_document_title(source, document_name)
    inspect = inspect_document(source)
    inspect["vlm_limit"] = settings.MAX_IMAGES_PER_DOC
    asset_root = kb_assets_dir(tenant_id, doc_id)
    asset_root.mkdir(parents=True, exist_ok=True)
    (asset_root / "images").mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    limit = settings.MAX_IMAGES_PER_DOC

    try:
        if suffix in {".txt", ".md", ".markdown"}:
            text = source.read_text(encoding="utf-8", errors="ignore")
            if count_image_refs(text) > 0 or "<img" in text.lower():
                return _normalize_markdown_with_images(
                    source, asset_root, text, limit=limit, inspect=inspect
                )
            manifest = {
                "ok": True,
                "source": str(source),
                "inspect": inspect,
                "images": [],
                "truncated": False,
                "pipeline_note": "plain_text",
            }
            md_path = asset_root / "normalized.md"
            md_path.write_text(text, encoding="utf-8")
            (asset_root / "normalized.txt").write_text(text, encoding="utf-8")
            mp = _write_manifest(asset_root, manifest)
            return NormalizationResult(
                ok=True,
                text=text,
                assets_dir=str(asset_root),
                manifest_path=str(mp),
                normalized_md_path=str(md_path),
                inspect=inspect,
                manifest=manifest,
            )

        if suffix in {".docx", ".doc"}:
            return _normalize_docx(
                source,
                asset_root,
                limit=limit,
                inspect=inspect,
                document_title=doc_title,
                task_id=task_id,
            )

        if suffix == ".pdf":
            return _normalize_pdf(
                source,
                asset_root,
                limit=limit,
                inspect=inspect,
                document_title=doc_title,
                task_id=task_id,
            )

        if suffix in IMAGE_EXTS:
            dest = asset_root / "images" / f"img_0001{suffix}"
            shutil.copy2(source, dest)
            md_parts, img_results, truncated = _process_images_inline(
                [dest],
                asset_root=asset_root,
                source_format=suffix.lstrip("."),
                doc_context=doc_title,
                limit=limit,
                task_id=task_id,
            )
            full_text = "\n\n".join([f"# {doc_title}\n", *md_parts]).strip()
            return _finalize(
                asset_root,
                full_text,
                inspect,
                source=source,
                pipeline_note="single_image",
                img_results=img_results,
                truncated=truncated,
                limit=limit,
                document_title=doc_title,
            )

        if suffix in {".xlsx", ".xls", ".pptx", ".ppt"}:
            return _normalize_office_other(
                source,
                asset_root,
                limit=limit,
                inspect=inspect,
                document_title=doc_title,
                task_id=task_id,
            )

        from app.services.knowledge_processor import read_document_text

        text = read_document_text(source)
        manifest = {
            "ok": True,
            "source": str(source),
            "inspect": inspect,
            "images": [],
            "pipeline_note": "generic_text",
        }
        md_path = asset_root / "normalized.md"
        md_path.write_text(text, encoding="utf-8")
        (asset_root / "normalized.txt").write_text(text, encoding="utf-8")
        mp = _write_manifest(asset_root, manifest)
        return NormalizationResult(
            ok=True,
            text=text,
            assets_dir=str(asset_root),
            manifest_path=str(mp),
            normalized_md_path=str(md_path),
            inspect=inspect,
            manifest=manifest,
        )
    except Exception as exc:
        logger.exception(
            "[RAG-文档标准化|doc_normalizer|normalize_document|硬编执行|失败] doc_id=%s",
            doc_id,
        )
        return NormalizationResult(
            ok=False,
            text="",
            assets_dir=str(asset_root),
            manifest_path="",
            normalized_md_path="",
            inspect=inspect,
            manifest={},
            error=str(exc)[:500],
        )
