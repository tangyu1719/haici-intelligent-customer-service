# -*- coding: utf-8 -*-
"""多模态 PDF 前端浏览器测试：上传 → 等待完成 → 导出 MD/TXT。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = PROJECT_ROOT / "RAG测试文档" / "库存调整单-提交.pdf"
REPORT_DIR = PROJECT_ROOT / ".run" / "multimodal_test_reports"
OUTPUT_DIR = PROJECT_ROOT / "output" / "multimodal_exports"
FRONTEND = "http://127.0.0.1:5173"
BASE_API = "http://127.0.0.1:8012/api/v1"
MAX_WAIT_SEC = 180


def _login_api(timeout: int = 120) -> str:
    import requests

    r = requests.post(
        f"{BASE_API}/auth/login",
        json={"identifier": "admin", "credential": "admin"},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _poll_task_api(token: str, task_id: str) -> dict:
    import requests

    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE_API}/multimodal-tasks/{task_id}", headers=h, timeout=30)
    r.raise_for_status()
    return r.json()["task"]


def _export_api(token: str, task_id: str, fmt: str) -> str:
    import requests

    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{BASE_API}/multimodal-tasks/{task_id}/export",
        params={"format": fmt},
        headers=h,
        timeout=60,
    )
    r.raise_for_status()
    return r.text


def run_browser_test() -> dict:
    if not PDF_PATH.is_file():
        raise FileNotFoundError(f"测试 PDF 不存在: {PDF_PATH}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("请先安装: pip install playwright && playwright install chromium") from exc

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "started_at": datetime.now().isoformat(),
        "pdf": str(PDF_PATH),
        "frontend": FRONTEND,
        "ok": False,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 登录
        page.goto(f"{FRONTEND}/login", wait_until="networkidle", timeout=60000)
        page.fill('input[type="text"], input[placeholder*="用户"], input:first-of-type', "admin")
        page.fill('input[type="password"]', "admin")
        page.click('button[type="submit"], button:has-text("登录")')
        page.wait_for_url("**/chat**", timeout=30000)

        # 多模态页
        page.goto(f"{FRONTEND}/multimodal", wait_until="networkidle", timeout=60000)
        page.wait_for_selector('text=多模态文档处理', timeout=20000)

        # 上传 PDF
        page.set_input_files('input[type="file"]', str(PDF_PATH.resolve()))
        page.click('button:has-text("提交处理")')
        report["upload_clicked_at"] = datetime.now().isoformat()

        token = _login_api()
        import requests

        h = {"Authorization": f"Bearer {token}"}
        # 等待任务出现在列表且完成/失败
        deadline = time.time() + MAX_WAIT_SEC
        task_id = ""
        final_status = ""
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            tr = requests.get(f"{BASE_API}/multimodal-tasks?limit=10", headers=h, timeout=120)
            tasks = tr.json().get("tasks") or []
            for t in tasks:
                if "库存调整" in (t.get("filename") or ""):
                    task_id = t["task_id"]
                    final_status = t["status"]
                    report["progress"] = t.get("progress")
                    report["stage_label"] = t.get("stage_label")
                    if final_status in ("completed", "failed", "cancelled"):
                        break
            if task_id and final_status in ("completed", "failed", "cancelled"):
                break

        report["task_id"] = task_id
        report["status"] = final_status
        page.screenshot(path=str(REPORT_DIR / "multimodal_pdf_final.png"), full_page=True)

        if final_status != "completed":
            if task_id:
                detail = _poll_task_api(_login_api(), task_id)
                report["error"] = detail.get("error")
                report["logs_tail"] = (detail.get("logs") or [])[-10:]
                report["output_md"] = detail.get("output_md")
                # 标准化成功但后续阶段失败时仍可导出 MD/TXT
                if detail.get("output_md"):
                    token = _login_api()
                    md_text = _export_api(token, task_id, "md")
                    txt_text = _export_api(token, task_id, "txt")
                    md_out = OUTPUT_DIR / "库存调整单-提交.normalized.md"
                    txt_out = OUTPUT_DIR / "库存调整单-提交.normalized.txt"
                    md_out.write_text(md_text, encoding="utf-8")
                    txt_out.write_text(txt_text, encoding="utf-8")
                    report["md_path"] = str(md_out)
                    report["txt_path"] = str(txt_out)
                    report["md_chars"] = len(md_text)
                    report["txt_chars"] = len(txt_text)
                    report["export_ok"] = True
            browser.close()
            report["ok"] = final_status == "completed"
            out = REPORT_DIR / f"{'pass' if report.get('export_ok') else 'fail'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return report

        # 导出 MD + TXT
        token = _login_api()
        md_text = _export_api(token, task_id, "md")
        txt_text = _export_api(token, task_id, "txt")
        md_out = OUTPUT_DIR / "库存调整单-提交.normalized.md"
        txt_out = OUTPUT_DIR / "库存调整单-提交.normalized.txt"
        md_out.write_text(md_text, encoding="utf-8")
        txt_out.write_text(txt_text, encoding="utf-8")
        report["md_path"] = str(md_out)
        report["txt_path"] = str(txt_out)
        report["md_chars"] = len(md_text)
        report["txt_chars"] = len(txt_text)
        report["ok"] = True
        report["finished_at"] = datetime.now().isoformat()

        browser.close()

    out = REPORT_DIR / f"pass_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run_browser_test()
