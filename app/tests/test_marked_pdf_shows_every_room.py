"""The marked-up VDB has to show every room, served or not.

Two different documents come out of the same button, at two different moments.

Late in a study it is the analysis: rooms, coverage, distances, exceptions.
Early on it is the drawing — *"here are the racks I am proposing, put them in
front of the design team"* — and at that point there may be no TEAP, no matching
and nothing to compute. The exporter only ever built the first one. Asked for
the second it either refused outright ("no matched spaces to analyse") or, worse,
produced a sheet with the proposals silently missing, because the list it drew
was the list the coverage engine had counted.

That list is the wrong list for a picture. A proposal is deliberately kept out
of the As-Is numbers — it is not an approved room, and letting it serve spaces
would inflate the study. Keeping it out of the *picture* is a separate decision
and the wrong one: seeing it on the sheet is the entire reason for asking.

So the two are separated here, and these tests hold the separation: what the
engine counts is unchanged, what the exporter draws is every room that has a
position, and a sheet with no analysis behind it says so instead of letting an
absence of red areas read as full coverage.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-pdfdraw-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

import pymupdf                                                     # noqa: E402

from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain.coverage import CoverageResult                     # noqa: E402
from app.domain.distance import DistanceRules                      # noqa: E402
from app.domain.pdf_ingest import ElementKind                      # noqa: E402
from app.domain.reports import export_marked_pdf                   # noqa: E402
from app.domain.units import Scale                                 # noqa: E402
from app.models import (Criticality, Drawing, KeepDecision, NerAsset,  # noqa: E402
                        NerStatus, Project)

RULES = DistanceRules()
SCALES = {1: Scale(metres_per_unit=0.1, source="manual", label="1:100", confirmed=True)}


@pytest.fixture(scope="module")
def db():
    init_db()
    with SessionLocal() as session:
        yield session


@pytest.fixture
def project(db):
    p = Project(name=f"pdfdraw-{os.urandom(4).hex()}")
    db.add(p)
    db.flush()
    db.add(Drawing(project_id=p.id, filename="v.pdf", stored_path="v.pdf",
                   sha256="0" * 64, page_count=1))
    db.flush()
    return p


def asset(project, name, **kw):
    base = dict(project_id=project.id, code=f"NER-{os.urandom(3).hex()}",
                display_name=name, kind=ElementKind.NER_NONCRITICAL,
                classification=Criticality.NON_CRITICAL,
                status=NerStatus.IDENTIFIED, keep_decision=KeepDecision.UNDECIDED,
                canonical_page=1, canonical_x=200.0, canonical_y=300.0,
                position_known=True)
    base.update(kw)
    return NerAsset(**base)


def blank_pdf(path):
    doc = pymupdf.open()
    doc.new_page(width=800, height=600)
    doc.save(path)
    doc.close()
    return path


def marked(tmp_path, ners, *, coverage_available=True):
    src = blank_pdf(str(tmp_path / "src.pdf"))
    out = str(tmp_path / "out.pdf")
    export_marked_pdf(
        src, out,
        coverage=CoverageResult(assignments=[], ner_load={}, exceptions=[], uncovered=[]),
        ners=ners, scale_for_page=SCALES, rules=RULES,
        coverage_available=coverage_available)
    doc = pymupdf.open(out)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# What gets drawn
# ---------------------------------------------------------------------------

def test_a_proposal_is_drawn_even_though_the_engine_ignores_it(db, project):
    """The heart of it. ``register_ners`` leaves suggestions out so they cannot
    inflate the coverage figures; the exporter must still put them on paper."""
    db.add(asset(project, "NER 01", status=NerStatus.SUGGESTED))
    db.commit()
    counted = S.register_ners(db, project)
    assert [n.label for n in counted] == [], "a suggestion must not be counted"
    drawn = S.rooms_to_draw(db, project, counted)
    assert [n.label for n in drawn] == ["NER 01"], "but it must be drawn"
    assert drawn[0].proposed is True


def test_an_accepted_room_is_counted_and_not_drawn_twice(db, project):
    """Accepting it puts it in the analysis. It must not then appear in both
    lists and be stamped on the sheet on top of itself."""
    db.add(asset(project, "NER 02", status=NerStatus.IN_REVIEW,
                 keep_decision=KeepDecision.KEEP))
    db.commit()
    counted = S.register_ners(db, project)
    assert [n.label for n in counted] == ["NER 02"]
    assert S.rooms_to_draw(db, project, counted) == []


def test_a_room_with_no_position_is_not_drawn(db, project):
    """There is nowhere to draw it, and a marker invented for the sake of
    completeness is a lie on a construction document."""
    db.add(asset(project, "NER 06", status=NerStatus.SUGGESTED,
                 position_known=False, canonical_page=0))
    db.commit()
    assert S.rooms_to_draw(db, project, []) == []


def test_a_discarded_room_is_not_drawn(db, project):
    db.add(asset(project, "gone", status=NerStatus.SUGGESTED,
                 keep_decision=KeepDecision.REJECT))
    db.commit()
    assert S.rooms_to_draw(db, project, []) == []


def test_the_label_reaches_the_paper(db, project, tmp_path):
    """The whole request: see them in a VDB."""
    db.add(asset(project, "NER 01", status=NerStatus.SUGGESTED))
    db.add(asset(project, "NER 13", status=NerStatus.SUGGESTED))
    db.commit()
    text = marked(tmp_path, S.rooms_to_draw(db, project, []))
    assert "NER 01" in text and "NER 13" in text


def test_a_room_serving_nothing_is_still_drawn(db, project, tmp_path):
    """Stated as its own case because it is what was actually asked for: a rack
    that reaches no area yet is exactly the rack you need to show somebody."""
    db.add(asset(project, "serves nobody"))
    db.commit()
    text = marked(tmp_path, S.register_ners(db, project))
    assert "serves nobody" in text


# ---------------------------------------------------------------------------
# A sheet with no analysis behind it must say so
# ---------------------------------------------------------------------------

def test_a_sheet_without_coverage_says_there_is_none(tmp_path):
    """Silence would be read as "everything is covered": no red areas looks like
    a clean result rather than an absent one."""
    text = marked(tmp_path, [], coverage_available=False)
    assert "No coverage analysis on this sheet" in text
    assert "have not been matched" in text


def test_a_normal_sheet_does_not_carry_that_warning(tmp_path):
    text = marked(tmp_path, [], coverage_available=True)
    assert "No coverage analysis on this sheet" not in text


def test_the_disclaimer_survives_either_way(tmp_path):
    for available in (True, False):
        # Wrapped across lines in the legend box, so match a fragment of one.
        assert "does not replace engineering" in marked(
            tmp_path, [], coverage_available=available)


# ---------------------------------------------------------------------------
# The legend is optional — the statements on it are not
# ---------------------------------------------------------------------------

def legendless(tmp_path, **kw):
    src = blank_pdf(str(tmp_path / "src.pdf"))
    out = str(tmp_path / "nolegend.pdf")
    export_marked_pdf(
        src, out,
        coverage=CoverageResult(assignments=[], ner_load={}, exceptions=[], uncovered=[]),
        ners=[], scale_for_page=SCALES, rules=RULES, draw_legend=False, **kw)
    doc = pymupdf.open(out)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def test_turning_the_legend_off_drops_the_box(tmp_path):
    """The reason to want it: 320 points of white box over a dense CAD sheet."""
    text = legendless(tmp_path)
    assert "Area near the limit" not in text, "the swatch list is the box"
    assert "NER - redundancy candidate" not in text


def test_the_limits_and_the_scale_survive_it(tmp_path):
    """They are what every distance on the page was measured against. A marked
    sheet without them cannot be checked by the person who receives it."""
    text = legendless(tmp_path)
    assert "90 m general" in text and "70 m photographers" in text
    assert "1:100" in text


def test_the_disclaimer_survives_it(tmp_path):
    """The one line whose absence could do real harm. This document gets
    forwarded to people who were not in the room, and without it a marked-up
    plan can be mistaken for an approved engineering drawing."""
    assert "does not replace engineering" in legendless(tmp_path)


def test_the_no_coverage_warning_survives_it(tmp_path):
    """Otherwise turning off the legend would also turn off the difference
    between "nothing is out of limit" and "nothing was measured"."""
    text = legendless(tmp_path, coverage_available=False)
    assert "No coverage analysis on this sheet" in text


def test_the_scenario_is_still_named(tmp_path):
    """As-Is and Proposed produce sheets that look alike. Which one this is has
    to be readable off the paper, legend or no legend."""
    assert "As-Is" in legendless(tmp_path)
