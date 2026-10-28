"""Re-running the matching must not throw away human decisions.

The step used to delete every match row and rebuild from scratch. Every
confirmation, every rejection and every room a person had chosen by hand went
with it. It is easy to miss because the rows come straight back — carrying the
automatic answer, unconfirmed — so on screen it reads as "the app is not saving
my work" rather than as a wipe.

The audit log is what showed it. On the VCC project, in fifteen minutes::

    04:07:06  match.decided   {"drawing_space_id": 253}
    04:08:27  matching.run                             ← gone
    04:09:59  match.decided   {"drawing_space_id": 253}
    04:10:12  matching.run                             ← gone again
    04:18:33  match.decided   {"drawing_space_id": 253}
    04:19:19  matching.run                             ← gone again

The same room, for the same row, six times.

The first fix snapshotted the decided rows just before the delete and wrote them
back afterwards. That is a *preservation*, and it holds only while nothing
disturbs the snapshot — a row the matcher stops reporting, a TEAP re-import, an
exception between the delete and the re-insert. When it fails it fails in the
same silent shape as the original bug.

So the decision no longer lives in the table that gets rebuilt. It is written on
the TEAP space at the moment it is given, and the matching step *reads* it.
These tests pin that: the association survives a re-run, survives the match rows
being wiped outright, and the row that carries it keeps its database id.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-rematch-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from sqlalchemy import delete, select                              # noqa: E402

from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Project,            # noqa: E402
                        SpaceMatchRow, TeapFile, TeapSpace)


@pytest.fixture(scope="module")
def db():
    init_db()
    with SessionLocal() as session:
        yield session


@pytest.fixture
def project(db):
    """A TEAP row whose code matches nothing, and two rooms on the drawing.

    The code is deliberately unmatchable so the matcher's own answer is "none".
    That is what makes the test sharp: if the human's choice survives, it can
    only be because it was stored, not because the matcher found it again.
    """
    p = Project(name=f"rematch-{os.urandom(4).hex()}")
    db.add(p)
    db.flush()
    d = Drawing(project_id=p.id, filename="x.pdf", stored_path="x.pdf",
                sha256="0" * 64, page_count=1)
    tf = TeapFile(project_id=p.id, filename="x.xlsx", stored_path="x.xlsx")
    db.add_all([d, tf])
    db.flush()
    rooms = [
        DrawingSpace(project_id=p.id, drawing_id=d.id, page=1,
                     space_code="PRS.007.05-01", name="Photo Position - Seat",
                     x=100.0, y=100.0),
        DrawingSpace(project_id=p.id, drawing_id=d.id, page=1,
                     space_code="PRS.001.02", name="Press Work Area",
                     x=200.0, y=200.0),
    ]
    teap = [
        # The real row from the screenshot: a placeholder code, matched by hand.
        TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key="PRS.DUM.099",
                  space_name="Main Photo Position - FOP", space_code="PRS.DUM.099",
                  total_ports=110.0, demand_type="general"),
        TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key="ZZZ.999",
                  space_name="Nothing Like This On The Sheet", space_code="ZZZ.999",
                  total_ports=1.0, demand_type="general"),
    ]
    db.add_all(rooms + teap)
    db.commit()
    return p, rooms, teap


def _rows(db, project):
    return {r.teap_space_id: r for r in db.execute(
        select(SpaceMatchRow).where(SpaceMatchRow.project_id == project.id)).scalars()}


def _decide(db, project, teap, **kw):
    """Decide, the way the screen decides: through the one function the route
    uses, so a test cannot pass by writing state the application never writes."""
    row = _rows(db, project)[teap.id]
    S.record_match_decision(db, row, **kw)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The association survives
# ---------------------------------------------------------------------------

def test_a_hand_picked_room_survives_a_re_run(db, project):
    """The exact sequence from the audit log: assign, re-run, still assigned."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id)

    S.run_matching(db, p)
    after = _rows(db, p)[teap[0].id]
    assert after.drawing_space_id == rooms[0].id, \
        "the room a person chose by hand was thrown away by the re-run"
    assert after.method == "manual"


def test_the_room_survives_without_being_confirmed_first(db, project):
    """Choosing is enough. Requiring a confirmation to make a choice durable
    would mean the half-finished review — which is what a review *is*, most of
    the time — is the case that loses work."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[1].id)
    assert _rows(db, p)[teap[0].id].confirmed is False

    S.run_matching(db, p)
    assert _rows(db, p)[teap[0].id].drawing_space_id == rooms[1].id


def test_the_room_survives_three_re_runs(db, project):
    """Marcelo re-ran it six times in one morning and re-picked the same room
    every time. Once is not the test; the loop is."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id)
    for _ in range(3):
        S.run_matching(db, p)
    assert _rows(db, p)[teap[0].id].drawing_space_id == rooms[0].id


def test_the_association_survives_the_match_rows_being_wiped(db, project):
    """The strongest form of the guarantee, and the reason it moved.

    Whatever happens to ``space_matches`` — a rebuild, a bad migration, a hand
    on the database — the answer a person gave is somewhere else and comes back.
    """
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id, confirmed=True)

    db.execute(delete(SpaceMatchRow).where(SpaceMatchRow.project_id == p.id))
    db.commit()
    assert _rows(db, p) == {}

    S.run_matching(db, p)
    after = _rows(db, p)[teap[0].id]
    assert after.drawing_space_id == rooms[0].id
    assert after.confirmed is True


def test_confirming_an_automatic_match_makes_it_durable_too(db, project):
    """A sign-off is a decision even when the matcher proposed the answer."""
    p, rooms, teap = project
    S.run_matching(db, p)
    row = _rows(db, p)[teap[0].id]
    row.drawing_space_id = rooms[1].id            # as if the matcher found it
    row.method = "fuzzy_name"
    db.commit()

    _decide(db, p, teap[0], confirmed=True)
    S.run_matching(db, p)
    after = _rows(db, p)[teap[0].id]
    assert after.drawing_space_id == rooms[1].id
    assert after.method == "fuzzy_name", \
        "confirming a fuzzy match must not relabel it as hand-picked"


def test_confirm_does_not_relabel_the_method_when_it_re_states_the_room(db, project):
    """The screen re-sends the room with the confirmation, so that a row cannot
    be signed off without recording what was signed off. That must not turn an
    automatic match into a manual one."""
    p, rooms, teap = project
    S.run_matching(db, p)
    row = _rows(db, p)[teap[0].id]
    row.drawing_space_id = rooms[0].id
    row.method = "base_code"
    db.commit()

    _decide(db, p, teap[0], drawing_space_id=rooms[0].id, confirmed=True)
    assert _rows(db, p)[teap[0].id].method == "base_code"


def test_a_confirmation_survives_a_re_run(db, project):
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id, confirmed=True)

    S.run_matching(db, p)
    after = _rows(db, p)[teap[0].id]
    assert after.confirmed is True, "a confirmation must not need to be given twice"
    assert after.confirmed_by == "user"


def test_a_rejection_survives_a_re_run(db, project):
    """Rejection matters as much: a space that is not on this drawing must not
    come back into the queue every time the step is run."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[1], rejected=True)

    S.run_matching(db, p)
    assert _rows(db, p)[teap[1].id].rejected is True


# ---------------------------------------------------------------------------
# What must still change
# ---------------------------------------------------------------------------

def test_an_undecided_row_still_takes_the_fresh_answer(db, project):
    """The other half. Locking everything would make the step useless — a row
    nobody has touched must pick up whatever the matcher now says."""
    p, rooms, teap = project
    S.run_matching(db, p)
    row = _rows(db, p)[teap[1].id]
    assert not row.confirmed and not row.rejected and row.method != "manual"
    row.reason = "stale text from an earlier run"
    db.commit()

    S.run_matching(db, p)
    assert _rows(db, p)[teap[1].id].reason != "stale text from an earlier run"


def test_clearing_the_room_hands_the_row_back_to_the_matcher(db, project):
    """Setting the dropdown back to "none" is itself a decision — to stop
    deciding. It must release the lock, or the row would be frozen on a choice
    the person has withdrawn."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id)
    _decide(db, p, teap[0], clear_room=True)

    S.run_matching(db, p)
    after = _rows(db, p)[teap[0].id]
    assert after.drawing_space_id is None
    assert after.method != "manual"
    t = db.get(TeapSpace, teap[0].id)
    assert t.locked_verdict is None


def test_un_rejecting_puts_the_space_back_in_the_queue(db, project):
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[1], rejected=True)
    _decide(db, p, teap[1], rejected=False)

    S.run_matching(db, p)
    assert _rows(db, p)[teap[1].id].rejected is False
    assert db.get(TeapSpace, teap[1].id).locked_verdict is None


# ---------------------------------------------------------------------------
# Row identity
# ---------------------------------------------------------------------------

def test_the_match_row_keeps_its_id_across_a_re_run(db, project):
    """SQLite recycles rowids after a bulk delete, so the old delete-and-insert
    handed each id to a different TEAP line on every run.

    That is not cosmetic. The screen holds the id of the row under the cursor;
    if the id moves, a click can decide a different space than the one being
    looked at, and the audit trail records the wrong one. Refreshing rows in
    place removes the whole class of problem.
    """
    p, rooms, teap = project
    S.run_matching(db, p)
    before = {k: v.id for k, v in _rows(db, p).items()}
    S.run_matching(db, p)
    after = {k: v.id for k, v in _rows(db, p).items()}
    assert before == after, \
        "match row ids moved between runs — a stale screen would patch the wrong row"


def test_the_run_reports_how_many_decisions_it_kept(db, project):
    """Silent preservation is nearly as bad as silent loss: the reviewer has to
    be able to see that their work is still there."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id, confirmed=True)

    out = S.run_matching(db, p)
    assert out["stats"].get("decisions_kept") == 1


def test_a_choice_whose_room_has_gone_is_released_and_counted(db, project):
    """Re-importing the drawing sets the room to NULL (the foreign key says so),
    leaving a lock that names a room nobody can look at any more.

    Carrying that forward would attach a sign-off to whatever the matcher picks
    next — a room the reviewer never saw. So it goes back into the queue, and
    the run says how many did.
    """
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id, confirmed=True)

    t = db.get(TeapSpace, teap[0].id)
    t.locked_drawing_space_id = None          # what the re-import leaves behind
    db.commit()

    out = S.run_matching(db, p)
    assert out["stats"].get("decisions_released_room_gone") == 1
    assert _rows(db, p)[teap[0].id].confirmed is False, \
        "a sign-off must not survive the room it was given for"
    assert db.get(TeapSpace, teap[0].id).locked_verdict is None


def test_a_rejection_needs_no_room_to_survive(db, project):
    """"This space is not on this drawing" stands on its own."""
    p, rooms, teap = project
    S.run_matching(db, p)
    _decide(db, p, teap[1], rejected=True)

    out = S.run_matching(db, p)
    assert _rows(db, p)[teap[1].id].rejected is True
    assert not out["stats"].get("decisions_released_room_gone")


# ---------------------------------------------------------------------------
# Remember is a separate act
# ---------------------------------------------------------------------------

def test_saving_the_association_writes_no_cross_project_rule(db, project):
    """The two were entangled: the association lived on the worklist row, and
    "Remember" was the only thing that made a pairing durable at all — so the
    safe local act and the one that reaches other venues were the same click.

    They are now separate. Choosing a room here must touch nothing outside this
    project.
    """
    from app.models import Alias
    p, rooms, teap = project
    before = db.execute(select(Alias)).scalars().all()
    S.run_matching(db, p)
    _decide(db, p, teap[0], drawing_space_id=rooms[0].id, confirmed=True)
    after = db.execute(select(Alias)).scalars().all()
    assert len(after) == len(before), \
        "choosing a room wrote a rule that applies to other venues"
