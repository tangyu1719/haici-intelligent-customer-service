"""对话附件上下文：将用户上传的图片/文档转为可注入 RAG/LLM 的文本补充。"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.schemas import ChatAttachmentItem
from app.services.haici_output import is_under_output_dir

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
_DOC_EXCERPT_MAX = 2500
_IMAGE_DESC_MAX = 1200


def _safe_path(raw: str) -> Path | None:
    try:
        p = Path(raw).resolve()
    except OSError:
        return None
    if not p.is_file() or not is_under_output_dir(p):
        return None
    return p


def _image_context(path: Path, doc_context: str) -> str:
    from app.services.doc_image_pipeline import process_image

    image_id = f"chat_{uuid.uuid4().hex[:10]}"
    try:
        res = process_image(str(path), image_id=image_id, doc_context=doc_context, source_format="chat")
        desc = (res.vlm_description or res.ocr_text or "").strip()
        if desc:
            return desc[:_IMAGE_DESC_MAX]
        return f"已上传图片 {path.name}（未能提取文字描述）"
    except Exception as exc:
        logger.warning(
            "[智能客服-对话|chat_attachment_context|图片|Agent执行|失败] path=%s; error_type=%s; error_message=%s",
            path.name,
            type(exc).__name__,
            str(exc)[:200],
        )
        return f"已上传图片 {path.name}（解析失败：{type(exc).__name__}）"


def _doc_context(path: Path) -> str:
    from app.services.document import convert_document

    try:
        result = convert_document(str(path))
        text = str(result.get("text") or "").strip()
        if not text:
            return f"已上传文档 {path.name}（未能提取正文）"
        if len(text) > _DOC_EXCERPT_MAX:
            return f"文档 {path.name} 摘要：\n{text[:_DOC_EXCERPT_MAX]}…"
        return f"文档 {path.name} 内容：\n{text}"
    except Exception as exc:
        logger.warning(
            "[智能客服-对话|chat_attachment_context|文档|Agent执行|失败] path=%s; error_type=%s; error_message=%s",
            path.name,
            type(exc).__name__,
            str(exc)[:200],
        )
        return f"已上传文档 {path.name}（解析失败：{type(exc).__name__}）"


def enrich_question_with_attachments(question: str, attachments: list[ChatAttachmentItem] | None) -> tuple[str, list[dict]]:
    """将附件解析结果拼入用户问题，返回 (增强后问题, 可持久化附件元数据)。"""
    if not attachments:
        return question, []

    blocks: list[str] = []
    meta: list[dict] = []
    for att in attachments[:8]:
        p = _safe_path(att.path)
        if not p:
            continue
        meta.append({"type": att.type, "name": att.name, "path": str(p)})
        suf = p.suffix.lower()
        if att.type == "image" or suf in _IMAGE_SUFFIXES:
            blocks.append(f"【附件·图片 {att.name}】\n{_image_context(p, question)}")
        else:
            blocks.append(f"【附件·文件 {att.name}】\n{_doc_context(p)}")

    if not blocks:
        return question, meta

    prefix = "\n\n".join(blocks)
    base = question.strip() or "请根据以上附件回答我的问题。"
    return f"{base}\n\n---\n{prefix}", meta
