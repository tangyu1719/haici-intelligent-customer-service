"""多模态 MD 改造联调：上传 docx → 轮询任务与日志。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8012"
DOC = Path(__file__).resolve().parents[2] / "RAG测试文档" / "运维助手用户手册-V1.0.docx"


def main() -> int:
    print("file exists", DOC.exists(), DOC.stat().st_size if DOC.exists() else 0)
    if not DOC.is_file():
        print("测试文件不存在:", DOC)
        return 1

    r = requests.post(
        f"{BASE}/api/v1/auth/login",
        json={"login_type": "password", "identifier": "admin", "credential": "admin"},
        timeout=10,
    )
    print("login", r.status_code)
    if r.status_code != 200:
        print(r.text)
        return 1
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    with DOC.open("rb") as f:
        r3 = requests.post(
            f"{BASE}/api/v1/multimodal-tasks/upload",
            headers=h,
            files={"file": (DOC.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"slice_method": "auto"},
            timeout=30,
        )
    print("upload", r3.status_code, r3.text[:500])
    if r3.status_code != 200:
        return 1

    task_id = r3.json()["task_id"]
    print("task_id", task_id)

    for i in range(80):
        td = requests.get(f"{BASE}/api/v1/multimodal-tasks/{task_id}", headers=h, timeout=15).json()["task"]
        logs = td.get("logs") or []
        status = td["status"]
        progress = td["progress"]
        stage = td.get("stage_label", "")
        print(f"[{i}] status={status} progress={progress} stage={stage} logs={len(logs)}")
        if logs:
            print("  last:", logs[-1]["message"][:160])
        if status in ("completed", "failed"):
            print("output_md:", td.get("output_md"))
            print("output_dir:", td.get("output_dir"))
            print("error:", td.get("error"))
            return 0 if status == "completed" else 2
        time.sleep(3)

    print("timeout")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
