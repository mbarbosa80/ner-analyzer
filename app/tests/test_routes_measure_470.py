"""4.7.0 — 27 Oct 2026. The route tool made usable, the ruler, and the viewer's
analysis made the real one.

Marcelo, on the viewer's ``route`` tool: "Para que serve essa ferramenta
route?" — it saved one straight segment per two clicks, showed no length, and
the engine only joined a space or a NER to a route through a segment's *end*
within 60 PDF units (about 4 m at 1:200), so a space beside the middle of a
corridor tray was measured in a straight line as if nothing had been traced.
And on ``Coverage``: "parece um botão pra testar run analyses que é fake" —
it ran and saved the real analysis, but the viewer never read the saved one
back, so the overlay was empty on every visit.

What is held here:

* the engine joins a point to the nearest spot *along* a traced segment, within
  the larger of 60 units and 15 m on the sheet's scale, and the lead-in is
  straight, so a route is never shorter than the straight line;
* a route that starts or ends on the middle of another joins it (T-junction);
* a route drawn corner by corner is saved as one named route (R1, R2 …) and
  taken back whole;
* ``GET /analysis`` returns the last saved run with the time it was *run* —
  not the time the scenario row was first created — with its UTC offset, and
  says when something changed after it;
* the ruler saves nothing: no request is made from it.
"""

from __future__ import annotations

import os
import random
import re
import tempfile
import time

import pytest

TMP = tempfile.mkdtemp(prefix="ner-470-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t470.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402

from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain.coverage import NER, compute_coverage              # noqa: E402
from app.domain.distance import DemandType, DistanceRules          # noqa: E402
from app.domain.geometry import Area, Point                        # noqa: E402
from app.domain.pdf_ingest import ElementKind                      # noqa: E402
from app.domain.routes import (RouteNetwork, RouteSegment,         # noqa: E402
                               VerticalLink, build_network)
from app.domain.units import Scale                                 # noqa: E402
from app.main import app                                           # noqa: E402
from app import migrate                                            # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, Page,      # noqa: E402
                        Project, Scenario, TeapFile, TeapSpace)

ROOT = os.path.join(os.path.dirname(__file__), "..")
ONE = Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)
#: 1:200 on a PDF — one unit is 1/72 in, so 0.0706 m on the ground.
A200 = Scale(metres_per_unit=0.0254 / 72 * 200, source="ratio", label="1:200", confirmed=True)
RULES = DistanceRules()


def _seg(a, b, page=1):
    return RouteSegment(Point(*a, page), Point(*b, page), page)


def _area(key, x, y, page=1):
    return Area(key=key, name=key, page=page, label_point=Point(x, y, page))


def _ner(key, x, y, page=1):
    return NER(key=key, label=key, kind=ElementKind.NER_NONCRITICAL,
               point=Point(x, y, page), critical=False, total_ports=None)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

def test_a_space_beside_the_middle_of_a_tray_joins_it():
    """The case that made routes look useless: the tray runs past the space,
    its ends are far away. Before 4.7.0 this returned None."""
    net = build_network([_seg((0, 0), (200, 0))], [], {1: ONE})
    r = net.route_length_m(Point(100, 5, 1), Point(190, 5, 1), ONE)
    assert r is not None
    assert r["traced_m"] == pytest.approx(90.0)
    assert r["lead_in_m"] == pytest.approx(10.0)
    assert r["length_m"] == pytest.approx(100.0)


def test_the_join_tolerance_is_fifteen_metres_on_the_sheet_scale():
    """At 1:200, 60 units is about 4 m — a room label is often further than
    that from the corridor. 15 m on the ground is the reach."""
    units_per_m = 1 / A200.metres_per_unit
    net = build_network([_seg((0, 0), (2000, 0))], [], {1: A200})
    near = Point(500, 12 * units_per_m, 1)      # 12 m off the tray
    far = Point(900, 18 * units_per_m, 1)       # 18 m off the tray
    ner = Point(1500, 0, 1)
    assert net.route_length_m(near, ner, A200) is not None
    assert net.route_length_m(far, ner, A200) is None


def test_a_route_is_never_shorter_than_the_straight_line():
    """The lead-ins are straight, so joining from further away can only add
    length — a wider reach never makes a verdict more optimistic."""
    rnd = random.Random(470)
    segs = [_seg((0, 0), (100, 0)), _seg((100, 0), (100, 80)), _seg((100, 80), (0, 80))]
    net = build_network(segs, [], {1: ONE})
    for _ in range(200):
        a = Point(rnd.uniform(-10, 110), rnd.uniform(-10, 90), 1)
        b = Point(rnd.uniform(-10, 110), rnd.uniform(-10, 90), 1)
        r = net.route_length_m(a, b, ONE)
        if r:
            assert r["length_m"] + 1e-6 >= a.distance_units(b)


def test_two_points_on_the_same_segment_are_measured_along_it():
    net = build_network([_seg((0, 0), (100, 0))], [], {1: ONE})
    r = net.route_length_m(Point(20, 0, 1), Point(70, 0, 1), ONE)
    assert r["traced_m"] == pytest.approx(50.0) and r["lead_in_m"] == pytest.approx(0.0)


def test_a_route_that_ends_on_the_middle_of_another_joins_it():
    """The viewer snaps a corner onto an existing route; the graph has to
    treat that spot as a junction."""
    main = _seg((0, 0), (100, 0))
    branch = _seg((50, 0), (50, 60))            # starts on main's middle
    net = build_network([main, branch], [], {1: ONE})
    r = net.route_length_m(Point(0, 0, 1), Point(50, 60, 1), ONE)
    assert r is not None and r["traced_m"] == pytest.approx(110.0)


def test_a_shaft_foot_on_the_middle_of_a_tray_joins_it():
    tray = _seg((0, 0), (100, 0), page=1)
    shaft = VerticalLink("S1", Point(40, 0, 1), Point(40, 0, 2), 5.0)
    net = build_network([tray], [shaft], {1: ONE, 2: ONE})
    r = net.route_length_m(Point(100, 0, 1), Point(40, 0, 2), ONE)
    assert r is not None and r["length_m"] == pytest.approx(65.0)
    assert r["crosses_levels"] is True and r["vertical_links"] == ["S1"]


def test_the_assumptions_say_how_much_was_traced():
    net = build_network([_seg((0, 0), (200, 0))], [], {1: ONE})
    res = compute_coverage(
        areas=[(_area("A", 100, 5), 3.0, DemandType.GENERAL, None, True)],
        ners=[_ner("N1", 190, 5)], scale_for_page={1: ONE}, rules=RULES, network=net)
    a = res.assignments[0]
    assert a.evaluation.method.value == "route"
    assert a.evaluation.effective_distance_m == pytest.approx(100.0)
    assert any("90.0 m along the traced route + 10.0 m straight lead-in" in x
               for x in a.evaluation.assumptions)


def test_the_network_answers_many_questions_from_one_computation():
    net = build_network([_seg((0, 0), (100, 0)), _seg((100, 0), (100, 100))], [], {1: ONE})
    for k in range(50):
        assert net.route_length_m(Point(k, 3, 1), Point(97, 90, 1), ONE) is not None
    assert len(net._sssp) <= 4, "single-source results are cached per node"


# ---------------------------------------------------------------------------
# The API
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


_N = iter(range(10_000))


def _project(name) -> int:
    with SessionLocal() as db:
        p = Project(name=f"{name}-{next(_N)}", venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="x" * 64, page_count=2)
        db.add(d)
        db.flush()
        for i in (1, 2):
            db.add(Page(drawing_id=d.id, number=i, width=1000, height=700,
                        metres_per_unit=1.0, scale_label="1u=1m",
                        scale_source="manual", scale_confirmed=True))
        db.commit()
        return p.id


def test_a_route_drawn_corner_by_corner_is_one_named_route(client):
    pid = _project("route-path")
    r = client.post(f"/api/projects/{pid}/routes/path",
                    json={"page": 1, "points": [[0, 0], [100, 0], [100, 0], [100, 50]]})
    assert r.status_code == 201, r.text
    assert r.json()["route"] == "R1" and len(r.json()["ids"]) == 2, \
        "the repeated corner (a double-click's second click) is dropped"
    r2 = client.post(f"/api/projects/{pid}/routes/path",
                     json={"page": 2, "points": [[0, 0], [10, 0]]}).json()
    assert r2["route"] == "R2"
    rows = client.get(f"/api/projects/{pid}/routes").json()
    assert sorted({x["label"] for x in rows}) == ["R1", "R2"] and len(rows) == 3


def test_the_same_route_sent_twice_is_one_route(client):
    """A quick double-click fired two finishes; the interface test saw R3 and
    R4 drawn on top of each other."""
    pid = _project("route-twice")
    body = {"page": 1, "points": [[400, 400], [400, 450], [700, 450]]}
    a = client.post(f"/api/projects/{pid}/routes/path", json=body).json()
    b = client.post(f"/api/projects/{pid}/routes/path", json=body).json()
    assert b["route"] == a["route"] == "R1" and b["ids"] == a["ids"] and b.get("existing")
    assert len(client.get(f"/api/projects/{pid}/routes").json()) == 2
    # the same path on the other sheet is another route
    c = client.post(f"/api/projects/{pid}/routes/path", json={**body, "page": 2}).json()
    assert c["route"] == "R2"


def test_the_viewer_guards_the_finish_against_a_second_double_click():
    src = _viewer()
    body = src[src.index("const finishRoute"):src.index("const removeMeasure")]
    assert body.count("finishingRef.current") >= 4


@pytest.mark.parametrize("points", [[[0, 0]], [[5, 5], [5, 5]], [[0, 0], [1]]])
def test_a_route_needs_two_different_corners(client, points):
    pid = _project("route-bad")
    assert client.post(f"/api/projects/{pid}/routes/path",
                       json={"page": 1, "points": points}).status_code == 422


def test_a_route_is_taken_back_whole_or_one_segment(client):
    pid = _project("route-erase")
    r1 = client.post(f"/api/projects/{pid}/routes/path",
                     json={"page": 1, "points": [[0, 0], [10, 0], [10, 10], [0, 10]]}).json()
    r2 = client.post(f"/api/projects/{pid}/routes/path",
                     json={"page": 1, "points": [[50, 0], [60, 0]]}).json()
    assert client.delete(f"/api/projects/{pid}/routes/{r1['ids'][0]}").status_code == 204
    assert len(client.get(f"/api/projects/{pid}/routes").json()) == 3, "one segment only"
    assert client.delete(f"/api/projects/{pid}/routes/{r1['ids'][1]}?whole=true").status_code == 204
    left = client.get(f"/api/projects/{pid}/routes").json()
    assert [x["id"] for x in left] == r2["ids"], "R1 went whole, R2 stayed"
    actions = client.get(f"/api/projects/{pid}/audit").json()
    gone = [a for a in actions if a["action"] == "route.deleted"]
    assert gone and gone[0]["payload"].get("route") == "R1"


def _something_to_analyse(pid):
    """One TEAP space, its room and a NER beside it."""
    with SessionLocal() as db:
        p = db.get(Project, pid)
        did = p.drawings[0].id
        tf = TeapFile(project_id=pid, filename="t.xlsx", stored_path=f"{TMP}/t.xlsx", sha256="y" * 64)
        db.add(tf)
        db.flush()
        db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key="TST|A.001",
                         space_code="A.001", space_name="Room A", total_ports=2,
                         lines=[{"row": 1, "product": "Laptop", "code": "X", "qty": 2,
                                 "ports": 2, "rule": "A", "explanation": ""}]))
        db.add(DrawingSpace(project_id=pid, drawing_id=did, page=1, space_code="A.001",
                            name="Room A", x=100, y=100, confidence=0.9))
        db.add(Element(project_id=pid, drawing_id=did, page=1, kind="NER_NONCRITICAL",
                       label="NER 1", x=130, y=100, origin="manual", confidence=1.0,
                       confirmed=True))
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))


def test_the_viewer_reads_the_last_saved_analysis(client):
    pid = _project("analysis-latest")
    _something_to_analyse(pid)
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    assert client.get(f"/api/projects/{pid}/analysis").json() == {"analysed": False}
    assert client.post(f"/api/projects/{pid}/analyse").status_code == 200
    first = client.get(f"/api/projects/{pid}/analysis").json()
    assert first["analysed"] is True and first["stale"] is None
    assert "assignments" in first and "ner_load" in first
    assert first["analysed_at"].endswith("+00:00"), \
        "the time carries its zone, or a browser reads UTC as local time"
    time.sleep(0.05)
    assert client.post(f"/api/projects/{pid}/analyse").status_code == 200
    second = client.get(f"/api/projects/{pid}/analysis").json()
    assert second["analysed_at"] > first["analysed_at"], "the time of the last run"
    demand = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    assert demand["analysed_at"] == second["analysed_at"], \
        "Demand per space showed the scenario's first save as its last run"
    with SessionLocal() as db:
        sc = db.query(Scenario).filter_by(project_id=pid, name="As-Is").one()
        created = sc.created_at.isoformat()
    assert not second["analysed_at"].startswith(created[:23])

    # Something changed: the viewer says so.
    client.post(f"/api/projects/{pid}/routes/path", json={"page": 1, "points": [[0, 0], [5, 0]]})
    assert client.get(f"/api/projects/{pid}/analysis").json()["stale"]["changes"] >= 1


# ---------------------------------------------------------------------------
# The viewer's source
# ---------------------------------------------------------------------------

def _viewer() -> str:
    return open(os.path.join(ROOT, "frontend", "src", "pages", "Viewer.tsx"), encoding="utf-8").read()


def test_the_viewer_has_the_ruler_and_it_saves_nothing():
    src = _viewer()
    assert '"measure": "measure"' in src and '["measure"]' in src
    body = src[src.index("const finishMeasure"):src.index("const removeMeasure")]
    assert "api." not in body, "a measure is never sent to the server"
    assert "Clear measures" in src


def test_the_route_tool_ends_on_double_click_and_saves_one_path():
    src = _viewer()
    assert "api.createRoutePath(" in src
    assert re.search(r'tool === "route" && draft\.length >= 2', src)
    assert "api.deleteRoute(p.id, d.id, true)" in src


def test_coverage_became_run_analysis_and_reads_the_saved_run():
    src = _viewer()
    assert "api.latestAnalysis(" in src
    assert '{t("Coverage")}' not in src and '{t("Run analysis")}' in src
    assert "Run “Coverage”" not in src
