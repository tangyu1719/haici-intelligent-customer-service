"""多模态模块回归测试 (PRD 多模态加分项)

测试用例:
1. 获取支持格式列表
2. 上传图片文件
3. 获取output路径信息
"""

import tempfile

import pytest
import requests

from tests.http_regression_helpers import BASE_URL, login_password


def _login():
    return login_password()


class TestMultimodalConfig:
    """TC-MULTIMODAL-001: 多模态配置"""

    def test_supported_formats(self):
        """获取支持的文件格式列表"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/multimodal/formats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "formats" in data or "ok" in data

    def test_output_path_info(self):
        """获取 output 路径信息"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/multimodal/output-path",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data or "path" in data


class TestMultimodalUpload:
    """TC-MULTIMODAL-002: 文件上传"""

    def test_upload_image(self):
        """上传PNG图片（1x1像素最小PNG）"""
        token = _login()
        # 最小 PNG: 1x1 透明像素
        min_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
            b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        resp = requests.post(
            f"{BASE_URL}/multimodal/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("test_1px.png", min_png, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data

    def test_upload_text_file(self):
        """上传文本文件"""
        token = _login()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
            f.write("多模态测试文本内容")
            tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                resp = requests.post(
                    f"{BASE_URL}/multimodal/upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("test.txt", f, "text/plain")},
                )
            assert resp.status_code == 200
        finally:
            import os
            os.unlink(tmp_path)
