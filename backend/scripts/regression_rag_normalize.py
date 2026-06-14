#!/usr/bin/env py3
"""RAG 文档标准化回归（不依赖 pytest tmp_path）。"""
from __future__ import annotations

import json
import os
import sys
import traceback
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

os.environ.setdefault("KB_NORMALIZE_ENABLED", "true")
os.environ.setdefault("VLM_IMAGE_ENABLED", "false")
os.environ.setdefault("BAIDU_OCR_ENABLED", "false")
os.environ.setdefault("MAX_IMAGES_PER_DOC", "30")

WORK = ROOT / "output" / "_regtest_rag"
WORK.mkdir(parents=True, exist_ok=True)

PASS = 0
FAIL = 0
RESULTS: list[str] = []


def ok(name: str, detail: str = ""):
    global PASS
    PASS += 1
    RESULTS.append(f"PASS  {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str):
    global FAIL
    FAIL += 1
    RESULTS.append(f"FAIL  {name} — {detail}")


def make_md() -> Path:
    p = WORK / "sample.md"
    p.write_text("# FAQ\n\n退货七天内可退。\n", encoding="utf-8")
    return p


def make_docx_with_png() -> Path:
    p = WORK / "with_img.docx"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>售后说明</w:t></w:r></w:p></w:body>
</w:document>"""
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr("word/media/image1.png", png)
    return p


def make_xlsx_with_png() -> Path:
    p = WORK / "sheet.xlsx"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("xl/media/image1.png", png)
    return p


def run_unit_tests():
    from app.services.doc_inspector import inspect_document
    from app.services.doc_normalizer import normalize_document
    from app.services.kb_chunk_service import split_to_documents, list_slice_methods
    from app.services import haici_output as ho

    md = make_md()
    docx = make_docx_with_png()
    xlsx = make_xlsx_with_png()

    r = inspect_document(md)
    if r["file_type"] == "md" and r["estimated_image_count"] == 0:
        ok("inspect_md", str(r))
    else:
        fail("inspect_md", str(r))

    r = inspect_document(docx)
    if r["estimated_image_count"] >= 1 and r["requires_normalization"]:
        ok("inspect_docx", f"images={r['estimated_image_count']}")
    else:
        fail("inspect_docx", str(r))

    r = inspect_document(xlsx)
    if r["estimated_image_count"] >= 1:
        ok("inspect_xlsx", f"images={r['estimated_image_count']}")
    else:
        fail("inspect_xlsx", str(r))

    n = normalize_document(md, tenant_id=1, doc_id=9001)
    if n.ok and Path(n.normalized_md_path).is_file():
        ok("normalize_md", f"len={len(n.text)}")
    else:
        fail("normalize_md", n.error or "no file")

    n = normalize_document(docx, tenant_id=1, doc_id=9002)
    manifest = json.loads(Path(n.manifest_path).read_text(encoding="utf-8")) if n.manifest_path else {}
    imgs = list(Path(n.assets_dir, "images").glob("img_*")) if n.assets_dir else []
    if n.ok and manifest.get("image_count", 0) >= 1 and imgs and "<!-- IMG:" in n.text:
        ok("normalize_docx", f"images={manifest.get('image_count')} url_in_text={'/output/' in n.text}")
    else:
        fail("normalize_docx", f"ok={n.ok} imgs={len(imgs)} err={n.error}")

    n = normalize_document(xlsx, tenant_id=1, doc_id=9003)
    manifest = json.loads(Path(n.manifest_path).read_text(encoding="utf-8")) if n.manifest_path else {}
    if n.ok and manifest.get("image_count", 0) >= 1:
        ok("normalize_xlsx", f"images={manifest.get('image_count')}")
    else:
        fail("normalize_xlsx", n.error or str(manifest))

    docs = split_to_documents(n.text or "x", 9003, "sheet.xlsx", mode="md_header")
    if docs and docs[0].metadata.get("document_id") == 9003:
        ok("chunk_split", f"chunks={len(docs)}")
    else:
        fail("chunk_split", "empty or bad metadata")

    if len(list_slice_methods()) >= 10:
        ok("slice_methods", f"count={len(list_slice_methods())}")
    else:
        fail("slice_methods", "too few")

    p = ho.kb_assets_dir(1, 9999) / "images" / "img_0001.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    url = ho.abs_path_to_public_url(p)
    if url.startswith("/output/kb_assets/") and url.endswith("img_0001.png"):
        ok("public_url", url)
    else:
        fail("public_url", url)

    faq = ROOT / "RAG测试文档" / "产品FAQ.md"
    if faq.is_file():
        n = normalize_document(faq, tenant_id=1, doc_id=9004)
        if n.ok:
            ok("normalize_real_faq", f"len={len(n.text)}")
        else:
            fail("normalize_real_faq", n.error)


def run_api_tests():
    try:
        import httpx
    except ImportError:
        fail("api_httpx", "httpx not installed")
        return

    bases = ["http://127.0.0.1:8000", "http://127.0.0.1:8012"]
    base = None
    for b in bases:
        try:
            r = httpx.get(f"{b}/health", timeout=3.0)
            if r.status_code == 200:
                base = b
                break
        except Exception:
            continue
    if not base:
        fail("api_health", "backend not running on 8000/8012")
        return
    ok("api_health", base)

    token = None
    for cred in [
        {"identifier": "admin", "credential": "admin"},
        {"identifier": "admin@example.com", "credential": "admin123"},
    ]:
        try:
            r = httpx.post(f"{base}/api/v1/auth/login", json=cred, timeout=10.0)
            if r.status_code == 200 and r.json().get("access_token"):
                token = r.json()["access_token"]
                break
        except Exception:
            continue
    if not token:
        fail("api_login", "cannot login admin")
        return
    ok("api_login", "token ok")
    h = {"Authorization": f"Bearer {token}"}

    r = httpx.get(f"{base}/api/v1/knowledge/config", headers=h, timeout=10.0)
    if r.status_code == 200 and r.json().get("max_images_per_doc") == 30:
        ok("api_kb_config", str(r.json()))
    else:
        fail("api_kb_config", f"{r.status_code} {r.text[:200]}")

    r = httpx.get(f"{base}/api/v1/knowledge/slice-methods", headers=h, timeout=10.0)
    if r.status_code == 200 and len(r.json().get("methods") or []) >= 5:
        ok("api_slice_methods", f"n={len(r.json()['methods'])}")
    else:
        fail("api_slice_methods", r.text[:200])

    md = make_md()
    with md.open("rb") as f:
        r = httpx.post(
            f"{base}/api/v1/knowledge/upload",
            headers=h,
            files={"file": ("regtest_faq.md", f, "text/markdown")},
            data={"slice_method": "md_header"},
            timeout=120.0,
        )
    if r.status_code == 200:
        body = r.json()
        if body.get("status") in ("ready", "processing") and body.get("file_type"):
            ok("api_upload_md", f"status={body.get('status')} chunks={body.get('chunk_count')} type={body.get('file_type')}")
            doc_id = body.get("id")
            if doc_id:
                r2 = httpx.get(f"{base}/api/v1/knowledge/{doc_id}/manifest", headers=h, timeout=10.0)
                if r2.status_code == 200:
                    ok("api_manifest", "manifest ok")
                elif r2.status_code == 404:
                    ok("api_manifest", "404 expected for md without assets")
                else:
                    fail("api_manifest", f"{r2.status_code}")
        else:
            fail("api_upload_md", str(body)[:300])
    else:
        fail("api_upload_md", f"{r.status_code} {r.text[:300]}")

    docx = make_docx_with_png()
    with docx.open("rb") as f:
        r = httpx.post(
            f"{base}/api/v1/knowledge/upload",
            headers=h,
            files={"file": ("regtest_docx.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"slice_method": "auto"},
            timeout=300.0,
        )
    if r.status_code == 200:
        body = r.json()
        if body.get("status") == "ready" and (body.get("image_count") or 0) >= 1:
            ok("api_upload_docx", f"images={body.get('image_count')} chunks={body.get('chunk_count')}")
            doc_id = body.get("id")
            if doc_id:
                r2 = httpx.get(f"{base}/api/v1/knowledge/{doc_id}/manifest", headers=h, timeout=10.0)
                manifest = (r2.json().get("manifest") or {}) if r2.status_code == 200 else {}
                imgs = manifest.get("images") or []
                if imgs and imgs[0].get("public_url"):
                    ok("api_manifest_docx", f"images={len(imgs)}")
                    url = imgs[0]["public_url"]
                    full = url if url.startswith("http") else f"{base}{url}"
                    ir = httpx.get(full, timeout=10.0)
                    if ir.status_code == 200 and len(ir.content) > 0:
                        ok("api_image_url", f"status=200 bytes={len(ir.content)}")
                    else:
                        fail("api_image_url", f"status={ir.status_code}")
                else:
                    fail("api_manifest_docx", f"status={r2.status_code} no images")
        elif body.get("status") == "failed":
            fail("api_upload_docx", body.get("error_message") or "failed")
        else:
            fail("api_upload_docx", str(body)[:400])
    else:
        fail("api_upload_docx", f"{r.status_code} {r.text[:300]}")


def main():
    print("=== RAG 文档标准化回归 ===")
    print(f"WORK={WORK}\n")
    try:
        run_unit_tests()
    except Exception as exc:
        fail("unit_tests_exception", f"{exc}\n{traceback.format_exc()}")
    try:
        run_api_tests()
    except Exception as exc:
        fail("api_tests_exception", f"{exc}\n{traceback.format_exc()}")

    print("\n".join(RESULTS))
    print(f"\n合计: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
