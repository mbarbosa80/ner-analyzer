"""2.6.0 — the tiles are the filter on TEAP × drawing, and Undo takes a decision back.

Marcelo, 21 Sep 2026, on the matching screen: *"todas essas legendas poderiam
ser botões que filtrassem TEAP Spaces, Matched, Confirmed by you, etc… assim
eu poderia inclusive verificar coisas que eu mesmo já confirmei e
desconfirmar caso eu tenha feito algo errado."*

Two things had to be true on the server for that to be honest on the screen:

1. **"Confirmed by you" counts people, not the matcher.** An unambiguous
   exact code is confirmed by the matcher itself (confidence 0.98 against a
   0.95 threshold), with nobody named. Those rows must not be filed under
   "confirmed by you", or the tile the request was about would show rows he
   never touched.
2. **Undo returns the row to the matcher's answer, not to nothing.** A room
   chosen by hand overwrites the matcher's on the row; ``clear_room`` only
   emptied it. The answer is now kept beside the decision and Undo puts it
   back — the same room, the same method, confirmed only if the matcher
   would have confirmed it — so the next run changes nothing.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-undo-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/undo.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402

from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Page, Project,       # noqa: E402
                        SpaceMatchRow, TeapFile, TeapSpace)


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


def _project(name: str) -> int:
    """Four TEAP lines against a sheet that carries them in three ways.

    ``PRS.001`` — exact code on the sheet: the matcher confirms it itself.
    ``PRS.002`` — only the sub-indexed ``PRS.002.01`` is printed: base code,
                  waits for a person.
    ``PRS.003`` — same, base code.
    ``ZZZ.009`` — printed nowhere: no room found.
    ``NOP.001`` — zero ports: outside the study.
    """
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="x" * 64, page_count=1)
        db.add(d)
        db.flush()
        db.add(Page(drawing_id=d.id, number=1, width=1000, height=700,
                    metres_per_unit=200 * 0.0254 / 72, scale_label="1:200",
                    scale_source="detected", scale_confirmed=True))
        tf = TeapFile(project_id=p.id, filename="t.xlsx", stored_path=f"{TMP}/t.xlsx",
                      sha256="y" * 64)
        db.add(tf)
        db.flush()
        for code, name, ports in (("PRS.001", "Press conference room", 10.0),
                                  ("PRS.002", "Press office", 6.0),
                                  ("PRS.003", "Press store", 4.0),
                                  ("ZZZ.009", "Timing hut", 2.0),
                                  ("NOP.001", "Cleaning cupboard", 0.0)):
            db.add(TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key=f"TST|{code}",
                             space_code=code, space_name=name, total_ports=ports))
        db.add(DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="PRS.001",
                            name="Press conference room", x=100, y=100, confidence=0.9))
        db.add(DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="PRS.002.01",
                            name="Media office A", x=300, y=100, confidence=0.9))
        db.add(DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="PRS.003.01",
                            name="Media store B", x=500, y=100, confidence=0.9))
        db.add(DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="OTH.001",
                            name="Volunteer lounge", x=700, y=100, confidence=0.9))
        db.commit()
        return p.id


def _rows(client, pid) -> dict[str, dict]:
    return {m["teap_code"]: m
            for m in client.get(f"/api/projects/{pid}/matches?include_zero=true").json()}


def _space_id(client, pid, code) -> int:
    for s in client.get(f"/api/projects/{pid}/drawing-spaces").json():
        if s["space_code"] == code:
            return s["id"]
    raise AssertionError(code)


# ---------------------------------------------------------------------------
# 1. "Confirmed by you" counts people, not the matcher
# ---------------------------------------------------------------------------

def test_the_matcher_s_own_confirmation_is_told_apart_from_a_person_s(client):
    pid = _project("undo260-tiles")
    stats = client.post(f"/api/projects/{pid}/matching/run").json()["stats"]
    assert stats["matched"] == 3 and stats["unmatched_teap"] == 1
    assert stats["confirmed"] == 1, "the exact code is confirmed by the matcher"
    assert stats["confirmed_by_you"] == 0, "nobody has clicked anything"
    assert stats["confirmed_by_matcher"] == 1
    assert stats["needs_review"] == 2

    rows = _rows(client, pid)
    exact = rows["PRS.001"]
    assert exact["confirmed"] and exact["confirmed_by"] is None
    assert exact["undo_available"] is False, "nothing of yours to undo on it"
    assert exact["auto_ready"] is True
    base = rows["PRS.002"]
    assert base["drawing_space_id"] and not base["confirmed"]
    assert rows["NOP.001"]["in_scope"] is False

    # Confirm one base-code row: now it is yours, and only it.
    r = client.patch(f"/api/projects/{pid}/matches/{base['id']}",
                     json={"confirmed": True, "drawing_space_id": base["drawing_space_id"],
                           "justification": "reviewed"})
    assert r.status_code == 200
    stats = client.post(f"/api/projects/{pid}/matching/run").json()["stats"]
    assert stats["confirmed"] == 2
    assert stats["confirmed_by_you"] == 1
    assert stats["confirmed_by_matcher"] == 1
    rows = _rows(client, pid)
    assert rows["PRS.002"]["confirmed_by"] and rows["PRS.002"]["undo_available"] is True
    assert rows["PRS.001"]["confirmed_by"] is None and rows["PRS.001"]["undo_available"] is False


def test_the_tile_figures_add_up_two_ways(client):
    """What the screen counts from the rows must add up the way the labels
    say — matched + no room found + rejected = TEAP spaces; matched =
    by you + by the matcher + not yet confirmed — and the zero-port space is
    outside both sums."""
    pid = _project("undo260-sums")
    client.post(f"/api/projects/{pid}/matching/run")
    rows = [m for m in _rows(client, pid).values()]
    scoped = [m for m in rows if m["in_scope"] is not False]
    matched = [m for m in scoped if m["drawing_space_id"] and not m["rejected"]]
    unmatched = [m for m in scoped if not m["drawing_space_id"] and not m["rejected"]]
    rejected = [m for m in scoped if m["rejected"]]
    assert len(matched) + len(unmatched) + len(rejected) == len(scoped) == 4
    by_you = [m for m in matched if m["confirmed"] and m["confirmed_by"]]
    by_matcher = [m for m in matched if m["confirmed"] and not m["confirmed_by"]]
    pending = [m for m in matched if not m["confirmed"]]
    assert len(by_you) + len(by_matcher) + len(pending) == len(matched) == 3
    assert len([m for m in rows if m["in_scope"] is False]) == 1


# ---------------------------------------------------------------------------
# 2. Undo returns the row to the matcher's answer
# ---------------------------------------------------------------------------

def test_undo_returns_a_hand_picked_room_to_the_matcher_s_answer(client):
    pid = _project("undo260-undo-room")
    client.post(f"/api/projects/{pid}/matching/run")
    base = _rows(client, pid)["PRS.002"]
    proposed = base["drawing_space_id"]
    other = _space_id(client, pid, "OTH.001")

    # Pick the wrong room by hand, then confirm it.
    client.patch(f"/api/projects/{pid}/matches/{base['id']}",
                 json={"drawing_space_id": other, "justification": "room chosen"})
    client.patch(f"/api/projects/{pid}/matches/{base['id']}",
                 json={"confirmed": True, "drawing_space_id": other, "justification": "reviewed"})
    m = _rows(client, pid)["PRS.002"]
    assert m["drawing_space_id"] == other and m["confirmed"] and m["locked"] == "assigned"

    r = client.post(f"/api/projects/{pid}/matches/{base['id']}/undo",
                    json={"justification": "wrong room"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restored"] is True and body["note"] is None
    assert body["drawing_space_id"] == proposed, "the matcher's room is back"
    assert body["method"] == "base_code"
    assert body["confirmed"] is False, "a base-code match waits for a person again"

    m = _rows(client, pid)["PRS.002"]
    assert m["drawing_space_id"] == proposed and not m["confirmed"]
    assert m["locked"] is None and m["undo_available"] is False
    with SessionLocal() as db:
        t = db.execute(S.select(TeapSpace).where(TeapSpace.project_id == pid,
                                                 TeapSpace.space_code == "PRS.002")).scalar_one()
        assert t.locked_verdict is None and t.locked_drawing_space_id is None
        assert not t.locked_confirmed and t.locked_by is None

    # The next run agrees with Undo: nothing flips back.
    client.post(f"/api/projects/{pid}/matching/run")
    m = _rows(client, pid)["PRS.002"]
    assert m["drawing_space_id"] == proposed and not m["confirmed"] and m["locked"] is None


def test_undo_on_a_confirmed_exact_code_leaves_it_confirmed_by_the_matcher(client):
    """He confirms an exact-code row, then undoes: the row is no longer his,
    but the matcher would confirm it again at the next run — so Undo says so
    now rather than showing an "unconfirmed" the run would contradict."""
    pid = _project("undo260-undo-exact")
    client.post(f"/api/projects/{pid}/matching/run")
    exact = _rows(client, pid)["PRS.001"]
    client.patch(f"/api/projects/{pid}/matches/{exact['id']}",
                 json={"confirmed": True, "drawing_space_id": exact["drawing_space_id"],
                       "justification": "reviewed"})
    assert _rows(client, pid)["PRS.001"]["confirmed_by"]
    body = client.post(f"/api/projects/{pid}/matches/{exact['id']}/undo", json={}).json()
    assert body["confirmed"] is True and body["method"] == "exact_code"
    m = _rows(client, pid)["PRS.001"]
    assert m["confirmed"] and m["confirmed_by"] is None and m["locked"] is None


def test_undo_returns_a_rejection_to_the_matcher_s_answer(client):
    pid = _project("undo260-undo-reject")
    client.post(f"/api/projects/{pid}/matching/run")
    base = _rows(client, pid)["PRS.003"]
    proposed = base["drawing_space_id"]
    client.patch(f"/api/projects/{pid}/matches/{base['id']}",
                 json={"rejected": True, "justification": "not here"})
    m = _rows(client, pid)["PRS.003"]
    assert m["rejected"] and m["locked"] == "rejected"
    body = client.post(f"/api/projects/{pid}/matches/{base['id']}/undo", json={}).json()
    assert body["restored"] and body["drawing_space_id"] == proposed
    m = _rows(client, pid)["PRS.003"]
    assert not m["rejected"] and m["drawing_space_id"] == proposed and m["locked"] is None


def test_undo_on_a_row_the_matcher_could_not_place_goes_back_to_no_room(client):
    pid = _project("undo260-undo-none")
    client.post(f"/api/projects/{pid}/matching/run")
    row = _rows(client, pid)["ZZZ.009"]
    assert row["drawing_space_id"] is None
    other = _space_id(client, pid, "OTH.001")
    client.patch(f"/api/projects/{pid}/matches/{row['id']}",
                 json={"drawing_space_id": other, "justification": "room chosen"})
    assert _rows(client, pid)["ZZZ.009"]["drawing_space_id"] == other
    body = client.post(f"/api/projects/{pid}/matches/{row['id']}/undo", json={}).json()
    assert body["restored"] is True and body["drawing_space_id"] is None
    assert body["method"] == "none" and body["note"] is None
    assert _rows(client, pid)["ZZZ.009"]["drawing_space_id"] is None


def test_undo_with_nothing_of_yours_on_the_row_is_refused(client):
    pid = _project("undo260-undo-nothing")
    client.post(f"/api/projects/{pid}/matching/run")
    exact = _rows(client, pid)["PRS.001"]
    r = client.post(f"/api/projects/{pid}/matches/{exact['id']}/undo", json={})
    assert r.status_code == 409
    assert "nothing to undo" in r.json()["detail"]


def test_undo_on_a_row_from_before_this_version_says_to_run_the_matching(client):
    """A row last refreshed by 2.5.x carries no stored answer. Undo still
    releases the decision — that is the part that matters — and says, in a
    message the interface translates, that a run brings the answer back."""
    pid = _project("undo260-undo-old")
    client.post(f"/api/projects/{pid}/matching/run")
    base = _rows(client, pid)["PRS.002"]
    other = _space_id(client, pid, "OTH.001")
    client.patch(f"/api/projects/{pid}/matches/{base['id']}",
                 json={"drawing_space_id": other, "justification": "room chosen"})
    with SessionLocal() as db:  # what the column looks like before 2.6.0
        m = db.get(SpaceMatchRow, base["id"])
        m.auto_method = None
        m.auto_drawing_space_id = None
        db.commit()
    body = client.post(f"/api/projects/{pid}/matches/{base['id']}/undo", json={}).json()
    assert body["restored"] is False
    assert body["drawing_space_id"] is None
    assert body["note"] == S.UNDO_NEEDS_RUN
    m = _rows(client, pid)["PRS.002"]
    assert m["locked"] is None and m["drawing_space_id"] is None and m["auto_ready"] is False
    # …and the run does bring it back.
    client.post(f"/api/projects/{pid}/matching/run")
    m = _rows(client, pid)["PRS.002"]
    assert m["drawing_space_id"] == base["drawing_space_id"] and m["auto_ready"] is True


def test_undo_is_audited_with_what_was_taken_back(client):
    pid = _project("undo260-undo-audit")
    client.post(f"/api/projects/{pid}/matching/run")
    base = _rows(client, pid)["PRS.002"]
    client.patch(f"/api/projects/{pid}/matches/{base['id']}",
                 json={"confirmed": True, "drawing_space_id": base["drawing_space_id"],
                       "justification": "reviewed"})
    client.post(f"/api/projects/{pid}/matches/{base['id']}/undo",
                json={"justification": "clicked the wrong row"})
    audit = client.get(f"/api/projects/{pid}/audit").json()
    undone = [a for a in audit if a["action"] == "match.undone"]
    assert len(undone) == 1
    a = undone[0]
    assert a["justification"] == "clicked the wrong row"
    assert a["payload"]["teap_code"] == "PRS.002"
    assert a["payload"]["verdict"] == "assigned" and a["payload"]["confirmed"] is True
    assert a["payload"]["restored_matcher_answer"] is True
