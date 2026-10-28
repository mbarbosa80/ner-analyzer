"""Every table in the interface sorts by clicking its headings.

A guard on the thing that will actually regress. The sorting itself lives in one
component, so it is unlikely to break; what breaks is the next table somebody
adds, rendered as a plain ``<thead>`` because that is what the surrounding code
looked like. This test reads the sources and fails when a table has no clickable
heading, or has clickable headings whose sorted rows are never used.

It checks structure, not behaviour. The comparison rules — three-state cycling,
blanks last in both directions, numbers inside text compared as numbers — are
not covered here: this project has no JavaScript test runner, and adding one
mid-flight was not worth the risk to a build the user depends on. Saying so is
better than implying a coverage that does not exist.
"""

from __future__ import annotations

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"
FILES = sorted(SRC.glob("pages/*.tsx"))

TH_SORTABLE = re.compile(r"<([a-z][A-Za-z0-9]*)\.Th\s+k=")
TH_PLAIN = re.compile(r'<th[^>]*>\{t\("([^"]+)"\)\}</th>')

#: Headings that are actions or layout, not data: nothing to order by.
NOT_DATA = {
    "Open", "Lock", "Confirm", "Remove", "Reposition", "Add", "NERs", "Link",
    "Conf.", "Score", "Set (ratio or text)", "As-Is", "Proposed", "Demand type",
    "Drawings", "Scenarios", "Remember",
    # 3 Sep 2026: a button column, two per-marker columns on a table of at most
    # a handful of rows (the markers of one room), and a free-text column
    # whose contents are sentences — none of them order anything usefully.
    "Details", "Evidence", "Confirmed", "Notes",
}


def tables():
    """Every ``<thead>`` in the pages, with the lines around it."""
    for path in FILES:
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            if "<thead>" not in line:
                continue
            fn = "?"
            for j in range(i, -1, -1):
                m = re.match(r"(?:export )?function (\w+)", lines[j])
                if m:
                    fn = m.group(1)
                    break
            yield (path.name, fn, i + 1,
                   "\n".join(lines[i:i + 14]),      # the header row
                   "\n".join(lines[i:i + 30]))      # header plus the body start


ALL = list(tables())


def test_there_are_tables_to_check():
    """If the scan finds nothing the rest of this file proves nothing.

    The floor moved from 20 to 15 when the As-Is vs Proposed screen, the
    optimiser tables, the register's own exports and the duplicated
    "matches awaiting validation" queue were removed. It is a guard against the
    scan silently matching nothing, not a target for how many tables the
    application should have.
    """
    assert len(ALL) >= 15, f"only {len(ALL)} tables found — has the markup changed?"


@pytest.mark.parametrize("name,fn,line,header,body",
                         ALL, ids=[f"{n}:{f}:{l}" for n, f, l, _, _ in ALL])
def test_every_table_has_clickable_headings(name, fn, line, header, body):
    assert TH_SORTABLE.search(header), (
        f"{name}:{line} in {fn} has no sortable heading. Give the columns "
        f"<x.Th k=\"field\"> from components/useSort, so this table orders like "
        f"every other one.")


@pytest.mark.parametrize("name,fn,line,header,body",
                         ALL, ids=[f"{n}:{f}:{l}" for n, f, l, _, _ in ALL])
def test_a_sortable_header_actually_sorts_its_rows(name, fn, line, header, body):
    """Clickable headings that nothing applies are worse than none: the arrow
    moves, the table does not, and the screen is lying about what it did."""
    var = TH_SORTABLE.search(header)
    assert var, "covered by the test above"
    v = var.group(1)
    assert f"{v}.apply(" in body, (
        f"{name}:{line} in {fn} has <{v}.Th> headings but never calls "
        f"{v}.apply(rows) on the body — clicking would move the arrow and "
        f"leave the rows where they are.")


@pytest.mark.parametrize("name,fn,line,header,body",
                         ALL, ids=[f"{n}:{f}:{l}" for n, f, l, _, _ in ALL])
def test_no_data_column_is_left_unclickable(name, fn, line, header, body):
    """A half-sortable table is its own annoyance: you learn the headings work
    and then meet the one that does not."""
    left = [h for h in TH_PLAIN.findall(header) if h not in NOT_DATA]
    assert not left, (
        f"{name}:{line} in {fn} still has plain data column(s) {left}. Either "
        f"make them sortable or add them to NOT_DATA with a reason.")


def test_the_sort_helper_exists_and_is_the_only_one():
    """One implementation, so there is one place to fix when it is wrong."""
    helper = SRC / "components" / "useSort.tsx"
    assert helper.exists()
    text = helper.read_text(encoding="utf-8")
    # The three rules that are easy to lose in a later edit.
    assert "numeric: true" in text, "numbers inside text must compare as numbers"
    assert "isBlank" in text, "blanks must be handled explicitly, not compared as ''"
    assert '"desc" ? null' in text or "dir === \"asc\" ? \"desc\" : null" in text, \
        "the third click must restore the original order"
