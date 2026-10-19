"""Overlap removal: only when the simulation says the spaces survive.

The rule as originally stated — "two NERs within 90 m serving the same area,
suggest removing the non-critical one" — would have been looser than what the
application already did, which only ever flagged a room carrying zero load.
These tests pin the safe version: a suggestion appears only when every space
the room serves can still be reached by another room that has the ports free.
"""

from __future__ import annotations

from app.domain.coverage import NER, compute_coverage
from app.domain.distance import DemandType, DistanceRules
from app.domain.geometry import Area, Point
from app.domain.overlap import overlapping_candidates
from app.domain.pdf_ingest import ElementKind
from app.domain.units import Scale

RULES = DistanceRules()
SCALES = {1: Scale(metres_per_unit=1.0, source="manual", label="1u=1m",
                   confirmed=True)}


def area(key, x, y, page=1, name=""):
    return Area(key=key, name=name or key, page=page,
                label_point=Point(x, y, page))


def ner(key, x, y, *, critical=False, ports=100, page=1, label=None):
    return NER(key=key, label=label or key,
               kind=ElementKind.NER_CRITICAL if critical else ElementKind.NER_NONCRITICAL,
               point=Point(x, y, page), critical=critical, total_ports=ports)


def run(areas, ners):
    spec = [(a, p, DemandType.GENERAL, c, True) for a, p, c in areas]
    result = compute_coverage(areas=spec, ners=ners, scale_for_page=SCALES,
                              rules=RULES)
    by_key = {a.key: (a, p, DemandType.GENERAL, c) for a, p, c in areas}
    return result, overlapping_candidates(result, ners, RULES, SCALES,
                                          areas_by_key=by_key)


def test_a_non_critical_room_beside_a_critical_one_can_be_given_up():
    """The case the rule was written for. The critical room has the ports, so
    the non-critical one is genuinely spare."""
    areas = [(area("A", 10, 0), 5.0, None), (area("B", 12, 0), 5.0, None)]
    ners = [ner("CRIT", 0, 0, critical=True, ports=100),
            ner("NONCRIT", 20, 0, critical=False, ports=100)]
    _, cands = run(areas, ners)
    removable = [c for c in cands if c["can_be_removed"]]
    assert removable, "an overlapping non-critical room with a spare partner " \
                      "should be a candidate"
    assert all(c["critical"] is False for c in removable), \
        "the critical room of a pair is never the one proposed for removal"


def test_the_critical_room_of_a_pair_is_never_proposed():
    areas = [(area("A", 10, 0), 5.0, None)]
    ners = [ner("CRIT", 0, 0, critical=True), ner("NONCRIT", 20, 0)]
    _, cands = run(areas, ners)
    crit = [c for c in cands if c["ner_key"] == "CRIT"]
    if crit:
        assert not crit[0]["can_be_removed"]
        assert any("critical room of the pair" in b for b in crit[0]["blockers"])


def test_a_room_is_kept_when_the_survivor_has_no_ports_left():
    """This is the VMC case, and it arrives as capacity rather than as a
    hand-set cable threshold: the partner simply cannot take the load."""
    areas = [(area("A", 10, 0), 90.0, None), (area("B", 12, 0), 90.0, None)]
    ners = [ner("CRIT", 0, 0, critical=True, ports=100),
            ner("NONCRIT", 20, 0, critical=False, ports=100)]
    _, cands = run(areas, ners)
    for c in cands:
        if c["can_be_removed"]:
            continue
        assert c["blockers"], "a refusal must always carry its reason"
    assert not any(c["can_be_removed"] for c in cands), \
        "with 180 ports of demand and 100 in the survivor, nothing is spare"


def test_a_room_serving_something_nothing_else_reaches_is_kept():
    """Overlap on one space does not make a room redundant: it may be the only
    room within limit of another."""
    areas = [(area("NEAR", 10, 0), 5.0, None),
             (area("FAR", 200, 0), 5.0, None)]
    ners = [ner("A", 0, 0, critical=True), ner("B", 195, 0, critical=False)]
    _, cands = run(areas, ners)
    b = [c for c in cands if c["ner_key"] == "B"]
    if b:
        assert not b[0]["can_be_removed"]


def test_rooms_that_do_not_overlap_are_not_candidates():
    areas = [(area("A", 10, 0), 5.0, None), (area("B", 500, 0), 5.0, None)]
    ners = [ner("A1", 0, 0), ner("B1", 495, 0)]
    _, cands = run(areas, ners)
    assert cands == [], "rooms far apart are not an overlapping pair"


def test_a_locked_room_is_never_proposed():
    areas = [(area("A", 10, 0), 5.0, None)]
    a = ner("CRIT", 0, 0, critical=True)
    b = ner("NONCRIT", 20, 0)
    b.locked = True
    _, cands = run(areas, [a, b])
    nc = [c for c in cands if c["ner_key"] == "NONCRIT"]
    if nc:
        assert not nc[0]["can_be_removed"]
        assert any("locked" in x for x in nc[0]["blockers"])


def test_a_critical_space_is_never_reassigned_to_a_non_critical_room():
    """Even in the simulation. Moving a critical space onto a non-critical room
    to justify a removal would be a worse outcome than the overlap."""
    areas = [(area("CRITSPACE", 10, 0), 5.0, True)]
    ners = [ner("C1", 0, 0, critical=True), ner("C2", 20, 0, critical=True),
            ner("N1", 15, 0, critical=False)]
    _, cands = run(areas, ners)
    for c in cands:
        for r in c["reassignments"]:
            if r["space_key"] == "CRITSPACE":
                assert r["to"] in ("C1", "C2"), \
                    "a critical space must not land on a non-critical room"


def test_every_suggestion_shows_where_each_space_would_go():
    """A proposal the reviewer cannot check is not a proposal."""
    areas = [(area("A", 10, 0), 5.0, None), (area("B", 12, 0), 5.0, None)]
    ners = [ner("CRIT", 0, 0, critical=True, ports=100),
            ner("NONCRIT", 20, 0, critical=False, ports=100)]
    _, cands = run(areas, ners)
    for c in cands:
        if c["can_be_removed"]:
            assert c["reassignments"], "must name the destination of every space"
            for r in c["reassignments"]:
                assert r["to"] and r["distance_m"] >= 0


def test_the_check_refuses_to_guess_without_the_space_positions():
    areas = [(area("A", 10, 0), 5.0, None)]
    ners = [ner("CRIT", 0, 0, critical=True), ner("NONCRIT", 20, 0)]
    spec = [(a, p, DemandType.GENERAL, c, True) for a, p, c in areas]
    result = compute_coverage(areas=spec, ners=ners, scale_for_page=SCALES,
                              rules=RULES)
    cands = overlapping_candidates(result, ners, RULES, SCALES, areas_by_key=None)
    for c in cands:
        assert not c["can_be_removed"]
        assert any("cannot simulate" in b for b in c["blockers"])
