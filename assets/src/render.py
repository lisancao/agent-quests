"""Render the README images from assets.html: python assets/src/render.py (needs playwright + chromium)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
OUT = HERE.parent
PANELS = ["banner", "loop", "hud", "toasts", "divider", "footer", "kit"]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    page.goto((HERE / "assets.html").as_uri())
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")
    for name in PANELS:
        page.locator(f"#{name}").screenshot(path=str(OUT / f"{name}.png"), omit_background=name == "divider")
        print("wrote", OUT / f"{name}.png")
    for name, svg in page.evaluate("window.SPRITE_SVG").items():
        (OUT / "sprites").mkdir(exist_ok=True)
        (OUT / "sprites" / f"{name}.svg").write_text(svg)
    browser.close()
