"""验证 SSE think/token 分离（本地测试脚本）。"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8012"
USER = "admin"
PWD = "admin"


def login() -> str:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"identifier": USER, "credential": PWD}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    sid = httpx.post(f"{BASE}/api/v1/sessions", headers=headers, timeout=30).json()["id"]
    body = {"session_id": sid, "question": "保修期多久？", "kb_id": 1}
    events: list[tuple[str, dict]] = []
    with httpx.stream(
        "POST",
        f"{BASE}/api/v1/chat/stream",
        headers={**headers, "Accept": "text/event-stream"},
        json=body,
        timeout=120,
    ) as resp:
        print("status", resp.status_code)
        buf = ""
        for chunk in resp.iter_bytes():
            buf += chunk.decode("utf-8", errors="ignore")
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                if not part.strip() or part.strip().startswith(":"):
                    continue
                ev = "message"
                data_line = ""
                for line in part.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    if line.startswith("data:"):
                        data_line = line[5:].strip()
                if not data_line:
                    continue
                data = json.loads(data_line)
                events.append((ev, data))
                if ev in ("think", "token", "citations", "status"):
                    sample = data.get("content") or data.get("text") or data.get("items")
                    if isinstance(sample, list):
                        sample = f"items={len(sample)}"
                    else:
                        sample = str(sample)[:60] if sample else str(data)[:80]
                    print(f"{ev}: {sample}")
                if ev == "done":
                    break
    think_n = sum(1 for e, _ in events if e == "think")
    token_n = sum(1 for e, _ in events if e == "token")
    cite_n = sum(1 for e, _ in events if e == "citations")
    print(f"summary think={think_n} token={token_n} citations={cite_n}")
    if think_n == 0:
        print("WARN: no think events")
        sys.exit(1)


if __name__ == "__main__":
    main()
