"""Capture a screenshot of a running AutoFB dashboard with Playwright."""
from __future__ import annotations

import os
import importlib.util
from pathlib import Path

if importlib.util.find_spec("playwright") is None:
    raise SystemExit(
        "Missing dependency: playwright. Run `python -m pip install -r reqs.txt` and `python -m playwright install chromium`."
    )

from playwright.sync_api import sync_playwright

def main() -> None:
    url = os.environ.get("AUTOFB_DASHBOARD_URL", "http://127.0.0.1:8001")
    output = Path(os.environ.get("AUTOFB_SCREENSHOT_PATH", "output/dashboard.png"))
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=str(output), full_page=True)
        browser.close()

    print(f"Saved dashboard screenshot to {output}")


if __name__ == "__main__":
    main()
