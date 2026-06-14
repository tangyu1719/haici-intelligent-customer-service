"""Markdown / 文档内图片引用解析与下载（本地路径、/output、HTTP）。"""

from __future__ import annotations



import base64

import logging

import re

import shutil

from pathlib import Path

from typing import Iterable

from urllib.parse import unquote, urlparse



from app.services.haici_output import get_output_dir



logger = logging.getLogger(__name__)



IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

IMG_HTML_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)





def iter_image_refs(text: str) -> list[tuple[str, str, str]]:

    """返回 [(完整匹配, alt, url), ...] 按出现顺序。"""

    seen: set[str] = set()

    out: list[tuple[str, str, str]] = []

    for m in IMG_MD_RE.finditer(text or ""):

        url = (m.group(2) or "").strip()

        if url and url not in seen:

            seen.add(url)

            out.append((m.group(0), m.group(1) or "", url))

    for m in IMG_HTML_RE.finditer(text or ""):

        url = (m.group(1) or "").strip()

        if url and url not in seen:

            seen.add(url)

            out.append((m.group(0), "", url))

    return out





def count_image_refs(text: str) -> int:

    return len(iter_image_refs(text))





def _copy_if_exists(src: Path, dest: Path) -> bool:

    if not src.is_file():

        return False

    dest.parent.mkdir(parents=True, exist_ok=True)

    if src.resolve() != dest.resolve():

        shutil.copy2(src, dest)

    return True





def _resolve_local_ref(url: str, base_dir: Path) -> Path | None:

    raw = unquote((url or "").strip().strip('"').strip("'"))

    if not raw or raw.startswith(("http://", "https://", "data:")):

        return None



    if raw.startswith("/output/"):

        rel = raw[len("/output/") :].lstrip("/")

        candidate = get_output_dir() / rel.replace("/", "\\") if "\\" in rel else get_output_dir() / rel

        if candidate.is_file():

            return candidate.resolve()

        candidate = (get_output_dir() / rel).resolve()

        return candidate if candidate.is_file() else None



    p = Path(raw)

    if p.is_absolute() and p.is_file():

        return p.resolve()



    for cand in [

        (base_dir / raw).resolve(),

        (base_dir / p.name).resolve(),

    ]:

        if cand.is_file():

            return cand

    return None





def _download_http(url: str, dest: Path, *, timeout: float = 30.0) -> bool:

    try:

        import httpx



        dest.parent.mkdir(parents=True, exist_ok=True)

        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:

            resp = client.get(url)

            if resp.status_code >= 400:

                return False

            content = resp.content

            if len(content) < 16:

                return False

            dest.write_bytes(content)

            return True

    except Exception as exc:

        logger.warning(

            "[RAG-文档标准化|md_image_resolver|download|硬编执行|失败] url=%s; err=%s",

            url[:120],

            str(exc)[:200],

        )

        return False





def _save_data_uri(url: str, dest: Path) -> bool:

    if not url.startswith("data:"):

        return False

    try:

        header, b64 = url.split(",", 1)

        if "base64" not in header:

            return False

        data = base64.b64decode(b64)

        dest.parent.mkdir(parents=True, exist_ok=True)

        dest.write_bytes(data)

        return len(data) > 0

    except Exception:

        return False





def _guess_ext(url: str, dest_hint: Path | None = None) -> str:

    if dest_hint and dest_hint.suffix:

        return dest_hint.suffix.lower()

    path = urlparse(url).path

    ext = Path(unquote(path)).suffix.lower()

    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:

        return ext

    return ".png"





def materialize_image_ref(

    url: str,

    dest: Path,

    *,

    base_dir: Path,

) -> bool:

    """将 Markdown 图片引用落到 dest；成功返回 True。"""

    u = (url or "").strip()

    if not u:

        return False



    if u.startswith("data:"):

        return _save_data_uri(u, dest)



    local = _resolve_local_ref(u, base_dir)

    if local is not None:

        ext = local.suffix.lower() or _guess_ext(u, dest)

        target = dest if dest.suffix else dest.with_suffix(ext)

        return _copy_if_exists(local, target)



    if u.startswith(("http://", "https://")):

        target = dest if dest.suffix else dest.with_suffix(_guess_ext(u))

        return _download_http(u, target)



    return False





def materialize_all_refs(

    refs: Iterable[tuple[str, str, str]],

    images_dir: Path,

    *,

    base_dir: Path,

    limit: int,

) -> list[tuple[str, str, Path]]:

    """按顺序下载/复制，返回 [(原始url, alt, 本地路径), ...]。"""

    out: list[tuple[str, str, Path]] = []

    for i, (_full, alt, url) in enumerate(refs, start=1):

        if i > limit:

            break

        ext = _guess_ext(url)

        dest = images_dir / f"img_{i:04d}{ext}"

        if materialize_image_ref(url, dest, base_dir=base_dir):

            out.append((url, alt, dest))

        else:

            logger.warning(

                "[RAG-文档标准化|md_image_resolver|materialize|硬编执行|跳过] url=%s",

                url[:120],

            )

    return out

