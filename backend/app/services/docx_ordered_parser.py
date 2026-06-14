"""DOCX 按阅读顺序解析：段落 / 表格 / 内嵌图（SPEC §4.2 P0）。"""
from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

W_P = f"{{{W_NS}}}p"
W_R = f"{{{W_NS}}}r"
W_T = f"{{{W_NS}}}t"
W_TBL = f"{{{W_NS}}}tbl"
W_TR = f"{{{W_NS}}}tr"
W_TC = f"{{{W_NS}}}tc"
A_BLIP = f"{{{A_NS}}}blip"
R_EMBED = f"{{{R_NS}}}embed"
V_NS = "urn:schemas-microsoft-com:vml"
V_IMAGEDATA = f"{{{V_NS}}}imagedata"
SCREEN_MARKER_RE = re.compile(r"※作业画面|如下图|作业画面如下|界面如下", re.I)


@dataclass
class DocxBlock:
    kind: str  # paragraph | table | image
    text: str = ""
    rows: List[List[str]] = field(default_factory=list)
    embed_rid: str = ""
    media_zip_path: str = ""
    image_bytes: bytes = b""


@dataclass
class DocxParseResult:
    ok: bool
    blocks: List[DocxBlock] = field(default_factory=list)
    error: str = ""


def _load_doc_rels(zf: zipfile.ZipFile) -> dict[str, str]:
    rels: dict[str, str] = {}
    try:
        raw = zf.read("word/_rels/document.xml.rels")
        root = ET.fromstring(raw)
        for rel in root:
            rid = rel.get("Id") or ""
            target = rel.get("Target") or ""
            if rid and target:
                rels[rid] = target.replace("\\", "/")
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|docx_ordered_parser|rels|硬编执行|失败] err=%s",
            str(exc)[:200],
        )
    return rels


def _collect_embed_rids(p_elem) -> List[str]:
    """段落内所有图片引用（DrawingML blip + VML imagedata）。"""
    rids: List[str] = []
    seen: set[str] = set()
    for blip in p_elem.iter(A_BLIP):
        rid = blip.get(R_EMBED) or blip.get("embed") or ""
        if rid and rid not in seen:
            seen.add(rid)
            rids.append(rid)
    for imd in p_elem.iter(V_IMAGEDATA):
        rid = imd.get(R_EMBED) or imd.get(f"{{{R_NS}}}id") or imd.get("id") or ""
        if rid and rid not in seen:
            seen.add(rid)
            rids.append(rid)
    return rids


def _paragraph_blocks(p_elem, rels: dict[str, str], zf: zipfile.ZipFile) -> List[DocxBlock]:
    out: List[DocxBlock] = []
    texts: List[str] = []

    for run in p_elem.findall(W_R):
        for t in run.findall(W_T):
            if t.text:
                texts.append(t.text)

    joined = "".join(texts).strip()
    if joined:
        out.append(DocxBlock(kind="paragraph", text=joined))

    for rid in _collect_embed_rids(p_elem):
        target = rels.get(rid, "")
        if not target:
            continue
        zip_path = target if target.startswith("word/") else f"word/{target.lstrip('/')}"
        try:
            data = zf.read(zip_path)
        except KeyError:
            alt = f"word/media/{Path(target).name}"
            try:
                data = zf.read(alt)
                zip_path = alt
            except KeyError:
                logger.warning(
                    "[RAG-文档标准化|docx_ordered_parser|image|硬编执行|缺失] rid=%s; target=%s",
                    rid,
                    target,
                )
                continue
        out.append(
            DocxBlock(
                kind="image",
                embed_rid=rid,
                media_zip_path=zip_path,
                image_bytes=data,
            )
        )
    return out


def _table_block(tbl_elem) -> DocxBlock:
    rows: List[List[str]] = []
    for tr in tbl_elem.findall(W_TR):
        row: List[str] = []
        for tc in tr.findall(W_TC):
            cell = "".join(t.text or "" for t in tc.iter(W_T)).strip()
            row.append(cell)
        if any(c.strip() for c in row):
            rows.append(row)
    return DocxBlock(kind="table", rows=rows)


def _table_to_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    lines = [
        "| " + " | ".join(norm[0]) + " |",
        "| " + " | ".join("---" for _ in norm[0]) + " |",
    ]
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def format_table_markdown(block: DocxBlock) -> str:
    return _table_to_markdown(block.rows)


def extract_all_docx_media(source: Path) -> List[tuple[str, bytes]]:
    """枚举 word/media 下全部内嵌图（用于 orphan 回插）。"""
    out: List[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(source.resolve(), "r") as zf:
            for name in sorted(zf.namelist()):
                if name.startswith("word/media/") and not name.endswith("/"):
                    ext = Path(name).suffix.lower()
                    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf"}:
                        out.append((name, zf.read(name)))
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|docx_ordered_parser|extract_all_docx_media|硬编执行|失败] err=%s",
            str(exc)[:200],
        )
    return out


def parse_docx_ordered(source: Path) -> DocxParseResult:
    """按 document.xml body 子节点顺序解析 DOCX。"""
    source = source.resolve()
    if source.suffix.lower() not in {".docx", ".doc"}:
        return DocxParseResult(ok=False, error="非 DOCX 文件")

    try:
        with zipfile.ZipFile(source, "r") as zf:
            rels = _load_doc_rels(zf)
            doc_xml = zf.read("word/document.xml")
            root = ET.fromstring(doc_xml)
            body = root.find(f"{{{W_NS}}}body")
            if body is None:
                return DocxParseResult(ok=False, error="document.xml 缺少 body")

            blocks: List[DocxBlock] = []
            for child in body:
                tag = child.tag
                if tag == W_P:
                    blocks.extend(_paragraph_blocks(child, rels, zf))
                elif tag == W_TBL:
                    tb = _table_block(child)
                    if tb.rows:
                        blocks.append(tb)

            if not blocks:
                return DocxParseResult(ok=False, error="DOCX 正文为空")

            return DocxParseResult(ok=True, blocks=blocks)
    except zipfile.BadZipFile:
        return DocxParseResult(ok=False, error="DOCX 不是有效 ZIP")
    except Exception as exc:
        logger.warning(
            "[RAG-文档标准化|docx_ordered_parser|parse|硬编执行|失败] err=%s",
            str(exc)[:200],
        )
        return DocxParseResult(ok=False, error=str(exc)[:300])
