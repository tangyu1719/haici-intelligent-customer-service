"""PDF 流程图专用识别管道 — 封装 src/agent/tools/flowchart_service（+ MERMIZED.md）。"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TOOLS_DIR: Optional[Path] = None
for _p in Path(__file__).resolve().parents:
    _candidate = _p / "src" / "agent" / "tools"
    if _candidate.is_dir() and (_candidate / "flowchart_service.py").is_file():
        _TOOLS_DIR = _candidate.resolve()
        break

if _TOOLS_DIR and str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def likely_flowchart_pdf(source: Path, *, page: int = 1, min_blocks: int = 4) -> bool:
    """启发式判定 PDF 首页是否为流程图（线框块检测 + 文本特征兜底）。"""
    source = source.resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        return False

    try:
        import cv2
        import fitz
        import numpy as np
        from fast_linebox_blocks import Params, detect_line_boxes

        doc = fitz.open(str(source))
        try:
            pidx = max(0, int(page) - 1)
            pg = doc[pidx]
            pix = pg.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            bgr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                bgr = cv2.cvtColor(bgr, cv2.COLOR_RGBA2BGR)
            elif pix.n == 1:
                bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
        finally:
            doc.close()

        p = Params(min_area=12000.0, max_ar=20.0, close_k=7, strip_long_lines=True)
        boxes, _ = detect_line_boxes(bgr, p)
        if len(boxes) >= min_blocks:
            logger.info(
                "[RAG-流程图PDF|flowchart_pdf_service|likely_flowchart_pdf|硬编执行|CV命中] source=%s; blocks=%s",
                source.name,
                len(boxes),
            )
            return True
    except Exception as exc:
        logger.warning(
            "[RAG-流程图PDF|flowchart_pdf_service|likely_flowchart_pdf|硬编执行|CV跳过] err=%s",
            str(exc)[:200],
        )

    try:
        import fitz

        doc = fitz.open(str(source))
        text = doc[max(0, int(page) - 1)].get_text() or ""
        doc.close()
        markers = ("IF ", "if ", "抛错", "调用", "循环", "→", "->", "submit", "Component")
        hits = sum(1 for m in markers if m in text)
        if hits >= 4 and len(text) > 200:
            logger.info(
                "[RAG-流程图PDF|flowchart_pdf_service|likely_flowchart_pdf|硬编执行|文本命中] source=%s; hits=%s",
                source.name,
                hits,
            )
            return True
    except Exception:
        pass
    return False


def run_flowchart_pdf_pipeline(
    source: Path,
    asset_root: Path,
    *,
    page: int = 1,
    skip_llm: bool = True,
    document_title: str = "",
) -> Dict[str, Any]:
    """
    跑 MinerU + CV + 箭头 + Mermaid 全链路，产物写入 asset_root/flowchart_pipeline/。
    主交付：MERMIZED.md（含 ```mermaid 块）。
    MinerU 不可用时降级为 CV-only（仍产出 Mermaid 拓扑，节点标签可能为 N1/N2…）。
    """
    from flowchart_service import FlowchartServiceInput, execute_flowchart_service

    source = source.resolve()
    asset_root.mkdir(parents=True, exist_ok=True)
    fc_root = (asset_root / "flowchart_pipeline").resolve()
    fc_root.mkdir(parents=True, exist_ok=True)

    logger.info(
        "[RAG-流程图PDF|flowchart_pdf_service|run_flowchart_pdf_pipeline|Agent执行|开始] source=%s; page=%s",
        source.name,
        page,
    )

    def _execute(*, skip_mineru: bool, allow_no_json: bool) -> Any:
        inp = FlowchartServiceInput(
            pdf=source,
            artifact_root=fc_root,
            page=int(page),
            zoom=2.0,
            skip_llm=bool(skip_llm),
            quiet=True,
            skip_auto_mineru_chain=skip_mineru,
            allow_no_mineru_json=allow_no_json,
        )
        return execute_flowchart_service(inp)

    out = _execute(skip_mineru=False, allow_no_json=False)
    degraded = False
    mineru_err = ""
    if not out.ok:
        mineru_err = out.error or "MinerU 链失败"
        logger.warning(
            "[RAG-流程图PDF|flowchart_pdf_service|run_flowchart_pdf_pipeline|Agent执行|MinerU链失败降级CV] source=%s; err=%s",
            source.name,
            mineru_err[:300],
        )
        out = _execute(skip_mineru=True, allow_no_json=True)
        degraded = True

    if not out.ok:
        err = out.error or "流程图识别服务失败"
        logger.error(
            "[RAG-流程图PDF|flowchart_pdf_service|run_flowchart_pdf_pipeline|Agent执行|失败] source=%s; err=%s",
            source.name,
            err[:500],
        )
        return {"ok": False, "error": err, "report": out.report}

    deliver = out.mermized_md or out.deliverable_md
    if deliver is None or not deliver.is_file():
        return {"ok": False, "error": "未生成 MERMIZED.md / flowchart_deliverable.md", "report": out.report}

    full_text = deliver.read_text(encoding="utf-8")
    title = document_title or source.stem
    if not full_text.lstrip().startswith("#"):
        full_text = f"# {title}\n\n{full_text}"

    if degraded:
        full_text = (
            f"> ⚠️ MinerU 映射链不可用，已降级为 **CV-only** 流程图识别（拓扑 Mermaid 可用，"
            f"节点标签可能为占位符）。原始错误见 manifest。\n\n{full_text}"
        )

    origin_png: Path | None = None
    work = out.work_dir
    if work and work.is_dir():
        cand = work / "origin_page.png"
        if cand.is_file():
            origin_png = cand

    images_dir = asset_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    if origin_png and origin_png.is_file():
        dest_img = images_dir / "img_0001.png"
        shutil.copy2(origin_png, dest_img)

    md_path = asset_root / "normalized.md"
    txt_path = asset_root / "normalized.txt"
    md_path.write_text(full_text, encoding="utf-8")
    txt_path.write_text(full_text, encoding="utf-8")

    mermaid_blocks = full_text.count("```mermaid")
    manifest = {
        "ok": True,
        "source": str(source),
        "document_title": title,
        "pipeline_note": "flowchart_mermaid_cv_only" if degraded else "flowchart_mermaid",
        "flowchart_pipeline": True,
        "flowchart_degraded": degraded,
        "mermaid_block_count": mermaid_blocks,
        "node_count": out.node_count,
        "edge_count": out.edge_count,
        "MERMIZED_md": str(deliver.resolve()),
        "flowchart_work_dir": str(work) if work else "",
        "flowchart_report_json": str(out.report_json) if out.report_json else "",
        "images": [],
        "image_count": 0,
        "truncated": False,
    }
    if degraded and mineru_err:
        manifest["mineru_chain_error"] = str(mineru_err)[:500]
    if origin_png and origin_png.is_file():
        manifest["origin_page"] = str((images_dir / "img_0001.png").resolve())

    mp = asset_root / "manifest.json"
    import json

    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "[RAG-流程图PDF|flowchart_pdf_service|run_flowchart_pdf_pipeline|Agent执行|完成] source=%s; nodes=%s; edges=%s; mermaid_blocks=%s; degraded=%s",
        source.name,
        out.node_count,
        out.edge_count,
        mermaid_blocks,
        degraded,
    )

    return {
        "ok": True,
        "text": full_text,
        "normalized_md_path": str(md_path),
        "normalized_txt_path": str(txt_path),
        "manifest_path": str(mp),
        "manifest": manifest,
        "node_count": out.node_count,
        "edge_count": out.edge_count,
        "mermaid_block_count": mermaid_blocks,
        "degraded": degraded,
        "report": out.report,
    }
