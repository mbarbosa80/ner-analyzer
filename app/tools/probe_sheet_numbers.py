"""Probe: what does the title block of a venue design book actually say?

Run with the project's venv from the repo root:

    .venv\\Scripts\\python.exe tools\\probe_sheet_numbers.py <book.pdf> [pages]

Prints, per page, the text items in the lower-right corner (display
coordinates, rotation applied) and every item anywhere on the page that looks
like a sheet number. Written to find out what to extract before extracting it.
"""
from __future__ import annotations

import re
import sys

import pymupdf

CANDIDATE_RX = re.compile(r"^[A-Z]{1,5}[-_.]?\d{2,4}(?:[-_.][A-Z0-9]{1,5}){0,5}$")


def items(page, page_no):
    rot = page.rotation_matrix
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            rect = pymupdf.Rect(line["bbox"]) * rot
            yield text, rect, spans[0].get("size", 0.0)


def main() -> None:
    path = sys.argv[1]
    wanted = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
    doc = pymupdf.open(path)
    print(f"{path}: {doc.page_count} pages")
    for i in range(doc.page_count):
        page_no = i + 1
        if wanted and page_no not in wanted:
            continue
        page = doc[i]
        w, h = page.rect.width, page.rect.height
        print(f"\n=== page {page_no}  rotation={page.rotation}  size={w:.0f}x{h:.0f}")
        corner, cands = [], []
        for text, rect, size in items(page, page_no):
            cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
            if cx > 0.72 * w and cy > 0.70 * h:
                corner.append((cy, cx, size, text))
            if CANDIDATE_RX.match(text.replace(" ", "")):
                cands.append((size, round(cx / w, 2), round(cy / h, 2), text))
        print("-- lower-right corner (y, x, size, text):")
        for cy, cx, size, text in sorted(corner)[:60]:
            print(f"   y={cy:7.1f} x={cx:7.1f} s={size:5.1f}  {text!r}")
        print("-- sheet-number-looking items anywhere (size, x%, y%, text):")
        for size, rx, ry, text in sorted(cands, reverse=True)[:20]:
            print(f"   s={size:5.1f} x={rx:.2f} y={ry:.2f}  {text!r}")
    doc.close()


if __name__ == "__main__":
    main()
