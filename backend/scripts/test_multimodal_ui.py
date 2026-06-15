"""Playwright UI smoke test for MultimodalPanel active/history split."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8012"
SHOT = Path(__file__).resolve().parents[2] / "output" / "multimodal_ui_test.png"


def api_tasks(token: str) -> tuple[list, list]:
    h = {"Authorization": f"Bearer {token}"}
    data = requests.get(f"{API}/api/v1/multimodal-tasks?limit=50", headers=h, timeout=15).json()
    tasks = data.get("tasks") or []
    active = [t for t in tasks if t["status"] in ("pending", "running")]
    history = [t for t in tasks if t["status"] in ("completed", "failed")]
    return active, history


def main() -> int:
    login = requests.post(
        f"{API}/api/v1/auth/login",
        json={"login_type": "password", "identifier": "admin", "credential": "admin"},
        timeout=10,
    )
    if login.status_code != 200:
        print("login failed", login.status_code, login.text)
        return 1
    token = login.json()["access_token"]
    user = login.json()["user"]
    active_api, history_api = api_tasks(token)
    print(f"api active={len(active_api)} history={len(history_api)}")

    SHOT.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill('input[placeholder="手机号 / 邮箱 / 用户名"]', "admin")
        page.fill('input[placeholder="密码"]', "admin")
        page.click('button:has-text("登录")')
        page.wait_for_url("**/chat**", timeout=15000)

        page.goto(f"{BASE}/multimodal", wait_until="networkidle")
        page.wait_for_timeout(2500)

        for text in ("正在执行", "提交处理", "上传文件", "历史记录"):
            if not page.get_by_text(text, exact=False).first.is_visible():
                errors.append(f"missing text: {text}")

        # 历史记录应打开独立大弹窗，不在左栏堆叠
        page.get_by_role("button", name="历史记录").click()
        page.wait_for_timeout(800)
        if not page.get_by_text("多模态处理历史记录", exact=False).first.is_visible():
            errors.append("history modal not opened")
        if page.locator("text=历史记录 (").count() > 0:
            errors.append("history still embedded in sidebar")

        page.screenshot(path=str(SHOT), full_page=True)
        browser.close()

    result = {
        "ok": not errors,
        "errors": errors,
        "api_active": len(active_api),
        "api_history": len(history_api),
        "screenshot": str(SHOT),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
