#!/usr/bin/env python3
"""将 RAG测试文档 目录批量导入知识库（需后端已启动）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

DEFAULT_BASE = "http://127.0.0.1:8012"
DEFAULT_DOCS = Path(__file__).resolve().parents[1] / "RAG测试文档"
SUFFIXES = {
    ".txt", ".md", ".markdown", ".pdf",
    ".doc", ".docx", ".csv", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
}


def _client() -> httpx.Client:
    return httpx.Client(timeout=600.0, trust_env=False)


def login(base: str, username: str, password: str) -> str:
    with _client() as client:
        r = client.post(
            f"{base}/api/v1/auth/login",
            json={"identifier": username, "credential": password},
        )
    if r.status_code != 200:
        raise SystemExit(f"登录失败 HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise SystemExit(f"登录响应无 token: {data}")
    return token


def upload_one(base: str, token: str, path: Path, slice_method: str = "") -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    with _client() as client, path.open("rb") as f:
        data = {}
        if slice_method:
            data["slice_method"] = slice_method
        r = client.post(
            f"{base}/api/v1/knowledge/upload",
            headers=headers,
            files={"file": (path.name, f, "application/octet-stream")},
            data=data,
        )
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    if r.status_code != 200:
        return {"ok": False, "file": path.name, "status": r.status_code, "body": body}
    return {"ok": True, "file": path.name, "id": body.get("id"), "status": body.get("status"), "chunks": body.get("chunk_count")}


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 RAG测试文档 到 HaiCi 知识库")
    parser.add_argument("--base", default=DEFAULT_BASE, help="后端根地址")
    parser.add_argument("--docs", default=str(DEFAULT_DOCS), help="文档目录")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--slice-method", default="", help="分块策略，如 md_header / dynamic_semantic / ai_semantic")
    args = parser.parse_args()

    docs_dir = Path(args.docs)
    if not docs_dir.is_dir():
        raise SystemExit(f"目录不存在: {docs_dir}")

    files = sorted([p for p in docs_dir.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES])
    if not files:
        raise SystemExit(f"目录内无可导入文件: {docs_dir}")

    token = login(args.base, args.username, args.password)
    results = []
    for p in files:
        print(f"上传 {p.name} …", flush=True)
        results.append(upload_one(args.base, token, p, slice_method=args.slice_method))

    ok = sum(1 for x in results if x.get("ok"))
    print(json.dumps({"imported": ok, "total": len(results), "results": results}, ensure_ascii=False, indent=2))
    if ok < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
