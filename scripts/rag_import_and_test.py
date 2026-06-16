# -*- coding: utf-8 -*-
"""RAG 文档导入与问答测试脚本（API + 可选前端监控）。"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAG_DIR = PROJECT_ROOT / "RAG测试文档"
BASE_URL = "http://127.0.0.1:8012/api/v1"
MAX_LATENCY_SEC = 40


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
    r = requests.get(f"{BASE_URL}/knowledge?page=1&page_size=200", headers=h, timeout=60)
    r.raise_for_status()
    return r.json().get("items", [])


def upload_file(token: str, path: Path, kb_id: int | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    data = {"slice_method": "auto"}
    if kb_id:
        data["kb_id"] = str(kb_id)
    with path.open("rb") as f:
        r = requests.post(
            f"{BASE_URL}/knowledge/upload",
            headers=h,
            files={"file": (path.name, f)},
            data=data,
            timeout=600,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"上传失败 {path.name}: {r.status_code} {r.text[:300]}")
    return r.json()


def create_session(token: str) -> int:
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{BASE_URL}/sessions", headers=h, json={}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def chat_stream(token: str, session_id: int, question: str, kb_id: int | None = None) -> dict:
    """消费 SSE 流并返回时延与内容。"""
    h = {"Authorization": f"Bearer {token}"}
    body = {"session_id": session_id, "question": question}
    if kb_id:
        body["kb_id"] = kb_id
    start = time.perf_counter()
    r = requests.post(
        f"{BASE_URL}/chat/stream",
        headers=h,
        json=body,
        stream=True,
        timeout=MAX_LATENCY_SEC + 10,
    )
    content_parts = []
    citations = []
    meta = {}
    done = {}
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            if event == "token":
                content_parts.append(payload.get("content", ""))
            elif event == "citations":
                citations = payload.get("items", [])
            elif event == "meta":
                meta = payload
            elif event == "done":
                done = payload
    elapsed = time.perf_counter() - start
    full = done.get("content") or "".join(content_parts)
    return {
        "elapsed_sec": round(elapsed, 2),
        "content": full,
        "citations": citations,
        "meta": meta,
        "ok": r.status_code == 200 and len(full.strip()) > 0,
    }


def cmd_list(token: str):
    for d in list_docs(token):
        err = d.get("error_message") or ""
        print(f"{d['id']:3} {d['status']:10} chunks={d['chunk_count']:3} {d['filename']}")
        if err:
            print(f"    ERR: {err[:150]}")


def cmd_import(token: str, filenames: list[str]):
    existing = {d["filename"]: d for d in list_docs(token)}
    for name in filenames:
        path = RAG_DIR / name
        if not path.is_file():
            print(f"SKIP 文件不存在: {path}")
            continue
        prev = existing.get(name)
        if prev and prev["status"] == "ready" and prev["chunk_count"] > 0:
            print(f"OK    已就绪跳过: {name} (id={prev['id']}, chunks={prev['chunk_count']})")
            continue
        print(f"UPLOAD {name} ...")
        t0 = time.perf_counter()
        result = upload_file(token, path)
        dt = time.perf_counter() - t0
        status = result.get("status")
        chunks = result.get("chunk_count", 0)
        err = result.get("error_message") or ""
        print(f"  -> id={result.get('id')} status={status} chunks={chunks} time={dt:.1f}s")
        if err:
            print(f"  ERR: {err[:200]}")
        if status != "ready" or chunks <= 0:
            raise SystemExit(f"导入失败: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["list", "import", "chat"])
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--question", default="你好")
    args = parser.parse_args()
    token = login()
    if args.action == "list":
        cmd_list(token)
    elif args.action == "import":
        cmd_import(token, args.files)
    elif args.action == "chat":
        sid = create_session(token)
        res = chat_stream(token, sid, args.question)
        print(json.dumps(res, ensure_ascii=False, indent=2))
