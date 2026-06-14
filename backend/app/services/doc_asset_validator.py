"""文档标准化产物硬编校验：DOCX 媒体数 / 本地下载 / manifest JSON / MD 块数量对齐。"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.doc_image_pipeline import ImageProcessResult
from app.services.docx_ordered_parser import extract_all_docx_media, parse_docx_ordered

logger = logging.getLogger(__name__)

PICTURE_BLOCK_RE = re.compile(r"\{picture_id\s*:", re.MULTILINE)


def count_docx_inline_images(source: Path) -> int:
    parsed = parse_docx_ordered(source)
    if not parsed.ok:
        return 0
    return sum(1 for b in parsed.blocks if b.kind == "image")


def count_picture_blocks_in_md(text: str) -> int:
    return len(PICTURE_BLOCK_RE.findall(text or ""))


def validate_normalization_assets(
    asset_root: Path,
    full_text: str,
    img_results: List[ImageProcessResult],
    *,
    source: Optional[Path] = None,
) -> Dict[str, Any]:
    """硬编校验：磁盘文件、manifest 条目、MD picture 块、img_results 四者必须一致。"""
    images_dir = asset_root / "images"
    disk_files = sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.name.startswith("img_")
    ) if images_dir.is_dir() else []

    processed = len(img_results)
    disk_count = len(disk_files)
    md_blocks = count_picture_blocks_in_md(full_text)

    counts: Dict[str, Any] = {
        "docx_media_total": None,
        "docx_inline_refs": None,
        "docx_orphan_media": None,
        "processed_images": processed,
        "disk_download_count": disk_count,
        "md_picture_blocks": md_blocks,
        "manifest_json_entries": processed,
    }

    errors: List[str] = []

    if disk_count != processed:
        errors.append(
            f"磁盘图片数({disk_count}) != 处理结果数({processed})"
        )
    if md_blocks != processed:
        errors.append(
            f"MD picture 块数({md_blocks}) != 处理结果数({processed})"
        )

    expected_names = {Path(r.abs_path).name for r in img_results if r.abs_path}
    disk_names = {p.name for p in disk_files}
    missing_on_disk = expected_names - disk_names
    extra_on_disk = disk_names - expected_names
    if missing_on_disk:
        errors.append(f"manifest 引用但磁盘缺失: {sorted(missing_on_disk)[:5]}")
    if extra_on_disk:
        errors.append(f"磁盘多余文件未入 manifest: {sorted(extra_on_disk)[:5]}")

    for r in img_results:
        if not r.abs_path or not Path(r.abs_path).is_file():
            errors.append(f"{r.image_id} 绝对路径不存在: {r.abs_path}")
        elif not full_text or r.image_id not in full_text:
            errors.append(f"normalized.md 未包含 {r.image_id} 的 picture 块")

    if source and source.suffix.lower() in {".docx", ".doc"}:
        media = extract_all_docx_media(source)
        inline = count_docx_inline_images(source)
        counts["docx_media_total"] = len(media)
        counts["docx_inline_refs"] = inline
        counts["docx_orphan_media"] = max(0, len(media) - inline)
        if processed < inline:
            errors.append(
                f"处理数({processed}) < DOCX 正文内联图数({inline})"
            )

    ok = len(errors) == 0
    report = {"ok": ok, "errors": errors, "counts": counts}
    level = logging.INFO if ok else logging.ERROR
    logger.log(
        level,
        "[RAG-文档标准化|doc_asset_validator|validate|硬编执行|完成] ok=%s; counts=%s; errors=%s",
        ok,
        counts,
        errors[:5],
    )
    return report
