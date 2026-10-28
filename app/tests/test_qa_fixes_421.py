"""4.2.1 — the defects the QA pass of 16 Oct 2026 (night) found in 4.2.0 (D17–D24).

Every test names its defect. The QA report ("Parecer de QA — NER Analyzer
4.2.0") has the reproduction on the real projects; these hold the rule.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import threading

import pymupdf
from sqlalchemy import select

from tests.test_wireless_tie_250 import TMP, _ner, _project, client  # noqa: F401
from tests.test_multi_book_410 import _two_books
from tests.test_qa_fixes_420 import _live, _room_at, _symbol_at
from app import migrate
from app import ner_register as R
from app import services as S
from app.db import SessionLocal
from app.models import AuditLog, Drawing, Element, NerAsset, Project

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _remove_the_old_way(db, asset_id):
    """A NER removed before 2.18.1: the row removed, its markers deleted."""
    a = db.get(NerAsset, asset_id)
    R.soft_delete(db, db.get(Project, a.project_id), a,
                  reason="removed before 2.18.1", actor="tests")
    for e in list(db.execute(select(Element).where(Element.ner_asset_id == asset_id)).scalars()):
        db.delete(e)
    db.commit()


# ---------------------------------------------------------------------------
# D17 — a NER removed before its markers were kept stays removed by position
# ---------------------------------------------------------------------------

def test_d17_a_symbol_where_a_legacy_removed_ner_stood_creates_nothing(client):
    """A softball venue, 16 Oct 2026: NER34 removed on 8 Oct (no code, marker
    deleted) came back as NER_35.1 at 0 pt when Place NERs read its symbol."""
    pid, a, _b = _two_books("d17 legacy spot")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        dr = db.get(Drawing, a)
        assert S.adopt_drawn_rooms(db, p, dr, [_symbol_at(1, 300, 300)])["created"] == 1
        gone = _live(db, pid)[0]
        _remove_the_old_way(db, gone.id)
        assert not db.execute(select(Element).where(Element.ner_asset_id == gone.id)).first()
        st = S.adopt_drawn_rooms(db, p, dr, [_symbol_at(1, 300, 300)])
        assert st["created"] == 0 and st["on_removed_ner"] == 1
        assert _live(db, pid) == []
        # It now holds the spot by a hidden marker, as a 2.18.1 removal does.
        hidden = db.execute(select(Element).where(Element.ner_asset_id == gone.id)).scalars().all()
        assert len(hidden) == 1
        st2 = S.adopt_drawn_rooms(db, p, dr, [_symbol_at(1, 300, 300)])
        assert st2["created"] == 0 and _live(db, pid) == []
        assert len(db.execute(select(Element).where(Element.ner_asset_id == gone.id)).scalars().all()) == 1


def test_d17_a_label_or_a_code_within_12_m_of_the_removed_spot_is_that_room(client):
    pid, a, _b = _two_books("d17 label")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        dr = db.get(Drawing, a)
        S.adopt_drawn_rooms(db, p, dr, [_symbol_at(1, 500, 200)])
        _remove_the_old_way(db, _live(db, pid)[0].id)
        # 8 m away on a 1 m/unit sheet: the same room.
        st = S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 508, 200, "TEC.020-031")])
        assert st["created"] == 0 and st["on_removed_ner"] == 1


def test_d17_another_room_elsewhere_or_another_code_is_still_created(client):
    """A new room is still a new room: far from the removed spot, or with a code
    other than the one the removed room carried."""
    pid, a, b = _two_books("d17 new rooms")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        dr = db.get(Drawing, a)
        S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 100, 100, "TEC.020-001")])
        _remove_the_old_way(db, _live(db, pid)[0].id)
        far = S.adopt_drawn_rooms(db, p, dr, [_symbol_at(1, 700, 600)])
        other_code = S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 102, 100, "TEC.020-002")])
        other_book = S.adopt_drawn_rooms(db, p, db.get(Drawing, b), [_symbol_at(1, 100, 100)])
        assert far["created"] == 1 and other_code["created"] == 1 and other_book["created"] == 1


def test_d17_an_annotation_where_a_removed_ner_stood_is_not_placed(client):
    pid, a, _b = _two_books("d17 annotation")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        S.adopt_drawn_rooms(db, p, db.get(Drawing, a), [_symbol_at(2, 250, 250)])
        gone = _live(db, pid)[0]
        _remove_the_old_way(db, gone.id)
        assert S._removed_spot_near(db, p, a, 2, 255, 252).id == gone.id
        assert S._removed_spot_near(db, p, a, 1, 255, 252) is None
        assert S._removed_spot_near(db, p, a, 2, 600, 600) is None


def test_d17_a_ner_already_re_created_there_is_flagged_not_removed(client):
    pid, a, _b = _two_books("d17 flag")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        dr = db.get(Drawing, a)
        S.adopt_drawn_rooms(db, p, dr, [_symbol_at(1, 400, 400)])
        old = _live(db, pid)[0]
        _remove_the_old_way(db, old.id)
        # What 4.2.0 did: the same spot, a new NER.
        e = Element(project_id=pid, drawing_id=a, page=1, kind="NER_NONCRITICAL", label="NER",
                    x=400, y=400, origin="extracted", confidence=0.6, detection_method="drawing_room")
        db.add(e)
        db.flush()
        new = migrate._asset_from_element(db, e, {}, [old.display_name])
        new.origin = "drawing_room"
        e.ner_asset_id = new.id
        db.commit()
        # The dates are set, not left to the clock (4.2.2): on a Windows
        # laptop two calls in the same millisecond give the same time, and a
        # removal "at the same instant" as the creation is not "before" it —
        # the test failed 3 runs in 8 on the work laptop. In the real case the
        # two are days apart: VCC's NER34 was removed on 8 Oct, NER_35.1
        # created on 16 Oct.
        gone = db.get(NerAsset, old.id)
        gone.deleted_at = _dt.datetime(2026, 10, 8, 18, 0, tzinfo=_dt.timezone.utc)
        new.created_at = _dt.datetime(2026, 10, 16, 20, 59, tzinfo=_dt.timezone.utc)
        db.commit()
        # A NER created before the removal is not one the removal let back in.
        gone.deleted_at = _dt.datetime(2026, 10, 17, 9, 0, tzinfo=_dt.timezone.utc)
        db.commit()
        assert migrate.flag_resurrected_ners(db, p)["resurrected_ners_flagged"] == 0
        gone.deleted_at = _dt.datetime(2026, 10, 8, 18, 0, tzinfo=_dt.timezone.utc)
        db.commit()
        assert migrate.flag_resurrected_ners(db, p)["resurrected_ners_flagged"] == 1
        db.refresh(new)
        flags = [v for v in new.pending_validations if v.startswith("position: a removed NER stood here")]
        assert len(flags) == 1 and old.display_name in flags[0]
        # Idempotent: a second start does not add a second line.
        migrate.flag_resurrected_ners(db, p)
        db.refresh(new)
        assert len([v for v in new.pending_validations if v.startswith("position: a removed")]) == 1
        assert new.deleted_at is None


# ---------------------------------------------------------------------------
# D18 — one-book projects refuse a page past the end of the book
# ---------------------------------------------------------------------------

def test_d18_a_one_book_project_refuses_a_page_it_does_not_have(client):
    pid = _project("d18 one book")              # one book, one page
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 40, "kind": "NER_NONCRITICAL", "label": "GHOST", "x": 1, "y": 1})
    assert r.status_code == 404 and "has no page 40" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/verticals", json={
        "key": "S", "lower_page": 1, "lower_x": 1, "lower_y": 1,
        "upper_page": 44, "upper_x": 1, "upper_y": 1, "length_m": 5})
    assert r.status_code == 404
    with SessionLocal() as db:
        assert not db.execute(select(Element).where(Element.project_id == pid,
                                                    Element.label == "GHOST")).first()
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": "TER", "label": "TER OK", "x": 1, "y": 1})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# D19 — a PDF that opens with no page is refused
# ---------------------------------------------------------------------------

def test_d19_a_truncated_pdf_is_refused_and_not_kept(client, monkeypatch):
    from app import isolate
    from app.config import settings
    real = isolate.run

    def no_pages(target, *a, **kw):
        out = real(target, *a, **kw) if not target.endswith("extract_drawing") else None
        if out is None:
            class _E:  # what a truncated book reads as: no page, nothing on it
                page_count = 0
                spaces, elements, needs_ocr_pages, layer_names = [], [], [], []
            return _E()
        return out
    monkeypatch.setattr(isolate, "run", no_pages)
    pid = client.post("/api/projects", json={"name": "d19 truncated", "venue_code": "D19"}).json()["id"]
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    r = client.post(f"/api/projects/{pid}/drawings",
                    files={"file": ("truncated.pdf", data, "application/pdf")})
    assert r.status_code == 422 and "opens with no page" in r.json()["detail"]
    assert not list((settings.uploads_dir / f"project_{pid}").glob("truncated*"))
    assert client.get(f"/api/projects/{pid}").json()["drawings"] == []


# ---------------------------------------------------------------------------
# D20 / D22 — names stay unique on Restore and under two requests at once
# ---------------------------------------------------------------------------

def test_d20_restore_refuses_a_name_a_live_ner_has(client):
    pid = _project("d20 restore")
    a = _ner(pid, "NER_35.1", 100, 120)
    with SessionLocal() as db:
        first = db.get(Element, a).ner_asset_id
    assert client.post(f"/api/projects/{pid}/ners/{first}/remove", json={"reason": "x"}).status_code == 200
    b = _ner(pid, "NER_35.1", 400, 120)
    with SessionLocal() as db:
        second = db.get(Element, b).ner_asset_id
    r = client.post(f"/api/projects/{pid}/ners/{first}/restore")
    assert r.status_code == 409 and "rename that one first" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.get(NerAsset, first).deleted_at is not None
    # With the live one renamed, the restore goes through.
    assert client.post(f"/api/projects/{pid}/ners/{second}/rename", json={"name": "NER_36.1"}).status_code == 200
    assert client.post(f"/api/projects/{pid}/ners/{first}/restore").status_code == 200


def test_d22_two_renames_to_one_name_at_once_leave_one_name(client):
    pid = _project("d22 race")
    ids = []
    for i, x in enumerate((100, 300, 500)):
        e = _ner(pid, f"NER RACE {i}", x, 120)
        with SessionLocal() as db:
            ids.append(db.get(Element, e).ner_asset_id)
    results = []

    def go(aid):
        with SessionLocal() as db:
            p = db.get(Project, pid)
            a = db.get(NerAsset, aid)
            try:
                R.rename(db, p, a, "NER SAME", actor="tests")
                results.append("ok")
            except R.NameInUse:
                results.append("refused")
    threads = [threading.Thread(target=go, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "refused", "refused"]
    with SessionLocal() as db:
        assert len([a for a in _live(db, pid) if a.display_name == "NER SAME"]) == 1


# ---------------------------------------------------------------------------
# D21 / D23 / D24 — the audit and the evidence
# ---------------------------------------------------------------------------

def test_d21_the_start_up_matching_is_audited_as_system():
    src = (ROOT / "backend" / "app" / "migrate.py").read_text(encoding="utf-8")
    assert 'S.run_matching(db, project, actor="system")' in src


def test_d21_run_matching_records_the_actor_it_is_given(client):
    pid = _project("d21 actor")
    with SessionLocal() as db:
        try:
            S.run_matching(db, db.get(Project, pid), actor="system")
        except S.ValidationError:
            pass
        rows = db.execute(select(AuditLog).where(AuditLog.project_id == pid,
                                                 AuditLog.action == "matching.run")).scalars().all()
        assert all(r.actor == "system" for r in rows)


def test_d23_placing_again_adds_no_evidence_line(client):
    pid, a, _b = _two_books("d23 evidence")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        dr = db.get(Drawing, a)
        S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 100, 100, "TEC.020-011", critical=True)])
        asset = _live(db, pid)[0]
        # The marker says non-critical while the drawing says critical: a question.
        for e in asset.occurrences:
            e.kind = "NER_NONCRITICAL"
        db.commit()
        S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 100, 100, "TEC.020-011", critical=True)])
        db.refresh(asset)
        ev, pv = len(asset.classification_evidence), len(asset.pending_validations)
        for _ in range(3):
            S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 100, 100, "TEC.020-011", critical=True)])
        db.refresh(asset)
        assert (len(asset.classification_evidence), len(asset.pending_validations)) == (ev, pv)


def test_d24_deleting_a_project_leaves_a_trace_in_the_installation_log(client):
    pid = client.post("/api/projects", json={"name": "d24 gone", "venue_code": "D24"}).json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    with SessionLocal() as db:
        row = db.execute(select(AuditLog).where(AuditLog.project_id.is_(None),
                                                AuditLog.action == "project.deleted",
                                                AuditLog.entity_id == pid)).scalar_one()
        assert row.actor == "tester" and row.payload["name"] == "d24 gone"
    events = client.get("/api/admin/audit").json()
    assert any(e["action"] == "project.deleted" and e["entity_id"] == pid for e in events)
