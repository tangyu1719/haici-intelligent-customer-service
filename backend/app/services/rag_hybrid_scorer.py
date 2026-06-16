"""RAG 精筛：向量分 + BM25 混合重排（粗筛大池 → 精筛自适应 Top-K 的前置步骤）。"""

from __future__ import annotations

import math
import re
from collections import Counter

from langchain_core.documents import Document

from app.config import settings

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-z0-9]+", re.IGNORECASE)


def tokenize_for_bm25(text: str) -> list[str]:
    """中英文混合分词（字符级中文 + 英文词）。"""
    return _TOKEN_RE.findall((text or "").lower())


class SimpleBM25:
    """轻量 BM25，无第三方依赖，用于精筛阶段关键词匹配。"""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = [tokenize_for_bm25(c) for c in corpus]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.df: Counter[str] = Counter()
        for doc in self.docs:
            for t in set(doc):
                self.df[t] += 1
        self.n = len(self.docs)

    def score_query(self, query: str) -> list[float]:
        q_tokens = tokenize_for_bm25(query)
        scores: list[float] = []
        for i, doc in enumerate(self.docs):
            s = 0.0
            doc_counter = Counter(doc)
            dl = self.doc_len[i]
            for t in q_tokens:
                if t not in doc_counter:
                    continue
                df = self.df.get(t, 0)
                idf = math.log((self.n - df + 0.5) / (df + 0.5) + 1.0)
                tf = doc_counter[t]
                denom = tf + self.k1 * (1.0 - self.b + self.b * dl / max(self.avgdl, 1.0))
                s += idf * tf * (self.k1 + 1.0) / max(denom, 1e-9)
            scores.append(s)
        return scores


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return scores
    mx = max(scores)
    if mx <= 0:
        return [0.0] * len(scores)
    return [s / mx for s in scores]


def hybrid_rescore(query: str, docs: list[Document]) -> list[Document]:
    """精筛：向量分 + BM25 加权融合，写回 metadata。"""
    if not docs:
        return docs

    vector_weight = max(0.0, min(1.0, 1.0 - settings.RAG_BM25_WEIGHT))
    bm25_weight = settings.RAG_BM25_WEIGHT

    corpus = [d.page_content for d in docs]
    bm25 = SimpleBM25(corpus)
    bm25_raw = bm25.score_query(query)
    bm25_norm = _normalize_scores(bm25_raw)

    rescored: list[Document] = []
    for d, b_score in zip(docs, bm25_norm):
        v_score = float(d.metadata.get("score", d.metadata.get("vector_score", 0)))
        meta = dict(d.metadata)
        meta["vector_score"] = v_score
        meta["bm25_score"] = round(b_score, 4)
        hybrid = vector_weight * v_score + bm25_weight * b_score
        meta["hybrid_score"] = round(hybrid, 4)
        meta["score"] = hybrid  # 下游统一读 score
        rescored.append(Document(page_content=d.page_content, metadata=meta))

    rescored.sort(key=lambda x: float(x.metadata.get("hybrid_score", 0)), reverse=True)
    return rescored
