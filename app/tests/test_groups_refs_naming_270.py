"""2.7.0 — the four piles, the unplaced rule, the NER references, the names.

Marcelo, 22 Sep 2026, on Demand per space: *"eu não consigo ver na prática
por que dividir o status do espaço em not analysable, match not confirmed,
not analysed. […] os que não foram cruzados caem todos no mesmo grupo […]
todo espaço que precisa de serviço de rede no TEAP vai ter que encontrar um
lugar no desenho ou […] eu tenho que amarrar com uma NER existente ou
criada."*

So:

* every engine status maps to one of four **groups** — served, out of limit /
  over capacity, served but not measured, pending — and the screen and the
  workbook show the group with the precise status as the reason;
* a TEAP space with **no room on the drawing** reaches the engine: pending
  until a person chooses its NER, and then counted on that NER with no
  distance invented (``assigned_not_placed``);
* the workbook gets a **Coverage figures** sheet — how much of the TEAP was
  found on the drawing, tied by hand, served, pending — as counts and shares;
* a **NER reference** (``NER_*_REF``) can be drawn on a key plan: named after
  a NER, ringed with the reach circles, and counted nowhere;
* a **suggested name** per NER from the venue's naming convention, adopted
  one row at a time.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import openpyxl
import pytest

TMP = tempfile.mkdtemp(prefix="ner-270-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t270.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain.distance import (GROUP_OF, GROUP_LABEL, STATUS_LABEL,  # noqa: E402
                                 Group, Status, group_of)
from app.domain.pdf_ingest import REFERENCE_KINDS                  # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, NerAsset, Page,  # noqa: E402
                        Project, SpaceMatchRow, TeapFile, TeapSpace)

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


def _line(product, qty, ports, code="X", row=1):
    return {"row": row, "product": product, "code": code, "qty": qty, "ports": ports,
            "rule": "A", "explanation": ""}


def _project(name) -> int:
    """Two sheets at 1 unit = 1 m: page 1 the plan, page 2 a key plan."""
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
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
    """Returns the register (asset) id."""
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


def _assign(client, pid, key, asset_id, why="venue knowledge"):
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                    json={"ner_asset_id": asset_id, "justification": why})
    assert r.status_code == 200, r.text
    return r.json()


def _rows(client, pid) -> dict:
    body = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    return {r["space_key"]: r for r in body["spaces"]}, body


# ---------------------------------------------------------------------------
# 1. The four piles
# ---------------------------------------------------------------------------

def test_every_status_belongs_to_exactly_one_group():
    """A status the table forgets would fall into "pending" by default and
    read as unresolved when it is not."""
    for st in Status:
        assert st in GROUP_OF, f"{st.value} has no group"
        assert st in STATUS_LABEL, f"{st.value} has no words"
    assert group_of(None) is Group.PENDING
    assert group_of("something-unknown") is Group.PENDING
    assert group_of("served") is Group.SERVED and group_of("near_limit") is Group.SERVED
    assert group_of("assigned_not_placed") is Group.NOT_MEASURED
    assert group_of("match_not_confirmed") is Group.PENDING


def test_the_screen_mirrors_the_engine_groups():
    """notation.ts carries the same table as distance.py — one drift and the
    tile counts and the pills disagree."""
    src = (SRC / "lib" / "notation.ts").read_text(encoding="utf-8")
    block = src[src.index("export const GROUP_OF"):src.index("export const GROUP_LABEL")]
    pairs = dict(re.findall(r"\n\s+(\w+):\s*\"(\w+)\"", block))
    assert pairs == {st.value: g.value for st, g in GROUP_OF.items()}
    labels = src[src.index("export const GROUP_LABEL"):src.index("export const GROUP_COLOUR")]
    for g in Group:
        assert f'{g.value}: "{GROUP_LABEL[g]}"' in labels, f"label of {g.value} drifted"


# ---------------------------------------------------------------------------
# 2. A TEAP space with no room on the drawing
# ---------------------------------------------------------------------------

def test_an_unplaced_space_is_pending_on_the_list_and_counted_on_no_room(client):
    pid = _project("unplaced-pending")
    _room(pid, "OFF.001", "Office", 100, 100)
    _teap(pid, "OFF.001", "Office", 4)
    ghost = _teap(pid, "GHO.001", "Not on any sheet", 6)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    result = _analyse(pid)

    keys = {a.space_key: a for a in result.assignments}
    assert ghost in keys, "the space with no room reached the engine"
    g = keys[ghost]
    assert g.status is Status.NOT_ANALYSABLE and g.unplaced and g.ner_key is None
    assert any("no room on the drawing" in r for r in g.reasons)
    assert g.to_dict()["page"] is None, "no page 0 on a screen"
    assert ghost in result.uncovered
    assert not any(e["space_key"] == ghost for e in result.exceptions), \
        "already listed as 'TEAP locations with no space' — not a third copy"
    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 4, "the ghost's 6 ports are on no room"
    summary = result.summary()
    assert summary["spaces"] == 2 and summary["unplaced"] == 1 and summary["unplaced_assigned"] == 0
    assert summary["by_group"] == {"served": 1, "pending": 1}

    rows, body = _rows(client, pid)
    assert rows[ghost]["group"] == "pending"
    assert rows[ghost]["group_reason"] == "no room on the drawing"
    assert rows["TST|OFF.001"]["group"] == "served"
    assert body["by_group"] == {"served": 1, "pending": 1}
    assert body["group_labels"]["pending"] == GROUP_LABEL[Group.PENDING]


def test_a_ner_chosen_for_an_unplaced_space_is_counted_and_not_measured(client):
    """His words: *"mesmo que eu não ache um lugar no desenho eu tenho que
    amarrar com uma NER existente ou criada."* The ports land on the room,
    no distance is invented, and the exception list carries the reminder."""
    pid = _project("unplaced-assigned")
    _room(pid, "OFF.002", "Office", 100, 100)
    _teap(pid, "OFF.002", "Office", 4)
    ghost = _teap(pid, "GHO.002", "Not on any sheet", 6)
    ner_a = _ner(pid, "NER A", 100, 120, total_ports=48)
    _match(client, pid)

    r = _assign(client, pid, ghost, ner_a)
    assert r["unplaced"] is True and r["cross_level"] is False
    assert "no room on the drawing" in r["note"]

    rows, body = _rows(client, pid)
    assert rows[ghost]["group"] == "not_measured", "the row moves before the next run"
    assert rows[ghost]["group_reason"] == STATUS_LABEL[Status.ASSIGNED_NOT_PLACED]

    result = _analyse(pid)
    g = next(a for a in result.assignments if a.space_key == ghost)
    assert g.status is Status.ASSIGNED_NOT_PLACED and g.ner_label == "NER A" and g.pinned
    assert g.evaluation.effective_distance_m is None
    assert g.evaluation.requires_human_validation
    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 10 and ghost in load["NER A"]["spaces"]
    assert ghost not in result.uncovered
    ex = next(e for e in result.exceptions if e["space_key"] == ghost)
    assert ex["status"] == "assigned_not_placed" and "distance not measured" in ex["detail"]
    assert result.summary()["by_group"] == {"served": 1, "not_measured": 1}
    assert result.summary()["unplaced_assigned"] == 1

    rows, _ = _rows(client, pid)
    assert rows[ghost]["status"] == "assigned_not_placed"
    assert rows[ghost]["serving_ner"] == "NER A" and rows[ghost]["distance_m"] is None


def test_an_unplaced_space_still_overloads_a_full_room(client):
    """Counted means counted: a room with 5 free ports given 6 is over capacity."""
    pid = _project("unplaced-capacity")
    _room(pid, "OFF.003", "Office", 100, 100)
    _teap(pid, "OFF.003", "Office", 4)
    ghost = _teap(pid, "GHO.003", "Not on any sheet", 6)
    ner_a = _ner(pid, "NER A", 100, 120, total_ports=9)
    _match(client, pid)
    _assign(client, pid, ghost, ner_a)
    result = _analyse(pid)
    # The office (4) is served first (ordering is by ports desc: ghost 6 first!)
    # — the ghost takes 6 of 9, the office then has 3 free against 4.
    statuses = {a.space_key: a.status for a in result.assignments}
    assert Status.INSUFFICIENT_CAPACITY in statuses.values()
    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 10 and load["NER A"]["utilisation_pct"] > 100


def test_a_rejected_match_makes_the_space_unplaced(client):
    """"Not on this drawing" (rejected on TEAP × drawing) is the same
    situation as never found: pending until a NER is chosen."""
    pid = _project("unplaced-rejected")
    _room(pid, "OFF.004", "Office", 100, 100)
    key = _teap(pid, "OFF.004", "Office", 4)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    with SessionLocal() as db:
        m = db.execute(select(SpaceMatchRow).where(SpaceMatchRow.project_id == pid)).scalar_one()
        m.rejected = True
        db.commit()
    result = _analyse(pid)
    a = next(x for x in result.assignments if x.space_key == key)
    assert a.unplaced and a.status is Status.NOT_ANALYSABLE
    rows, _ = _rows(client, pid)
    assert rows[key]["group"] == "pending" and rows[key]["group_reason"] == "no room on the drawing"


# ---------------------------------------------------------------------------
# 3. The workbook: figures, and the group beside the status
# ---------------------------------------------------------------------------

def test_the_workbook_carries_the_figures_and_the_group(client):
    pid = _project("workbook-figures")
    _room(pid, "OFF.005", "Office", 100, 100)
    _room(pid, "OFF.006", "Store", 150, 100)
    _teap(pid, "OFF.005", "Office", 4)
    _teap(pid, "OFF.006", "Store", 2)
    ghost = _teap(pid, "GHO.005", "Not on any sheet", 6)
    _teap(pid, "ZER.005", "No ports", 0)
    ner_a = _ner(pid, "NER A", 100, 120, total_ports=48)
    _match(client, pid)
    _assign(client, pid, ghost, ner_a)
    _analyse(pid)

    r = client.post(f"/api/projects/{pid}/reports/xlsx")
    assert r.status_code == 200, r.text
    path = r.json().get("file") or r.json().get("path")
    if not path or not os.path.exists(path):
        from app.config import settings
        path = next((settings.exports_dir / f"project_{pid}").glob("*_analysis.xlsx"))
    wb = openpyxl.load_workbook(path)
    assert "Coverage figures" in wb.sheetnames
    # 3.0.0: the figures are the last sheet (Marcelo's order of 14 Oct 2026)
    assert wb.sheetnames[-1] == "Coverage figures"
    ws = wb["Coverage figures"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("Section", "Figure", "Count", "Of", "Share", "Note")
    by_label = {r[1]: r for r in rows[1:]}
    assert by_label["TEAP spaces in the file"][2] == 4
    assert by_label["requesting network ports — the study"][2] == 3
    assert by_label["requesting no port — left out"][2] == 1
    assert by_label["found on the drawing (tied to a room)"][2] == 2
    assert by_label["found on the drawing (tied to a room)"][4] == pytest.approx(2 / 3, abs=1e-3)
    assert by_label["not found on the drawing"][2] == 1
    assert by_label["  of which served by a NER you chose"][2] == 1
    assert by_label[GROUP_LABEL[Group.SERVED]][2] == 2
    assert by_label[GROUP_LABEL[Group.NOT_MEASURED]][2] == 1
    assert by_label["ports requested by the study (TEAP)"][2] == 12
    assert by_label["ports on a NER"][2] == 12
    assert ws.cell(row=2, column=5).number_format == "0.0%"

    ws = wb["TEAP and coverage"]
    head = [c.value for c in ws[1]]
    assert "Status" in head and "Status detail" in head
    i_s, i_d = head.index("Status"), head.index("Status detail")
    got = {r[0]: (r[i_s], r[i_d]) for r in ws.iter_rows(min_row=2, values_only=True)}
    assert got["OFF.005"] == (GROUP_LABEL[Group.SERVED], STATUS_LABEL[Status.SERVED])
    assert got["GHO.005"] == (GROUP_LABEL[Group.NOT_MEASURED],
                              STATUS_LABEL[Status.ASSIGNED_NOT_PLACED])

    ws = wb["Exceptions"]
    head = [c.value for c in ws[1]]
    assert head == ["Space key", "Space name", "Page", "Status", "Status detail", "Detail"]


def test_the_figures_service_reads_hand_ties_and_rejections(client):
    pid = _project("figures-hands")
    r1 = _room(pid, "OFF.007", "Office", 100, 100)
    _room(pid, "OFF.008", "Store", 150, 100)
    k1 = _teap(pid, "OFF.007", "Office", 4)
    k2 = _teap(pid, "OFF.008", "Store", 2)
    _teap(pid, "GHO.007", "Ghost", 1)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    with SessionLocal() as db:
        rows = {m.teap_space_id: m for m in db.execute(
            select(SpaceMatchRow).where(SpaceMatchRow.project_id == pid)).scalars()}
        teap = {t.space_key: t for t in db.execute(
            select(TeapSpace).where(TeapSpace.project_id == pid)).scalars()}
        rows[teap[k1].id].method, rows[teap[k1].id].confirmed = "manual", True
        rows[teap[k1].id].confirmed_by = "tester"
        rows[teap[k2].id].rejected = True
        db.commit()
    result = _analyse(pid)
    with SessionLocal() as db:
        figs = {f["label"]: f for f in S.coverage_figures(db, db.get(Project, pid), result)}
    assert figs["  tied by hand"]["count"] == 1
    assert figs["  confirmed by you"]["count"] == 1
    assert figs["  of which rejected — not on this drawing"]["count"] == 1
    assert figs["not found on the drawing"]["count"] == 2
    assert figs[GROUP_LABEL[Group.PENDING]]["count"] == 2
    assert figs["  drawn by you"]["count"] == 1


# ---------------------------------------------------------------------------
# 4. NER references on a key plan
# ---------------------------------------------------------------------------

def test_a_reference_is_drawn_only_and_counted_nowhere(client):
    pid = _project("refs")
    _room(pid, "OFF.009", "Office", 100, 100)
    _teap(pid, "OFF.009", "Office", 4)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)

    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 2, "kind": "NER_CRITICAL_REF", "label": "NER A",
                          "x": 400, "y": 300})
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["ner_asset_id"] is None, "a reference never becomes a register row"
    with SessionLocal() as db:
        assets = db.execute(select(NerAsset).where(NerAsset.project_id == pid)).scalars().all()
        assert len(assets) == 1, "still one NER in the register"
        p = db.get(Project, pid)
        assert "NER_CRITICAL_REF" not in migrate.ASSET_KINDS
        drawn = S.markers_to_draw(db, p)
        ref = next(n for n in drawn if n.kind == "NER_CRITICAL_REF")
        assert ref.label == "NER A" and ref.point.page == 2 and not ref.can_serve
    # The engine never sees it: the office is still served by NER A alone.
    result = _analyse(pid)
    assert set(result.ner_load) == {f"A{assets[0].id}"}
    # Re-classifying between the two reference kinds is allowed; to a NER is
    # a different thing (it would enter the register) and is left to the
    # +NER tools.
    r = client.patch(f"/api/projects/{pid}/elements/{made['id']}", json={"kind": "NER_NONCRITICAL_REF"})
    assert r.status_code == 200
    r = client.patch(f"/api/projects/{pid}/elements/{made['id']}", json={"kind": "BOGUS_REF"})
    assert r.status_code == 422
    listed = next(e for e in client.get(f"/api/projects/{pid}/elements?page=2").json()
                  if e["id"] == made["id"])
    assert listed["kind"] == "NER_NONCRITICAL_REF" and listed["ner_asset_id"] is None


def test_the_exporter_rings_a_reference_with_the_reach_circles():
    """The circles are what the reference is drawn for."""
    from app.domain import reports as R
    src = (ROOT / "backend" / "app" / "domain" / "reports.py").read_text(encoding="utf-8")
    # Since 2.8.0 only a *NER* reference gets the circles: a TER, COW or
    # DIVA reference has none, like the room it points at.
    assert "if not (n.can_serve or n.kind in NER_REFERENCE_KINDS):" in src
    assert "dashes=REFERENCE_RING_DASHES" in src
    for kind in REFERENCE_KINDS:
        assert kind in R.COLOURS
    assert any(row[2] == "reference" for row in R.LEGEND_ROWS)
    viewer = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    assert '"add-ner-ref-critical": "NER_CRITICAL_REF"' in viewer
    assert '"add-ner-ref": "NER_NONCRITICAL_REF"' in viewer
    assert '"*NER★"' in viewer and '"*NER"' in viewer


# ---------------------------------------------------------------------------
# 5. Suggested names
# ---------------------------------------------------------------------------

# Since 2.10.0 the convention is the "NER Standardized Naming Structure"
# sheet (24 Sep 2026), not the ALA device sheet: NERc NN with fixed numbers by
# purpose at a competition venue, 09–20 for the rest, NER 21+ for every
# non-critical room.

# The naming-convention tests that stood here (the suggester, the venue
# presets, the per-project convention, the TER numbering) went with the
# convention itself in 2.14.0 — every NER is named in sequence now; see
# tests/test_scale_keyplans_sequence_2140.py.


def test_the_demand_table_keeps_its_width_and_the_box_scrolls():
    """A table at 100 % never overflows — it shrinks. With a working width
    the box gets a horizontal scrollbar on a small monitor instead of a Notes
    column three words wide (Marcelo, 22 Sep 2026)."""
    panels = (SRC / "pages" / "panels.tsx").read_text(encoding="utf-8")
    css = (SRC / "styles.css").read_text(encoding="utf-8")
    demand = panels[panels.index("export function DemandPanel"):panels.index("export function ExceptionsPanel")]
    assert "<WideScroll>" in demand and '<table className="wide">' in demand
    wide = (SRC / "components" / "WideScroll.tsx").read_text(encoding="utf-8")
    assert 'className="hscroll-top"' in wide, "the sideways scrollbar is mirrored at the top"
    assert 'className={`scroll wide-scroll' in wide
    assert re.search(r"table\.wide\s*\{[^}]*min-width:\s*\d{4}px", css)
    assert re.search(r"\.wide-scroll\s*\{[^}]*overflow-x:\s*auto", css)
