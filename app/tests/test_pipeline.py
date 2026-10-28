"""End-to-end pipeline tests over the full stack, using synthetic documents."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-test-")
os.environ["NER_DATA_DIR"] = TMP
os.environ["NER_DATABASE_URL"] = f"sqlite:///{TMP}/test.sqlite3"

from fastapi.testclient import TestClient           # noqa: E402

from app.db import init_db                          # noqa: E402
from app.domain.demand import DemandRuleSet, compute_demand  # noqa: E402
from app.domain.matching import (MatchMethod, base_code, is_placeholder_code,  # noqa: E402
                                 match_spaces, normalise_name)
from app.domain.pdf_ingest import ElementKind, extract_drawing  # noqa: E402
from app.domain.teap_import import (load_product_catalogue, profile_workbook,  # noqa: E402
                                    read_sheet)
from app.main import app                            # noqa: E402
from app.sample_data import build_all               # noqa: E402


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


@pytest.fixture(scope="session")
def samples():
    return build_all(str(Path(TMP) / "samples"))


@pytest.fixture(scope="session")
def client():
    init_db()
    c = TestClient(app)
    _sign_in(c)
    return c


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def test_vector_pdf_is_recognised_and_text_is_extracted(samples):
    ex = extract_drawing(samples["pdf"])
    assert ex.page_count == 3
    assert ex.pages[0].is_vector
    assert ex.needs_ocr_pages == []
    assert len(ex.spaces) >= 15


def test_scanned_pdf_is_flagged_for_ocr_instead_of_being_silently_skipped(samples):
    ex = extract_drawing(samples["scanned_pdf"])
    assert ex.pages[0].is_vector is False
    assert ex.needs_ocr_pages == [1]
    assert ex.spaces == []


def test_metric_scale_is_detected_per_page(samples):
    ex = extract_drawing(samples["pdf"])
    assert ex.pages[0].scale_candidates[0].denominator == pytest.approx(200.0)
    assert ex.pages[0].scale_candidates[0].confirmed is False


def test_imperial_scale_is_detected_and_not_confused_with_a_ratio(samples):
    ex = extract_drawing(samples["pdf"])
    labels = [s.label for s in ex.pages[2].scale_candidates]
    denoms = [s.denominator for s in ex.pages[2].scale_candidates]
    assert any('1/8"' in l for l in labels)
    assert pytest.approx(96.0) in denoms
    assert 8.0 not in [round(d, 3) for d in denoms]     # the 1/8 must not read as 1:8


def test_blue_ter_is_identified(samples):
    ex = extract_drawing(samples["pdf"])
    ters = [e for e in ex.elements if e.kind == ElementKind.TER]
    assert len(ters) == 1
    assert ters[0].color == "#0000cc"


def test_critical_and_non_critical_ners_are_separated_by_label_not_colour(samples):
    ex = extract_drawing(samples["pdf"])
    crit = [e for e in ex.elements if e.kind == ElementKind.NER_CRITICAL]
    non = [e for e in ex.elements if e.kind == ElementKind.NER_NONCRITICAL]
    assert {e.label for e in crit} == {"Critical NER 1", "Critical NER 4"}
    assert {e.label for e in non} == {"NER 2", "NER 3", "NER 5"}
    # both classes are drawn in the same red, exactly like the real venue design book
    assert {e.color for e in crit + non} == {"#cc0000"}


def test_legend_entries_do_not_become_phantom_elements(samples):
    ex = extract_drawing(samples["pdf"])
    labels = {e.label for e in ex.elements}
    assert "NER - Critical" not in labels
    assert "Proposed NER" not in labels
    assert len(ex.elements) == 7


def test_every_detected_element_carries_a_confidence_and_evidence(samples):
    ex = extract_drawing(samples["pdf"])
    for e in ex.elements:
        assert 0.0 < e.confidence <= 1.0
        assert e.evidence


# ---------------------------------------------------------------------------
# TEAP import and demand
# ---------------------------------------------------------------------------

def test_multi_sheet_workbook_header_row_is_found(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    assert best.name == "TEAP v2.0"
    assert best.header_row == 2               # the title occupies row 1
    assert best.proposed_mapping["space_code"] == "Space Code"
    assert best.proposed_mapping["network_ports"] == "Network Ports"
    assert len(profiles) >= 3                 # every sheet was profiled


def test_demand_uses_the_explicit_port_column_without_double_counting(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    imp = read_sheet(samples["teap"], best.name, best.header_row, best.proposed_mapping)
    imp.product_ports = load_product_catalogue(samples["teap"])
    demands = {d.space_code: d for d in compute_demand(imp)}

    vao = demands["ACR.001"]                  # 7 laptops + 2 printers + 4 webcams
    assert vao.total_ports == 9               # webcams consume no port
    assert all(l.rule == "A" for l in vao.lines)
    assert "TOTAL = 9 port(s)" in vao.breakdown()[-1]


def test_demand_falls_back_to_the_catalogue_when_no_explicit_total(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    mapping = dict(best.proposed_mapping)
    mapping.pop("network_ports")              # simulate a TEAP without the column
    imp = read_sheet(samples["teap"], best.name, best.header_row, mapping)
    imp.product_ports = load_product_catalogue(samples["teap"])
    demands = {d.space_code: d for d in compute_demand(imp)}
    assert demands["ACR.001"].total_ports == 9
    assert all(l.rule == "B" for l in demands["ACR.001"].lines)


def test_unknown_product_is_flagged_rather_than_guessed(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    mapping = dict(best.proposed_mapping)
    mapping.pop("network_ports")
    mapping.pop("product_category", None)
    imp = read_sheet(samples["teap"], best.name, best.header_row, mapping)
    imp.product_ports = {}                    # no catalogue at all
    demands = compute_demand(imp)
    assert all(d.total_ports == 0 for d in demands)
    assert any("review required" in w for d in demands for w in d.warnings)


def test_photographer_areas_are_detected_from_the_teap(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    imp = read_sheet(samples["teap"], best.name, best.header_row, best.proposed_mapping)
    imp.product_ports = load_product_catalogue(samples["teap"])
    demands = {d.space_code: d for d in compute_demand(imp)}
    assert demands["BRS.003"].demand_type.value == "photographer"
    assert demands["ACR.001"].demand_type.value == "general"


def test_missing_criticality_is_reported_not_invented(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    imp = read_sheet(samples["teap"], best.name, best.header_row, best.proposed_mapping)
    demands = compute_demand(imp)
    assert all(d.criticality is None for d in demands)
    assert all(any("criticality" in w for w in d.warnings) for d in demands)


def test_growth_margin_is_an_explicit_assumption(samples):
    profiles = profile_workbook(samples["teap"])
    best = profiles[0]
    imp = read_sheet(samples["teap"], best.name, best.header_row, best.proposed_mapping)
    imp.product_ports = load_product_catalogue(samples["teap"])
    demands = {d.space_code: d for d in compute_demand(imp, DemandRuleSet(growth_margin_pct=20))}
    assert demands["ACR.001"].total_ports == pytest.approx(10.8)
    assert any("growth margin" in a for a in demands["ACR.001"].assumptions)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_identical_names_match(samples):
    ex = extract_drawing(samples["pdf"])
    rep = match_spaces([("k1", None, "Press Work Room", None, None)], ex.spaces)
    assert rep.matches[0].best.method in (MatchMethod.EXACT_NAME,
                                          MatchMethod.NORMALISED_NAME)


def test_similar_names_match_by_normalisation(samples):
    ex = extract_drawing(samples["pdf"])
    rep = match_spaces([("k1", None, "Con Resources Venue", None, None)],
                       ex.spaces + [type(ex.spaces[0])(space_code=None,
                                                       name="CON Resources - Venue",
                                                       page=1, x=1, y=1)])
    assert rep.matches[0].matched
    assert normalise_name("Con Resources Venue") == normalise_name("CON Resources - Venue")


def test_space_code_beats_name_similarity(samples):
    ex = extract_drawing(samples["pdf"])
    rep = match_spaces([("k1", "TEC.004-02", "Tech Store", None, None)], ex.spaces)
    m = rep.matches[0]
    assert m.best.method is MatchMethod.EXACT_CODE
    assert m.best.drawing_space.space_code == "TEC.004-02"
    assert m.confirmed is True


def test_dash_and_dot_code_variants_normalise_together():
    assert base_code("TEC.004-02") == base_code("TEC.004.02") == "TEC.004"


def test_placeholder_codes_are_reported_not_matched(samples):
    ex = extract_drawing(samples["pdf"])
    rep = match_spaces([("k1", "LOG.DUM", "Logistics - unallocated", None, None)], ex.spaces)
    assert is_placeholder_code("LOG.DUM")
    assert rep.matches == []
    assert rep.placeholders and "placeholder" in rep.placeholders[0].exception


def test_ambiguous_matches_are_never_confirmed_silently(samples):
    from app.domain.pdf_ingest import DetectedSpace
    spaces = [DetectedSpace(space_code=None, name="Store Room A", page=1, x=10, y=10,
                            confidence=0.8),
              DetectedSpace(space_code=None, name="Store Room B", page=1, x=90, y=10,
                            confidence=0.8)]
    rep = match_spaces([("k1", None, "Store Room", None, None)], spaces)
    m = rep.matches[0]
    assert m.confirmed is False
    assert m in rep.needs_review
    assert any("ambiguous" in n for n in m.notes)


def test_teap_space_absent_from_the_drawings_becomes_an_exception(samples):
    ex = extract_drawing(samples["pdf"])
    rep = match_spaces([("k1", "ZZZ.999", "Room that does not exist", None, None)], ex.spaces)
    assert rep.unmatched_teap and rep.matches == []
    assert "no space on the drawings" in rep.unmatched_teap[0].exception


def test_drawing_space_absent_from_the_teap_is_listed(samples):
    ex = extract_drawing(samples["pdf"])
    rep = match_spaces([("k1", "ACR.001", "Venue Accreditation Office (VAO)", None, None)],
                       ex.spaces)
    assert len(rep.unmatched_drawing) >= 10


def test_a_name_on_several_pages_is_flagged():
    from app.domain.pdf_ingest import DetectedSpace
    spaces = [DetectedSpace(space_code="TEC.004", name="Technology Storage", page=1, x=1, y=1),
              DetectedSpace(space_code="TEC.004", name="Technology Storage", page=2, x=1, y=1)]
    rep = match_spaces([("k1", "TEC.004", "Technology Storage", None, None)], spaces)
    assert "TEC.004" in rep.multi_level
    assert rep.multi_level["TEC.004"] == [1, 2]
    assert any("several levels" in n or "pages" in n for n in rep.matches[0].notes)


# ---------------------------------------------------------------------------
# Full HTTP workflow
# ---------------------------------------------------------------------------

def test_full_workflow_over_the_api(client, samples):
    r = client.post("/api/projects", json={"name": "Synthetic Venue", "venue_code": "SYN"})
    assert r.status_code == 201
    pid = r.json()["id"]

    with open(samples["pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                        files={"file": ("plan.pdf", fh, "application/pdf")})
    assert r.status_code == 201, r.text
    assert r.json()["page_count"] == 3

    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap",
                        files={"file": ("teap.xlsx", fh,
                                        "application/vnd.openxmlformats-officedocument."
                                        "spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    tid, proposed = r.json()["id"], r.json()["proposed"]

    r = client.post(f"/api/projects/{pid}/teap/{tid}/import",
                    json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"]})
    assert r.status_code == 200, r.text
    assert r.json()["spaces"] >= 18

    # scale must be confirmed per page before definitive results
    for page in (1, 2):
        r = client.post(f"/api/projects/{pid}/pages/{page}/scale",
                        json={"denominator": 200.0, "confirm": True})
        assert r.status_code == 200

    r = client.post(f"/api/projects/{pid}/matching/run")
    assert r.status_code == 200, r.text
    stats = r.json()["stats"]
    assert stats["matched"] >= 17
    assert stats["match_rate"] > 0.85

    # confirm everything the engine left for review
    for m in client.get(f"/api/projects/{pid}/matches", params={"only_review": True}).json():
        client.patch(f"/api/projects/{pid}/matches/{m['id']}",
                     json={"confirmed": True, "justification": "test fixture"})

    r = client.post(f"/api/projects/{pid}/analyse")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["spaces"] >= 17
    assert body["disclaimer"]
    statuses = {a["status"] for a in body["assignments"]}
    assert statuses & {"served", "near_limit", "out_of_limit"}

    # every assignment must carry its audit trail
    for a in body["assignments"]:
        if a["evaluation"]:
            assert a["evaluation"]["scale_label"]
            assert a["evaluation"]["assumptions"] or a["evaluation"]["warnings"]

    r = client.post(f"/api/projects/{pid}/reports/xlsx")
    assert r.status_code == 200, r.text
    dl = client.get(r.json()["download"])
    assert dl.status_code == 200 and len(dl.content) > 5000

    r = client.post(f"/api/projects/{pid}/reports/pdf")
    assert r.status_code == 200, r.text
    assert client.get(r.json()["download"]).status_code == 200

    r = client.get(f"/api/projects/{pid}/audit")
    assert r.status_code == 200
    actions = {a["action"] for a in r.json()}
    assert {"project.created", "drawing.ingested", "teap.imported",
            "matching.run", "report.generated"} <= actions
