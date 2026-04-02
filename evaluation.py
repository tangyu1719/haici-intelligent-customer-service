import logging
from typing import Dict, List
from dataclasses import dataclass, field
from datetime import datetime
from llms import get_llm

logger = logging.getLogger(__name__)

@dataclass
class EvalMetrics:
    total: int = 0
    correct: int = 0
    retrieval_scores: List[float] = field(default_factory=list)
    gen_scores: List[float] = field(default_factory=list)
    details: Dict[str, Dict] = field(default_factory=dict)
    latency: List[float] = field(default_factory=list)

class Evaluator:
    def __init__(self):
        self.m = EvalMetrics()
        self.llm = get_llm()

    def eval_intent(self, pred: str, exp: str) -> bool:
        ok = pred == exp
        self.m.total += 1
        if ok: self.m.correct += 1
        
        if exp not in self.m.details:
            self.m.details[exp] = {"total": 0, "correct": 0}
        self.m.details[exp]["total"] += 1
        if ok: self.m.details[exp]["correct"] += 1
        return ok

    def eval_retrieval(self, answer: str, keywords: List[str]) -> float:
        # 保持关键词匹配作为检索的基础指标
        if not keywords:
            self.m.retrieval_scores.append(1.0)
            return 1.0
        hit = sum(1 for k in keywords if k.lower() in answer.lower())
        recall = hit / len(keywords)
        self.m.retrieval_scores.append(recall)
        return recall

    def eval_generation_llm(self, query: str, answer: str, expected_context: str = ""):
        """
        LLM-as-a-Judge: 使用大模型进行评分 (0-100)
        """
        if "无法" in answer or "抱歉" in answer or len(answer) < 5:
            self.m.gen_scores.append(10.0)
            return

        prompt = f"""你是一名公正的评委。请对回答的相关性进行打分。
问题: {query}
系统回答: {answer}
评分标准:
- 0分: 完全不相关或错误。
- 50分: 回答了部分问题，但不完整。
- 80分: 回答准确，但略显啰嗦。
- 100分: 回答完美，准确且简洁。

请仅输出一个0到100之间的数字，不要输出其他内容。"""

        try:
            score_str = self.llm.call(prompt, temperature=0.0, max_tokens=10)
            import re
            match = re.search(r'\d+', score_str)
            score = float(match.group()) if match else 50.0
        except Exception:
            score = 50.0
            
        self.m.gen_scores.append(min(score, 100.0))

    def record_latency(self, lat: float):
        if lat > 0: self.m.latency.append(lat)

    def get_report(self) -> Dict:
        t = max(self.m.total, 1)
        avg_lat = sum(self.m.latency) / len(self.m.latency) if self.m.latency else 0
        avg_gen = sum(self.m.gen_scores) / len(self.m.gen_scores) if self.m.gen_scores else 0
        avg_recall = sum(self.m.retrieval_scores) / len(self.m.retrieval_scores) if self.m.retrieval_scores else 0
        
        return {
            "timestamp": datetime.now().isoformat(),
            "sample_count": self.m.total,
            "intent_accuracy": round(self.m.correct / t, 4),
            "retrieval_recall": round(avg_recall, 4),
            "generation_quality": {"avg_relevance": round(avg_gen, 2)},
            "avg_latency": round(avg_lat, 3),
            "intent_details": self.m.details
        }

    def reset(self):
        self.m = EvalMetrics()

_ev = None
def get_evaluator() -> Evaluator:
    global _ev
    if _ev is None:
        _ev = Evaluator()
    return _ev
