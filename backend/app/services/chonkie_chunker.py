"""Chonkie-based text chunking helpers.

Provides a small integration layer so the backend can use Chonkie's semantic
chunking alongside the existing token/recursive-style document processing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

ChunkMode = Literal["token", "sentence", "recursive", "semantic", "auto"]


@dataclass
class ChunkResult:
    text: str
    index: int
    token_count: int
    metadata: Dict[str, Any]


def _fallback_chunks(text: str, max_chars: int = 800, overlap: int = 80) -> List[ChunkResult]:
    raw = (text or "").strip()
    if not raw:
        return []
    chunks: List[ChunkResult] = []
    start = 0
    idx = 0
    step = max(1, max_chars - overlap)
    while start < len(raw):
        end = min(len(raw), start + max_chars)
        part = raw[start:end].strip()
        if part:
            chunks.append(ChunkResult(text=part, index=idx, token_count=max(1, len(part) // 2), metadata={"mode": "fallback"}))
            idx += 1
        if end >= len(raw):
            break
        start += step
    return chunks


def _normalize_chunks(chunks: Any) -> List[ChunkResult]:
    out: List[ChunkResult] = []
    for i, ch in enumerate(chunks or []):
        txt = getattr(ch, "text", None)
        if txt is None and isinstance(ch, dict):
            txt = ch.get("text") or ch.get("content") or ""
        txt = str(txt or "").strip()
        if not txt:
            continue
        token_count = getattr(ch, "token_count", None)
        if token_count is None and isinstance(ch, dict):
            token_count = ch.get("token_count")
        if token_count is None:
            token_count = max(1, len(txt) // 2)
        meta = getattr(ch, "metadata", None)
        if meta is None and isinstance(ch, dict):
            meta = ch.get("metadata") or {}
        out.append(ChunkResult(text=txt, index=i, token_count=int(token_count), metadata=dict(meta or {})))
    return out


def chunk_text(text: str, *, mode: ChunkMode = "semantic", max_tokens: int = 350, overlap: int = 40) -> List[Dict[str, Any]]:
    """Chunk plain text with Chonkie when available.

    Modes:
      - semantic: SemanticChunker (preferred for multi-topic docs)
      - token: TokenChunker
      - sentence: SentenceChunker
      - recursive: RecursiveChunker
      - auto: semantic if available, else recursive/token fallback
    """
    raw = (text or "").strip()
    if not raw:
        return []

    try:
        import chonkie  # type: ignore
    except Exception:
        return [cr.__dict__ for cr in _fallback_chunks(raw, max_chars=max(300, max_tokens * 4), overlap=max(20, overlap))]

    chunker = None
    mode = mode or "auto"
    try:
        if mode == "semantic" or mode == "auto":
            chunker = getattr(chonkie, "SemanticChunker", None)
            if chunker is not None:
                try:
                    from chonkie import Model2VecEmbeddings  # type: ignore
                    chunker = chunker(embeddings=Model2VecEmbeddings())
                except Exception:
                    chunker = chunker()
        elif mode == "sentence":
            chunker = chonkie.SentenceChunker(max_tokens=max_tokens, overlap=overlap)
        elif mode == "recursive":
            chunker = chonkie.RecursiveChunker(max_tokens=max_tokens, overlap=overlap)
        elif mode == "token":
            chunker = chonkie.TokenChunker(max_tokens=max_tokens, overlap=overlap)
    except Exception:
        chunker = None

    if chunker is None:
        try:
            chunker = chonkie.RecursiveChunker(max_tokens=max_tokens, overlap=overlap)
        except Exception:
            return [cr.__dict__ for cr in _fallback_chunks(raw, max_chars=max(300, max_tokens * 4), overlap=max(20, overlap))]

    try:
        result = chunker(raw)
    except Exception:
        return [cr.__dict__ for cr in _fallback_chunks(raw, max_chars=max(300, max_tokens * 4), overlap=max(20, overlap))]

    return [cr.__dict__ for cr in _normalize_chunks(result)]


def chunk_text_with_meta(
    text: str,
    *,
    mode: ChunkMode = "semantic",
    max_tokens: int = 350,
    overlap: int = 40,
    source: str = "",
) -> Dict[str, Any]:
    chunks = chunk_text(text, mode=mode, max_tokens=max_tokens, overlap=overlap)
    for i, ch in enumerate(chunks):
        ch["index"] = i
        ch["metadata"] = {**(ch.get("metadata") or {}), "source": source, "mode": mode}
    return {
        "mode": mode,
        "count": len(chunks),
        "chunks": chunks,
    }
