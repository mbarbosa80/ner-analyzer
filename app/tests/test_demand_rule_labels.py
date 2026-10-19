"""The rule column has to mean something to whoever opens the file.

The *Demand detail* sheet had a column headed ``Rule`` carrying "rule A" on
every line. Inside this application that letter is precise — exactly one of four
rules fires per TEAP line, which is what structurally prevents double counting.
On a sheet that leaves the application it says nothing, which is the same defect
as an internal room key sitting in a column headed with a room name.

The letter stays first, so the column still sorts and filters by rule and anyone
already saying "rule A" in a meeting keeps their vocabulary. What follows it is
what makes the row readable on its own.
"""

from __future__ import annotations

import openpyxl
import pytest

from app.domain.demand import RULE_LABEL, rule_label
from app.domain.reports import RULE_MEANING, export_workbook
from app.domain.coverage import CoverageResult
from app.domain.distance import DistanceRules

RULES = DistanceRules()


class _Line:
    def __init__(self, rule):
        self.row_number, self.product_code = 1, "P1"
        self.product_description, self.quantity = "Wired LAN", 60
        self.ports, self.rule = 60, rule
        self.explanation, self.warnings = "explicit port count", []


class _Demand:
    def __init__(self, rule):
        self.space_key, self.space_name = "PRS.001", "Venue Media Centre"
        self.space_code, self.total_ports = "PRS.001", 60.0
        self.warnings, self.lines = [], [_Line(rule)]

    def breakdown(self):
        return ["TOTAL = 60 port(s)"]


def test_every_rule_letter_has_a_meaning():
    """Four rules, four labels, four explanations — none of them left implicit."""
    assert set(RULE_LABEL) == {"A", "B", "C", "D"}
    assert set(RULE_MEANING) == set(RULE_LABEL)


def test_the_label_keeps_the_letter_first():
    """So the column still sorts and filters, and "rule A" stays sayable."""
    for letter, label in RULE_LABEL.items():
        assert label.startswith(letter), label
        assert len(label) > len(letter) + 2, f"{label!r} says no more than the letter"


def test_an_unknown_letter_is_returned_as_it_is():
    """A rule this table has not heard of must not vanish from the sheet."""
    assert rule_label("Z") == "Z"


@pytest.mark.parametrize("rule,expected", [("A", "no"), ("B", "yes"),
                                           ("C", "yes"), ("D", "yes")])
def test_an_assumed_port_count_still_asks_for_a_human(tmp_path, rule, expected):
    """The `Rule` and `Explanation` columns were dropped on 2 Sep 2026 — on the
    event's TEAP every one of 17,495 checkable lines fires rule A, so both columns
    were constant, and two columns of constant on a 17,000-row sheet are noise.

    What they carried on a *different* workbook is not noise: rules B, C and D
    mean the port count was **assumed** from a catalogue or a category default
    rather than read off the TEAP line. An assumed number that looks exactly
    like an explicit one is the one thing this sheet must not produce, so that
    warning folds into `Needs validation`, which is where a reader already looks
    for "does a human still have to check this row".
    """
    from app.domain.coverage import Assignment
    from app.domain.distance import DemandType, Status
    from app.domain.geometry import Area, Point

    area = Area(key="PRS.001", name="Venue Media Centre", page=1,
                label_point=Point(10.0, 10.0, 1))
    served = Assignment(
        space_key="PRS.001", space_name="Venue Media Centre", area=area,
        demand_type=DemandType.GENERAL, ports_required=60.0,
        ner_key="N1", ner_label="NER 1", ner_critical=False,
        evaluation=None, status=Status.SERVED, match_confirmed=True, reasons=[])

    out = str(tmp_path / f"wb_{rule}.xlsx")
    export_workbook(out, coverage=CoverageResult([served], {}, [], []), ners=[],
                    demands=[_Demand(rule)], rules=RULES, project_name="t")
    ws = openpyxl.load_workbook(out)["TEAP and coverage"]
    headers = [c.value for c in ws[1]]
    assert "Rule" not in headers and "Explanation" not in headers
    assert "Demand type" not in headers
    got = ws.cell(row=2, column=headers.index("Needs validation") + 1).value
    assert got == expected, (
        f"rule {rule} on an otherwise clean row should read {expected!r}")


def test_the_summary_sheet_carries_the_legend(tmp_path):
    """Somebody opening this file cold should not have to ask what rule A is."""
    out = str(tmp_path / "wb.xlsx")
    export_workbook(out, coverage=CoverageResult([], {}, [], []), ners=[],
                    demands=[_Demand("A")], rules=RULES, project_name="t")
    ws = openpyxl.load_workbook(out)["Summary"]
    text = "\n".join(f"{r[0].value} {r[1].value}" for r in ws.iter_rows(min_row=1)
                     if r[0].value)
    assert "Port demand rules" in text
    assert "prevents double counting" in text
    for letter in RULE_LABEL:
        assert f"Rule {letter}" in text
