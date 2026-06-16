# -*- coding: utf-8 -*-
"""RAG 口语化测试集：前端监控 + 时延 + 多轮 + 闲聊铺垫，逐条标准核查。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTSET = PROJECT_ROOT / "RAG测试文档" / "rag_qa_testset.json"
REPORT_DIR = PROJECT_ROOT / ".run" / "rag_test_reports"
BASE_URL = "http://127.0.0.1:8012/api/v1"
FRONTEND_URL = "http://127.0.0.1:5173"
MAX_LATENCY_SEC = 40


def login() -> str:
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"identifier": "admin", "credential": "admin"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def create_session(token: str) -> int:
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{BASE_URL}/sessions", headers=h, json={}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def chat_stream(token: str, session_id: int, question: str) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    start = time.perf_counter()
    r = requests.post(
        f"{BASE_URL}/chat/stream",
        headers=h,
        json={"session_id": session_id, "question": question},
        stream=True,
        timeout=MAX_LATENCY_SEC + 15,
    )
    event = ""
    parts: list[str] = []
    done: dict = {}
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            if event == "token":
                parts.append(payload.get("content", ""))
            elif event == "done":
                done = payload
    elapsed = round(time.perf_counter() - start, 2)
    content = (done.get("content") or "".join(parts)).strip()
    return {
        "elapsed_sec": elapsed,
        "content": content,
        "ok": r.status_code == 200 and len(content) > 0,
        "latency_ok": elapsed <= MAX_LATENCY_SEC,
    }


def verify_frontend() -> bool:
    try:
        r = requests.get(FRONTEND_URL, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def run_case(token: str, case: dict) -> dict:
    sid = create_session(token)
    turns: list[dict] = []
    all_ok = True
    for role, text in (
        ("warmup", case["warmup"]),
        ("main", case["question"]),
        ("followup", case["followup"]),
    ):
        res = chat_stream(token, sid, text)
        turns.append({"role": role, "question": text, **res})
        if not res["ok"] or not res["latency_ok"]:
            all_ok = False
    return {
        "id": case["id"],
        "session_id": sid,
        "source_hint": case.get("source_hint", ""),
        "pass": all_ok,
        "turns": turns,
        "frontend_url": f"{FRONTEND_URL}/#/chat?session={sid}",
    }


def main() -> int:
    start_from = ""
    if len(sys.argv) >= 2:
        arg = sys.argv[1]
        if arg.startswith("--from="):
            start_from = arg.split("=", 1)[1].strip().upper()
        elif arg == "--from" and len(sys.argv) >= 3:
            start_from = sys.argv[2].strip().upper()
    if not TESTSET.is_file():
        print(f"缺少测试集: {TESTSET}")
        return 1
    if not verify_frontend():
        print(f"FAIL 前端不可达: {FRONTEND_URL}")
        return 1
    data = json.loads(TESTSET.read_text(encoding="utf-8"))
    cases = data["cases"]
    if start_from:
        idx = next((i for i, c in enumerate(cases) if c["id"].upper() == start_from), -1)
        if idx < 0:
            print(f"未找到用例: {start_from}")
            return 1
        cases = cases[idx:]
        print(f"从 {start_from} 续跑，剩余 {len(cases)} 条\n")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    token = login()
    summary: list[dict] = []
    print(f"前端监控: {FRONTEND_URL}  |  API: {BASE_URL}  |  时延上限: {MAX_LATENCY_SEC}s")
    print(f"测试集: {len(cases)} 条\n")
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']} warmup+主问+追问 ...")
        result = run_case(token, case)
        summary.append(result)
        for t in result["turns"]:
            flag = "OK" if t["ok"] and t["latency_ok"] else "FAIL"
            print(f"  {flag} {t['role']:8} {t['elapsed_sec']:5.1f}s  {t['question'][:40]}...")
        print(f"  前端会话: {result['frontend_url']}")
        if not result["pass"]:
            report_path = REPORT_DIR / f"fail_{case['id']}_{datetime.now():%Y%m%d_%H%M%S}.json"
            report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n*** 标准核查未通过: {case['id']}，报告已写入 {report_path}")
            print("请排查后重启服务再测。")
            return 1
        print()
    all_report = REPORT_DIR / f"pass_all_{datetime.now():%Y%m%d_%H%M%S}.json"
    all_report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for s in summary if s["pass"])
    print(f"=== 全部通过 {passed}/{len(cases)} ===")
    print(f"汇总报告: {all_report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
