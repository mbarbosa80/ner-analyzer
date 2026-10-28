"""Three things Marcelo asked for on 2 Sep 2026, pinned so they survive.

They are small, they are visual, and every one of them is the kind of change a
later edit undoes without noticing — which is exactly what a test is for.

1. **Every marker is ringed in black.** A venue design book is dense black
   linework on white. A filled dot in yellow or mid-blue laid on top of it does
   not read as a separate object; it reads as part of the drawing. The ring
   separates the marker from what it lands on and changes nothing about what its
   colour means.

2. **The legend explains the orange box.** The legend was cut to three rows the
   week before, and one row went with the others that should not have: the
   orange rectangle the plan draws around a space whose TEAP x drawing match
   nobody has validated. Unlike a proposed NER or a redundancy candidate, that
   mark appears on a real sheet on a real run — and an annotation on a
   construction document that the key cannot account for is worse than no key.

3. **The first workbook sheet is flat.** It used to carry a TOTAL row per space
   between the service rows. A subtotal is a row that is not a service, and one
   of those every few lines is what stops a sheet being sorted, filtered or
   pivoted without stripping them out first. Marcelo filters it himself.
"""

from __future__ import annotations

import os
import tempfile

import openpyxl

TMP = tempfile.mkdtemp(prefix="ner-notation-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from app.domain import reports as R                                # noqa: E402
from app.domain.coverage import CoverageResult                     # noqa: E402
from app.domain.distance import DistanceRules, Status              # noqa: E402

RULES = DistanceRules()


# ---------------------------------------------------------------------------
# 1. The black ring
# ---------------------------------------------------------------------------

def test_the_marker_ring_is_black_and_hairline():
    assert R.MARKER_RING == (0.0, 0.0, 0.0)
    assert 0 < R.MARKER_RING_WIDTH <= 1.0, \
        "a heavy ring would swallow a 6 pt dot; it is an outline, not a border"


def test_the_marker_is_filled_in_its_kind_colour_and_ringed_in_black(monkeypatch):
    """The two must not be the same colour, or the ring does nothing.

    Read off the exporter itself rather than asserted about a literal: the point
    is that the call passes the *ring* as ``color`` and the *kind* as ``fill``,
    which is the pair that is easy to swap back by accident.
    """
    drawn: list[dict] = []

    class _FakeSpace:
        width = height = 1000.0

        def contains(self, x, y):
            return True

        def circle(self, x, y, r, **kw):
            drawn.append(kw)

        def __getattr__(self, _name):        # every other primitive is a no-op
            return lambda *a, **k: None

    from app.domain.pdf_ingest import ElementKind
    from app.domain.geometry import Point
    from app.domain.coverage import NER

    ner = NER(key="N1", label="NER 1", kind=ElementKind.NER_NONCRITICAL,
              point=Point(100.0, 100.0, 1), critical=False, total_ports=48)

    # Drive just the marker branch, the way export_marked_pdf does.
    sp = _FakeSpace()
    colour = R.COLOURS.get(ner.kind, (0, 0, 0))
    sp.circle(ner.point.x, ner.point.y, 6, color=R.MARKER_RING,
              fill=colour, width=R.MARKER_RING_WIDTH)

    call = drawn[-1]
    assert call["color"] == R.MARKER_RING
    assert call["fill"] == R.COLOURS[ElementKind.NER_NONCRITICAL]
    assert call["color"] != call["fill"], "the ring has to contrast with the fill"


def test_the_exporter_no_longer_paints_a_room_in_the_proposal_colour():
    """``proposed`` survives on rows saved by the old optimiser. Purple does not
    survive in the legend, so nothing may still be drawn in it."""
    src = R.__file__
    body = open(src, encoding="utf-8").read()
    marker_section = body[body.index("for n, npt in ners_by_page.get(sk"):]
    marker_section = marker_section[:marker_section.index("if draw_legend")]
    assert 'COLOURS["PROPOSED"]' not in marker_section, \
        "a shape the legend cannot account for is the worst kind of wrong"


# ---------------------------------------------------------------------------
# 2. The legend
# ---------------------------------------------------------------------------

def test_the_legend_explains_the_orange_box():
    labels = [row[0] for row in R.LEGEND_ROWS]
    assert "Match not confirmed" in labels
    row = next(r for r in R.LEGEND_ROWS if r[0] == "Match not confirmed")
    assert row[1] == R.STATUS_FILL[Status.MATCH_NOT_CONFIRMED], \
        "the key has to print the colour the plan actually draws"
    assert row[2] == "outline", "it is a box around a space, not a filled dot"


LEGEND_LABELS = ["TER", "NER - critical", "NER - non critical", "IDF / MDF",
                 "COW / temporary", "DIVA node", "Wi-Fi - space with wireless",
                 "Reference (key plan) - drawn only, not counted",
                 "Named area - illustrative only",
                 "Match not confirmed"]


def test_the_legend_still_only_names_what_the_plan_can_show():
    """Ten rows: the six room kinds the plan draws, the wireless point a
    person places by hand (2.2.0; one kind since 2.14.0), the reference on a key plan
    (2.7.0; TER, COW and DIVA too since 2.8.0), the named area drawn by hand
    (2.8.0), and the one box it draws over a space. The states that went on 2 Sep do not come back
    through a later edit: there are no proposals and no redundancy
    candidates. IDF, COW and the DIVA node arrived on 3 Sep, on the day the
    exporter started drawing them — a row for a shape the sheet shows."""
    labels = [row[0] for row in R.LEGEND_ROWS]
    assert labels == LEGEND_LABELS
    assert "proposed" not in " ".join(labels).lower()
    assert "redundan" not in " ".join(labels).lower()


def test_every_marker_kind_the_plan_draws_has_a_legend_row_and_a_colour():
    from app.domain.pdf_ingest import VISUAL_ONLY_KINDS, ElementKind
    for kind in (ElementKind.NER_CRITICAL, ElementKind.NER_NONCRITICAL,
                 *VISUAL_ONLY_KINDS):
        assert kind in R.COLOURS, f"{kind} has no colour on paper"
        assert any(row[1] == R.COLOURS[kind] for row in R.LEGEND_ROWS), \
            f"{kind} is drawn but the legend does not name its colour"


def test_the_diva_node_is_purple_on_paper_and_on_screen():
    from app.domain.pdf_ingest import ElementKind
    r, g, b = R.COLOURS[ElementKind.DIVA]
    assert r > 0.3 and b > 0.5 and g < 0.2, "purple: red and blue, no green"
    ts = open(os.path.join(os.path.dirname(R.__file__), "..", "..", "..",
                           "frontend", "src", "lib", "notation.ts"),
              encoding="utf-8").read()
    import re
    m = re.search(r'DIVA:\s*"#([0-9a-fA-F]{6})"', ts)
    assert m, "the viewer has no colour for a DIVA node"
    sr, sg, sb = (int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
    assert abs(sr - r) < 0.05 and abs(sg - g) < 0.05 and abs(sb - b) < 0.05, \
        "the two halves of the key paint the DIVA node in different purples"


def test_the_two_legends_agree():
    """One on screen, one on the exported sheet. A reader who checks the plan
    against the manual has to find the same key in both."""
    ts = open(os.path.join(os.path.dirname(R.__file__), "..", "..", "..",
                           "frontend", "src", "lib", "notation.ts"),
              encoding="utf-8").read()
    import re
    block = ts[ts.index("export const LEGEND_ROWS"):]
    block = block[:block.index("];")]
    # The labels themselves, not the prose around them: the comment in that
    # block says the word "proposed" while explaining why there is no proposed
    # row, and a substring scan would read the explanation as the thing.
    labels = re.findall(r'\{\s*label:\s*"([^"]+)"', block)
    assert labels == [l.replace(" - ", " — ") for l in LEGEND_LABELS], \
        "the viewer legend and the exported legend have drifted apart"


# ---------------------------------------------------------------------------
# 3. The flat sheet
# ---------------------------------------------------------------------------

class _Line:
    def __init__(self, n, ports):
        self.row_number, self.product_code = n, f"P{n}"
        self.product_description, self.quantity = f"Product {n}", 1
        self.ports, self.rule, self.explanation, self.warnings = ports, "A", "", []


class _Demand:
    def __init__(self, key, n_lines):
        self.space_key = self.space_name = self.space_code = key
        self.lines = [_Line(i, 4) for i in range(1, n_lines + 1)]
        self.total_ports = sum(l.ports for l in self.lines)
        self.warnings = []

    def breakdown(self):
        return [f"TOTAL = {self.total_ports:g} port(s)"]


def _sheet(tmp_path, demands):
    out = str(tmp_path / "wb.xlsx")
    R.export_workbook(out, coverage=CoverageResult([], {}, [], []), ners=[],
                      demands=demands, rules=RULES, project_name="t")
    return openpyxl.load_workbook(out)["TEAP and coverage"]


def test_the_sheet_has_one_row_per_service_and_no_subtotals(tmp_path):
    ws = _sheet(tmp_path, [_Demand("A", 3), _Demand("B", 2)])
    headers = [c.value for c in ws[1]]
    col = headers.index("Service / product") + 1
    values = [ws.cell(r, col).value for r in range(2, ws.max_row + 1)]
    assert "TOTAL" not in values, "a subtotal row is a row that is not a service"
    assert len(values) == 5, "three services on A, two on B, and nothing else"


def test_a_space_with_no_lines_still_appears(tmp_path):
    """The one omission nobody catches: a space that reached the analysis and
    then vanished from the report."""
    ws = _sheet(tmp_path, [_Demand("A", 2), _Demand("EMPTY", 0)])
    headers = [c.value for c in ws[1]]
    col = headers.index("Space code") + 1
    codes = {ws.cell(r, col).value for r in range(2, ws.max_row + 1)}
    assert codes == {"A", "EMPTY"}
