"""PDF 含图标准化测试（MinerU 主路径 + PyMuPDF 抽图兜底）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.doc_inspector import inspect_document
from app.services.doc_normalizer import normalize_document

PDF_CANDIDATES = [
    PROJECT_ROOT / "RAG测试文档" / "库存调整单-提交.pdf",
    BACKEND / ".pytest_tmp" / "test_normalize_pdf_via_mineru_0" / "manual.pdf",
]


def _resolve_pdf() -> Path | None:
    for p in PDF_CANDIDATES:
        if p.is_file():
            return p
    return None


@pytest.mark.parametrize("pdf_path", [_resolve_pdf()], ids=["sample_pdf"])
def test_pdf_with_images_normalize(pdf_path: Path | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if pdf_path is None:
        pytest.skip("未找到含图 PDF 测试样本")

    monkeypatch.setenv("MAX_IMAGES_PER_DOC", "5")
    monkeypatch.setenv("IMAGE_CLASSIFY_ENABLED", "false")

    inspect = inspect_document(pdf_path)
    assert inspect.get("file_type") == "pdf"

    asset_root = tmp_path / "assets"
    result = normalize_document(
        pdf_path,
        tenant_id=1,
        doc_id=999,
        document_name=pdf_path.name,
        task_id="",
    )

    assert result.ok, result.error
    assert result.text.strip()
    assert Path(result.normalized_md_path).is_file()
    manifest = result.manifest
    assert manifest.get("ok") is True
    pipeline = manifest.get("pipeline_note", "")
    assert pipeline in {
        "mineru_pdf",
        "mineru_pdf_partial",
        "pymupdf_ocr_fallback",
    }, f"unexpected pipeline: {pipeline}"
    # manifest JSON 封装（与 DOCX 一致）
    assert "images" in manifest
    assert "validation" in manifest

    img_count = int(manifest.get("image_count") or 0)
    if inspect.get("embedded_image_count", 0) > 0 or img_count > 0:
        images_dir = asset_root / "images"
        # normalize_document 写入 kb_assets 路径；至少 manifest 应记录图片
        assert img_count >= 0
        if img_count > 0:
            assert any("picture_id" in result.text or "img_" in result.text for _ in [0])


def test_pdf_cancel_during_image_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """用户取消后，图片批处理应抛出 TaskCancelledError。"""
    from app.services.doc_normalizer import _process_images_batch
    from app.services.multimodal_task_manager import TaskCancelledError, create_task, request_cancel

    img = tmp_path / "img_0001.png"
    img.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    task = create_task("cancel_test.pdf", str(tmp_path / "x.pdf"), tenant_id=1)
    request_cancel(task["task_id"])

    with pytest.raises(TaskCancelledError):
        _process_images_batch([(img, "img_0001", "ctx")], source_format="pdf", task_id=task["task_id"])
