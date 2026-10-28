"""2.9.0 — the "TEAP by NER" sheet: the flat TEAP sheet summed NER → space →
product, the way Marcelo pivoted it by hand on 24 Sep 2026.

What is held here, because it is what his hand-made pivot got wrong:

* every NER total equals "Ports assigned" on "NERs and ports" — only TEAP
  lines are listed (4.0.0: an access point is not a TEAP product), so the two
  sheets agree;
* the lines with no NER are one named group, last, never "(blank)";
* lines that count 0 ports are left out and their number is stated;
* totals are SUBTOTAL formulas over the right ranges, the grand total sits
  outside the filter, and the rows carry outline levels 2 / 1 / 0.
"""

from __future__ import annotations

import re

import openpyxl
import pytest

from tests.test_wireless_tie_250 import (DWISA, _analyse, _ap, _line, _match,  # noqa: F401
                                         _ner, _project, _room, _teap, client)
from app.domain.reports import BY_NER_HEADERS, PENDING_NER_LABEL


def _workbook(client, pid):
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    return openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])


def _build(client):
    pid = _project("by-ner")
    _room(pid, "OFF.050", "Office", 100, 100)
    _room(pid, "OFF.060", "Office Two", 400, 100)
    _teap(pid, "OFF.050", "Office", [
        _line("Laptop", 4, 4, "LAP", 1),
        _line(DWISA, 1, 1, "DWISA", 2),
        _line("Monitor", 2, 0, "MON", 3),
    ])
    _teap(pid, "OFF.060", "Office Two", [_line("Printer", 1, 1, "PRN", 4)])
    _teap(pid, "GHO.099", "Nowhere Room", [_line("Laptop", 3, 3, "LAP", 5)])
    _ner(pid, "NER.10", 100, 120)
    _ner(pid, "NER.2", 400, 120)
    _match(client, pid)
    _ap(client, pid, 100, 105)
    _ap(client, pid, 110, 105)
    _analyse(pid)
    return _workbook(client, pid)


@pytest.fixture(scope="module")
def wb(client):
    return _build(client)


def test_teap_by_ner_sits_after_the_flat_sheet_and_adds_up(wb):
    names = wb.sheetnames
    assert names[0] == "TEAP by NER"           # 4.0.0: first, red
    ws = wb["TEAP by NER"]
    assert [c.value for c in ws[1]] == BY_NER_HEADERS

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    details = [r for r in rows if isinstance(r[6], (int, float))]
    ner_totals = [r for r in rows if isinstance(r[5], str) and r[5] == f"{r[0]} total"]

    # the NER groups, in natural order, pending last and named
    assert [r[0] for r in ner_totals] == ["NER.2", "NER.10", PENDING_NER_LABEL]

    # each NER's lines add up to "Ports assigned" on the NERs sheet
    assigned = {r[0]: r[7] for r in wb["NERs and ports"].iter_rows(min_row=2, values_only=True)
                if r[0] and r[0] != "TOTAL"}
    for ner in ("NER.10", "NER.2"):
        s = sum(r[6] for r in details if r[0] == ner)
        assert s == assigned[ner], (ner, s, assigned[ner])

    # 4.0.0: an access point is not a TEAP product — none is listed; the
    # space's DWISA line is, under the NER of its space, with its one port
    under_10 = [r for r in details if r[0] == "NER.10"]
    assert not any(r[4] == "AP" or r[3] == "Wireless points drawn" for r in details)
    assert [(r[4], r[6]) for r in under_10 if r[5] == DWISA] == [("DWISA", 1)]

    # the pending group, and a zero-port line left out with a note
    assert any(r[0] == PENDING_NER_LABEL and r[2] == "GHO.099" and r[6] == 3 for r in details)
    assert not any(r[4] == "MON" for r in details)
    note = [r[0] for r in rows if isinstance(r[0], str) and "count 0 ports" in r[0]]
    assert note and note[0].startswith("1 TEAP line(s)"), note   # MON only

    # grand total = every TEAP port, the DWISA line included, nothing else
    grand = next(r for r in rows if r[0] == "Grand total")
    assert re.fullmatch(r"=SUBTOTAL\(9,G2:G\d+\)", grand[6])
    assert sum(r[6] for r in details) == 4 + 1 + 1 + 3


def test_teap_by_ner_totals_are_subtotals_over_their_own_rows(wb):
    ws = wb["TEAP by NER"]
    last = int(ws.auto_filter.ref.split(":G")[1])
    assert ws.auto_filter.ref == f"A1:G{last}"
    for r in range(2, last + 1):
        label, value = ws.cell(r, 6).value, ws.cell(r, 7).value
        level = ws.row_dimensions[r].outline_level
        if isinstance(value, str):
            m = re.fullmatch(r"=SUBTOTAL\(9,G(\d+):G(\d+)\)", value)
            assert m, value
            lo, hi = int(m[1]), int(m[2])
            assert hi == r - 1, (r, value)
            if label == f"{ws.cell(r, 1).value} total":          # NER total
                assert level == 0
                assert all(ws.cell(k, 1).value == ws.cell(r, 1).value for k in range(lo, hi + 1))
            else:                                                 # space total
                assert level == 1
                assert all(ws.row_dimensions[k].outline_level == 2 for k in range(lo, hi + 1))
        else:
            assert level == 2 and isinstance(value, (int, float)), (r, value)
    assert ws.cell(last + 2, 1).value == "Grand total"
    assert ws.sheet_properties.outlinePr.summaryBelow is True
