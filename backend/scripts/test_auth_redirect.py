"""Verify unauthenticated access redirects to login."""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{BASE}/multimodal", wait_until="networkidle")
        page.wait_for_timeout(1500)
        url = page.url
        title = page.locator("h1").first.inner_text() if page.locator("h1").count() else ""
        print("url", url)
        print("title", title)
        browser.close()
        if "/login" not in url:
            print("FAIL: expected redirect to /login")
            return 2
        print("OK: redirected to login")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
