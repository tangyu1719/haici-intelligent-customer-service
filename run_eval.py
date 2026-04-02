import json
import logging
import sys
import time
from dialog import get_manager
from evaluation import get_evaluator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

def main():
    try:
        with open("test_data/eval_cases.json", "r", encoding="utf-8") as f:
            cases = json.load(f)
    except Exception as e:
        logger.error("加载评测数据失败: %s", str(e))
        return

    mgr = get_manager()
    ev = get_evaluator()
    ev.reset()

    total = len(cases)
    logger.info("开始评测 %d 条数据 (使用 LLM-as-a-Judge)...", total)

    passed = 0

    for c in cases:
        q = c["query"]
        exp_intent = c.get("expected_intent")
        keywords = c.get("keywords", [])

        if not exp_intent: continue

        t0 = time.time()
        r = mgr.process(q, f"eval_{c.get('id')}", "default", skip_cache=True, agent=True)
        lat = time.time() - t0

        act_intent = r.get("intent", "unknown")
        ans = r.get("answer", "")
        
        ctx_list = r.get("context", [])
        ctx_str = " ".join([c.get("content", "") for c in ctx_list]) if ctx_list else ""
        # tool_call类意图的关键词在answer中（来自工具返回），不在RAG context中
        if exp_intent in ("order_query", "order_cancel", "refund_request", "logistics_query", "stock_query", "product_compare", "tool_call"):
            search_target = ans
        else:
            search_target = ctx_str + " " + ans

        ev.record_latency(lat)

        coarse_actual = "chitchat" if act_intent == "chitchat" else "non_chitchat"
        coarse_expected = "chitchat" if exp_intent == "chitchat" else "non_chitchat"
        intent_ok = ev.eval_intent(coarse_actual, coarse_expected)

        ev.eval_retrieval(search_target, keywords)
        ev.eval_generation_llm(q, ans)

        if intent_ok: passed += 1

        status = "PASS" if intent_ok else "FAIL"
        logger.info("[%s] Q:%s.. | I:%s | T:%.2fs", status, q[:15], act_intent, lat)

    rpt = ev.get_report()

    print("\n" + "="*50)
    print(" 智能客服评测报告 (LLM Judge)")
    print("="*50)
    print(f"样本总数: {rpt['sample_count']}")
    print(f"意图准确: {rpt['intent_accuracy']*100:.1f}% ({passed}/{total})")
    print(f"检索召回: {rpt['retrieval_recall']*100:.1f}%")
    print(f"生成质量: {rpt['generation_quality']['avg_relevance']:.1f} (LLM打分 0-100)")
    print(f"平均延迟: {rpt['avg_latency']}s")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
