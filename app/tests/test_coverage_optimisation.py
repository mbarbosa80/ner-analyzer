"""Coverage assignment, capacity and redundancy tests.

The optimiser cases that used to close this file went with the optimiser. What
they proved — that a solver could cover a gap with a new site, cheaply and
deterministically — was true and is no longer something this application does:
new equipment rooms are placed by hand on the drawing.
"""

from __future__ import annotations

import pytest

from app.domain.coverage import NER, compute_coverage, redundancy_candidates
from app.domain.distance import DemandType, DistanceRules, Status
from app.domain.geometry import Area, Point
from app.domain.pdf_ingest import ElementKind
from app.domain.routes import RouteNetwork, RouteSegment, VerticalLink, build_network
from app.domain.units import Scale

RULES = DistanceRules()


def unit_scale(confirmed: bool = True) -> Scale:
    return Scale(metres_per_unit=1.0, source="manual", label="1u=1m", confirmed=confirmed)


def area(key: str, x: float, y: float, page: int = 1, name: str = "") -> Area:
    return Area(key=key, name=name or key, page=page, label_point=Point(x, y, page))


def ner(key: str, x: float, y: float, *, page: int = 1, critical: bool = False,
        ports: int | None = None, **kw) -> NER:
    return NER(
        key=key, label=key,
        kind=ElementKind.NER_CRITICAL if critical else ElementKind.NER_NONCRITICAL,
        point=Point(x, y, page), critical=critical, total_ports=ports, **kw)


SCALES = {1: unit_scale(), 2: unit_scale()}


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def test_nearest_compliant_ner_is_chosen():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 80, 0), ner("N2", 20, 0)],
        scale_for_page=SCALES, rules=RULES)
    a = res.assignments[0]
    assert a.ner_key == "N2"
    assert a.status is Status.SERVED


def test_a_plan_with_no_ner_reports_every_space_as_not_analysable():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[], scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].status is Status.NOT_ANALYSABLE
    assert res.uncovered == ["A"]
    assert res.exceptions


def test_area_beyond_every_ner_is_reported_out_of_coverage():
    res = compute_coverage(
        areas=[(area("A", 500, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 0, 0)], scale_for_page=SCALES, rules=RULES)
    a = res.assignments[0]
    assert a.ner_key is None
    assert a.status is Status.OUT_OF_LIMIT
    assert "nearest NER" in " ".join(a.reasons)


def test_photographer_area_uses_the_70m_limit_in_assignment():
    res = compute_coverage(
        areas=[(area("P", 75, 0), 4.0, DemandType.PHOTOGRAPHER, None, True)],
        ners=[ner("N1", 0, 0)], scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].status is Status.OUT_OF_LIMIT
    assert res.assignments[0].evaluation.limit_m == 70.0


def test_insufficient_capacity_is_distinguished_from_being_out_of_range():
    """The rule since 3 Sep 2026: a full room within reach is still the room.

    The space is assigned to the nearest NER inside the limit even though that
    NER is out of ports, and the verdict says so. Leaving it with no room hid
    the demand from the port load of the very room that will end up carrying
    it — and the report is where the decision to draw a second NER is made.
    """
    res = compute_coverage(
        areas=[(area("A", 10, 0), 50.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 20, 0, ports=10)], scale_for_page=SCALES, rules=RULES)
    a = res.assignments[0]
    assert a.status is Status.INSUFFICIENT_CAPACITY
    assert a.ner_key == "N1"
    assert "out of ports" in " ".join(a.reasons)
    assert res.uncovered == ["A"], "full is not served"
    assert res.exceptions and res.exceptions[0]["status"] == "insufficient_capacity"
    assert res.ner_load["N1"]["utilisation_pct"] == 500.0, \
        "the overload is reported, not hidden"


def test_the_second_nearest_room_wins_when_the_nearest_is_full():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 8.0, DemandType.GENERAL, None, True)],
        ners=[ner("FULL", 12, 0, ports=4), ner("SPARE", 40, 0, ports=48)],
        scale_for_page=SCALES, rules=RULES)
    a = res.assignments[0]
    assert a.ner_key == "SPARE"
    assert a.status is Status.SERVED


def test_out_of_limit_still_names_the_nearest_room_without_assigning_it():
    """No room within 90 m: nothing serves the space, but the row says which
    room is closest and how far, instead of a blank."""
    res = compute_coverage(
        areas=[(area("A", 500, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("FAR", 0, 0), ner("FARTHER", -100, 0)],
        scale_for_page=SCALES, rules=RULES)
    a = res.assignments[0]
    assert a.ner_key is None
    assert a.status is Status.OUT_OF_LIMIT
    assert a.nearest_label == "FAR"
    assert a.nearest_distance_m == pytest.approx(500.0)
    assert a.to_dict()["nearest_distance_m"] == 500.0
    assert "FAR" not in res.ner_load or res.ner_load["FAR"]["assigned_ports"] == 0, \
        "a cable that cannot reach carries no ports"


def test_capacity_is_consumed_across_spaces_in_a_deterministic_order():
    res = compute_coverage(
        areas=[(area("BIG", 10, 0), 30.0, DemandType.GENERAL, None, True),
               (area("SMALL", 12, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 15, 0, ports=32)], scale_for_page=SCALES, rules=RULES)
    by_key = {a.space_key: a for a in res.assignments}
    assert by_key["BIG"].ner_key == "N1"                 # largest demand served first
    assert by_key["SMALL"].status is Status.INSUFFICIENT_CAPACITY
    assert by_key["SMALL"].ner_key == "N1", "the full room still carries it, flagged"
    assert res.ner_load["N1"]["utilisation_pct"] == pytest.approx(109.4, abs=0.2)


def test_a_critical_space_is_not_served_by_a_non_critical_ner():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, True, True)],
        ners=[ner("NONCRIT", 12, 0), ner("CRIT", 40, 0, critical=True)],
        scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].ner_key == "CRIT"


def test_unstated_criticality_produces_a_proposal_that_must_be_validated():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 20, 0)], scale_for_page=SCALES, rules=RULES)
    assert any("criticality not stated" in r for r in res.assignments[0].reasons)


def test_unknown_capacity_is_reported_and_never_blocks_assignment():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 500.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 20, 0, ports=None)], scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].ner_key == "N1"
    assert any("capacity unknown" in r for r in res.assignments[0].reasons)
    assert res.ner_load["N1"]["capacity_known"] is False


def test_a_ter_is_never_auto_assigned_as_the_serving_room():
    ter = NER(key="T1", label="TER", kind=ElementKind.TER, point=Point(11, 0, 1))
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ter, ner("N1", 60, 0)], scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].ner_key == "N1"
    assert "T1" not in res.ner_load


def test_an_unconfirmed_match_is_served_by_the_nearest_ner_and_still_flagged():
    """3.0.0 (Marcelo, 14 Oct 2026): the room the matcher found is served by
    the nearest NER; the row keeps saying the match is not confirmed."""
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, False)],
        ners=[ner("N1", 20, 0)], scale_for_page=SCALES, rules=RULES)
    a = res.assignments[0]
    assert a.status is Status.SERVED and a.ner_key == "N1"
    assert a.match_confirmed is False
    assert a.evaluation.requires_human_validation
    assert res.ner_load["N1"]["assigned_ports"] == 5.0


def test_unconfirmed_scale_blocks_the_whole_coverage_run():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 20, 0)], scale_for_page={1: unit_scale(confirmed=False)},
        rules=RULES)
    assert res.assignments[0].status is Status.SCALE_NOT_CONFIRMED


def test_results_are_deterministic_across_runs():
    args = dict(
        areas=[(area(f"A{i}", i * 7, 0), float(i), DemandType.GENERAL, None, True)
               for i in range(1, 12)],
        ners=[ner("N1", 10, 0, ports=40), ner("N2", 60, 0, ports=40)],
        scale_for_page=SCALES, rules=RULES)
    first = [a.to_dict() for a in compute_coverage(**args).assignments]
    for _ in range(3):
        assert [a.to_dict() for a in compute_coverage(**args).assignments] == first


# ---------------------------------------------------------------------------
# Floors and routes
# ---------------------------------------------------------------------------

def test_ners_on_different_floors_do_not_serve_each_other_by_default():
    res = compute_coverage(
        areas=[(area("A", 10, 0, page=1), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 12, 0, page=2)], scale_for_page=SCALES, rules=RULES)
    assert res.assignments[0].status is Status.NOT_ANALYSABLE
    assert "no NER on this level" in res.assignments[0].reasons[0]


def test_a_registered_shaft_enables_cross_floor_service():
    net = build_network(
        [RouteSegment(Point(10, 0, 1), Point(50, 0, 1), 1),
         RouteSegment(Point(50, 0, 2), Point(12, 0, 2), 2)],
        [VerticalLink("SH1", Point(50, 0, 1), Point(50, 0, 2), length_m=6.0)],
        SCALES)
    assert net.has_vertical_between(1, 2)
    res = compute_coverage(
        areas=[(area("A", 10, 0, page=1), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 12, 0, page=2)], scale_for_page=SCALES, rules=RULES,
        network=net)
    a = res.assignments[0]
    assert a.ner_key == "N1"
    assert a.evaluation.method.value == "route"
    assert a.evaluation.effective_distance_m == pytest.approx(84.0, abs=1.0)


def test_the_real_route_is_longer_than_the_straight_line_and_can_fail():
    net = RouteNetwork()
    sc = unit_scale()
    for a, b in (((10, 0), (10, 60)), ((10, 60), (70, 60)), ((70, 60), (70, 0))):
        net.add_segment(RouteSegment(Point(*a, 1), Point(*b, 1), 1), sc)
    straight = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 70, 0)], scale_for_page=SCALES, rules=RULES)
    routed = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 70, 0)], scale_for_page=SCALES, rules=RULES, network=net)
    assert straight.assignments[0].evaluation.effective_distance_m == pytest.approx(60.0)
    assert routed.assignments[0].evaluation.effective_distance_m == pytest.approx(180.0)
    assert straight.assignments[0].status is Status.SERVED
    assert routed.assignments[0].status is Status.OUT_OF_LIMIT


# ---------------------------------------------------------------------------
# Overlap and redundancy
# ---------------------------------------------------------------------------

def test_overlapping_ners_do_not_by_themselves_justify_removal():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 12, 0), ner("N2", 14, 0)],   # heavily overlapping coverage
        scale_for_page=SCALES, rules=RULES)
    ners = [ner("N1", 12, 0), ner("N2", 14, 0)]
    cands = redundancy_candidates(res, ners, RULES)
    assert len(cands) == 1 and cands[0]["ner_key"] == "N2"
    assert "Spatial redundancy candidate" in cands[0]["classification"]
    assert "capacity unknown" in cands[0]["blockers"]
    assert cands[0]["eligible_for_removal_analysis"] is False


def test_a_locked_or_critical_ner_is_never_eligible_for_removal_analysis():
    res = compute_coverage(
        areas=[(area("A", 10, 0), 5.0, DemandType.GENERAL, None, True)],
        ners=[ner("N1", 12, 0), ner("LOCK", 14, 0, ports=48, locked=True),
              ner("CRIT", 16, 0, ports=48, critical=True)],
        scale_for_page=SCALES, rules=RULES)
    ners = [ner("N1", 12, 0), ner("LOCK", 14, 0, ports=48, locked=True),
            ner("CRIT", 16, 0, ports=48, critical=True)]
    by_key = {c["ner_key"]: c for c in redundancy_candidates(res, ners, RULES)}
    assert "locked" in " ".join(by_key["LOCK"]["blockers"])
    assert "critical" in " ".join(by_key["CRIT"]["blockers"]).lower()
    assert all(not c["eligible_for_removal_analysis"] for c in by_key.values())

