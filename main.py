import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import time
import base64
import logging
from dialog import get_manager
from typing import Optional

logger = logging.getLogger(__name__)

app = FastAPI(title="Zhiwei Agent API")

@app.on_event("startup")
async def preload_models():
    import logging
    logger = logging.getLogger(__name__)
    try:
        from llms import get_reranker
        r = get_reranker()
        if r:
            logger.info("BGE Reranker 预加载成功")
        else:
            logger.warning("BGE Reranker 预加载失败")
    except Exception as e:
        logger.warning("BGE Reranker 预加载异常: %s", str(e))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str
    session_id: str = "default_session"
    image: Optional[str] = None

@app.post("/chat/sync")
async def chat_sync(request: ChatRequest):
    start_time = time.time()
    manager = get_manager()

    image_bytes = None
    if request.image:
        try:
            b64_data = request.image.split(",")[-1] if "," in request.image else request.image
            image_bytes = base64.b64decode(b64_data)
        except Exception as e:
            logger.error("图片解码失败: %s", str(e))

    response = manager.process(request.question, request.session_id, image_data=image_bytes)

    latency = round(time.time() - start_time, 2)
    return {
        "answer": response.get("answer", "系统异常，请稍后重试。"),
        "intent": response.get("intent", "unknown") if isinstance(response.get("intent"), str) else getattr(response.get("intent"), "value", "unknown"),
        "latency": latency
    }

@app.post("/rag/query")
async def rag_query_api(request: ChatRequest):
    from rag import rag_query
    result = rag_query(request.question)
    return result

@app.get("/")
async def serve_frontend():
    return FileResponse("frontend/index.html")

@app.post("/eval/run")
async def run_eval():
    import json, time
    from evaluation import get_evaluator

    with open("test_data/eval_cases.json", "r", encoding="utf-8") as f:
        cases = json.load(f)

    manager = get_manager()
    ev = get_evaluator()
    ev.reset()

    for c in cases:
        q = c["query"]
        exp_intent = c.get("expected_intent")
        keywords = c.get("keywords", [])
        if not exp_intent:
            continue

        t0 = time.time()
        r = manager.process(q, f"eval_{c.get('id')}", "default", skip_cache=True, agent=True)
        lat = time.time() - t0

        act_intent = r.get("intent", "unknown")
        ans = r.get("answer", "")
        
        ctx_list = r.get("context", [])
        ctx_str = " ".join([c.get("content", "") for c in ctx_list]) if ctx_list else ""
        if exp_intent in ("order_query", "order_cancel", "refund_request", "logistics_query", "stock_query", "product_compare", "tool_call"):
            search_target = ans
        else:
            search_target = ctx_str + " " + ans

        ev.record_latency(lat)

        def to_triflow(intent):
            if intent == "chitchat":
                return "chitchat"
            elif intent in ("order_query", "order_cancel", "refund_request", "logistics_query", "stock_query", "product_compare", "tool_call"):
                return "tool_call"
            else:
                return "rag"
                
        ev.eval_intent(to_triflow(act_intent), to_triflow(exp_intent))
        ev.eval_retrieval(search_target, keywords)
        ev.eval_generation_llm(q, ans)

    rpt = ev.get_report()
    return {
        "intent_accuracy": round(rpt["intent_accuracy"] * 100, 1),
        "retrieval_recall": round(rpt["retrieval_recall"] * 100, 1),
        "generation_quality": rpt["generation_quality"]["avg_relevance"],
        "avg_latency": rpt["avg_latency"]
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
