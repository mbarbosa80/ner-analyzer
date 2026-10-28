"""2.14.2 — the documentation pass: the manual audited against the code, one
more one-page installation guide, and the two small things the audit found in
the code itself.

Everything here reads the shipped files, so a future edit that reintroduces a
Portuguese control-kind label, drops the document skeleton or lets a removed
NER's number be handed out again fails on the next run.
"""
from __future__ import annotations

import os
import pathlib
import re
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-2142-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2142.sqlite3")

from tests.test_wireless_tie_250 import client  # noqa: E402,F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

MANUALS = ["MANUAL.html", "INSTALL.html", "QUICK-INSTALL.html", "HISTORY.html"]

# The bilingual labels of the pre-2.13.1 manuals, and any other Portuguese
# word that would betray a leftover.
PORTUGUESE = re.compile(r"seleção|botão|caixa /|texto /|número (do|de)|\b[123]º\b", re.I)


@pytest.mark.parametrize("name", MANUALS)
def test_every_manual_is_a_complete_english_document(name):
    text = (DOCS / name).read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>\n<html lang=\"en\">"), name
    assert "<head>" in text and "</head>" in text and "<body>" in text, name
    assert text.rstrip().endswith("</html>"), name
    assert '<meta charset="utf-8"/>' in text, name
    if name != "HISTORY.html":     # the history quotes Marcelo's own words, in Portuguese
        assert not PORTUGUESE.search(text), f"{name}: Portuguese left over: {PORTUGUESE.search(text).group(0)!r}"


def test_control_kind_labels_are_english_only():
    text = (DOCS / "MANUAL.html").read_text(encoding="utf-8")
    kinds = set(re.findall(r'class="ctrl-kind">([^<]*)<', text))
    assert kinds, "the manual lost its control-kind labels"
    assert kinds <= {"select", "button", "checkbox", "text", "number", "search box", "admin", "file"}, kinds


def test_quick_install_names_the_package_and_the_version():
    text = (DOCS / "QUICK-INSTALL.html").read_text(encoding="utf-8")
    assert f"ner-analyzer-{VERSION}-windows.zip" in text
    assert "setup.bat" in text and "Run as administrator" in text
    assert "127.0.0.1:8000" in text
    # It is the one-page guide: no navigation column, and it sends the reader
    # to the full manual for everything else.
    assert 'id="toc"' not in text
    assert "INSTALL.html" in text


def test_manual_matches_the_teap_card_label():
    """The card's title and the manual's heading name the same three formats —
    the ones the picker and the server accept (`.xls` is refused)."""
    panels = (ROOT / "frontend/src/pages/panels.tsx").read_text(encoding="utf-8")
    manual = (DOCS / "MANUAL.html").read_text(encoding="utf-8")
    assert 't("2 · TEAP (XLSX / XLSM / CSV)")' in panels
    assert "<h3>2 · TEAP (XLSX / XLSM / CSV)</h3>" in manual
    assert "XLSX / XLS / CSV" not in panels and "XLSX / XLS / CSV" not in manual


def test_package_ships_the_quick_guide():
    src = (ROOT / "tools/make_package.py").read_text(encoding="utf-8")
    assert '"docs/QUICK-INSTALL.html"' in src


def test_removed_ner_number_is_not_handed_out_again(client):
    """A NER removed from the register can be restored, so its number stays
    taken: the next sequential name skips it."""
    import datetime as dt

    from sqlalchemy import select

    from app import ner_register as R
    from app.db import SessionLocal
    from app.models import NerAsset, Project

    with SessionLocal() as db:
        p = Project(name="seq-2142", venue_code="SEQ")
        db.add(p)
        db.commit()
        for name in ("NERc01", "NERc02"):
            db.add(NerAsset(project_id=p.id, code=name, display_name=name, kind="NER_CRITICAL",
                            classification="critical", classification_confirmed=True,
                            origin="manual"))
        db.commit()
        assert R.next_sequential_name(R.live_names(db, p.id), True) == "NERc_03.1"
        gone = db.execute(select(NerAsset).where(NerAsset.project_id == p.id,
                                                 NerAsset.display_name == "NERc02")).scalar_one()
        gone.deleted_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        # The removed row still holds NERc02: the next name is NERc03, never NERc02.
        assert R.next_sequential_name(R.live_names(db, p.id), True) == "NERc_03.1"
        pid = p.id
    nxt = client.get(f"/api/projects/{pid}/ner-next-name").json()
    assert nxt["critical"] == "NERc_03.1"
