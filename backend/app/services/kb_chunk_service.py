"""RAG 知识库文档分块服务 — 对齐 web_rebuild_v2 全量切割策略。

支持：
- Chonkie：semantic / token / sentence / recursive / auto
- 动态语义（dynamic_semantic / dynamic_range）：句边界 + 嵌入相似度谷值
- Markdown 标题结构（md_header）
- 段落切割（paragraph）
- AI 动态语义段（ai_semantic / ai_dynamic）：真实 LLM 划分
- 固定窗口 / 句子边界（fixed_window / sentence_boundary）
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

SliceMode = Literal[
    "auto",
    "semantic",
    "token",
    "sentence",
    "recursive",
    "dynamic_semantic",
    "dynamic_range",
    "md_header",
    "markdown_header",
    "paragraph",
    "ai_semantic",
    "ai_dynamic",
    "fixed_window",
    "sentence_boundary",
    "numbered_header",
]

_CHONKIE_MODES = frozenset({"semantic", "token", "sentence", "recursive", "auto"})

# 对外展示目录（与 web_rebuild slice_method / chunk_mode 对齐）
SLICE_METHOD_CATALOG: List[Dict[str, str]] = [
    {"id": "auto", "label": "自动", "group": "Chonkie", "description": "优先语义切割，不可用时递归降级"},
    {"id": "semantic", "label": "语义切割", "group": "Chonkie", "description": "Chonkie SemanticChunker，按语义主题切分"},
    {"id": "recursive", "label": "递归字符", "group": "Chonkie", "description": "Chonkie RecursiveChunker，按分隔符优先级递归"},
    {"id": "sentence", "label": "句子级", "group": "Chonkie", "description": "Chonkie SentenceChunker"},
    {"id": "token", "label": "Token 级", "group": "Chonkie", "description": "Chonkie TokenChunker"},
    {
        "id": "dynamic_semantic",
        "label": "动态范围语义",
        "group": "嵌入策略",
        "description": "句边界 + 句间嵌入相似度谷值，超长块二次动态切分（BGE）",
    },
    {
        "id": "md_header",
        "label": "MD 标题结构",
        "group": "结构策略",
        "description": "按 Markdown #/##/### 标题层级切分，大块再递归细分",
    },
    {"id": "paragraph", "label": "段落切割", "group": "结构策略", "description": "按空行段落切分，过长段落句边界二次切"},
    {
        "id": "ai_semantic",
        "label": "AI 动态语义段",
        "group": "LLM 策略",
        "description": "调用 LLM 识别文档语义主题并划分段落（真实 API）",
    },
    {"id": "fixed_window", "label": "固定窗口", "group": "基础策略", "description": "固定字符窗口 + overlap"},
    {"id": "sentence_boundary", "label": "句子边界", "group": "基础策略", "description": "在句号/换行等边界切分"},
]

_AGENT_DIR: Optional[Path] = None
for _p in Path(__file__).resolve().parents:
    _candidate = _p / "src" / "agent"
    if _candidate.is_dir() and (_candidate / "text_splitter_strategies.py").is_file():
        _AGENT_DIR = _candidate.resolve()
        break
if _AGENT_DIR and str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))


@dataclass
class ChunkPiece:
    text: str
    index: int
    metadata: Dict[str, Any]


def normalize_slice_mode(mode: str | None) -> str:
    raw = (mode or "auto").strip().lower()
    aliases = {
        "dynamic_range": "dynamic_semantic",
        "markdown_header": "md_header",
        "ai_dynamic": "ai_semantic",
    }
    return aliases.get(raw, raw or "auto")


def list_slice_methods() -> List[Dict[str, str]]:
    return list(SLICE_METHOD_CATALOG)


def _merge_small_chunks(pieces: List[ChunkPiece], min_chars: int) -> List[ChunkPiece]:
    if not pieces or min_chars <= 0:
        return pieces
    merged: List[ChunkPiece] = []
    buf = ""
    buf_meta: Dict[str, Any] = {}
    for p in pieces:
        if not buf:
            buf, buf_meta = p.text, dict(p.metadata)
            continue
        if len(buf) < min_chars:
            buf = f"{buf}\n\n{p.text}".strip()
            buf_meta = {**buf_meta, **p.metadata}
        else:
            merged.append(ChunkPiece(text=buf, index=len(merged), metadata=buf_meta))
            buf, buf_meta = p.text, dict(p.metadata)
    if buf:
        merged.append(ChunkPiece(text=buf, index=len(merged), metadata=buf_meta))
    return merged


def _split_oversized(text: str, max_chars: int, overlap: int, mode: str) -> List[str]:
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(chunk_size=max_chars, chunk_overlap=overlap)
    return [c.strip() for c in splitter.split_text(text) if c.strip()]


def _pieces_from_texts(texts: List[str], mode: str, extra_meta: Optional[Dict[str, Any]] = None) -> List[ChunkPiece]:
    out: List[ChunkPiece] = []
    for i, t in enumerate(texts):
        t = (t or "").strip()
        if not t:
            continue
        out.append(
            ChunkPiece(
                text=t,
                index=i,
                metadata={"mode": mode, **(extra_meta or {})},
            )
        )
    return out


def _split_chonkie(text: str, mode: str, max_tokens: int, overlap: int) -> List[ChunkPiece]:
    from app.services.chonkie_chunker import chunk_text

    ch_mode = mode if mode in _CHONKIE_MODES else "auto"
    rows = chunk_text(text, mode=ch_mode, max_tokens=max_tokens, overlap=overlap)  # type: ignore[arg-type]
    pieces: List[ChunkPiece] = []
    for row in rows:
        txt = str(row.get("text") or "").strip()
        if not txt:
            continue
        meta = dict(row.get("metadata") or {})
        meta["mode"] = ch_mode
        pieces.append(ChunkPiece(text=txt, index=int(row.get("index") or len(pieces)), metadata=meta))
    return pieces


class _STEncodeAdapter:
    """将 LangChain Embedding 适配为 text_splitter_strategies 所需的 encode 接口。"""

    def __init__(self, embedder: Any):
        self._embedder = embedder

    def encode(self, texts: List[str], batch_size: int = 32, show_progress_bar: bool = False, convert_to_numpy: bool = True):
        import numpy as np

        _ = batch_size, show_progress_bar
        vecs = self._embedder.embed_documents(list(texts))
        arr = np.array(vecs, dtype=np.float32)
        return arr if convert_to_numpy else arr.tolist()


def _split_dynamic_semantic(text: str, chunk_size: int, overlap: int, dynamic_max_chars: int) -> List[ChunkPiece]:
    try:
        from text_splitter_strategies import TextSplitterFactory  # type: ignore
    except ImportError as exc:
        logger.warning(
            "[智能客服-知识库|kb_chunk_service|dynamic_semantic|硬编执行|降级] err=%s",
            str(exc)[:120],
        )
        return _split_chonkie(text, "recursive", max(chunk_size // 4, 80), overlap)

    embedder = None
    try:
        from app.llms import get_embedder

        embedder = _STEncodeAdapter(get_embedder())
    except Exception as exc:
        logger.warning(
            "[智能客服-知识库|kb_chunk_service|dynamic_semantic|硬编执行|无嵌入] err=%s",
            str(exc)[:120],
        )

    splitter = TextSplitterFactory.get_strategy(
        "dynamic_semantic",
        embedding_model=embedder,
        chunk_size=chunk_size,
        overlap=overlap,
        min_chunk_size=max(100, chunk_size // 5),
        dynamic_max_chars=dynamic_max_chars,
    )
    tuples = splitter.split(text, chunk_size=chunk_size, overlap=overlap)
    return _pieces_from_texts([t[0] for t in tuples], "dynamic_semantic")


def _split_numbered_header(text: str, chunk_size: int, overlap: int) -> List[ChunkPiece]:
    """????????????"2.1"?"??"?????????????"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # Match numbered headers:
    # - "2.1" / "2.1.1" style (digit.digit...)
    # - "??" / "??" Chinese numbered section (first-level)
    # - "???" / "(?)" style
    header_pattern = re.compile(
        r"^\s*((?:\d+\.)+\d*)\s*(.*)$"          # e.g. "2.1 login" or "2.1.1 sub"
        r"|^\s*([??????????]+)[???](.*)$"  # e.g. "??????"
        r"|^\s*[?(]([??????????]+)[?)](.*)$",   # e.g. "?????"
        re.MULTILINE
    )

    lines = text.split("\n")
    sections: list[tuple[int, str, str]] = []  # (start_line, header, level)
    current_section: list[str] = []
    current_header = ""
    current_level = 0

    for i, line in enumerate(lines):
        m = header_pattern.match(line)
        if m:
            groups = m.groups()
            if groups[0]:  # digit.digit style
                header = line.strip()
                level = len(groups[0].rstrip(".").split("."))
                if len(current_section) > 0:
                    sections.append((i - len(current_section), current_header, "\n".join(current_section)))
                current_section = [line]
                current_header = header
                current_level = level
            elif groups[2]:  # Chinese number "??"
                if len(current_section) > 0:
                    sections.append((i - len(current_section), current_header, "\n".join(current_section)))
                current_section = [line]
                current_header = line.strip()
                current_level = 1
            elif groups[4]:  # "???"
                if len(current_section) > 0:
                    sections.append((i - len(current_section), current_header, "\n".join(current_section)))
                current_section = [line]
                current_header = line.strip()
                current_level = 1
        else:
            current_section.append(line)

    if current_section:
        sections.append((len(lines) - len(current_section), current_header, "\n".join(current_section)))

    if not sections or (len(sections) == 1 and not sections[0][1]):
        # No headers found, fallback to paragraph split
        return _split_paragraph(text, chunk_size, overlap, 80)

    # Filter to keep only sections at the desired level (default: level 2 = secondary sections like "2.1")
    # We prefer level-2 sections if available, otherwise use all sections
    level2_sections = [(s, h, t) for s, h, t in sections if len(h) > 0 and not h[0].isdigit() and h[0] not in "???????????("]
    # Actually, let's just use all identified sections - they are sequentially ordered

    secondary = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    pieces: List[ChunkPiece] = []

    for start_line, header, body in sections:
        body_stripped = body.strip()
        if not body_stripped:
            continue
        meta = {"numbered_header": header, "section_start_line": start_line}

        if len(body_stripped) <= chunk_size:
            pieces.append(ChunkPiece(text=body_stripped, index=len(pieces), metadata={"mode": "numbered_header", **meta}))
        else:
            for part in _split_oversized(body_stripped, chunk_size, overlap, "numbered_header"):
                for sub in secondary.split_text(part) if len(part) > chunk_size else [part]:
                    sub = sub.strip()
                    if sub:
                        pieces.append(ChunkPiece(text=sub, index=len(pieces), metadata={"mode": "numbered_header", **meta}))

    return pieces


def _split_fixed_or_sentence(text: str, strategy: str, chunk_size: int, overlap: int) -> List[ChunkPiece]:
    try:
        from text_splitter_strategies import TextSplitterFactory  # type: ignore

        splitter = TextSplitterFactory.get_strategy(strategy, chunk_size=chunk_size, overlap=overlap)
        tuples = splitter.split(text, chunk_size=chunk_size, overlap=overlap)
        return _pieces_from_texts([t[0] for t in tuples], strategy)
    except ImportError:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        return _pieces_from_texts([c for c in splitter.split_text(text) if c.strip()], strategy)


def _split_md_header(text: str, chunk_size: int, overlap: int) -> List[ChunkPiece]:
    from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

    headers = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers, strip_headers=False)
    try:
        md_docs = md_splitter.split_text(text)
    except Exception:
        md_docs = []

    sections: List[str] = []
    header_meta: List[Dict[str, str]] = []
    for doc in md_docs or []:
        body = str(getattr(doc, "page_content", doc) or "").strip()
        if not body:
            continue
        meta = dict(getattr(doc, "metadata", {}) or {})
        sections.append(body)
        header_meta.append({k: str(v) for k, v in meta.items()})

    if not sections:
        sections = [text]

    secondary = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    pieces: List[ChunkPiece] = []
    for sec, hm in zip(sections, header_meta or [{}] * len(sections)):
        for part in _split_oversized(sec, chunk_size, overlap, "md_header"):
            for sub in secondary.split_text(part) if len(part) > chunk_size else [part]:
                sub = sub.strip()
                if sub:
                    pieces.append(
                        ChunkPiece(
                            text=sub,
                            index=len(pieces),
                            metadata={"mode": "md_header", **hm},
                        )
                    )
    return pieces


def _split_paragraph(text: str, chunk_size: int, overlap: int, min_paragraph_chars: int) -> List[ChunkPiece]:
    raw_parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not raw_parts:
        return []
    merged = _merge_small_chunks(
        _pieces_from_texts(raw_parts, "paragraph"),
        min_paragraph_chars,
    )
    final: List[ChunkPiece] = []
    for p in merged:
        if len(p.text) <= chunk_size:
            final.append(ChunkPiece(text=p.text, index=len(final), metadata={**p.metadata, "mode": "paragraph"}))
        else:
            for sub in _split_oversized(p.text, chunk_size, overlap, "paragraph"):
                final.append(
                    ChunkPiece(text=sub, index=len(final), metadata={**p.metadata, "mode": "paragraph"})
                )
    return final


def _parse_ai_segments(raw: str) -> List[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [text] if text else []

    segments: List[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str) and item.strip():
                segments.append(item.strip())
            elif isinstance(item, dict):
                seg = str(item.get("text") or item.get("content") or "").strip()
                if seg:
                    segments.append(seg)
    elif isinstance(data, dict):
        for key in ("segments", "chunks", "pieces"):
            arr = data.get(key)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, str) and item.strip():
                        segments.append(item.strip())
                    elif isinstance(item, dict):
                        seg = str(item.get("text") or item.get("content") or "").strip()
                        if seg:
                            segments.append(seg)
                break
    return segments


def _split_ai_semantic(text: str, max_segments: int = 24) -> List[ChunkPiece]:
    """真实 LLM 调用划分语义段；失败时降级为 md_header。"""
    raw = (text or "").strip()
    if not raw:
        return []
    preview = raw[:12000]
    system = (
        "你是文档语义分段助手。根据全文主题与逻辑，将文档切分为若干完整语义段。"
        "每段应可独立检索、语义自洽，禁止截断句子。"
        f"输出 JSON 数组，长度不超过 {max_segments}，每项格式 {{\"text\":\"段落全文\"}}。"
        "只输出 JSON，不要 markdown 代码块或解释。"
    )
    user = f"请划分以下文档：\n\n{preview}"
    try:
        from app.llms import get_llm

        llm = get_llm()
        answer = llm.call(f"{system}\n\n{user}", temperature=0.1, max_tokens=4096)
        segments = _parse_ai_segments(answer)
        if segments:
            logger.info(
                "[智能客服-知识库|kb_chunk_service|ai_semantic|Agent执行|完成] segments=%s; llm_powered=true",
                len(segments),
            )
            return _pieces_from_texts(segments, "ai_semantic", {"llm_powered": True})
    except Exception as exc:
        logger.warning(
            "[智能客服-知识库|kb_chunk_service|ai_semantic|Agent执行|降级] error_type=%s; error_message=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
    return _split_md_header(raw, chunk_size=500, overlap=80)


def split_text_to_chunks(
    text: str,
    *,
    mode: str = "auto",
    chunk_size: int = 500,
    overlap: int = 80,
    max_tokens: int = 350,
    dynamic_max_chars: int = 800,
    min_paragraph_chars: int = 80,
    source: str = "",
) -> List[ChunkPiece]:
    """统一分块入口，返回 ChunkPiece 列表。"""
    raw = (text or "").strip()
    if not raw:
        return []

    m = normalize_slice_mode(mode)
    logger.info(
        "[智能客服-知识库|kb_chunk_service|split_text_to_chunks|硬编执行|开始] mode=%s; chars=%s; source=%s",
        m,
        len(raw),
        (source or "")[:80],
    )

    if m in _CHONKIE_MODES:
        pieces = _split_chonkie(raw, m, max_tokens, overlap)
    elif m == "dynamic_semantic":
        pieces = _split_dynamic_semantic(raw, chunk_size, overlap, dynamic_max_chars)
    elif m == "md_header":
        pieces = _split_md_header(raw, chunk_size, overlap)
    elif m == "paragraph":
        pieces = _split_paragraph(raw, chunk_size, overlap, min_paragraph_chars)
    elif m == "ai_semantic":
        pieces = _split_ai_semantic(raw)
    elif m == "numbered_header":
        pieces = _split_numbered_header(raw, chunk_size, overlap)
    elif m in ("fixed_window", "sentence_boundary"):
        pieces = _split_fixed_or_sentence(raw, m, chunk_size, overlap)
    else:
        pieces = _split_chonkie(raw, "auto", max_tokens, overlap)

    for i, p in enumerate(pieces):
        p.index = i
        if source:
            p.metadata["source"] = source
        p.metadata.setdefault("mode", m)
    logger.info(
        "[智能客服-知识库|kb_chunk_service|split_text_to_chunks|硬编执行|完成] mode=%s; chunks=%s",
        m,
        len(pieces),
    )
    return pieces


def chunk_text_with_meta(
    text: str,
    *,
    mode: str = "auto",
    chunk_size: int = 500,
    overlap: int = 80,
    max_tokens: int = 350,
    dynamic_max_chars: int = 800,
    source: str = "",
) -> Dict[str, Any]:
    """与 web_rebuild chonkie_chunker.chunk_text_with_meta 返回结构兼容。"""
    m = normalize_slice_mode(mode)
    pieces = split_text_to_chunks(
        text,
        mode=m,
        chunk_size=chunk_size,
        overlap=overlap,
        max_tokens=max_tokens,
        dynamic_max_chars=dynamic_max_chars,
        source=source,
    )
    chunks = [
        {
            "text": p.text,
            "index": p.index,
            "token_count": max(1, len(p.text) // 2),
            "metadata": p.metadata,
        }
        for p in pieces
    ]
    return {"mode": m, "count": len(chunks), "chunks": chunks}


def split_to_documents(
    text: str,
    document_id: int,
    document_name: str,
    *,
    mode: str = "auto",
    chunk_size: int = 500,
    overlap: int = 80,
    max_tokens: int = 350,
    dynamic_max_chars: int = 800,
):
    from langchain_core.documents import Document

    pieces = split_text_to_chunks(
        text,
        mode=mode,
        chunk_size=chunk_size,
        overlap=overlap,
        max_tokens=max_tokens,
        dynamic_max_chars=dynamic_max_chars,
        source=document_name,
    )
    return [
        Document(
            page_content=p.text,
            metadata={
                "document_id": document_id,
                "document_name": document_name,
                "chunk_index": p.index,
                "slice_mode": p.metadata.get("mode", normalize_slice_mode(mode)),
                **{k: v for k, v in p.metadata.items() if k not in ("mode",)},
            },
        )
        for p in pieces
    ]
