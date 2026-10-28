"""What the title-block reader finds on every book under data/uploads.

    .venv\\Scripts\\python.exe tools\\check_title_blocks.py [max pages per book]

Prints, per book and page, the drawing number, the title and the level read
by ``read_title_blocks`` — the function the start-up backfill and the importer
use — so a new book's layout can be checked before anyone relies on it.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.domain.pdf_ingest import read_title_blocks  # noqa: E402


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    root = Path(__file__).resolve().parents[1] / "data" / "uploads"
    for pdf in sorted(root.rglob("*.pdf")):
        t0 = time.perf_counter()
        blocks = read_title_blocks(str(pdf), range(1, limit + 1))
        dt = time.perf_counter() - t0
        print(f"\n== {pdf.relative_to(root)}  ({len(blocks)} pages read in {dt:.1f}s)")
        for page_no, tb in sorted(blocks.items()):
            print(f"   page {page_no:>3}: number={tb.number!r:22} level={tb.level!r:12} "
                  f"title={tb.title!r}")


if __name__ == "__main__":
    main()
