"""语义缓存层 (SPEC §3) — 相似问题命中缓存直接返回，不调LLM。

实现:
1. 完全匹配(TTL去重): 相同问题hash → 5分钟内返回缓存
2. 语义匹配: Embedding相似度 > 0.92 → 返回缓存
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    question: str
    answer: str
    citations: list[dict] = field(default_factory=list)
    model: str = ""
    created_at: float = 0.0
    ttl_seconds: int = 300  # 默认5分钟
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class GatewayCache:
    """网关级缓存，支持精确匹配和语义匹配。

    精确缓存: 内存 LRU (默认1000条)
    语义缓存: 通过 ChromaDB 向量相似度
    """

    def __init__(self, max_exact_entries: int = 1000, default_ttl: int = 300):
        self._exact: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_exact = max_exact_entries
        self._default_ttl = default_ttl
        self._stats = {"hits": 0, "misses": 0, "semantic_hits": 0}

    def _question_hash(self, question: str) -> str:
        return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]

    def exact_lookup(self, question: str) -> CacheEntry | None:
        """精确匹配查询"""
        h = self._question_hash(question)
        entry = self._exact.get(h)
        if entry and not entry.expired:
            entry.hit_count += 1
            self._stats["hits"] += 1
            # LRU: move to end
            self._exact.move_to_end(h)
            logger.info(f"[缓存-精确命中] hash={h}; hits={entry.hit_count}; age={entry.age_seconds:.0f}s")
            return entry
        if entry and entry.expired:
            del self._exact[h]
        self._stats["misses"] += 1
        return None

    def semantic_lookup(self, question: str) -> CacheEntry | None:
        """语义匹配查询（通过ChromaDB向量相似度）"""
        try:
            from app.vectorstore import search as vec_search

            docs = vec_search(question, k=1, tenant_id="cache")
            if not docs:
                return None
            score = float(docs[0].metadata.get("score", 0))
            if score >= 0.92:
                meta = docs[0].metadata
                entry = CacheEntry(
                    question=meta.get("question", question),
                    answer=docs[0].page_content,
                    citations=meta.get("citations", []),
                    model=meta.get("model", ""),
                    created_at=meta.get("cached_at", time.time()),
                    ttl_seconds=self._default_ttl,
                )
                self._stats["semantic_hits"] += 1
                logger.info(f"[缓存-语义命中] score={score:.4f}")
                return entry
        except Exception as exc:
            logger.warning(f"[缓存-语义查询失败] {exc}")
        return None

    def store(self, question: str, answer: str, citations: list[dict] | None = None, model: str = "") -> None:
        """存入缓存"""
        h = self._question_hash(question)
        entry = CacheEntry(
            question=question, answer=answer,
            citations=citations or [], model=model,
            created_at=time.time(), ttl_seconds=self._default_ttl,
        )
        # LRU 淘汰
        while len(self._exact) >= self._max_exact:
            self._exact.popitem(last=False)
        self._exact[h] = entry
        logger.info(f"[缓存-存储] hash={h}; entries={len(self._exact)}")

        # 同时存入语义缓存
        try:
            from app.vectorstore import get_collection
            col = get_collection("cache")
            col.add(
                ids=[h],
                documents=[answer],
                metadatas=[{
                    "question": question, "model": model,
                    "citations": str(citations or []),
                    "cached_at": time.time(),
                }],
            )
        except Exception as exc:
            logger.warning(f"[缓存-语义存储失败] {exc}")

    def stats(self) -> dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        return {
            "exact_hits": self._stats["hits"],
            "semantic_hits": self._stats["semantic_hits"],
            "misses": self._stats["misses"],
            "hit_rate": round(self._stats["hits"] / max(total, 1), 4),
            "entries": len(self._exact),
            "max_entries": self._max_exact,
        }

    def invalidate(self, question: str | None = None) -> int:
        """清除缓存"""
        if question:
            h = self._question_hash(question)
            if h in self._exact:
                del self._exact[h]
                return 1
            return 0
        count = len(self._exact)
        self._exact.clear()
        return count


# 全局单例
cache = GatewayCache()
