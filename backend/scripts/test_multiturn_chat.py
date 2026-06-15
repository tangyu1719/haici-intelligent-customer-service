"""多轮闲聊 SSE 链路压测（定位卡在「正在理解...」的原因）。"""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8012/api/v1"


def login(client: httpx.Client) -> str:
    r = client.post(
        f"{BASE}/auth/login",
        json={"login_type": "password", "identifier": "admin", "credential": "admin"},
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or (data.get("data") or {}).get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"login ok but no token: {data}")
    return token


def ensure_session(client: httpx.Client, headers: dict) -> int:
    r = client.post(f"{BASE}/sessions", headers=headers, json={"title": "多轮测试"})
    if r.status_code in (200, 201):
        data = r.json()
        sid = data.get("id") or (data.get("data") or {}).get("id")
        if sid:
            return int(sid)
    r = client.get(f"{BASE}/sessions", headers=headers, params={"page": 1, "size": 5})
    r.raise_for_status()
    payload = r.json()
    items = payload.get("items") or (payload.get("data") or {}).get("items") or []
    if not items:
        raise RuntimeError("no session available")
    return int(items[0]["id"])


def stream_once(client: httpx.Client, headers: dict, session_id: int, question: str) -> list[tuple[str, object, float]]:
    events: list[tuple[str, object, float]] = []
    t0 = time.time()
    with client.stream(
        "POST",
        f"{BASE}/chat/stream",
        headers=headers,
        json={"session_id": session_id, "question": question},
        timeout=180,
    ) as resp:
        print(f"HTTP {resp.status_code} for Q={question!r}")
        if resp.status_code >= 400:
            print(resp.read().decode("utf-8", "replace")[:500])
            return events
        buf = ""
        for chunk in resp.iter_bytes():
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                ev = "message"
                data = None
                for line in part.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        try:
                            data = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            data = line[5:].strip()
                if data is not None:
                    events.append((ev, data, time.time() - t0))
    return events


def main() -> int:
    questions = ["你好", "你好呀", "你怎么了？"]
    with httpx.Client(timeout=30) as client:
        token = login(client)
        headers = {"Authorization": f"Bearer {token}"}
        sid = ensure_session(client, headers)
        print(f"session_id={sid}")

        for q in questions:
            print(f"\n=== {q} ===")
            events = stream_once(client, headers, sid, q)
            for ev, data, dt in events:
                if ev == "token":
                    print(f"  [{dt:5.2f}s] token: {str((data or {}).get('content', ''))[:100]!r}")
                elif ev == "status":
                    print(f"  [{dt:5.2f}s] status: {(data or {}).get('text')}")
                elif ev == "meta":
                    d = data or {}
                    print(f"  [{dt:5.2f}s] meta intent={d.get('intent')} label={d.get('intent_label')}")
                elif ev == "done":
                    d = data or {}
                    print(
                        f"  [{dt:5.2f}s] done content={str(d.get('content', ''))[:120]!r} "
                        f"error={d.get('error')} code={d.get('error_code')}"
                    )
                else:
                    print(f"  [{dt:5.2f}s] {ev}: {str(data)[:120]}")
            if not any(e[0] == "done" for e in events):
                print("  *** 未收到 done，前端会卡在「正在理解...」***")
                return 2
            if not any(e[0] == "token" for e in events):
                print("  *** 未收到 token ***")
                return 3
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
