"""上传文件名规范化：修复 Windows/浏览器 multipart 中文名乱码。"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def normalize_upload_filename(raw: str | None) -> str:
    """将上传原始文件名规范为可读的 UTF-8 文本。"""
    name = unicodedata.normalize("NFC", (raw or "").strip())
    if not name:
        return "upload.bin"
    name = Path(name).name
    if not name or name in {".", ".."}:
        return "upload.bin"

    # 已是正常中文/ASCII，直接返回
    if not _looks_mojibake(name):
        return name[:255]

    for fixer in (_fix_latin1_to_gbk, _fix_latin1_to_utf8, _fix_cp1252_to_utf8):
        fixed = fixer(name)
        if fixed and not _looks_mojibake(fixed):
            return fixed[:255]

    return name[:255]


def _looks_mojibake(name: str) -> bool:
    """启发式：含典型 Latin 乱码且无常用中文。"""
    if re.search(r"[\u4e00-\u9fff]", name):
        return False
    return bool(re.search(r"[À-ÿÃÔËÎÖúÊÓÃ»§²á]", name)) or "??" in name


def _fix_latin1_to_gbk(name: str) -> str:
    try:
        return name.encode("latin-1").decode("gbk")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return ""


def _fix_latin1_to_utf8(name: str) -> str:
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return ""


def _fix_cp1252_to_utf8(name: str) -> str:
    try:
        return name.encode("cp1252").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return ""
