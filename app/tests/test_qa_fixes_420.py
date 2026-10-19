"""4.2.0 — the defects the QA pass of 16 Oct 2026 found in 4.1.0 (D1–D16).

Every test names its defect. The QA report ("Parecer de QA — NER Analyzer
4.1.0") has the reproduction on the real projects; these hold the rule.
"""

from __future__ import annotations

import datetime as _dt
import pathlib

import openpyxl
from sqlalchemy import select

from tests.test_wireless_tie_250 import (DWISA, OFFICE, TMP, _ap, _analyse, _line,  # noqa: F401
                                         _match, _ner, _project, _room, _teap, client)
from tests.test_multi_book_410 import _key, _two_books
from app import migrate
from app import ner_register as R
from app import services as S
from app.config import settings
from app.db import SessionLocal
from app.domain.drawn_rooms import DrawnRoom
from app.domain.pdf_ingest import SPACE_CODE_RX
from app.models import (AuditLog, Drawing, DrawingSpace, Element, NerAsset, Project,
                        SpaceMatchRow, TeapSpace)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"


def _room_at(page, x, y, code, critical=False):
    return DrawnRoom(page=page, x=x, y=y, label_x=x, label_y=y, critical=critical, code=code,
                     source="code", text=f"Network Equipment Rack {code}", via_leader=False)


def _live(db, pid):
    return [a for a in db.execute(select(NerAsset).where(NerAsset.project_id == pid)).scalars()
            if a.deleted_at is None and a.merged_into_id is None]


# ---------------------------------------------------------------------------
# D1 — a removed numbered room is not created again
# ---------------------------------------------------------------------------

def test_d1_a_removed_coded_room_stays_removed_on_another_sheet_and_series(client):
    pid, a, b = _two_books("d1 removed code")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        st = S.adopt_drawn_rooms(db, p, db.get(Drawing, a), [_room_at(1, 100, 100, "TEC.020-026")])
        assert st["created"] == 1
        asset = _live(db, pid)[0]
        R.soft_delete(db, p, asset, reason="not in the design", actor="tests")
        db.commit()
        # The same code printed on page 2 of the same book, and on the 600 series.
        st2 = S.adopt_drawn_rooms(db, p, db.get(Drawing, a), [_room_at(2, 300, 300, "TEC.020-026")])
        st3 = S.adopt_drawn_rooms(db, p, db.get(Drawing, b), [_room_at(1, 500, 500, "TEC.020-026")])
        assert st2["created"] == 0 and st2["on_removed_ner"] == 1
        assert st3["created"] == 0 and st3["on_removed_ner"] == 1
        assert _live(db, pid) == []
        # Restore brings the room back on every sheet the code is printed on.
        R.restore(db, p, db.get(NerAsset, asset.id), actor="tests")
        db.commit()
        keys = {S.SH.for_project(db, pid).of(e) for e in db.get(NerAsset, asset.id).occurrences}
        assert keys == {_key(a, 1), _key(a, 2), _key(b, 1)}


def _symbol_at(page, x, y):
    return DrawnRoom(page=page, x=x, y=y, label_x=x, label_y=y, critical=None, code=None,
                     source="symbol", text="NER", via_leader=False)


def test_d1_a_symbol_beside_a_code_read_in_the_same_pass_is_the_same_room(client):
    """The RIV 400 book: TEC.010-021 (removed) and the NER block symbol of
    the same rack 4 m away (1 unit = 1 m on these sheets). 4.1.0 created both; the symbol alone came back
    after the code was fixed."""
    pid, a, b = _two_books("d1 symbol")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        dr = db.get(Drawing, a)
        S.adopt_drawn_rooms(db, p, dr, [_room_at(1, 100, 100, "TEC.010-021", critical=True)])
        R.soft_delete(db, p, _live(db, pid)[0], reason="not in the design", actor="tests")
        db.commit()
        # Another sheet: the removed code and its symbol; a new code and its symbol.
        st = S.adopt_drawn_rooms(db, p, dr, [
            _room_at(2, 300, 300, "TEC.010-021", critical=True),
            _room_at(2, 900, 300, "TEC.020-030"),
            _symbol_at(2, 304, 302), _symbol_at(2, 905, 303)])
        assert st["created"] == 1 and st["on_removed_ner"] == 2 and st["same_as_marker"] == 1
        assert [x.space_code for x in _live(db, pid)] == ["TEC.020-030"]
        # A symbol far from every room is still a room of its own.
        st = S.adopt_drawn_rooms(db, p, dr, [_symbol_at(3, 50, 50)])
        assert st["created"] == 1


# ---------------------------------------------------------------------------
# D2 — codes with a three-digit sub-index are read in full
# ---------------------------------------------------------------------------

def test_d2_the_reader_keeps_three_digit_sub_indices():
    for text, code in [("PEM.003.000-003", "PEM.003.000-003"), ("PRS.007.001-004", "PRS.007.001-004"),
                       ("VBV.001.001-001", "VBV.001.001-001"), ("SPT.003.03", "SPT.003.03"),
                       ("PRS.007.01.21", "PRS.007.01.21"), ("TEC.010-001", "TEC.010-001")]:
        assert SPACE_CODE_RX.search(text).group(0) == code
    assert SPACE_CODE_RX.search("03/31/2026") is None


def test_d2_cut_codes_are_repaired_and_a_confirmation_on_the_cut_code_released(client):
    pid = _project("d2 repair")
    rid = _room(pid, "VBV.001", ".001-001 Athlete Staging FOP", 100, 100)
    other = _room(pid, "PRS.007", ".001-004", 200, 200)
    key = _teap(pid, "VBV.001", "Field of Play", [_line("Laptop", 3, 3, "LAP")])
    with SessionLocal() as db:
        t = db.execute(select(TeapSpace).where(TeapSpace.space_key == key)).scalar_one()
        t.locked_verdict, t.locked_drawing_space_id = "assigned", rid
        t.locked_method, t.locked_confirmed, t.locked_by = "exact_code", True, "user"
        db.commit()
        out = migrate.repair_truncated_codes(db, db.get(Project, pid))
        assert out == {"codes_repaired": 2, "confirmations_released": 1}
        ds = db.get(DrawingSpace, rid)
        assert (ds.space_code, ds.name) == ("VBV.001.001-001", "Athlete Staging FOP")
        assert db.get(DrawingSpace, other).space_code == "PRS.007.001-004"
        t = db.execute(select(TeapSpace).where(TeapSpace.space_key == key)).scalar_one()
        assert t.locked_drawing_space_id == rid and t.locked_confirmed is False
        # Once per book.
        assert migrate.repair_truncated_codes(db, db.get(Project, pid))["codes_repaired"] == 0


# ---------------------------------------------------------------------------
# D3 — a restart never signs off the matcher's answers in a person's name
# ---------------------------------------------------------------------------

def test_d3_the_matchers_confirmation_is_not_adopted_as_a_decision(client):
    pid = _project("d3 adopt")
    _room(pid, "OFF.301", "Office", 100, 100)
    key = _teap(pid, "OFF.301", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    with SessionLocal() as db:
        m = db.execute(select(SpaceMatchRow).join(TeapSpace, TeapSpace.id == SpaceMatchRow.teap_space_id)
                       .where(TeapSpace.space_key == key)).scalar_one()
        assert m.confirmed and not m.confirmed_by, "an exact code the matcher signs off"
        migrate.adopt_match_decisions(db, db.get(Project, pid))
        t = db.execute(select(TeapSpace).where(TeapSpace.space_key == key)).scalar_one()
        assert t.locked_verdict is None


def test_d3_locks_an_old_start_made_are_released_and_a_persons_kept(client):
    pid = _project("d3 release")
    _room(pid, "OFF.302", "Office", 100, 100)
    _room(pid, "OFF.303", "Office 3", 300, 100)
    k1 = _teap(pid, "OFF.302", "Office", OFFICE)
    k2 = _teap(pid, "OFF.303", "Office 3", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    # A person confirms OFF.303 through the screen.
    m2 = next(x for x in client.get(f"/api/projects/{pid}/matches").json() if x["teap_code"] == "OFF.303")
    assert client.patch(f"/api/projects/{pid}/matches/{m2['id']}",
                        json={"confirmed": True, "justification": "seen"}).status_code == 200
    when = _dt.datetime.utcnow()
    with SessionLocal() as db:
        # What 4.1.0's start-up did to OFF.302: locked "by user" at start time.
        t1 = db.execute(select(TeapSpace).where(TeapSpace.space_key == k1)).scalar_one()
        m1 = db.execute(select(SpaceMatchRow).where(SpaceMatchRow.teap_space_id == t1.id)).scalar_one()
        t1.locked_verdict, t1.locked_drawing_space_id = "assigned", m1.drawing_space_id
        t1.locked_method, t1.locked_confirmed, t1.locked_by, t1.locked_at = "exact_code", True, "user", when
        m1.confirmed_by = "user"
        db.add(AuditLog(project_id=pid, actor="user", action="matching.decisions_made_durable",
                        at=when, payload={"rooms_locked": 1}))
        db.commit()
        out = migrate.release_matcher_locks(db, db.get(Project, pid))
        assert out["matcher_locks_released"] == 1
        t1 = db.execute(select(TeapSpace).where(TeapSpace.space_key == k1)).scalar_one()
        t2 = db.execute(select(TeapSpace).where(TeapSpace.space_key == k2)).scalar_one()
        assert t1.locked_verdict is None, "the matcher's answer again"
        assert t2.locked_verdict == "assigned", "a person's confirmation stays"
        m1 = db.execute(select(SpaceMatchRow).where(SpaceMatchRow.teap_space_id == t1.id)).scalar_one()
        assert m1.confirmed and m1.confirmed_by is None, "confirmed by the matcher"


# ---------------------------------------------------------------------------
# D4 — an export never comes from an analysis something changed after
# ---------------------------------------------------------------------------

def test_d4_a_deleted_ner_is_not_in_an_export_made_before_run_analysis(client):
    pid = _project("d4 stale")
    _room(pid, "OFF.401", "Office", 100, 100)
    _teap(pid, "OFF.401", "Office", OFFICE)
    eid = _ner(pid, "NER GONE", 100, 120)
    _ner(pid, "NER STAYS", 140, 120)
    _match(client, pid)
    assert client.post(f"/api/projects/{pid}/analyse").status_code == 200
    assert client.get(f"/api/projects/{pid}/spaces/assignments").json()["stale"] is None
    assert client.delete(f"/api/projects/{pid}/elements/{eid}").status_code == 204
    stale = client.get(f"/api/projects/{pid}/spaces/assignments").json()["stale"]
    assert stale and stale["changes"] >= 1
    r = client.post(f"/api/projects/{pid}/reports/xlsx")
    assert r.status_code == 200 and r.json()["analysis_refreshed"]["changes"] >= 1
    path = settings.exports_dir / f"project_{pid}" / r.json()["file"]
    names = [row[0] for row in openpyxl.load_workbook(path)["NERs and ports"].iter_rows(
        min_row=2, values_only=True) if row[0] and row[0] != "TOTAL"]
    assert "NER GONE" not in names and "NER STAYS" in names
    assert client.get(f"/api/projects/{pid}/spaces/assignments").json()["stale"] is None


def test_d4_a_saved_scenario_other_than_as_is_comes_out_as_it_was_saved(client):
    pid = _project("d4 proposed")
    _room(pid, "OFF.402", "Office", 100, 100)
    _teap(pid, "OFF.402", "Office", OFFICE)
    eid = _ner(pid, "NER P", 100, 120)
    _match(client, pid)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        res, ners = S.analyse(db, p, scenario_name="Proposed")
        S.save_scenario(db, p, "Proposed", "proposed", res, ners)
    assert client.delete(f"/api/projects/{pid}/elements/{eid}").status_code == 204
    r = client.post(f"/api/projects/{pid}/reports/xlsx?scenario=Proposed")
    assert r.status_code == 200 and r.json().get("analysis_refreshed") is None


# ---------------------------------------------------------------------------
# D5 — the audit log names the person signed in
# ---------------------------------------------------------------------------

def test_d5_the_author_is_the_person_signed_in_never_the_request_body(client):
    pid = _project("d5 actor")
    eid = _ner(pid, "NER ACT", 100, 120)
    with SessionLocal() as db:
        aid = db.get(Element, eid).ner_asset_id
    r = client.post(f"/api/projects/{pid}/ners/{aid}/rename",
                    json={"name": "NER ACTED", "reason": "x", "actor": "someone-else"})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/projects/{pid}/ners/{aid}/remove", json={"reason": "y"}).status_code == 200
    log = client.get(f"/api/projects/{pid}/audit").json()
    acts = {a["action"]: a["actor"] for a in log}
    assert acts["ner.renamed"] == "tester" and acts["ner.removed"] == "tester"
    assert all(a["actor"] != "someone-else" for a in log)


# ---------------------------------------------------------------------------
# D6 — a shaft between two series
# ---------------------------------------------------------------------------

def test_d6_the_shaft_tool_names_the_sheet_not_a_bare_page():
    src = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    assert "sheetFromText(p, other)" in src and "upper_page: target" in src
    assert "upper_page: Number(other)" not in src
    panels = (SRC / "pages" / "panels.tsx").read_text(encoding="utf-8")
    assert "export function sheetFromText" in panels


def test_d6_a_shaft_between_books_by_sheet_keys_is_accepted(client):
    pid, a, b = _two_books("d6 shaft")
    r = client.post(f"/api/projects/{pid}/verticals", json={
        "key": "S1", "lower_page": _key(a, 1), "lower_x": 1, "lower_y": 1,
        "upper_page": _key(b, 2), "upper_x": 1, "upper_y": 1, "length_m": 4.5, "kind": "shaft"})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# D7 — a deleted project takes its files; ids are never handed out twice
# ---------------------------------------------------------------------------

def test_d7_delete_removes_the_files_and_the_id_is_not_reused(client):
    r = client.post("/api/projects", json={"name": "d7 one", "venue_code": "D7"})
    pid = r.json()["id"]
    folder = settings.uploads_dir / f"project_{pid}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "book.pdf").write_bytes(b"%PDF-1.4")
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert not folder.exists()
    r2 = client.post("/api/projects", json={"name": "d7 two", "venue_code": "D7"})
    assert r2.json()["id"] > pid


def test_d7_orphan_folders_and_files_are_set_aside_at_start_never_deleted(client):
    ghost = settings.uploads_dir / "project_987654"
    ghost.mkdir(parents=True, exist_ok=True)
    (ghost / "old.pdf").write_bytes(b"x")
    pid = _project("d7 orphan file")
    live = settings.uploads_dir / f"project_{pid}"
    live.mkdir(parents=True, exist_ok=True)
    (live / "cancelled.pdf").write_bytes(b"x")
    with SessionLocal() as db:
        out = migrate.set_aside_orphan_files(db)
        assert out["orphan_folders"] >= 1 and out["orphan_files"] >= 1
        assert S.next_project_id(db) > 987654
    assert not ghost.exists() and not (live / "cancelled.pdf").exists()
    aside = sorted((settings.data_dir / "set-aside").iterdir())[-1]
    assert (aside / "uploads" / "project_987654" / "old.pdf").read_bytes() == b"x"
    assert (aside / "uploads" / f"project_{pid}" / "cancelled.pdf").read_bytes() == b"x"
    assert "never reads them" in (aside / "WHAT-IS-THIS.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# D8 / D13 — renaming
# ---------------------------------------------------------------------------

def test_d8_a_name_another_ner_has_is_refused_and_existing_pairs_flagged(client):
    pid = _project("d8 names")
    a = _ner(pid, "NER23", 100, 120)
    b = _ner(pid, "NER24", 400, 120)
    with SessionLocal() as db:
        ida, idb = db.get(Element, a).ner_asset_id, db.get(Element, b).ner_asset_id
    r = client.post(f"/api/projects/{pid}/ners/{idb}/rename", json={"name": "ner 23"})
    assert r.status_code == 409 and "consolidate" in r.json()["detail"]
    # A pair an earlier version allowed is flagged on both rows.
    r = client.post(f"/api/projects/{pid}/ners/{idb}/rename", json={"name": "NER23", "same_name_ok": True})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert migrate.flag_same_name_ners(db, db.get(Project, pid))["same_name_ners"] == 2
        assert any(v.startswith("name: another NER has the same name")
                   for v in db.get(NerAsset, ida).pending_validations)
    src = (SRC / "pages" / "NerRegister.tsx").read_text(encoding="utf-8")
    assert "is already the name of another NER" in src and "consolidateNers" in src


def test_d13_a_locked_ner_cannot_be_renamed(client):
    pid = _project("d13 locked")
    e = _ner(pid, "NER LOCK", 100, 120)
    with SessionLocal() as db:
        aid = db.get(Element, e).ner_asset_id
    assert client.post(f"/api/projects/{pid}/ners/{aid}/lock", json={"locked": True}).status_code == 200
    r = client.post(f"/api/projects/{pid}/ners/{aid}/rename", json={"name": "NER OTHER"})
    assert r.status_code == 422 and "locked" in r.json()["detail"]


# ---------------------------------------------------------------------------
# D9 / D10 — the interface
# ---------------------------------------------------------------------------

def test_d9_the_saved_project_is_not_forgotten_before_it_is_restored():
    src = (SRC / "App.tsx").read_text(encoding="utf-8")
    assert "if (restoreDone.current) localStorage.removeItem(\"ner.project\")" in src


def test_d10_the_viewer_starts_on_a_sheet_the_project_has():
    src = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    assert "|| 1; }" not in src
    assert "if (p.pages?.length && !p.pages.some((x: any) => x.number === page)) return;" in src


# ---------------------------------------------------------------------------
# D11 / D12 / D14 / D15
# ---------------------------------------------------------------------------

def test_d11_a_file_that_is_not_a_pdf_is_refused_and_not_kept(client):
    r = client.post("/api/projects", json={"name": "d11 bad pdf", "venue_code": "D11"})
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/drawings",
                    files={"file": ("fake.pdf", b"not a pdf at all", "application/pdf")})
    assert r.status_code == 422 and "could not be read as a PDF" in r.json()["detail"]
    assert "AppData" not in r.json()["detail"] and "uploads" not in r.json()["detail"]
    assert not list((settings.uploads_dir / f"project_{pid}").glob("fake*"))


def test_d12_project_names_are_trimmed_and_unique_whatever_the_case(client):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.post("/api/projects", json={"name": "  D12 Venue  "}).json()["name"] == "D12 Venue"
    assert client.post("/api/projects", json={"name": "d12 venue"}).status_code == 409


def test_d14_a_page_past_the_end_of_a_book_is_refused(client):
    pid, a, b = _two_books("d14 pages")
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": _key(b, 99), "kind": "TER", "label": "X", "x": 1, "y": 1})
    assert r.status_code == 404 and "has no page 99" in r.json()["detail"]


def test_d15_decisions_carried_counts_decisions_only():
    with SessionLocal() as db:
        pid = _project("d15 count")
        tf_id = db.execute(select(TeapSpace.teap_file_id)).first()
        p = db.get(Project, pid)
        from app.models import TeapFile
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        rows = [TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|P{i}", space_code=f"PRS.007.0{i}",
                          space_name="Photo", total_ports=1, lines=[], demand_type="photographer")
                for i in range(3)]
        db.add_all(rows)
        db.flush()
        carried = {r.space_key: {"cols": {c: None for c in S._DECISION_COLUMNS}, "links": [],
                                 "demand_type": "photographer"} for r in rows}
        assert S._lay_decisions(db, p, rows, carried) == 0, "the import's own photographer type"
        db.rollback()


# ---------------------------------------------------------------------------
# D16 — an access point follows the NER that serves its space
# ---------------------------------------------------------------------------

def test_d16_the_point_follows_the_nearest_rule_ner_of_its_space(client):
    """The RIV case: the space is served by the nearest NER to its label
    (NER NEAR SPACE); its access point is drawn nearer another NER (NER NEAR AP).
    Until 4.1.0 the point went to NER NEAR AP — its port on one NER, the point on
    another."""
    pid = _project("d16 follow")
    _room(pid, "SEC.016", "Screening", 100, 100)
    key = _teap(pid, "SEC.016", "Screening", OFFICE)
    _ner(pid, "NER NEAR SPACE", 100, 130)
    _ner(pid, "NER NEAR AP", 175, 100)
    _match(client, pid)
    _ap(client, pid, 165, 100, space_key=key)
    result = _analyse(pid)
    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER NEAR SPACE"]["wireless_ports"] == 1
    assert load["NER NEAR SPACE"]["wireless_points"] == 1
    assert load["NER NEAR AP"]["wireless_points"] == 0


def test_d16_the_point_of_a_space_with_no_ner_waits_with_it(client):
    pid = _project("d16 pending")
    _room(pid, "SEC.017", "Screening", 100, 100)
    key = _teap(pid, "SEC.017", "Screening", OFFICE)
    _ner(pid, "NER FAR", 900, 650)       # beyond 90 m of the space
    _ner(pid, "NER BY AP", 640, 640)     # near where the point is drawn
    _match(client, pid)
    _ap(client, pid, 630, 640, space_key=key)
    result = _analyse(pid)
    load = {v["label"]: v for v in result.ner_load.values()}
    assert sum(v["wireless_points"] for v in load.values()) == 0
    point = next(a for a in result.assignments if a.kind == "wireless_point")
    assert point.ner_key is None and any("has no NER yet" in r for r in point.reasons)
