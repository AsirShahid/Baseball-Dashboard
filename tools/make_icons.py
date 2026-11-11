#!/usr/bin/env python3
"""Render the home-screen icons in web/static/icons/ from web/static/favicon.svg.

    uv run --python 3.12 --with playwright python tools/make_icons.py

Uses the installed Google Chrome (no Playwright browser download). Outputs:
icon-192.png and icon-512.png (rounded tile, like the favicon), maskable-512.png
(full-bleed, glyph inside the 80% safe zone for Android's masks) and
apple-touch-icon.png (180 px, full-bleed; iOS rounds the corners).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
CHROME = "/usr/bin/google-chrome"
BACKGROUND = "#0a0e15"


def variants(favicon: str) -> dict[str, tuple[int, str]]:
    glyph = re.search(r"<g\b.*</g>", favicon, re.S).group(0)

    def svg(scale: float, rounded: bool) -> str:
        offset = 12 * (1 - scale)
        tile = f'<rect width="24" height="24" rx="{6 if rounded else 0}" fill="{BACKGROUND}"/>'
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="100%" height="100%">{tile}'
                f'<g transform="translate({offset} {offset}) scale({scale})">{glyph}</g></svg>')

    return {
        "icon-192.png": (192, svg(1.0, True)),
        "icon-512.png": (512, svg(1.0, True)),
        "maskable-512.png": (512, svg(0.8, False)),
        "apple-touch-icon.png": (180, svg(0.86, False)),
    }


def render(items: dict[str, tuple[int, str]], out: Path) -> None:
    out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        page = browser.new_page()
        for name, (size, svg) in items.items():
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(f'<html><body style="margin:0;background:transparent">'
                             f'<div style="width:{size}px;height:{size}px">{svg}</div></body></html>')
            page.screenshot(path=str(out / name), omit_background=True)
            print(out / name)
        browser.close()


if __name__ == "__main__":
    render(variants((STATIC / "favicon.svg").read_text()), STATIC / "icons")
    sys.exit(0)
