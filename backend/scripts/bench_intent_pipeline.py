"""意图识别 / Pipeline 耗时基准（本地脚本）。"""
from __future__ import annotations

import json
import time

import httpx

from app.intent import get_recognizer
from app.llms import get_pipeline_llm
from app.services.agent_pipeline import run_agent_pipeline, _llm_preprocess

SAMPLES = [
    "我夸你呢？你没感觉吗",
    "好像和你进行深入交流啊",
    "退货政策是什么？",
    "HaiCi 智能客服能提供哪些能力？",
    "你好",
]


def bench_rule(q: str) -> float:
    t0 = time.perf_counter()
    get_recognizer().recognize(q)
    return (time.perf_counter() - t0) * 1000


def bench_pipeline(q: str) -> tuple[float, str, str]:
    t0 = time.perf_counter()
    r = run_agent_pipeline(q, [])
    ms = (time.perf_counter() - t0) * 1000
    return ms, r.intent, r.pipeline_source


def bench_ollama_preprocess(q: str) -> tuple[float, bool]:
    node = get_pipeline_llm()
    if not node:
        return -1.0, False
    t0 = time.perf_counter()
    data = _llm_preprocess(q, [])
    ms = (time.perf_counter() - t0) * 1000
    return ms, data is not None


def main() -> None:
    node = get_pipeline_llm()
    print("pipeline_llm:", f"{node.name} @ {node.base_url} model={node.model}" if node else "None")
    print("-" * 72)
    for q in SAMPLES:
        rule_ms = bench_rule(q)
        pipe_ms, intent, source = bench_pipeline(q)
        ollama_ms, ok = bench_ollama_preprocess(q) if intent != "chitchat" else (-1.0, False)
        print(f"Q: {q}")
        print(f"  rule_only={rule_ms:.2f}ms  pipeline={pipe_ms:.2f}ms  intent={intent} source={source}")
        if ollama_ms >= 0:
            print(f"  llm_preprocess={ollama_ms:.2f}ms ok={ok}")
        print()

    # SSE 首包 intent 延迟（端到端采样）
    print("=" * 72)
    print("SSE intent 首包延迟（需后端 8012 运行）")
    try:
        login = httpx.post(
            "http://127.0.0.1:8012/api/v1/auth/login",
            json={"identifier": "admin", "credential": "admin"},
            timeout=10,
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        sid = httpx.post("http://127.0.0.1:8012/api/v1/sessions", headers=headers, timeout=10).json()["id"]
        for q in SAMPLES[:2]:
            t0 = time.perf_counter()
            first_intent_ms = None
            with httpx.stream(
                "POST",
                "http://127.0.0.1:8012/api/v1/chat/stream",
                headers={**headers, "Accept": "text/event-stream"},
                json={"session_id": sid, "question": q, "kb_id": 1},
                timeout=120,
            ) as resp:
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
                        if ev == "intent" and first_intent_ms is None:
                            first_intent_ms = (time.perf_counter() - t0) * 1000
                            data = json.loads(data_line)
                            print(f"  [{q[:20]}…] intent_event={first_intent_ms:.0f}ms {data}")
                            break
                    if first_intent_ms is not None:
                        break
                resp.close()
    except Exception as exc:
        print("  SSE bench skipped:", exc)


if __name__ == "__main__":
    main()
