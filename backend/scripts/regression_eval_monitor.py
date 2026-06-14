#!/usr/bin/env py3
"""EVAL 评测监控回归：装饰器埋点 + /admin/eval/overview API + 对话触发 RAG 链。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

PASS = FAIL = 0
RESULTS: list[str] = []


def ok(name: str, detail: str = ""):
    global PASS
    PASS += 1
    RESULTS.append(f"PASS  {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str):
    global FAIL
    FAIL += 1
    RESULTS.append(f"FAIL  {name} — {detail}")


def run_unit():
    """进程内：装饰器 + eval 聚合。"""
    from app.services.agent_call_logger import (
        AGENT_API_TYPES,
        get_agent_chain,
        set_agent_chain,
        set_agent_trace,
        track_agent_call,
    )
    from app.services.eval_service import build_eval_overview

    if "rag" in AGENT_API_TYPES and "embedding" in AGENT_API_TYPES:
        ok("agent_api_types", ",".join(AGENT_API_TYPES))
    else:
        fail("agent_api_types", str(AGENT_API_TYPES))

    logged: list[dict] = []

    def _capture(**kw):
        logged.append(kw)

    import app.services.agent_call_logger as acl

    orig = acl.log_agent_call
    acl.log_agent_call = lambda **kw: logged.append(kw)  # type: ignore[assignment]
    try:
        set_agent_trace(user_id=999)
        set_agent_chain("regression/eval")

        @track_agent_call(
            api_type="rag",
            target="test:chroma",
            tool_name="rag_search",
            extra_fn=lambda docs, a, k: {"hits": len(docs), "recall": 0.5, "top_k": 5},
        )
        def _fake_search(q: str, k: int = 5):
            return ["doc1", "doc2"]

        _fake_search("退货政策", k=5)
        if len(logged) == 1 and logged[0].get("api_type") == "rag":
            extra = logged[0].get("extra") or {}
            if extra.get("hits") == 2 and extra.get("tool_name") == "rag_search":
                ok("decorator_rag", f"chain={get_agent_chain()}")
            else:
                fail("decorator_rag_extra", str(extra))
        else:
            fail("decorator_rag", f"logged={logged}")

        from app.database import SessionLocal

        db = SessionLocal()
        try:
            overview = build_eval_overview(db, days=7)
            for key in ("summary", "by_type", "daily_trend", "types"):
                if key not in overview:
                    fail("eval_overview_shape", f"missing {key}")
                    break
            else:
                ok("eval_overview_shape", f"types={overview.get('types')}")
            rag = overview.get("by_type", {}).get("rag") or {}
            if "call_count" in rag and "fail_rate" in rag and "recall_rate" in rag:
                ok("eval_rag_metrics", f"calls={rag.get('call_count')}")
            else:
                fail("eval_rag_metrics", str(rag))
        finally:
            db.close()
    finally:
        acl.log_agent_call = orig


def _find_base() -> str | None:
    import httpx

    for b in ("http://127.0.0.1:8012", "http://127.0.0.1:8000"):
        try:
            if httpx.get(f"{b}/health", timeout=5).status_code == 200:
                return b
        except Exception:
            continue
    return None


def _auth_headers(base: str) -> dict | None:
    import httpx

    r = httpx.post(
        f"{base}/api/v1/auth/login",
        json={"identifier": "admin", "credential": "admin"},
        timeout=15,
    )
    if r.status_code != 200:
        fail("login", r.text[:200])
        return None
    ok("login", "admin")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _eval_counts(base: str, headers: dict) -> dict[str, int]:
    import httpx

    r = httpx.get(f"{base}/api/v1/admin/eval/overview?days=7", headers=headers, timeout=15)
    if r.status_code != 200:
        fail("eval_overview_api", f"{r.status_code} {r.text[:200]}")
        return {}
    data = r.json()
    ok("eval_overview_api", f"summary_calls={data.get('summary', {}).get('call_count')}")
    by = data.get("by_type") or {}
    return {t: int((by.get(t) or {}).get("call_count") or 0) for t in data.get("types") or []}


def _stream_chat_rag(base: str, headers: dict) -> bool:
    import httpx

    r = httpx.post(f"{base}/api/v1/sessions", headers=headers, timeout=15)
    if r.status_code != 200:
        fail("chat_session", r.text[:200])
        return False
    sid = r.json().get("id")
    if not sid:
        fail("chat_session", "no id")
        return False
    ok("chat_session", f"id={sid}")

    question = "请问产品的退货政策和保修期限是什么？"
    got_meta = got_done = False
    trace_id = ""
    try:
        with httpx.stream(
            "POST",
            f"{base}/api/v1/chat/stream",
            headers=headers,
            json={"session_id": sid, "question": question},
            timeout=120,
        ) as resp:
            if resp.status_code != 200:
                fail("chat_stream", f"{resp.status_code}")
                return False
            buf = ""
            for chunk in resp.iter_bytes():
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    if "event: meta" in block and "eval_trace_id" in block:
                        got_meta = True
                        for line in block.split("\n"):
                            if line.startswith("data:"):
                                try:
                                    trace_id = json.loads(line[5:].strip()).get("eval_trace_id") or ""
                                except Exception:
                                    pass
                    if "event: done" in block:
                        got_done = True
            if got_meta and trace_id:
                ok("chat_stream_meta", f"trace={trace_id[:8]}...")
            elif got_meta:
                ok("chat_stream_meta", "no trace id")
            else:
                fail("chat_stream_meta", "missing eval_trace_id in SSE meta")
            if got_done:
                ok("chat_stream_done", "ok")
            else:
                fail("chat_stream_done", "no done event")
    except Exception as exc:
        fail("chat_stream", str(exc)[:200])
        return False
    return got_done


def run_api():
    base = _find_base()
    if not base:
        fail("health", "backend not listening on 8012/8000")
        return
    ok("health", base)

    headers = _auth_headers(base)
    if not headers:
        return

    # 运维评测菜单
    import httpx

    r = httpx.get(f"{base}/api/v1/auth/menus", headers=headers, timeout=15)
    if r.status_code == 200:
        payload = r.json()
        roots = payload if isinstance(payload, list) else payload.get("items") or []
        flat = []

        def walk(nodes):
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                flat.append(n)
                walk(n.get("children"))

        walk(roots)
        names = {x.get("name") for x in flat}
        paths = {x.get("path") for x in flat}
        if "运维评测" in names and "/admin/eval" in paths and "/admin/feedback" in paths:
            ok("menus_ops_eval", "运维评测/EVAL/用户反馈")
        else:
            fail("menus_ops_eval", f"names={names} paths={paths}")
    else:
        fail("menus", r.text[:200])

    before = _eval_counts(base, headers)
    if not before:
        return

    rag_before = before.get("rag", 0)
    emb_before = before.get("embedding", 0)
    ok("eval_baseline", f"rag={rag_before} embedding={emb_before}")

    if _stream_chat_rag(base, headers):
        time.sleep(1.5)
        after = _eval_counts(base, headers)
        rag_after = after.get("rag", 0)
        emb_after = after.get("embedding", 0)
        if rag_after > rag_before or emb_after > emb_before:
            ok(
                "eval_after_chat",
                f"rag {rag_before}->{rag_after} embedding {emb_before}->{emb_after}",
            )
        else:
            fail(
                "eval_after_chat",
                f"no increment rag {rag_before}->{rag_after} embedding {emb_before}->{emb_after} "
                "(Chroma/embedding 不可用或未触发 RAG 意图)",
            )


def main():
    print("=== EVAL 评测监控回归 ===\n")
    print("[1/2] 进程内装饰器与聚合\n")
    run_unit()
    print("\n[2/2] 运行中后端 API + 对话链\n")
    run_api()
    print("\n".join(RESULTS))
    print(f"\n合计: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
