#!/usr/bin/env py3
"""会话持久化回归。"""
from __future__ import annotations

import os
import sys
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


def run_api():
    import httpx

    base = None
    for b in ("http://127.0.0.1:8012", "http://127.0.0.1:8000"):
        try:
            if httpx.get(f"{b}/health", timeout=3).status_code == 200:
                base = b
                break
        except Exception:
            continue
    if not base:
        fail("health", "backend down")
        return
    ok("health", base)

    r = httpx.post(f"{base}/api/v1/auth/login", json={"identifier": "admin", "credential": "admin"}, timeout=10)
    if r.status_code != 200:
        fail("login", r.text[:200])
        return
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    ok("login", "ok")

    r = httpx.post(f"{base}/api/v1/sessions", headers=h, timeout=10)
    if r.status_code != 200:
        fail("create", r.text[:300])
        return
    body = r.json()
    sid = body.get("id")
    cid = body.get("context_id")
    if sid and cid and len(cid) == 36:
        ok("create", f"id={sid} context_id={cid[:8]}...")
    else:
        fail("create", str(body)[:300])
        return

    for field in ("id", "context_id", "title", "created_at", "updated_at", "message_count", "meta"):
        if field not in body:
            fail("create_fields", f"missing {field}")
            break
    else:
        ok("create_fields", "all present")

    r = httpx.patch(f"{base}/api/v1/sessions/{sid}", headers=h, json={"title": "回归测试会话", "note": "自动化"}, timeout=10)
    if r.status_code == 200 and r.json().get("title") == "回归测试会话":
        ok("patch_rename", r.json().get("meta", {}).get("note", ""))
    else:
        fail("patch_rename", f"{r.status_code} {r.text[:200]}")

    r = httpx.get(f"{base}/api/v1/sessions", headers=h, timeout=10)
    if r.status_code == 200 and any(x.get("id") == sid for x in r.json()):
        item = next(x for x in r.json() if x.get("id") == sid)
        if item.get("created_at") and item.get("updated_at"):
            ok("list", f"count={len(r.json())}")
        else:
            fail("list_dates", str(item)[:200])
    else:
        fail("list", r.text[:200])

    r = httpx.get(f"{base}/api/v1/sessions/{sid}", headers=h, timeout=10)
    if r.status_code == 200 and r.json().get("context_id") == cid:
        ok("detail", f"messages={len(r.json().get('messages') or [])}")
    else:
        fail("detail", r.text[:200])

    r = httpx.delete(f"{base}/api/v1/sessions/{sid}", headers=h, timeout=10)
    if r.status_code == 200 and r.json().get("archived"):
        ok("archive", "ok")
    else:
        fail("archive", r.text[:200])


def main():
    print("=== 会话持久化回归 ===\n")
    try:
        from app.auth.bootstrap import _ensure_chat_sessions_columns
        from app.database import engine
        from sqlalchemy import text

        with engine.begin() as conn:
            _ensure_chat_sessions_columns(conn)
            cols = {r[0] for r in conn.execute(text("SHOW COLUMNS FROM chat_sessions")).fetchall()}
        for c in ("context_id", "meta_json", "status"):
            if c in cols:
                ok(f"db_column_{c}", "exists")
            else:
                fail(f"db_column_{c}", "missing")
    except Exception as exc:
        fail("db_migration", str(exc))

    run_api()
    print("\n".join(RESULTS))
    print(f"\n合计: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
