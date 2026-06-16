"""知识库管理模块回归测试 (PRD §2)

测试用例:
1. 上传文档（.txt）
2. 获取文档列表
3. 删除文档
"""

import os
import tempfile

import pytest
import requests

from tests.http_regression_helpers import BASE_URL, login_password


def _login():
    return login_password()


class TestKnowledgeUpload:
    """TC-KNOWLEDGE-001: 上传文档"""

    def test_upload_txt(self):
        """上传 .txt 文档并验证入库"""
        token = _login()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
            f.write("这是测试文档内容。\n用于验证知识库上传功能。\n它包含多行文本。")
            tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                resp = requests.post(
                    f"{BASE_URL}/knowledge/upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("test_doc.txt", f, "text/plain")},
                    data={"slice_method": "auto"},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("filename") == "test_doc.txt"
            assert data.get("status") in ("processing", "ready", "failed")
            if data.get("status") == "failed":
                assert data.get("error_message"), "失败态应返回可观测 error_message"
        finally:
            os.unlink(tmp_path)

    def test_upload_unsupported_format(self):
        """上传不支持格式应失败"""
        token = _login()
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                resp = requests.post(
                    f"{BASE_URL}/knowledge/upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("malware.exe", f, "application/octet-stream")},
                )
            assert resp.status_code == 400
        finally:
            os.unlink(tmp_path)

    def test_get_knowledge_list(self):
        """获取知识库文档列表"""
        token = _login()
        resp = requests.get(
            f"{BASE_URL}/knowledge?page=1&size=20",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data


class TestKnowledgeDelete:
    """TC-KNOWLEDGE-002: 删除文档"""

    def test_delete_document(self):
        """上传后删除文档"""
        token = _login()
        # 1. 上传
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
            f.write("待删除文档内容")
            tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                upload_resp = requests.post(
                    f"{BASE_URL}/knowledge/upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("del_test.txt", f, "text/plain")},
                )
            if upload_resp.status_code != 200:
                pytest.skip("上传失败")
            doc_id = upload_resp.json()["id"]
            # 2. 删除
            del_resp = requests.delete(
                f"{BASE_URL}/knowledge/{doc_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert del_resp.status_code == 200
        finally:
            os.unlink(tmp_path)

    def test_delete_nonexistent_document(self):
        """删除不存在的文档应返回404"""
        token = _login()
        resp = requests.delete(
            f"{BASE_URL}/knowledge/99999",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
