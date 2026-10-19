"""2.8.0 — named areas, TER/COW/DIVA references, fibre runs, the overlay.

Marcelo, 22 Sep 2026:

* *"me permitir desenhar áreas e nomear […] BTOC, TER, etc. […] só para fins
  ilustrativos"* — a **named area** is a ``Zone`` of kind ``area``: drawn on
  the sheet and in the marked-up PDF, named on a tag, deletable, and part
  of no figure;
* *"preciso de *COW, *TER e *DIVA, também para servir só de forma
  ilustrativa"* — a **reference** to those rooms on a key plan, like the NER
  reference of 2.7.0 but without reach circles;
* *"uma coluna RUN fiber to TER, contando 2 para cada NERc e uma para cada
  NER não crítica. Também preciso de um resumão"* — **fibre runs to the
  TER** per room on the NERs sheet, a TOTAL row, and the totals (ports,
  fibre runs, indoor and outdoor APs) at the top of the Summary sheet;
* *"o coverage tbm parece não estar funcionando"* — every assignment now
  carries the **drawing room's id and position**, so the viewer paints the
  verdict on the room the row was measured from instead of guessing it from
  the TEAP key's spelling;
* *"toda vez que eu mexo em uma NER, o PDF vai pra longe"* — the stage takes
  its pan from **its own** drag only.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import openpyxl
import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-280-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t280.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain import reports as R                                # noqa: E402
from app.domain.pdf_ingest import (NER_REFERENCE_KINDS, REFERENCE_KINDS,  # noqa: E402
                                   REFERENCE_OF, VISUAL_ONLY_KINDS, ElementKind)
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, Page, Project,  # noqa: E402
                        TeapFile, TeapSpace, Zone)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"


@pytest.fixture(scope="module")
def client():
    init_db()
    c = TestClient(app)
    from app import auth as A
    with SessionLocal() as db:
        try:
            A.create_user(db, username="tester", password="a-long-test-phrase",
                          display_name="Test User", is_admin=True, actor="tests")
        except A.AuthError:
            pass
    assert c.post("/api/auth/login", json={"username": "tester",
                                           "password": "a-long-test-phrase"}).status_code == 200
    return c


def _pdf(path: str, pages: int = 2) -> str:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=1000, height=700)
    doc.save(path)
    doc.close()
    return path


def _line(product, qty, ports, code="X", row=1):
    return {"row": row, "product": product, "code": code, "qty": qty, "ports": ports,
            "rule": "A", "explanation": ""}


def _project(name) -> int:
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=_pdf(f"{TMP}/{name}.pdf"),
                    sha256="x" * 64, page_count=2)
        db.add(d)
        db.flush()
        for n in (1, 2):
            db.add(Page(drawing_id=d.id, number=n, width=1000, height=700, metres_per_unit=1.0,
                        scale_label="1u=1m", scale_source="manual", scale_confirmed=True,
                        level="LEVEL 01"))
        db.add(TeapFile(project_id=p.id, filename="teap.xlsx", stored_path=f"{TMP}/t.xlsx",
                        sha256="y" * 64))
        db.commit()
        return p.id


def _room(pid, code, name, x, y, page=1) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        r = DrawingSpace(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                         space_code=code, name=name, x=x, y=y, confidence=0.9)
        db.add(r)
        db.commit()
        return r.id


def _teap(pid, code, name, ports, functional_area=None) -> str:
    with SessionLocal() as db:
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        t = TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|{code}",
                      space_code=code, space_name=name, total_ports=ports,
                      functional_area=functional_area,
                      lines=[_line("Laptop", ports, ports, "LAP", 1)])
        db.add(t)
        db.commit()
        return t.space_key


def _ner(pid, label, x, y, *, kind="NER_NONCRITICAL", total_ports=48, page=1) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                    kind=kind, label=label, x=x, y=y, origin="manual",
                    confidence=1.0, confirmed=True, total_ports=total_ports)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        e.ner_asset.total_ports = total_ports
        db.commit()
        return e.ner_asset_id


def _match(client, pid):
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200


def _analyse(pid):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        result, ners = S.analyse(db, p)
        S.save_scenario(db, p, "As-Is", "as_is", result, ners)
        db.commit()
    return result


# ---------------------------------------------------------------------------
# 1. Named areas
# ---------------------------------------------------------------------------

def test_a_named_area_is_created_listed_by_page_renamed_and_deleted(client):
    pid = _project("areas")
    poly = [[100, 100], [300, 100], [300, 250], [100, 250]]
    r = client.post(f"/api/projects/{pid}/zones",
                    json={"page": 1, "kind": "area", "label": "  BTOC ", "polygon": poly})
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["label"] == "BTOC" and made["kind"] == "area" and made["polygon"] == poly

    # A name is what makes it an area; a shape with no name says nothing.
    r = client.post(f"/api/projects/{pid}/zones",
                    json={"page": 1, "kind": "area", "label": "   ", "polygon": poly})
    assert r.status_code == 422
    # Fewer than three corners is not an area.
    r = client.post(f"/api/projects/{pid}/zones",
                    json={"page": 1, "kind": "area", "label": "X", "polygon": poly[:2]})
    assert r.status_code == 422
    # And a kind the app does not know is refused, not stored.
    r = client.post(f"/api/projects/{pid}/zones",
                    json={"page": 1, "kind": "bogus", "label": "X", "polygon": poly})
    assert r.status_code == 422

    other = client.post(f"/api/projects/{pid}/zones",
                        json={"page": 2, "kind": "area", "label": "TER", "polygon": poly}).json()
    assert [z["label"] for z in client.get(f"/api/projects/{pid}/zones?page=1").json()] == ["BTOC"]
    assert [z["label"] for z in client.get(f"/api/projects/{pid}/zones?page=2").json()] == ["TER"]
    assert len(client.get(f"/api/projects/{pid}/zones").json()) == 2

    r = client.patch(f"/api/projects/{pid}/zones/{made['id']}",
                     json={"label": "BTOC compound", "notes": "broadcast"})
    assert r.status_code == 200 and r.json()["label"] == "BTOC compound"
    assert client.patch(f"/api/projects/{pid}/zones/{made['id']}",
                        json={"label": " "}).status_code == 422

    assert client.delete(f"/api/projects/{pid}/zones/{other['id']}").status_code == 204
    assert client.delete(f"/api/projects/{pid}/zones/{other['id']}").status_code == 404
    assert [z["label"] for z in client.get(f"/api/projects/{pid}/zones").json()] == ["BTOC compound"]

    with SessionLocal() as db:
        assert S.areas_to_draw(db, db.get(Project, pid)) == [
            {"id": made["id"], "page": 1, "label": "BTOC compound", "polygon": poly}]
        # The audit log says what was drawn and what was taken back.
        from app.models import AuditLog
        actions = [a.action for a in db.execute(select(AuditLog).where(
            AuditLog.project_id == pid)).scalars()]
        assert "zone.created" in actions and "zone.updated" in actions and "zone.deleted" in actions


def test_the_exporter_draws_the_named_areas_and_the_legend_names_them(client):
    pid = _project("areas-pdf")
    poly = [[100, 100], [300, 100], [300, 250], [100, 250]]
    client.post(f"/api/projects/{pid}/zones",
                json={"page": 1, "kind": "area", "label": "BTOC", "polygon": poly})
    _ner(pid, "NER 1", 500, 400, kind="NER_CRITICAL")
    r = client.post(f"/api/projects/{pid}/reports/pdf?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    doc = pymupdf.open(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    text = doc[0].get_text()
    doc.close()
    assert "BTOC" in text, "the area's name is on the sheet"
    assert "Named area - illustrative only" in text, "and the legend explains the shape"
    assert any(row[2] == "area" and row[1] == R.AREA_COLOUR for row in R.LEGEND_ROWS)


# ---------------------------------------------------------------------------
# 2. TER / COW / DIVA references
# ---------------------------------------------------------------------------

def test_the_reference_kinds_cover_every_room_kind_but_the_idf():
    assert set(REFERENCE_KINDS) == set(NER_REFERENCE_KINDS) | {"TER_REF", "COW_REF", "DIVA_REF"}
    for ref, real in REFERENCE_OF.items():
        assert ref in REFERENCE_KINDS
        assert real in ("NER_CRITICAL", "NER_NONCRITICAL") or real in VISUAL_ONLY_KINDS
        assert R.COLOURS[ref] == R.COLOURS[real], f"{ref} is drawn in {real}'s colour"
    assert not any(k in migrate.ASSET_KINDS for k in REFERENCE_KINDS)


def test_a_ter_reference_is_drawn_dashed_without_circles_and_never_numbered(client):
    pid = _project("ter-ref")
    with SessionLocal() as db:                                   # the real TER on page 1
        p = db.get(Project, pid)
        db.add(Element(project_id=pid, drawing_id=p.drawings[0].id, page=1, kind="TER",
                       label="TER", x=100, y=100, origin="manual", confidence=1.0, confirmed=True))
        db.commit()
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 2, "kind": "TER_REF", "label": "TER", "x": 50, "y": 50})
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["ner_asset_id"] is None, "never a register row"
    for kind in ("COW_REF", "DIVA_REF"):
        assert client.post(f"/api/projects/{pid}/elements",
                           json={"page": 2, "kind": kind, "label": kind[:-4],
                                 "x": 80, "y": 80}).status_code == 201
    # Re-classifying among the reference kinds is allowed; a made-up kind is not.
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"kind": "COW_REF"}).status_code == 200
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"kind": "TER_REF"}).status_code == 200
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"kind": "TER_REFX"}).status_code == 422

    with SessionLocal() as db:
        p = db.get(Project, pid)
        drawn = S.markers_to_draw(db, p)
        kinds = sorted(n.kind for n in drawn)
        assert kinds == ["COW_REF", "DIVA_REF", "TER", "TER_REF"]
        assert not any(n.can_serve for n in drawn)

    # On paper: a dashed ring in the TER's colour, no reach circles. The
    # circle test is by source, the way 2.7.0's was, because a PDF page
    # does not say which circle was meant as what.
    src = (ROOT / "backend" / "app" / "domain" / "reports.py").read_text(encoding="utf-8")
    assert "if not (n.can_serve or n.kind in NER_REFERENCE_KINDS):" in src
    r = client.post(f"/api/projects/{pid}/reports/pdf?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    doc = pymupdf.open(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    assert "TER" in doc[1].get_text()
    doc.close()


def test_the_viewer_offers_the_three_new_references_and_the_area_tool_apart():
    viewer = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    notation = (SRC / "lib" / "notation.ts").read_text(encoding="utf-8")
    for tool, kind in (("add-ter-ref", "TER_REF"), ("add-cow-ref", "COW_REF"),
                       ("add-diva-ref", "DIVA_REF")):
        assert f'"{tool}": "{kind}"' in viewer
    for label in ('"*TER"', '"*COW"', '"*DIVA"', '"+area"'):
        assert label in viewer
    # The illustrative group is styled apart from the +NER tools.
    assert 'ILLUSTRATIVE_TOOLS' in viewer and 'className={`tool-group ${gi === 4 ? "illustrative"' in viewer
    css = (SRC / "styles.css").read_text(encoding="utf-8")
    assert ".toolbox button.illus" in css      # the toolbox down the left since 2.14.0
    # Reach circles: NER references only.
    assert 'export const NER_REFERENCE_KINDS = new Set(["NER_CRITICAL_REF", "NER_NONCRITICAL_REF"]);' in notation
    assert "return canServe(kind) || (!!kind && NER_REFERENCE_KINDS.has(kind));" in notation
    for kind in ("TER_REF", "COW_REF", "DIVA_REF"):
        assert f"  {kind}: " in notation


# ---------------------------------------------------------------------------
# 3. The viewer's two defects: the pan jump and the overlay
# ---------------------------------------------------------------------------

def test_the_stage_takes_its_pan_from_its_own_drag_only():
    """Konva bubbles ``dragend`` from a marker to the stage. The handler took
    the marker's position (PDF units) as the pan, and the sheet left the
    screen every time a NER was moved."""
    viewer = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    assert "if (e.target === e.target.getStage()) setPan(" in viewer
    assert "onDragEnd={(e) => setPan({ x: e.target.x(), y: e.target.y() })}" not in viewer


def test_every_assignment_carries_the_room_it_was_measured_from(client):
    pid = _project("overlay")
    room = _room(pid, "OVR.010", "OVR office", 100, 100)
    _teap(pid, "OVR-010", "OVR office", 8)          # spelled differently from the room
    _ner(pid, "NER 1", 100, 120, kind="NER_CRITICAL")
    _match(client, pid)
    # A match the matcher would not make on its own is tied by hand, which is
    # exactly the case the old key-tail lookup could not paint.
    with SessionLocal() as db:
        from app.models import SpaceMatchRow
        m = db.execute(select(SpaceMatchRow).where(SpaceMatchRow.project_id == pid)).scalars().first()
        t = db.execute(select(TeapSpace).where(TeapSpace.project_id == pid)).scalars().first()
        if m is None:
            m = SpaceMatchRow(project_id=pid, teap_space_id=t.id)
            db.add(m)
        m.drawing_space_id = room
        m.confirmed = True
        m.rejected = False
        db.commit()
    result = _analyse(pid)
    rows = [a.to_dict() for a in result.assignments]
    assert len(rows) == 1
    a = rows[0]
    assert a["drawing_space_id"] == room and a["x"] == 100 and a["y"] == 100
    assert a["status"] == "served"
    # The stored scenario carries it too, so a saved run paints the same.
    body = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    assert body["spaces"][0]["space_key"] == "TST|OVR-010"
    viewer = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    assert "assignmentsBySpaceId[s.id]" in viewer
    assert "coverage.ner_load?.[`A${selected.data.ner_asset_id}`]" in viewer
    # The "Register NERs" button appears only when it has something to toggle.
    assert "{proposed.length > 0 && (" in viewer


def test_an_unplaced_space_has_no_position_to_paint(client):
    pid = _project("overlay-unplaced")
    _teap(pid, "SPT.001", "Sport office", 8)
    _ner(pid, "NER 1", 100, 120)
    result = _analyse(pid)                       # no room on the drawing at all
    a = result.assignments[0].to_dict()
    assert a["unplaced"] is True and a["x"] is None and a["y"] is None
    assert a["drawing_space_id"] is None


# ---------------------------------------------------------------------------
# 4. Fibre runs to the TER and the totals
# ---------------------------------------------------------------------------

def _workbook(client, pid):
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    return openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])


def test_the_fibre_runs_column_counts_two_per_critical_and_one_otherwise(client):
    pid = _project("fibre")
    _room(pid, "OVR.010", "OVR office", 100, 100)
    _room(pid, "MED.010", "Media", 500, 100)
    _room(pid, "FOP.010", "FOP", 100, 400)
    _teap(pid, "OVR.010", "OVR office", 8)
    _teap(pid, "MED.010", "Media", 6)
    _teap(pid, "FOP.010", "FOP", 4)
    _ner(pid, "NERc.03", 100, 120, kind="NER_CRITICAL", total_ports=24)
    _ner(pid, "NER.06", 500, 120, total_ports=24)
    _ner(pid, "NERc.04", 100, 420, kind="NER_CRITICAL", total_ports=24)
    _match(client, pid)
    # Two access points, one of each kind, so the totals have something to count.
    for kind, x in (("WIRELESS", 110), ("WIRELESS", 120)):
        assert client.post(f"/api/projects/{pid}/elements",
                           json={"page": 1, "kind": kind, "label": "", "x": x, "y": 105}).status_code == 201
    _analyse(pid)

    wb = _workbook(client, pid)
    ws = wb["NERs and ports"]
    head = [c.value for c in ws[1]]
    assert head[-2:] == ["Fibre runs to TER", "Notes"]   # 3.0.0: Notes is last
    by_name = {ws.cell(row=r, column=1).value: [c.value for c in ws[r]] for r in range(2, 5)}
    assert by_name["NERc.03"][-2] == 2 and by_name["NERc.04"][-2] == 2
    assert by_name["NER.06"][-2] == 1
    # The TOTAL row: a blank row apart, live SUM formulas, outside the filter.
    assert ws.cell(row=5, column=1).value is None
    assert ws.cell(row=6, column=1).value == "TOTAL"
    assert ws.cell(row=6, column=13).value == "=SUM(M2:M4)"
    assert ws.cell(row=6, column=7).value == "=SUM(G2:G4)"
    assert ws.cell(row=6, column=5).value == "2 critical / 1 non-critical"
    # 4.0.0: the rooms with no indoor / outdoor are said, not left out
    assert ws.cell(row=6, column=6).value == "0 indoor / 0 outdoor / 3 not said"
    assert ws.auto_filter.ref == "A1:N4"

    summary = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value
               for r in range(2, wb["Summary"].max_row + 1)
               for ws in (wb["Summary"],)}
    assert summary["Totals: Fibre runs to the TER (total)"] == 5
    assert summary["  critical NERs x 2"] == 4 and summary["  non-critical NERs x 1"] == 1
    assert summary["Totals: NERs on the drawing"] == 3
    assert summary["Totals: Wi-Fi points drawn (one per space; not an AP count)"] == 2
    assert summary["Totals: NERs indoor"] == 0 and summary["Totals: NERs indoor/outdoor not said"] == 3
    # 4.0.0: the TEAP is the only source of ports — the 2 drawn points add none.
    assert summary["Totals: Total ports requested (TEAP)"] == 18
    assert summary["Fibre runs to the TER per NER"].startswith("2 per critical NER, 1 per non-critical NER")

    # The figures sheet carries the same numbers.
    fig = {(ws.cell(row=r, column=2).value or "").strip(): ws.cell(row=r, column=3).value
           for ws in (wb["Coverage figures"],) for r in range(2, ws.max_row + 1)}
    assert fig["fibre runs to the TER — 2 critical x 2 + 1 non-critical x 1"] == 5

    # The rule is a project setting: 3 per critical room, say.
    r = client.patch(f"/api/projects/{pid}/settings", json={"fibre_runs_critical": 3})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/projects/{pid}").json()["settings"]["fibre_runs_critical"] == 3
    wb = _workbook(client, pid)
    ws = wb["NERs and ports"]
    assert sorted(ws.cell(row=r, column=13).value for r in range(2, 5)) == [1, 3, 3]
    summary = {wb["Summary"].cell(row=r, column=1).value: wb["Summary"].cell(row=r, column=2).value
               for r in range(2, wb["Summary"].max_row + 1)}
    assert summary["Totals: Fibre runs to the TER (total)"] == 7
    assert client.patch(f"/api/projects/{pid}/settings",
                        json={"fibre_runs_critical": 99}).status_code == 422


def test_a_project_that_predates_the_setting_gets_the_default_rule():
    with SessionLocal() as db:
        p = Project(name="fibre-default", venue_code="TST")
        p.fibre_runs_critical = None
        p.fibre_runs_noncritical = None
        assert S.fibre_rule(p) == (2, 1)
        p.fibre_runs_critical = 4
        assert S.fibre_rule(p) == (4, 1)


def test_the_project_rules_card_edits_the_fibre_rule():
    panels = (SRC / "pages" / "panels.tsx").read_text(encoding="utf-8")
    assert "fibre_runs_critical" in panels and "fibre_runs_noncritical" in panels
    assert ("projects", "fibre_runs_critical", "INTEGER DEFAULT 2") in migrate.ADDED_COLUMNS
