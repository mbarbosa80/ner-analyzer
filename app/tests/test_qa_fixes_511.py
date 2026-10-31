"""5.1.1 — the defects the complementary QA of 5.1.0 (31 Oct 2026) found.

D34: a NER whose drawing a person took off a sheet was drawn back there by
*Place NERs from the drawing* when the sheet prints the NER's code away from
the released spot — and always when the drawing was deleted before 5.1.0,
whose audit line holds no position (an aquatics project, NERc_09.1).
D32: the refusal to move a NER drawn twice on ONE sheet spoke of sheets that
disagree and advised leaving a sheet off the map.
D33 (the order the 5.1.0 tests ran in) is fixed in ``test_qa_fixes_510.py``.
"""
from __future__ import annotations

from sqlalchemy import select

from tests.test_composite_map_500 import (CB, _map_point, _page_of, _place,  # noqa: F401
                                          _project_with_book, _wait, client)
from tests.test_qa_fixes_510 import _build, _code, _live
from app import migrate as MG
from app import services as S
from app import sheets as SH
from app.db import SessionLocal
from app.models import Drawing, Element, NerAsset, Project

CODE = "TEC.020-091"


def _markers(db, aid):
    return sorted((e.page, round(e.x, 1), round(e.y, 1)) for e in db.get(NerAsset, aid).occurrences
                  if e.scenario_id is None)


def _two_sheet_ner(client, tmp, name):
    """A NER read from its code on sheet (0, 0), then the same code on sheet
    (1, 1): one NER drawn on both."""
    pid, facts = _project_with_book(client, tmp, name, [("TST_400_TST_O.pdf", {})])
    did, f = next(iter(facts.items()))
    pa, pb = _page_of(f, (0, 0)), _page_of(f, (1, 1))
    with SessionLocal() as db:
        p, d = db.get(Project, pid), db.get(Drawing, did)
        st = S.adopt_drawn_rooms(db, p, d, [_code(pa, *CB.detail_to_pt(0, 0, 40, 40), CODE)])
        assert st["created"] == 1
        st = S.adopt_drawn_rooms(db, p, d, [_code(pb, *CB.detail_to_pt(1, 1, 150, 100), CODE)])
        assert st["same_code_other_page"] == 1 and st["created"] == 0
        a = next(a for a in _live(db, pid) if a.space_code == CODE)
        eb = next(e for e in a.occurrences if e.page == pb and e.scenario_id is None)
        return pid, did, f, pa, pb, a.id, eb.id


def test_d34_the_code_printed_elsewhere_on_the_sheet_does_not_draw_it_back(client, tmp_path):
    pid, did, f, pa, pb, aid, eb = _two_sheet_ner(client, tmp_path, "D34 code elsewhere")
    r = client.delete(f"/api/projects/{pid}/elements/{eb}?scope=marker")
    assert r.status_code == 204, r.text
    with SessionLocal() as db:
        p, d = db.get(Project, pid), db.get(Drawing, did)
        n = len(_live(db, pid))
        # The same code read 25 m from where the drawing was: 5.1.0 drew the
        # NER back on the sheet (same code on another sheet).
        st = S.adopt_drawn_rooms(db, p, d, [_code(pb, *CB.detail_to_pt(1, 1, 175, 100), CODE)])
        assert st["created"] == 0 and st["same_code_other_page"] == 0, st
        assert st["released_spot"] == 1, st
        assert len(_live(db, pid)) == n
        assert pb not in {m[0] for m in _markers(db, aid)}
        # The other sheet keeps its drawing.
        assert pa in {m[0] for m in _markers(db, aid)}


def _delete_before_510(db, pid, did, pb, aid, eb):
    """What 5.0.0 left after *Delete only this marker*: no marker, no spot,
    an audit line with the name and the sheet."""
    e = db.get(Element, eb)
    a = db.get(NerAsset, aid)
    db.delete(e)
    a.released_spots = None
    sh = SH.for_project(db, pid)
    S.audit(db, pid, "element.deleted", entity="element", entity_id=eb,
            payload={"label": a.display_name, "page": sh.key(did, pb), "scope": "marker"})
    db.commit()


def test_d34_a_deletion_made_before_510_keeps_the_whole_sheet(client, tmp_path):
    pid, did, f, pa, pb, aid, eb = _two_sheet_ner(client, tmp_path, "D34 before 5.1.0")
    with SessionLocal() as db:
        _delete_before_510(db, pid, did, pb, aid, eb)
        p, d = db.get(Project, pid), db.get(Drawing, did)
        out = MG.released_sheets_511(db, p)
        assert out == {"released_sheets_kept": 1}
        spots = db.get(NerAsset, aid).released_spots
        assert len(spots) == 1 and spots[0]["page"] == pb and spots[0]["x"] is None
        # Running again changes nothing.
        assert MG.released_sheets_511(db, p) == {}
        # The room's own code, where it was drawn: not drawn back, no new NER.
        n = len(_live(db, pid))
        st = S.adopt_drawn_rooms(db, p, d, [_code(pb, *CB.detail_to_pt(1, 1, 150, 100), CODE)])
        assert st["created"] == 0 and st["same_code_other_page"] == 0, st
        assert st["released_spot"] == 1
        assert pb not in {m[0] for m in _markers(db, aid)}
        assert len(_live(db, pid)) == n
        # A NER without a code elsewhere on that sheet is still a new NER.
        st = S.adopt_drawn_rooms(db, p, d, [_code(pb, *CB.detail_to_pt(1, 1, 120, 60), "TEC.020-092")])
        assert st["created"] == 1


def test_d34_the_pass_leaves_alone_what_it_cannot_tell(client, tmp_path):
    pid, did, f, pa, pb, aid, eb = _two_sheet_ner(client, tmp_path, "D34 ambiguous")
    with SessionLocal() as db:
        _delete_before_510(db, pid, did, pb, aid, eb)
        p = db.get(Project, pid)
        a = db.get(NerAsset, aid)
        # The drawing was put back on that sheet by hand afterwards: it wins.
        back = Element(project_id=pid, drawing_id=did, page=pb, kind=a.kind, label=a.display_name,
                       x=10, y=10, origin="manual", ner_asset_id=aid)
        db.add(back)
        db.commit()
        assert MG.released_sheets_511(db, p) == {}
        db.delete(back)
        db.commit()
        # Two NERs carry the name now: which one was it? Nothing is kept.
        twin = NerAsset(project_id=pid, code="NER-9999", display_name=a.display_name, kind=a.kind,
                        classification=a.classification)
        db.add(twin)
        db.commit()
        assert MG.released_sheets_511(db, p) == {}
        assert not db.get(NerAsset, aid).released_spots


def test_d32_drawn_twice_on_one_sheet_says_so(client, tmp_path):
    pid, did, f, mid, ids = _build(client, tmp_path, "D32 twice", [
        ("NER_70.1", (1, 1), (150, 100), None), ("NER_70.1", (1, 1), (156, 100), "NER_70.1")])
    p11 = _page_of(f, (1, 1))
    X, Y = _map_point(mid, p11, (1, 1), (160, 100))
    for preview in (True, False):
        r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                        json={"asset_id": ids["NER_70.1"], "x": X, "y": Y, "preview": preview})
        assert r.status_code == 422
        msg = r.json()["detail"]
        assert "drawn twice on the same sheet" in msg and "6.0 m apart" in msg
        assert "Delete only this marker" in msg
        assert "leave it off the map" not in msg and "sheets disagree" not in msg


def test_d32_two_sheets_that_disagree_keep_their_message(client, tmp_path):
    pid, did, f, mid, ids = _build(client, tmp_path, "D32 two sheets", [
        ("NER_80.1", (0, 0), (102, 30), None), ("NER_80.1", (1, 0), (105, 30), "NER_80.1")])
    p0 = _page_of(f, (0, 0))
    X, Y = _map_point(mid, p0, (0, 0), (100, 32))
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": ids["NER_80.1"], "x": X, "y": Y})
    assert r.status_code == 422
    assert "sheets disagree" in r.json()["detail"]
