"""A NER serves a space. A TER, an IDF and a COW are drawn and nothing else.

Marcelo, 2 Sep 2026:

    NER é algo editável, é a coisa mais importante e só linkamos NER com TEAP.
    TER precisa aparecer e ter posição confirmada, mas nunca será usada para
    atender espaço ou entra na lista de possibilidades. COW e IDF, só precisam
    aparecer […] basta constar no desenho […] mas só para efeitos visuais.

Two of those rooms were **not** being treated that way, and the failures were
quiet ones:

* **COW was in ``SERVING_KINDS``.** A temporary cabin that happened to be the
  nearest thing on the sheet could be handed a hundred permanent ports, and the
  coverage numbers would look fine.
* **TER, IDF and COW became register rows.** That put them in the NER register,
  in the consolidation queue, and — worst — in the "Served by" dropdown, where
  picking one was accepted by the server.

The line is held in four places, and this file checks all four, because three of
them are cosmetic and only the fourth actually refuses:

1. ``SERVING_KINDS`` — the engine will not assign one;
2. ``ASSET_KINDS`` — they never reach the register at all;
3. the API — ``/spaces/{key}/assign`` refuses a non-NER with a 422;
4. the reach circles — no radius is drawn for a room that cannot serve.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-serving-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/serving.sqlite3")

from fastapi.testclient import TestClient                         # noqa: E402

from app.db import SessionLocal, init_db                          # noqa: E402
from app.domain.coverage import (NER, SERVING_KINDS,              # noqa: E402
                                 compute_coverage)
from app.domain.distance import DemandType, DistanceRules, Status  # noqa: E402
from app.domain.geometry import Area, Point                       # noqa: E402
from app.domain.pdf_ingest import ElementKind                     # noqa: E402
from app.domain.units import Scale                                # noqa: E402
from app.main import app                                          # noqa: E402
from app.migrate import ASSET_KINDS                               # noqa: E402
from app.models import Criticality, Drawing, NerAsset, NerStatus, Project  # noqa: E402

RULES = DistanceRules()
SCALES = {1: Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)}


def area(key, x, y=0.0):
    return Area(key=key, name=key, page=1, label_point=Point(x, y, 1))


def room(key, kind, x, ports=96):
    return NER(key=key, label=key, kind=kind, point=Point(x, 0.0, 1),
               critical=(kind == ElementKind.NER_CRITICAL), total_ports=ports)


# ---------------------------------------------------------------------------
# 1. The engine
# ---------------------------------------------------------------------------

def test_only_the_two_ner_kinds_can_serve():
    assert SERVING_KINDS == {ElementKind.NER_CRITICAL, ElementKind.NER_NONCRITICAL}


@pytest.mark.parametrize("kind", [ElementKind.TER, ElementKind.IDF,
                                  ElementKind.COW, ElementKind.SHAFT])
def test_a_nearer_non_ner_never_takes_the_space(kind):
    """The one that matters: nearest wins, *among rooms that may serve*.

    The non-NER sits 5 m away and the NER 60 m away. Before this rule a COW at
    5 m won, and nothing on the sheet said the hundred ports had just been
    assigned to a temporary cabin.
    """
    res = compute_coverage(
        areas=[(area("A", 0), 10.0, DemandType.GENERAL, None, True)],
        ners=[room("X", kind, 5), room("N1", ElementKind.NER_NONCRITICAL, 60)],
        scale_for_page=SCALES, rules=RULES)
    got = res.assignments[0]
    assert got.ner_key == "N1", f"a {kind} took the space"
    assert got.status is Status.SERVED


@pytest.mark.parametrize("kind", [ElementKind.TER, ElementKind.IDF,
                                  ElementKind.COW, ElementKind.SHAFT])
def test_a_non_ner_never_appears_in_the_port_load(kind):
    """``ner_load`` is what the "NERs and ports" sheet is built from, so a room
    that cannot serve must not be a row on it — carrying 0 of 96 ports and
    reading, to anyone scanning the file, as spare capacity."""
    res = compute_coverage(
        areas=[(area("A", 0), 10.0, DemandType.GENERAL, None, True)],
        ners=[room("X", kind, 5), room("N1", ElementKind.NER_NONCRITICAL, 20)],
        scale_for_page=SCALES, rules=RULES)
    assert set(res.ner_load) == {"N1"}


def test_a_space_with_only_non_ners_near_it_is_reported_not_served():
    """And it says so rather than falling back on whatever is nearest."""
    res = compute_coverage(
        areas=[(area("A", 0), 10.0, DemandType.GENERAL, None, True)],
        ners=[room("T1", ElementKind.TER, 5), room("C1", ElementKind.COW, 8)],
        scale_for_page=SCALES, rules=RULES)
    got = res.assignments[0]
    assert got.ner_key is None
    assert got.status is Status.NOT_ANALYSABLE
    assert res.uncovered == ["A"]


# ---------------------------------------------------------------------------
# 2. The register
# ---------------------------------------------------------------------------

def test_only_ners_become_register_entries():
    """A TER is still extracted, drawn, renamed, moved and deleted — on the
    drawing. It is not a register row: there is nothing to classify about it,
    nothing to consolidate it with, and nothing for it to serve."""
    assert set(ASSET_KINDS) == {"NER_CRITICAL", "NER_NONCRITICAL"}


# ---------------------------------------------------------------------------
# 3. The API — the only one of the four that actually refuses
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


def test_the_api_refuses_to_let_a_ter_serve_a_space(client):
    """A register row of each kind, made directly.

    ``ASSET_KINDS`` stops these being created from markers now, but an older
    database can still hold one, and the guard has to hold for those too — a
    stale dropdown offering a TER is exactly the case this refuses.
    """
    from app.models import TeapFile, TeapSpace

    with SessionLocal() as db:
        p = Project(name="serving-guard", venue_code="SRV")
        db.add(p)
        db.flush()
        db.add(Drawing(project_id=p.id, filename="d.pdf", stored_path="/tmp/d.pdf",
                       sha256="x" * 64, page_count=1))
        tf = TeapFile(project_id=p.id, filename="teap.xlsx",
                      stored_path="/tmp/teap.xlsx", sha256="y" * 64)
        db.add(tf)
        db.flush()
        space = TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key="PRS.001",
                          space_name="Venue Media Centre", space_code="PRS.001",
                          total_ports=12.0)
        ter = NerAsset(project_id=p.id, code="NER-9001", display_name="TER 1",
                       kind=ElementKind.TER, status=NerStatus.IDENTIFIED,
                       classification=Criticality.NON_CRITICAL,
                       canonical_page=1, canonical_x=10.0, canonical_y=10.0)
        ner = NerAsset(project_id=p.id, code="NER-9002", display_name="NER 1",
                       kind=ElementKind.NER_NONCRITICAL, status=NerStatus.IDENTIFIED,
                       classification=Criticality.NON_CRITICAL,
                       canonical_page=1, canonical_x=20.0, canonical_y=10.0)
        db.add_all([space, ter, ner])
        db.commit()
        pid, ter_id, ner_id = p.id, ter.id, ner.id

    refused = client.post(f"/api/projects/{pid}/spaces/PRS.001/assign",
                          json={"ner_asset_id": ter_id, "justification": "nope"})
    assert refused.status_code == 422, refused.text
    assert "only a NER" in refused.json()["detail"]

    allowed = client.post(f"/api/projects/{pid}/spaces/PRS.001/assign",
                          json={"ner_asset_id": ner_id, "justification": "yes"})
    assert allowed.status_code == 200, allowed.text


# ---------------------------------------------------------------------------
# 4. What the screens offer
# ---------------------------------------------------------------------------

def _src(*parts) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return open(os.path.join(here, "..", "frontend", "src", *parts),
                encoding="utf-8").read()


def test_the_served_by_dropdown_filters_to_ners():
    """One definition of the room list. Coverage analysis folded into Demand
    per space on 3 Sep 2026; since 2.12.0 the Exceptions step offers the same
    list, through the same function, so the NER-only filter exists once."""
    panels = _src("pages", "panels.tsx")
    assert panels.count("canServe(n.kind)") == 1, \
        "the room list is filtered to NERs in one place only"
    assert panels.count("nerRoomOptions(ners)") == 2, \
        "Demand per space and Exceptions both offer rooms through nerRoomOptions"


def test_no_reach_circle_is_drawn_for_a_room_that_cannot_serve():
    """A 90 m ring around a TER promises a coverage it can never provide.

    Since 2.7.0 the element filter goes through ``drawsReach`` — a NER, or a
    NER *reference* on a key plan, which is drawn for its circles — and
    ``drawsReach`` is defined in notation.ts as ``canServe`` plus the
    reference kinds, nothing else."""
    viewer = _src("pages", "Viewer.tsx")
    notation = _src("lib", "notation.ts")
    assert 'elements.filter((e) => drawsReach(e.kind))' in viewer
    assert 'proposed.filter((a) => canServe(a.kind))' in viewer
    # …and since 2.8.0 only the *NER* references: a TER, COW or DIVA
    # reference has no circles, like the room it points at.
    assert "return canServe(kind) || (!!kind && NER_REFERENCE_KINDS.has(kind));" in notation
    # The radius filters must go through canServe, not through a local guess at
    # what a NER is. `kind.startsWith("NER")` still appears once, choosing the
    # default label text for a new marker, which is not a serving decision.
    assert 'e.kind.startsWith("NER")' not in viewer, \
        "one source of truth for what may serve, and it is notation.ts"


def test_the_viewer_can_place_every_kind_the_plan_needs():
    """He asked to be able to draw a TER, an IDF and a COW as well — visually.
    The DIVA node joined them on 3 Sep 2026."""
    viewer = _src("pages", "Viewer.tsx")
    for kind in ("TER", "IDF", "COW", "DIVA", "NER_CRITICAL", "NER_NONCRITICAL"):
        assert f'"{kind}"' in viewer, f"no tool places a {kind}"
    assert '"calibrate"' not in viewer and '"zone-' not in viewer, \
        "calibrate and the zone tools went on 3 Sep 2026"


# ---------------------------------------------------------------------------
# 5. The bug this file caught on its way in
# ---------------------------------------------------------------------------

def test_every_request_model_a_route_asks_for_actually_exists():
    """``AssignIn`` was deleted by accident and nothing noticed for a day.

    It went out with the ``/compare`` endpoint on the morning of 2 Sep: the cut
    ran from one decorator to the next and swallowed the model defined between
    them. FastAPI does not fail at import for that — a ``body:`` annotation it
    cannot resolve as a model quietly becomes a *query* parameter, so the route
    still starts, still serves, and answers every real call with

        {"loc": ["query", "body"], "msg": "Field required"}

    which is a 422 that looks like the caller's fault. **Choosing the NER that
    serves a space was broken in production for a day**, on both screens, and
    the only reason it surfaced is that a test in this file happened to POST to
    that endpoint.

    Two lessons, and this test is the second one: cutting between decorators is
    unsafe, and a request model is not covered by "the app imports".
    """
    import pathlib
    import re

    here = pathlib.Path(__file__).resolve().parents[1] / "backend" / "app" / "api"
    broken: list[str] = []
    for path in sorted(here.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        defined = set(re.findall(r"^class (\w+)\(BaseModel\)", src, flags=re.M))
        for used in set(re.findall(r"\bbody:\s*(\w+)\b", src)):
            if used not in defined:
                broken.append(f"{path.name}: body: {used} is not defined there")
    assert not broken, "\n  ".join(["a route asks for a model that is gone:"] + broken)
