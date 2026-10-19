"""The 10 Sep 2026 Demand-screen pass — pinned by test.

Marcelo, from a screenshot of *Demand per space*, asked for five things and
then two more:

1. **From → to.** A TEAP space tied to a *different* room on the drawing
   (``PRS.001.03`` → ``PRS.001.02``) was invisible here; the row now says which
   drawing room it points at, and flags the redirection.
2. **Another level.** A space on level 2 served by the NER directly below it
   on level 1 "pode e vai acontecer". The engine used to drop such a pin and
   quietly hand the space to the nearest room on the same page. It now
   honours the pin — once the person has **declared** it (the ``other
   level`` box), or the TEAP names the room — counts the ports against that
   room, and reports the distance as *not measured* rather than inventing one.
3. **Notes readable** — a screen matter, held by the bundle, not by these.
4. **Bigger markers** on the marked-up PDF: 2× the dot, +2 pt bold label.
5. **Lines optional** on the marked-up PDF, like the legend.
6. The ``other level`` checkbox itself, and
7. the **drawing number** beside the page number, read off the title block.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-demand-20260910-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/demand.sqlite3")

import pymupdf                                                     # noqa: E402
from fastapi.testclient import TestClient                          # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain.coverage import NER, CoverageResult, compute_coverage  # noqa: E402
from app.domain.distance import (CROSS_LEVEL_WARNING, DemandType,  # noqa: E402
                                 DistanceRules, Status, evaluate_cross_level)
from app.domain.geometry import Area, Point                        # noqa: E402
from app.domain.pdf_ingest import (ElementKind, TextItem, TitleBlock,  # noqa: E402
                                   _title_block, extract_drawing, read_title_blocks)
from app.domain.reports import (MARKER_LABEL_FONT, MARKER_LABEL_SIZE,  # noqa: E402
                                MARKER_RADIUS, STATUS_FILL, export_marked_pdf)
from app.domain.routes import VerticalLink, build_network          # noqa: E402
from app.domain.units import Scale                                 # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, NerAsset, Page,  # noqa: E402
                        Project, TeapFile, TeapSpace)

RULES = DistanceRules()
SCALES = {1: Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True),
          2: Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)}


def area(key="S", x=10.0, page=1):
    return Area(key=key, name=key, page=page, label_point=Point(x, 0.0, page))


def ner(key, x, *, page=1, ports=100, used=0, critical=False):
    return NER(key=key, label=f"room {key}",
               kind=ElementKind.NER_CRITICAL if critical else ElementKind.NER_NONCRITICAL,
               point=Point(x, 0.0, page), critical=critical, total_ports=ports,
               used_ports=used)


def run(areas, ners, *, pinned=None, pin_sources=None, cross_level=None, ports=5.0,
        network=None, confirmed=True):
    spec = [(a, ports, DemandType.GENERAL, None, confirmed) for a in areas]
    return compute_coverage(areas=spec, ners=ners, scale_for_page=SCALES, rules=RULES,
                            pinned=pinned, pin_sources=pin_sources,
                            cross_level=cross_level, network=network)


# ---------------------------------------------------------------------------
# 2. A room on another level — the engine
# ---------------------------------------------------------------------------

def test_the_engine_still_never_crosses_a_page_on_its_own():
    """The rule that predates all of this, unchanged: with no route and no
    declaration, a room on another page is not an option."""
    res = run([area(page=1)], [ner("BELOW", 10, page=2)])
    a = res.assignments[0]
    assert a.ner_key is None and a.status is Status.NOT_ANALYSABLE
    assert res.ner_load["BELOW"]["assigned_ports"] == 0.0


def test_a_pin_to_a_room_on_another_page_is_counted_without_a_tick():
    """2.10.0 (Marcelo, 24 Sep 2026: "se eu escolhi, deveria ser served"): the
    choice is the declaration. The room he chose on another page serves the
    space and carries its ports; the distance is not measured. What must
    still not happen is what happened before 10 Sep: the space handed to the
    nearest room on this page instead."""
    res = run([area(page=1)], [ner("SAME", 0, page=1), ner("BELOW", 10, page=2)],
              pinned={"S": "BELOW"}, ports=5.0)
    a = res.assignments[0]
    assert a.ner_key == "BELOW" and a.status is Status.CROSS_LEVEL_NOT_MEASURED
    assert res.ner_load["BELOW"]["assigned_ports"] == 5.0
    assert res.ner_load["SAME"]["assigned_ports"] == 0.0
    assert "S" not in res.uncovered


def test_a_declared_cross_level_pin_is_honoured_and_counted():
    """The case itself: level-2 space, level-1 room right below it, box ticked."""
    res = run([area(page=1)], [ner("SAME", 0, page=1), ner("BELOW", 10, page=2)],
              pinned={"S": "BELOW"}, cross_level={"S"}, ports=7.0)
    a = res.assignments[0]
    assert a.ner_key == "BELOW" and a.pinned is True
    assert a.status is Status.CROSS_LEVEL_NOT_MEASURED
    assert a.cross_level is True and a.ner_page == 2
    assert a.evaluation is not None
    assert a.evaluation.effective_distance_m is None, "no distance is invented across sheets"
    assert CROSS_LEVEL_WARNING in a.evaluation.warnings
    assert a.evaluation.requires_human_validation is True
    assert "you assigned it" in " ".join(a.reasons)
    assert "not measured" in " ".join(a.reasons)
    # the point of the exercise: the ports land on the room he chose
    assert res.ner_load["BELOW"]["assigned_ports"] == 7.0
    assert res.ner_load["SAME"]["assigned_ports"] == 0.0
    # served-but-unmeasured is neither "within limits" nor "not covered" —
    # it is on the exception list, waiting for the vertical route
    assert "S" not in res.uncovered
    assert res.summary()["served"] == 0
    ex = [e for e in res.exceptions if e["space_key"] == "S"]
    assert ex and ex[0]["status"] == "cross_level_not_measured"
    assert "vertical route" in ex[0]["detail"]


def test_the_teap_naming_the_room_is_a_declaration_in_itself():
    res = run([area(page=1)], [ner("BELOW", 10, page=2)],
              pinned={"S": "BELOW"}, pin_sources={"S": "the TEAP"})
    a = res.assignments[0]
    assert a.ner_key == "BELOW" and a.status is Status.CROSS_LEVEL_NOT_MEASURED
    assert "the TEAP names it" in " ".join(a.reasons)


def test_capacity_still_bites_across_levels():
    """Counting the ports against the room is the whole point — so a full room
    on the other level comes back full, exactly as a full room on this one."""
    res = run([area(page=1)], [ner("BELOW", 10, page=2, ports=8)],
              pinned={"S": "BELOW"}, cross_level={"S"}, ports=10.0)
    a = res.assignments[0]
    assert a.ner_key == "BELOW"
    assert a.status is Status.INSUFFICIENT_CAPACITY
    assert "over capacity" in " ".join(a.reasons)
    assert "S" in res.uncovered
    assert res.ner_load["BELOW"]["assigned_ports"] == 10.0
    assert res.ner_load["BELOW"]["utilisation_pct"] == 125.0


def test_an_unconfirmed_match_no_longer_hides_the_cross_level_room():
    """3.0.0: the chosen room on another level is counted whether or not the
    match is confirmed; the row still carries the unconfirmed match."""
    res = run([area(page=1)], [ner("BELOW", 10, page=2)],
              pinned={"S": "BELOW"}, cross_level={"S"}, confirmed=False)
    assert res.assignments[0].status is Status.CROSS_LEVEL_NOT_MEASURED
    assert res.assignments[0].match_confirmed is False


def test_a_declaration_for_a_room_on_the_same_page_changes_nothing():
    """The tick is about a room on another page; on the same page the distance
    is measured as always and the status is a real verdict."""
    res = run([area(page=1)], [ner("NEAR", 0, page=1), ner("CHOSEN", 60, page=1)],
              pinned={"S": "CHOSEN"}, cross_level={"S"})
    a = res.assignments[0]
    assert a.ner_key == "CHOSEN" and a.status is Status.SERVED
    assert a.cross_level is False and a.ner_page == 1
    assert a.evaluation.effective_distance_m == pytest.approx(50.0)


def test_a_registered_vertical_route_measures_the_cross_level_pin():
    """The day the shaft is drawn the status goes away by itself: the route is
    measured and the verdict is a distance, declaration or no declaration."""
    net = build_network([], [VerticalLink("shaft", Point(10, 0, 1), Point(10, 0, 2), 6.0)],
                        SCALES)
    res = run([area(page=1, x=10)], [ner("BELOW", 10, page=2)],
              pinned={"S": "BELOW"}, network=net)
    a = res.assignments[0]
    assert a.ner_key == "BELOW" and a.status is Status.SERVED
    assert a.cross_level is True and a.ner_page == 2
    assert a.evaluation.effective_distance_m == pytest.approx(6.0)
    assert a.evaluation.method.value == "route"


def test_the_row_carries_the_room_page_and_the_flag():
    res = run([area(page=1)], [ner("BELOW", 10, page=2)],
              pinned={"S": "BELOW"}, cross_level={"S"})
    d = res.assignments[0].to_dict()
    assert d["ner_page"] == 2 and d["cross_level"] is True
    assert d["status"] == "cross_level_not_measured"
    assert d["evaluation"]["effective_distance_m"] is None


def test_evaluate_cross_level_carries_the_limit_and_no_distance():
    ev = evaluate_cross_level(area=area(page=1), ner_point=Point(0, 0, 2), scale=SCALES[1],
                              rules=RULES, demand_type=DemandType.PHOTOGRAPHER)
    assert ev.status is Status.CROSS_LEVEL_NOT_MEASURED
    assert ev.limit_m == RULES.photographer_limit_m
    assert ev.effective_distance_m is None and ev.margin_m is None
    assert ev.compliant is False
    assert ev.detail == {"space_page": 1, "ner_page": 2}


def test_every_status_has_a_fill_on_the_marked_pdf():
    """A verdict the exporter cannot paint would fall back to a colour the
    legend does not explain."""
    for st in Status:
        assert st in STATUS_FILL, st


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------

def _sign_in(client: TestClient) -> None:
    from app import auth as A
    with SessionLocal() as db:
        try:
            A.create_user(db, username="tester", password="a-long-test-phrase",
                          display_name="Test User", is_admin=True, actor="tests")
        except A.AuthError:
            pass
    assert client.post("/api/auth/login",
                       json={"username": "tester",
                             "password": "a-long-test-phrase"}).status_code == 200


@pytest.fixture(scope="module")
def client():
    init_db()
    c = TestClient(app)
    _sign_in(c)
    return c


def _pdf(path: str, pages: int = 2) -> str:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=800, height=600)
    doc.save(path)
    doc.close()
    return path


def _project(name: str, *, pages: int = 2) -> int:
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        path = _pdf(f"{TMP}/{name}.pdf", pages)
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=path,
                    sha256="x" * 64, page_count=pages)
        db.add(d)
        db.flush()
        for i in range(pages):
            db.add(Page(drawing_id=d.id, number=i + 1, width=800, height=600,
                        metres_per_unit=1.0, scale_label="1u=1m",
                        scale_source="manual", scale_confirmed=True, sheet_number=""))
        db.commit()
        return p.id


def _marker(pid: int, label: str, *, page: int = 1, x: float = 100, y: float = 100) -> int:
    """A non-critical NER marker on ``page``; returns its register asset id."""
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                    kind="NER_NONCRITICAL", label=label, x=x, y=y, origin="extracted",
                    confidence=0.8, confirmed=False, evidence=[f"label text '{label}'"],
                    total_ports=48)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        return e.ner_asset_id


def _teap_and_rooms(pid: int, rows: list[tuple[str, str, str, str, int]]) -> None:
    """``rows``: (teap code, teap name, drawing code, drawing name, drawing page)."""
    with SessionLocal() as db:
        p = db.get(Project, pid)
        tf = TeapFile(project_id=pid, filename="t.xlsx", stored_path=f"{TMP}/t.xlsx",
                      sha256="y" * 64)
        db.add(tf)
        db.flush()
        for code, name, dcode, dname, page in rows:
            db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|{code}",
                             space_code=code, space_name=name, total_ports=4.0))
            if dcode or dname:
                db.add(DrawingSpace(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                                    space_code=dcode or None, name=dname, x=50, y=50,
                                    confidence=0.9))
        db.commit()


# ---------------------------------------------------------------------------
# 1. From → to on the Demand row
# ---------------------------------------------------------------------------

def test_the_demand_row_says_which_drawing_room_the_space_was_tied_to(client):
    pid = _project("from-to")
    _teap_and_rooms(pid, [
        ("PRS.001.03", "Photo Work Room", "PRS.001.02", "Photo Work Room", 2),
        ("PRS.005", "Photo File Centre", "PRS.005", "Photo File Centre", 1),
        ("OBS.71.01", "OB VAN", "", "", 1),
    ])
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    # tie PRS.001.03 to the room labelled PRS.001.02, by hand, as he would
    rows = {m["teap_code"]: m for m in client.get(f"/api/projects/{pid}/matches").json()}
    with SessionLocal() as db:
        target = db.execute(
            __import__("sqlalchemy").select(DrawingSpace).where(
                DrawingSpace.project_id == pid,
                DrawingSpace.space_code == "PRS.001.02")).scalar_one()
        target_id = target.id
    r = client.patch(f"/api/projects/{pid}/matches/{rows['PRS.001.03']['id']}",
                     json={"confirmed": True, "drawing_space_id": target_id,
                           "justification": "same room on the drawing"})
    assert r.status_code == 200, r.text

    body = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    by = {s["space_code"]: s for s in body["spaces"]}

    redirected = by["PRS.001.03"]
    assert redirected["matched_code"] == "PRS.001.02"
    assert redirected["matched_name"] == "Photo Work Room"
    assert redirected["matched_page"] == 2
    assert redirected["redirected"] is True, "a different code is the from → to he asked for"
    assert redirected["match_confirmed"] is True
    # the matcher found it by base code; confirming it made it a person's decision
    assert redirected["match_method"] == "base_code"
    assert redirected["match_by"] == "user"

    same = by["PRS.005"]
    assert same["matched_code"] == "PRS.005"
    assert same["redirected"] is False, "an identical code is not worth an arrow"

    nothing = by["OBS.71.01"]
    assert nothing["matched_code"] is None and nothing["redirected"] is False

    assert body["redirected"] == 1
    assert body["sheet_numbers"] == {"1": "", "2": ""}     # JSON keys are strings


def test_a_code_that_only_differs_in_punctuation_is_the_same_room(client):
    pid = _project("from-to-punct")
    _teap_and_rooms(pid, [("TEC.004-02", "Timing", "TEC.004.02", "Timing", 1)])
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    body = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    assert body["spaces"][0]["matched_code"] == "TEC.004.02"
    assert body["spaces"][0]["redirected"] is False


# ---------------------------------------------------------------------------
# 6. The "other level" box — the API
# ---------------------------------------------------------------------------

def test_choosing_a_room_on_another_page_declares_the_other_level(client):
    """Marcelo, 10 Sep 2026: "a intervenção humana se baseou no conhecimento
    que eu tenho do projeto, dos níveis … eu verifiquei a existência de shaft".
    The choice is the declaration: the box comes ticked, the room counts from
    the next run, and the status says *other level*, never *not analysable*."""
    pid = _project("other-level")
    a_same = _marker(pid, "NER 1", page=1)
    a_below = _marker(pid, "NER 2", page=2)
    _teap_and_rooms(pid, [("PRS.001", "Press", "PRS.001", "Press", 1)])
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    key = "TST|PRS.001"

    # nothing to declare before a room is chosen
    r = client.post(f"/api/projects/{pid}/spaces/{key}/cross-level",
                    json={"cross_level": True})
    assert r.status_code == 422

    # choosing a room on another page: ticked by the choice itself
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                    json={"ner_asset_id": a_below, "justification": "the room below"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["other_page"] is True and body["ner_page"] == 2 and body["space_page"] == 1
    assert body["cross_level"] is True
    assert "other level" in body["note"] and "not measured" in body["note"]
    with SessionLocal() as db:
        assert S.cross_level_declarations(db, db.get(Project, pid)) == {key}
    row = {s["space_key"]: s for s in
           client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"]}[key]
    assert row["cross_level_declared"] is True
    assert row["assigned_ner_page"] == 2 and row["matched_page"] == 1

    # the analysis honours it: served from page 2, counted, not measured
    r = client.post(f"/api/projects/{pid}/analyse?scenario=As-Is")
    assert r.status_code == 200, r.text
    row = {s["space_key"]: s for s in
           client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"]}[key]
    assert row["serving_ner"] == "NER 2"
    assert row["serving_ner_page"] == 2 and row["cross_level"] is True
    assert row["status"] == "cross_level_not_measured", "other level — not 'not analysable'"
    assert row["distance_m"] is None
    load = {v["label"]: v for v in
            client.get(f"/api/projects/{pid}/spaces/assignments").json()["ner_load"]}
    assert load["NER 2"]["assigned_ports"] == 4.0
    assert load["NER 1"]["assigned_ports"] == 0.0

    # 2.10.0: there is no box to untick any more — the way back from a slip
    # is to clear the choice, and the row returns to the rule (NER 1, on the
    # same page, nearest).
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                    json={"ner_asset_id": None, "justification": "a slip"})
    assert r.status_code == 200
    assert client.post(f"/api/projects/{pid}/analyse?scenario=As-Is").status_code == 200
    row = {s["space_key"]: s for s in
           client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"]}[key]
    assert row["serving_ner"] == "NER 1" and row["assigned_ner_asset_id"] is None
    load = {v["label"]: v for v in
            client.get(f"/api/projects/{pid}/spaces/assignments").json()["ner_load"]}
    assert load["NER 2"]["assigned_ports"] == 0.0 and load["NER 1"]["assigned_ports"] == 4.0

    # a room on the same page carries no declaration
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                    json={"ner_asset_id": a_same, "justification": "changed my mind"})
    assert r.status_code == 200 and r.json()["cross_level"] is False
    assert r.json()["other_page"] is False
    with SessionLocal() as db:
        assert S.cross_level_declarations(db, db.get(Project, pid)) == set()

    # and releasing the room clears it too
    client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                json={"ner_asset_id": a_below, "justification": "below again"})
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign", json={"ner_asset_id": None})
    assert r.status_code == 200
    with SessionLocal() as db:
        t = db.execute(__import__("sqlalchemy").select(TeapSpace).where(
            TeapSpace.space_key == key, TeapSpace.project_id == pid)).scalar_one()
        assert t.assigned_cross_level is False


# ---------------------------------------------------------------------------
# 4 and 5. The marked-up PDF: bigger markers, optional lines
# ---------------------------------------------------------------------------

def _marked(tmp_path, *, draw_links: bool) -> pymupdf.Page:
    src = _pdf(str(tmp_path / f"src-{draw_links}.pdf"), pages=1)
    out = str(tmp_path / f"out-{draw_links}.pdf")
    rooms = [ner("N1", 150)]
    res = run([area("S", x=100)], rooms)
    export_marked_pdf(src, out, coverage=res, ners=rooms, scale_for_page=SCALES,
                      rules=RULES, draw_links=draw_links)
    return pymupdf.open(out)[0]


def test_the_marker_is_twice_the_size_and_the_name_two_points_bigger_and_bold(tmp_path):
    assert MARKER_RADIUS == 12.0, "was 6"
    assert MARKER_LABEL_SIZE == 9.0, "was 7"
    assert MARKER_LABEL_FONT == "hebo", "Helvetica-Bold"
    page = _marked(tmp_path, draw_links=True)
    widths = [round(d["rect"].width) for d in page.get_drawings()]
    assert 24 in widths, f"a 12 pt-radius dot should be on the sheet; widths: {widths}"
    spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])
             for s in l.get("spans", []) if s["text"] == "room N1"]
    assert spans, "the room is named on the sheet"
    assert spans[0]["size"] == pytest.approx(9.0)
    assert "bold" in spans[0]["font"].lower()


def test_the_lines_can_be_left_off_and_the_rest_stays(tmp_path):
    with_lines = _marked(tmp_path, draw_links=True)
    without = _marked(tmp_path, draw_links=False)
    assert "50" in with_lines.get_text(), "the distance rides on the line"
    assert "50" not in without.get_text(), "and leaves with it"
    assert len(without.get_drawings()) < len(with_lines.get_drawings())
    # the markers, the space fill and the legend are untouched
    for page in (with_lines, without):
        assert "room N1" in page.get_text()
        assert "NER COVERAGE" in page.get_text()
        assert 24 in [round(d["rect"].width) for d in page.get_drawings()]


def test_a_room_on_another_page_is_named_beside_the_space(tmp_path):
    """No line can be drawn to a room on another sheet; the space says which
    room serves it instead, so a grey fill is not left unexplained."""
    src = _pdf(str(tmp_path / "x.pdf"), pages=2)
    out = str(tmp_path / "x-out.pdf")
    rooms = [ner("BELOW", 10, page=2)]
    res = run([area("S", x=100, page=1)], rooms, pinned={"S": "BELOW"}, cross_level={"S"})
    export_marked_pdf(src, out, coverage=res, ners=rooms, scale_for_page=SCALES, rules=RULES)
    doc = pymupdf.open(out)
    assert "room BELOW (p. 2)" in doc[0].get_text()
    doc.close()


def test_the_report_route_accepts_the_lines_switch(client):
    pid = _project("lines-switch")
    _marker(pid, "NER 9", page=1)
    _teap_and_rooms(pid, [("PRS.001", "Press", "PRS.001", "Press", 1)])
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    r = client.post(f"/api/projects/{pid}/reports/pdf?lines=false&legend=false")
    assert r.status_code == 200, r.text
    assert r.json()["file"].endswith("_marked.pdf")
    audit = client.get(f"/api/projects/{pid}/audit").json()
    gen = next(a for a in audit if a["action"] == "report.generated")
    assert gen["payload"]["lines"] is False and gen["payload"]["legend"] is False


# ---------------------------------------------------------------------------
# 7. The drawing number, read off the title block
# ---------------------------------------------------------------------------

def _item(text, x, y, size=7.0):
    return TextItem(text=text, x=x, y=y, x0=x - 20, y0=y - 4, x1=x + 20, y1=y + 4,
                    page=1, size=size, color=0)


def test_the_title_block_is_read_by_its_labels_not_by_font_size():
    """The OWC canoe-slalom sheet, as measured: label at 7 pt, value 11 pt
    below it at 12 pt — and a key-plan grid tag ``410C8-CSL-O`` printed at 16 pt
    in the same corner, larger than the number and shaped just like it."""
    items = [
        _item("410C8-CSL-O", 1779.7, 1110.9, 15.9),
        _item("VENUE", 2165.6, 1316.3), _item("CANOE SLALOM CENTER", 2225.8, 1328.0, 10),
        _item("DRAWING TITLE", 2180.9, 1401.3),
        _item("KEY ENLARGED PLAN - LEVEL 01", 2236.8, 1413.2, 10),
        _item("STATUS", 2167.4, 1463.5), _item("VENUE DESIGN BOOK 3.0", 2278.7, 1476.2, 10),
        _item("DRAWING NUMBER", 2186.6, 1492.0), _item("OWC-401-CSL-O", 2278.7, 1502.8, 12),
        _item("DRAWN", 2166.9, 1520.3), _item("CH", 2194.4, 1532.7, 10),
        _item("03/31/2026", 2375.8, 1282.8),
    ]
    tb = _title_block(items)
    assert tb.number == "OWC-401-CSL-O"
    assert tb.title == "KEY ENLARGED PLAN - LEVEL 01"
    assert tb.level == "LEVEL 01"
    assert any("printed under 'DRAWING NUMBER'" in e for e in tb.evidence)


def test_a_sheet_with_no_title_block_yields_nothing_rather_than_a_guess():
    tb = _title_block([_item("410C8-CSL-O", 1779.7, 1110.9, 15.9), _item("NER 10", 200, 200, 36)])
    assert tb == TitleBlock()


def test_a_label_beside_its_value_is_read_too():
    tb = _title_block([_item("SHEET NO.", 100, 500), _item("A-101", 220, 500, 9),
                       _item("SHEET TITLE", 100, 520), _item("LEVEL 2 PLAN", 240, 520, 9)])
    assert tb.number == "A-101" and tb.title == "LEVEL 2 PLAN" and tb.level == "LEVEL 2"


def _book(path: str, numbers: list[str | None]) -> str:
    doc = pymupdf.open()
    for n in numbers:
        page = doc.new_page(width=800, height=600)
        if n:
            page.insert_text((650, 560), "DRAWING NUMBER", fontsize=7)
            page.insert_text((660, 572), n, fontsize=12)
            page.insert_text((650, 520), "DRAWING TITLE", fontsize=7)
            page.insert_text((660, 532), f"ENLARGED PLAN LEVEL 0{numbers.index(n) + 1}",
                             fontsize=10)
    doc.save(path)
    doc.close()
    return path


def test_extract_drawing_reads_the_sheet_number_and_the_level(tmp_path):
    path = _book(str(tmp_path / "book.pdf"), ["OWC-401-CSL-O", None, "OWC-410B8-CSL-O"])
    pages = extract_drawing(path).pages
    assert [p.sheet_number for p in pages] == ["OWC-401-CSL-O", "", "OWC-410B8-CSL-O"]
    assert pages[0].sheet_title == "ENLARGED PLAN LEVEL 01"
    assert pages[0].level_hint == "LEVEL 01"
    assert pages[2].level_hint == "LEVEL 03"
    blocks = read_title_blocks(path, [3])
    assert list(blocks) == [3] and blocks[3].number == "OWC-410B8-CSL-O"


def test_pages_imported_before_this_are_filled_once_on_start(tmp_path):
    """The book on his machine was imported before any of this existed. The
    next start reads the numbers off it — and marks the pages that carry none
    so the 45 MB file is not opened again for them."""
    path = _book(str(tmp_path / "old.pdf"), ["OWC-401-CSL-O", None])
    with SessionLocal() as db:
        p = Project(name="backfill", venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="old.pdf", stored_path=path,
                    sha256="z" * 64, page_count=2)
        db.add(d)
        db.flush()
        for i in range(2):
            db.add(Page(drawing_id=d.id, number=i + 1, width=800, height=600,
                        sheet_title="Critical NER 4"))     # the old font-size guess
        gone = Drawing(project_id=p.id, filename="gone.pdf",
                       stored_path=str(tmp_path / "missing.pdf"), sha256="w" * 64,
                       page_count=1)
        db.add(gone)
        db.flush()
        db.add(Page(drawing_id=gone.id, number=1, width=800, height=600))
        db.commit()
        pid = p.id

    with SessionLocal() as db:
        p = db.get(Project, pid)
        report = migrate.backfill_sheet_numbers(db, p)
        assert report == {"sheet_numbers_read": 1, "sheet_numbers_blank": 1,
                          "sheet_numbers_file_missing": 1}
        pages = {(pg.drawing.filename, pg.number): pg for d in p.drawings for pg in d.pages}
        assert pages[("old.pdf", 1)].sheet_number == "OWC-401-CSL-O"
        assert pages[("old.pdf", 1)].sheet_title == "ENLARGED PLAN LEVEL 01", \
            "the title block outranks the font-size guess"
        assert pages[("old.pdf", 1)].level == "LEVEL 01"
        assert pages[("old.pdf", 2)].sheet_number == ""
        assert pages[("old.pdf", 2)].sheet_title == "Critical NER 4", \
            "nothing found, nothing touched"
        assert pages[("gone.pdf", 1)].sheet_number == ""
        # second start: nothing left to read
        assert migrate.backfill_sheet_numbers(db, p) == {
            "sheet_numbers_read": 0, "sheet_numbers_blank": 0,
            "sheet_numbers_file_missing": 0}


def test_the_project_payload_names_the_sheet(client):
    pid = _project("sheet-in-payload")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.drawings[0].pages[0].sheet_number = "OWC-401-CSL-O"
        db.commit()
    pages = client.get(f"/api/projects/{pid}").json()["pages"]
    assert pages[0]["sheet_number"] == "OWC-401-CSL-O"
    assert pages[1]["sheet_number"] == ""


# ---------------------------------------------------------------------------
# The TEAP × drawing tiles add up
# ---------------------------------------------------------------------------

def test_the_matching_tiles_add_up_and_a_rejection_is_counted_apart(client):
    """On his OWC project the tiles read 102 / 45 / 45 / 0 / 57 / 45 and looked
    wrong. They were right — every one of the 45 matched rows had been
    confirmed by him — but "still need review: 0" over 57 spaces still waiting
    for a room read as "nothing left to do". The figures now split every TEAP
    space into matched + no room + rejected, and matched into confirmed + not
    yet confirmed."""
    pid = _project("tiles")
    _teap_and_rooms(pid, [
        ("PRS.001", "Press", "PRS.001", "Press", 1),
        ("PRS.002", "Photo", "PRS.002", "Photo", 1),
        ("OBS.001", "OB VAN", "", "", 1),
        ("OBS.002", "GFX", "", "", 1),
    ])
    first = client.post(f"/api/projects/{pid}/matching/run").json()["stats"]
    assert (first["matched"], first["unmatched_teap"], first["rejected"]) == (2, 2, 0)
    assert first["matched"] + first["unmatched_teap"] + first["rejected"] == first["teap_spaces"]
    assert first["confirmed"] + first["needs_review"] == first["matched"]

    rows = {m["teap_code"]: m for m in client.get(f"/api/projects/{pid}/matches").json()}
    # he says OB VAN is not on this drawing, and confirms one of the two matches
    assert client.patch(f"/api/projects/{pid}/matches/{rows['OBS.001']['id']}",
                        json={"rejected": True, "justification": "not here"}).status_code == 200
    assert client.patch(f"/api/projects/{pid}/matches/{rows['PRS.001']['id']}",
                        json={"confirmed": True, "drawing_space_id": rows["PRS.001"]["drawing_space_id"],
                              "justification": "checked"}).status_code == 200

    second = client.post(f"/api/projects/{pid}/matching/run").json()["stats"]
    assert second["matched"] == 2 and second["rejected"] == 1 and second["unmatched_teap"] == 1
    assert second["matched"] + second["unmatched_teap"] + second["rejected"] == 4
    assert second["confirmed"] + second["needs_review"] == second["matched"]
    assert second["decisions_kept"] == 2, "the rejection and the confirmation"
