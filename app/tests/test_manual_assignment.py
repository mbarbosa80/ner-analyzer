"""Choosing which NER serves which space, and what that choice may not buy.

The engine assigns every space to the nearest compatible room. That is right
until it is not: putting a second NER beside an existing one is a statement
geometry cannot make — the old room is full, or critical and non-critical
services must not share it. Neither is visible to a distance calculation, so
the decision has to be sayable.

The whole risk of the feature is in what a pin is allowed to change. It settles
**which** room. It must not settle whether that room is close enough, critical
enough, or has ports left, because the case it exists for is precisely "the
other room is overloaded" — a pin that silenced the overload would be a way of
laundering a violation through the register. These tests exist mostly to hold
that line.
"""

from __future__ import annotations

import pytest

from app.domain.coverage import NER, compute_coverage
from app.domain.distance import DemandType, DistanceRules, Status
from app.domain.geometry import Area, Point
from app.domain.pdf_ingest import ElementKind
from app.domain.units import Scale

RULES = DistanceRules()
SCALES = {1: Scale(metres_per_unit=1.0, source="manual", label="1u=1m",
                   confirmed=True)}


def area(key="SPACE", x=10.0, y=0.0):
    return Area(key=key, name=key, page=1, label_point=Point(x, y, 1))


def ner(key, x, *, critical=False, ports=100, used=0):
    return NER(key=key, label=f"room {key}",
               kind=ElementKind.NER_CRITICAL if critical else ElementKind.NER_NONCRITICAL,
               point=Point(x, 0.0, 1), critical=critical, total_ports=ports,
               used_ports=used)


def run(areas, ners, pinned=None, is_critical=None, ports=5.0):
    spec = [(a, ports, DemandType.GENERAL, is_critical, True) for a in areas]
    return compute_coverage(areas=spec, ners=ners, scale_for_page=SCALES,
                            rules=RULES, pinned=pinned)


# ---------------------------------------------------------------------------
# The choice is honoured
# ---------------------------------------------------------------------------

def test_without_a_pin_the_nearest_room_still_wins():
    """The regression guard. Nothing changes for a project nobody has pinned."""
    res = run([area(x=10)], [ner("NEAR", 0), ner("FAR", 60)])
    a = res.assignments[0]
    assert a.ner_key == "NEAR"
    assert a.pinned is False


def test_a_pinned_room_is_used_even_though_another_is_nearer():
    """The case Marcelo described: a new room beside an existing one, because
    the existing one cannot take this space."""
    res = run([area(x=10)], [ner("NEAR", 0), ner("CHOSEN", 60)],
              pinned={"SPACE": "CHOSEN"})
    a = res.assignments[0]
    assert a.ner_key == "CHOSEN", "the room a person chose must win over the nearest"
    assert a.pinned is True
    assert any("because you assigned it" in r for r in a.reasons), \
        "and the report must say the choice was yours, not the geometry's"


def test_the_load_lands_on_the_room_that_was_chosen():
    """Otherwise the utilisation figures would describe a different design."""
    res = run([area(x=10)], [ner("NEAR", 0), ner("CHOSEN", 60)],
              pinned={"SPACE": "CHOSEN"}, ports=7.0)
    assert res.ner_load["CHOSEN"]["assigned_ports"] == 7.0
    assert res.ner_load["NEAR"]["assigned_ports"] == 0.0


# ---------------------------------------------------------------------------
# The line the pin must not cross
# ---------------------------------------------------------------------------

def test_a_pin_does_not_make_a_distance_compliant():
    """200 m is 200 m whoever chose it."""
    res = run([area(x=0)], [ner("NEAR", 5), ner("MILES", 200)],
              pinned={"SPACE": "MILES"})
    a = res.assignments[0]
    assert a.ner_key == "MILES"
    assert a.status is Status.OUT_OF_LIMIT, \
        "a pinned room out of limit must still report out of limit"
    assert any("the assignment stands, the distance does not" in r for r in a.reasons)


def test_a_pinned_violation_still_reaches_the_exception_list():
    """Hiding it because a person chose it is the one thing this must not do."""
    res = run([area(x=0)], [ner("NEAR", 5), ner("MILES", 200)],
              pinned={"SPACE": "MILES"})
    assert any(e["space_key"] == "SPACE" for e in res.exceptions), \
        "a pinned assignment that breaks the limit is an exception like any other"
    assert any("by you" in e["detail"] for e in res.exceptions)


def test_a_pin_does_not_manufacture_spare_ports():
    """The exact case the feature is for, inverted: pinning a room that is
    already full has to come back as full, or the tool stops being useful for
    the decision it is supposed to support."""
    res = run([area(x=10)], [ner("FULL", 0, ports=10, used=10), ner("FREE", 20)],
              pinned={"SPACE": "FULL"}, ports=5.0)
    a = res.assignments[0]
    assert a.ner_key == "FULL"
    assert a.status is Status.INSUFFICIENT_CAPACITY
    assert any("over capacity" in r for r in a.reasons)


def test_a_pin_does_not_silence_a_criticality_mismatch():
    res = run([area(x=10)], [ner("NONCRIT", 0), ner("CRIT", 20, critical=True)],
              pinned={"SPACE": "NONCRIT"}, is_critical=True)
    a = res.assignments[0]
    assert a.ner_key == "NONCRIT"
    assert any("not critical-rated" in r for r in a.reasons), \
        "the mismatch has to be stated, even though the choice is honoured"


def test_distance_out_of_limit_outranks_capacity_in_the_status():
    """One status per row, and the harder failure is the one worth showing."""
    res = run([area(x=0)], [ner("MILES", 200, ports=10, used=10)],
              pinned={"SPACE": "MILES"}, ports=5.0)
    assert res.assignments[0].status is Status.OUT_OF_LIMIT


# ---------------------------------------------------------------------------
# When the pinned room is not there any more
# ---------------------------------------------------------------------------

def test_a_pin_to_a_room_that_is_gone_falls_back_and_says_so():
    """Silently reverting to the nearest room would leave a reviewer looking at
    an assignment they did not make and cannot account for."""
    res = run([area(x=10)], [ner("NEAR", 0)], pinned={"SPACE": "DELETED"})
    a = res.assignments[0]
    assert a.ner_key == "NEAR", "the space must still be served"
    assert a.pinned is False
    assert any("no longer available" in r for r in a.reasons)


def test_a_pin_for_a_different_space_does_not_leak():
    res = run([area("A", x=10), area("B", x=12)],
              [ner("NEAR", 0), ner("CHOSEN", 60)], pinned={"A": "CHOSEN"})
    by_key = {a.space_key: a for a in res.assignments}
    assert by_key["A"].ner_key == "CHOSEN" and by_key["A"].pinned is True
    assert by_key["B"].ner_key == "NEAR" and by_key["B"].pinned is False


def test_the_pin_is_visible_in_the_exported_row():
    """The sheet has to distinguish "the engine chose this" from "you did"."""
    res = run([area(x=10)], [ner("NEAR", 0), ner("CHOSEN", 60)],
              pinned={"SPACE": "CHOSEN"})
    assert res.assignments[0].to_dict()["pinned"] is True


def test_the_pinned_room_is_the_one_the_sheet_reports(tmp_path):
    """The "Chosen by" column was taken off the workbook when the sheet was cut
    back to the TEAP plus the answer. What must not be lost is the answer
    itself: the room a person pinned is the room the export names."""
    import openpyxl
    from app.domain.reports import export_workbook

    class _D:                       # the exporter's demand adapter
        def __init__(self, key):
            self.space_key, self.space_name, self.space_code = key, key, key
            self.total_ports, self.warnings, self.lines = 1.0, [], []

        def breakdown(self):
            return ["TOTAL = 1 port(s)"]

    res = run([area("A", x=10), area("B", x=12)],
              [ner("NEAR", 0), ner("CHOSEN", 60)], pinned={"A": "CHOSEN"})
    out = str(tmp_path / "wb.xlsx")
    export_workbook(out, coverage=res, ners=[], demands=[_D("A"), _D("B")],
                    rules=RULES, project_name="t", scale_for_page=SCALES)
    ws = openpyxl.load_workbook(out)["TEAP and coverage"]
    h = [c.value for c in ws[1]]
    assert "Serving NER" in h and "NER critical" in h
    got = {ws.cell(r, h.index("Space code") + 1).value:
           ws.cell(r, h.index("Serving NER") + 1).value
           for r in range(2, ws.max_row + 1)}
    assert "CHOSEN" in got["A"], "the pinned room has to survive into the export"
    assert "NEAR" in got["B"]
