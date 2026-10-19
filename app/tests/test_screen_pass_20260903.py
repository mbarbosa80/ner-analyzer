"""The 3 Sep 2026 screen pass — what changed on each step, pinned.

Marcelo walked the app screen by screen again and asked for six things:

1. **Scale** — one button that confirms every page at once, keeping the
   per-page controls.
2. **Drawing viewer** — a DIVA node, drawn like a TER / IDF / COW (visual only,
   never serves), in purple; calibrate and the zone tools gone; DIVA in the
   legend.
3. **NERs** — the two tabs ("On the drawing" / "Register") folded into one
   list with one name per room, an origin flag, editable criticality,
   lock / confirm / delete per row and lock-all / confirm-all.
4. **TEAP × drawing** — proof that re-running the matching keeps every
   decision, and the "N need review" figure counted *after* the decisions.
5. **Demand per space** — the serving-room rule: the TEAP's own column if
   it has one, then his choice, then the nearest room with free ports, then
   the nearest room anyway, flagged.
6. The visual-only markers reach the exported plan, so the legend rows for
   them describe something the sheet actually shows.
"""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-pass-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/pass.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402

from app import ner_register as R                                  # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain.coverage import NER, compute_coverage              # noqa: E402
from app.domain.demand import compute_demand                       # noqa: E402
from app.domain.distance import DemandType, DistanceRules, Status  # noqa: E402
from app.domain.geometry import Area, Point                        # noqa: E402
from app.domain.pdf_ingest import (ROOM_MARKER_RX, VISUAL_ONLY_KINDS,  # noqa: E402
                                   ElementKind, TextItem, _classify_marker)
from app.domain.teap_import import CANONICAL_FIELDS, TeapImport, TeapRow  # noqa: E402
from app.domain.units import Scale                                 # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Criticality, Drawing, Element, NerAsset, NerStatus,  # noqa: E402
                        Page, Project, TeapFile, TeapSpace)

RULES = DistanceRules()
SCALES = {1: Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

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


def _project(name: str, *, pages: int = 3, scales=(200.0, None, 200.0)) -> int:
    """A project with one drawing and ``pages`` pages; ``scales[i]`` is the
    detected denominator of page i+1, or None for a page nothing was read on."""
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="x" * 64, page_count=pages)
        db.add(d)
        db.flush()
        for i in range(pages):
            denom = scales[i] if i < len(scales) else 200.0
            db.add(Page(drawing_id=d.id, number=i + 1, width=1000, height=700,
                        metres_per_unit=(None if denom is None else denom * 0.0254 / 72),
                        scale_label=(None if denom is None else f"1:{denom:g}"),
                        scale_source=(None if denom is None else "detected"),
                        scale_confirmed=False))
        db.commit()
        return p.id


def _marker(pid: int, kind: str, label: str, *, page: int = 1, x: float = 100,
            y: float = 100, confirmed: bool = False) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=page, kind=kind,
                    label=label, x=x, y=y, origin="extracted", confidence=0.8,
                    confirmed=confirmed, evidence=[f"label text '{label}'"])
        db.add(e)
        db.commit()
        from app import migrate
        migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        return e.id


def _asset_of(element_id: int) -> NerAsset | None:
    with SessionLocal() as db:
        e = db.get(Element, element_id)
        if e is None or e.ner_asset_id is None:
            return None
        a = db.get(NerAsset, e.ner_asset_id)
        db.refresh(a)
        db.expunge(a)
        return a


# ---------------------------------------------------------------------------
# 1. Scale — confirm every page at once
# ---------------------------------------------------------------------------

def test_confirm_all_confirms_what_was_detected_and_skips_what_was_not(client):
    pid = _project("scale-all", pages=3, scales=(200.0, None, 100.0))
    r = client.post(f"/api/projects/{pid}/pages/scale/confirm-all")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confirmed"] == [1, 3]
    assert body["skipped_no_scale"] == [2], \
        "a page with no scale is named, never given one"
    assert body["already_confirmed"] == []

    # Idempotent, and honest about it.
    again = client.post(f"/api/projects/{pid}/pages/scale/confirm-all").json()
    assert again["confirmed"] == [] and again["already_confirmed"] == [1, 3]

    project = client.get(f"/api/projects/{pid}").json()
    by_no = {p["number"]: p for p in project["pages"]}
    assert by_no[1]["scale_confirmed"] and by_no[3]["scale_confirmed"]
    assert not by_no[2]["scale_confirmed"], "page 2 still blocks its results"


def test_the_per_page_control_survives(client):
    """The one button is in addition to the row buttons, not instead of them."""
    pid = _project("scale-one", pages=2, scales=(None, None))
    r = client.post(f"/api/projects/{pid}/pages/2/scale",
                    json={"denominator": 250.0, "confirm": True})
    assert r.status_code == 200
    body = client.post(f"/api/projects/{pid}/pages/scale/confirm-all").json()
    assert body["already_confirmed"] == [2] and body["skipped_no_scale"] == [1]


# ---------------------------------------------------------------------------
# 2. The DIVA node
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["DIVA Node", "DIVA NODE", "DIVA Node Rack",
                                  "DIVA Node 2", "DIVA 3"])
def test_the_extractor_reads_a_diva_node_as_it_is_printed(text):
    """The ALA and HND books print it as "DIVA Node", "DIVA NODE" and
    "DIVA Node Rack" — all three are the same kind of thing."""
    item = TextItem(text=text, x=10, y=10, x0=0, y0=0, x1=40, y1=12, page=1,
                    size=8, color=0)
    el = _classify_marker(item)
    assert el is not None and el.kind == ElementKind.DIVA


def test_a_note_that_merely_mentions_diva_is_not_a_marker():
    item = TextItem(text="for DIVA &", x=10, y=10, x0=0, y0=0, x1=40, y1=12, page=1,
                    size=8, color=0)
    assert _classify_marker(item) is None
    assert ROOM_MARKER_RX.match("SPACE FOR DIVA NODE RACK") is None


def test_a_diva_node_is_visual_only_like_a_ter():
    """Never a register row, never a room that serves, never a reach circle."""
    from app.domain.coverage import SERVING_KINDS
    from app.migrate import ASSET_KINDS
    assert ElementKind.DIVA in VISUAL_ONLY_KINDS
    assert ElementKind.DIVA not in ASSET_KINDS
    assert ElementKind.DIVA not in SERVING_KINDS
    diva = NER(key="D", label="DIVA Node", kind=ElementKind.DIVA,
               point=Point(12.0, 0.0, 1), total_ports=96)
    ner = NER(key="N", label="NER 1", kind=ElementKind.NER_NONCRITICAL,
              point=Point(60.0, 0.0, 1), total_ports=96)
    res = compute_coverage(
        areas=[(Area(key="A", name="A", page=1, label_point=Point(10, 0, 1)),
                4.0, DemandType.GENERAL, None, True)],
        ners=[diva, ner], scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].ner_key == "N"
    assert "D" not in res.ner_load


def test_a_diva_node_placed_by_hand_never_enters_the_register(client):
    pid = _project("diva-hand")
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": "DIVA", "label": "DIVA Node 1",
                          "x": 50, "y": 50})
    assert r.status_code == 201, r.text
    assert r.json()["ner_asset_id"] is None
    ners = client.get(f"/api/projects/{pid}/ners").json()["ners"]
    assert all(n["kind"] != "DIVA" for n in ners)
    els = client.get(f"/api/projects/{pid}/elements").json()
    assert [e["kind"] for e in els] == ["DIVA"]


def test_the_visual_only_markers_reach_the_exported_plan():
    """A TER on the screen and missing from the paper, under a legend that
    lists TER, was the state before 3 Sep 2026."""
    pid = _project("markers-on-paper")
    _marker(pid, "TER", "TER", x=10, y=10)
    _marker(pid, "DIVA", "DIVA Node", x=20, y=20)
    _marker(pid, "NER_NONCRITICAL", "NER 1", x=30, y=30)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        drawn = S.markers_to_draw(db, p)
        assert sorted(n.label for n in drawn) == ["DIVA Node", "TER"]
        assert all(not n.can_serve for n in drawn)
        assert all(n.kind in VISUAL_ONLY_KINDS for n in drawn)
        # The NER comes through the register, not through this list — it would
        # otherwise be drawn twice.
        assert all(n.label != "NER 1" for n in drawn)
        assert [n.label for n in S.register_ners(db, p)] == ["NER 1"]


# ---------------------------------------------------------------------------
# 3. One NERs screen
# ---------------------------------------------------------------------------

def test_a_row_says_where_it_came_from_and_carries_the_marker_evidence(client):
    pid = _project("one-screen")
    e_id = _marker(pid, "NER_CRITICAL", "Critical NER 4", x=10, y=10)
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": "NER_NONCRITICAL", "label": "NER 9",
                          "x": 50, "y": 50})
    assert r.status_code == 201
    rows = {n["display_name"]: n for n in client.get(f"/api/projects/{pid}/ners").json()["ners"]}
    assert rows["Critical NER 4"]["origin"] == "vdb_detection"
    assert rows["NER 9"]["origin"] == "manual"
    assert rows["Critical NER 4"]["classification"] == "critical"
    assert rows["Critical NER 4"]["confirmed"] is False
    occ = rows["Critical NER 4"]["occurrences"][0]
    assert occ["id"] == e_id and occ["evidence"] == ["label text 'Critical NER 4'"]
    assert occ["confirmed"] is False


def test_renaming_the_room_relabels_its_marker_and_keeps_the_old_name(client):
    pid = _project("rename")
    e_id = _marker(pid, "NER_NONCRITICAL", "NER 3", x=10, y=10)
    a = _asset_of(e_id)
    r = client.post(f"/api/projects/{pid}/ners/{a.id}/rename",
                    json={"name": "NER 03-A", "reason": "renumbered"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Element, e_id).label == "NER 03-A", "one name, on the sheet too"
        a2 = db.get(NerAsset, a.id)
        assert a2.display_name == "NER 03-A" and "NER 3" in (a2.aliases or [])
        assert a2.previous_name == "NER 3"
    # and the other way round: relabelling the marker renames the room
    r = client.patch(f"/api/projects/{pid}/elements/{e_id}", json={"label": "NER 03-B"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(NerAsset, a.id).display_name == "NER 03-B"


def test_choosing_the_criticality_confirms_it_and_repaints_the_marker(client):
    pid = _project("criticality")
    e_id = _marker(pid, "NER_NONCRITICAL", "NER 3", x=10, y=10)
    a = _asset_of(e_id)
    r = client.post(f"/api/projects/{pid}/ners/{a.id}/classify",
                    json={"classification": "critical", "confirmed": True})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "NER_CRITICAL"
    with SessionLocal() as db:
        assert db.get(Element, e_id).kind == "NER_CRITICAL", \
            "the viewer paints the marker in the colour of its own kind"
        p = db.get(Project, pid)
        assert [n.critical for n in S.register_ners(db, p)] == [True], \
            "the engine serves from the confirmed classification"


def test_confirm_signs_off_the_criticality_and_every_marker(client):
    pid = _project("confirm")
    e1 = _marker(pid, "NER_NONCRITICAL", "NER 5", page=1, x=10, y=10)
    a = _asset_of(e1)
    r = client.post(f"/api/projects/{pid}/ners/{a.id}/confirm", json={"confirmed": True})
    assert r.status_code == 200, r.text
    assert r.json()["confirmed"] is True
    with SessionLocal() as db:
        e = db.get(Element, e1)
        assert e.confirmed and e.link_status == "confirmed"
        assert db.get(NerAsset, a.id).classification_confirmed
    row = next(n for n in client.get(f"/api/projects/{pid}/ners").json()["ners"]
               if n["id"] == a.id)
    assert row["confirmed"] is True
    assert "criticality not confirmed by a human" not in row["pending_validations"]

    r = client.post(f"/api/projects/{pid}/ners/{a.id}/confirm", json={"confirmed": False})
    assert r.json()["confirmed"] is False


def test_a_pending_criticality_cannot_be_confirmed(client):
    pid = _project("confirm-pending")
    e1 = _marker(pid, "NER_NONCRITICAL", "NER 5", x=10, y=10)
    a = _asset_of(e1)
    with SessionLocal() as db:
        db.get(NerAsset, a.id).classification = Criticality.PENDING
        db.commit()
    r = client.post(f"/api/projects/{pid}/ners/{a.id}/confirm", json={"confirmed": True})
    assert r.status_code == 422
    assert "choose critical or non-critical" in r.json()["detail"]


def test_lock_all_and_confirm_all_write_one_audit_row_per_room(client):
    pid = _project("bulk")
    for i, kind in enumerate(("NER_NONCRITICAL", "NER_CRITICAL", "NER_NONCRITICAL")):
        _marker(pid, kind, f"NER {i}", x=10 + 20 * i, y=10)
    r = client.post(f"/api/projects/{pid}/ners/bulk", json={"action": "lock"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 3
    r = client.post(f"/api/projects/{pid}/ners/bulk", json={"action": "confirm"})
    assert r.json()["changed"] == 3 and r.json()["skipped"] == []
    rows = client.get(f"/api/projects/{pid}/ners").json()["ners"]
    assert all(n["locked"] and n["confirmed"] for n in rows)
    # second time round there is nothing to do, and it says so
    assert client.post(f"/api/projects/{pid}/ners/bulk",
                       json={"action": "confirm"}).json()["changed"] == 0
    audit = client.get(f"/api/projects/{pid}/audit").json()
    assert sum(1 for a in audit if a["action"] == "ner.locked") == 3
    assert sum(1 for a in audit if a["action"] == "ner.confirmed") == 3
    assert client.post(f"/api/projects/{pid}/ners/bulk",
                       json={"action": "unlock"}).json()["changed"] == 3
    assert client.post(f"/api/projects/{pid}/ners/bulk",
                       json={"action": "explode"}).status_code == 422


def test_a_deleted_ner_leaves_the_drawing_and_comes_back_on_restore(client):
    pid = _project("delete")
    e1 = _marker(pid, "NER_NONCRITICAL", "NER 7", x=10, y=10)
    a = _asset_of(e1)
    r = client.post(f"/api/projects/{pid}/ners/{a.id}/remove",
                    json={"reason": "not in the revised design"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/projects/{pid}/elements").json() == [], \
        "the viewer must not keep drawing a room the study no longer contains"
    assert [n["id"] for n in client.get(f"/api/projects/{pid}/ners").json()["ners"]] == []
    with SessionLocal() as db:
        assert db.get(Element, e1) is not None, "nothing is deleted — the audit needs it"
        p = db.get(Project, pid)
        assert S.register_ners(db, p) == [] or all(
            n.key != f"A{a.id}" for n in S.register_ners(db, p))
    r = client.post(f"/api/projects/{pid}/ners/{a.id}/restore")
    assert r.status_code == 200
    assert [e["id"] for e in client.get(f"/api/projects/{pid}/elements").json()] == [e1]


def test_reclassifying_a_ner_marker_as_a_ter_retires_its_row(client):
    pid = _project("kind-change")
    e1 = _marker(pid, "NER_NONCRITICAL", "NER 8", x=10, y=10)
    a = _asset_of(e1)
    r = client.patch(f"/api/projects/{pid}/elements/{e1}", json={"kind": "TER"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        e = db.get(Element, e1)
        assert e.kind == "TER" and e.ner_asset_id is None
        a2 = db.get(NerAsset, a.id)
        assert a2.deleted_at is not None and "re-classified" in a2.deleted_reason
    assert client.get(f"/api/projects/{pid}/ners").json()["ners"] == []
    # and back: a TER re-read as a NER enters the register at once
    r = client.patch(f"/api/projects/{pid}/elements/{e1}", json={"kind": "NER_CRITICAL"})
    assert r.status_code == 200, r.text
    rows = client.get(f"/api/projects/{pid}/ners").json()["ners"]
    assert len(rows) == 1 and rows[0]["classification"] == "critical"
    assert client.patch(f"/api/projects/{pid}/elements/{e1}",
                        json={"kind": "BANANA"}).status_code == 422


# ---------------------------------------------------------------------------
# 4. TEAP × drawing — the figures count the decisions
# ---------------------------------------------------------------------------

def test_the_review_count_is_taken_after_the_decisions_are_laid_back(client):
    """On his real database every decision survived every re-run — verified
    on three projects, 154 decisions, zero rows changed. What did *not*
    survive was the message: "30 need review" after a run on a project whose
    thirty rows had all been confirmed. That figure came from the matcher,
    which cannot know about confirmations. It is now counted afterwards."""
    from app.models import DrawingSpace, SpaceMatchRow
    pid = _project("stats")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        tf = TeapFile(project_id=pid, filename="t.xlsx", stored_path=f"{TMP}/t.xlsx",
                      sha256="y" * 64)
        db.add(tf)
        db.flush()
        for i in range(4):
            db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|PRS.00{i}",
                             space_code=f"PRS.00{i}", space_name=f"Press room {i}",
                             total_ports=4.0))
            db.add(DrawingSpace(project_id=pid, drawing_id=p.drawings[0].id, page=1,
                                space_code=f"PRS.00{i}.01", name=f"Press room {i}",
                                x=10 * i, y=10, confidence=0.9))
        db.commit()

    first = client.post(f"/api/projects/{pid}/matching/run").json()["stats"]
    assert first["matched"] == 4
    assert first["needs_review"] == 4, "base-code matches wait for a person"

    rows = client.get(f"/api/projects/{pid}/matches").json()
    for m in rows:
        assert client.patch(f"/api/projects/{pid}/matches/{m['id']}",
                            json={"confirmed": True, "drawing_space_id": m["drawing_space_id"],
                                  "justification": "reviewed"}).status_code == 200

    second = client.post(f"/api/projects/{pid}/matching/run").json()["stats"]
    assert second["matched"] == 4
    assert second["needs_review"] == 0, "the decisions were kept, so say so"
    assert second["confirmed"] == 4
    assert second["decisions_kept"] == 4
    assert second["matcher_needs_review"] == 4, "the raw figure is still there"
    assert all(m["confirmed"] for m in client.get(f"/api/projects/{pid}/matches").json())


# ---------------------------------------------------------------------------
# 5. The serving-room rule
# ---------------------------------------------------------------------------

def _teap(rows: list[dict]) -> TeapImport:
    mapping = {k: k for k in rows[0]}
    return TeapImport(source="t", sheet="s", mapping=mapping,
                      rows=[TeapRow(row_number=i + 2, sheet="s", values=r)
                            for i, r in enumerate(rows)])


def test_the_teap_column_is_optional_and_carefully_named():
    assert "serving_ner" in CANONICAL_FIELDS
    assert "ner" not in CANONICAL_FIELDS["serving_ner"], \
        "a bare 'ner' would claim the Critical NER / Non-Critical NER tick columns"


def test_a_teap_that_names_the_room_is_read_verbatim():
    imp = _teap([
        {"space_code": "PRS.001", "space_name": "Press", "network_ports": 4,
         "serving_ner": "NER 03"},
        {"space_code": "PRS.001", "space_name": "Press", "network_ports": 2,
         "serving_ner": "NER 03"},
        {"space_code": "PRS.002", "space_name": "Mixed zone", "network_ports": 2,
         "serving_ner": ""},
    ])
    by = {d.space_code: d for d in compute_demand(imp)}
    assert by["PRS.001"].serving_ner == "NER 03"
    assert by["PRS.002"].serving_ner is None


def test_two_different_rooms_on_one_space_is_a_contradiction_in_the_teap():
    imp = _teap([
        {"space_code": "PRS.001", "space_name": "Press", "network_ports": 4,
         "serving_ner": "NER 3"},
        {"space_code": "PRS.001", "space_name": "Press", "network_ports": 2,
         "serving_ner": "NER 4"},
    ])
    d = compute_demand(imp)[0]
    assert d.serving_ner == "NER 3"
    assert any("more than one NER" in w for w in d.warnings)


def test_the_teap_room_is_resolved_by_name_and_pins_the_space(client):
    pid = _project("teap-pin")
    e1 = _marker(pid, "NER_NONCRITICAL", "NER 3", x=10, y=10)
    _marker(pid, "NER_NONCRITICAL", "NER 4", x=200, y=10)
    a3 = _asset_of(e1)
    with SessionLocal() as db:
        tf = TeapFile(project_id=pid, filename="t.xlsx", stored_path=f"{TMP}/t.xlsx",
                      sha256="y" * 64)
        db.add(tf)
        db.flush()
        db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key="TST|PRS.001",
                         space_code="PRS.001", space_name="Press", total_ports=4.0,
                         teap_serving_ner="NER 03"))          # 03 finds 3
        db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key="TST|PRS.002",
                         space_code="PRS.002", space_name="Mixed", total_ports=4.0,
                         teap_serving_ner="NER 99"))          # nobody home
        db.commit()
        p = db.get(Project, pid)
        pins, sources = S.pin_map(db, p)
        assert pins == {"TST|PRS.001": f"A{a3.id}"}
        assert sources == {"TST|PRS.001": "the TEAP"}
        assert S.resolve_teap_ner_names(db, p) == {"TST|PRS.001": a3.id,
                                                   "TST|PRS.002": None}
    body = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    rows = {r["space_key"]: r for r in body["spaces"]}
    assert rows["TST|PRS.001"]["teap_ner"] == "NER 03"
    assert rows["TST|PRS.001"]["teap_ner_asset_id"] == a3.id
    assert rows["TST|PRS.001"]["teap_ner_name"] == "NER 3"
    assert rows["TST|PRS.002"]["teap_ner"] == "NER 99"
    assert rows["TST|PRS.002"]["teap_ner_asset_id"] is None
    assert body["teap_named"] == 2 and body["teap_unresolved"] == 1

    # a person's choice still outranks the TEAP, and the row says whose it was
    r = client.post(f"/api/projects/{pid}/spaces/TST|PRS.001/assign",
                    json={"ner_asset_id": _asset_of(e1).id + 1, "justification": "full"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        pins, sources = S.pin_map(db, db.get(Project, pid))
        assert sources["TST|PRS.001"] == "you"


def test_the_engine_says_the_teap_named_the_room():
    ner = NER(key="A1", label="NER 3", kind=ElementKind.NER_NONCRITICAL,
              point=Point(60.0, 0.0, 1), total_ports=96)
    near = NER(key="A2", label="NER 4", kind=ElementKind.NER_NONCRITICAL,
               point=Point(12.0, 0.0, 1), total_ports=96)
    res = compute_coverage(
        areas=[(Area(key="S", name="S", page=1, label_point=Point(10, 0, 1)),
                4.0, DemandType.GENERAL, None, True)],
        ners=[ner, near], scale_for_page=SCALES, rules=RULES,
        pinned={"S": "A1"}, pin_sources={"S": "the TEAP"})
    a = res.assignments[0]
    assert a.ner_key == "A1" and a.pinned
    assert "the TEAP names it" in " ".join(a.reasons)


def test_the_full_rule_end_to_end():
    """TEAP → your choice → nearest with free ports → next nearest → nearest
    anyway, flagged. One engine call, five spaces, each on a different leg."""
    ners = [NER(key="N1", label="N1", kind=ElementKind.NER_NONCRITICAL,
                point=Point(0, 0, 1), total_ports=8),
            NER(key="N2", label="N2", kind=ElementKind.NER_NONCRITICAL,
                point=Point(40, 0, 1), total_ports=100),
            NER(key="N3", label="N3", kind=ElementKind.NER_NONCRITICAL,
                point=Point(400, 0, 1), total_ports=100)]

    def sp(key, x, ports):
        return (Area(key=key, name=key, page=1, label_point=Point(x, 0, 1)),
                ports, DemandType.GENERAL, None, True)

    res = compute_coverage(
        areas=[sp("TEAP", 5, 2), sp("YOU", 6, 2), sp("NEAREST", 7, 2),
               sp("SECOND", 8, 5), sp("FAR", 300, 2)],
        ners=ners, scale_for_page=SCALES, rules=RULES,
        pinned={"TEAP": "N2", "YOU": "N2"},
        pin_sources={"TEAP": "the TEAP", "YOU": "you"})
    by = {a.space_key: a for a in res.assignments}
    assert by["TEAP"].ner_key == "N2" and "the TEAP names it" in " ".join(by["TEAP"].reasons)
    assert by["YOU"].ner_key == "N2" and "you assigned it" in " ".join(by["YOU"].reasons)
    # SECOND (5 ports) is served first — largest demand first — and takes N1
    # down to 3 free; NEAREST (2 ports) then still fits in N1.
    assert by["SECOND"].ner_key == "N1" and by["NEAREST"].ner_key == "N1"
    # nothing within 90 m of FAR: no room, but the nearest is named
    assert by["FAR"].ner_key is None and by["FAR"].status is Status.OUT_OF_LIMIT
    assert by["FAR"].nearest_label == "N3"
    assert by["FAR"].nearest_distance_m == pytest.approx(100.0)

    # and the last leg: everything within reach is full → nearest anyway
    res2 = compute_coverage(
        areas=[sp("A", 5, 50)],
        ners=[NER(key="FULL", label="FULL", kind=ElementKind.NER_NONCRITICAL,
                  point=Point(0, 0, 1), total_ports=8)],
        scale_for_page=SCALES, rules=RULES)
    a = res2.assignments[0]
    assert a.ner_key == "FULL" and a.status is Status.INSUFFICIENT_CAPACITY
    assert res2.ner_load["FULL"]["utilisation_pct"] > 100
    assert res2.exceptions[0]["status"] == "insufficient_capacity"
