"""Tests for the four defects found in real use, and the machinery added to fix them.

Every case here traces back to something that actually went wrong when the tool was
pointed at a real venue design book and a real master allocation plan.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-guard-")
os.environ["NER_DATA_DIR"] = TMP
os.environ["NER_DATABASE_URL"] = f"sqlite:///{TMP}/guard.sqlite3"

from fastapi.testclient import TestClient                       # noqa: E402

from app.db import init_db                                      # noqa: E402
from app.domain.distance import DemandType, DistanceRules       # noqa: E402
from app.domain.geometry import Point                           # noqa: E402
from app.domain.matching import (MatchMethod, MatchSettings, match_spaces)  # noqa: E402
from app.domain.pdf_ingest import DetectedSpace                 # noqa: E402
from app.domain.teap_import import preview_venues, profile_workbook  # noqa: E402
from app.domain.units import Scale                              # noqa: E402
from app.main import app                                        # noqa: E402
from app.sample_data import build_all                           # noqa: E402


def _sign_in(client: TestClient) -> None:
    """Sign the test client in. Every API call needs an account from V2.1 on.

    The engine is a module-level singleton, so every test module in one pytest
    run shares one database and only the first of them can use the bootstrap
    endpoint. Creating the account through the service layer when it is missing
    keeps this independent of which module happens to import first.
    """
    from app import auth as A
    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            A.create_user(db, username="tester", password="a-long-test-phrase",
                          display_name="Test User", is_admin=True, actor="tests")
        except A.AuthError:
            pass                                   # already there
    r = client.post("/api/auth/login",
                    json={"username": "tester", "password": "a-long-test-phrase"})
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def samples():
    return build_all(str(Path(TMP) / "samples"))


@pytest.fixture(scope="module")
def client():
    init_db()
    c = TestClient(app)
    _sign_in(c)
    return c


def space(code, name, page, x=10.0, y=10.0):
    return DetectedSpace(space_code=code, name=name, page=page, x=x, y=y, confidence=0.9)


def unit_scale():
    return Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=True)


# ---------------------------------------------------------------------------
# 1. The venue trap
# ---------------------------------------------------------------------------

def test_preview_lists_every_venue_in_the_sheet(samples):
    best = profile_workbook(samples["teap"])[0]
    venues = preview_venues(samples["teap"], best.name, best.header_row,
                            best.proposed_mapping)
    assert venues
    assert venues[0]["venue_code"] == "SYN"
    assert venues[0]["rows"] > 0


def _upload_pair(client, name, venue_code, samples):
    pid = client.post("/api/projects",
                      json={"name": name, "venue_code": venue_code}).json()["id"]
    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap", files={"file": ("teap.xlsx", fh)})
    return pid, r.json()["id"], r.json()["proposed"]


def test_a_multi_venue_sheet_is_refused_without_a_filter(client, samples, monkeypatch):
    """The reference workbook covers 96 venues; importing all of them against one
    venue's drawings produced 5,543 spaces instead of 115 and hung the optimiser."""
    import app.services as S
    pid, tid, proposed = _upload_pair(client, "Refusal test", None, samples)
    monkeypatch.setattr(S, "preview_venues", lambda *a, **k: [
        {"venue_code": "SYN", "venue_name": "Synthetic", "rows": 30},
        {"venue_code": "OTH", "venue_name": "Other Venue", "rows": 40},
    ])
    r = client.post(f"/api/projects/{pid}/teap/{tid}/import",
                    json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"]})
    assert r.status_code == 422
    assert "2 venues" in r.json()["detail"]
    assert "venue filter" in r.json()["detail"]


def test_the_projects_venue_code_becomes_the_default_filter(client, samples):
    pid, tid, proposed = _upload_pair(client, "Default filter test", "SYN", samples)
    r = client.post(f"/api/projects/{pid}/teap/{tid}/import",
                    json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"]})
    assert r.status_code == 200, r.text
    assert r.json()["venue_filter"] == "SYN"
    assert r.json()["spaces"] > 0


def test_all_venues_can_still_be_imported_when_asked_explicitly(client, samples,
                                                                monkeypatch):
    import app.services as S
    pid, tid, proposed = _upload_pair(client, "Explicit all venues", None, samples)
    monkeypatch.setattr(S, "preview_venues", lambda *a, **k: [
        {"venue_code": "SYN", "venue_name": "Synthetic", "rows": 30},
        {"venue_code": "OTH", "venue_name": "Other", "rows": 40},
    ])
    r = client.post(f"/api/projects/{pid}/teap/{tid}/import",
                    json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"], "allow_all_venues": True})
    assert r.status_code == 200, r.text
    assert r.json()["venue_filter"] is None


def test_venue_preview_endpoint_suggests_the_projects_venue(client, samples):
    pid, tid, proposed = _upload_pair(client, "Preview endpoint", "SYN", samples)
    r = client.post(f"/api/projects/{pid}/teap/{tid}/preview-venues",
                    json={"sheet": proposed["sheet"],
                          "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"]})
    assert r.status_code == 200
    assert r.json()["suggested"] == "SYN"
    assert r.json()["count"] >= 1


# ---------------------------------------------------------------------------
# 2. The optimiser had no ceiling — and now has no optimiser
#
# Three cases stood here, pinning a guard that refused an oversized CP-SAT model
# instead of pegging a core for minutes with no feedback. They went with the
# solver. The venue guard above is what survives of that episode, and it is the
# half that mattered: the model got oversized because a multi-venue TEAP was
# imported whole, and that is still refused.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 3. The same code on a key plan and a detail plan is not ambiguity
# ---------------------------------------------------------------------------

def test_a_code_on_a_key_plan_and_a_detail_plan_resolves_to_the_detail_sheet():
    """36 of 41 review items on the reference venue were exactly this case."""
    drawing = [space("TEC.004", "Technology Storage", page=1)]        # key plan
    drawing += [space(f"SPT.{n:03d}", f"Room {n}", page=8) for n in range(1, 30)]
    drawing += [space("TEC.004", "Technology Storage", page=8)]       # detail plan
    st = MatchSettings(page_scale_denominator={1: 1500.0, 8: 200.0})
    rep = match_spaces([("k", "TEC.004", "Technology Storage", None, None)], drawing, st)
    m = rep.matches[0]
    assert m.best.drawing_space.page == 8
    assert m.confirmed is True
    assert m not in rep.needs_review
    assert any("detail sheet" in n for n in m.notes)


def test_scale_alone_is_enough_to_pick_the_detail_sheet():
    drawing = [space("TEC.004", "Technology Storage", page=1),
               space("TEC.004", "Technology Storage", page=2)]
    st = MatchSettings(page_scale_denominator={1: 1500.0, 2: 200.0})
    rep = match_spaces([("k", "TEC.004", "Technology Storage", None, None)], drawing, st)
    assert rep.matches[0].best.drawing_space.page == 2


def test_genuinely_tied_pages_stay_ambiguous_and_go_to_a_human():
    drawing = [space("TEC.004", "Technology Storage", page=1),
               space("TEC.004", "Technology Storage", page=2)]
    rep = match_spaces([("k", "TEC.004", "Technology Storage", None, None)], drawing,
                       MatchSettings())          # no scale information at all
    m = rep.matches[0]
    assert m.confirmed is False
    assert m in rep.needs_review
    assert any("ambiguous" in n for n in m.notes)


def test_page_preference_can_be_switched_off():
    drawing = [space("TEC.004", "Technology Storage", page=1)]
    drawing += [space(f"X.{n:03d}", f"R{n}", page=8) for n in range(1, 20)]
    drawing += [space("TEC.004", "Technology Storage", page=8)]
    st = MatchSettings(prefer_detail_pages=False)
    rep = match_spaces([("k", "TEC.004", "Technology Storage", None, None)], drawing, st)
    assert rep.matches[0].confirmed is False


# ---------------------------------------------------------------------------
# 4. Placeholder codes were a dead end even when they carried real demand
# ---------------------------------------------------------------------------

def test_a_placeholder_code_still_matches_on_its_name():
    """PRS.DUM.099 'Main Photo Position - FOP' carries 110 ports under the 70 m
    limit — the largest single demand in the reference venue. It used to vanish."""
    drawing = [space(None, "Main Photo Position - FOP", page=3)]
    rep = match_spaces([("k", "PRS.DUM.099", "Main Photo Position - FOP", None, None)],
                       drawing)
    assert rep.matches, "the placeholder must not be a dead end"
    m = rep.matches[0]
    assert m.best.drawing_space.name == "Main Photo Position - FOP"
    assert m.confirmed is False, "a placeholder always needs human confirmation"
    assert any("placeholder" in n for n in m.notes)
    assert m in rep.placeholders


def test_a_placeholder_with_no_name_match_says_what_to_do():
    rep = match_spaces([("k", "LOG.DUM.004", "Nothing like this on the plan", None, None)],
                       [space("ACR.001", "Accreditation", page=1)])
    assert rep.unmatched_teap
    assert "assign the room manually" in rep.unmatched_teap[0].exception


def test_unresolved_spaces_are_ranked_by_the_ports_riding_on_them():
    teap = [("small", "AAA.DUM.001", "Nowhere Store", None, None),
            ("big", "PRS.DUM.099", "Nowhere Photo Position", None, None)]
    rep = match_spaces(teap, [space("ZZZ.001", "Unrelated", page=1)],
                       demand_by_key={"small": 1.0, "big": 110.0})
    assert [m.teap_key for m in rep.unmatched_teap] == ["big", "small"]
    assert [m.teap_key for m in rep.placeholders] == ["big", "small"]


# ---------------------------------------------------------------------------
# 5. The curated alias dictionary
# ---------------------------------------------------------------------------

def test_a_curated_alias_beats_everything_else():
    """No similarity metric will ever connect 'OFFIC2' to 'Observer Office 2'."""
    drawing = [space("OBS.033", "Observer Office 2", page=4),
               space("OBS.099", "Office Store", page=4)]
    st = MatchSettings(code_aliases={"OBS.33.01": "OBS.033"})
    rep = match_spaces([("k", "OBS.33.01", "OFFIC2", None, None)], drawing, st)
    m = rep.matches[0]
    assert m.best.method is MatchMethod.ALIAS
    assert m.best.drawing_space.space_code == "OBS.033"
    assert m.confirmed is True
    assert "curated alias" in m.best.reason


def test_a_name_alias_works_for_a_cryptic_teap_name():
    drawing = [space("BRS.077", "Broadcast Information Office", page=2)]
    st = MatchSettings(name_aliases={"bioca1b": "Broadcast Information Office"})
    rep = match_spaces([("k", "BRS.DUM.077", "BIOCA1b", None, None)], drawing, st)
    assert rep.matches[0].best.method is MatchMethod.ALIAS


def test_alias_crud_and_reuse_across_projects(client, samples):
    pid = client.post("/api/projects", json={"name": "Alias CRUD"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/aliases",
                    json={"kind": "code", "teap_value": "OBS.33.01",
                          "drawing_value": "OBS.033", "note": "observer office 2",
                          "global_scope": True, "demand_hint": 8.0})
    assert r.status_code == 201
    listed = client.get(f"/api/projects/{pid}/aliases").json()
    assert any(a["teap_value"] == "OBS.33.01" and a["global_scope"] for a in listed)

    # a different project sees the global alias
    other = client.post("/api/projects", json={"name": "Alias reuse"}).json()["id"]
    assert any(a["teap_value"] == "OBS.33.01"
               for a in client.get(f"/api/projects/{other}/aliases").json())

    exported = client.get(f"/api/projects/{pid}/aliases/export").json()
    assert exported["version"] == 1 and exported["aliases"]

    third = client.post("/api/projects", json={"name": "Alias import"}).json()["id"]
    r = client.post(f"/api/projects/{third}/aliases/import",
                    json={"aliases": exported["aliases"], "as_global": False})
    assert r.status_code == 200

    alias_id = [a for a in listed if a["teap_value"] == "OBS.33.01"][0]["id"]
    assert client.delete(f"/api/projects/{pid}/aliases/{alias_id}").status_code == 204


def test_alias_suggestions_are_ranked_by_ports(client, samples):
    """The curation worklist must put the biggest demand first, not an arbitrary row."""
    pid = client.post("/api/projects",
                      json={"name": "Suggestions", "venue_code": "SYN"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true", files={"file": ("p.pdf", fh)})
    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap", files={"file": ("t.xlsx", fh)})
    tid, proposed = r.json()["id"], r.json()["proposed"]
    client.post(f"/api/projects/{pid}/teap/{tid}/import",
                json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                      "mapping": proposed["mapping"]})
    client.post(f"/api/projects/{pid}/matching/run")
    sugg = client.get(f"/api/projects/{pid}/aliases/suggestions").json()
    ports = [s["ports"] for s in sugg]
    assert ports == sorted(ports, reverse=True)


# ---------------------------------------------------------------------------
# 6. Jobs: progress, completion and cancellation
# ---------------------------------------------------------------------------

def _wait(client, job_id, timeout=90.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/jobs/{job_id}").json()
        if not last["running"]:
            return last
        time.sleep(0.15)
    return last


def test_a_drawing_is_ingested_as_a_job_with_progress(client, samples):
    pid = client.post("/api/projects", json={"name": "Job ingest"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings?background=true&place_ners=true",
                        files={"file": ("plan.pdf", fh)})
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    assert r.json()["background"] is True

    final = _wait(client, job_id)
    assert final["state"] == "done", final
    assert final["progress"] == 1.0
    assert final["result"]["page_count"] == 3
    assert "pages" in final["stage"] or final["stage"] == "finished"

    listed = client.get(f"/api/projects/{pid}/jobs").json()
    assert listed and listed[0]["kind"] == "drawing.ingest"


def test_a_failing_job_reports_the_error_instead_of_disappearing(client, samples):
    pid = client.post("/api/projects", json={"name": "Job failure"}).json()["id"]
    # matching with nothing imported is a user-correctable error
    r = client.post(f"/api/projects/{pid}/matching/run?background=true")
    final = _wait(client, r.json()["job_id"])
    assert final["state"] == "error"
    assert "TEAP" in final["error"] or "drawing" in final["error"]


def test_a_job_can_be_cancelled(client, samples):
    pid = client.post("/api/projects", json={"name": "Job cancel"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings?background=true&place_ners=true",
                        files={"file": ("plan.pdf", fh)})
    job_id = r.json()["job_id"]
    client.post(f"/api/jobs/{job_id}/cancel")
    final = _wait(client, job_id)
    assert final["state"] in ("cancelled", "done")
    if final["state"] == "cancelled":
        assert "cancel" in final["stage"]


def test_cancelling_a_finished_job_is_reported_not_pretended(client, samples):
    pid = client.post("/api/projects", json={"name": "Job late cancel"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/matching/run?background=true")
    job_id = r.json()["job_id"]
    _wait(client, job_id)
    body = client.post(f"/api/jobs/{job_id}/cancel").json()
    assert body["cancelled"] is False
    assert "already finished" in body["detail"]


def test_an_unknown_job_is_a_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# 7. The two tie-break defects the real venue exposed after the first fix
# ---------------------------------------------------------------------------

def test_a_code_labelled_twice_on_one_sheet_is_not_ambiguity():
    """EVM.001, SPT.200, DOP.001.02 and five others: the same code tagged more than
    once on a single sheet. There is no question of which sheet, so no human is
    needed — the instance carrying the room's area figure is the real label."""
    drawing = [
        DetectedSpace(space_code="EVM.001", name="Event Operations Centre", page=8,
                      x=10, y=10, confidence=0.9),
        DetectedSpace(space_code="EVM.001", name="Event Operations Centre", page=8,
                      x=400, y=400, area_label="120 m²", confidence=0.9),
    ]
    drawing += [space(f"ZZ.{n:03d}", f"R{n}", page=8) for n in range(1, 20)]
    rep = match_spaces([("k", "EVM.001", "Event Operations Centre (EOC)", None, None)],
                       drawing, MatchSettings(page_scale_denominator={8: 200.0}))
    m = rep.matches[0]
    assert m.confirmed is True
    assert m.best.drawing_space.area_label == "120 m²"
    assert any("labelled 2 times on page 8" in n for n in m.notes)


def test_a_sub_index_difference_still_counts_as_the_same_room_for_the_tie_break():
    """PRS.006.02 on the TEAP against PRS.006.01 on the drawing. Requiring an exact
    code match here blocked the tie-break on 11 of 19 unresolved rooms."""
    drawing = [DetectedSpace(space_code="PRS.006.01", name="Press Tribune", page=33,
                             x=5, y=5, confidence=0.9)]
    drawing += [space(f"YY.{n:03d}", f"R{n}", page=8) for n in range(1, 30)]
    drawing += [DetectedSpace(space_code="PRS.006.03", name="Press Tribune", page=8,
                              x=9, y=9, confidence=0.9)]
    st = MatchSettings(page_scale_denominator={8: 200.0, 33: 200.0})
    rep = match_spaces([("k", "PRS.006.02", "Press Tribune - Tabled Positions", None, None)],
                       drawing, st)
    m = rep.matches[0]
    assert m.best.drawing_space.page == 8, "the denser sheet should win"
    assert any("detail sheet" in n for n in m.notes)


def test_a_marginal_page_rank_difference_is_not_treated_as_evidence():
    """Six SEC.005-* rooms sat at a 4% page-rank gap. That is noise, and calling it
    a decision would be silent over-confidence."""
    drawing = [space("SEC.005", "Security Post", page=21)]
    drawing += [space(f"AA.{n:03d}", f"R{n}", page=21) for n in range(1, 16)]
    drawing += [space("SEC.005", "Security Post", page=12)]
    drawing += [space(f"BB.{n:03d}", f"R{n}", page=12) for n in range(1, 15)]
    st = MatchSettings(page_scale_denominator={21: 200.0, 12: 200.0})
    rep = match_spaces([("k", "SEC.005-03", "Security Post", None, None)], drawing, st)
    m = rep.matches[0]
    assert m.confirmed is False
    assert any("ambiguous" in n and "none clearly more detailed" in n for n in m.notes)


def test_the_page_rank_margin_is_configurable():
    drawing = [space("SEC.005", "Security Post", page=21)]
    drawing += [space(f"AA.{n:03d}", f"R{n}", page=21) for n in range(1, 16)]
    drawing += [space("SEC.005", "Security Post", page=12)]
    drawing += [space(f"BB.{n:03d}", f"R{n}", page=12) for n in range(1, 15)]
    st = MatchSettings(page_scale_denominator={21: 200.0, 12: 200.0},
                       page_rank_margin=0.999)
    rep = match_spaces([("k", "SEC.005-03", "Security Post", None, None)], drawing, st)
    m = rep.matches[0]
    assert any("resolved to the detail sheet" in n for n in m.notes)
    assert not any("ambiguous" in n for n in m.notes)
    # Resolving WHICH SHEET does not resolve WHICH ROOM: the TEAP says SEC.005-03
    # and the drawing says SEC.005, and a sub-index difference still deserves a
    # human. The confidence stays at the base-code level on purpose.
    assert m.confirmed is False
    assert m.confidence == pytest.approx(0.90)


def test_bulk_confirm_by_method(client, samples):
    """21 identical judgements deserve one decision, not twenty-one clicks."""
    pid = client.post("/api/projects",
                      json={"name": "Bulk confirm", "venue_code": "SYN"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true", files={"file": ("p.pdf", fh)})
    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap", files={"file": ("t.xlsx", fh)})
    tid, proposed = r.json()["id"], r.json()["proposed"]
    client.post(f"/api/projects/{pid}/teap/{tid}/import",
                json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                      "mapping": proposed["mapping"]})
    client.post(f"/api/projects/{pid}/matching/run")

    # unconfirm everything so there is something to bulk-confirm
    before = client.get(f"/api/projects/{pid}/matches").json()
    for m in before:
        if m["drawing_space_id"]:
            client.patch(f"/api/projects/{pid}/matches/{m['id']}", json={"confirmed": False})

    r = client.post(f"/api/projects/{pid}/matches/bulk",
                    json={"method": "exact_code", "confirmed": True,
                          "justification": "reviewed a sample"})
    assert r.status_code == 200
    assert r.json()["updated"] > 0

    after = client.get(f"/api/projects/{pid}/matches").json()
    assert all(m["confirmed"] for m in after if m["method"] == "exact_code")
    assert all(not m["confirmed"] for m in after if m["method"] == "none")

    # every bulk decision is audited individually, exactly like a single click
    actions = [a for a in client.get(f"/api/projects/{pid}/audit").json()
               if a["action"] == "match.decided"]
    assert len(actions) >= r.json()["updated"]
    assert all(a["payload"].get("bulk") for a in actions[:r.json()["updated"]])


def test_the_audit_keeps_its_order_when_the_clock_does_not_move(client):
    """A bulk decision stamps every row it writes with one timestamp, and on
    Windows the clock tick is coarse enough that the click before it can land on
    the same one. Ordered by time alone, SQLite hands those rows back in any
    order it likes — so the screen that says who decided what, in which order,
    would show an order that is not the one things happened in. The id breaks
    the tie."""
    import datetime as _dt

    from app.db import SessionLocal
    from app.models import AuditLog

    pid = client.post("/api/projects",
                      json={"name": "Audit order", "venue_code": "AUD"}).json()["id"]
    same = _dt.datetime(2026, 9, 18, 12, 0, 0)
    db = SessionLocal()
    try:
        for n in range(6):
            db.add(AuditLog(project_id=pid, at=same, action="match.decided",
                            entity="match", entity_id=n, payload={"n": n}))
        db.commit()
    finally:
        db.close()

    rows = [r for r in client.get(f"/api/projects/{pid}/audit").json()
            if r["action"] == "match.decided"]
    assert [r["payload"]["n"] for r in rows] == [5, 4, 3, 2, 1, 0], \
        "rows written in the same tick must still come back newest first"


def test_bulk_confirm_respects_a_confidence_band(client, samples):
    pid = client.post("/api/projects",
                      json={"name": "Bulk band", "venue_code": "SYN"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true", files={"file": ("p.pdf", fh)})
    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap", files={"file": ("t.xlsx", fh)})
    tid, proposed = r.json()["id"], r.json()["proposed"]
    client.post(f"/api/projects/{pid}/teap/{tid}/import",
                json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                      "mapping": proposed["mapping"]})
    client.post(f"/api/projects/{pid}/matching/run")
    for m in client.get(f"/api/projects/{pid}/matches").json():
        if m["drawing_space_id"]:
            client.patch(f"/api/projects/{pid}/matches/{m['id']}", json={"confirmed": False})

    # a band that excludes exact_code (0.98) must change nothing
    r = client.post(f"/api/projects/{pid}/matches/bulk",
                    json={"min_confidence": 0.0, "max_confidence": 0.5, "confirmed": True})
    assert r.json()["updated"] == 0


def test_bulk_never_touches_unmatched_rows(client, samples):
    pid = client.post("/api/projects",
                      json={"name": "Bulk safety", "venue_code": "SYN"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true", files={"file": ("p.pdf", fh)})
    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap", files={"file": ("t.xlsx", fh)})
    tid, proposed = r.json()["id"], r.json()["proposed"]
    client.post(f"/api/projects/{pid}/teap/{tid}/import",
                json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                      "mapping": proposed["mapping"]})
    client.post(f"/api/projects/{pid}/matching/run")
    client.post(f"/api/projects/{pid}/matches/bulk", json={"confirmed": True})
    unmatched = [m for m in client.get(f"/api/projects/{pid}/matches").json()
                 if not m["drawing_space_id"]]
    assert unmatched, "the fixture must contain unmatched rows"
    assert all(not m["confirmed"] for m in unmatched)
