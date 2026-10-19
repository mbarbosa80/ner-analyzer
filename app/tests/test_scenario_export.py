"""Exporting "Proposed" must draw the proposal, not the current state again.

A scenario is a snapshot — the assignments and the equipment rooms as they
stood when it was saved, proposed rooms included, each at the position it was
proposed at. The exporters ignored all of it and re-analysed the live project,
so asking for the Proposed drawing produced the As-Is drawing with a different
word in the legend. The two files came out identical apart from the title,
which is why putting them side by side showed nothing.

These tests pin the replay: what was saved is what is drawn.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-scenario-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from app import services as S                                    # noqa: E402
from app.db import SessionLocal, init_db                          # noqa: E402
from app.domain.coverage import NER, compute_coverage             # noqa: E402
from app.domain.distance import DemandType, DistanceRules         # noqa: E402
from app.domain.geometry import Point                             # noqa: E402
from app.domain.pdf_ingest import ElementKind                     # noqa: E402
from app.domain.units import Scale                                # noqa: E402
from app.models import (Drawing, DrawingSpace, Project,           # noqa: E402
                        SpaceMatchRow, TeapFile, TeapSpace)

RULES = DistanceRules()
SCALE = Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)

SPACE_X, SPACE_Y = 1900.0, 500.0


@pytest.fixture(scope="module")
def db():
    init_db()
    with SessionLocal() as session:
        yield session


@pytest.fixture
def project(db):
    """One project with one TEAP space matched to one room on the drawing.

    Built through the models rather than the API so the test stays about the
    replay, but through ``collect_areas`` all the same, because the position
    the export needs is exactly what that function supplies.
    """
    p = Project(name=f"scenario-replay-{os.urandom(4).hex()}")
    db.add(p)
    db.flush()
    d = Drawing(project_id=p.id, filename="x.pdf", stored_path="x.pdf",
                sha256="0" * 64, page_count=1)
    db.add(d)
    db.flush()
    tf = TeapFile(project_id=p.id, filename="x.xlsx", stored_path="x.xlsx")
    db.add(tf)
    db.flush()
    ds = DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="BRS.002",
                      name="Technical Operation Center", x=SPACE_X, y=SPACE_Y)
    ts = TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key="BRS.002",
                   space_name="Technical Operation Center",
                   space_code="BRS.002", total_ports=5.0, demand_type="general")
    db.add_all([ds, ts])
    db.flush()
    db.add(SpaceMatchRow(project_id=p.id, teap_space_id=ts.id, drawing_space_id=ds.id,
                         confirmed=True, score=100.0, method="exact_code"))
    db.commit()
    return p


def _proposed(x, y):
    return NER(key="PROP-1", label="NER 99 (proposed)", kind=ElementKind.NER_NONCRITICAL,
               point=Point(x, y, 1), critical=False, total_ports=100, proposed=True)


def _coverage(area, ner):
    return compute_coverage(areas=[(area, 5.0, DemandType.GENERAL, None, True)],
                            ners=[ner], scale_for_page={1: SCALE}, rules=RULES)


def _saved_scenario_view(db, project):
    """An As-Is run saved and read back, with a named critical room serving it."""
    area = _area(db, project)
    room = NER(key="A2", label="Critical NER 1", kind=ElementKind.NER_CRITICAL,
               point=Point(SPACE_X + 40, SPACE_Y, 1), critical=True, total_ports=100)
    S.save_scenario(db, project, "As-Is", "as_is", _coverage(area, room), [room])
    view = S.scenario_view(db, project, "As-Is")
    assert view is not None
    return view


def _area(db, project):
    areas = S.collect_areas(db, project)
    assert areas, "the fixture must produce one positioned space"
    return areas[0][0]


# ---------------------------------------------------------------------------

def test_an_unknown_scenario_falls_back_rather_than_failing(db, project):
    """No snapshot means a live analysis, not an error."""
    assert S.scenario_view(db, project, "No Such Scenario") is None


def test_a_saved_scenario_is_replayed_with_its_own_rooms(db, project):
    area = _area(db, project)
    prop = _proposed(SPACE_X + 3, SPACE_Y + 3)
    S.save_scenario(db, project, "Proposed", "proposed", _coverage(area, prop), [prop])

    view = S.scenario_view(db, project, "Proposed")
    assert view is not None, "a saved scenario must be replayable"
    replayed, ners = view
    assert [n.key for n in ners] == ["PROP-1"]
    assert ners[0].proposed is True, "the proposal flag decides how it is drawn"
    assert (ners[0].point.x, ners[0].point.y) == (SPACE_X + 3, SPACE_Y + 3), \
        "a proposed room must be drawn where it was proposed, not where it ended up"
    assert [a.space_key for a in replayed.assignments] == ["BRS.002"]
    assert replayed.assignments[0].area.label_point.x == SPACE_X, \
        "the space must carry a real position or the export cannot draw it"


def test_the_proposed_export_differs_from_the_as_is_one(db, project):
    """The symptom, stated directly: two scenarios, two different drawings."""
    area = _area(db, project)
    existing = NER(key="N1", label="NER 1", kind=ElementKind.NER_NONCRITICAL,
                   point=Point(SPACE_X + 200, SPACE_Y, 1), critical=False,
                   total_ports=100)
    prop = _proposed(SPACE_X + 3, SPACE_Y + 3)
    S.save_scenario(db, project, "As-Is", "as_is", _coverage(area, existing), [existing])
    S.save_scenario(db, project, "Proposed", "proposed", _coverage(area, prop), [prop])

    as_is, as_is_ners = S.scenario_view(db, project, "As-Is")
    proposed, prop_ners = S.scenario_view(db, project, "Proposed")
    assert [n.key for n in as_is_ners] != [n.key for n in prop_ners]
    assert as_is.assignments[0].ner_key != proposed.assignments[0].ner_key


def test_a_space_that_left_the_drawing_is_reported_not_invented(db, project):
    """A scenario records which space, never where. If a space has since been
    unmatched, the honest answer is to drop it and say so."""
    area = _area(db, project)
    prop = _proposed(SPACE_X + 3, SPACE_Y + 3)
    result = _coverage(area, prop)
    result.assignments[0].space_key = "GHOST"
    S.save_scenario(db, project, "Ghosts", "proposed", result, [prop])

    replayed, _ = S.scenario_view(db, project, "Ghosts")
    assert replayed.assignments == [], "a space with no position must not be drawn"
    assert any("no longer" in e["detail"] for e in replayed.exceptions), \
        "and the reviewer has to be told why it is missing"


def test_the_evaluation_survives_far_enough_to_label_the_leader_line(db, project):
    area = _area(db, project)
    prop = _proposed(SPACE_X + 3, SPACE_Y + 3)
    live = _coverage(area, prop)
    S.save_scenario(db, project, "Labelled", "proposed", live, [prop])
    replayed, _ = S.scenario_view(db, project, "Labelled")
    a = replayed.assignments[0]
    assert a.evaluation is not None
    assert a.evaluation.effective_distance_m == pytest.approx(
        live.assignments[0].evaluation.effective_distance_m)


# ---------------------------------------------------------------------------
# The Proposed scenario, as the optimiser actually stored it
#
# Five cases stood here, all of them about reading back the shape
# ``_store_optimisation`` wrote: that an optimisation scenario was drawable at
# all, that uncovered spaces were still drawn in a proposal, that the serving
# room was named rather than keyed, that its criticality reached the sheet, and
# that a solver-invented site got a readable name.
#
# There is no optimiser and no Proposed scenario now. A scenario stored in that
# shape by an earlier version is treated as having nothing to draw — ``None``
# from ``scenario_view`` — rather than being silently redrawn as the live state,
# which is the failure those cases were written to catch in the first place.
# ---------------------------------------------------------------------------

def test_the_workbook_names_the_room_and_says_whether_it_is_critical(db, project,
                                                                    tmp_path):
    """The two facts the first sheet exists to add to the TEAP.

    *Serving NER* used to hold an internal key on a proposed scenario — "A2",
    "grid-72-1" — which is a handle, not a room. And *NER critical* was blank on
    every row while a duplicate column two places along said "yes" about
    something else entirely. Both are checked here on the sheet that survived
    the workbook being cut back.
    """
    import openpyxl
    from app.domain.reports import export_workbook

    result, ners = _saved_scenario_view(db, project)

    class _D:
        def __init__(self, key):
            self.space_key, self.space_name, self.space_code = key, key, key
            self.total_ports, self.warnings, self.lines = 4.0, [], []

        def breakdown(self):
            return ["TOTAL = 4 port(s)"]

    out = str(tmp_path / "wb.xlsx")
    export_workbook(out, coverage=result, ners=ners,
                    demands=[_D(a.space_key) for a in result.assignments],
                    rules=RULES, project_name="test", scale_for_page={1: SCALE})

    ws = openpyxl.load_workbook(out)["TEAP and coverage"]
    headers = [c.value for c in ws[1]]
    assert "Serving NER" in headers and "NER critical" in headers
    assert "NER internal id" not in headers, \
        "the internal handle belongs in the register, not on a coverage row"
    assert "Criticality confirmed" not in headers, \
        "that header described the match, not the criticality, and said it twice"
    row = {h: ws.cell(row=2, column=i + 1).value for i, h in enumerate(headers)}
    assert row["Serving NER"] == "Critical NER 1", "the name, not the key"
    assert row["NER critical"] in ("yes", "no"), "this column was blank everywhere"
