"""2.2.0 — 17 Sep 2026. Four things Marcelo asked for in one conversation, and
two defects the real TEAP v2.3 exposed while they were being built.

1. **The TEAP rules.** The check runs from the TEAP to the drawing and never
   back: a room on the drawing that no TEAP line asks for is not a finding.
2. **No ports, no work.** A TEAP space that requests no network port is matched
   silently and left off the queue, Demand per space, the exceptions and the
   coverage run. Filtered, not deleted — and a space whose *wired connections*
   count no port (the Photo Position FOP case) stays visible, with the reason.
3. **The same space on more than one page.** A room cut by a match line is
   labelled on two sheets. Same code + same level is proof; anything less is a
   question on the row. Once confirmed the engine measures from the sheet the
   NER is actually on.
4. **Wireless points.** Placed by hand, one port each on the nearest NER within
   the general limit, counted against that room's capacity.

Defects: TEAP v2.3's three quantity columns (the README says *Updated QTY*;
the importer took *NEW QTY*), and a newer TEAP being added beside the older
one instead of replacing it (OWC: 102 + 105 spaces for one venue).
"""

from __future__ import annotations

import os
import tempfile

import openpyxl
import pytest

TMP = tempfile.mkdtemp(prefix="ner-220-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t220.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain.coverage import NER, compute_coverage              # noqa: E402
from app.domain.distance import DemandType, DistanceRules, Status  # noqa: E402
from app.domain.geometry import Area, Point                        # noqa: E402
from app.domain.pdf_ingest import (DEMAND_KINDS, VISUAL_ONLY_KINDS,  # noqa: E402
                                   ElementKind)
from app.domain.scope import teap_scope, wired_without_ports       # noqa: E402
from app.domain.teap_import import _score_header_row               # noqa: E402
from app.domain.units import Scale                                 # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, Page, Project,  # noqa: E402
                        SpaceOccurrenceLink, TeapFile, TeapSpace)

RULES = DistanceRules()
ONE = Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)


# ---------------------------------------------------------------------------
# fixtures
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


def _line(product, qty, ports, code="X"):
    return {"row": 1, "product": product, "code": code, "qty": qty, "ports": ports,
            "rule": "A", "explanation": ""}


def _project(name, *, levels=("LEVEL 04", "LEVEL 04")) -> int:
    """Two sheets at 1 unit = 1 m. ``levels`` is what the title block gave."""
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="x" * 64, page_count=len(levels))
        db.add(d)
        db.flush()
        for i, lvl in enumerate(levels):
            db.add(Page(drawing_id=d.id, number=i + 1, width=1000, height=700,
                        metres_per_unit=1.0, scale_label="1u=1m",
                        scale_source="manual", scale_confirmed=True, level=lvl))
        tf = TeapFile(project_id=p.id, filename="teap.xlsx", stored_path=f"{TMP}/t.xlsx",
                      sha256="y" * 64)
        db.add(tf)
        db.commit()
        return p.id


def _room(pid, code, name, page, x, y) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        r = DrawingSpace(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                         space_code=code, name=name, x=x, y=y, confidence=0.9)
        db.add(r)
        db.commit()
        return r.id


def _teap(pid, code, name, ports, lines=None) -> int:
    with SessionLocal() as db:
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        t = TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|{code or name}",
                      space_code=code, space_name=name, total_ports=ports,
                      lines=lines if lines is not None else [_line("Laptop", ports, ports)])
        db.add(t)
        db.commit()
        return t.id


def _ner(pid, label, page, x, y, *, total_ports=None) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                    kind="NER_NONCRITICAL", label=label, x=x, y=y, origin="manual",
                    confidence=1.0, confirmed=True, total_ports=total_ports)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        if total_ports is not None and e.ner_asset is not None:
            e.ner_asset.total_ports = total_ports
            db.commit()
        return e.id


def _match_and_analyse(client, pid):
    r = client.post(f"/api/projects/{pid}/matching/run")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        p = db.get(Project, pid)
        result, ners = S.analyse(db, p)
        S.save_scenario(db, p, "As-Is", "as_is", result, ners)
        db.commit()
    return r.json(), result


# ---------------------------------------------------------------------------
# 1 + 2. The scope rule
# ---------------------------------------------------------------------------

def test_ports_requested_means_in_scope():
    assert teap_scope(3, [_line("Laptop", 3, 3)]) == (True, None)


def test_no_ports_and_nothing_wired_is_out_of_scope():
    lines = [_line("Wireless Connection - Shared Internet Access (SIA) Wireless LAN", 4, 0),
             _line("Monitor - Standard - 24 inch", 2, 0)]
    assert teap_scope(0, lines) == (False, None)
    assert teap_scope(0, []) == (False, None)
    assert teap_scope(None, None) == (False, None)


def test_wired_connections_with_no_port_counted_stay_on_the_list():
    """HND, TEAP v2.3: Photo Position FOP — 15 wired connections, zero
    network ports. The 70 m limit exists for exactly these rooms."""
    lines = [_line("Wired Connection - Shared Internet Access (SIA) Wired LAN", 15, 0, "DIPSA")]
    assert wired_without_ports(lines) == 15
    ok, note = teap_scope(0, lines)
    assert ok is True
    assert "15 wired connection" in note and "no network port" in note


@pytest.mark.parametrize("product", [
    "Wired Connection - Dedicated plug (RJ45) for RF", "Wired Connection - Dedicated Internet Access (DIA)"])
def test_every_kind_of_wired_request_counts(product):
    assert wired_without_ports([_line(product, 2, 0)]) == 2


def test_a_wireless_line_is_never_mistaken_for_a_wired_one():
    assert wired_without_ports(
        [_line("Wireless Connection - Shared Internet Access (SIA) Wireless LAN", 9, 0)]) == 0


def test_a_wired_line_with_quantity_zero_asks_for_nothing():
    assert wired_without_ports([_line("Wired Connection - SIA", 0, 0)]) == 0


def test_no_port_is_ever_invented_for_a_wired_line(client):
    """In scope at zero ports: visible, measured, and adding nothing to a NER."""
    pid = _project("scope-wired")
    _room(pid, "PRS.007.01", "Photo Position FOP", 1, 100, 100)
    _teap(pid, "PRS.007.01", "Photo Position FOP", 0,
          [_line("Wired Connection - Shared Internet Access (SIA) Wired LAN", 15, 0)])
    _ner(pid, "NER 1", 1, 130, 100)
    _, result = _match_and_analyse(client, pid)
    a = next(x for x in result.assignments if x.space_key == "TST|PRS.007.01")
    assert a.status is Status.SERVED and a.ports_required == 0
    assert sum(v["assigned_ports"] for v in result.ner_load.values()) == 0


def test_zero_port_spaces_are_matched_silently_and_left_off_every_list(client):
    pid = _project("scope-lists")
    _room(pid, "OFF.001", "Office", 1, 100, 100)
    _room(pid, "LNG.001", "Lounge", 1, 200, 100)
    _teap(pid, "OFF.001", "Office", 4)
    _teap(pid, "LNG.001", "Lounge", 0,
          [_line("Wireless Connection - Shared Internet Access (SIA) Wireless LAN", 1, 0)])
    _ner(pid, "NER 1", 1, 150, 100)
    out, result = _match_and_analyse(client, pid)

    assert out["stats"]["teap_spaces"] == 1, "the tiles count the study, not the TEAP"
    assert out["stats"]["zero_port_hidden"] == 1
    assert [a.space_key for a in result.assignments] == ["TST|OFF.001"], \
        "a space that requests no port is not analysed"

    listed = client.get(f"/api/projects/{pid}/matches").json()
    assert [m["teap_code"] for m in listed] == ["OFF.001"]
    everything = client.get(f"/api/projects/{pid}/matches?include_zero=true").json()
    lounge = next(m for m in everything if m["teap_code"] == "LNG.001")
    assert lounge["in_scope"] is False
    assert lounge["drawing_code"] == "LNG.001", \
        "it is still matched — silently — so its room is known if a later TEAP gives it a port"

    demand = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    assert [d["space_code"] for d in demand["spaces"]] == ["OFF.001"]
    assert demand["zero_port_hidden"] == 1
    shown = client.get(f"/api/projects/{pid}/spaces/assignments?include_zero=true").json()
    assert {d["space_code"] for d in shown["spaces"]} == {"OFF.001", "LNG.001"}

    flags = {t["space_code"]: t["in_scope"]
             for t in client.get(f"/api/projects/{pid}/teap-spaces").json()}
    assert flags == {"OFF.001": True, "LNG.001": False}


def test_the_scope_follows_the_teap_not_a_stored_flag(client):
    """Filtered, not deleted: give the space a port and it is back by itself."""
    pid = _project("scope-live")
    _room(pid, "LNG.002", "Lounge", 1, 100, 100)
    tid = _teap(pid, "LNG.002", "Lounge", 0, [])
    _room(pid, "OFF.002", "Office", 1, 140, 100)
    _teap(pid, "OFF.002", "Office", 2)
    client.post(f"/api/projects/{pid}/matching/run")
    assert len(client.get(f"/api/projects/{pid}/matches").json()) == 1
    with SessionLocal() as db:
        db.get(TeapSpace, tid).total_ports = 2
        db.commit()
    assert len(client.get(f"/api/projects/{pid}/matches").json()) == 2


def test_the_check_never_runs_from_the_drawing_to_the_teap(client, tmp_path):
    """A room on the drawing that no TEAP line asks for is not a finding — not
    in the matching result, not on a tile, not in the workbook."""
    pid = _project("teap-rules")
    _room(pid, "OFF.003", "Office", 1, 100, 100)
    for i in range(5):
        _room(pid, f"STO.00{i}", f"Storage {i}", 1, 300 + i * 10, 300)
    _teap(pid, "OFF.003", "Office", 2)
    _ner(pid, "NER 1", 1, 120, 100)
    out, result = _match_and_analyse(client, pid)
    assert set(out) == {"stats"}
    assert "unmatched_drawing" not in out["stats"]

    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        from app.config import settings
        path = settings.exports_dir / f"project_{pid}" / r.json()["file"]
    wb = openpyxl.load_workbook(path)
    text = " ".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row
                    if c.value is not None)
    assert "Storage" not in text and "not in TEAP" not in text


def test_rooms_nobody_is_tied_to_are_offered_first(client):
    """A TEAP line the matcher could not place is tied by hand. The rooms no
    line is tied to are where it most likely is — but two lines may share a
    room, so the rest stay available."""
    pid = _project("teap-manual")
    a = _room(pid, "OFF.004", "Office", 1, 100, 100)
    b = _room(pid, "ZZZ.999", "Mystery room", 1, 200, 100)
    _teap(pid, "OFF.004", "Office", 2)
    _teap(pid, "OBVAN", "OB VAN", 6)
    client.post(f"/api/projects/{pid}/matching/run")
    tied = {s["id"]: s["tied_to"] for s in client.get(f"/api/projects/{pid}/drawing-spaces").json()}
    assert tied[a] == ["OFF.004"] and tied[b] == []
    row = next(m for m in client.get(f"/api/projects/{pid}/matches").json()
               if m["teap_code"] == "OBVAN")
    assert row["drawing_space_id"] is None
    assert client.patch(f"/api/projects/{pid}/matches/{row['id']}",
                        json={"drawing_space_id": b}).status_code == 200
    tied = {s["id"]: s["tied_to"] for s in client.get(f"/api/projects/{pid}/drawing-spaces").json()}
    assert tied[b] == ["OBVAN"]


def test_the_workbook_names_what_it_left_out(client):
    pid = _project("scope-workbook")
    _room(pid, "OFF.005", "Office", 1, 100, 100)
    _room(pid, "LNG.005", "Lounge", 1, 140, 100)
    _teap(pid, "OFF.005", "Office", 2)
    _teap(pid, "LNG.005", "Lounge", 0, [])
    _ner(pid, "NER 1", 1, 120, 100)
    _match_and_analyse(client, pid)
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    wb = openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    main = [row[0].value for row in wb["TEAP and coverage"].iter_rows(min_row=2)]
    assert "OFF.005" in main and "LNG.005" not in main
    left = [row[0].value for row in wb["TEAP spaces with no ports"].iter_rows(min_row=2)]
    assert left == ["LNG.005"], "nothing leaves the workbook without a trace"


# ---------------------------------------------------------------------------
# 3. The same space on more than one page
# ---------------------------------------------------------------------------

def _area(key, page, x, y, **kw):
    return Area(key=key, name=key, page=page, label_point=Point(x, y, page), **kw)


def _n(key, page, x, y, **kw):
    return NER(key=key, label=key, kind=ElementKind.NER_NONCRITICAL,
               point=Point(x, y, page), **kw)


def test_engine_alone_a_corner_label_with_the_ner_on_the_next_sheet():
    """Before: 'no NER on this level'. The NER is on page 2; so is the space."""
    a = _area("S", 1, 990, 10)
    res = compute_coverage(areas=[(a, 4, DemandType.GENERAL, None, True)],
                           ners=[_n("N", 2, 50, 10)], scale_for_page={1: ONE, 2: ONE},
                           rules=RULES)
    assert res.assignments[0].status is Status.NOT_ANALYSABLE

    a = _area("S", 1, 990, 10)
    a.occurrences.append(_area("S", 2, 20, 10, meta={"link_basis": "same space code on the same level"}))
    res = compute_coverage(areas=[(a, 4, DemandType.GENERAL, None, True)],
                           ners=[_n("N", 2, 50, 10)], scale_for_page={1: ONE, 2: ONE},
                           rules=RULES)
    got = res.assignments[0]
    assert got.status is Status.SERVED and got.ner_key == "N"
    assert got.evaluation.effective_distance_m == pytest.approx(30 * RULES.routing_slack_factor, rel=0.3)
    assert got.measured_page == 2
    assert got.cross_level is False, "same level, another sheet — not another floor"
    assert any("measured from page 2" in r for r in got.reasons)
    assert res.ner_load["N"]["assigned_ports"] == 4


def test_engine_the_shortest_real_measurement_wins_and_the_tied_page_wins_a_tie():
    a = _area("S", 1, 100, 10)
    a.occurrences.append(_area("S", 2, 100, 10))
    res = compute_coverage(areas=[(a, 1, DemandType.GENERAL, None, True)],
                           ners=[_n("FAR", 1, 180, 10), _n("NEAR", 2, 110, 10)],
                           scale_for_page={1: ONE, 2: ONE}, rules=RULES)
    assert res.assignments[0].ner_key == "NEAR" and res.assignments[0].measured_page == 2

    a = _area("S", 1, 100, 10)
    a.occurrences.append(_area("S", 2, 100, 10))
    res = compute_coverage(areas=[(a, 1, DemandType.GENERAL, None, True)],
                           ners=[_n("N1", 1, 120, 10)],
                           scale_for_page={1: ONE, 2: ONE}, rules=RULES)
    assert res.assignments[0].measured_page is None, "measured where the TEAP line is tied"


def test_engine_the_photographer_limit_still_applies_from_the_other_sheet():
    a = _area("P", 1, 990, 10)
    a.occurrences.append(_area("P", 2, 0, 10))
    res = compute_coverage(areas=[(a, 1, DemandType.PHOTOGRAPHER, None, True)],
                           ners=[_n("N", 2, 80, 10)], scale_for_page={1: ONE, 2: ONE},
                           rules=RULES)
    assert res.assignments[0].status is Status.OUT_OF_LIMIT, "80 m is past 70 m on any sheet"


def test_engine_an_unconfirmed_label_is_a_question_never_an_answer():
    a = _area("S", 1, 990, 10)
    a.meta["proposed_occurrences"] = [_area("S", 2, 20, 10, meta={"link_id": 7,
                                                                 "link_method": "exact_code"})]
    res = compute_coverage(areas=[(a, 4, DemandType.GENERAL, None, True)],
                           ners=[_n("N", 2, 50, 10)], scale_for_page={1: ONE, 2: ONE},
                           rules=RULES)
    got = res.assignments[0]
    assert got.status is Status.NOT_ANALYSABLE and got.ner_key is None
    assert res.ner_load["N"]["assigned_ports"] == 0, "nothing moves on a guess"
    assert got.occurrence_hint["link_id"] == 7 and got.occurrence_hint["ner_label"] == "N"
    assert any("confirm on this row" in r for r in got.reasons)


def test_engine_no_hint_when_the_row_is_already_served():
    a = _area("S", 1, 100, 10)
    a.meta["proposed_occurrences"] = [_area("S", 2, 20, 10, meta={"link_id": 1})]
    res = compute_coverage(areas=[(a, 1, DemandType.GENERAL, None, True)],
                           ners=[_n("N1", 1, 110, 10), _n("N2", 2, 30, 10)],
                           scale_for_page={1: ONE, 2: ONE}, rules=RULES)
    assert res.assignments[0].occurrence_hint is None, "asked only where it changes the answer"


def _links(pid):
    with SessionLocal() as db:
        return [(ln.verdict, ln.auto, ln.method, ln.id) for ln in db.execute(
            select(SpaceOccurrenceLink).where(SpaceOccurrenceLink.project_id == pid)
            .order_by(SpaceOccurrenceLink.id)).scalars()]


def test_same_code_same_level_is_proof(client):
    """HND: PRS.001.03 Photo Work Room, tied to the sheet with no NER, and
    labelled again on the neighbouring sheet, which has one."""
    pid = _project("occ-proof", levels=("LEVEL 04", "LEVEL 04"))
    _room(pid, "PRS.001.03", "Photo Work Room", 1, 990, 10)
    for i in range(6):                                   # page 1 is the denser sheet
        _room(pid, f"AAA.10{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "PRS.001.03", "Photo Work Room", 2, 20, 10)
    _teap(pid, "PRS.001.03", "Photo Work Room", 2)
    _ner(pid, "NER 20", 2, 50, 10)
    out, result = _match_and_analyse(client, pid)
    assert [(v, a, m) for v, a, m, _ in _links(pid)] == [("confirmed", True, "exact_code")]
    assert out["stats"]["same_space_other_pages"]["confirmed_by_rule"] == 1
    a = result.assignments[0]
    assert a.status is Status.SERVED and a.ner_label == "NER 20" and a.measured_page == 2

    row = client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"][0]
    assert row["measured_page"] == 2 and row["serving_ner"] == "NER 20"
    assert [(o["page"], o["verdict"], o["auto"]) for o in row["occurrences"]] == [(2, "confirmed", True)]
    assert any("both pages are LEVEL 04" in e for e in row["occurrences"][0]["evidence"])
    assert row["occurrences"][0]["level_basis"] == "title_block"


def test_an_unread_level_is_a_question_and_your_answer_settles_it(client):
    """HND page 31 has no level in its title block; page 32 is LEVEL 04."""
    pid = _project("occ-ask", levels=(None, "LEVEL 04"))
    _room(pid, "PRS.001", "Venue Media Center", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.20{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "PRS.001", "Venue Media Center", 2, 20, 10)
    _teap(pid, "PRS.001", "Venue Media Center", 6)
    _ner(pid, "NER 20", 2, 50, 10)
    _, result = _match_and_analyse(client, pid)
    (verdict, auto, method, link_id), = _links(pid)
    assert (verdict, auto) == ("proposed", True)
    assert result.assignments[0].status is Status.NOT_ANALYSABLE
    assert result.assignments[0].occurrence_hint["link_id"] == link_id

    demand = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    assert demand["same_space_questions"] == 1
    assert demand["spaces"][0]["occurrence_hint"]["ner_label"] == "NER 20"

    r = client.patch(f"/api/projects/{pid}/occurrence-links/{link_id}", json={"verdict": "confirmed"})
    assert r.status_code == 200, r.text
    _, result = _match_and_analyse(client, pid)
    assert result.assignments[0].status is Status.SERVED
    assert [(v, a) for v, a, _, _ in _links(pid)] == [("confirmed", False)], \
        "a matching run never overwrites what a person said"


def test_saying_not_the_same_space_holds_even_against_the_rule(client):
    pid = _project("occ-no", levels=("LEVEL 02", "LEVEL 02"))
    _room(pid, "SEC.005", "Security", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.30{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "SEC.005", "Security", 2, 20, 10)
    _teap(pid, "SEC.005", "Security", 3)
    _ner(pid, "NER 9", 2, 50, 10)
    _match_and_analyse(client, pid)
    link_id = _links(pid)[0][3]
    client.patch(f"/api/projects/{pid}/occurrence-links/{link_id}", json={"verdict": "rejected"})
    _, result = _match_and_analyse(client, pid)
    assert result.assignments[0].status is Status.NOT_ANALYSABLE
    assert result.assignments[0].occurrence_hint is None
    assert _links(pid)[0][:2] == ("rejected", False)

    # …and "undo" hands the question back to the rule.
    client.patch(f"/api/projects/{pid}/occurrence-links/{link_id}", json={"verdict": "proposed"})
    assert [(v, a) for v, a, _, _ in _links(pid)] == [("confirmed", True)]


def test_another_floor_is_never_inferred_from_a_label(client):
    pid = _project("occ-floor", levels=("LEVEL 01", "LEVEL 02"))
    _room(pid, "WC.001", "Toilets", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.40{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "WC.001", "Toilets", 2, 20, 10)
    _teap(pid, "WC.001", "Toilets", 1)
    _ner(pid, "NER 3", 2, 50, 10)
    _, result = _match_and_analyse(client, pid)
    assert _links(pid) == []
    assert result.assignments[0].status is Status.NOT_ANALYSABLE


def test_a_name_alone_is_never_proof(client):
    """'Storage' is on every level of every venue."""
    pid = _project("occ-name", levels=("LEVEL 01", "LEVEL 01"))
    _room(pid, None, "Storage", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.50{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, None, "Storage", 2, 20, 10)
    _teap(pid, None, "Storage", 1)
    _ner(pid, "NER 3", 2, 50, 10)
    _, result = _match_and_analyse(client, pid)
    assert [(v, m) for v, _, m, _ in _links(pid)] == [("proposed", "name")]
    assert result.assignments[0].status is Status.NOT_ANALYSABLE


@pytest.mark.parametrize("sheet,level", [
    ("HND-440B5-VVO-O", "LEVEL 04"), ("HND-410B5-VVO-O", "LEVEL 01"),
    ("HND-410MB2-VVO-O", "LEVEL 01M"), ("HND-401M-VVO-O", "LEVEL 01M"),
    ("OWC-401-CSL-O", "LEVEL 01"), ("OWC-430A6-CSL-O", "LEVEL 03"),
    ("HND-470B10-VVO-O", "LEVEL 07"), ("A-101", None), ("", None), (None, None)])
def test_the_level_a_drawing_number_implies(sheet, level):
    from app.domain.matching import level_from_sheet_number
    assert level_from_sheet_number(sheet) == level


def _set_sheet(pid, page, sheet):
    with SessionLocal() as db:
        for pg in db.execute(select(Page).join(Drawing).where(Drawing.project_id == pid)).scalars():
            if pg.number == page:
                pg.sheet_number = sheet
        db.commit()


def test_a_level_implied_by_the_drawing_number_helps_the_question_never_answers_it(client):
    """HND page 31 (HND-440B5): no level in the title block. The number says
    level 04, like page 32 — on the reference books the number agrees with the
    title block 68 times out of 68. Still a convention, not a statement on the
    sheet: it makes the question a two-second one, it does not skip it."""
    pid = _project("occ-sheetno", levels=(None, "LEVEL 04"))
    _set_sheet(pid, 1, "HND-440B5-VVO-O")
    _set_sheet(pid, 2, "HND-440B10-VVO-O")
    _room(pid, "PRS.001", "VMC", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.70{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "PRS.001", "VMC", 2, 20, 10)
    _teap(pid, "PRS.001", "VMC", 6)
    client.post(f"/api/projects/{pid}/matching/run")
    assert [(v, a) for v, a, _, _ in _links(pid)] == [("proposed", True)]
    link = client.get(f"/api/projects/{pid}/occurrence-links").json()[0]
    assert link["level_basis"] == "drawing_number"
    ev = link["evidence"][1]
    assert "implied by the drawing number HND-440B5-VVO-O" in ev and "yours to confirm" in ev


def test_a_drawing_number_is_enough_to_rule_another_floor_out(client):
    pid = _project("occ-sheetno-floor", levels=(None, "LEVEL 04"))
    _set_sheet(pid, 1, "HND-420B5-VVO-O")
    _room(pid, "WC.009", "Toilets", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.80{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "WC.009", "Toilets", 2, 20, 10)
    _teap(pid, "WC.009", "Toilets", 1)
    client.post(f"/api/projects/{pid}/matching/run")
    assert _links(pid) == []


def test_the_question_is_not_asked_of_a_row_waiting_on_something_else():
    a = _area("S", 1, 990, 10)
    a.meta["proposed_occurrences"] = [_area("S", 2, 20, 10, meta={"link_id": 3})]
    res = compute_coverage(areas=[(a, 1, DemandType.GENERAL, None, False)],   # match unconfirmed
                           ners=[_n("N1", 1, 900, 10), _n("N2", 2, 50, 10)],
                           scale_for_page={1: ONE, 2: ONE}, rules=RULES)
    # 3.0.0: an unconfirmed match is served by the nearest NER, so there is
    # nothing to ask about another page.
    assert res.assignments[0].ner_key == "N1"
    assert res.assignments[0].occurrence_hint is None


def test_tying_the_line_to_another_room_drops_the_old_rooms_pages(client):
    pid = _project("occ-retie", levels=("LEVEL 01", "LEVEL 01"))
    _room(pid, "PRS.010", "Press", 1, 990, 10)
    for i in range(6):
        _room(pid, f"AAA.60{i}", f"Filler {i}", 1, 10 + i, 600)
    _room(pid, "PRS.010", "Press", 2, 20, 10)
    other = _room(pid, "PRS.099", "Other", 1, 500, 10)
    _teap(pid, "PRS.010", "Press", 1)
    client.post(f"/api/projects/{pid}/matching/run")
    assert len(_links(pid)) == 1
    row = client.get(f"/api/projects/{pid}/matches").json()[0]
    client.patch(f"/api/projects/{pid}/matches/{row['id']}", json={"drawing_space_id": other})
    assert _links(pid) == []


def test_there_is_no_bulk_way_to_say_same_space(client):
    """A wrong 'same space' moves a room's ports onto a NER that does not reach
    it. One row at a time — Marcelo's rule for anything a wrong click costs."""
    from app.api.routes import router
    paths = [r.path for r in router.routes if "occurrence-links" in getattr(r, "path", "")]
    assert sorted(paths) == ["/projects/{project_id}/occurrence-links",
                             "/projects/{project_id}/occurrence-links/{link_id}"]


# ---------------------------------------------------------------------------
# 4. Wireless points
# ---------------------------------------------------------------------------

def test_a_wireless_point_is_demand_not_a_room():
    assert ElementKind.WIRELESS in DEMAND_KINDS
    assert ElementKind.WIRELESS not in VISUAL_ONLY_KINDS
    assert ElementKind.WIRELESS not in migrate.ASSET_KINDS
    from app.domain.coverage import SERVING_KINDS
    assert ElementKind.WIRELESS not in SERVING_KINDS


def _wp(client, pid, x, y, page=1):
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": page, "kind": "WIRELESS", "label": "", "x": x, "y": y})
    assert r.status_code == 201, r.text
    return r.json()


def test_wireless_points_number_themselves_and_stay_out_of_the_register(client):
    pid = _project("wp-names")
    a, b = _wp(client, pid, 10, 10), _wp(client, pid, 20, 10)
    assert a["ner_asset_id"] is None and b["ner_asset_id"] is None
    labels = [e["label"] for e in client.get(f"/api/projects/{pid}/elements").json()]
    assert labels == ["WIFI-1", "WIFI-2"]
    assert client.get(f"/api/projects/{pid}/ners").json()["ners"] == []


def test_each_point_is_measured_to_the_nearest_ner_and_takes_no_port(client):
    """4.0.0: an access point is not a TEAP product — measured, never counted."""
    pid = _project("wp-load")
    _room(pid, "OFF.010", "Office", 1, 100, 100)
    _teap(pid, "OFF.010", "Office", 4)
    _ner(pid, "NER A", 1, 100, 120, total_ports=48)
    _ner(pid, "NER B", 1, 600, 120, total_ports=48)
    _wp(client, pid, 110, 120)            # 10 m from A
    _wp(client, pid, 590, 120)            # 10 m from B
    _wp(client, pid, 350, 650)            # beyond 90 m of both
    _, result = _match_and_analyse(client, pid)

    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 4 and load["NER A"]["wireless_points"] == 1
    assert load["NER B"]["assigned_ports"] == 0 and load["NER B"]["wireless_points"] == 1
    assert len(load["NER A"]["spaces"]) == 1, "a wireless point is not a space served"

    s = result.summary()
    assert s["spaces"] == 1 and s["total_ports"] == 4, "the space figures stay the space figures"
    assert (s["wireless_points"], s["wireless_served"], s["wireless_not_served"]) == (3, 2, 1)

    far = next(a for a in result.assignments if a.space_name == "WIFI-3")
    assert far.ner_key is None and far.status is Status.OUT_OF_LIMIT
    assert any(e["space_name"] == "WIFI-3" for e in result.exceptions), \
        "a point no NER reaches is an exception, not a silence"

    demand = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    assert [d["space_code"] for d in demand["spaces"]] == ["OFF.010"]
    rows = {w["label"]: w for w in demand["wireless_points"]}
    assert rows["WIFI-1"]["serving_ner"] == "NER A" and rows["WIFI-1"]["status"] == "served"
    assert rows["WIFI-3"]["serving_ner"] is None and rows["WIFI-3"]["nearest_ner"]
    assert {v["label"]: v["wireless_points"] for v in demand["ner_load"]} == {"NER A": 1, "NER B": 1}


def test_a_full_room_passes_the_point_to_the_next_and_says_so_when_none_is_free():
    full = _n("FULL", 1, 10, 0, total_ports=1, used_ports=1)
    free = _n("FREE", 1, 40, 0, total_ports=24)
    wp = _area("WP1", 1, 0, 0, estimated=False, meta={"kind": "wireless_point"})
    res = compute_coverage(areas=[(wp, 1.0, DemandType.GENERAL, None, True)],
                           ners=[full, free], scale_for_page={1: ONE}, rules=RULES)
    assert res.assignments[0].ner_key == "FREE"

    wp = _area("WP1", 1, 0, 0, estimated=False, meta={"kind": "wireless_point"})
    res = compute_coverage(areas=[(wp, 1.0, DemandType.GENERAL, None, True)],
                           ners=[_n("FULL", 1, 10, 0, total_ports=1, used_ports=1)],
                           scale_for_page={1: ONE}, rules=RULES)
    assert res.assignments[0].ner_key == "FULL"
    assert res.assignments[0].status is Status.INSUFFICIENT_CAPACITY


def test_a_point_never_reaches_a_ner_on_another_page():
    wp = _area("WP1", 1, 0, 0, estimated=False, meta={"kind": "wireless_point"})
    res = compute_coverage(areas=[(wp, 1.0, DemandType.GENERAL, None, True)],
                           ners=[_n("N", 2, 5, 0)], scale_for_page={1: ONE, 2: ONE}, rules=RULES)
    assert res.assignments[0].ner_key is None


def test_a_room_carrying_only_wireless_points_is_not_a_redundancy_candidate():
    from app.domain.coverage import redundancy_candidates
    wp = _area("WP1", 1, 0, 0, estimated=False, meta={"kind": "wireless_point"})
    ners = [_n("N", 1, 5, 0, total_ports=24)]
    res = compute_coverage(areas=[(wp, 1.0, DemandType.GENERAL, None, True)],
                           ners=ners, scale_for_page={1: ONE}, rules=RULES)
    assert redundancy_candidates(res, ners, RULES) == []


def test_wireless_points_alone_are_enough_to_analyse(client):
    """No TEAP matched yet, access points already drawn: still a study."""
    pid = _project("wp-only")
    _ner(pid, "NER A", 1, 100, 120)
    _wp(client, pid, 110, 120)
    with SessionLocal() as db:
        result, _ = S.analyse(db, db.get(Project, pid))
    assert [a.space_name for a in result.assignments] == ["WIFI-1"]


def test_the_sign_is_on_both_legends_in_the_same_colour():
    import re
    from app.domain import reports as R
    ts = open(os.path.join(os.path.dirname(R.__file__), "..", "..", "..",
                           "frontend", "src", "lib", "notation.ts"), encoding="utf-8").read()
    # One sign since 2.14.0 (the indoor/outdoor split of 2.5.0 went), in the
    # same colour on both legends.
    for label, kind, style, ts_key in (
            ("Wi-Fi - space with wireless", ElementKind.WIRELESS, "wifi", "WIRELESS"),):
        row = next(r for r in R.LEGEND_ROWS if r[0] == label)
        assert row[2] == style and row[1] == R.COLOURS[kind]
        m = re.search(ts_key + r':\s*"#([0-9a-fA-F]{6})"', ts)
        assert m, ts_key
        rgb = tuple(int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
        assert all(abs(a - b) < 0.02 for a, b in zip(rgb, row[1])), label


# ---------------------------------------------------------------------------
# The two defects TEAP v2.3 exposed
# ---------------------------------------------------------------------------

V23_HEADERS = ["Action", "Unique ID", "UniqueKey", "Venue Code", "Venue Name", "Venue Type",
               "Zone", "FA Code", "Space Code", "Space Name", "Product Code",
               "Product Description", "TEAP v2.0", "NEW QTY", "Updated QTY", "Sport Code",
               "Staffing", "FA's Comments", "TEAP Team's comment", "NER Name",
               "Primary Product Category", "Network Ports"]


def test_v23_quantity_is_the_updated_column_as_its_readme_says():
    """'column O - Updated Quantity should be used … Column M and N are feeding
    data for Column O and should be ignored.' NEW QTY comes first on the sheet
    and used to win: every line unchanged since v2.0 was read as quantity 0."""
    _, mapping = _score_header_row(V23_HEADERS)
    assert mapping["quantity"] == "Updated QTY"
    assert mapping["network_ports"] == "Network Ports"


def test_v20_quantity_column_is_still_found():
    headers = [h for h in V23_HEADERS if h not in ("TEAP v2.0", "NEW QTY", "Updated QTY")]
    _, mapping = _score_header_row(headers + ["New REQ Qty"])
    assert mapping["quantity"] == "New REQ Qty"


def _write_teap(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TEAP"
    ws.append(["Venue Code", "Space Code", "Space Name", "Product Code",
               "Product Description", "Updated QTY", "Network Ports"])
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def _import(client, pid, path):
    with open(path, "rb") as fh:
        up = client.post(f"/api/projects/{pid}/teap", files={"file": (os.path.basename(path), fh)})
    assert up.status_code == 201, up.text
    body = up.json()
    r = client.post(f"/api/projects/{pid}/teap/{body['id']}/import",
                    json={"sheet": body["proposed"]["sheet"],
                          "header_row": body["proposed"]["header_row"],
                          "mapping": body["proposed"]["mapping"], "venue_filter": "TST"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_newer_teap_replaces_the_older_one_and_keeps_your_decisions(client, tmp_path):
    """OWC held v2.0 and v2.3 side by side: 102 + 105 spaces for one venue, the
    ports counted twice, and the 45 decisions made on the v2.0 rows absent from
    the v2.3 ones."""
    with SessionLocal() as db:
        p = Project(name="teap-supersede", venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="x" * 64, page_count=1)
        db.add(d)
        db.flush()
        db.add(Page(drawing_id=d.id, number=1, width=1000, height=700, metres_per_unit=1.0,
                    scale_confirmed=True))
        db.commit()
        pid = p.id
    room = _room(pid, "ZZZ.001", "Truck bay", 1, 100, 100)
    _room(pid, "OFF.020", "Office", 1, 200, 100)

    old = str(tmp_path / "teap-v2.0.xlsx")
    _write_teap(old, [("TST", "OBVAN", "OB VAN", "TSTDI", "Desk phone", 6, 6),
                      ("TST", "OFF.020", "Office", "TSTDI", "Desk phone", 2, 2)])
    assert _import(client, pid, old)["spaces"] == 2
    client.post(f"/api/projects/{pid}/matching/run")
    row = next(m for m in client.get(f"/api/projects/{pid}/matches").json()
               if m["teap_code"] == "OBVAN")
    client.patch(f"/api/projects/{pid}/matches/{row['id']}",
                 json={"drawing_space_id": room, "confirmed": True})

    new = str(tmp_path / "teap-v2.3.xlsx")
    _write_teap(new, [("TST", "OBVAN", "OB VAN", "TSTDI", "Desk phone", 8, 8),
                      ("TST", "OFF.020", "Office", "TSTDI", "Desk phone", 2, 2),
                      ("TST", "NEW.001", "New room", "TSTDI", "Desk phone", 1, 1)])
    assert _import(client, pid, new)["spaces"] == 3

    spaces = client.get(f"/api/projects/{pid}/teap-spaces").json()
    assert sorted(s["space_code"] for s in spaces) == ["NEW.001", "OBVAN", "OFF.020"], \
        "one TEAP, one set of spaces — never both versions side by side"
    assert next(s for s in spaces if s["space_code"] == "OBVAN")["total_ports"] == 8

    client.post(f"/api/projects/{pid}/matching/run")
    row = next(m for m in client.get(f"/api/projects/{pid}/matches").json()
               if m["teap_code"] == "OBVAN")
    assert row["drawing_space_id"] == room and row["confirmed"] is True
    assert row["locked"] == "assigned", "the hand-made tie came across with the new TEAP"


# ---------------------------------------------------------------------------
# 2.3.0 — anything drawn on the sheet can be taken off the sheet
# ---------------------------------------------------------------------------

def test_a_wireless_point_placed_by_mistake_can_be_deleted(client):
    pid = _project("wp-delete")
    _ner(pid, "NER A", 1, 100, 120, total_ports=48)
    keep, wrong = _wp(client, pid, 110, 120), _wp(client, pid, 115, 125)
    with SessionLocal() as db:
        result, _ = S.analyse(db, db.get(Project, pid))
    assert {v["label"]: v["wireless_points"] for v in result.ner_load.values()} == {"NER A": 2}

    assert client.delete(f"/api/projects/{pid}/elements/{wrong['id']}").status_code == 204
    rows = client.get(f"/api/projects/{pid}/spaces/assignments").json()["wireless_points"]
    assert [w["label"] for w in rows] == ["WIFI-1"], "gone from the list at once, not at the next run"
    with SessionLocal() as db:
        result, _ = S.analyse(db, db.get(Project, pid))
    assert {v["label"]: v["wireless_points"] for v in result.ner_load.values()} == {"NER A": 1}
    assert {v["label"]: v["assigned_ports"] for v in result.ner_load.values()} == {"NER A": 0}

    # The next point takes the next free number after the highest still there.
    _wp(client, pid, 120, 120)
    labels = [e["label"] for e in client.get(f"/api/projects/{pid}/elements").json()]
    assert labels == ["NER A", "WIFI-1", "WIFI-2"]


def test_a_locked_marker_refuses_to_be_erased(client):
    pid = _project("wp-locked")
    wp = _wp(client, pid, 10, 10)
    assert client.patch(f"/api/projects/{pid}/elements/{wp['id']}",
                        json={"locked": True}).status_code == 200
    assert client.delete(f"/api/projects/{pid}/elements/{wp['id']}").status_code == 409


def test_a_route_segment_can_be_taken_back_and_the_distance_follows(client):
    pid = _project("route-delete")
    r = client.post(f"/api/projects/{pid}/routes",
                    json={"page": 1, "x0": 0, "y0": 0, "x1": 50, "y1": 0, "kind": "tray"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert [x["id"] for x in client.get(f"/api/projects/{pid}/routes").json()] == [rid]
    assert client.delete(f"/api/projects/{pid}/routes/{rid}").status_code == 204
    assert client.get(f"/api/projects/{pid}/routes").json() == []
    assert client.delete(f"/api/projects/{pid}/routes/{rid}").status_code == 404

    other = _project("route-delete-other")
    r2 = client.post(f"/api/projects/{other}/routes",
                     json={"page": 1, "x0": 0, "y0": 0, "x1": 5, "y1": 0, "kind": "tray"}).json()["id"]
    assert client.delete(f"/api/projects/{pid}/routes/{r2}").status_code == 404, \
        "one project cannot erase another's drawing"


def test_a_shaft_can_be_taken_back(client):
    pid = _project("shaft-delete")
    v = client.post(f"/api/projects/{pid}/verticals",
                    json={"key": "SHAFT-1-100", "lower_page": 1, "lower_x": 100, "lower_y": 100,
                          "upper_page": 2, "upper_x": 100, "upper_y": 100, "length_m": 4.5})
    assert v.status_code == 201, v.text
    vid = v.json()["id"]
    assert client.delete(f"/api/projects/{pid}/verticals/{vid}").status_code == 204
    assert client.get(f"/api/projects/{pid}/verticals").json() == []
    actions = [a["action"] for a in client.get(f"/api/projects/{pid}/audit").json()]
    assert "vertical.deleted" in actions, "erasing is audited like drawing"


def test_the_viewer_can_erase_everything_it_can_draw():
    """Every tool that puts something on the sheet has a way to take it off."""
    ts = open(os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "pages",
                           "Viewer.tsx"), encoding="utf-8").read()
    assert '"delete": "delete"' in ts, "the eraser tool"
    for call in ("api.deleteElement", "api.deleteRoute", "api.deleteVertical"):
        assert call in ts, call
    assert 'ev.key !== "Delete"' in ts, "the Delete key"
    assert 'pick("route", r)' in ts and 'pick("vertical", v)' in ts and 'pick("element", e)' in ts
