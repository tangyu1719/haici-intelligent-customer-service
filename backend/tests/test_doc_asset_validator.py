"""picture 块格式与资产硬编校验测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.doc_asset_validator import count_picture_blocks_in_md, validate_normalization_assets
from app.services.doc_image_pipeline import ImageProcessResult, build_rag_image_block


def test_build_rag_image_block_uses_abs_path_and_picture_format(tmp_path: Path):
    img = tmp_path / "images" / "img_0001.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"png")
    res = ImageProcessResult(
        image_id="img_0001",
        file_name="img_0001.png",
        abs_path=str(img),
        public_url="/output/kb_assets/1/1/images/img_0001.png",
        vlm_description="该页面是云仓系统数据字典模块的运维助手操作界面。",
    )
    block = build_rag_image_block(res, ordinal=1)
    assert block.startswith("{picture_id:图1-img_0001;")
    assert f"url:{img.resolve()};" in block or str(img.resolve()) in block
    assert "description:" in block
    assert "数据字典" in block
    assert block.strip().endswith("}")


def test_validate_normalization_assets_ok(tmp_path: Path):
    asset_root = tmp_path / "assets"
    images = asset_root / "images"
    images.mkdir(parents=True)
    p = images / "img_0001.png"
    p.write_bytes(b"x")
    res = ImageProcessResult(
        image_id="img_0001",
        file_name="img_0001.png",
        abs_path=str(p),
        public_url="/output/x",
        vlm_description="描述",
    )
    block = build_rag_image_block(res, ordinal=1)
    report = validate_normalization_assets(asset_root, block, [res])
    assert report["ok"] is True
    assert report["counts"]["disk_download_count"] == 1
    assert report["counts"]["md_picture_blocks"] == count_picture_blocks_in_md(block)


def test_count_picture_blocks_ignores_nested_in_description():
    nested = (
        "{picture_id:图1-img_0001;\n"
        "url:/x;\n"
        "description:\n"
        "参见 {picture_id:图2-img_0002; url:/y; description: 内嵌}\n"
        "}"
    )
    assert count_picture_blocks_in_md(nested) == 1


def test_validate_normalization_assets_truncated_allows_extra_md_blocks(tmp_path: Path):
    asset_root = tmp_path / "assets"
    images = asset_root / "images"
    images.mkdir(parents=True)
    p = images / "img_0001.png"
    p.write_bytes(b"x")
    res = ImageProcessResult(
        image_id="img_0001",
        file_name="img_0001.png",
        abs_path=str(p),
        public_url="/output/x",
        vlm_description="描述",
    )
    block = build_rag_image_block(res, ordinal=1)
    extra = "{picture_id:图2-img_0002;url:/x;description:未处理占位}"
    md = block + "\n" + extra
    report = validate_normalization_assets(asset_root, md, [res], truncated=True)
    assert report["ok"] is True
    report_strict = validate_normalization_assets(asset_root, md, [res], truncated=False)
    assert report_strict["ok"] is False


def test_validate_normalization_assets_mismatch(tmp_path: Path):
    asset_root = tmp_path / "assets"
    (asset_root / "images").mkdir(parents=True)
    res = ImageProcessResult(
        image_id="img_0001",
        file_name="img_0001.png",
        abs_path=str(asset_root / "images" / "img_0001.png"),
        public_url="/output/x",
    )
    report = validate_normalization_assets(asset_root, "", [res])
    assert report["ok"] is False
    assert report["errors"]
