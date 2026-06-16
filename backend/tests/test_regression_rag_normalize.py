"""RAG 文档标准化 + 分块 + 知识库 API 回归测试。"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("KB_NORMALIZE_ENABLED", "true")
os.environ.setdefault("VLM_IMAGE_ENABLED", "false")
os.environ.setdefault("BAIDU_OCR_ENABLED", "false")
os.environ.setdefault("MAX_IMAGES_PER_DOC", "30")


@pytest.fixture
def sample_md(tmp_path: Path) -> Path:
    p = tmp_path / "faq.md"
    p.write_text("# FAQ\n\n退货七天内可退。\n", encoding="utf-8")
    return p


@pytest.fixture
def sample_docx_with_image(tmp_path: Path) -> Path:
    """最小 docx：一段文字 + 1x1 PNG。"""
    p = tmp_path / "with_img.docx"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/2006/relationships/image" Target="media/image1.png"/>
</Relationships>"""
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:r><w:t>售后说明文档</w:t></w:r></w:p>
    <w:p><w:r><w:drawing>
      <wp:inline><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:blipFill><a:blip r:embed="rId1"/></pic:blipFill></pic:pic>
      </a:graphicData></a:graphic></wp:inline>
    </w:drawing></w:r></w:p>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/media/image1.png", png)
    return p


@pytest.fixture
def sample_xlsx_with_image(tmp_path: Path) -> Path:
    p = tmp_path / "sheet_img.xlsx"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("xl/media/image1.png", png)
        zf.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
    return p


@pytest.fixture
def sample_md_with_local_image(tmp_path: Path) -> Path:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (tmp_path / "screen.png").write_bytes(png)
    md = tmp_path / "manual.md"
    md.write_text(
        "# 运维助手\n\n2.1登录\n\n※作业画面：\n\n![登录页](screen.png)\n",
        encoding="utf-8",
    )
    return md


@pytest.fixture
def sample_docx_orphan_image(tmp_path: Path) -> Path:
    """DOCX：正文含 ※作业画面，图片仅在 word/media（无 document.xml 引用）。"""
    p = tmp_path / "manual_orphan.docx"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>2.1登录</w:t></w:r></w:p>
    <w:p><w:r><w:t>※作业画面：</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr("word/media/image1.png", png)
    return p


class TestDocInspector:
    def test_md_no_images(self, sample_md: Path):
        from app.services.doc_inspector import inspect_document

        r = inspect_document(sample_md)
        assert r["file_type"] == "md"
        assert r["file_size_bytes"] > 0
        assert r["estimated_image_count"] == 0
        assert r["requires_normalization"] is False

    def test_docx_estimates_images(self, sample_docx_with_image: Path):
        from app.services.doc_inspector import inspect_document

        r = inspect_document(sample_docx_with_image)
        assert r["estimated_image_count"] >= 1
        assert r["requires_normalization"] is True

    def test_xlsx_estimates_images(self, sample_xlsx_with_image: Path):
        from app.services.doc_inspector import inspect_document

        r = inspect_document(sample_xlsx_with_image)
        assert r["estimated_image_count"] >= 1

    def test_md_with_image_refs(self, sample_md_with_local_image: Path):
        from app.services.doc_inspector import inspect_document

        r = inspect_document(sample_md_with_local_image)
        assert r.get("markdown_image_refs", 0) >= 1
        assert r["requires_normalization"] is True


class TestDocNormalizer:
    def test_normalize_md(self, sample_md: Path):
        from app.services.doc_normalizer import normalize_document

        r = normalize_document(sample_md, tenant_id=1, doc_id=101)
        assert r.ok is True
        assert Path(r.normalized_md_path).is_file()
        assert Path(r.manifest_path).is_file()
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        assert manifest["ok"] is True
        assert manifest.get("image_count", 0) == 0

    def test_normalize_docx_extracts_image(self, sample_docx_with_image: Path):
        from app.services.doc_normalizer import normalize_document

        r = normalize_document(sample_docx_with_image, tenant_id=1, doc_id=102)
        assert r.ok is True
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        assert manifest["image_count"] >= 1
        assert manifest.get("pipeline_note") == "docx_p0_ordered"
        imgs = list(Path(r.assets_dir, "images").glob("img_*"))
        assert len(imgs) >= 1
        assert "{picture_id:" in r.text
        assert "url:" in r.text
        assert "description:" in r.text
        assert "售后说明文档" in r.text
        assert r.text.index("售后说明文档") < r.text.index("{picture_id:")
        assert "/output/kb_assets/" in r.text or "kb_assets" in r.text

    def test_normalize_xlsx_extracts_image(self, sample_xlsx_with_image: Path):
        from app.services.doc_normalizer import normalize_document

        r = normalize_document(sample_xlsx_with_image, tenant_id=1, doc_id=103)
        assert r.ok is True
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        assert manifest["image_count"] >= 1

    def test_normalize_md_download_link_describe_reinsert(self, sample_md_with_local_image: Path):
        from app.services.doc_normalizer import normalize_document

        r = normalize_document(sample_md_with_local_image, tenant_id=1, doc_id=105)
        assert r.ok is True
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        assert manifest["image_count"] >= 1
        assert manifest.get("pipeline_note") == "markdown_image_pipeline"
        assert "{picture_id:" in r.text
        assert "description:" in r.text
        assert "url:" in r.text
        assert manifest.get("validation", {}).get("ok") is True
        assert list(Path(r.assets_dir, "images").glob("img_*.png"))

    def test_normalize_docx_orphan_at_screen_marker(self, sample_docx_orphan_image: Path):
        from app.services.doc_normalizer import normalize_document

        r = normalize_document(sample_docx_orphan_image, tenant_id=1, doc_id=106)
        assert r.ok is True
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        assert manifest["image_count"] >= 1
        assert "※作业画面" in r.text
        pos_marker = r.text.index("※作业画面")
        pos_img = r.text.index("{picture_id:")
        assert pos_marker < pos_img
        assert "url:" in r.text
        assert manifest.get("validation", {}).get("ok") is True


class TestImagePipelineIntegration:
    def test_manifest_public_url_fetchable(self, sample_docx_with_image: Path):
        from app.services.doc_normalizer import normalize_document
        from app.services.haici_output import get_output_dir

        r = normalize_document(sample_docx_with_image, tenant_id=1, doc_id=107)
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        url = manifest["images"][0]["public_url"]
        assert url.startswith("/output/")
        rel = url[len("/output/") :]
        assert (get_output_dir() / rel.replace("/", "\\")).is_file() or (get_output_dir() / rel).is_file()


@pytest.fixture
def sample_mineru_pdf_md(tmp_path: Path) -> tuple[Path, Path]:
    """模拟 MinerU PDF 产出：md 含 ![](images/...) 与本地切图。"""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    mineru_dir = tmp_path / "mineru_out" / "manual"
    img_dir = mineru_dir / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "page1_img1.png").write_bytes(png)
    md = mineru_dir / "manual.md"
    md.write_text(
        "# 运维手册\n\n2.1 登录\n\n![登录界面](images/page1_img1.png)\n",
        encoding="utf-8",
    )
    pdf_stub = tmp_path / "manual.pdf"
    pdf_stub.write_bytes(b"%PDF-1.4 stub")
    return pdf_stub, mineru_dir


class TestPdfMineruPipeline:
    def test_describe_mineru_markdown_reinsert(self, tmp_path: Path, sample_mineru_pdf_md):
        from app.services.doc_normalizer import _describe_mineru_markdown
        from app.services.haici_output import kb_assets_dir

        pdf_stub, mineru_dir = sample_mineru_pdf_md
        asset_root = kb_assets_dir(1, "pdf_test")
        asset_root.mkdir(parents=True, exist_ok=True)
        md = (mineru_dir / "manual.md").read_text(encoding="utf-8")

        full_text, img_results, truncated = _describe_mineru_markdown(
            md,
            asset_root,
            mineru_dir,
            source_format="pdf",
            limit=30,
            doc_context_prefix=md[:500],
        )
        assert len(img_results) >= 1
        assert "{picture_id:" in full_text
        assert "url:" in full_text
        assert "description:" in full_text
        assert "/output/kb_assets/" in full_text or "kb_assets" in full_text
        assert "images/page1_img1.png" not in full_text or "{picture_id:" in full_text
        assert img_results[0].pipeline
        assert list((asset_root / "images").glob("img_*.png"))

    def test_normalize_pdf_via_mineru_mock(self, tmp_path: Path, sample_mineru_pdf_md, monkeypatch):
        from app.services.doc_normalizer import normalize_document

        pdf_stub, mineru_dir = sample_mineru_pdf_md
        md = (mineru_dir / "manual.md").read_text(encoding="utf-8")

        def _fake_mineru(source, asset_root):
            return md, mineru_dir

        monkeypatch.setattr(
            "app.services.doc_normalizer._mineru_to_text",
            _fake_mineru,
        )
        r = normalize_document(pdf_stub, tenant_id=1, doc_id=201)
        assert r.ok is True
        manifest = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
        assert manifest["image_count"] >= 1
        assert manifest.get("pipeline_note") == "mineru_pdf"
        assert "{picture_id:" in r.text
        assert "/output/kb_assets/" in r.text or "kb_assets" in r.text


class TestKbChunkService:
    def test_split_after_normalize(self, sample_md: Path):
        from app.services.doc_normalizer import normalize_document
        from app.services.kb_chunk_service import split_to_documents

        r = normalize_document(sample_md, tenant_id=1, doc_id=104)
        docs = split_to_documents(r.text, 104, "faq.md", mode="md_header")
        assert len(docs) >= 1
        assert docs[0].metadata.get("document_id") == 104


class TestHaiciOutput:
    def test_public_url(self, tmp_path: Path, monkeypatch):
        from app.services import haici_output as ho

        out = ho.get_output_dir()
        p = out / "kb_assets" / "1" / "99" / "images" / "img_0001.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake")
        url = ho.abs_path_to_public_url(p)
        assert url.startswith("/output/kb_assets/")
        assert "img_0001.png" in url


class TestKnowledgeSchemas:
    def test_document_item_fields(self):
        from app.schemas import KnowledgeDocumentItem
        from datetime import datetime

        item = KnowledgeDocumentItem(
            id=1,
            filename="a.pdf",
            status="ready",
            chunk_count=3,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            file_type="pdf",
            file_size_bytes=1024,
            file_size_human="1.0 KB",
            image_count=2,
            vlm_limit=30,
            truncated=False,
        )
        assert item.image_count == 2
        assert item.vlm_limit == 30
