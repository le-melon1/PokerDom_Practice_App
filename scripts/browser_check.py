import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parent.parent / "screenshots"
OUT_DIR.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1000, "height": 900})
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.goto("http://127.0.0.1:8001/", wait_until="networkidle")
    page.wait_for_selector("#seats .seat", timeout=10000)
    page.screenshot(path=str(OUT_DIR / "01_initial.png"))
    print("screenshot 1 taken")

    # if it's hero's turn, click an action button
    time.sleep(1)
    if page.locator("#btn-fold").count() > 0:
        page.click("#btn-fold")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT_DIR / "02_after_fold.png"))
        print("screenshot 2 taken (after fold)")
    else:
        print("not hero's turn or hand already resolved at load")

    print("console errors:", errors)
    browser.close()
