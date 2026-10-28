"""Render the HTML manuals to PDF (and a screenshot for review) with Chromium.

    python tools/render_docs.py                # docs/MANUAL.pdf, QUICK-INSTALL.pdf, INSTALL.pdf, HISTORY.pdf
    python tools/render_docs.py --shots        # also PNG screenshots for a visual check

The manuals are in English only (bilingual up to 2.13.0). The print
stylesheet hides the navigation.

Needs Playwright with Chromium (a development-machine tool, not part of the
installation package).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MANUALS = ["MANUAL", "QUICK-INSTALL", "INSTALL", "HISTORY"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", action="store_true", help="also write PNG screenshots")
    ap.add_argument("--only", default="", help="render one manual (e.g. MANUAL)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    names = [args.only] if args.only else [m for m in MANUALS if (DOCS / f"{m}.html").exists()]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names:
            src = DOCS / f"{name}.html"
            html = src.read_text(encoding="utf-8")
            for suffix in ("",):
                page = browser.new_page(viewport={"width": 1240, "height": 900})
                # Every manual is a complete HTML document since 2.14.2.
                page.set_content(html, wait_until="load")
                page.emulate_media(media="print")
                page.wait_for_timeout(600)
                out = DOCS / f"{name}{suffix}.pdf"
                page.pdf(path=str(out), format="A4", print_background=True,
                         margin={"top": "14mm", "bottom": "14mm", "left": "13mm", "right": "13mm"},
                         display_header_footer=True,
                         header_template="<span></span>",
                         footer_template=(
                             '<div style="font-size:8px;color:#888;width:100%;text-align:center;'
                             'font-family:sans-serif">NER Spatial Coverage Analyzer &middot; '
                             '&copy; 2026 Marcelo Barbosa &middot; '
                             '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'))
                print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
                if args.shots:
                    page.emulate_media(media="screen")
                    shot = DOCS / f"{name}{suffix}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    print(f"wrote {shot}")
                page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
