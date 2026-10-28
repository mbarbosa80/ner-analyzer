"""The criticality matrix and how it reaches (or fails to reach) a venue.

Measured against the event's real matrix and the three live venue projects on
2026-08-31::

    VEE, 112 TEAP spaces
        exact space code        23   20.5%
        + parent code          +17   15.2%   ->  36%
        + fuzzy name            +2    1.8%   ->  38%
        no rule at all          70   62.5%

Those proportions are the reason the module is shaped the way it is: parent
inheritance is worth having and is labelled, name similarity is not worth
applying, and the majority of rooms have no rule at all — which must be
reported, not defaulted away.
"""

from __future__ import annotations

import pytest

from app.domain.criticality_matrix import (CRITICAL, NON_CRITICAL,
                                           ancestors, build_matrix)

# The real sheet's shape.
HEAD = ["Target Functions", "Target Room / Space Considerations", "Space Code",
        "HD Wi-Fi", "Critical NER", "Non-Critical NER", "Comments"]


def rows(*items):
    return [list(i) for i in items]


MATRIX = build_matrix(HEAD, rows(
    ["ACR", "Venue Accreditation Office", "ACR.001", "", "", "X", ""],
    ["BRS", "Broadcast Compound", "#N/A", "", "X", "", ""],
    ["", "Commentator Control Room", "BRS.051", "", "X", "", ""],
    ["PRS", "Venue Media Centre (VMC)", "PRS.001", "", "X", "", ""],
    ["", "Press Conference Room", "PRS.002", "", "", "X", ""],
    ["", "Photo Position - FOP", "#N/A", "", "X", "", ""],
))


# ---------------------------------------------------------------------------
# The three ways a rule reaches a space
# ---------------------------------------------------------------------------

def test_an_exact_space_code_is_stated():
    v = MATRIX.lookup("PRS.001", "Venue Media Centre")
    assert v.criticality == CRITICAL
    assert v.provenance == "stated"
    assert v.applies
    assert "stated by the matrix" in v.explain()


def test_a_child_code_inherits_and_says_so():
    """~16% of spaces arrive this way. It is applied, but never disguised as a
    direct statement — a reviewer must be able to disagree with one case
    without rejecting the whole rule."""
    v = MATRIX.lookup("PRS.001.03", "Photo Work Room")
    assert v.criticality == CRITICAL
    assert v.provenance == "inherited"
    assert v.matched_key == "PRS.001"
    assert v.applies
    assert "inherited from PRS.001" in v.explain()


def test_a_similar_name_is_proposed_and_never_applied():
    """Recovers under 2%, and getting it wrong promotes or demotes a room."""
    v = MATRIX.lookup("PRS.DUM.099", "Main Photo Position - FOP")
    assert v.provenance == "proposed"
    assert v.criticality == CRITICAL
    assert v.applies is False, "a name guess must not be written onto a space"
    assert "Not applied" in v.explain()


def test_a_space_with_no_rule_stays_unknown():
    v = MATRIX.lookup("VVO.001", "Field of Play - VOLLEYBALL")
    assert v.criticality is None
    assert v.provenance is None
    assert v.applies is False
    assert "not stated in the criticality matrix" in v.explain()


def test_a_missing_rule_never_becomes_non_critical():
    """The failure that would matter most, stated as its own test.

    Non-critical is a *permission* — it lets any room serve the space. Reading
    an absent rule as non-critical grants a permission the matrix never gave,
    and it does so silently, for the 62% of rooms the matrix does not cover.
    """
    for code, name in (("MED.002", "Athlete Medical Station"),
                       ("OBS.95.01", "Central Technical Area (CTA)"),
                       ("NRG.DUM.003", "Power Generator")):
        v = MATRIX.lookup(code, name)
        assert v.criticality != NON_CRITICAL, f"{code} was silently permitted"


# ---------------------------------------------------------------------------
# The code hierarchy
# ---------------------------------------------------------------------------

def test_ancestors_walk_from_nearest_to_furthest():
    assert ancestors("PRS.001.03") == ["PRS.001", "PRS"]


def test_placeholder_segments_are_not_treated_as_levels():
    """``PRS.DUM.099`` is "some photo position", not the 99th child of DUM.

    Keeping DUM would invent an ancestor ``PRS.DUM`` that no matrix will ever
    contain, and the walk would waste its most useful step.
    """
    assert ancestors("PRS.DUM.099") == ["PRS"]
    assert "PRS.DUM" not in ancestors("PRS.DUM.099")


def test_an_instance_suffix_is_not_a_level():
    assert ancestors("PRS.007.01-001") == ["PRS.007", "PRS"]


def test_a_top_level_code_has_no_ancestors():
    assert ancestors("ACR") == []
    assert ancestors("") == []
    assert ancestors("#N/A") == []


def test_inheritance_prefers_the_nearest_ancestor():
    m = build_matrix(HEAD, rows(
        ["", "Parent", "SPT", "", "X", "", ""],
        ["", "Nearer parent", "SPT.300", "", "", "X", ""],
    ))
    v = m.lookup("SPT.300.03", "Video Control Area")
    assert v.matched_key == "SPT.300"
    assert v.criticality == NON_CRITICAL, "the nearest rule must win"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_rows_with_no_space_code_are_kept_for_name_matching():
    """The real matrix has seven of these — Broadcast Compound, Photo Position
    and friends, all with ``#N/A`` where the code should be."""
    assert "broadcast compound" in MATRIX.by_name
    assert "#N/A" not in MATRIX.by_code
    assert not any(k.startswith("#") for k in MATRIX.by_code)


def test_a_row_ticked_both_ways_is_recorded_as_a_conflict():
    m = build_matrix(HEAD, rows(
        ["", "Impossible Room", "IMP.001", "", "X", "X", ""],
    ))
    assert m.conflicts == ["Impossible Room"]
    assert "IMP.001" not in m.by_code, "a contradiction must not become a value"


def test_a_sheet_without_the_columns_is_refused_with_a_useful_message():
    with pytest.raises(ValueError) as e:
        build_matrix(["Space Code", "Space Name"], rows(["A.1", "Room"]))
    assert "Critical NER" in str(e.value)


# ---------------------------------------------------------------------------
# Coverage reporting
# ---------------------------------------------------------------------------

def test_coverage_reports_the_gap_rather_than_hiding_it():
    spaces = [
        ("PRS.001", "Venue Media Centre"),        # stated
        ("PRS.001.03", "Photo Work Room"),        # inherited
        ("PRS.DUM.099", "Main Photo Position - FOP"),   # proposed
        ("VVO.001", "Field of Play - VOLLEYBALL"),      # nothing
        ("MED.002", "Athlete Medical Station"),         # nothing
    ]
    report = MATRIX.coverage(spaces)
    assert report["total_spaces"] == 5
    assert report["by_provenance"] == {"stated": 1, "inherited": 1,
                                       "proposed": 1, "unknown": 2}
    assert report["applied"] == 2
    assert report["applied_pct"] == 40.0
    assert report["rule_missing"] == 2
    assert [g["space_code"] for g in report["gaps"]] == ["VVO.001", "MED.002"]
    assert report["alias_proposals"][0]["space_code"] == "PRS.DUM.099"
    assert "permission" in report["note"], (
        "the report must say why a missing rule is not treated as non-critical")


def test_coverage_of_an_empty_venue_does_not_divide_by_zero():
    report = MATRIX.coverage([])
    assert report["total_spaces"] == 0
    assert report["applied_pct"] == 0.0
    assert report["rule_missing_pct"] == 0.0
