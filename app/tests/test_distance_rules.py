"""Mandatory distance tests (specification section 20)."""

import math
import pytest

from app.domain.distance import (DemandType, DistanceMethod, DistanceRules, Status,
                                 evaluate_area, evaluate_distance)
from app.domain.geometry import Area, Point
from app.domain.units import (Scale, POINTS_PER_METRE, parse_scale_text,
                              scale_from_ratio, scale_from_two_points, format_length)

RULES = DistanceRules()


def scale_1_to_1() -> Scale:
    """A scale where 1 PDF unit == 1 metre, confirmed. Keeps the tests readable."""
    return Scale(metres_per_unit=1.0, source="manual", label="test 1u=1m", confirmed=True)


# --- 89 m passes / 91 m fails ------------------------------------------------

def test_general_point_at_89m_passes():
    ev = evaluate_distance(distance_units=89.0, scale=scale_1_to_1(), rules=RULES,
                           demand_type=DemandType.GENERAL)
    assert ev.compliant
    assert ev.status is Status.NEAR_LIMIT      # 89 > 0.90 * 90 = 81
    assert ev.effective_distance_m == pytest.approx(89.0)
    assert ev.margin_m == pytest.approx(1.0)


def test_general_point_at_91m_fails():
    ev = evaluate_distance(distance_units=91.0, scale=scale_1_to_1(), rules=RULES,
                           demand_type=DemandType.GENERAL)
    assert not ev.compliant
    assert ev.status is Status.OUT_OF_LIMIT
    assert ev.margin_m == pytest.approx(-1.0)


def test_photographer_point_at_69m_passes():
    ev = evaluate_distance(distance_units=69.0, scale=scale_1_to_1(), rules=RULES,
                           demand_type=DemandType.PHOTOGRAPHER)
    assert ev.compliant
    assert ev.limit_m == 70.0


def test_photographer_point_at_71m_fails():
    ev = evaluate_distance(distance_units=71.0, scale=scale_1_to_1(), rules=RULES,
                           demand_type=DemandType.PHOTOGRAPHER)
    assert not ev.compliant
    assert ev.status is Status.OUT_OF_LIMIT


def test_photographer_limit_is_stricter_than_general_at_same_distance():
    for dt, expected in ((DemandType.GENERAL, True), (DemandType.PHOTOGRAPHER, False)):
        ev = evaluate_distance(distance_units=75.0, scale=scale_1_to_1(), rules=RULES,
                               demand_type=dt)
        assert ev.compliant is expected


# --- straight line vs real route ---------------------------------------------

def test_straight_line_emits_the_mandatory_warning():
    ev = evaluate_distance(distance_units=50.0, scale=scale_1_to_1(), rules=RULES)
    assert any("straight-line" in w.lower() for w in ev.warnings)
    assert ev.requires_human_validation is True


def test_route_length_differs_from_straight_line_and_can_flip_the_verdict():
    straight = evaluate_distance(distance_units=80.0, scale=scale_1_to_1(), rules=RULES)
    route = evaluate_distance(distance_units=None, scale=scale_1_to_1(), rules=RULES,
                              method=DistanceMethod.ROUTE, route_length_m=104.0)
    assert straight.compliant and not route.compliant
    assert route.method is DistanceMethod.ROUTE
    assert route.requires_human_validation is False


def test_routing_slack_factor_makes_a_marginal_point_non_compliant():
    """The engineering point: 75 m in a straight line is not 75 m of cable."""
    lax = DistanceRules(routing_slack_factor=1.0)
    real = DistanceRules(routing_slack_factor=1.3)
    assert evaluate_distance(distance_units=75.0, scale=scale_1_to_1(), rules=lax).compliant
    ev = evaluate_distance(distance_units=75.0, scale=scale_1_to_1(), rules=real)
    assert not ev.compliant
    assert ev.geometric_distance_m == pytest.approx(75.0)
    assert ev.effective_distance_m == pytest.approx(97.5)


def test_slack_factor_below_one_is_rejected():
    with pytest.raises(ValueError):
        DistanceRules(routing_slack_factor=0.9)


# --- scale -------------------------------------------------------------------

def test_metric_scale_parsing():
    s = parse_scale_text("SCALE  1 : 200")
    assert s is not None and s.source == "ratio"
    assert s.denominator == pytest.approx(200.0)
    # 1 metre on paper at 1:200 is 200 m on the ground
    assert s.to_metres(POINTS_PER_METRE) == pytest.approx(200.0)


def test_imperial_architectural_scale_parsing():
    s = parse_scale_text('1/8" = 1\'-0"')
    assert s is not None and s.source == "architectural"
    assert s.denominator == pytest.approx(96.0)


def test_imperial_and_metric_scales_agree_on_a_known_length():
    metric = scale_from_ratio(100.0)
    # 1:100 -> 1 cm on paper is 1 m. 1 cm = 0.01 * POINTS_PER_METRE pdf units.
    assert metric.to_metres(0.01 * POINTS_PER_METRE) == pytest.approx(1.0)
    imperial = parse_scale_text('1" = 20\'')
    assert imperial.denominator == pytest.approx(240.0)


def test_pages_with_different_scales_are_kept_separate():
    scales = {1: scale_from_ratio(1500.0).confirm(), 8: scale_from_ratio(200.0).confirm()}
    d_units = 200.0
    # the very same 200 pdf units mean 105.8 m on the key plan and 14.1 m on the
    # enlarged plan, so the page a measurement came from changes the verdict
    assert scales[1].to_metres(d_units) == pytest.approx(105.84, abs=0.05)
    assert scales[8].to_metres(d_units) == pytest.approx(14.11, abs=0.05)
    ev1 = evaluate_distance(distance_units=d_units, scale=scales[1], rules=RULES)
    ev8 = evaluate_distance(distance_units=d_units, scale=scales[8], rules=RULES)
    assert not ev1.compliant and ev8.compliant


def test_manual_two_point_calibration():
    s = scale_from_two_points(pdf_distance_units=283.46, real_distance=10.0, unit="m")
    assert s.to_metres(283.46) == pytest.approx(10.0)
    assert s.denominator == pytest.approx(100.0, rel=1e-3)


def test_manual_calibration_in_feet():
    s = scale_from_two_points(pdf_distance_units=100.0, real_distance=32.8084, unit="ft")
    assert s.to_metres(100.0) == pytest.approx(10.0, rel=1e-4)


def test_unconfirmed_scale_blocks_a_definitive_result():
    unconfirmed = scale_from_ratio(200.0)          # confirmed=False by default
    ev = evaluate_distance(distance_units=10.0, scale=unconfirmed, rules=RULES)
    assert ev.status is Status.SCALE_NOT_CONFIRMED
    assert not ev.compliant


def test_display_in_metres_feet_or_both():
    assert format_length(90.0, "m") == "90.0 m"
    assert format_length(90.0, "ft").startswith("295.")
    assert "(" in format_length(90.0, "both")


# --- areas, polygons, floors --------------------------------------------------

def test_farthest_polygon_vertex_governs_compliance():
    ner = Point(0.0, 0.0, page=1)
    area = Area(key="a", name="Hall", page=1, label_point=Point(60.0, 0.0, 1),
                polygon=[(50, -20), (85, -20), (85, 20), (50, 20)])
    ev = evaluate_area(area=area, ner_point=ner, scale=scale_1_to_1(), rules=RULES)
    assert ev.farthest_point_distance_m > ev.geometric_distance_m
    assert ev.farthest_point_distance_m == pytest.approx(math.hypot(85, 20))   # 87.3 m
    assert ev.effective_distance_m == pytest.approx(math.hypot(85, 20))
    # the centroid alone would have read ~67.5 m and looked comfortable
    assert ev.geometric_distance_m < 70.0
    assert ev.status is Status.NEAR_LIMIT
    assert any("farthest vertex" in a for a in ev.assumptions)


def test_farthest_polygon_vertex_can_fail_a_room_whose_centre_passes():
    ner = Point(0.0, 0.0, page=1)
    area = Area(key="a", name="Concourse", page=1, label_point=Point(70.0, 0.0, 1),
                polygon=[(50, -30), (95, -30), (95, 30), (50, 30)])
    ev = evaluate_area(area=area, ner_point=ner, scale=scale_1_to_1(), rules=RULES)
    assert ev.geometric_distance_m < 90.0        # centre passes
    assert not ev.compliant                       # farthest corner does not
    assert ev.status is Status.OUT_OF_LIMIT


def test_area_without_polygon_is_flagged_as_an_estimate():
    ner = Point(0.0, 0.0, page=1)
    area = Area(key="a", name="Office", page=1, label_point=Point(30.0, 0.0, 1),
                estimated=True)
    ev = evaluate_area(area=area, ner_point=ner, scale=scale_1_to_1(), rules=RULES)
    assert any("estimated" in a.lower() for a in ev.assumptions)
    assert ev.compliant


def test_cross_floor_without_a_vertical_route_is_not_analysable():
    ner = Point(0.0, 0.0, page=2)
    area = Area(key="a", name="Office", page=1, label_point=Point(10.0, 0.0, 1))
    ev = evaluate_area(area=area, ner_point=ner, scale=scale_1_to_1(), rules=RULES)
    assert ev.status is Status.NOT_ANALYSABLE
    assert any("different drawing pages" in w for w in ev.warnings)


def test_cross_floor_with_a_registered_route_is_analysable():
    ner = Point(0.0, 0.0, page=2)
    area = Area(key="a", name="Office", page=1, label_point=Point(10.0, 0.0, 1))
    ev = evaluate_area(area=area, ner_point=ner, scale=scale_1_to_1(), rules=RULES,
                       route_length_m=45.0)
    assert ev.status is Status.SERVED
    assert ev.method is DistanceMethod.ROUTE


def test_straight_line_between_pages_raises():
    with pytest.raises(ValueError):
        Point(0, 0, page=1).distance_units(Point(1, 1, page=2))


# --- match confirmation gate ---------------------------------------------------

def test_unconfirmed_match_keeps_the_verdict_and_asks_for_validation():
    ev = evaluate_distance(distance_units=10.0, scale=scale_1_to_1(), rules=RULES,
                           match_confirmed=False)
    assert ev.status is Status.SERVED
    assert ev.requires_human_validation
    assert any("not yet confirmed" in s for s in ev.assumptions)


def test_configurable_limits_are_honoured():
    custom = DistanceRules(general_limit_m=75.0, photographer_limit_m=55.0)
    assert not evaluate_distance(distance_units=80.0, scale=scale_1_to_1(),
                                 rules=custom).compliant
    assert evaluate_distance(distance_units=70.0, scale=scale_1_to_1(),
                             rules=custom).compliant
