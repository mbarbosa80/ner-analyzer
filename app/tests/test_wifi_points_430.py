"""4.3.0 — Wi-Fi points instead of access points, and the legend on page 1 only.

Marcelo, 19 Oct 2026, after a reviewer counted the AP markers on a marked-up
PDF and read them as the number of access points requested: "não marque mais
os AP como AP e sim como Wi-Fi somente. Pois não quero mais associar isso com
qtde de AP" — and, from the same reviewer, "keep the legend image on the
first page only, as it covers some of the map lines".

* the placing step draws **one** Wi-Fi point per space whose TEAP states
  wireless, whatever the DWISA quantity; the quantity stays on the TEAP line;
* points are labelled ``WIFI-n``; the start-up pass renames ``AP-n`` and takes
  back the extra points an earlier version placed (one per DWISA unit), never
  a point drawn by hand;
* the marked PDF carries the legend box on the first page of the file only;
  every other page carries the short footnote, which points at page 1.
"""

from __future__ import annotations

import pathlib

import pymupdf
from sqlalchemy import select

from tests.test_wireless_tie_250 import (DWISA, TMP, _analyse, _ap, _line, _match,  # noqa: F401
                                         _ner, _project, _room, _teap, client)
from app import migrate
from app import services as S
from app.db import SessionLocal
from app.domain import reports as RP
from app.domain.coverage import CoverageResult
from app.domain.distance import DistanceRules
from app.models import AuditLog, Element, Project

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _place(client, pid) -> dict:
    r = client.post(f"/api/projects/{pid}/wireless/place-from-teap")
    assert r.status_code == 200, r.text
    return r.json()


def _points(pid, key=None) -> list[Element]:
    with SessionLocal() as db:
        q = select(Element).where(Element.project_id == pid, Element.kind == "WIRELESS")
        if key:
            q = q.where(Element.space_key == key)
        return list(db.execute(q.order_by(Element.id)).scalars())


# ---------------------------------------------------------------------------
# One Wi-Fi point per space
# ---------------------------------------------------------------------------

def test_one_wifi_point_per_space_whatever_the_dwisa_quantity(client):
    pid = _project("wifi-430-one")
    _room(pid, "MED.430", "Media", 100, 100)
    key = _teap(pid, "MED.430", "Media", [_line(DWISA, 7, 7, "DWISA", 1)])
    _ner(pid, "NER_20.1", 100, 130)
    _match(client, pid)
    r = _place(client, pid)
    assert r["placed"] == 1 and r["spaces_placed"] == 1
    pts = _points(pid, key)
    assert [e.label for e in pts] == ["WIFI-1"]
    assert any("not an access point count" in s for s in pts[0].evidence)
    # the DWISA quantity is still the space's wireless ports
    result = _analyse(pid)
    space = next(a for a in result.assignments if a.kind == "space")
    assert space.ports_required == 7


def test_a_point_drawn_by_hand_is_numbered_wifi_too(client):
    pid = _project("wifi-430-hand")
    _room(pid, "OFF.430", "Office", 100, 100)
    _teap(pid, "OFF.430", "Office", [_line("Laptop", 1, 1, "LAP", 1)])
    _match(client, pid)
    made = _ap(client, pid, 100, 105)
    assert made["label"] == "WIFI-1"


# ---------------------------------------------------------------------------
# The start-up pass
# ---------------------------------------------------------------------------

def test_the_start_up_pass_renames_and_keeps_one_point_per_space(client):
    pid = _project("wifi-430-migrate")
    _room(pid, "MED.431", "Media", 100, 100)
    key = _teap(pid, "MED.431", "Media", [_line(DWISA, 3, 3, "DWISA", 1)])
    _ner(pid, "NER_20.1", 100, 130)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        did = p.drawings[0].id
        # what 4.2.3 left: three points placed from the TEAP for one space,
        # and one drawn by hand tied to nothing
        for n in (1, 2, 3):
            db.add(Element(project_id=pid, drawing_id=did, page=1, kind="WIRELESS",
                           label=f"AP-{n}", x=120 + 30 * n, y=115, origin="teap",
                           tie_source="teap", space_key=key, confirmed=True, confidence=1.0))
        db.add(Element(project_id=pid, drawing_id=did, page=1, kind="WIRELESS",
                       label="AP-4", x=600, y=600, origin="manual", tie_source="auto",
                       confirmed=True, confidence=1.0))
        db.commit()
        first_id = min(e.id for e in db.execute(select(Element).where(
            Element.project_id == pid, Element.kind == "WIRELESS")).scalars())
        out = migrate.wifi_points_430(db, db.get(Project, pid))
    assert out == {"wifi_renamed": 4, "wifi_extra_removed": 2}
    pts = _points(pid)
    assert [(e.id == first_id, e.label) for e in pts if e.space_key == key] == [(True, "WIFI-1")]
    assert [e.label for e in pts if not e.space_key] == ["WIFI-4"]
    with SessionLocal() as db:
        audit = db.execute(select(AuditLog).where(
            AuditLog.project_id == pid, AuditLog.action == "wireless.wifi_points")).scalars().one()
        assert len(audit.payload["removed"]) == 2
        # idempotent
        assert migrate.wifi_points_430(db, db.get(Project, pid)) == {
            "wifi_renamed": 0, "wifi_extra_removed": 0}
    # the next placing run finds the space done
    _match(client, pid)
    r = _place(client, pid)
    assert r["placed"] == 0 and r["removed_extra"] == 0


def test_the_pass_never_removes_a_point_drawn_by_hand(client):
    pid = _project("wifi-430-hand-kept")
    _room(pid, "OFF.432", "Office", 100, 100)
    key = _teap(pid, "OFF.432", "Office", [_line(DWISA, 2, 2, "DWISA", 1)])
    with SessionLocal() as db:
        did = db.get(Project, pid).drawings[0].id
        for n, origin in ((1, "manual"), (2, "manual"), (3, "teap")):
            db.add(Element(project_id=pid, drawing_id=did, page=1, kind="WIRELESS",
                           label=f"AP-{n}", x=100 + n, y=100, origin=origin,
                           tie_source="manual" if origin == "manual" else "teap",
                           space_key=key, confirmed=True, confidence=1.0))
        db.commit()
        out = migrate.wifi_points_430(db, db.get(Project, pid))
    assert out["wifi_extra_removed"] == 1                   # only the TEAP one
    assert [e.label for e in _points(pid, key)] == ["WIFI-1", "WIFI-2"]


# ---------------------------------------------------------------------------
# The legend on the first page only
# ---------------------------------------------------------------------------

def _book(path: str, pages: int) -> str:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=1000, height=700)
    doc.save(path)
    doc.close()
    return path


def _export(src: str, out: str, **kw) -> list[str]:
    RP.export_marked_pdf(src, out, coverage=CoverageResult(assignments=[], ner_load={},
                                                           exceptions=[], uncovered=[]),
                         ners=[], scale_for_page={}, rules=DistanceRules(), **kw)
    with pymupdf.open(out) as doc:
        return [pg.get_text() for pg in doc]


def test_the_legend_box_is_on_the_first_page_only():
    texts = _export(_book(f"{TMP}/legend-430.pdf", 3), f"{TMP}/legend-430-out.pdf")
    assert "NER COVERAGE" in texts[0] and "Wi-Fi - space with wireless" in texts[0]
    assert RP.LEGEND_ON_FIRST_PAGE not in texts[0]
    for t in texts[1:]:
        assert "NER COVERAGE —" not in t and "Wi-Fi - space with wireless" not in t
        assert RP.LEGEND_ON_FIRST_PAGE in t
        assert "limits 90 m general" in t, "the limits and the scale stay on every sheet"
        assert "does not replace" in t or "não substitui" in t or "engineering" in t


def test_a_second_book_gets_no_legend_and_legend_off_means_no_pointer():
    texts = _export(_book(f"{TMP}/legend-430b.pdf", 2), f"{TMP}/legend-430b-out.pdf",
                    legend_page=None)
    assert all("Wi-Fi - space with wireless" not in t for t in texts)
    assert all(RP.LEGEND_ON_FIRST_PAGE in t for t in texts)
    off = _export(_book(f"{TMP}/legend-430c.pdf", 2), f"{TMP}/legend-430c-out.pdf",
                  draw_legend=False)
    assert all(RP.LEGEND_ON_FIRST_PAGE not in t and "Wi-Fi - space" not in t for t in off)


def test_the_multi_book_export_puts_the_legend_on_the_first_book_only():
    src = (ROOT / "backend" / "app" / "api" / "routes.py").read_text(encoding="utf-8")
    assert "legend_page=1 if i == 0 else None" in src


# ---------------------------------------------------------------------------
# The words on screen
# ---------------------------------------------------------------------------

def test_the_screens_say_wifi_not_ap():
    viewer = (ROOT / "frontend" / "src" / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    panels = (ROOT / "frontend" / "src" / "pages" / "panels.tsx").read_text(encoding="utf-8")
    notation = (ROOT / "frontend" / "src" / "lib" / "notation.ts").read_text(encoding="utf-8")
    assert '"add-wireless": "+Wi-Fi"' in viewer
    assert '"+AP"' not in viewer
    assert 't("APs")' not in panels and 't("Place APs from the TEAP")' not in panels
    assert "Wireless point — AP" not in notation
    assert S.PLACE_APS_BUSY.startswith("Place Wi-Fi from the TEAP")
