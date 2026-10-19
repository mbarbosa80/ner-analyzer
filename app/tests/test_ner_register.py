"""V2 — the canonical NER register, consolidation and suggestions.

Covers the cases spec section 22 lists for phase one (1–14), plus the two the
migration itself has to get right: identity survives, and the numbers the tool
produced before it ran are still the numbers it produces after.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-v2-test-")
os.environ["NER_DATA_DIR"] = TMP
os.environ["NER_DATABASE_URL"] = f"sqlite:///{TMP}/test.sqlite3"

from fastapi.testclient import TestClient                       # noqa: E402

from app.db import SessionLocal, init_db                        # noqa: E402
from app.domain.consolidation import (Candidate, compare,       # noqa: E402
                                      group_candidates, normalise_label)
from app.main import app                                        # noqa: E402
from app.models import Element, NerAsset, NerStatus, Page, Project  # noqa: E402
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


@pytest.fixture(scope="module")
def project(client, samples) -> int:
    """A project with the synthetic drawing and TEAP fully imported."""
    r = client.post("/api/projects", json={"name": "V2 Register", "venue_code": "SYN"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    with open(samples["pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                        files={"file": ("plan.pdf", fh, "application/pdf")})
    assert r.status_code == 201, r.text

    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap",
                        files={"file": ("teap.xlsx", fh,
                                        "application/vnd.openxmlformats-officedocument."
                                        "spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    tid, proposed = r.json()["id"], r.json()["proposed"]
    r = client.post(f"/api/projects/{pid}/teap/{tid}/import",
                    json={"sheet": proposed["sheet"],
                          "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"]})
    assert r.status_code == 200, r.text

    for page in (1, 2, 3):
        client.post(f"/api/projects/{pid}/pages/{page}/scale",
                    json={"mode": "ratio", "denominator": 200.0, "confirm": True})
    r = client.post(f"/api/projects/{pid}/matching/run")
    assert r.status_code == 200, r.text
    return pid


def _ners(client, pid, **kw) -> list[dict]:
    r = client.get(f"/api/projects/{pid}/ners", params=kw)
    assert r.status_code == 200, r.text
    return r.json()["ners"]


# ---------------------------------------------------------------------------
# The comparison rule itself
# ---------------------------------------------------------------------------

def test_label_normalisation_collapses_the_ways_a_sheet_writes_one_room():
    assert normalise_label("Critical NER 3") == "critical ner 3"
    assert normalise_label("CRITICAL-NER-03") == "critical ner 3"
    assert normalise_label("  critical   ner  3 ") == "critical ner 3"
    assert normalise_label("Critical NER 30") != normalise_label("Critical NER 3")


def test_same_room_on_two_pages_of_the_same_level_merges_without_asking():
    a = Candidate(ref=1, label="Critical NER 3", kind="NER_CRITICAL", page=5,
                  level="L1", building="Main")
    b = Candidate(ref=2, label="CRITICAL NER 03", kind="NER_CRITICAL", page=12,
                  level="L1", building="Main")
    c = compare(a, b)
    assert c.auto_mergeable
    assert any("identical normalised label" in e for e in c.evidence)


def test_consecutive_numbers_in_a_series_are_never_the_same_room():
    a = Candidate(ref=1, label="NER 4", kind="NER_NONCRITICAL", page=5, level="L1")
    b = Candidate(ref=2, label="NER 5", kind="NER_NONCRITICAL", page=5, level="L1")
    c = compare(a, b)
    assert c.blocking == "different_index"
    assert c.score == 0.0


def test_a_conflicting_level_beats_an_identical_label():
    a = Candidate(ref=1, label="NER 7", kind="NER_NONCRITICAL", page=3, level="L1")
    b = Candidate(ref=2, label="NER 7", kind="NER_NONCRITICAL", page=9, level="L2")
    c = compare(a, b)
    assert c.blocking == "different_level"
    assert not c.auto_mergeable


def test_an_unknown_level_is_a_question_not_an_agreement():
    """The case that decides whether this tool is trustworthy.

    Two identical labels with no level recorded *might* be one room. The tool
    must not decide that on its own — it lands just under the automatic
    threshold, which puts it in the review queue with its evidence.
    """
    a = Candidate(ref=1, label="NER 7", kind="NER_NONCRITICAL", page=3, level=None)
    b = Candidate(ref=2, label="NER 7", kind="NER_NONCRITICAL", page=9, level=None)
    c = compare(a, b)
    assert not c.auto_mergeable
    assert c.is_candidate
    assert any("agreement unproven" in d for d in c.differences)


def test_a_reviewers_separate_decision_silences_the_pair():
    a = Candidate(ref=1, label="NER 7", kind="NER_NONCRITICAL", page=3, level="L1",
                  confirmed_separate_from=frozenset({2}))
    b = Candidate(ref=2, label="NER 7", kind="NER_NONCRITICAL", page=9, level="L1")
    assert compare(a, b).blocking == "declared_separate"


def test_grouping_only_compares_rooms_that_could_be_related():
    items = [Candidate(ref=i, label=f"NER {i}", level="L1") for i in range(1, 30)]
    items.append(Candidate(ref=99, label="NER 1", level="L1"))
    pairs = group_candidates(items)
    assert len(pairs) == 1
    assert {pairs[0][0].ref, pairs[0][1].ref} == {1, 99}


# ---------------------------------------------------------------------------
# Migration and the register
# ---------------------------------------------------------------------------

def test_every_detected_room_reaches_the_register(client, project):
    rows = _ners(client, project)
    assert rows, "the drawing has equipment rooms; the register must not be empty"
    for r in rows:
        assert r["code"].startswith("NER-")
        assert r["occurrence_count"] >= 1
        assert r["occurrences"][0]["page"] >= 1


def test_migration_confirms_nothing(client, project):
    """A red symbol is a suggestion. Nothing arrives *confirmed*.

    The principle is unchanged; what it applies to has been narrowed. It used to
    also force ``classification == "pending"``, which meant the register showed
    "Pending" beside a marker the extractor had read as "Critical NER 1" and
    stored as CRITICAL in ``suggested_classification`` — while the coverage
    engine was already treating the room as critical, because
    ``_asset_to_ner`` reads the marker kind. The screen was less truthful than
    the analysis, and it asked twenty-one questions the drawing had answered.

    So the drawing's reading is now the value, and the thing that stays false is
    the one that carries the audit weight: no human has signed it off.
    """
    for r in _ners(client, project):
        assert r["classification_confirmed"] is False, \
            "reading the drawing is not a human sign-off"
        assert "criticality not confirmed by a human" in r["pending_validations"]


def test_the_drawing_answer_is_the_starting_value(client, project):
    """A marker the extractor classified arrives classified, not "pending"."""
    rows = _ners(client, project)
    assert rows
    for r in rows:
        if r["suggested_classification"] in ("critical", "non-critical"):
            assert r["classification"] == r["suggested_classification"], \
                "the register must not ask what the drawing already says"
        assert r["classification_evidence"], \
            "and it must show where that reading came from"


def test_a_room_on_the_drawing_is_not_asked_whether_to_keep_it(client, project):
    """A drawn room exists. Rejecting it is a change request, raised on purpose
    — not a blank field on a form."""
    for r in _ners(client, project):
        if r["status"] == "suggested":
            continue
        assert r["keep_decision"] == "keep"
        assert r["keep_is_open_question"] is False
        assert "keep / reject decision outstanding" not in r["pending_validations"]


def test_a_removed_room_is_closed_to_editing(client, project):
    """A rejected room is a record of a decision. Leaving its fields editable
    invites someone to change a room that is no longer in the study."""
    rows = _ners(client, project)
    target = rows[0]
    r = client.post(f"/api/projects/{project}/ners/{target['id']}/keep",
                    json={"decision": "reject", "justification": "test"})
    assert r.status_code == 200, r.text
    after = {x["id"]: x for x in _ners(client, project, include_removed=True)}[target["id"]]
    assert after["editable"] is False
    # It stays listed on purpose: the decision is part of the record, and a room
    # that vanished from the screen could not be restored or explained. What it
    # loses is the ability to be edited as though it were still in the study.
    assert target["id"] in {x["id"] for x in _ners(client, project,
                                                   include_removed=True)}


def test_the_register_never_claims_a_route_it_has_not_read(client, project):
    for r in _ners(client, project):
        assert r["routes"]["redundancy_status"] == "not_analysed"
        assert r["routes"]["route_a"] is None
        assert any("TVDB" in v for v in r["pending_validations"])


def test_renaming_keeps_the_internal_identity(client, project):
    """Spec section 22 case 7, and section 25's hard rule."""
    row = _ners(client, project)[0]
    before_id, before_code = row["id"], row["code"]
    r = client.post(f"/api/projects/{project}/ners/{before_id}/rename",
                    json={"name": "HND-NER-01", "reason": "venue naming convention"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["identity_unchanged"] is True
    assert body["id"] == before_id and body["code"] == before_code
    assert body["display_name"] == "HND-NER-01"

    after = client.get(f"/api/projects/{project}/ners/{before_id}").json()
    assert after["previous_name"] == row["display_name"]
    assert row["display_name"] in after["aliases"]
    assert after["name_history"][0]["new"] == "HND-NER-01"
    assert after["name_history"][0]["reason"] == "venue naming convention"


def test_an_empty_name_is_refused(client, project):
    nid = _ners(client, project)[0]["id"]
    r = client.post(f"/api/projects/{project}/ners/{nid}/rename", json={"name": "   "})
    assert r.status_code == 422


def test_classification_is_a_human_decision_and_moves_the_marker_kind(client, project):
    """Cases 5 and 6: confirm criticality, then change it back."""
    nid = _ners(client, project)[0]["id"]
    r = client.post(f"/api/projects/{project}/ners/{nid}/classify",
                    json={"classification": "critical", "confirmed": True,
                          "reason": "confirmed against the venue design book"})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": nid, "classification": "critical",
                        "classification_confirmed": True, "kind": "NER_CRITICAL"}

    r = client.post(f"/api/projects/{project}/ners/{nid}/classify",
                    json={"classification": "non_critical", "confirmed": True,
                          "reason": "reclassified after the services review"})
    assert r.status_code == 200
    assert r.json()["kind"] == "NER_NONCRITICAL"

    after = client.get(f"/api/projects/{project}/ners/{nid}").json()
    assert "criticality not confirmed by a human" not in after["pending_validations"]


def test_pending_cannot_be_a_confirmed_classification(client, project):
    nid = _ners(client, project)[0]["id"]
    r = client.post(f"/api/projects/{project}/ners/{nid}/classify",
                    json={"classification": "pending", "confirmed": True})
    assert r.status_code == 422


def test_locking_blocks_movement_and_rejection(client, project):
    """Case 9."""
    nid = _ners(client, project)[1]["id"]
    assert client.post(f"/api/projects/{project}/ners/{nid}/lock",
                       json={"locked": True, "reason": "position signed off"}
                       ).status_code == 200

    r = client.post(f"/api/projects/{project}/ners/{nid}/move",
                    json={"page": 1, "x": 10.0, "y": 10.0, "propose": False})
    assert r.status_code == 422
    assert "locked" in r.json()["detail"]

    r = client.post(f"/api/projects/{project}/ners/{nid}/keep",
                    json={"decision": "reject"})
    assert r.status_code == 422

    # a *proposal* is still allowed — it changes nothing on its own
    r = client.post(f"/api/projects/{project}/ners/{nid}/move",
                    json={"page": 1, "x": 10.0, "y": 10.0, "propose": True,
                          "reason": "closer to the demand cluster"})
    assert r.status_code == 200, r.text
    assert r.json()["proposed_position"]["reason"] == "closer to the demand cluster"
    assert r.json()["status"] == "reposition_proposed"

    client.post(f"/api/projects/{project}/ners/{nid}/lock", json={"locked": False})


def test_rejecting_a_ner_keeps_the_row_and_takes_it_out_of_the_analysis(client, project):
    """Case 8, and spec section 7: deletion is never silent."""
    rows = _ners(client, project)
    nid = rows[-1]["id"]
    r = client.post(f"/api/projects/{project}/ners/{nid}/keep",
                    json={"decision": "reject", "reason": "duplicate of the main room"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    row = [x for x in _ners(client, project) if x["id"] == nid][0]
    assert row["is_live"] is False, "a rejected NER must stop counting as live"
    assert row["status"] == "rejected"
    assert row["keep_decision"] == "reject"

    log = client.get(f"/api/projects/{project}/audit").json()
    entry = [e for e in log if e["action"] == "ner.keep_decision"][0]
    assert entry["justification"] == "duplicate of the main room"

    client.post(f"/api/projects/{project}/ners/{nid}/restore")
    back = [x for x in _ners(client, project) if x["id"] == nid][0]
    assert back["is_live"] is True


def test_removal_requires_a_reason(client, project):
    nid = _ners(client, project)[0]["id"]
    r = client.post(f"/api/projects/{project}/ners/{nid}/remove", json={"reason": ""})
    assert r.status_code == 422


def _add_second_occurrence(client, pid: int, label: str, page: int,
                           level: str | None) -> int:
    """Draw the same room again on another page, as a design book does."""
    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            if pg.number == page:
                pg.level = level
                db.commit()
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": page, "kind": "NER_NONCRITICAL", "label": label,
                          "x": 300.0, "y": 300.0})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_the_same_room_drawn_twice_is_one_ner_not_two(client, samples):
    """Cases 10 and 11 — the defect that made V1 over-count equipment rooms."""
    r = client.post("/api/projects", json={"name": "Duplicate venue", "venue_code": "DUP"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})

    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = "Level 1"
        db.commit()

    before = len(_ners(client, pid))
    e1 = _add_second_occurrence(client, pid, "NER 42", 1, "Level 1")
    after_first = _ners(client, pid)
    assert len(after_first) == before + 1

    e2 = _add_second_occurrence(client, pid, "ner-42", 2, "Level 1")
    rows = _ners(client, pid)
    assert len(rows) == before + 1, "the second drawing of NER 42 must not add a NER"

    row = [x for x in rows if normalise_label(x["display_name"]) == "ner 42"][0]
    assert row["occurrence_count"] == 2
    assert sorted(row["pages"]) == [1, 2]
    assert {e1, e2} == {o["id"] for o in row["occurrences"]}

    hist = client.get(f"/api/projects/{pid}/ner-consolidations").json()["consolidations"]
    auto = [h for h in hist if h["method"] == "auto" and h["decision"] == "merged"]
    assert auto, "an automatic link must be recorded, not implicit"
    assert any("identical normalised label" in e for e in auto[0]["evidence"])


def test_similar_rooms_on_different_levels_stay_separate(client, samples):
    """Case 12."""
    r = client.post("/api/projects", json={"name": "Two levels", "venue_code": "TL"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})

    before = len(_ners(client, pid))
    _add_second_occurrence(client, pid, "NER 77", 1, "Level 1")
    _add_second_occurrence(client, pid, "NER 77", 2, "Level 2")
    rows = _ners(client, pid)
    assert len(rows) == before + 2, "same label, different levels — two rooms"

    cands = client.get(f"/api/projects/{pid}/ners/duplicates/candidates").json()
    assert not [c for c in cands["candidates"]
                if normalise_label(c["primary"]["display_name"]) == "ner 77"], \
        "a level conflict is an answer, not a question"


def test_an_ambiguous_pair_is_asked_about_and_never_merged_on_its_own(client, samples):
    """Case 13 — the rule the whole register rests on."""
    r = client.post("/api/projects", json={"name": "Ambiguous", "venue_code": "AMB"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})

    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = None
        db.commit()

    before = len(_ners(client, pid))
    _add_second_occurrence(client, pid, "NER 88", 1, None)
    _add_second_occurrence(client, pid, "NER 88", 2, None)
    assert len(_ners(client, pid)) == before + 2, "unknown level must not auto-merge"

    body = client.get(f"/api/projects/{pid}/ners/duplicates/candidates").json()
    pair = [c for c in body["candidates"]
            if normalise_label(c["primary"]["display_name"]) == "ner 88"]
    assert pair, "the pair must reach the review queue"
    cmp_ = pair[0]["comparison"]
    assert cmp_["auto_mergeable"] is False
    assert cmp_["evidence"] and cmp_["differences"], \
        "a reviewer must see both why it might be one room and why it might not"


def test_consolidating_moves_the_occurrences_and_can_be_undone(client, samples):
    """Case 14 — undo has to restore the register exactly."""
    r = client.post("/api/projects", json={"name": "Undo venue", "venue_code": "UND"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})
    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = None
        db.commit()

    _add_second_occurrence(client, pid, "NER 91", 1, None)
    _add_second_occurrence(client, pid, "NER 91", 2, None)
    rows = [x for x in _ners(client, pid)
            if normalise_label(x["display_name"]) == "ner 91"]
    assert len(rows) == 2
    a, b = rows[0], rows[1]

    r = client.post(f"/api/projects/{pid}/ners/consolidate",
                    json={"primary_id": a["id"], "duplicate_id": b["id"],
                          "justification": "same room, key plan and detail sheet"})
    assert r.status_code == 200, r.text
    cid = r.json()["consolidation_id"]
    assert r.json()["occurrences_moved"] == 1

    merged = client.get(f"/api/projects/{pid}/ners/{a['id']}").json()
    assert merged["occurrence_count"] == 2
    assert b["code"] in merged["aliases"], \
        "the merged room's internal code must stay traceable from the survivor"
    assert b["id"] not in [x["id"] for x in _ners(client, pid)]

    r = client.post(f"/api/projects/{pid}/ner-consolidations/{cid}/undo",
                    params={"reason": "they are different rooms after all"})
    assert r.status_code == 200, r.text
    assert r.json()["occurrences_restored"] == 1

    back = {x["id"]: x for x in _ners(client, pid)}
    assert b["id"] in back
    assert back[a["id"]]["occurrence_count"] == 1
    assert back[b["id"]]["occurrence_count"] == 1
    assert b["code"] not in back[a["id"]]["aliases"]

    r = client.post(f"/api/projects/{pid}/ner-consolidations/{cid}/undo")
    assert r.status_code == 422, "undoing twice must be refused"


def test_declaring_two_rooms_separate_stops_the_question(client, samples):
    r = client.post("/api/projects", json={"name": "Separate venue", "venue_code": "SEP"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})
    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = None
        db.commit()

    _add_second_occurrence(client, pid, "NER 55", 1, None)
    _add_second_occurrence(client, pid, "NER 55", 2, None)
    rows = [x for x in _ners(client, pid)
            if normalise_label(x["display_name"]) == "ner 55"]
    assert len(rows) == 2

    def pending() -> list:
        body = client.get(f"/api/projects/{pid}/ners/duplicates/candidates").json()
        return [c for c in body["candidates"]
                if normalise_label(c["primary"]["display_name"]) == "ner 55"]

    assert pending()
    r = client.post(f"/api/projects/{pid}/ners/declare-separate",
                    json={"a_id": rows[0]["id"], "b_id": rows[1]["id"],
                          "justification": "two rooms, both tagged NER 55 by mistake"})
    assert r.status_code == 200, r.text
    assert not pending(), "a decided pair must stop being asked about"

    r = client.post(f"/api/projects/{pid}/ners/consolidate",
                    json={"primary_id": rows[0]["id"], "duplicate_id": rows[1]["id"]})
    assert r.status_code == 422


def test_detaching_one_occurrence_splits_it_out(client, samples):
    """The fine-grained undo: right for two pages, wrong for the third."""
    r = client.post("/api/projects", json={"name": "Detach venue", "venue_code": "DET"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})
    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = "Level 1"
        db.commit()

    _add_second_occurrence(client, pid, "NER 60", 1, "Level 1")
    e2 = _add_second_occurrence(client, pid, "NER 60", 2, "Level 1")
    row = [x for x in _ners(client, pid)
           if normalise_label(x["display_name"]) == "ner 60"][0]
    assert row["occurrence_count"] == 2

    r = client.post(f"/api/projects/{pid}/occurrences/{e2}/detach",
                    params={"reason": "this one is a different room"})
    assert r.status_code == 200, r.text
    new_id = r.json()["new_ner_id"]
    assert client.get(f"/api/projects/{pid}/ners/{row['id']}"
                      ).json()["occurrence_count"] == 1
    assert client.get(f"/api/projects/{pid}/ners/{new_id}"
                      ).json()["occurrence_count"] == 1


def test_detaching_the_only_occurrence_is_refused(client, project):
    single = [x for x in _ners(client, project) if x["occurrence_count"] == 1]
    if not single:
        pytest.skip("every register row has several occurrences")
    eid = single[0]["occurrences"][0]["id"]
    r = client.post(f"/api/projects/{project}/occurrences/{eid}/detach")
    assert r.status_code == 422
    assert "only this occurrence" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Coverage reads the register
# ---------------------------------------------------------------------------

def test_a_rejected_ner_stops_serving_areas(client, project):
    """The register is not decoration: rejecting a room changes the analysis."""
    r = client.post(f"/api/projects/{project}/analyse")
    assert r.status_code == 200, r.text
    before = r.json()["summary"]["ner_count"]
    assert before >= 1

    served = [k for k, v in r.json()["ner_load"].items() if v.get("spaces")]
    assert served, "the synthetic venue must have at least one serving room"
    nid = int(served[0][1:])          # keys are "A<asset id>"

    client.post(f"/api/projects/{project}/ners/{nid}/keep",
                json={"decision": "reject", "reason": "removed from the design"})
    after = client.post(f"/api/projects/{project}/analyse").json()
    assert after["summary"]["ner_count"] == before - 1
    assert f"A{nid}" not in after["ner_load"]

    client.post(f"/api/projects/{project}/ners/{nid}/restore")
    client.post(f"/api/projects/{project}/ners/{nid}/keep", json={"decision": "keep"})


def test_coverage_keys_are_canonical_rooms_not_markers(client, project):
    body = client.post(f"/api/projects/{project}/analyse").json()
    assert body["ner_load"], "analysis must report per-room load"
    assert all(k.startswith("A") for k in body["ner_load"]), \
        "coverage must be keyed on the canonical NER, not on a drawing marker"


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def test_a_suggestion_is_excluded_from_the_as_is_analysis(client, project):
    body = client.post(f"/api/projects/{project}/analyse").json()
    suggested = {f"A{x['id']}" for x in _ners(client, project)
                 if x["status"] == "suggested"}
    assert not (suggested & set(body["ner_load"])), \
        "an unapproved room must not appear in the As-Is coverage"


def test_rerunning_suggestions_does_not_stack_duplicates(client, project):
    first = {x["id"] for x in _ners(client, project) if x["status"] == "suggested"}
    client.post(f"/api/projects/{project}/ners/suggest", json={"allow_new": True})
    second = {x["id"] for x in _ners(client, project) if x["status"] == "suggested"}
    assert second == first or not first


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_every_register_decision_is_in_the_audit_log(client, project):
    nid = _ners(client, project)[0]["id"]
    client.post(f"/api/projects/{project}/ners/{nid}/rename",
                json={"name": "Audited NER", "reason": "traceability check"})
    log = client.get(f"/api/projects/{project}/audit").json()
    actions = [e["action"] for e in log]
    for expected in ("ner.renamed", "ner.classified", "ner.keep_decision"):
        assert expected in actions, f"{expected} must be auditable"
    renames = [e for e in log if e["action"] == "ner.renamed"]
    assert renames[0]["payload"]["id"] == nid


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_a_rejected_ner_stops_competing_for_its_own_label(client, samples):
    """The renumbering case: reject NER 007, rename the last room to NER 007.

    With one index both assets answer to that label on the same level, the
    scores tie, and a new marker could be linked to the room that was deleted.
    """
    r = client.post("/api/projects", json={"name": "Renumber", "venue_code": "RNB"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})
    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = "Level 1"
        db.commit()

    _add_second_occurrence(client, pid, "NER 007", 1, "Level 1")
    _add_second_occurrence(client, pid, "NER 033", 2, "Level 1")
    rows = {x["display_name"]: x for x in _ners(client, pid)}
    old, last = rows["NER 007"], rows["NER 033"]

    # the renumber
    client.post(f"/api/projects/{pid}/ners/{old['id']}/keep",
                json={"decision": "reject", "reason": "removed from the design"})
    r = client.post(f"/api/projects/{pid}/ners/{last['id']}/rename",
                    json={"name": "NER 007", "reason": "renumbered after the removal"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == last["id"], "renaming must not change the identity"

    # the revised drawing still carries a marker labelled NER 007
    new_element = _add_second_occurrence(client, pid, "NER 007", 3, "Level 1")

    with SessionLocal() as db:
        e = db.get(Element, new_element)
        linked = db.get(NerAsset, e.ner_asset_id)
    assert linked.id != old["id"], \
        "a marker must never be linked back to a NER that was rejected"

    assert linked.id == last["id"], \
        "it belongs to the room that now carries the name"

    # the rejected row is still there, still named, still traceable
    everything = {x["id"]: x for x in _ners(client, pid, include_removed=True)}
    assert everything[old["id"]]["status"] == "rejected"
    assert everything[last["id"]]["previous_name"] == "NER 033"


def test_a_marker_matching_only_a_rejected_ner_raises_a_question(client, samples):
    """The dangerous case: nothing living claims the label any more.

    Without the retirement rule the new marker links straight back to the room
    the design dropped, and the removal quietly un-happens.
    """
    r = client.post("/api/projects", json={"name": "Ghost", "venue_code": "GHO"})
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                    files={"file": ("plan.pdf", fh, "application/pdf")})
    with SessionLocal() as db:
        for pg in db.query(Page).join(Page.drawing).filter(
                Page.drawing.has(project_id=pid)).all():
            pg.level = "Level 1"
        db.commit()

    _add_second_occurrence(client, pid, "NER 099", 1, "Level 1")
    dropped = [x for x in _ners(client, pid) if x["display_name"] == "NER 099"][0]
    client.post(f"/api/projects/{pid}/ners/{dropped['id']}/keep",
                json={"decision": "reject", "reason": "removed from the design"})

    # the revised drawing still shows it
    eid = _add_second_occurrence(client, pid, "NER 099", 2, "Level 1")
    with SessionLocal() as db:
        e = db.get(Element, eid)
        linked_id = e.ner_asset_id
    assert linked_id != dropped["id"], "a removal must not silently un-happen"

    everything = _ners(client, pid, include_removed=True)
    flagged = [x for x in everything
               if any(dropped["code"] in v for v in x["pending_validations"])]
    assert flagged, "reusing a rejected NER's label must raise a question"
    assert any("rejected" in v for v in flagged[0]["pending_validations"])


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def test_a_change_request_freezes_what_was_asked(client, project):
    rows = _ners(client, project)
    target = rows[0]
    client.post(f"/api/projects/{project}/ners/{target['id']}/keep",
                json={"decision": "reject", "reason": "absorbed by the neighbour"})

    r = client.post(f"/api/projects/{project}/register-snapshots",
                    json={"kind": "change_request", "name": "Revision 1",
                          "reference": "VNI-2026-014", "issued_to": "VNI team",
                          "note": "first pass"})
    assert r.status_code == 201, r.text
    snap = r.json()
    sid = snap["id"]
    assert snap["summary"]["to_remove"] >= 1

    item = [i for i in snap["change_items"] if i["internal_code"] == target["code"]][0]
    assert item["action"] == "remove"
    # the three identity columns are the whole point
    assert item["internal_code"] and "current_name" in item and "previous_name" in item

    # changing your mind afterwards must not rewrite what was asked
    client.post(f"/api/projects/{project}/ners/{target['id']}/keep",
                json={"decision": "keep", "reason": "changed my mind"})
    again = client.get(f"/api/projects/{project}/register-snapshots/{sid}").json()
    assert again["summary"]["to_remove"] == snap["summary"]["to_remove"]
    assert [i["internal_code"] for i in again["change_items"]] == \
           [i["internal_code"] for i in snap["change_items"]], \
        "a frozen request must not follow the register"


def test_a_snapshot_needs_a_name_and_a_known_kind(client, project):
    assert client.post(f"/api/projects/{project}/register-snapshots",
                       json={"name": "   "}).status_code == 422
    assert client.post(f"/api/projects/{project}/register-snapshots",
                       json={"kind": "whatever", "name": "x"}).status_code == 422


def test_snapshots_export_with_the_stable_code_alongside_the_name(client, project):
    client.post(f"/api/projects/{project}/register-snapshots",
                json={"kind": "freeze", "name": "Design freeze"})
    listing = client.get(f"/api/projects/{project}/register-snapshots").json()
    assert listing["snapshots"], "snapshots must be listed newest first"
    assert listing["snapshots"][0]["kind"] == "freeze"
    sid = listing["snapshots"][0]["id"]

    r = client.get(f"/api/projects/{project}/register-snapshots/{sid}/export/csv")
    assert r.status_code == 200
    assert "Internal code (stable)" in r.text
    assert "Previously called" in r.text

    r = client.get(f"/api/projects/{project}/register-snapshots/{sid}/export/xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Change request", "Register at that moment", "Notice"]
    assert "code is stable" in wb["Notice"]["A3"].value

    assert client.get(
        f"/api/projects/{project}/register-snapshots/{sid}/export/docx"
    ).status_code == 422


# ---------------------------------------------------------------------------
# Removed with the features they covered
#
# Five cases stood at the end of this file:
#
#   * the bulk renamer ("apply {venue}-NER-{index:02d} to every room") and its
#     refusal to produce two rooms with the same name;
#   * a solver suggestion entering the register as a question rather than as a
#     fact;
#   * three cases on the register's own CSV/XLSX export — that it carries the
#     internal code beside the current and previous name, that it never writes a
#     zero where a capacity is unknown, and that an unknown format is refused.
#
# The renamer and the suggestions are gone. The register export is gone too, but
# what it guaranteed is not: ``test_snapshots_export_with_the_stable_code_
# alongside_the_name`` above holds the same line on the snapshot export, which
# is the file that actually leaves the building — it goes to the drawing team as
# a change request, and it is the one where a rename must never lose the thread.
# ---------------------------------------------------------------------------
