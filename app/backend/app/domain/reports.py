"""Auditable exports: marked-up PDF overlays and calculation workbooks.

Every exported row carries its provenance — source file and page, the scale used,
the coordinates, the rule applied, the distance, the method, the confidence and
whether a human still has to validate it — because a coverage number without its
assumptions is not reviewable.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable, Optional, Sequence

import openpyxl
import pymupdf
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .coverage import CoverageResult, NER
from .geometry import Point
from .sheetnames import page_label, pages_label
from .demand import RULE_LABEL

#: One line per rule for the Summary sheet, so the workbook explains itself.
RULE_MEANING = {
    "A": "the TEAP line already carries a port count — used verbatim, and "
         "reconciled against the catalogue (see Warnings)",
    "B": "no port count on the line, but the product is in the catalogue — "
         "quantity x catalogue ports per unit",
    "C": "not in the catalogue either — quantity x the category default. "
         "An assumption, and flagged as one",
    "D": "nothing usable — the fallback is applied and the line is flagged "
         "for review",
}
from .distance import (GROUP_LABEL, PENDING_NO_ROOM, PENDING_NOT_ANALYSED,
                       STATUS_LABEL as STATUS_WORDS, DistanceRules, Group, Status,
                       group_of)
from .matching import normalise_code
from .pdf_ingest import NER_REFERENCE_KINDS, REFERENCE_KINDS, ElementKind
from .units import Scale, format_length
from ..version import APP_NAME, __version__

#: A venue code already in front of a NER name: ``VHH_NERc_01.1``.
VENUE_PREFIX_RX = re.compile(r"^\s*[A-Z0-9]{2,5}_(?=NER)", re.IGNORECASE)


def ner_full_name(venue_code: Optional[str], name: str) -> str:
    """The NER name with the project's venue code in front — ``VHH_NERc_01.1`` —
    the way the event's naming sheet v2.0 writes it (``VVV_NERc_02.1``; on a cluster
    each venue uses its own code). Workbook only (Marcelo, 9 Oct 2026: "leva o
    nome completo para o excel"): the register and the drawing keep the short
    name. A name that already carries a code, or a project with no venue code,
    is left as it is."""
    name = (name or "").strip()
    code = (venue_code or "").strip().upper()
    if not code or not name or VENUE_PREFIX_RX.match(name):
        return name
    return f"{code}_{name}"

#: Stamped on every export so a file found on a desk months later says which
#: build produced it. Reads "NER Spatial Coverage Analyzer 2.0.0".
PRODUCED_BY = f"{APP_NAME} {__version__}"

DISCLAIMER = (
    "This tool supports the design process. It does not replace engineering approval, "
    "a site survey, cable route validation or physical inspection."
)

# RGB 0-1 tuples matching the documented notation — the same values as
# ``KIND_COLOUR`` in ``frontend/src/lib/notation.ts``, which is the on-screen
# half of the same key.
COLOURS = {
    ElementKind.TER: (0.0, 0.0, 0.80),
    ElementKind.NER_CRITICAL: (0.80, 0.0, 0.0),
    ElementKind.NER_NONCRITICAL: (0.90, 0.72, 0.0),
    ElementKind.IDF: (0.48, 0.48, 0.48),
    ElementKind.COW: (0.55, 0.35, 0.0),
    # Purple, as Marcelo asked on 3 Sep 2026. The proposal colour used to be
    # this shade; there are no proposals any more, so nothing else claims it.
    ElementKind.DIVA: (0.50, 0.0, 0.63),
    # Sky blue, and a shape of its own — the fan of a Wi-Fi sign
    # (``_draw_wifi``) — because a wireless point is demand a person drew, not
    # a room. Same value as ``KIND_COLOUR.WIRELESS`` on screen.
    ElementKind.WIRELESS: (0.0, 0.59, 0.78),
    # A NER reference on a key plan (2.7.0): the colour of the NER it stands
    # for; what tells it apart is the dashed ring, not the fill.
    ElementKind.NER_CRITICAL_REF: (0.80, 0.0, 0.0),
    ElementKind.NER_NONCRITICAL_REF: (0.90, 0.72, 0.0),
    # A TER, COW or DIVA reference on a key plan (2.8.0): the colour of the
    # room it stands for, the dashed ring telling it apart.
    ElementKind.TER_REF: (0.0, 0.0, 0.80),
    ElementKind.COW_REF: (0.55, 0.35, 0.0),
    ElementKind.DIVA_REF: (0.50, 0.0, 0.63),
    "PROPOSED": (0.50, 0.0, 0.60),
    "REMOVAL": (0.45, 0.45, 0.45),
}

#: A named area a person drew on the sheet to point something out — "BTOC",
#: "TER", a compound — illustrative only (2.8.0). One colour for all of them,
#: chosen to sit apart from every status fill and every marker: slate blue,
#: filled faintly, outlined, named on a tag.
AREA_COLOUR = (0.24, 0.35, 0.50)
AREA_FILL_OPACITY = 0.16

# The hairline ring every marker is drawn with. A venue design book is dense
# black linework on white; a filled dot in yellow or mid-blue laid on top of it
# reads as part of the drawing rather than as something added to it. The ring
# separates the marker from what it lands on without touching what the colour
# means, which is the only job the colour has.
MARKER_RING = (0.0, 0.0, 0.0)
MARKER_RING_WIDTH = 0.6

# The size of a room marker on the exported sheet. Doubled on 10 Sep 2026 at
# Marcelo's request — at 6 pt on an ANSI D sheet full of 4 pt room codes the
# dots "estão muito pequenas e difíceis de serem vistas" — and the name beside
# each one went from 7 pt regular to 9 pt bold. A marked-up plan is read on a
# screen at fit-to-page and on paper at arm's length; at either distance the
# marker has to be the first thing the eye lands on, because it is the one
# thing on the sheet the drawing office did not put there.
MARKER_RADIUS = 12.0
MARKER_LABEL_SIZE = 9.0
#: A reference's name (*NER, *TER, *COW, *DIVA) — two points larger, to be read
#: from across a key plan (Marcelo, 14 Oct 2026); the viewer does the same.
REFERENCE_LABEL_SIZE = MARKER_LABEL_SIZE + 2.0
MARKER_LABEL_FONT = "hebo"          # Helvetica-Bold, one of PyMuPDF's base-14 names
#: A Wi-Fi point on the exported PDF (4.4.0): the sign a little larger and its
#: name at the NERs' size, in a darker blue than the sign on a white tag —
#: the 6.5 pt cyan name straight on the linework was reported unreadable.
WIFI_SIGN_SIZE = 16.0
WIFI_LABEL_SIZE = MARKER_LABEL_SIZE
WIFI_LABEL_INK = (0.0, 0.33, 0.50)

# The colour a marker's *name* is written in, which is not always the colour of
# its dot. Non-critical yellow is a good fill and a bad ink: #e6b800 text on the
# white of a drawing sheet is close to unreadable, and the label is the half of
# the marker that carries the information. The dot keeps the notation colour;
# the text gets a shade dark enough to read at 7 pt.
LABEL_COLOURS = {
    **COLOURS,
    ElementKind.NER_NONCRITICAL: (0.48, 0.36, 0.0),
    ElementKind.NER_NONCRITICAL_REF: (0.48, 0.36, 0.0),
}

#: The ring of a NER reference: dashed, so a reader sees at once that the dot
#: is a pointer to a room drawn elsewhere and not the room itself.
REFERENCE_RING_DASHES = "[2 2] 0"
STATUS_FILL = {
    Status.SERVED: (0.20, 0.65, 0.25),
    Status.NEAR_LIMIT: (0.95, 0.55, 0.10),
    Status.OUT_OF_LIMIT: (0.85, 0.10, 0.10),
    Status.INSUFFICIENT_CAPACITY: (0.85, 0.10, 0.10),
    Status.MATCH_NOT_CONFIRMED: (0.95, 0.55, 0.10),
    Status.SCALE_NOT_CONFIRMED: (0.55, 0.55, 0.55),
    Status.ROUTE_NOT_VALIDATED: (0.55, 0.55, 0.55),
    Status.NOT_ANALYSABLE: (0.35, 0.35, 0.35),
    # Served from another level, distance not measured: a room was chosen and
    # its ports are counted, but no figure was checked. Neither green nor red
    # would be honest; the same grey as the other "not measured" states.
    Status.CROSS_LEVEL_NOT_MEASURED: (0.55, 0.55, 0.55),
    # No room on the drawing, NER chosen by hand: nothing to paint — the
    # space has no position — but the table needs a colour for its rows.
    Status.ASSIGNED_NOT_PLACED: (0.55, 0.55, 0.55),
}

# Seven rows. The exported plan's legend matches the one on screen, and both
# list exactly what a marker on a sheet can be — the six kinds the plan draws —
# plus the one annotation it draws over a space. Every other row the legend
# once carried described a state this application no longer produces
# (proposals, redundancy candidates) or a fill whose meaning is written in
# words in the Status column of the workbook.
#
# IDF, COW and the DIVA node were added on 3 Sep 2026, when the exporter
# started drawing them. Before that the legend said "TER" and the sheet showed
# no TER at all: the exporter drew only the register, and the register holds
# NERs. A key that names a shape the reader cannot find is noise; a shape the
# key does not name is worse. Both are fixed by drawing every marker kind and
# listing every marker kind, in the same order the viewer lists them.
LEGEND_ROWS = [
    ("TER", COLOURS[ElementKind.TER], "circle"),
    ("NER - critical", COLOURS[ElementKind.NER_CRITICAL], "circle"),
    ("NER - non critical", COLOURS[ElementKind.NER_NONCRITICAL], "circle"),
    ("IDF / MDF", COLOURS[ElementKind.IDF], "circle"),
    ("COW / temporary", COLOURS[ElementKind.COW], "circle"),
    ("DIVA node", COLOURS[ElementKind.DIVA], "circle"),
    ("Wi-Fi - space with wireless", COLOURS[ElementKind.WIRELESS], "wifi"),
    # A reference on a key plan (2.7.0, widened in 2.8.0 to TER, COW and DIVA):
    # a dot in the room's colour with a dashed ring. Drawn only — it points at
    # a room drawn on another sheet — and counted nowhere; a NER reference
    # also gets the reach circles to this sheet's scale.
    ("Reference (key plan) - drawn only, not counted",
     COLOURS[ElementKind.NER_CRITICAL_REF], "reference"),
    # A named area drawn by hand (2.8.0): illustrative, nothing is measured
    # or counted from it.
    ("Named area - illustrative only", AREA_COLOUR, "area"),
    # The orange box drawn around a space whose TEAP x drawing match nobody has
    # validated. It went out with the other eight rows and came back on its own:
    # unlike a proposed NER or a redundancy candidate, this mark is drawn on a
    # real sheet on a real run, and an annotation on a construction document
    # that the key does not explain is worse than no key at all.
    ("Match not confirmed", STATUS_FILL[Status.MATCH_NOT_CONFIRMED], "outline"),
]


def user_unit(page: "pymupdf.Page") -> float:
    """The page's ``/UserUnit`` (1.0 when it has none), 4.8.0."""
    try:
        kind, val = page.parent.xref_get_key(page.xref, "UserUnit")
        u = float(val) if kind in ("float", "int") else 1.0
        return u if u > 0 else 1.0
    except Exception:  # noqa: BLE001 — a malformed entry reads as no unit
        return 1.0


class PageSpace:
    """Writes into a page using *display* coordinates.

    Everything this application stores — space label points, marker positions,
    polygons — is in display coordinates: the page as a reader sees it, with the
    ``/Rotate`` entry already applied. That is deliberate. It is what PDF.js
    reports to the viewer, and the extractor was corrected to produce the same
    thing so that the two agree.

    PyMuPDF's *writing* methods do not work in that space. ``insert_text`` and
    ``draw_circle`` address the unrotated MediaBox, so on a page carrying
    ``/Rotate 90`` — every page of the venue books seen so far — a marker stored
    at x=2040 was written into a box only 1584 wide and left the sheet
    altogether, dragging its leader line to an area that had gone with it. That
    is the "NERs out of place pointing at areas outside the drawing" defect, and
    it lived only in the export: the viewer was already right.

    Every write in the exporter goes through this class, so the correction
    cannot be forgotten at one call site and applied at the others.

    **One shape, one commit.** Each ``page.draw_*`` call is its own ``Shape``,
    and committing one appends to — and re-parses — the page's content stream.
    On a venue book that stream is enormous: 35 MB over 75 pages is about
    475 KB of vector CAD per page, so a single draw call costs a tenth of a
    second and the legend alone is twenty-two of them. Measured on the VCC
    book, page by page:

        separate calls (as it was)   2.03 s/page   →  75 pages ≈ 152 s
        one Shape per page           0.10 s/page   →  75 pages ≈   7 s

    Twenty times faster for the same picture. That mattered for more than
    patience: the export ran inside the request, and a single-worker server
    blocked for two and a half minutes is indistinguishable from a dead one.
    So everything is accumulated into one ``Shape`` and committed once, when
    the page is done.
    """

    def __init__(self, page: pymupdf.Page):
        self.page = page
        self._m = page.derotation_matrix
        self._shape = page.new_shape()
        # Text written into the unrotated box appears turned once the reader
        # applies /Rotate. Turning it by the page's own rotation cancels that
        # out, so labels read left to right on the sheet as displayed.
        self.text_rotate = int(page.rotation) % 360
        self._uu = user_unit(page)

    @property
    def width(self) -> float:
        return self.page.rect.width

    @property
    def height(self) -> float:
        return self.page.rect.height

    def contains(self, x: float, y: float) -> bool:
        return 0 <= x <= self.width and 0 <= y <= self.height

    def pt(self, x: float, y: float) -> pymupdf.Point:
        return pymupdf.Point(x, y) * self._m

    def rect(self, x0: float, y0: float, x1: float, y1: float) -> pymupdf.Rect:
        return pymupdf.Rect(x0, y0, x1, y1) * self._m

    # -- drawing, all in display coordinates -------------------------------
    #
    # ``Shape.finish`` takes the styling that ``page.draw_*`` takes as keywords,
    # so each of these is "add the geometry, then close it off with its style".

    def circle(self, x: float, y: float, r: float, **kw) -> None:
        self._shape.draw_circle(self.pt(x, y), r)
        self._shape.finish(**kw)

    def line(self, a: tuple[float, float], b: tuple[float, float], **kw) -> None:
        self._shape.draw_line(self.pt(*a), self.pt(*b))
        self._shape.finish(**kw)

    def box(self, x0: float, y0: float, x1: float, y1: float, **kw) -> None:
        self._shape.draw_rect(self.rect(x0, y0, x1, y1))
        self._shape.finish(**kw)

    def polyline(self, points, **kw) -> None:
        self._shape.draw_polyline([self.pt(x, y) for x, y in points])
        self._shape.finish(**kw)

    def text(self, x: float, y: float, s: str, **kw) -> None:
        p = self.pt(x, y)
        if self._uu != 1.0:
            # A sheet larger than 14,400 pt (the PDF limit) carries /UserUnit
            # (4.8.0): the VBB 700 series, 17,144 x 11,092 pt with UserUnit
            # 1.19. PyMuPDF scales the position of what it draws by it but
            # not the position of the text it inserts, so every label of the
            # app landed off the sheet — empty Wi-Fi tags, no footnote. The
            # position is divided by the unit here, the way the drawing is.
            p = pymupdf.Point(p.x / self._uu, p.y / self._uu)
        self._shape.insert_text(p, s, rotate=self.text_rotate, **kw)

    def commit(self) -> None:
        """Write everything drawn on this page, in one pass."""
        self._shape.commit()


def _draw_wifi(space: PageSpace, x: float, y: float, size: float, colour,
               *, mast: bool = False) -> None:
    """The wireless sign: a dot with two arcs fanning out above it.

    ``(x, y)`` is the dot — the point itself, where the person clicked — and
    ``size`` the radius of the outer arc. Drawn from lines only, so it survives
    every PDF viewer and prints the same as it shows. (``mast`` drew the pole
    of the outdoor point until 2.14.0; one kind of AP now, so it is ignored.)
    """
    import math
    space.circle(x, y, max(1.2, size * 0.2), color=MARKER_RING, fill=colour,
                 width=MARKER_RING_WIDTH)
    for r in (size * 0.55, size):
        pts = [(x + r * math.cos(math.radians(deg)), y + r * math.sin(math.radians(deg)))
               for deg in range(-140, -39, 10)]
        space.polyline(pts, color=colour, width=max(1.0, size * 0.16), closePath=False)


def _draw_legend(space: PageSpace, scenario: str, rules: DistanceRules,
                 scale: Optional[Scale], *, coverage_available: bool = True) -> None:
    w = 320.0
    h = 26.0 + len(LEGEND_ROWS) * 15.0 + 54.0 + 9.0 + (0.0 if coverage_available else 22.0)
    x0, y0 = 18.0, 18.0
    space.box(x0, y0, x0 + w, y0 + h,
              color=(0.15, 0.15, 0.15), fill=(1, 1, 1), width=0.9, fill_opacity=0.92)
    space.text(x0 + 10, y0 + 18, f"NER COVERAGE — {scenario.upper()}",
               fontsize=10, color=(0, 0, 0))
    y = y0 + 34
    for label, colour, style in LEGEND_ROWS:
        if style == "fill":
            space.box(x0 + 10, y - 7, x0 + 24, y + 3,
                      color=colour, fill=colour, fill_opacity=0.35, width=0.5)
        elif style == "dashed":
            space.circle(x0 + 17, y - 2, 5, color=colour, width=1.1, dashes="[2 2] 0")
        elif style == "crossed":
            space.circle(x0 + 17, y - 2, 5, color=colour, width=0.9)
            space.line((x0 + 12, y - 7), (x0 + 22, y + 3), color=colour, width=0.9)
        elif style == "outline":
            space.box(x0 + 10, y - 7, x0 + 24, y + 3, color=colour, width=1.2)
        elif style == "reference":
            space.circle(x0 + 17, y - 2, 5, color=MARKER_RING, fill=colour,
                         width=MARKER_RING_WIDTH, dashes=REFERENCE_RING_DASHES)
        elif style == "area":
            space.box(x0 + 10, y - 7, x0 + 24, y + 3, color=colour, fill=colour,
                      fill_opacity=AREA_FILL_OPACITY, width=0.9)
        elif style == "wifi":
            _draw_wifi(space, x0 + 17, y + 2, 9.0, colour)
        elif style == "wifi-mast":
            _draw_wifi(space, x0 + 17, y + 2, 9.0, colour, mast=True)
        else:
            space.circle(x0 + 17, y - 2, 5, color=MARKER_RING, fill=colour,
                         width=MARKER_RING_WIDTH)
        space.text(x0 + 32, y, label, fontsize=7.5, color=(0.1, 0.1, 0.1))
        y += 15

    y += 6
    space.text(x0 + 10, y, f"Limits: {rules.general_limit_m:g} m general / "
                           f"{rules.photographer_limit_m:g} m photographers",
               fontsize=7, color=(0.1, 0.1, 0.1))
    y += 11
    space.text(x0 + 10, y, f"Routing slack factor: {rules.routing_slack_factor:g}x"
                           f"   Scale: {scale.label if scale else 'not confirmed'}",
               fontsize=7, color=(0.1, 0.1, 0.1))
    y += 11
    if not coverage_available:
        # Silence here would be read as "everything is covered". The sheet has
        # to say that no coverage was computed, or the absence of red areas
        # becomes an accidental claim.
        for line in _wrap("No coverage analysis on this sheet: the spaces have "
                          "not been matched to the drawing yet. The rooms shown "
                          "are positions only — nothing here says what they "
                          "serve or whether they reach it.", 72):
            space.text(x0 + 10, y, line, fontsize=6.6, color=(0.55, 0.35, 0.0))
            y += 9
        y += 2
    for line in _wrap(DISCLAIMER, 72):
        space.text(x0 + 10, y, line, fontsize=6.2, color=(0.45, 0.1, 0.1))
        y += 8
    space.text(x0 + 10, y + 1, PRODUCED_BY, fontsize=5.6, color=(0.4, 0.4, 0.4))


#: The line a sheet without the legend box carries when the box is on the
#: first page of the file (4.3.0).
LEGEND_ON_FIRST_PAGE = "Legend: see the first page of this file."


def _footnote_lines(scenario: str, rules: DistanceRules, scale: Optional[Scale],
                    coverage_available: bool, *, legend_elsewhere: bool = False
                    ) -> list[tuple[str, tuple]]:
    """What has to stay on the sheet when the legend box is not on it."""
    out: list[tuple[str, tuple]] = []
    if legend_elsewhere:
        out.append((LEGEND_ON_FIRST_PAGE, (0.1, 0.1, 0.1)))
    out += [(
        f"NER coverage — {scenario} · limits {rules.general_limit_m:g} m general / "
        f"{rules.photographer_limit_m:g} m photographers · slack "
        f"{rules.routing_slack_factor:g}x · scale "
        f"{scale.label if scale else 'not confirmed'} · {PRODUCED_BY}",
        (0.1, 0.1, 0.1))]
    if not coverage_available:
        out.append(("No coverage analysis on this sheet — the spaces have not been "
                    "matched to the drawing yet.", (0.55, 0.35, 0.0)))
    out.append((DISCLAIMER, (0.45, 0.1, 0.1)))
    return out


def _draw_footnote(space: PageSpace, scenario: str, rules: DistanceRules,
                   scale: Optional[Scale], *, coverage_available: bool = True,
                   legend_elsewhere: bool = False) -> None:
    """The legend, reduced to what may not be dropped.

    Turning the legend off is a reasonable thing to want: the box is 320 points
    wide and on a dense sheet it sits over the drawing. But three things on it
    are not decoration.

    The **limits and the scale** are what every distance on the page was
    measured against; a marked sheet without them cannot be checked by the
    person receiving it. The **"no coverage" warning**, when it applies, is the
    difference between "nothing is out of limit" and "nothing was measured".
    And the **disclaimer** is the sentence that keeps this a design aid rather
    than something a reader could mistake for an approved engineering drawing —
    it is the one line whose absence could do real harm, on a document that will
    be forwarded to people who were not in the room.

    So the switch drops the box and the swatches, not the statements. Three
    small lines along the foot of the sheet, out of the way of the plan.
    """
    lines: list[tuple[str, tuple]] = []
    for text, colour in _footnote_lines(scenario, rules, scale, coverage_available,
                                        legend_elsewhere=legend_elsewhere):
        for chunk in _wrap(text, 150):
            lines.append((chunk, colour))
    y = space.height - 8.0 - (len(lines) - 1) * 8.0
    for text, colour in lines:
        space.text(14.0, y, text, fontsize=6.0, color=colour)
        y += 8.0


def _wrap(text: str, width: int) -> list[str]:
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


def strip_pdf_annotations(doc: "pymupdf.Document") -> int:
    """Delete every annotation (and form widget) of an open document — the
    reviewers' markups — leaving the page content untouched. Returns how
    many went. Works on the open document only: the caller decides where
    (and whether) the result is saved."""
    removed = 0
    for page in doc:
        # ``delete_annot`` invalidates the iterator, so the list is taken first.
        for annot in list(page.annots()):
            page.delete_annot(annot)
            removed += 1
        for widget in list(page.widgets()):
            page.delete_widget(widget)
            removed += 1
    return removed


def _point_on(ner: Optional[NER], page: int, near) -> Optional[Point]:
    """Where ``ner`` is drawn on ``page`` (nearest marker to ``near``), or
    ``None`` — the room is not on this sheet."""
    if ner is None:
        return None
    if hasattr(ner, "point_on"):
        return ner.point_on(page, near)
    return ner.point if ner.point.page == page else None


def export_marked_pdf(
    source_pdf: str,
    out_path: str,
    *,
    coverage: CoverageResult,
    ners: Sequence[NER],
    scale_for_page: dict[int, Scale],
    rules: DistanceRules,
    scenario: str = "As-Is",
    draw_radii: bool = True,
    draw_links: bool = True,
    off_page: Optional[list] = None,
    coverage_available: bool = True,
    draw_legend: bool = True,
    legend_page: Optional[int] = 1,
    progress=None,
    areas: Optional[Sequence[dict]] = None,
    strip_annotations: bool = True,
    page_key=None,
    sheet_text=None,
) -> str:
    """Write a copy of the drawing with coverage overlays and a permanent legend.

    ``strip_annotations`` (2.14.0, on by default) takes the reviewers' own
    markups off the copy first — the PDF *annotations* a comments round
    leaves on a book: the red "COW #1" / "NER 14" free-text boxes, the ink
    blobs, sticky notes. They are not part of the drawing (the design team's
    linework is page content, and stays); the export draws the app's own
    markers in their place. Marcelo, 29 Sep 2026: *"limpar aquilo que não é
    de origem do arquivo."* The book on disk is never touched — only the
    copy being written.

    Pass a list as ``off_page`` to collect anything whose stored position falls
    outside its page. Nothing is dropped — it is still drawn, because a marker
    silently missing from an export is worse than one visibly in the wrong
    place — but the caller gets a list it can put in front of a reviewer.

    ``areas`` are the named areas a person drew (2.8.0): dicts with ``page``,
    ``label`` and ``polygon``. Illustrative — filled faintly, outlined, named
    on a tag — and part of no figure.

    ``progress`` is called with ``(fraction, stage)`` once per page and again
    while the file is written, which is the slow part on a large book. It may
    raise to abort, which is how cancellation works.

    ``legend_page`` (4.3.0) is the one page of this file that carries the
    legend box — the first, by default; ``None`` puts it on none (a second
    book appended to a file whose first page already has it). Every other
    page gets the short footnote instead — limits, scale, the disclaimer and
    a line pointing at the legend — so the box no longer sits over the plan
    on every sheet. Asked by a reviewer on 19 Oct 2026: the box covered map
    lines.

    ``page_key`` (4.1.0) turns this file's page number into the sheet key the
    coverage result uses (:mod:`app.sheets`) — left out, the two are the same,
    as in every one-book project. ``sheet_text`` names a sheet on the marked
    page (``p. 6`` by default).
    """
    key_of = page_key or (lambda n: n)
    st = sheet_text or (lambda k: f"p. {k}")
    doc = pymupdf.open(source_pdf)
    try:
        if strip_annotations:
            removed = strip_pdf_annotations(doc)
            if removed and progress is not None:
                progress(0.0, f"{removed} reviewer annotation(s) taken off the copy")
        areas_by_page: dict[int, list[dict]] = {}
        for z in areas or ():
            if len(z.get("polygon") or []) >= 3:
                areas_by_page.setdefault(int(z["page"]), []).append(z)
        by_page: dict[int, list] = {}
        #: page -> [(assignment, the label of that space on *this* page)] for a
        #: space whose distance was measured from another sheet than the one the
        #: TEAP line is tied to. It is drawn there too, with its leader line,
        #: because that is the sheet the serving room is on.
        measured_elsewhere: dict[int, list] = {}
        for a in coverage.assignments:
            by_page.setdefault(a.area.page, []).append(a)
            if a.measured_page:
                occ = next((o for o in (a.area.occurrences or [])
                            if o.page == a.measured_page), None)
                if occ is not None:
                    measured_elsewhere.setdefault(occ.page, []).append((a, occ))
        #: page -> [(room, where this page draws it)]. Every marker of a room
        #: is drawn where it stands on its own sheet (3.0.0) — a room drawn on
        #: three sheets used to be drawn three times at the canonical sheet's
        #: coordinates, on the canonical sheet only.
        ners_by_page: dict[int, list[tuple[NER, Point]]] = {}
        for n in ners:
            for q in getattr(n, "points", None) or [n.point]:
                ners_by_page.setdefault(q.page, []).append((n, q))

        # Named in full on purpose. This was ``n``, which the marker loop further
        # down also uses for the NER it is drawing — so from the first page that
        # carried a marker onwards, the page count *was* a NER and the progress
        # line raised "'>' not supported between instances of 'int' and 'NER'".
        # It only fired with progress attached, which is to say only in the
        # background job, and only past the first page with a marker.
        page_count = doc.page_count
        for page_no in range(1, page_count + 1):
            if progress is not None:
                progress(0.9 * (page_no - 1) / max(page_count, 1),
                         f"marking page {page_no} of {page_count}")
            page = doc[page_no - 1]
            sp = PageSpace(page)
            sk = key_of(page_no)
            scale = scale_for_page.get(sk)

            # Named areas first, under everything else: a faint fill with the
            # name on a tag at its centre. They are the reader's own notes on
            # the sheet ("BTOC", "TER"), not a result.
            for z in areas_by_page.get(sk, []):
                poly = [(float(x), float(y)) for x, y in z["polygon"]]
                sp.polyline(poly + [poly[0]], color=AREA_COLOUR, fill=AREA_COLOUR,
                            fill_opacity=AREA_FILL_OPACITY, width=1.1)
                label = (z.get("label") or "").strip()
                if label:
                    cx = sum(x for x, _ in poly) / len(poly)
                    cy = sum(y for _, y in poly) / len(poly)
                    tw = pymupdf.get_text_length(label, fontname=MARKER_LABEL_FONT,
                                                 fontsize=MARKER_LABEL_SIZE)
                    tx, ty = cx - tw / 2, cy + MARKER_LABEL_SIZE * 0.4
                    sp.box(tx - 3, ty - MARKER_LABEL_SIZE * 0.78 - 2, tx + tw + 3, ty + 3,
                           color=AREA_COLOUR, fill=(1, 1, 1), fill_opacity=0.85, width=0.5)
                    sp.text(tx, ty, label, fontsize=MARKER_LABEL_SIZE,
                            fontname=MARKER_LABEL_FONT, color=AREA_COLOUR)

            if draw_radii and scale is not None:
                for n, npt in ners_by_page.get(sk, []):
                    # A NER, or a reference to one on a key plan: the circles
                    # are what the reference is drawn for. A TER, an IDF, a
                    # COW and a DIVA node get none — and neither do their
                    # references.
                    if not (n.can_serve or n.kind in NER_REFERENCE_KINDS):
                        continue
                    for limit, colour, dash in (
                        (rules.general_limit_m, (0.20, 0.45, 0.85), "[4 3] 0"),
                        (rules.photographer_limit_m, (0.60, 0.20, 0.75), "[2 3] 0"),
                    ):
                        r = scale.to_pdf_units(limit / rules.routing_slack_factor)
                        sp.circle(npt.x, npt.y, r, color=colour,
                                  width=0.7, dashes=dash)

            for a, occ in measured_elsewhere.get(sk, []):
                colour = STATUS_FILL.get(a.status, (0.4, 0.4, 0.4))
                q = occ.representative_point()
                sp.circle(q.x, q.y, 5.0, color=colour, fill=colour,
                          fill_opacity=0.45, width=0.6)
                sp.text(q.x + 7, q.y + 9,
                        f"{a.area.space_code or a.space_name} (TEAP line tied on {st(a.area.page)})",
                        fontsize=5.5, color=colour)
                ner = next((n for n in ners if n.key == a.ner_key), None)
                npt = _point_on(ner, sk, q)
                if draw_links and npt is not None:
                    sp.line((q.x, q.y), (npt.x, npt.y),
                            color=colour, width=0.6, dashes="[1 2] 0")
                    if a.evaluation and a.evaluation.effective_distance_m is not None:
                        sp.text((q.x + npt.x) / 2, (q.y + npt.y) / 2,
                                f"{a.evaluation.effective_distance_m:.0f} m",
                                fontsize=5.5, color=colour)

            for a in by_page.get(sk, []):
                colour = STATUS_FILL.get(a.status, (0.4, 0.4, 0.4))
                p = a.area.representative_point()
                if a.kind == "wireless_point":
                    # Its own sign, in its own colour; the verdict is the ring
                    # under it, in the same status colours as a space.
                    sp.circle(p.x, p.y, 5.0, color=colour, fill=colour,
                              fill_opacity=0.35, width=0.6)
                    wcol = COLOURS[ElementKind.WIRELESS]
                    _draw_wifi(sp, p.x, p.y, WIFI_SIGN_SIZE, wcol)
                    # The name on a white tag under the sign, the way a NER's
                    # name is written (4.4.0). It was 6.5 pt in the sign's own
                    # cyan straight on the linework, and the team found it
                    # small and unreadable on the exported PDF.
                    wl = a.space_name or ""
                    if wl:
                        tw = pymupdf.get_text_length(wl, fontname=MARKER_LABEL_FONT,
                                                     fontsize=WIFI_LABEL_SIZE)
                        tx = p.x - tw / 2
                        ty = p.y + WIFI_LABEL_SIZE + 5
                        sp.box(tx - 2.5, ty - WIFI_LABEL_SIZE * 0.78 - 1.5, tx + tw + 2.5, ty + 3,
                               color=wcol, fill=(1, 1, 1), fill_opacity=0.85, width=0.4)
                        sp.text(tx, ty, wl, fontsize=WIFI_LABEL_SIZE,
                                fontname=MARKER_LABEL_FONT, color=WIFI_LABEL_INK)
                    ner = next((n for n in ners if n.key == a.ner_key), None)
                    npt = _point_on(ner, sk, p)
                    if draw_links and npt is not None:
                        sp.line((p.x, p.y), (npt.x, npt.y),
                                color=colour, width=0.6, dashes="[1 2] 0")
                    continue
                if off_page is not None and not sp.contains(p.x, p.y):
                    off_page.append({"kind": "space", "key": a.space_key,
                                     "label": a.space_name, "page": sk,
                                     "x": round(p.x, 1), "y": round(p.y, 1),
                                     "page_width": sp.width, "page_height": sp.height})
                poly = a.area.polygon
                if poly and len(poly) >= 3:
                    sp.polyline(list(poly) + [poly[0]], color=colour,
                                fill=colour, fill_opacity=0.22, width=0.8)
                else:
                    sp.circle(p.x, p.y, 5.0, color=colour, fill=colour,
                              fill_opacity=0.45, width=0.6)
                if not a.match_confirmed:
                    sp.box(p.x - 12, p.y - 9, p.x + 12, p.y + 9,
                           color=STATUS_FILL[Status.MATCH_NOT_CONFIRMED], width=1.1)
                # The space → room leader line with its distance. Optional
                # since 10 Sep 2026 (``with NER → space lines`` on Reports):
                # on a sheet with a hundred served rooms the lines are the
                # picture, and there are readers who want the markers and the
                # verdict colours without them. When the room is on another
                # page there is no line to draw; the space says which room
                # serves it instead, so the reader is not left with a grey
                # fill and no explanation.
                if draw_links and a.ner_key:
                    ner = next((n for n in ners if n.key == a.ner_key), None)
                    npt = _point_on(ner, sk, p)
                    if npt is not None:
                        sp.line((p.x, p.y), (npt.x, npt.y),
                                color=colour, width=0.6, dashes="[1 2] 0")
                        if a.evaluation and a.evaluation.effective_distance_m is not None:
                            mx, my = (p.x + npt.x) / 2, (p.y + npt.y) / 2
                            sp.text(mx, my, f"{a.evaluation.effective_distance_m:.0f} m",
                                    fontsize=5.5, color=colour)
                    elif ner is not None:
                        sp.text(p.x + 7, p.y + 2,
                                f"{ner.label} ({st(ner.point.page)})",
                                fontsize=5.5, color=colour)

            for n, npt in ners_by_page.get(sk, []):
                # Always the kind colour. A room read back from a scenario
                # saved by the old optimiser still carries ``proposed``, and
                # painting it purple would put a shape on the sheet that the
                # legend no longer explains.
                colour = COLOURS.get(n.kind, (0, 0, 0))
                if off_page is not None and not sp.contains(npt.x, npt.y):
                    off_page.append({"kind": "ner", "key": n.key, "label": n.label,
                                     "page": sk, "x": round(npt.x, 1),
                                     "y": round(npt.y, 1),
                                     "page_width": sp.width, "page_height": sp.height})
                if n.kind in REFERENCE_KINDS:
                    sp.circle(npt.x, npt.y, MARKER_RADIUS, color=MARKER_RING,
                              fill=colour, width=MARKER_RING_WIDTH,
                              dashes=REFERENCE_RING_DASHES)
                else:
                    sp.circle(npt.x, npt.y, MARKER_RADIUS, color=MARKER_RING,
                              fill=colour, width=MARKER_RING_WIDTH)
                # The name sits on a translucent white tag *under* the dot, not
                # beside it. On a real book the marker lands on the room's own
                # label — the extractor put it there — and on the VDB comment
                # sets those labels are PDF *annotations*, which every viewer
                # paints above the page content: a tag beside the dot went
                # behind the drawing's own "NER 5" and read as half a word
                # (seen on the VBB book, 10 Sep 2026). Below the dot is
                # clear of the annotation's baseline; the tag keeps the name
                # readable and lets the linework show through.
                size = (REFERENCE_LABEL_SIZE if n.kind in REFERENCE_KINDS
                        else MARKER_LABEL_SIZE)
                tw = pymupdf.get_text_length(n.label, fontname=MARKER_LABEL_FONT,
                                             fontsize=size)
                tx = npt.x - tw / 2
                ty = npt.y + MARKER_RADIUS + size + 2
                sp.box(tx - 2.5, ty - size * 0.78 - 1.5, tx + tw + 2.5, ty + 3,
                       color=colour, fill=(1, 1, 1), fill_opacity=0.82, width=0.4)
                sp.text(tx, ty, n.label, fontsize=size,
                        fontname=MARKER_LABEL_FONT,
                        color=LABEL_COLOURS.get(n.kind, colour))

            if draw_legend and page_no == legend_page:
                _draw_legend(sp, scenario, rules, scale,
                             coverage_available=coverage_available)
            else:
                _draw_footnote(sp, scenario, rules, scale,
                               coverage_available=coverage_available,
                               legend_elsewhere=draw_legend)
            # One commit per page. Committing per drawn item re-parses the
            # page's content stream every time, which on a CAD sheet is the
            # difference between seven seconds and two and a half minutes.
            sp.commit()

        if progress is not None:
            progress(0.92, f"writing {out_path.rsplit('/')[-1] or 'the file'}")
        doc.save(out_path)
        if progress is not None:
            progress(1.0, "done")
        return out_path
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------

_HEAD = Font(bold=True, color="FFFFFF")
_HEAD_FILL = PatternFill("solid", fgColor="1F3864")


def _write_sheet(ws, headers: list[str], rows: Iterable[Sequence]) -> None:
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = _HEAD
        cell.fill = _HEAD_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = "A2"
    # A filter on every heading, on every sheet: the person opening this is
    # going to filter it (by NER, by status, by "Needs validation") before
    # doing anything else, and a sheet that arrives without the arrows makes
    # them add it by hand every time (Marcelo, 21 Sep 2026).
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(ws.max_row, 2)}"
    for c in range(1, len(headers) + 1):
        width = max(12, min(48, len(str(headers[c - 1])) + 6))
        ws.column_dimensions[get_column_letter(c)].width = width


#: "NERs and ports", column by column (3.0.0 order).
NER_SHEET_HEADERS = ["NER", "Full name", "Space code", "Page", "Critical",
                     "Indoor / outdoor", "Spaces served", "Ports assigned",
                     "Total ports", "Utilisation %", "Wireless points",
                     "of which wireless ports", "Fibre runs to TER", "Notes"]
NER_COL = {h: i + 1 for i, h in enumerate(NER_SHEET_HEADERS)}

#: "Wireless points", column by column. "Indoor / outdoor" (4.5.0) sits next
#: to the type, as it does next to "Critical" on the NERs sheet.
WIFI_SHEET_HEADERS = ["Wireless point", "Type", "Indoor / outdoor", "Page", "Serving NER",
                      "Distance (m)", "Status", "TEAP space", "Tie", "Notes"]

PENDING_NER_LABEL = "Pending — no NER"
BY_NER_HEADERS = ["NER", "Critical", "Space code", "Space name", "Product code",
                  "Service / product", "Ports"]
_TOTAL_FONT = Font(bold=True)
_NER_TOTAL_FILL = PatternFill("solid", fgColor="D9E1F2")
_SPACE_TOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")
_REPEAT_FONT = Font(color="808080")


def _natural_key(label: str):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", label or "")]


def _write_teap_by_ner(ws, teap_rows: Sequence[tuple], critical_by_label: dict) -> None:
    """NER → space → product, with totals — the grouped twin of
    "TEAP and coverage".

    What it does that a PivotTable on the flat sheet does not:

    * the lines with no serving NER are one named group, "Pending — no NER",
      last — a pivot calls them "(blank)", and on a first pass they are most of
      the ports;
    * only TEAP lines, never anything else (4.0.0): an access point drawn on
      a sheet is not a TEAP product, and the space's wireless port is its own
      DWISA line, listed under the space like any other product. Each NER total
      therefore equals "Ports assigned" on "NERs and ports", and the grand total
      the Summary's "Total ports requested (TEAP)";
    * lines that count 0 ports (monitors, phones, TVs) are left out, and the
      count of them is stated under the total;
    * it is rebuilt on every export, so it can never miss rows the way a pivot
      on a fixed range does.

    Totals are ``SUBTOTAL(9, …)`` formulas: Excel skips nested SUBTOTALs, so
    no port is counted twice, and a filter on the sheet narrows the grand total
    with it. Rows carry outline levels — the 1/2/3 buttons in Excel collapse
    the sheet to NER totals, space totals, or every line. Labels repeat on
    every row (in grey after the first) so a filter on NER or space keeps its
    totals with it.
    """
    groups: dict[str, dict[tuple, list]] = {}
    zero_lines = 0
    for r in teap_rows:
        counted = r[16] or 0
        if not counted:
            zero_lines += 1
            continue
        ner = r[10] or PENDING_NER_LABEL
        groups.setdefault(ner, {}).setdefault((r[0] or "", r[1] or ""), []).append(
            (r[6] or "", r[7] or "", counted))

    order = sorted((k for k in groups if k != PENDING_NER_LABEL), key=_natural_key)
    if PENDING_NER_LABEL in groups:
        order.append(PENDING_NER_LABEL)

    _write_sheet(ws, BY_NER_HEADERS, [])
    ws.sheet_properties.outlinePr.summaryBelow = True
    row = 2
    for ner in order:
        crit = critical_by_label.get(ner)
        crit_txt = "" if crit is None else ("yes" if crit else "no")
        ner_first = row
        space_total_rows = []
        for (code, name), lines in sorted(groups[ner].items(),
                                          key=lambda kv: (kv[0][0] == "", kv[0][0], kv[0][1])):
            first = row
            for pcode, desc, ports in sorted(lines, key=lambda t: (t[0], t[1])):
                ws.append([ner, crit_txt, code, name, pcode, desc, ports])
                if row != ner_first:
                    for c in (1, 2):
                        ws.cell(row=row, column=c).font = _REPEAT_FONT
                if row != first:
                    for c in (3, 4):
                        ws.cell(row=row, column=c).font = _REPEAT_FONT
                ws.row_dimensions[row].outline_level = 2
                row += 1
            ws.append([ner, crit_txt, code, name, "", f"{name or code} total",
                       f"=SUBTOTAL(9,G{first}:G{row - 1})"])
            for c in range(1, 8):
                cell = ws.cell(row=row, column=c)
                cell.fill = _SPACE_TOTAL_FILL
                cell.font = Font(italic=True, bold=(c == 7))
            ws.row_dimensions[row].outline_level = 1
            space_total_rows.append(row)
            row += 1
        ws.append([ner, crit_txt, "", "", "", f"{ner} total",
                   f"=SUBTOTAL(9,G{ner_first}:G{row - 1})"])
        for c in range(1, 8):
            cell = ws.cell(row=row, column=c)
            cell.fill = _NER_TOTAL_FILL
            cell.font = _TOTAL_FONT
        row += 1
    last = max(row - 1, 2)
    ws.auto_filter.ref = f"A1:G{last}"
    # The grand total sits outside the filter range, one blank row down, like
    # the TOTAL row of "NERs and ports": sorting or filtering never moves it.
    g = last + 2
    ws.cell(row=g, column=1, value="Grand total").font = _TOTAL_FONT
    c = ws.cell(row=g, column=7, value=f"=SUBTOTAL(9,G2:G{last})")
    c.font = _TOTAL_FONT
    if zero_lines:
        ws.cell(row=g + 1, column=1,
                value=f"{zero_lines} TEAP line(s) count 0 ports and are not listed here "
                      f"(devices with no port of their own) — they are on "
                      f"'TEAP and coverage'.").font = _REPEAT_FONT
    widths = {"A": 20, "B": 9, "C": 16, "D": 40, "E": 14, "F": 60, "G": 9}
    for k, v in widths.items():
        ws.column_dimensions[k].width = v


def _needs_validation(assignment, evaluation, line) -> str:
    """Does a person still have to check this row?

    Three different doubts, one answer, because a reader scanning a sheet has
    one question and not three:

    * the coverage evaluation says so — an unconfirmed page scale, a route
      never validated;
    * the TEAP line was never matched to a room on the drawing by a human;
    * the port count on this line was **assumed** — rule B, C or D — rather
      than read off the TEAP. Rule A is the only one that reads a number that
      was actually written down.
    """
    if assignment is None:
        return "yes"
    if evaluation is not None and evaluation.requires_human_validation:
        return "yes"
    if not assignment.match_confirmed:
        return "yes"
    if line is not None and getattr(line, "rule", "A") != "A":
        return "yes"
    return "no"


def export_workbook(
    out_path: str,
    *,
    coverage: CoverageResult,
    ners: Sequence[NER],
    demands: Sequence,
    match_report=None,
    match_rows: Optional[Sequence[dict]] = None,
    rules: DistanceRules,
    project_name: str = "NER coverage analysis",
    source_files: Optional[dict[str, str]] = None,
    scale_for_page: Optional[dict[int, Scale]] = None,
    left_out: Optional[Sequence[tuple]] = None,
    figures: Optional[Sequence[dict]] = None,
    fibre_runs: tuple[int, int] = (2, 1),
    venue_code: Optional[str] = None,
    ner_info: Optional[dict[str, dict]] = None,
    wifi_info: Optional[dict[int, dict]] = None,
    sheet_cell=None,
) -> str:
    """``demands`` are the TEAP spaces **in scope** — the ones that request
    ports. ``left_out`` lists the rest as ``(code, name, TEAP lines, note)`` so
    the workbook says what it did not analyse instead of just not showing it.
    ``figures`` is the list :func:`app.services.coverage_figures` builds — the
    shares of the TEAP found, not found, tied by hand, served and pending —
    written to its own sheet when given.

    ``fibre_runs`` is ``(per critical NER, per non-critical NER)``: the fibre
    runs from the TER each room needs — two for a critical room (A and B
    paths), one otherwise, by default; a project setting. It is a count of
    runs, not a length: nothing here measures a fibre route.

    ``venue_code`` is the project's venue code (``VHH``): the *Full name*
    column of the NERs sheet is ``<code>_<NER name>`` (2.18.0).

    ``ner_info`` maps a room's key (``A<id>``) to what the register holds and
    the analysis does not: ``space_code`` (the AAM / VDB code of the room) and
    ``notes`` (what the person wrote on the NERs screen) — 3.0.0.

    ``wifi_info`` (4.5.0) maps a wireless point's element id to what the
    marker holds now — ``environment``: indoor (a covered area), outdoor (an
    open area) or None. Left out, the run's own value is used.

    ``sheet_cell`` (4.1.0) turns a sheet key into what a *Page* cell holds:
    left out, the page number as before; in a project with several books, the
    sheet's drawing number (see :mod:`app.sheets`)."""
    ner_info = ner_info or {}
    wifi_info = wifi_info or {}
    pc = sheet_cell or (lambda p: p)
    scale_for_page = scale_for_page or {}
    wb = openpyxl.Workbook()
    fibre_critical, fibre_noncritical = int(fibre_runs[0]), int(fibre_runs[1])

    # The totals the LLD team asks for first (Marcelo, 22 Sep 2026: "um
    # resumão: quantas portas no total, quantas fibras, quantos AP interno e
    # AP externo"). Computed once here, written at the top of the Summary
    # sheet and used again on the NERs sheet.
    summary = coverage.summary()
    rooms = [{**v, "key": k} for k, v in coverage.ner_load.items()]
    n_critical = sum(1 for i in rooms if i["critical"])
    n_noncritical = len(rooms) - n_critical
    fibre_total = n_critical * fibre_critical + n_noncritical * fibre_noncritical
    points = [a for a in coverage.assignments if a.kind == "wireless_point"]

    def wifi_env(a) -> str:
        """Indoor / outdoor of one Wi-Fi point (4.5.0): the marker as it is
        now, else what the run carried; "" = not said."""
        eid = a.area.meta.get("element_id")
        info = wifi_info.get(eid) if eid is not None else None
        return ((info or {}).get("environment") if info is not None
                else a.area.meta.get("environment")) or ""
    # Every port is a TEAP port (4.0.0): the DWISA line is the wireless port
    # of its space, and an access point drawn on a sheet adds none. These three
    # lines are the same numbers as "Coverage figures" and the TOTAL row of
    # "NERs and ports", and the last two add up to the first.
    totals = [
        ("Total ports requested (TEAP)", summary["total_ports"]),
        ("  of which wireless (DWISA)", summary["wireless_ports"]),
        ("Ports on a NER (assigned in this run)",
         round(sum(float(i["assigned_ports"]) for i in rooms), 1)),
        ("Ports on no NER yet (pending)", summary["ports_pending"]),
        ("NERs on the drawing", len(rooms)),
        ("  critical", n_critical),
        ("  non-critical", n_noncritical),
        ("Fibre runs to the TER (total)", fibre_total),
        (f"  critical NERs x {fibre_critical}", n_critical * fibre_critical),
        (f"  non-critical NERs x {fibre_noncritical}", n_noncritical * fibre_noncritical),
        ("Wi-Fi points drawn (one per space; not an AP count)", summary["wireless_points"]),
        # Indoor / outdoor NERs (2.14.0): the kind of rack the venue is sent.
        ("NERs indoor", sum(1 for i in rooms if i.get("environment") == "indoor")),
        ("NERs outdoor", sum(1 for i in rooms if i.get("environment") == "outdoor")),
        ("NERs indoor/outdoor not said", sum(1 for i in rooms if not i.get("environment"))),
        # Indoor / outdoor Wi-Fi points (4.5.0): the setting each access point
        # is proposed for — covered or open.
        ("Wi-Fi points indoor", sum(1 for a in points if wifi_env(a) == "indoor")),
        ("Wi-Fi points outdoor", sum(1 for a in points if wifi_env(a) == "outdoor")),
        ("Wi-Fi points indoor/outdoor not said", sum(1 for a in points if not wifi_env(a))),
    ]

    ws = wb.active
    ws.title = "Summary"
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    rows = [
        ("Project", project_name),
        ("Generated", stamp),
        ("Generated by", PRODUCED_BY),
    ]
    rows += [(k if k.startswith("  ") else f"Totals: {k}", v) for k, v in totals]
    rows += [
        ("General limit (m)", rules.general_limit_m),
        ("Photographer limit (m)", rules.photographer_limit_m),
        ("Near-limit threshold", f"{rules.near_limit_ratio:.0%} of the limit"),
        ("Routing slack factor", rules.routing_slack_factor),
        ("Cross-floor without a route allowed", rules.allow_cross_floor_without_route),
        ("Fibre runs to the TER per NER",
         f"{fibre_critical} per critical NER, {fibre_noncritical} per non-critical NER "
         f"(a count of runs, not a length)"),
    ]
    for k, v in (source_files or {}).items():
        rows.append((f"Source: {k}", v))
    for k, v in summary.items():
        rows.append((f"Result: {k}", str(v)))
    # The demand rules, spelled out where somebody opening this file cold will
    # find them. Exactly one fires per TEAP line — that is what structurally
    # prevents double counting, and it is worth stating rather than implying.
    rows.append(("Port demand rules",
                 "Exactly one fires per TEAP line, which is what prevents "
                 "double counting:"))
    for letter, label in RULE_LABEL.items():
        rows.append((f"  Rule {letter}", RULE_MEANING[letter]))
    rows.append(("Disclaimer", DISCLAIMER))
    _write_sheet(ws, ["Field", "Value"], rows)

    # ------------------------------------------------------------------
    # The figures — how much of the TEAP is placed, served, pending, as
    # counts and shares. Marcelo, 22 Sep 2026: "uma sheet falando dos
    # percentuais: espaços no TEAP que foram encontrados no desenho, não
    # encontrados, feitos à mão". The share is a real number formatted as a
    # percentage, so the reader can chart it; the denominator is on the row.
    # ------------------------------------------------------------------
    if figures:
        ws = wb.create_sheet("Coverage figures", 1)
        _write_sheet(ws, ["Section", "Figure", "Count", "Of", "Share", "Note"],
                     ((f["section"], f["label"], f["count"],
                       f["of"] if f["of"] is not None else "",
                       f["share"] if f["share"] is not None else "",
                       f.get("note") or "") for f in figures))
        for r in range(2, ws.max_row + 1):
            ws.cell(row=r, column=5).number_format = "0.0%"
        ws.column_dimensions["B"].width = 58
        ws.column_dimensions["F"].width = 64

    # ------------------------------------------------------------------
    # Sheet 1 — the TEAP, with the answer added to it.
    #
    # This used to be two sheets: "Coverage", one row per space, and "Demand
    # detail", one row per TEAP line. Reading them meant holding a space key in
    # your head while moving between them, and the second one carried no
    # coverage at all.
    #
    # They are one sheet now, shaped like the source document: every space,
    # every service on it, every port — the TEAP as it arrived — with three
    # columns added on the right. Which NER serves the space, whether that NER
    # is critical, and how far it is. That is the whole question this
    # application exists to answer, and it now reads across a single row.
    #
    # It is flat on purpose: no subtotal row per space. A subtotal is a row that
    # is not a service, and one of those every few lines is what stops a sheet
    # being sorted, filtered or pivoted without first stripping them out. The
    # totals are on the next sheet, "TEAP by NER", and one PivotTable away
    # for anything else.
    #
    # Columns that were dropped rather than moved:
    #   * NER internal id and "Chosen by" — the identifier is in the register
    #     and in the change requests, which is where a rename has to stay
    #     traceable; on a coverage row it was a handle nobody uses.
    #   * Method, Limit, Margin, geometric and farthest-point distances — the
    #     arithmetic behind the verdict. The verdict is in Status.
    #   * Scale used / confirmed / match confirmed — three separate yes/no
    #     columns answering one question, which is now asked once as
    #     "Needs validation". That column stays, because a row that reached a
    #     conclusion from an unconfirmed scale or an unconfirmed match has to
    #     say so on the row and not only in a footnote.
    #   * Rule, Explanation and Demand type — dropped at Marcelo's request on
    #     2 Sep 2026. On the event's TEAP every one of 17,495 checkable lines fires
    #     rule A, so the column read "A — explicit in the TEAP" on every row and
    #     its explanation repeated the same sentence: two columns of constant.
    #     Demand type answered "which limit applies", which Status already
    #     settles as a verdict.
    #
    #     What Rule *did* carry on a different workbook is the warning that a
    #     port count was assumed rather than read. That has not been dropped
    #     with the column — it folds into "Needs validation", which is where a
    #     reader looks for "does a human still have to check this row".
    # ------------------------------------------------------------------
    by_space = {a.space_key: a for a in coverage.assignments}
    ws = wb.create_sheet("TEAP and coverage")
    teap_rows = []
    for d in demands:
        a = by_space.get(d.space_key)
        ev = a.evaluation if a else None
        # "Status" is the pile the space is in — served, out of limit, served
        # but not measured, pending — and "Status detail" the precise verdict
        # behind it (match not confirmed, scale not confirmed, no room on the
        # drawing…). Two columns since 2.7.0: the first is what the person
        # filters on, the second is why.
        if a is None:
            group, detail = GROUP_LABEL[Group.PENDING], PENDING_NOT_ANALYSED
        else:
            group = GROUP_LABEL[group_of(a.status.value)]
            detail = STATUS_WORDS.get(a.status, a.status.value)
            if a.unplaced and a.ner_key is None:
                detail = PENDING_NO_ROOM
        tail = (
            a.ner_label or "" if a else "",
            ("" if a is None or a.ner_critical is None
             else ("yes" if a.ner_critical else "no")),
            (None if not ev or ev.effective_distance_m is None
             else round(ev.effective_distance_m, 2)),
            group, detail,
        )
        head = (d.space_code, d.space_name,
                getattr(a.area, "building", "") if a else "",
                getattr(a.area, "level", "") if a else "",
                (pc(a.area.page) or "") if a else "")
        # "Needs validation" is computed per line, not per space, because one
        # of the three things it answers is per line: a port count the importer
        # *assumed* from a category default rather than read off the TEAP. The
        # Rule column that used to say so is gone, and an assumed number that
        # looks exactly like an explicit one is the one thing this sheet must
        # not do.
        # "Ports" is the TEAP as it arrived and never changes. "Counted ports"
        # is what the analysis put on a NER for this line — since 4.0.0 always
        # the same number: the DWISA wireless line counts on its space like any
        # other line, whether or not access points are drawn for it. The column
        # stays so a workbook read side by side with an older one keeps its
        # shape.
        for ln in d.lines:
            teap_rows.append(head + (
                ln.row_number, ln.product_code, ln.product_description,
                ln.quantity, ln.ports,
            ) + tail + (_needs_validation(a, ev, ln), ln.ports))
        # A space with no TEAP lines behind it still gets one row, or it would
        # disappear from the sheet entirely — and a space that reached the
        # coverage analysis and then vanished from the report is the one kind of
        # omission nobody catches.
        if not d.lines:
            teap_rows.append(head + ("", "", "", "", d.total_ports)
                             + tail + (_needs_validation(a, ev, None), d.total_ports))
    _write_sheet(ws, [
        "Space code", "Space name", "Building", "Level", "Page",
        "TEAP row", "Product code", "Service / product", "Qty", "Ports",
        "Serving NER", "NER critical", "Distance (m)", "Status", "Status detail",
        "Needs validation", "Counted ports",
    ], teap_rows)

    # ------------------------------------------------------------------
    # "TEAP by NER" (2.9.0) — the same lines, summed the way the LLD team
    # reads them: NER → space → product, with a total per space, per NER and
    # overall. Marcelo built this as a PivotTable on an export on 24 Sep 2026
    # and asked for it in the file. It is written as a grouped sheet, not a
    # real PivotTable: openpyxl cannot create one, and a hand-written pivot
    # definition that Excel dislikes opens with a repair prompt and loses the
    # table. See _write_teap_by_ner for what it adds over his pivot.
    # ------------------------------------------------------------------
    _write_teap_by_ner(wb.create_sheet("TEAP by NER"), teap_rows,
                       {i["label"]: i["critical"] for i in rooms})

    # ------------------------------------------------------------------
    # Sheet 2 — the NERs and their ports.
    # ------------------------------------------------------------------
    # NERs only — a TER, an IDF and a COW never serve a space, so they are never
    # in the port load and never on this sheet.
    #
    # "Capacity known" was a column here and is gone: it said "no" exactly when
    # "Total ports" was blank, which the blank already says. Blank still means
    # *unknown* and is never read as zero — that is a rule of the engine, not of
    # this sheet.
    #
    # "Fibre runs to TER" (2.8.0): how many fibre runs from the TER the room
    # needs — two for a critical NER, one for a non-critical NER by default,
    # a project setting. A count, never a length. The bottom of the sheet
    # carries a TOTAL row of live SUM formulas, kept outside the filter range
    # so sorting or filtering the rooms never drags it into the data.
    ws = wb.create_sheet("NERs and ports")
    # 3.0.0 (Marcelo, 14 Oct 2026): the full name moves to B, the room's space
    # code (AAM / VDB, typed or corrected on the NERs screen) is C, and the
    # notes written on the NERs screen are the last column. Everything else
    # keeps its order.
    _write_sheet(ws, NER_SHEET_HEADERS,
                 ((i["label"],
                   # 2.18.0: the naming sheet's full name, venue code + NER name
                   ner_full_name(venue_code, i["label"]),
                   (ner_info.get(i["key"]) or {}).get("space_code") or "",
                   pc(i["page"]), "yes" if i["critical"] else "no",
                   i.get("environment") or "",
                   len(i["spaces"]), round(i["assigned_ports"], 1),
                   i["total_ports"], None,
                   i.get("wireless_points", 0), round(i.get("wireless_ports", 0.0), 1),
                   fibre_critical if i["critical"] else fibre_noncritical,
                   (ner_info.get(i["key"]) or {}).get("notes") or "")
                  for i in rooms))
    ws.column_dimensions[get_column_letter(NER_COL["Notes"])].width = 60
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=NER_COL["Notes"]).alignment = Alignment(wrap_text=True,
                                                                        vertical="top")
    # Utilisation is a live formula, not a number: the network team fills in
    # or corrects "Total ports" on this very sheet, and the figure has to
    # follow. Blank total → blank utilisation, never 0 % (unknown is not zero).
    last_room_row = ws.max_row
    assigned = get_column_letter(NER_COL["Ports assigned"])
    total = get_column_letter(NER_COL["Total ports"])
    for r in range(2, last_room_row + 1):
        cell = ws.cell(row=r, column=NER_COL["Utilisation %"])
        cell.value = f'=IF(OR({total}{r}="",{total}{r}=0),"",{assigned}{r}/{total}{r})'
        cell.number_format = "0.0%"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(NER_SHEET_HEADERS))}{max(last_room_row, 2)}"
    if rooms:
        total_row = last_room_row + 2            # one blank row keeps it apart
        ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
        ws.cell(row=total_row, column=NER_COL["Critical"],
                value=f"{n_critical} critical / {n_noncritical} non-critical")
        n_in = sum(1 for i in rooms if i.get("environment") == "indoor")
        n_out = sum(1 for i in rooms if i.get("environment") == "outdoor")
        n_unsaid = len(rooms) - n_in - n_out
        ws.cell(row=total_row, column=NER_COL["Indoor / outdoor"],
                value=f"{n_in} indoor / {n_out} outdoor"
                      + (f" / {n_unsaid} not said" if n_unsaid else ""))
        for name in ("Spaces served", "Ports assigned", "Total ports", "Wireless points",
                     "of which wireless ports", "Fibre runs to TER"):
            letter = get_column_letter(NER_COL[name])
            c = ws.cell(row=total_row, column=NER_COL[name],
                        value=f"=SUM({letter}2:{letter}{last_room_row})")
            c.font = Font(bold=True)
        u = ws.cell(row=total_row, column=NER_COL["Utilisation %"],
                    value=f'=IF(OR({total}{total_row}="",{total}{total_row}=0),"",'
                          f'{assigned}{total_row}/{total}{total_row})')
        u.number_format = "0.0%"
        u.font = Font(bold=True)

    # The access points drawn on the sheets. Their own sheet, because they are
    # not TEAP lines: no port of their own (4.0.0) — the port is the DWISA line
    # of the space each one belongs to, counted on that space's row. The NER
    # and the distance say whether the 90 m rule holds where the AP is drawn.
    if points:
        ws = wb.create_sheet("Wireless points")
        # "Indoor / outdoor" (4.5.0) beside the type, as on the NERs sheet:
        # a covered area or an open one, said by the person; blank = not said.
        _write_sheet(ws, WIFI_SHEET_HEADERS,
                     ((a.space_name, "Wi-Fi", wifi_env(a), pc(a.area.page), a.ner_label or "",
                       (None if not a.evaluation or a.evaluation.effective_distance_m is None
                        else round(a.evaluation.effective_distance_m, 2)),
                       a.status.value,
                       a.area.meta.get("space_name") or "",
                       ("" if not a.area.meta.get("space_key")
                        else "by you" if a.area.meta.get("tie_source") == "manual"
                        else "placed from the TEAP" if a.area.meta.get("tie_source") == "teap"
                        else "proposed"),
                       " | ".join(a.reasons)) for a in points))

    if left_out:
        ws = wb.create_sheet("TEAP spaces with no ports")
        _write_sheet(ws, ["Space code", "Space name", "TEAP lines", "Why it is not analysed"],
                     left_out)

    ws = wb.create_sheet("Exceptions")
    _write_sheet(ws, ["Space key", "Space name", "Page", "Status", "Status detail", "Detail"],
                 ((e["space_key"], e["space_name"], pc(e.get("page")) or "",
                   GROUP_LABEL[group_of(e["status"])], e["status"], e["detail"])
                  for e in coverage.exceptions))

    # The matching evidence. It was taken off the TEAP × drawing screen, where
    # a confidence percentage next to a room name invited people to trust the
    # number instead of the drawing; it belongs in the file that gets audited.
    if match_report is not None:
        ws = wb.create_sheet("Matching")
        _write_sheet(ws, ["TEAP code", "TEAP name", "Drawing code", "Drawing name",
                          "Page", "Method", "Score", "Confidence", "Reason",
                          "Confirmed", "Notes"],
                     ((m.teap_code, m.teap_name,
                       m.best.drawing_space.space_code if m.best else "",
                       m.best.drawing_space.name if m.best else "",
                       pc(m.best.drawing_space.page) if m.best else "",
                       m.best.method.value if m.best else "none",
                       round(m.best.score, 1) if m.best else 0,
                       round(m.confidence, 3), m.best.reason if m.best else (m.exception or ""),
                       "yes" if m.confirmed else "no", " | ".join(m.notes))
                      for m in list(match_report.matches) + list(match_report.unmatched_teap)))

        ws = wb.create_sheet("Match exceptions")
        # From the TEAP to the drawing, never back: a room on the drawing that
        # no TEAP line points at is not an exception, and a code repeated
        # across sheets is only worth a row when a TEAP line was tied to it.
        ex_rows = [("TEAP not found on drawings", m.teap_code, m.teap_name, m.exception or "")
                   for m in match_report.unmatched_teap]
        tied = {normalise_code(m.best.drawing_space.space_code)
                for m in match_report.matches if m.best and m.best.drawing_space.space_code}
        ex_rows += [("Same space on several pages", k, "", pages_label(v))
                    for k, v in match_report.multi_level.items() if k in tied]
        ex_rows += [("Needs human validation", m.teap_code, m.teap_name,
                     f"confidence {m.confidence:.2f}") for m in match_report.needs_review]
        _write_sheet(ws, ["Exception type", "Code", "Name", "Detail"], ex_rows)

    if match_report is None and match_rows is not None:
        # The application's own export: the matching as it stands in the
        # project — the matcher's answer with every decision a person laid over
        # it — rather than a fresh run. Until 2.8.1 the app never passed either,
        # so the two sheets the manual describes were only ever written by the
        # command-line tools.
        ws = wb.create_sheet("Matching")
        _write_sheet(ws, ["TEAP code", "TEAP name", "Drawing code", "Drawing name",
                          "Page", "Method", "Score", "Confidence", "Reason",
                          "Confirmed", "Confirmed by", "Notes"],
                     ((r.get("teap_code") or "", r.get("teap_name") or "",
                       r.get("drawing_code") or "", r.get("drawing_name") or "",
                       pc(r.get("page")) if r.get("page") is not None else "",
                       r.get("method") or "none", round(float(r.get("score") or 0), 1),
                       round(float(r.get("confidence") or 0), 3), r.get("reason") or "",
                       "yes" if r.get("confirmed") else "no", r.get("confirmed_by") or "",
                       " | ".join(r.get("notes") or []))
                      for r in match_rows))
        ws = wb.create_sheet("Match exceptions")
        ex_rows = [("TEAP not found on drawings", r.get("teap_code") or "",
                    r.get("teap_name") or "", r.get("exception") or "no drawing space matched")
                   for r in match_rows if not r.get("drawing_space_id") and not r.get("rejected")]
        ex_rows += [("Rejected — not on this drawing", r.get("teap_code") or "",
                     r.get("teap_name") or "", "declared off this drawing by a person")
                    for r in match_rows if r.get("rejected")]
        pages_by_code: dict[str, set] = {}
        for r in match_rows:
            for pg_ in (r.get("pages_of_code") or []):
                pages_by_code.setdefault(r.get("drawing_code") or "", set()).add(pg_)
        ex_rows += [("Same space on several pages", code, "", pages_label(sorted(pages)))
                    for code, pages in sorted(pages_by_code.items()) if code and len(pages) > 1]
        ex_rows += [("Needs human validation", r.get("teap_code") or "", r.get("teap_name") or "",
                     f"{r.get('method') or 'none'} — confidence {float(r.get('confidence') or 0):.2f}")
                    for r in match_rows if r.get("drawing_space_id") and not r.get("confirmed")]
        _write_sheet(ws, ["Exception type", "Code", "Name", "Detail"], ex_rows)

    ws = wb.create_sheet("Scales")
    _write_sheet(ws, ["Page", "Scale label", "Source", "Metres per PDF unit", "Confirmed"],
                 ((pc(p), s.label, s.source, s.metres_per_unit, "yes" if s.confirmed else "no")
                  for p, s in sorted(scale_for_page.items())))

    _order_and_colour_sheets(wb)
    wb.save(out_path)
    return out_path


#: The order of the sheets and the colour of their tabs (Marcelo, 16 Oct
#: 2026, from a screenshot of the tab bar): the three the network team works
#: from first — "TEAP by NER" red, "NERs and ports" and "Wireless points"
#: yellow — then the rest with no colour. A sheet a run did not write is
#: skipped; one not named here goes last.
SHEET_ORDER = ["TEAP by NER", "NERs and ports", "Wireless points", "Summary",
               "TEAP and coverage", "Matching", "Match exceptions", "Exceptions",
               "TEAP spaces with no ports", "Scales", "Coverage figures"]
TAB_YELLOW = "FFFF00"
TAB_RED = "FF0000"
SHEET_TAB_COLOUR = {"TEAP by NER": TAB_RED, "NERs and ports": TAB_YELLOW,
                    "Wireless points": TAB_YELLOW}


def _order_and_colour_sheets(wb) -> None:
    rank = {name: i for i, name in enumerate(SHEET_ORDER)}
    wb._sheets.sort(key=lambda ws: rank.get(ws.title, len(SHEET_ORDER)))
    for i, ws in enumerate(wb.worksheets):
        colour = SHEET_TAB_COLOUR.get(ws.title)
        ws.sheet_properties.tabColor = colour if colour else None
        # Only the first tab selected: "Summary" was created as the active
        # sheet and keeps ``tabSelected``; left on it, Excel would open with
        # two tabs grouped and every edit would land on both.
        ws.sheet_view.tabSelected = (i == 0)
    wb.active = 0


def export_csv(out_path: str, coverage: CoverageResult, sheet_cell=None) -> str:
    import csv
    pc = sheet_cell or (lambda p: p)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["space_key", "space_name", "page", "demand_type", "ports_required",
                    "ner", "ner_internal_id", "ner_chosen_by", "ner_critical",
                    "distance_m", "method", "limit_m", "margin_m", "status",
                    "needs_validation"])
        for a in coverage.assignments:
            ev = a.evaluation
            w.writerow([
                a.space_key, a.space_name, pc(a.area.page) or "", a.demand_type.value,
                a.ports_required, a.ner_label or "", a.ner_key or "",
                "you" if a.pinned else ("the engine" if a.ner_key else ""),
                "" if a.ner_critical is None else ("yes" if a.ner_critical else "no"),
                "" if not ev or ev.effective_distance_m is None else round(ev.effective_distance_m, 2),
                ev.method.value if ev else "", ev.limit_m if ev else "",
                "" if not ev or ev.margin_m is None else round(ev.margin_m, 2),
                a.status.value,
                "yes" if (ev and ev.requires_human_validation) else "no",
            ])
    return out_path
