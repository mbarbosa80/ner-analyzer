"""The drawing viewer has to show everything, inherited and proposed.

For as long as every NER came from the sheet, drawing the extractor's markers
*was* the whole picture. It stopped being the whole picture the moment the
register could hold a room the sheet does not — a solver suggestion, or a
proposal read from a comments tracker. Those are real rows with real positions,
and they were invisible on the one screen where position is the point. A venue
whose VDB carries no NER at all showed an empty plan however much work had gone
into the register.

Two things have to stay true, and they pull in opposite directions:

* everything with a position is offered to the viewer, whatever produced it;
* nothing without a position is given one, and the count of those is reported
  rather than quietly dropped — otherwise the plan under-reports the work and
  the omission is invisible.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-viewer-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from app.api.routes import ner_asset_positions                    # noqa: E402
from app.db import SessionLocal, init_db                          # noqa: E402
from app.domain.pdf_ingest import ElementKind                     # noqa: E402
from app.models import (Criticality, Drawing, Element, KeepDecision,  # noqa: E402
                        NerAsset, NerStatus, Project)


@pytest.fixture(scope="module")
def db():
    init_db()
    with SessionLocal() as session:
        yield session


@pytest.fixture
def project(db):
    p = Project(name=f"viewer-{os.urandom(4).hex()}")
    db.add(p)
    db.flush()
    d = Drawing(project_id=p.id, filename="v.pdf", stored_path="v.pdf",
                sha256="0" * 64, page_count=3)
    db.add(d)
    db.flush()
    return p, d


def asset(project, **kw):
    base = dict(project_id=project.id, code=f"NER-{os.urandom(2).hex()}",
                display_name="a room", kind=ElementKind.NER_NONCRITICAL,
                classification=Criticality.NON_CRITICAL,
                status=NerStatus.IDENTIFIED, keep_decision=KeepDecision.UNDECIDED,
                canonical_page=1, canonical_x=10.0, canonical_y=20.0,
                position_known=True)
    base.update(kw)
    return NerAsset(**base)


def positions(db, project, page=None):
    return ner_asset_positions(project.id, page=page, db=db)


# ---------------------------------------------------------------------------

def test_a_proposal_with_a_position_reaches_the_viewer(db, project):
    """The bug this file exists for. A room the register holds and the sheet
    does not was drawn nowhere at all."""
    p, _ = project
    db.add(asset(p, display_name="NER 01", status=NerStatus.SUGGESTED,
                 origin="imported", position_source="tracker"))
    db.commit()
    out = positions(db, p)
    assert [r["name"] for r in out["positions"]] == ["NER 01"]
    assert out["positions"][0]["proposed"] is True
    assert out["positions"][0]["on_drawing"] is False


def test_a_room_the_drawing_already_shows_is_flagged_as_such(db, project):
    """It still comes back — the register's view is the whole register — but
    flagged, because the viewer already draws it as a marker and drawing it
    twice would double it by eye."""
    p, d = project
    a = asset(p, display_name="NER 02")
    db.add(a)
    db.flush()
    db.add(Element(project_id=p.id, drawing_id=d.id, page=1, x=10.0, y=20.0,
                   kind=ElementKind.NER_NONCRITICAL, label="NER 02",
                   ner_asset_id=a.id))
    db.commit()
    row = next(r for r in positions(db, p)["positions"] if r["name"] == "NER 02")
    assert row["on_drawing"] is True


def test_a_proposal_with_no_position_is_counted_never_placed(db, project):
    """The line. A rack drawn at the corner of page one is worse than a gap,
    and a gap nobody is told about is worse than both."""
    p, _ = project
    db.add(asset(p, display_name="NER 06", status=NerStatus.SUGGESTED,
                 position_known=False, position_source="unplaced",
                 canonical_page=0, canonical_x=0.0, canonical_y=0.0,
                 pending_validations=["the space is not on this drawing set yet"]))
    db.commit()
    out = positions(db, p)
    assert [r["name"] for r in out["positions"]] == []
    assert out["unplaced_count"] == 1
    assert out["unplaced"][0]["name"] == "NER 06"
    assert "not on this drawing set" in out["unplaced"][0]["why"]


def test_an_unplaced_row_is_reported_whatever_page_is_being_viewed(db, project):
    """It belongs to no page, so filtering by page must not hide it — the count
    is about the study, not about the sheet on screen."""
    p, _ = project
    db.add(asset(p, display_name="NER 07", status=NerStatus.SUGGESTED,
                 position_known=False, canonical_page=0))
    db.commit()
    for page in (1, 2, 3):
        assert positions(db, p, page=page)["unplaced_count"] == 1


def test_the_page_filter_still_applies_to_placed_rooms(db, project):
    p, _ = project
    db.add(asset(p, display_name="on one", canonical_page=1))
    db.add(asset(p, display_name="on two", canonical_page=2))
    db.commit()
    assert [r["name"] for r in positions(db, p, page=2)["positions"]] == ["on two"]


def test_a_discarded_proposal_is_not_drawn(db, project):
    """Rejecting it is a decision, and the plan has to stop showing it."""
    p, _ = project
    db.add(asset(p, display_name="discarded", status=NerStatus.SUGGESTED,
                 keep_decision=KeepDecision.REJECT))
    db.add(asset(p, display_name="deleted", deleted_at=__import__("datetime")
                 .datetime.utcnow()))
    db.commit()
    names = [r["name"] for r in positions(db, p)["positions"]]
    assert "discarded" not in names and "deleted" not in names


def test_the_row_carries_what_the_viewer_needs_to_explain_it(db, project):
    """Clicking a proposed room must answer "why is this here" without leaving
    the screen. A dashed circle with no account behind it is not evidence."""
    p, _ = project
    db.add(asset(p, display_name="NER 01", status=NerStatus.SUGGESTED,
                 kind=ElementKind.NER_CRITICAL, space_name="A Technical Operation Center",
                 space_code="BRS.002",
                 suggestion={"comment": "MB- Critical NER to be located inside..."},
                 pending_validations=["a lockable rack position"]))
    db.commit()
    r = positions(db, p)["positions"][0]
    assert r["critical"] is True
    assert r["space_name"] == "A Technical Operation Center"
    assert r["why"].startswith("MB- Critical NER")
    assert r["pending_validations"] == ["a lockable rack position"]


# ---------------------------------------------------------------------------
# Moving a room the sheet does not carry
# ---------------------------------------------------------------------------

def move(db, project, ner_id, **kw):
    from app.api.routes import NerPositionIn, move_ner_asset
    return move_ner_asset(project.id, ner_id, NerPositionIn(**kw), db=db)


def test_an_accepted_proposal_is_drawn_as_part_of_the_design(db, project):
    """Accepting it changes what it is. It stops being a dashed proposal and
    becomes a room — and the plan has to say so, or the two states look alike."""
    p, _ = project
    a = asset(p, display_name="NER 01", status=NerStatus.IN_REVIEW,
              keep_decision=KeepDecision.KEEP, origin="imported")
    db.add(a)
    db.commit()
    row = positions(db, p)["positions"][0]
    assert row["proposed"] is False, "an accepted room is no longer a proposal"
    assert row["on_drawing"] is False, "and the sheet still does not carry it"


def test_a_room_with_no_marker_can_be_moved(db, project):
    """The gap this closes. A room off the sheet is moved by dragging its
    marker; a room the sheet does not carry had no marker and so no way to move
    at all. A part of the design you cannot reposition is not much of a design.
    """
    p, _ = project
    a = asset(p, display_name="NER 01", status=NerStatus.IN_REVIEW,
              position_source="tracker")
    db.add(a)
    db.flush()
    move(db, p, a.id, page=2, x=500.0, y=600.0)
    db.refresh(a)
    assert (a.canonical_page, a.canonical_x, a.canonical_y) == (2, 500.0, 600.0)


def test_moving_it_stops_it_claiming_the_trackers_position(db, project):
    """The row said "this is where the tracker put it". After a hand move that
    is no longer true, and the record has to follow the fact."""
    p, _ = project
    a = asset(p, display_name="NER 01", position_source="tracker")
    db.add(a)
    db.flush()
    move(db, p, a.id, page=1, x=1.0, y=2.0)
    db.refresh(a)
    assert a.position_source == "manual"


def test_placing_an_unplaced_proposal_answers_its_open_question(db, project):
    """Its outstanding validation was "this has no room yet". Dragging it onto
    the plan is the answer, so the validation goes — leaving it open would make
    the register ask a question it can see has been settled."""
    p, _ = project
    a = asset(p, display_name="NER 06", status=NerStatus.SUGGESTED,
              position_known=False, position_source="unplaced", canonical_page=0,
              pending_validations=["the space this NER is to sit in is not on "
                                   "this drawing set yet — it must be shown first",
                                   "a lockable rack position with power"])
    db.add(a)
    db.flush()
    move(db, p, a.id, page=3, x=10.0, y=10.0)
    db.refresh(a)
    assert a.position_known is True
    assert a.pending_validations == ["a lockable rack position with power"], \
        "the room question is answered; the rack question is not"


def test_a_locked_room_refuses_to_move(db, project):
    """That is what the lock is for."""
    from fastapi import HTTPException
    p, _ = project
    a = asset(p, display_name="locked one", locked=True)
    db.add(a)
    db.flush()
    with pytest.raises(HTTPException) as e:
        move(db, p, a.id, page=1, x=9.0, y=9.0)
    assert "locked" in str(e.value.detail)
    db.refresh(a)
    assert (a.canonical_x, a.canonical_y) == (10.0, 20.0)


def test_the_move_is_recorded(db, project):
    """Every position in the register has to be accountable, and a position a
    person dragged is accounted for by saying who dragged it and from where."""
    from sqlalchemy import select as _select
    from app.models import AuditLog
    p, _ = project
    a = asset(p, display_name="NER 01", canonical_x=10.0, canonical_y=20.0)
    db.add(a)
    db.flush()
    move(db, p, a.id, page=1, x=77.0, y=88.0, reason="moved off the panel wall")
    row = db.execute(_select(AuditLog).where(AuditLog.project_id == p.id,
                                             AuditLog.action == "ner.moved")
                     .order_by(AuditLog.id.desc())).scalars().first()
    assert row is not None
    assert row.payload["from"]["x"] == 10.0 and row.payload["to"]["x"] == 77.0
    assert "panel wall" in row.justification


def test_the_viewer_is_told_whether_it_may_drag(db, project):
    p, _ = project
    db.add(asset(p, display_name="free", locked=False))
    db.add(asset(p, display_name="pinned", locked=True))
    db.commit()
    by = {r["name"]: r for r in positions(db, p)["positions"]}
    assert by["free"]["locked"] is False and by["pinned"]["locked"] is True
