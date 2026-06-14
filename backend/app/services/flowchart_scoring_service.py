"""流程图单页得分 —— 封装 src/agent/tools/flowchart_scoring_pipeline.py 供 Web 多模态页调用。"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .haici_output import get_output_dir, is_under_output_dir

_LOG = logging.getLogger(__name__)

_TOOLS_DIR: Optional[Path] = None
for _p in Path(__file__).resolve().parents:
    _candidate = _p / "src" / "agent" / "tools"
    if _candidate.is_dir():
        _TOOLS_DIR = _candidate.resolve()
        break

if _TOOLS_DIR and str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_FLOWCHART_INPUT_SUFFIXES = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)


def _log_event(
    action: str,
    *,
    stage: str,
    obj: str,
    ok: Optional[bool] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    parts = [f"[多模态Web-流程图得分|flowchart_scoring_service|{obj}|硬编执行|{stage}] {action}"]
    if ok is not None:
        parts.append(f"ok={ok}")
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}={v}")
    _LOG.info("; ".join(parts))


def abs_path_to_output_url(abs_path: str | Path) -> str:
    """将 output 根下的绝对路径转为 /output/ 相对 URL（支持子目录）。"""
    p = Path(abs_path).resolve()
    root = get_output_dir().resolve()
    try:
        rel = p.relative_to(root).as_posix()
    except ValueError:
        return ""
    from urllib.parse import quote

    return "/output/" + quote(rel, safe="/")


def _collect_column_cuts(report: Dict[str, Any]) -> List[int]:
    cuts: List[int] = []
    merge = report.get("merge_stage") or {}
    for cell in merge.get("column_band_cells") or []:
        for y in cell.get("cuts_abs") or []:
            yi = int(y)
            if yi not in cuts:
                cuts.append(yi)
    return sorted(cuts)


def _summarize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    geom = report.get("geometry_score") or {}
    merge = report.get("merge_stage") or {}
    return {
        "method": report.get("method"),
        "source": report.get("source"),
        "work_dir": report.get("work_dir"),
        "origin_page": report.get("origin_page"),
        "raw_cv_blocks": report.get("raw_cv_blocks"),
        "final_block_count": report.get("final_block_count"),
        "geometry_score": geom,
        "merge_stage": {
            "column_band_split": merge.get("column_band_split"),
            "column_band_cells": merge.get("column_band_cells"),
            "box_refine": merge.get("box_refine"),
        },
        "column_band_cuts": _collect_column_cuts(report),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
    }


def run_flowchart_score(
    file_path: str,
    *,
    page: int = 1,
    zoom: float = 2.0,
    mineru_json: str = "",
    column_band_split: bool = True,
    column_bands: int = 0,
    min_band_h: int = 48,
    skip_arrows: bool = True,
    artifact_subdir: str = "",
) -> Dict[str, Any]:
    """
    对 PDF/图片跑流程图得分链路，产物落在 output/flowchart_scoring_web/ 下以便 /output 静态访问。
    """
    src = Path(file_path).resolve()
    obj = src.name
    if not src.is_file():
        _log_event("路径无效", stage="校验", obj=obj, ok=False)
        return {"ok": False, "error": "路径无效或不是可读文件", "file_path": str(src)}
    if src.suffix.lower() not in _FLOWCHART_INPUT_SUFFIXES:
        _log_event("扩展名不支持", stage="校验", obj=obj, ok=False, extra={"suffix": src.suffix})
        return {
            "ok": False,
            "error": f"流程图得分仅支持: {', '.join(sorted(_FLOWCHART_INPUT_SUFFIXES))}",
            "file_path": str(src),
        }

    job_id = (artifact_subdir or "").strip() or uuid.uuid4().hex[:12]
    art_root = (get_output_dir() / "flowchart_scoring_web" / job_id).resolve()
    art_root.mkdir(parents=True, exist_ok=True)

    _log_event(
        "开始",
        stage="执行",
        obj=obj,
        extra={
            "page": page,
            "column_bands": column_bands,
            "column_band_split": column_band_split,
            "job_id": job_id,
        },
    )

    try:
        from flowchart_scoring_pipeline import FlowchartPageInput, run_flowchart_page_pipeline

        mj = Path(mineru_json).resolve() if mineru_json else None
        if mj and not mj.is_file():
            mj = None
        inp = FlowchartPageInput(
            source=src,
            page=max(1, int(page)),
            zoom=float(zoom),
            artifact_root=art_root,
            mineru_json=mj,
            column_band_split=bool(column_band_split),
            column_bands=int(column_bands),
            min_band_h=int(min_band_h),
            skip_arrows=bool(skip_arrows),
        )
        report = run_flowchart_page_pipeline(inp)
    except Exception as exc:
        _log_event(
            "链路异常",
            stage="失败",
            obj=obj,
            ok=False,
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:500]},
        )
        return {"ok": False, "error": str(exc), "file_path": str(src), "job_id": job_id}

    overlay_abs = report.get("debug_overlay") or ""
    overlay_url = abs_path_to_output_url(overlay_abs) if overlay_abs else ""
    work_dir = report.get("work_dir") or str(art_root)
    geom = report.get("geometry_score") or {}
    summary = _summarize_report(report)

    under = is_under_output_dir(Path(work_dir)) if work_dir else False
    _log_event(
        "完成",
        stage="收尾",
        obj=obj,
        ok=True,
        extra={
            "block_count": report.get("final_block_count"),
            "overlap_pair_count": geom.get("overlap_pair_count"),
            "overlay_under_output": under,
        },
    )

    return {
        "ok": True,
        "file_path": str(src),
        "job_id": job_id,
        "work_dir": work_dir,
        "overlay_path": overlay_abs,
        "overlay_url": overlay_url,
        "origin_page": report.get("origin_page"),
        "origin_url": abs_path_to_output_url(report.get("origin_page") or ""),
        "geometry_score": geom,
        "final_block_count": report.get("final_block_count"),
        "overlap_ok": bool(geom.get("overlap_ok")),
        "column_band_cuts": summary.get("column_band_cuts") or [],
        "report": summary,
        "report_path": str(Path(work_dir) / "flowchart_scoring_report.json"),
        "error": "",
    }
