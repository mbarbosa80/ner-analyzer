"""2.17.0 — the book is read in a child interpreter, and the memory comes back.

What is checked: the child returns exactly what the in-process call returns;
progress reaches the parent's callback; an exception in the child arrives
as :class:`IsolatedError` with the child's type name; a callback that raises
(cancellation) kills the child; the in-process switch still works; and the
two service call sites go through ``isolate.run``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from app import isolate                              # noqa: E402
from app.domain.pdf_ingest import extract_drawing    # noqa: E402
from app.sample_data import build_all                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def samples():
    return build_all(str(Path(TMP) / "samples-isolate"))


def test_child_returns_what_the_function_returns(samples):
    direct = extract_drawing(samples["pdf"], known_names=[])
    seen: list[tuple[float, str]] = []
    via = isolate.run("app.domain.pdf_ingest.extract_drawing", samples["pdf"],
                      progress=lambda f, s: seen.append((f, s)), known_names=[])
    assert via.page_count == direct.page_count
    assert [s.name for s in via.spaces] == [s.name for s in direct.spaces]
    assert [(e.kind, e.page, round(e.x), round(e.y)) for e in via.elements] == \
           [(e.kind, e.page, round(e.x), round(e.y)) for e in direct.elements]
    assert [p.sheet_number for p in via.pages] == [p.sheet_number for p in direct.pages]
    assert seen, "progress frames must reach the parent"
    assert all(0.0 <= f <= 1.0 for f, _ in seen)
    assert any("page" in s for _, s in seen)


def test_an_exception_in_the_child_is_an_isolated_error():
    with pytest.raises(isolate.IsolatedError) as info:
        isolate.run("app.domain.pdf_ingest.extract_drawing", "/no/such/book.pdf")
    assert info.value.kind                      # the child's own exception type
    assert "book.pdf" in str(info.value) or info.value.trace


def test_a_raising_progress_callback_stops_the_child(samples):
    class Stop(Exception):
        pass

    def progress(_f, _s):
        raise Stop()

    before = _child_count()
    with pytest.raises(Stop):
        isolate.run("app.domain.pdf_ingest.extract_drawing", samples["pdf"], progress=progress)
    # Give the OS a moment to reap, then make sure nothing was left behind.
    time.sleep(0.5)
    assert _child_count() <= before


def test_in_process_switch(samples, monkeypatch):
    monkeypatch.setenv("NER_INPROCESS", "1")
    ex = isolate.run("app.domain.pdf_ingest.extract_drawing", samples["pdf"], known_names=[])
    assert ex.page_count >= 1


def test_the_two_heavy_reads_go_through_the_child():
    src = (ROOT / "backend" / "app" / "services.py").read_text(encoding="utf-8")
    assert 'isolate.run("app.domain.pdf_ingest.extract_drawing"' in src
    assert 'isolate.run("app.domain.pdf_ingest.read_drawn_rooms"' in src
    # Nothing calls them directly any more from the service layer.
    assert not re.search(r"^\s*extract\s*=\s*extract_drawing\(", src, re.M)
    assert not re.search(r"^\s*rooms\s*=\s*read_drawn_rooms\(", src, re.M)


def _child_count() -> int:
    """How many ``-c`` interpreters of ours are alive (POSIX only; 0 elsewhere)."""
    if sys.platform == "win32":
        return 0
    try:
        out = subprocess.run(["pgrep", "-f", "import importlib, pickle, struct, sys, traceback"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    return len([ln for ln in out.split() if ln.strip()])
