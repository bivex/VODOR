"""Capture screenshots of generated Nassi-Shneiderman HTML diagrams."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "structural.nassi.html": "structure_panel.png",
    "full.nassi.html": "full_diagram.png",
    "simple.nassi.html": "simple_diagram.png",
}

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    for html_file, png_name in FILES.items():
        html_path = ROOT / html_file
        if not html_path.exists():
            print(f"SKIP {html_file}: not found", file=sys.stderr)
            continue
        page.goto(f"file://{html_path}")
        page.wait_for_load_state("networkidle")
        # Wait for fonts to load
        page.wait_for_timeout(1000)

        # Full page screenshot
        out_path = OUT / png_name
        page.screenshot(path=str(out_path), full_page=True)
        print(f"OK  {png_name}")

    browser.close()

print("Done.")
