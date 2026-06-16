# -*- coding: utf-8 -*-
"""快速导入 RAG 测试文档（关闭 VLM，延长超时）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAG_DIR = PROJECT_ROOT / "RAG测试文档"
BASE_URL = "http://127.0.0.1:8012/api/v1"
UPLOAD_TIMEOUT = 1800

FILES = [
    "WMS系统高频报错代码及解决方案手册（简体中文）（V1.0）.docx",
    "_云盒培训文档_converted.docx",
    "运维助手用户手册-V1.0.docx",
]


def login() -> str:
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"identifier": "admin", "credential": "admin"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def list_docs(token: str) -> list:
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE_URL}/knowledge?page=1&page_size=200", headers=h, timeout=120)
    r.raise_for_status()
    return r.json().get("items", [])


def upload(token: str, path: Path) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    with path.open("rb") as f:
        r = requests.post(
            f"{BASE_URL}/knowledge/upload",
            headers=h,
            files={"file": (path.name, f)},
            data={"slice_method": "auto"},
            timeout=UPLOAD_TIMEOUT,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"上传失败 {path.name}: {r.status_code} {r.text[:400]}")
    return r.json()


def main() -> int:
    token = login()
    existing = {d["filename"]: d for d in list_docs(token)}
    ok_all = True
    for name in FILES:
        path = RAG_DIR / name
        if not path.is_file():
            print(f"SKIP 不存在: {path}")
            ok_all = False
            continue
        prev = existing.get(name)
        if prev and prev.get("status") == "ready" and prev.get("chunk_count", 0) > 0:
            print(f"OK    已就绪: {name} id={prev['id']} chunks={prev['chunk_count']}")
            continue
        if prev and prev.get("status") in ("failed", "processing"):
            print(f"DEL   清理旧记录: {name} id={prev['id']} status={prev['status']}")
            requests.delete(
                f"{BASE_URL}/knowledge/{prev['id']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
        print(f"UPLOAD {name} ...")
        t0 = time.perf_counter()
        result = upload(token, path)
        dt = time.perf_counter() - t0
        status = result.get("status")
        chunks = result.get("chunk_count", 0)
        err = result.get("error_message") or ""
        print(f"  -> id={result.get('id')} status={status} chunks={chunks} time={dt:.1f}s")
        if err:
            print(f"  ERR: {err[:300]}")
        if status != "ready" or chunks <= 0:
            ok_all = False
            print(f"FAIL  {name}")
            return 1
        print(f"OK    {name}")
    print("\n=== 导入完成 ===")
    for d in list_docs(token):
        if d["filename"] in FILES:
            print(f"  {d['filename']}: status={d['status']} chunks={d['chunk_count']}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
