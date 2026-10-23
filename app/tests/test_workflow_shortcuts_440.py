"""4.4.0 — fewer clicks between screens, and a readable Wi-Fi label on paper.

Marcelo, 22 Oct 2026, after a week of using the app on real venues:

* the left menu and the viewer's legend should fold away, to give the drawing
  the room on a small screen;
* the page shown on NERs and on TEAP × drawing should be a button that opens
  the sheet;
* — none — on TEAP × drawing sits at the top of a list of hundreds of rooms:
  a button beside the list should set it in one click;
* Confirm on an exact match is a formality: the time should go on the rows
  that need a look;
* the team found the name beside the Wi-Fi sign small and unreadable on the
  exported PDF.

The matching rule is tested on the matcher itself and the export end to end;
the screen changes are held by source checks, as the rest of this suite does
for the interface.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-440-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t440.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain import reports as R                                # noqa: E402
from app.domain.matching import MatchMethod, match_spaces          # noqa: E402
from app.domain.pdf_ingest import DetectedSpace                    # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, Page, Project,  # noqa: E402
                        TeapFile, TeapSpace)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
DWISA = "Wireless Connection - Shared Internet Access (SIA) Wireless LAN"


def _src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# An exact match needs no Confirm
# ---------------------------------------------------------------------------

def _room(code, name, page=1, x=100.0, y=100.0):
    return DetectedSpace(space_code=code, name=name, page=page, x=x, y=y, confidence=0.9)


def test_an_identical_name_on_a_line_without_a_code_is_confirmed_by_the_matcher():
    rep = match_spaces([("k1", None, "Media Workroom", None, None)],
                       [_room(None, "Media Workroom"), _room(None, "Storage", x=300)])
    m = rep.matches[0]
    assert m.best.method == MatchMethod.EXACT_NAME
    assert m.confirmed, "an identical name is an exact match for a line with no code"


def test_an_exact_code_is_still_confirmed():
    rep = match_spaces([("k1", "SPT.016.01", "Anything", None, None)],
                       [_room("SPT.016.01", "Team Room")])
    assert rep.matches[0].best.method == MatchMethod.EXACT_CODE
    assert rep.matches[0].confirmed


def test_a_name_on_a_line_whose_code_the_drawing_lacks_waits_for_a_person():
    # The code says one room; the drawing does not print it, and a room of the
    # same name may be the one next door.
    rep = match_spaces([("k1", "SPT.099", "Storage", None, None)],
                       [_room(None, "Storage")])
    m = rep.matches[0]
    assert m.best is not None and m.best.method == MatchMethod.EXACT_NAME
    assert not m.confirmed


def test_two_rooms_answering_to_the_same_name_wait_for_a_person():
    rep = match_spaces([("k1", None, "Storage", None, None)],
                       [_room(None, "Storage", page=1), _room(None, "Storage", page=2, x=400)])
    assert not rep.matches[0].confirmed


def test_the_worklist_shows_confirm_only_where_it_is_still_a_question():
    s = _src("pages/panels.tsx")
    i = s.index("export function MatchingPanel")
    body = s[i:i + 20000]
    # A confirmed row with a room shows a tick, not the button.
    assert "{m.confirmed && hasRoom(m) ? (" in body
    # Rows needing a look first, then the settled ones.
    assert "Number(isSettled(a)) - Number(isSettled(b))" in body
    assert "const isSettled" in s


# ---------------------------------------------------------------------------
# — none — in one click
# ---------------------------------------------------------------------------

def test_a_none_button_sits_beside_the_room_list():
    s = _src("pages/panels.tsx")
    i = s.index("export function MatchingPanel")
    body = s[i:i + 20000]
    btn = body[body.index('className="small none-btn"') - 60:][:700]
    assert "onClick={() => choose(m, null)}" in btn
    assert 'disabled={m.locked === "rejected"}' in btn


# ---------------------------------------------------------------------------
# The page is the way to the sheet
# ---------------------------------------------------------------------------

def test_page_buttons_open_the_viewer_on_that_sheet_and_point():
    s = _src("pages/panels.tsx")
    assert "export function openViewerAt(ctx: Ctx, page: number" in s
    assert "HANDOFF.viewerAt = { page, x, y };" in s
    assert 'ctx.go("viewer")' in s[s.index("export function openViewerAt"):][:300]
    # TEAP × drawing: the page cell is a PageButton centred on the tied room.
    i = s.index("export function MatchingPanel")
    assert "<PageButton ctx={ctx} page={m.page} x={ds?.x} y={ds?.y} />" in s[i:i + 20000]
    # NERs: the page pill, each "also on" sheet and each marker's page.
    n = _src("pages/NerRegister.tsx")
    assert "<PageButton ctx={ctx} page={r.canonical.page} x={r.canonical.x} y={r.canonical.y} pill />" in n
    assert "<PageButton ctx={ctx} page={x} x={o?.x} y={o?.y} />" in n
    assert "<PageButton ctx={ctx} page={o.page} x={o.x} y={o.y} />" in n


def test_the_viewer_opens_on_the_sheet_it_was_sent_to_and_rings_the_point():
    v = _src("pages/Viewer.tsx")
    assert "const sent = HANDOFF.viewerAt?.page;" in v
    assert "useEffect(() => { HANDOFF.viewerAt = null; }, []);" in v
    assert "setFocus({ page: at.page, x: at.x, y: at.y });" in v


# ---------------------------------------------------------------------------
# The menu and the legend fold away
# ---------------------------------------------------------------------------

def test_the_menu_folds_to_a_rail_and_is_remembered():
    a = _src("App.tsx")
    assert 'localStorage.getItem("ner.sidebar")' in a
    assert 'className="sidebar rail"' in a
    css = _src("styles.css")
    assert re.search(r"\.sidebar\.rail\s*\{[^}]*width:\s*46px", css)


def test_the_legend_folds_to_a_tab_and_is_remembered():
    v = _src("pages/Viewer.tsx")
    assert 'localStorage.getItem("ner.legend")' in v
    assert 'className="legend-reopen"' in v
    assert ".legend-reopen" in _src("styles.css")


# ---------------------------------------------------------------------------
# A Wi-Fi name that can be read on paper
# ---------------------------------------------------------------------------

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


def _pdf(path: str) -> str:
    doc = pymupdf.open()
    doc.new_page(width=1000, height=700)
    doc.save(path)
    doc.close()
    return path


def _line(product, qty, ports, code="X", row=1):
    return {"row": row, "product": product, "code": code, "qty": qty, "ports": ports,
            "rule": "A", "explanation": ""}


def test_the_wifi_label_constants_match_the_ners():
    assert R.WIFI_LABEL_SIZE >= R.MARKER_LABEL_SIZE >= 9.0
    assert R.WIFI_SIGN_SIZE > 14.0


def test_the_exported_wifi_name_is_bold_at_the_ner_size(client):
    with SessionLocal() as db:
        p = Project(name="wifi-label-440", venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=_pdf(f"{TMP}/w440.pdf"),
                    sha256="x" * 64, page_count=1)
        db.add(d)
        db.flush()
        db.add(Page(drawing_id=d.id, number=1, width=1000, height=700, metres_per_unit=1.0,
                    scale_label="1u=1m", scale_source="manual", scale_confirmed=True,
                    level="LEVEL 01"))
        tf = TeapFile(project_id=p.id, filename="teap.xlsx", stored_path=f"{TMP}/t.xlsx",
                      sha256="y" * 64)
        db.add(tf)
        db.flush()
        db.add(DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="OFF.010",
                            name="Office", x=100, y=100, confidence=0.9))
        db.add(TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key="TST|OFF.010",
                         space_code="OFF.010", space_name="Office", total_ports=5,
                         lines=[_line("Laptop", 4, 4, "LAP", 1), _line(DWISA, 1, 1, "DWISA", 2)],
                         wireless_required=True))
        db.add(Element(project_id=p.id, drawing_id=d.id, page=1, kind="NER_NONCRITICAL",
                       label="NER 1", x=100, y=160, origin="manual", confidence=1.0,
                       confirmed=True, total_ports=48))
        db.commit()
        pid = p.id
        migrate.backfill_assets(db, db.get(Project, pid))
        db.commit()
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": "WIRELESS", "label": "", "x": 300, "y": 300})
    assert r.status_code == 201, r.text
    label = r.json()["label"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        result, ners = S.analyse(db, p)
        S.save_scenario(db, p, "As-Is", "as_is", result, ners)
        db.commit()
    r = client.post(f"/api/projects/{pid}/reports/pdf?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    doc = pymupdf.open(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    spans = [s for b in doc[0].get_text("dict")["blocks"] for ln in b.get("lines", [])
             for s in ln["spans"] if s["text"].strip() == label]
    doc.close()
    assert spans, f"{label} is on the sheet"
    assert all(s["size"] >= 9.0 for s in spans), [s["size"] for s in spans]
    assert all("Bold" in s["font"] for s in spans), [s["font"] for s in spans]
