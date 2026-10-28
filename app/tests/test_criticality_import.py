"""Reading criticality out of the TEAP, in the shape the TEAP actually uses.

The application has enforced criticality since V1: ``_criticality_ok`` refuses
to let a non-critical room serve a critical space, and there are tests for it.
None of that had ever run on real data. A probe of the live database on
2026-08-31 returned::

    teap_spaces (279 rows)   criticality: [(None, 279)]

Every row null. The importer was looking for a single column called
``criticality`` / ``critical`` / ``priority`` / ``tier``; the event's sheets carry
a **pair** of columns ticked with an X — ``Critical NER`` and
``Non-Critical NER``. Nothing matched, so nothing was read, so every space fell
through to "criticality not stated in the TEAP — nearest compatible NER" and
was assigned on distance alone.

These tests exist so that cannot happen quietly again.
"""

from __future__ import annotations

from app.domain.teap_import import (TICKED, detect_criticality_columns,
                                    is_ticked)


# ---------------------------------------------------------------------------
# Finding the pair
# ---------------------------------------------------------------------------

def test_the_two_columns_are_told_apart():
    """The whole reason this needs its own resolver.

    "critical ner" is a substring of "non-critical ner". Generic substring
    matching maps both headers onto the critical field and every non-critical
    space silently becomes critical — the worst available direction for this
    error, because it inflates the critical count and drives NER upgrades
    nobody asked for.
    """
    found = detect_criticality_columns(
        ["Target Function", "Target Room / Space Considerations", "Space Code",
         "HD Wi-Fi", "Critical NER", "Non-Critical NER", "Comments"])
    assert found["critical_flag"] == "Critical NER"
    assert found["non_critical_flag"] == "Non-Critical NER"


def test_the_order_of_the_columns_does_not_matter():
    found = detect_criticality_columns(["Non-Critical NER", "Critical NER"])
    assert found["critical_flag"] == "Critical NER"
    assert found["non_critical_flag"] == "Non-Critical NER"


def test_various_spellings_of_the_negation():
    for header in ("Non Critical NER", "Non-critical", "NÃO CRÍTICA", "Not critical"):
        found = detect_criticality_columns(["Critical NER", header])
        assert found["non_critical_flag"] == header, header
        assert found["critical_flag"] == "Critical NER", header


def test_a_sheet_with_neither_column_finds_nothing():
    found = detect_criticality_columns(["Space Code", "Space Name", "Qty"])
    assert found == {"critical_flag": None, "non_critical_flag": None}


def test_a_single_criticality_column_is_not_mistaken_for_the_pair():
    """A TEAP with one word-bearing column must not have it read as a tick box."""
    found = detect_criticality_columns(["Space Code", "Criticality"])
    assert found["critical_flag"] == "Criticality"
    assert found["non_critical_flag"] is None


# ---------------------------------------------------------------------------
# Reading a tick
# ---------------------------------------------------------------------------

def test_the_marks_people_actually_use_are_read():
    for mark in ("X", "x", " x ", "Yes", "sim", "TRUE", "1", "✓"):
        assert is_ticked(mark) is True, mark


def test_an_empty_cell_means_not_this_one():
    for blank in ("", "   ", "-", "N/A", "no", "0"):
        assert is_ticked(blank) is False, blank


def test_a_failed_lookup_is_unknown_and_not_a_no():
    """``#N/A`` is the sheet failing to answer, which is not the same as
    answering "not critical" — and the screenshots show plenty of them.

    Collapsing the two would quietly mark unknown spaces as non-critical, and a
    non-critical space is one the analysis is happy to serve from any room.
    """
    for residue in ("#N/A", "#REF!", "#VALUE!", "#NAME?"):
        assert is_ticked(residue) is None, residue
    assert is_ticked(None) is None


def test_the_tick_vocabulary_is_lower_case():
    """``is_ticked`` lower-cases before comparing; a stray upper-case entry in
    the table would be unreachable and the bug would be invisible."""
    assert all(m == m.lower() for m in TICKED)


# ---------------------------------------------------------------------------
# Turning the pair into a value
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, **values):
        self._v = values

    def get(self, name, default=None):
        return self._v.get(name, default)


def _read(**values):
    from app.domain.demand import _read_criticality
    return _read_criticality(_Row(**values))


def test_a_ticked_critical_column_reads_critical():
    assert _read(critical_flag="X", non_critical_flag="") == "critical"


def test_a_ticked_non_critical_column_reads_non_critical():
    assert _read(critical_flag="", non_critical_flag="X") == "non-critical"


def test_neither_ticked_is_unknown():
    assert _read(critical_flag="", non_critical_flag="") is None


def test_both_ticked_is_a_conflict_and_never_a_guess():
    """A space cannot be both. Picking one silently would put a fabricated
    value into a study that drives equipment decisions."""
    from app.domain.demand import CRITICALITY_CONFLICT
    assert _read(critical_flag="X", non_critical_flag="X") == CRITICALITY_CONFLICT


def test_the_pair_wins_over_a_single_column():
    """The pair is the more specific statement."""
    assert _read(critical_flag="X", criticality="low") == "critical"


def test_a_single_column_teap_still_works():
    assert _read(criticality="Critical") == "Critical"
    assert _read(criticality="  ") is None


# ---------------------------------------------------------------------------
# What the value means downstream
# ---------------------------------------------------------------------------

def test_the_words_this_reader_emits_are_the_words_coverage_understands():
    """The reader writes into ``TeapSpace.criticality``; ``services`` turns that
    string into the boolean the coverage engine uses, by membership in a fixed
    tuple. If those two vocabularies drift, criticality silently stops working
    again — which is exactly the failure this module exists to end.
    """
    truthy = ("critical", "yes", "true", "high", "1", "crítico")
    assert "critical" in truthy, "a critical space must read as critical"
    assert "non-critical" not in truthy, "a non-critical space must not read as critical"


# ---------------------------------------------------------------------------
# The enforcement gate
# ---------------------------------------------------------------------------

def test_criticality_does_not_constrain_assignments_by_default():
    """Reading criticality must not, by itself, change any coverage result.

    The engine has always been able to refuse a non-critical room for a
    critical space. Until the criticality matrix existed that rule had no data
    and never fired. Letting it switch on the moment the data lands would
    silently re-open every live study: spaces served today would become
    unserved, and change requests already sent to the drawing team would rest
    on numbers that moved underneath them.

    So the data arrives, the reports use it, and the hard constraint stays off
    until someone turns it on for that project.
    """
    from app.models import Project
    assert Project.__table__.c.criticality_enforced.default.arg is False


def test_the_gate_is_read_before_criticality_reaches_coverage():
    """Guards the wiring, not just the default.

    A setting nobody consults is not a setting. If this ever stops being read,
    the default above becomes decoration and the study silently changes.
    """
    import inspect as _inspect
    from app import services
    src = _inspect.getsource(services.collect_areas)
    assert "criticality_enforced" in src, (
        "collect_areas must consult the project's enforcement setting before "
        "turning a stated criticality into a hard constraint")
