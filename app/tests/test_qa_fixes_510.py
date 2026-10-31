"""5.1.0 — the defects the QA pass of 31 Oct 2026 found in 5.0.0 (D25–D30).

Every test names its defect and fails on 5.0.0. The QA report ("Parecer de QA
— NER Analyzer 5.0.0") has the reproduction on the real projects; these hold
the rule on the invented book of ``composite_book.py``.
"""
from __future__ import annotations

import datetime as _dt
import math
import threading

import pymupdf
import pytest
from sqlalchemy import select

from tests.test_composite_map_500 import (CB, _map_point, _page_of, _place,  # noqa: F401
                                          _project_with_book, _wait, client)
from app import composite_service as CS
from app import migrate as MG
from app import services as S
from app.db import SessionLocal
from app.domain.drawn_rooms import DrawnRoom
from app.models import AuditLog, CompositeMap, Drawing, Element, NerAsset, Project


def _symbol(page, x, y):
    return DrawnRoom(page=page, x=x, y=y, label_x=x, label_y=y, critical=None, code=None,
                     source="symbol", text="NER", via_leader=False)


def _code(page, x, y, code):
    return DrawnRoom(page=page, x=x, y=y, label_x=x, label_y=y, critical=False, code=code,
                     source="code", text=f"Network Equipment Rack {code}", via_leader=False)


def _live(db, pid):
    return [a for a in db.execute(select(NerAsset).where(NerAsset.project_id == pid)).scalars()
            if a.deleted_at is None and a.merged_into_id is None]


def _build(client, tmp, name, placements):
    """A project with the invented book, the NERs given, and its map built."""
    pid, facts = _project_with_book(client, tmp, name, [("TST_400_TST_O.pdf", {})])
    did, f = next(iter(facts.items()))
    made = {}
    for label, zone, site, same in placements:
        r = _place(client, pid, did, f, zone, site, label,
                   same_as=made[same]["ner_asset_id"] if same else None)
        made.setdefault(label, r)
    j = _wait(client, client.post(f"/api/projects/{pid}/composite/build",
                                  json={"drawing_id": did}).json()["job_id"])
    assert j["state"] == "done", j
    mid = client.get(f"/api/projects/{pid}/composite").json()["books"][0]["groups"][0]["map"]["id"]
    return pid, did, f, mid, {k: v["ner_asset_id"] for k, v in made.items()}


@pytest.fixture
def moved(client, tmp_path_factory):
    """NER_20.1 drawn on sheet (0, 0) only, moved across the map onto (2, 2):
    the drawing on (0, 0) is taken off, one is drawn on (2, 2).

    One project per test (5.1.1, D33): with a module-scoped project the Undo
    test put the drawing back for every test that ran after it, so the result
    depended on the order the tests ran in."""
    tmp = tmp_path_factory.mktemp("d25")
    pid, did, f, mid, ids = _build(client, tmp, f"D25 moved {tmp.name}", [
        ("NER_20.1", (0, 0), (60, 60), None), ("NER_21.1", (3, 2), (350, 160), None)])
    p0, p22 = _page_of(f, (0, 0)), _page_of(f, (2, 2))
    X, Y = _map_point(mid, p22, (2, 2), (250, 160))
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": ids["NER_20.1"], "x": X, "y": Y})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["moved"] == [] and len(out["removed"]) == 1 and out["created"]
    return {"pid": pid, "did": did, "f": f, "mid": mid, "ids": ids, "p0": p0, "p22": p22,
            "old": CB.detail_to_pt(0, 0, 60, 60), "undo": out["undo_id"]}


# ---------------------------------------------------------------------------
# D25 — a drawing taken off a sheet is not created again as a new NER
# ---------------------------------------------------------------------------

def test_d25_place_ners_after_a_move_takes_the_room_left_behind_as_the_same_ner(moved):
    pid, did = moved["pid"], moved["did"]
    x, y = moved["old"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        before = {a.id for a in _live(db, pid)}
        a = db.get(NerAsset, moved["ids"]["NER_20.1"])
        assert a.released_spots and a.released_spots[0]["page"] == moved["p0"]
        # The NER block symbol the sheet prints where NER_20.1 was drawn: 5.0.0
        # made a new NER of it (a port project's NER_38.1, an arena project's NER_43.1).
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did), [_symbol(moved["p0"], x + 3, y)])
        db.commit()
        assert st["created"] == 0 and st["released_spot"] == 1, st
        assert {a.id for a in _live(db, pid)} == before
        # Nothing is drawn back on the sheet the person took it off.
        a = db.get(NerAsset, moved["ids"]["NER_20.1"])
        assert [e.page for e in a.occurrences if e.scenario_id is None] == [moved["p22"]]
        # Again: the same answer, nothing added twice.
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did), [_symbol(moved["p0"], x + 3, y)])
        db.commit()
        assert st["created"] == 0 and st["released_spot"] == 1
        ev = [v for v in db.get(NerAsset, a.id).classification_evidence if "taken off" in v]
        assert len(ev) == 1


def test_d25_a_new_room_elsewhere_on_that_sheet_is_still_a_new_ner(moved):
    pid, did = moved["pid"], moved["did"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        n = len(_live(db, pid))
        x, y = CB.detail_to_pt(0, 0, 10, 10)          # 50 m from the released spot
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did), [_symbol(moved["p0"], x, y)])
        db.commit()
        assert st["created"] == 1
        assert len(_live(db, pid)) == n + 1


def test_d25_a_coded_room_at_the_spot_is_neither_a_new_ner_nor_drawn_back(moved):
    pid, did = moved["pid"], moved["did"]
    x, y = moved["old"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        n = len(_live(db, pid))
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did),
                                 [_code(moved["p0"], x - 2, y + 1, "TEC.020-077")])
        db.commit()
        assert st["created"] == 0 and st["released_spot"] == 1
        assert len(_live(db, pid)) == n
        a = db.get(NerAsset, moved["ids"]["NER_20.1"])
        assert moved["p0"] not in {e.page for e in a.occurrences if e.scenario_id is None}


def test_d25_place_ners_annotations_respect_the_released_spot(moved, client):
    """The whole Place NERs pass, with a team annotation written where the
    drawing was taken off."""
    pid, did = moved["pid"], moved["did"]
    x, y = moved["old"]
    with SessionLocal() as db:
        d = db.get(Drawing, did)
        s = dict(d.extract_summary or {})
        s["ner_annotations"] = [{"page": moved["p0"], "x": x + 1, "y": y + 1, "kind": "NER_NONCRITICAL",
                                 "label": "NER 20", "number": 20, "confidence": 0.9, "evidence": []}]
        d.extract_summary = s
        db.commit()
        n = len(_live(db, pid))
        out = S.place_ners_from_drawing(db, db.get(Project, pid), actor="tests")
        assert out["created"] == 0 and out["annotations_absorbed"] >= 1, out
        assert len(_live(db, pid)) == n


def test_d25_undo_puts_the_drawing_back_and_forgets_the_released_spot(moved, client):
    pid, did = moved["pid"], moved["did"]
    r = client.post(f"/api/projects/{pid}/composite/undo/{moved['undo']}")
    assert r.status_code == 200, r.text
    x, y = moved["old"]
    with SessionLocal() as db:
        a = db.get(NerAsset, moved["ids"]["NER_20.1"])
        assert not a.released_spots
        assert {e.page for e in a.occurrences if e.scenario_id is None} == {moved["p0"]}
        st = S.adopt_drawn_rooms(db, db.get(Project, pid), db.get(Drawing, did),
                                 [_symbol(moved["p0"], x, y)])
        db.commit()
        assert st["created"] == 0 and st["same_as_marker"] == 1


def test_d25_delete_only_this_marker_leaves_its_spot_to_the_ner(client, tmp_path):
    """The same hole without the map: a NER drawn on two sheets, one drawing
    deleted with Delete only this marker, then Place NERs."""
    pid, did, f, mid, ids = _build(client, tmp_path, "D25 marker", [
        ("NER_30.1", (0, 0), (102, 30), None), ("NER_30.1", (1, 0), (102, 30), "NER_30.1")])
    p1 = _page_of(f, (1, 0))
    with SessionLocal() as db:
        e = [o for o in db.get(NerAsset, ids["NER_30.1"]).occurrences if o.page == p1][0]
        eid, ex, ey = e.id, e.x, e.y
    assert client.delete(f"/api/projects/{pid}/elements/{eid}?scope=marker").status_code == 204
    with SessionLocal() as db:
        p = db.get(Project, pid)
        n = len(_live(db, pid))
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did), [_symbol(p1, ex, ey)])
        db.commit()
        assert st["created"] == 0 and st["released_spot"] == 1
        assert len(_live(db, pid)) == n
        # Removing the NER later keeps its released spot removed too.
        from app import ner_register as R
        R.soft_delete(db, p, db.get(NerAsset, ids["NER_30.1"]), reason="test", actor="tests")
        db.commit()
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did), [_symbol(p1, ex, ey)])
        db.commit()
        assert st["created"] == 0 and st["on_removed_ner"] == 1


def test_d25_the_start_up_pass_restores_the_spot_and_flags_the_ner_made_on_it(client, tmp_path):
    """A 5.0.0 database: a move took a drawing off, nothing kept the spot, and
    Place NERs created a NER there. 5.1.0 reads the spot back from the audit
    log and puts a validation on the new NER — it removes nothing."""
    pid, did, f, mid, ids = _build(client, tmp_path, "D25 migrate", [
        ("NER_40.1", (0, 0), (60, 60), None)])
    p0, p22 = _page_of(f, (0, 0)), _page_of(f, (2, 2))
    X, Y = _map_point(mid, p22, (2, 2), (250, 160))
    assert client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                       json={"asset_id": ids["NER_40.1"], "x": X, "y": Y}).status_code == 200
    x, y = CB.detail_to_pt(0, 0, 60, 60)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        db.get(NerAsset, ids["NER_40.1"]).released_spots = None      # as 5.0.0 left it
        db.commit()
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, did), [_symbol(p0, x, y)])
        db.commit()
        assert st["created"] == 1                                      # the 5.0.0 defect
        made = [a for a in _live(db, pid) if a.id != ids["NER_40.1"]][0]
        made.created_at = _dt.datetime.utcnow() + _dt.timedelta(seconds=5)
        db.commit()
        out = MG.released_spots_510(db, p)
        assert out["released_spots_restored"] >= 1 and out["released_spot_ners_flagged"] == 1
        flagged = db.get(NerAsset, made.id)
        assert any(v.startswith(MG._RELEASED_PREFIX) for v in flagged.pending_validations)
        assert flagged.deleted_at is None                              # nothing removed
        again = MG.released_spots_510(db, p)
        assert again["released_spots_restored"] == 0 and again["released_spot_ners_flagged"] == 1
        assert sum(v.startswith(MG._RELEASED_PREFIX)
                   for v in db.get(NerAsset, made.id).pending_validations) == 1
        assert db.get(NerAsset, ids["NER_40.1"]).released_spots


# ---------------------------------------------------------------------------
# D29 — a NER whose sheets disagree is not collapsed onto one spot
# ---------------------------------------------------------------------------

def test_d29_a_ner_whose_drawings_land_apart_is_refused_and_nothing_changes(client, tmp_path):
    # One NER drawn on two neighbouring sheets at places 40 m apart.
    pid, did, f, mid, ids = _build(client, tmp_path, "D29 spread", [
        ("NER_50.1", (0, 0), (60, 30), None), ("NER_50.1", (1, 0), (130, 50), "NER_50.1")])
    o = client.get(f"/api/projects/{pid}/composite/{mid}").json()
    n = [x for x in o["ners"] if x["name"] == "NER_50.1"][0]
    assert n["spread_m"] > 1
    with SessionLocal() as db:
        before = sorted((e.page, e.x, e.y) for e in db.get(NerAsset, ids["NER_50.1"]).occurrences)
    for preview in (True, False):
        r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                        json={"asset_id": ids["NER_50.1"], "x": n["X"] + 1, "y": n["Y"],
                              "preview": preview})
        assert r.status_code == 422 and "apart" in r.json()["detail"], r.text
    with SessionLocal() as db:
        after = sorted((e.page, e.x, e.y) for e in db.get(NerAsset, ids["NER_50.1"]).occurrences)
        assert after == before
    o = client.get(f"/api/projects/{pid}/composite/{mid}").json()
    assert any(x["type"] == "spread" and x["name"] == "NER_50.1" for x in o["findings"])


# ---------------------------------------------------------------------------
# D26 — the window can say how far a move goes before it is confirmed
# ---------------------------------------------------------------------------

def test_d26_preview_says_the_distance_and_sheets_and_changes_nothing(client, tmp_path):
    pid, did, f, mid, ids = _build(client, tmp_path, "D26 preview", [
        ("NER_60.1", (1, 1), (150, 100), None)])
    p11 = _page_of(f, (1, 1))
    X0, Y0 = _map_point(mid, p11, (1, 1), (150, 100))
    X1, Y1 = _map_point(mid, p11, (1, 1), (170, 100))               # 20 m east
    with SessionLocal() as db:
        before = [(e.page, e.x, e.y) for e in db.get(NerAsset, ids["NER_60.1"]).occurrences]
        n_logs = db.execute(select(AuditLog).where(AuditLog.project_id == pid)).all()
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": ids["NER_60.1"], "x": X1, "y": Y1, "preview": True})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["preview"] is True and pv["distance_m"] == pytest.approx(20, abs=0.5)
    assert pv["moved"] and pv["removed"] == [] and pv["created"] == []
    assert all(pv["labels"].get(str(k)) for k in pv["moved"])
    with SessionLocal() as db:
        assert [(e.page, e.x, e.y) for e in db.get(NerAsset, ids["NER_60.1"]).occurrences] == before
        assert len(db.execute(select(AuditLog).where(AuditLog.project_id == pid)).all()) == len(n_logs)
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": ids["NER_60.1"], "x": X1, "y": Y1})
    assert r.json()["distance_m"] == pytest.approx(20, abs=0.5)
    with SessionLocal() as db:
        e = db.get(NerAsset, ids["NER_60.1"]).occurrences[0]
        x0, y0 = CB.detail_to_pt(1, 1, 150, 100)
        assert math.hypot(e.x - x0, e.y - y0) * CB.DET_MPU == pytest.approx(20, abs=0.3)


# ---------------------------------------------------------------------------
# D27, D28 — the PDF tells the placement states apart, and says so
# ---------------------------------------------------------------------------

def _close(c, ref, tol=0.02):
    return c is not None and all(abs(a - b) < tol for a, b in zip(c, ref))


def test_d27_d28_the_pdf_draws_each_state_its_own_way_and_the_legend_lists_them(client, tmp_path):
    pid, did, f, mid, ids = _build(client, tmp_path, "D27 states", [
        ("NER_70.1", (1, 1), (150, 100), None)])
    p_bad, p_unc = _page_of(f, (2, 1)), _page_of(f, (0, 2))
    with SessionLocal() as db:
        m = db.get(CompositeMap, mid)
        sheets = [dict(s) for s in m.sheets]
        for s in sheets:
            if s["page"] == p_bad:
                s["state"] = "contradicted"
            if s["page"] == p_unc:
                s["state"] = "unconfirmed"
        m.sheets = sheets
        db.commit()
    j = _wait(client, client.post(f"/api/projects/{pid}/composite-report").json()["job_id"])
    assert j["state"] == "done", j
    doc = pymupdf.open(stream=client.get(j["result"]["download"]).content, filetype="pdf")
    pg = doc[0]
    text = pg.get_text()
    assert "CONTRADICTED" in text and "NOT CONFIRMED" in text
    for word in ("Sheet confirmed", "Sheet not confirmed", "Sheet contradicted", "TER", "IDF",
                 "COW", "DIVA"):
        assert word in text, word
    strokes = [(d.get("color"), d.get("dashes"), d.get("width")) for d in pg.get_drawings()
               if d.get("color") is not None]
    red, orange, blue = (CS.STATE_PDF[k]["colour"] for k in ("contradicted", "unconfirmed",
                                                              "confirmed"))
    dash = {k: CS.STATE_PDF[k]["dashes"].split("]")[0] for k in CS.STATE_PDF}
    assert any(_close(c, red) and d and dash["contradicted"].strip("[") in d for c, d, w in strokes)
    assert any(_close(c, orange) and d and dash["unconfirmed"].strip("[") in d for c, d, w in strokes)
    assert any(_close(c, blue) for c, d, w in strokes)
    # The three outline patterns differ, so the state reads without colour.
    assert len({CS.STATE_PDF[k]["dashes"] for k in CS.STATE_PDF}) == 3


# ---------------------------------------------------------------------------
# D30 — tiles asked in parallel compose the missing picture once
# ---------------------------------------------------------------------------

def test_d30_parallel_tiles_compose_the_missing_picture_once(client, tmp_path):
    pid, did, f, mid, ids = _build(client, tmp_path, "D30 tiles", [
        ("NER_80.1", (1, 1), (150, 100), None)])
    folder = CS.project_dir(pid)
    with SessionLocal() as db:
        m = db.get(CompositeMap, mid)
        CS._drop_files(m)
        m.base_file = ""
        db.commit()
    for p in folder.glob("*.pdf"):
        p.unlink()
    errors = []

    def one(z, x, y):
        try:
            with SessionLocal() as db:
                CS.tile(db, db.get(CompositeMap, mid), z, x, y)
        except Exception as exc:          # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=one, args=(3, i % 3, i // 3)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(list(folder.glob("*.pdf"))) == 1
    with SessionLocal() as db:
        assert (folder / db.get(CompositeMap, mid).base_file).exists()


# ---------------------------------------------------------------------------
# D31 — Undo does not give a NER two drawings on one sheet
# ---------------------------------------------------------------------------

def test_d31_undo_does_not_draw_a_second_marker_where_the_ner_is_drawn_again(client, tmp_path):
    """A stadium project, QA of 5.0.0: after a move took NER_21.1 off two sheets, Place NERs
    drew it back there (same TEC code), and Undo then put the old markers
    back beside them — two NER_21.1 on each sheet."""
    pid, did, f, mid, ids = _build(client, tmp_path, "D31 undo", [
        ("NER_90.1", (0, 0), (60, 60), None)])
    p0, p22 = _page_of(f, (0, 0)), _page_of(f, (2, 2))
    X, Y = _map_point(mid, p22, (2, 2), (250, 160))
    out = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                      json={"asset_id": ids["NER_90.1"], "x": X, "y": Y}).json()
    x, y = CB.detail_to_pt(0, 0, 61, 60)
    with SessionLocal() as db:                       # drawn back there, 1 m off
        a = db.get(NerAsset, ids["NER_90.1"])
        db.add(Element(project_id=pid, drawing_id=did, page=p0, kind=a.kind,
                       label=a.display_name, x=x, y=y, origin="extracted",
                       ner_asset_id=a.id, origin_x=x, origin_y=y))
        db.commit()
    r = client.post(f"/api/projects/{pid}/composite/undo/{out['undo_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["already_drawn"]
    with SessionLocal() as db:
        pages = [e.page for e in db.get(NerAsset, ids["NER_90.1"]).occurrences
                 if e.scenario_id is None]
        assert pages.count(p0) == 1 and p22 not in pages


def test_d25_the_same_ner_in_another_series_keeps_its_drawing_there(client, tmp_path):
    """One NER drawn in the 400 and the 600 series. A move on the 400 map takes
    its 400 drawing off; the 600 drawing is not moved, and Place NERs on either
    book creates nothing."""
    pid, facts = _project_with_book(client, tmp_path, "D25 two series", [
        ("TST_400_TST_O.pdf", {}), ("TST_600_TST_O.pdf", {"prefix": "612"})])
    (d4, f4), (d6, f6) = sorted(facts.items())
    a = _place(client, pid, d4, f4, (0, 0), (60, 60), "NER_95.1")
    _place(client, pid, d6, f6, (0, 0), (60, 60), "NER_95.1", same_as=a["ner_asset_id"])
    j = _wait(client, client.post(f"/api/projects/{pid}/composite/build",
                                  json={"drawing_id": d4}).json()["job_id"])
    assert j["state"] == "done", j
    groups = [g for b in client.get(f"/api/projects/{pid}/composite").json()["books"]
              if b["drawing_id"] == d4 for g in b["groups"] if g.get("map")]
    mid = groups[0]["map"]["id"]
    p0, p22 = _page_of(f4, (0, 0)), _page_of(f4, (2, 2))
    X, Y = _map_point(mid, p22, (2, 2), (250, 160))
    out = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                      json={"asset_id": a["ner_asset_id"], "x": X, "y": Y}).json()
    assert out["other_books"] and out["created"]
    x, y = CB.detail_to_pt(0, 0, 60, 60)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        n = len(_live(db, pid))
        six = [e for e in db.get(NerAsset, a["ner_asset_id"]).occurrences if e.drawing_id == d6]
        assert len(six) == 1 and (six[0].x, six[0].y) == pytest.approx((x, y))
        st4 = S.adopt_drawn_rooms(db, p, db.get(Drawing, d4), [_symbol(p0, x, y)])
        st6 = S.adopt_drawn_rooms(db, p, db.get(Drawing, d6), [_symbol(_page_of(f6, (0, 0)), x, y)])
        db.commit()
        assert st4["created"] == 0 and st4["released_spot"] == 1
        assert st6["created"] == 0 and st6["same_as_marker"] == 1
        assert len(_live(db, pid)) == n
