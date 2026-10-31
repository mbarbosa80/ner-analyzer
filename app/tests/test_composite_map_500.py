"""5.0.0 — the composite map.

Marcelo, 30 Oct 2026: lay the detail sheets of one level of one book on one
map — never two series, never the key plan — as an option built only when he
asks, in a window of its own, carrying everything already worked on the
sheets; move, delete and reclassify NERs on it; print it as one PDF beside the
marked-up one. Moving a NER moves its marker on every sheet of the level that
shows the new spot; a sheet that does not loses it, and the move can be undone.

The book here is invented (``composite_book.py``), so the true place of every
sheet is known and each test can say how far the map put it from there.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-500-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t500.sqlite3")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite_book as CB                                        # noqa: E402

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import composite_service as CS                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.config import settings                                    # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain import composite as C                              # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import AuditLog, CompositeMap, Drawing, Element, NerAsset, Page  # noqa: E402

RATIO = CB.KEY_MPU / CB.DET_MPU


def _truth(zone: tuple[int, int]) -> tuple[float, float]:
    """The translation that puts a detail sheet exactly on the key plan's frame."""
    kx, ky = CB.key_to_pt(10, 10)
    dx, dy = CB.detail_to_pt(*zone, 10, 10)
    return kx * RATIO - dx, ky * RATIO - dy


def _error_m(sheet: dict, zone) -> float:
    tx, ty = _truth(zone)
    return math.hypot(sheet["tx"] - tx, sheet["ty"] - ty) * CB.DET_MPU


# ---------------------------------------------------------------------------
# The placement itself
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def books(tmp_path_factory):
    d = tmp_path_factory.mktemp("books")
    out = {}
    for name, kw in {"flat": {}, "rotated": {"rotated": True},
                     "no_lines": {"match_lines": False},
                     "bad_grid": {"shift_m": {(2, 1): (6.0, 0.0)}}}.items():
        path = str(d / f"{name}.pdf")
        out[name] = (path, CB.make_book(path, **kw))
    return out


@pytest.mark.parametrize("name", ["flat", "rotated"])
def test_every_sheet_lands_within_a_few_decimetres(books, name):
    path, facts = books[name]
    res = C.align_book(path, facts)
    assert len(res["groups"]) == 1
    g = res["groups"][0]
    assert g["key"] == "412" and g["level"] == "LEVEL 02"
    assert len(g["sheets"]) == 12
    for sh, f in zip(g["sheets"], facts[1:]):
        assert sh["state"] == "confirmed", sh
        assert sh["method"] == "match lines"
        assert _error_m(sh, f["zone"]) < 0.3, (sh["sheet_number"], _error_m(sh, f["zone"]))
    assert g["refine"]["dropped"] == 0


def test_a_book_without_match_lines_is_placed_by_correlation(books):
    path, facts = books["no_lines"]
    g = C.align_book(path, facts)["groups"][0]
    for sh, f in zip(g["sheets"], facts[1:]):
        assert sh["method"] == "correlation"
        assert _error_m(sh, f["zone"]) < 0.3


def test_match_lines_that_disagree_with_the_key_plan_are_overruled(books):
    """A grid that is not regular (two books of the feasibility test): the match
    lines alone put the sheet 6 m off, silently. The correlation wins."""
    path, facts = books["bad_grid"]
    g = C.align_book(path, facts)["groups"][0]
    by_zone = {f["zone"]: sh for sh, f in zip(g["sheets"], facts[1:])}
    bad = by_zone[(2, 1)]
    assert bad["method"] == "correlation (match lines rejected)"
    assert bad["a_vs_b_m"] > 5
    assert _error_m(bad, (2, 1)) < 0.3
    for z, sh in by_zone.items():
        assert _error_m(sh, z) < 0.3


def test_neighbours_correct_a_few_metres_and_never_relocate_a_sheet(books):
    """The neighbour check measures each overlapping pair only near where the
    sheets are: a sheet 2.5 m off is put right by its neighbours; one 10 m
    off is left where it is and is not confirmed (a wider search found wrong
    matches and dragged good sheets 7 to 11 m on 30 Oct 2026)."""
    path, facts = books["no_lines"]
    book = C._Book(path)
    sheets = {}
    for f in facts[1:]:
        tx, ty = _truth(f["zone"])
        sheets[f["number"]] = {"tx": tx, "ty": ty, "mpu": CB.DET_MPU, "method": "correlation",
                               "view": list(C.viewport(book.page(f["number"]).rect))}
    near, far = _page_of(facts, (1, 1)), _page_of(facts, (2, 2))
    sheets[near]["tx"] += 2.5 / CB.DET_MPU
    sheets[far]["ty"] += 10.0 / CB.DET_MPU
    C._refine(book, sheets)
    by = {f["number"]: f for f in facts[1:]}
    assert _error_m(sheets[near], by[near]["zone"]) < 0.3
    assert sheets[near]["neighbours_ok"] > 0
    assert _error_m(sheets[far], by[far]["zone"]) == pytest.approx(10.0, abs=0.01)
    assert sheets[far]["neighbours_ok"] == 0


def test_groups_follow_the_drawing_number_and_leave_key_plans_out():
    pages = [
        {"number": 1, "sheet_number": "X-401-A", "level": "LEVEL 01", "key_plan": True, "mpu": 0.2},
        {"number": 2, "sheet_number": "X-411A1-A", "level": "LEVEL 01", "key_plan": False, "mpu": 0.05},
        {"number": 3, "sheet_number": "X-411A2-A", "level": "82 m²", "key_plan": False, "mpu": 0.05},
        {"number": 4, "sheet_number": "X-412A1-A", "level": "LEVEL 02", "key_plan": False, "mpu": None},
        {"number": 5, "sheet_number": "", "level": None, "key_plan": False, "mpu": 0.05},
    ]
    plan = {g["key"]: g for g in C.plan_groups(pages)}
    # The title block said "82 m²" for page 3; the drawing number is right.
    assert plan["411"]["pages"] == [2, 3]
    assert plan["411"]["label"] == "411 · LEVEL 01"
    assert plan["412"]["pages"] == [] and plan["412"]["no_scale"] == [4]
    assert plan["(no level)"]["pages"] == [5]
    assert all(1 not in g["pages"] for g in plan.values())


def test_map_and_sheet_coordinates_are_inverse():
    sheet = {"tx": 120.5, "ty": -40.25, "s": 0.5}
    frame = {"x0": 30.0, "y0": -12.0}
    X, Y = C.to_map(sheet, frame, 800.0, 333.0)
    assert C.from_map(sheet, frame, X, Y) == pytest.approx((800.0, 333.0))


def test_a_tile_off_the_map_is_blank_and_full_size(tmp_path):
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    pg.draw_rect(pymupdf.Rect(10, 10, 590, 390), color=(0, 0, 0), width=3)
    path = str(tmp_path / "base.pdf")
    doc.save(path)
    png = C.render_tile(path, 6, 40, 40)
    pix = pymupdf.Pixmap(png)
    assert (pix.width, pix.height) == (C.TILE_PX, C.TILE_PX)
    C.forget(path)


# ---------------------------------------------------------------------------
# The application
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


def _wait(c, job_id: str) -> dict:
    for _ in range(600):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _project_with_book(c, tmp_path, name: str, files: list[tuple[str, dict]]):
    pid = c.post("/api/projects", json={"name": name, "venue_code": "TST"}).json()["id"]
    facts_by_drawing = {}
    for fname, kw in files:
        path = tmp_path / fname
        facts = CB.make_book(str(path), **kw)
        with open(path, "rb") as fh:
            r = c.post(f"/api/projects/{pid}/drawings",
                       files={"file": (fname, fh, "application/pdf")})
        assert r.status_code == 201, r.text
        did = r.json()["drawing_id"] if "drawing_id" in r.json() else r.json()["id"]
        # The facts the Scale screen would hold once the scales are confirmed
        # and the key plans ticked.
        with SessionLocal() as db:
            for f in facts:
                pg = db.execute(select(Page).where(Page.drawing_id == did,
                                                   Page.number == f["number"])).scalar_one()
                pg.sheet_number, pg.level, pg.key_plan = f["sheet_number"], f["level"], f["key_plan"]
                pg.metres_per_unit, pg.scale_confirmed = f["mpu"], True
            db.commit()
        facts_by_drawing[did] = facts
    return pid, facts_by_drawing


def _key(c, pid, did, page):
    p = c.get(f"/api/projects/{pid}").json()
    hit = [x for x in p["pages"] if x.get("drawing_id") == did and x.get("page", x["number"]) == page]
    return hit[0]["number"] if hit else page


def _page_of(facts, zone):
    return [f["number"] for f in facts if f.get("zone") == zone][0]


def _place(c, pid, did, facts, zone, site, label, kind="NER_NONCRITICAL", same_as=None):
    x, y = CB.detail_to_pt(*zone, *site)
    body = {"page": _key(c, pid, did, _page_of(facts, zone)), "kind": kind, "label": label,
            "x": x, "y": y}
    if same_as:
        body["same_as_asset_id"] = same_as
    r = c.post(f"/api/projects/{pid}/elements", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _map_point(map_id: int, page: int, zone, site) -> tuple[float, float]:
    with SessionLocal() as db:
        m = db.get(CompositeMap, map_id)
        s = [x for x in m.sheets if x["page"] == page][0]
        return C.to_map(s, m.frame, *CB.detail_to_pt(*zone, *site))


@pytest.fixture(scope="module")
def built(client, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("proj")
    pid, facts = _project_with_book(client, tmp, "Composite 500", [("TST_400_TST_O.pdf", {})])
    did, f = next(iter(facts.items()))
    # One NER drawn on two neighbouring sheets (the overlap of A-zone 1 and 2),
    # two NERs 1 m apart under different names, one alone.
    a = _place(client, pid, did, f, (0, 0), (102, 30), "NER_20.1")
    _place(client, pid, did, f, (1, 0), (102, 30), "NER_20.1", same_as=a["ner_asset_id"])
    _place(client, pid, did, f, (2, 1), (250, 100), "NER_21.1")
    _place(client, pid, did, f, (2, 1), (251, 100), "NER_22.1")
    _place(client, pid, did, f, (3, 2), (350, 160), "NERc_01.1", kind="NER_CRITICAL")
    r = client.post(f"/api/projects/{pid}/composite/build", json={"drawing_id": did})
    assert r.status_code == 200, r.text
    j = _wait(client, r.json()["job_id"])
    assert j["state"] == "done", j
    plan = client.get(f"/api/projects/{pid}/composite").json()["books"]
    g = plan[0]["groups"][0]
    return {"pid": pid, "did": did, "facts": f, "map_id": g["map"]["id"], "plan": plan,
            "asset": a["ner_asset_id"]}


def test_the_build_makes_one_map_per_level_and_says_how_sure_it_is(client, built):
    g = built["plan"][0]["groups"][0]
    assert g["key"] == "412"
    m = g["map"]
    assert m["sheets"] == 12 and m["confirmed"] == 12 and m["has_picture"]
    assert m["built_by"] == "tester" and not m["outdated"]
    with SessionLocal() as db:
        acts = [a.action for a in db.execute(select(AuditLog).where(
            AuditLog.project_id == built["pid"])).scalars()]
    assert "composite.built" in acts
    # Building a picture changes nothing the analysis reads.
    assert {"composite.built", "composite.sheet_excluded"} <= S._ANALYSIS_NEUTRAL


def test_a_second_build_while_one_runs_is_refused(client, built, monkeypatch):
    from app.api import composite_routes as R
    monkeypatch.setattr(R, "_busy", lambda *a, **k: True)
    r = client.post(f"/api/projects/{built['pid']}/composite/build",
                    json={"drawing_id": built["did"]})
    assert r.status_code == 409


def test_the_overlay_carries_the_work_of_every_sheet_and_the_findings(client, built):
    o = client.get(f"/api/projects/{built['pid']}/composite/{built['map_id']}").json()
    names = {n["name"]: n for n in o["ners"]}
    assert set(names) == {"NER_20.1", "NER_21.1", "NER_22.1", "NERc_01.1"}
    # The NER drawn on two sheets is one NER, its two drawings in one place.
    n20 = names["NER_20.1"]
    assert len(n20["points"]) == 2 and n20["spread_m"] < 0.5
    assert names["NERc_01.1"]["critical"] is True
    kinds = {(f["type"], f.get("name"), f.get("other_name")) for f in o["findings"]}
    assert ("close", "NER_21.1", "NER_22.1") in kinds
    assert not any(f["type"] == "spread" for f in o["findings"])
    assert o["limits"] == {"general_m": 90.0, "photographer_m": 70.0}
    assert all(s.get("rect") for s in o["sheets"])
    assert o["map"]["tile_px"] == C.TILE_PX


def test_tiles_are_png_and_cached(client, built):
    url = f"/api/projects/{built['pid']}/composite/{built['map_id']}/tiles/3/0/0.png"
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert pymupdf.Pixmap(r.content).width == C.TILE_PX
    with SessionLocal() as db:
        m = db.get(CompositeMap, built["map_id"])
        assert (CS._tiles_dir(m) / "3" / "0_0.png").exists()
    assert client.get(f"/api/projects/{built['pid']}/composite/{built['map_id']}"
                      f"/tiles/{C.TILE_ZMAX + 1}/0/0.png").status_code == 404


def test_moving_a_ner_follows_the_sheets_that_show_the_spot_and_undoes(client, built):
    pid, did, f, mid = built["pid"], built["did"], built["facts"], built["map_id"]
    p0, p1 = _page_of(f, (0, 0)), _page_of(f, (1, 0))
    # The middle of zone (1, 0): sheet (1, 0) shows it, sheet (0, 0) does not.
    X, Y = _map_point(mid, p1, (1, 0), (150, 33))
    with SessionLocal() as db:
        before = {e.page: (e.x, e.y) for e in db.execute(select(Element).where(
            Element.ner_asset_id == built["asset"])).scalars()}
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": built["asset"], "x": X, "y": Y})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["moved"] == [p1] and out["removed"] == [p0] and out["created"] == []
    with SessionLocal() as db:
        es = list(db.execute(select(Element).where(Element.ner_asset_id == built["asset"])).scalars())
        assert [e.page for e in es] == [p1]
        x, y = CB.detail_to_pt(1, 0, 150, 33)
        assert math.hypot(es[0].x - x, es[0].y - y) * CB.DET_MPU < 0.3
        a = db.get(NerAsset, built["asset"])
        assert a.canonical_page == p1 and a.canonical_x == pytest.approx(es[0].x)
        acts = [l.action for l in db.execute(select(AuditLog).where(
            AuditLog.project_id == pid).order_by(AuditLog.id)).scalars()]
    assert "ner.moved" in acts and "composite.ner_moved" in acts
    assert "composite.ner_moved" not in S._ANALYSIS_NEUTRAL          # it is a change
    # Undo puts both drawings back where they were.
    r = client.post(f"/api/projects/{pid}/composite/undo/{out['undo_id']}")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        after = {e.page: (e.x, e.y) for e in db.execute(select(Element).where(
            Element.ner_asset_id == built["asset"])).scalars()}
    assert after.keys() == before.keys()
    for k in before:
        assert after[k] == pytest.approx(before[k])
    assert client.post(f"/api/projects/{pid}/composite/undo/{out['undo_id']}").status_code == 409


def test_a_spot_no_sheet_of_the_ner_shows_gets_a_marker_on_the_sheet_that_does(client, built):
    pid, did, f, mid = built["pid"], built["did"], built["facts"], built["map_id"]
    p_target = _page_of(f, (2, 2))
    X, Y = _map_point(mid, p_target, (2, 2), (250, 160))
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": built["asset"], "x": X, "y": Y})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["moved"] == [] and out["created"] == [p_target] and len(out["removed"]) == 2
    with SessionLocal() as db:
        es = list(db.execute(select(Element).where(Element.ner_asset_id == built["asset"])).scalars())
        assert [e.page for e in es] == [p_target]
        assert es[0].detection_method == "composite map"
    assert client.post(f"/api/projects/{pid}/composite/undo/{out['undo_id']}").status_code == 200
    with SessionLocal() as db:
        pages = sorted(e.page for e in db.execute(select(Element).where(
            Element.ner_asset_id == built["asset"])).scalars())
    assert pages == sorted([_page_of(f, (0, 0)), _page_of(f, (1, 0))])


def test_a_spot_off_every_sheet_and_a_locked_ner_are_refused(client, built):
    pid, mid = built["pid"], built["map_id"]
    r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                    json={"asset_id": built["asset"], "x": -5000, "y": -5000})
    assert r.status_code == 422
    with SessionLocal() as db:
        db.get(NerAsset, built["asset"]).locked = True
        db.commit()
    try:
        X, Y = _map_point(mid, _page_of(built["facts"], (1, 0)), (1, 0), (150, 33))
        r = client.post(f"/api/projects/{pid}/composite/{mid}/move-ner",
                        json={"asset_id": built["asset"], "x": X, "y": Y})
        assert r.status_code == 409
    finally:
        with SessionLocal() as db:
            db.get(NerAsset, built["asset"]).locked = False
            db.commit()


def test_a_sheet_left_off_the_map_stays_off_after_a_rebuild(client, built):
    pid, did, f, mid = built["pid"], built["did"], built["facts"], built["map_id"]
    pg = _page_of(f, (3, 2))
    r = client.post(f"/api/projects/{pid}/composite/{mid}/sheets/{pg}/exclude",
                    json={"excluded": True})
    assert r.status_code == 200, r.text and r.json()["excluded"] == 1
    o = client.get(f"/api/projects/{pid}/composite/{mid}").json()
    crit = [n for n in o["ners"] if n["name"] == "NERc_01.1"][0]
    assert crit["points"] == [] and crit["off_map_pages"]
    assert any(x["type"] == "off_map" and x["name"] == "NERc_01.1" for x in o["findings"])
    j = _wait(client, client.post(f"/api/projects/{pid}/composite/build",
                                  json={"drawing_id": did}).json()["job_id"])
    assert j["state"] == "done"
    m = client.get(f"/api/projects/{pid}/composite").json()["books"][0]["groups"][0]["map"]
    assert m["excluded"] == 1
    r = client.post(f"/api/projects/{pid}/composite/{mid}/sheets/{pg}/exclude",
                    json={"excluded": False})
    assert r.status_code == 200 and r.json()["excluded"] == 0


def test_the_composite_pdf_has_a_page_per_map_and_the_legend_once(client, tmp_path):
    pid, facts = _project_with_book(client, tmp_path, "Composite two books", [
        ("TST_400_TST_O.pdf", {}), ("TST_600_TST_O.pdf", {"prefix": "612"})])
    assert client.post(f"/api/projects/{pid}/composite-report").status_code == 422
    for did, f in facts.items():
        _place(client, pid, did, f, (1, 1), (150, 100), f"NER_3{did % 10}.1")
        j = _wait(client, client.post(f"/api/projects/{pid}/composite/build",
                                      json={"drawing_id": did}).json()["job_id"])
        assert j["state"] == "done", j
    j = _wait(client, client.post(f"/api/projects/{pid}/composite-report").json()["job_id"])
    assert j["state"] == "done", j
    r = client.get(j["result"]["download"])
    assert r.status_code == 200
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    assert doc.page_count == 2
    t0, t1 = doc[0].get_text(), doc[1].get_text()
    assert "Legend" in t0 and "Legend" not in t1
    assert "composite map" in t0 and "612" in t1
    assert max(doc[0].rect.width, doc[0].rect.height) <= C.PDF_MAX_SIDE + 1


def test_a_book_without_a_key_plan_is_refused_with_a_reason(client, tmp_path):
    pid, facts = _project_with_book(client, tmp_path, "Composite no key", [("TST_400_K.pdf", {})])
    did = next(iter(facts))
    with SessionLocal() as db:
        for pg in db.execute(select(Page).where(Page.drawing_id == did)).scalars():
            pg.key_plan = False
        db.commit()
    j = _wait(client, client.post(f"/api/projects/{pid}/composite/build",
                                  json={"drawing_id": did}).json()["job_id"])
    assert j["state"] == "error" and "key plan" in j["error"]


def test_a_level_on_one_sheet_gets_no_map(books):
    path, facts = books["flat"]
    one = [facts[0], dict(facts[1], sheet_number="TST-413A1-TST-OP")] + facts[2:]
    keys = [g["key"] for g in C.align_book(path, one)["groups"]]
    assert keys == ["412"]


def test_deleting_the_project_takes_the_maps_with_it(client, tmp_path):
    pid, facts = _project_with_book(client, tmp_path, "Composite gone", [("TST_400_G.pdf", {})])
    did = next(iter(facts))
    assert _wait(client, client.post(f"/api/projects/{pid}/composite/build",
                                     json={"drawing_id": did}).json()["job_id"])["state"] == "done"
    folder = settings.composite_dir / f"project_{pid}"
    assert any(folder.glob("*.pdf"))
    assert client.delete(f"/api/projects/{pid}").status_code in (200, 204)
    assert not folder.exists()
    with SessionLocal() as db:
        assert db.execute(select(CompositeMap).where(CompositeMap.project_id == pid)).first() is None
