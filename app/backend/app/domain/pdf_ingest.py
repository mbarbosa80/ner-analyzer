"""Vector-PDF extraction: pages, text with coordinates, scales, spaces and NER/TER
markers.

Design note — why colour is not the primary signal
--------------------------------------------------
The specification proposes blue = TER, red = critical NER, yellow = non-critical
NER. Real event venue design books do not honour that convention: on the
reference drawing used to build this module every equipment room label — critical
and non-critical alike — is drawn in the same red (#cc0000), and criticality is
carried by the **word** "Critical" in the label text. Classifying on colour alone
would therefore have mislabelled every non-critical NER on the sheet.

The extractor consequently scores several independent signals — label text,
symbol colour, PDF layer (OCG), proximity to a legend entry and spatial context —
and reports a confidence per element. Nothing is ever silently accepted: the UI
requires human confirmation for anything below the configured threshold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import pymupdf

from .aam_vocab import SpaceVocabulary, strip_length_tag
from .drawn_rooms import (find_drawn_rooms, is_illustrative_title, is_key_plan_title,
                          leader_geometry)
from .ner_symbol import find_ner_symbols
from .geometry import Point
from .units import Scale, parse_scale_candidates

# ---------------------------------------------------------------------------
# Patterns (all overridable per project)
# ---------------------------------------------------------------------------

#: Event venue space code, e.g. SPT.016.01, TEC.004-02, VVO.001
#: The sub-indices take one to three digits (4.2.0): the 3.x design books print
#: PEM.003.000-003 and PRS.007.001-004, which the two-digit form cut to PEM.003
#: and pushed ".000-003" into the room's name — on the VAA book 213 of 590
#: spaces, and "exact" matches to the wrong room (VBV.001 Field of Play →
#: VBV.001.001-001 Athlete Staging FOP).
SPACE_CODE_RX = re.compile(r"\b([A-Z]{2,4})\.(\d{2,3})(?:[.\-](\d{1,3}))?(?:[.\-](\d{1,3}))?\b")

#: A room marker is the WHOLE label: "NER 5", "Critical NER 12", "TER", "IDF",
#: "COW #1", "DIVA Node 2". The match is anchored at both ends on purpose. On the
#: reference drawing a substring search additionally picked up "Rack (NER)",
#: "Rack (NER) -", "(TER)" and "(COW/Temporary" — annotation callouts inside a
#: notes block that describe equipment, not rooms. A short trailing qualifier
#: after a dash or colon is tolerated because some sheets write
#: "NER 5 - Level 200".
#:
#: DIVA was added on 3 Sep 2026. The VAA and VEE books write it
#: as "DIVA Node", "DIVA NODE" and "DIVA Node Rack", so the word "Node" and the
#: word "Rack" are both optional parts of the kind, not a qualifier — otherwise
#: "DIVA Node Rack" would need the dash the sheets do not print.
ROOM_MARKER_RX = re.compile(
    r"""^\s*(?P<crit>CRITICAL\s+)?
         (?P<kind>NER|TER|IDF|MDF|COW|DIVA(?:\s+NODE)?(?:\s+RACK)?)\b
         \s*\#?\s*(?P<num>\d{1,3})?
         \s*(?:[-–—:]\s*[\w\s./]{0,24})?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

#: "63 m²", "1,250 SF"
AREA_RX = re.compile(r"^\s*([\d,.]+)\s*(m²|m2|sqm|sf|ft²)\s*$", re.IGNORECASE)

PHOTO_RX = re.compile(r"\bPHOTO(?:GRAPHER|GRAPHY)?S?\b|\bPHT\b", re.IGNORECASE)
SHAFT_RX = re.compile(r"\bSHAFT\b|\bRISER\b|\bSLEEVE\b", re.IGNORECASE)

#: Legend keys describe the notation rather than marking a room. They must never
#: become elements — on the reference drawing the legend alone would otherwise have
#: produced four phantom NERs per sheet.
LEGEND_HEADING_RX = re.compile(r"^\s*(LEGEND|KEY|NOTATION|SYMBOLS?)\s*:?\s*$", re.IGNORECASE)
LEGEND_ENTRY_RX = re.compile(
    r"""^\s*(?:
          (?:CRITICAL\s+)?(?:NER|TER|IDF|MDF|COW|DIVA)\s*[-–—:]\s*\S  # 'NER - Critical'
        | (?:PROPOSED|EXISTING|SUGGESTED|RELOCATED|REMOVED|NEW)\s+(?:NER|TER)
        | (?:NER|TER)\s+(?:CRITICAL|NON[\s-]?CRITICAL|PROPOSED|EXISTING)
        | (?:NON[\s-]?CRITICAL|CRITICAL)\s+(?:NER|TER)\s*$
      )""",
    re.IGNORECASE | re.VERBOSE,
)

#: How far below a "LEGEND" heading text is still considered part of the legend.
LEGEND_BAND_HEIGHT = 220.0
LEGEND_BAND_WIDTH = 420.0


class ElementKind(str):
    TER = "TER"
    NER_CRITICAL = "NER_CRITICAL"
    NER_NONCRITICAL = "NER_NONCRITICAL"
    IDF = "IDF"
    COW = "COW"
    #: A DIVA node — the broadcast-distribution rack the VDB marks beside the
    #: NERs. Drawn in purple; like a TER, an IDF and a COW it is on the plan so
    #: the plan shows what is in the building, and it never serves a space.
    DIVA = "DIVA"
    #: A wireless point (an access point) placed **by hand** in the viewer. It is
    #: never read off a drawing. It is not a room and serves nothing — it is
    #: *demand*: one network port on the nearest NER within the general limit.
    #: One kind since 2.14.0: the indoor/outdoor split of 2.5.0 went at
    #: Marcelo's request (29 Sep 2026: *"deixar tudo somente como AP mesmo"*);
    #: ``LEGACY_WIRELESS_OUTDOOR`` names the old kind so the start-up pass
    #: can fold it in.
    WIRELESS = "WIRELESS"
    #: A **reference** to a NER, drawn by hand on a key plan (2.7.0). The
    #: overview sheets of a design book — "key enlarged plan" — show the whole
    #: venue at a small scale, and Marcelo wants every NER pointed at on one
    #: such sheet, named after the real NER, with its reach circles drawn to
    #: that sheet's scale (22 Sep 2026: *"só para apontar no desenho … mas é
    #: importante que esse desenho mostre o raio 90m e 70m"*). It is a
    #: picture of a room that exists elsewhere: no register row, no TEAP
    #: link, no port, nothing counted — like a TER or a COW — but unlike them
    #: it does get the reach circles, because that is what it is drawn for.
    NER_CRITICAL_REF = "NER_CRITICAL_REF"
    NER_NONCRITICAL_REF = "NER_NONCRITICAL_REF"
    #: The same idea for the other rooms (2.8.0): a TER, a COW or a DIVA node
    #: pointed at on a key plan, named after the real one. Drawn with the
    #: dashed ring in the kind's colour; no reach circles (the real one has
    #: none either), no naming suggestion, nothing counted.
    TER_REF = "TER_REF"
    COW_REF = "COW_REF"
    DIVA_REF = "DIVA_REF"
    SHAFT = "SHAFT"
    UNKNOWN = "UNKNOWN"


#: The marker kinds that are drawn, moved, renamed and deleted by hand but take
#: part in nothing else — no register row, no TEAP link, no reach circle. The
#: NER kinds are what the study is about; these are the rest of the plan.
VISUAL_ONLY_KINDS = (ElementKind.TER, ElementKind.IDF, ElementKind.COW, ElementKind.DIVA)

#: The NER references drawn on a key plan: visual only *and* ringed with the
#: reach circles. Never a register row, never serving, never counted.
NER_REFERENCE_KINDS = (ElementKind.NER_CRITICAL_REF, ElementKind.NER_NONCRITICAL_REF)

#: Every reference kind — the NER ones above plus (2.8.0) the TER, COW and
#: DIVA references, which get the dashed ring and nothing else.
REFERENCE_KINDS = NER_REFERENCE_KINDS + (ElementKind.TER_REF, ElementKind.COW_REF,
                                         ElementKind.DIVA_REF)

#: The kind a reference stands for — what colour it is drawn in.
REFERENCE_OF = {ElementKind.NER_CRITICAL_REF: ElementKind.NER_CRITICAL,
                ElementKind.NER_NONCRITICAL_REF: ElementKind.NER_NONCRITICAL,
                ElementKind.TER_REF: ElementKind.TER,
                ElementKind.COW_REF: ElementKind.COW,
                ElementKind.DIVA_REF: ElementKind.DIVA}

#: The marker kinds that are **demand** rather than rooms: drawn by hand, never
#: in the register, never serving — and each one takes ports on the NER that
#: reaches it. The wireless points (Marcelo, 17 Sep 2026).
DEMAND_KINDS = (ElementKind.WIRELESS,)

#: The kind of the outdoor access point of 2.5.0–2.13.x. Folded into
#: ``WIRELESS`` by the start-up pass of 2.14.0; never created any more.
LEGACY_WIRELESS_OUTDOOR = "WIRELESS_OUTDOOR"

#: Label prefix and human name of a wireless point. The prefix is what the
#: viewer numbers a new point with (``WIFI-1``, ``WIFI-2`` …). Since 4.3.0 the
#: point says "this space has Wi-Fi", not "an access point goes here": Marcelo,
#: 19 Oct 2026 — *"não marque mais os AP como AP e sim como Wi-Fi somente. Pois
#: não quero mais associar isso com qtde de AP"*. The AP count belongs to the
#: wireless design; the TEAP's DWISA line stays the space's wireless port.
WIRELESS_PREFIX = {ElementKind.WIRELESS: "WIFI"}
WIRELESS_NAME = {ElementKind.WIRELESS: "Wi-Fi"}
#: Labels of the earlier numbering, renamed by the 4.3.0 start-up pass.
LEGACY_WIRELESS_LABEL_RX = r"AP-(\d+)"

#: Ports one wireless point takes on its NER: none since 4.0.0. The access
#: point's uplink is the TEAP's ``DWISA`` line of the space it belongs to,
#: counted on that space's row; an access point drawn on a sheet is a position,
#: not a product of the TEAP (Marcelo, 16 Oct 2026).
WIRELESS_POINT_PORTS = 0.0


@dataclass
class TextItem:
    text: str
    x: float
    y: float
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    size: float
    color: int
    #: Writing direction of the line, as PyMuPDF reports it: (1, 0) for normal
    #: horizontal text, (0, 1) or (0, -1) for text rotated a quarter turn.
    #: Venue design books use rotated labels heavily — a room whose name does
    #: not fit horizontally gets turned — and the label parts of a rotated
    #: label are laid out along x at constant y, which is the transpose of what
    #: the horizontal case does.
    dir_x: float = 1.0
    dir_y: float = 0.0

    @property
    def rotated(self) -> bool:
        """Is this line written vertically rather than horizontally?"""
        return abs(self.dir_y) > abs(self.dir_x)

    @property
    def point(self) -> Point:
        return Point(self.x, self.y, self.page)

    @property
    def hex_color(self) -> str:
        return f"#{self.color:06x}"


@dataclass
class DetectedSpace:
    space_code: Optional[str]
    name: str
    page: int
    x: float
    y: float
    area_label: Optional[str] = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    @property
    def point(self) -> Point:
        return Point(self.x, self.y, self.page)


@dataclass
class DetectedElement:
    kind: str
    label: str
    page: int
    x: float
    y: float
    number: Optional[int] = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    color: Optional[str] = None
    locked: bool = False

    @property
    def point(self) -> Point:
        return Point(self.x, self.y, self.page)


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    rotation: int
    is_vector: bool
    vector_count: int
    image_count: int
    char_count: int
    scale_candidates: list[Scale] = field(default_factory=list)
    sheet_title: Optional[str] = None
    level_hint: Optional[str] = None
    #: The drawing number from the title block; "" when the block was read and
    #: carried none, so the caller can tell "none printed" from "never looked".
    sheet_number: str = ""
    #: The title block names a key plan ("KEY ENLARGED PLAN - LEVEL 01"):
    #: an overview sheet that only illustrates (2.13.0).
    key_plan: bool = False


@dataclass
class DrawingExtract:
    path: str
    page_count: int
    pages: list[PageInfo]
    spaces: list[DetectedSpace]
    elements: list[DetectedElement]
    needs_ocr_pages: list[int]
    layer_names: list[str]
    #: NER rooms the sheets print — a TEC.003 code or a "Network Equipment
    #: Rack (NER)" label — read on every page that is not a key plan (2.13.0).
    rooms: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _iter_text_items(page: pymupdf.Page, page_no: int) -> Iterable[TextItem]:
    """Text on a page, in the coordinates the page is *displayed* in.

    The distinction matters and it cost a day. Sheets in a venue design book
    carry ``/Rotate 90``: the media box is portrait (1584 x 2448) and the sheet
    is drawn to be viewed landscape (2448 x 1584). PyMuPDF reports text in the
    **unrotated** box; PDF.js, which renders the page in the viewer, applies the
    rotation and hands back the landscape one.

    So the application was drawing markers taken from one coordinate system on
    top of an image drawn in another. Every room and every NER landed somewhere
    plausible-looking and wrong, which is the worst kind of wrong: a marker in
    open ground reads as a data problem, not a projection problem.

    It also explains a symptom chased earlier: every line on every page came
    back with ``dir=(0, -1)``, and that was read as "this book turns its
    labels". No book turns *all* of its text. The whole page was turned.

    ``page.rotation_matrix`` maps the unrotated box onto the displayed one, so
    applying it here puts extraction and rendering in the same space once, at
    the single point where coordinates enter the application.
    """
    rot = page.rotation_matrix
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            rect = pymupdf.Rect(line["bbox"]) * rot
            x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
            # The writing direction has to turn with the page, or a label that
            # is horizontal on screen still reports itself as vertical.
            raw = line.get("dir", (1.0, 0.0)) or (1.0, 0.0)
            direction = (rot.a * raw[0] + rot.c * raw[1],
                         rot.b * raw[0] + rot.d * raw[1])
            yield TextItem(
                text=text, x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                x0=x0, y0=y0, x1=x1, y1=y1, page=page_no,
                size=spans[0].get("size", 0.0), color=spans[0].get("color", 0),
                dir_x=float(direction[0]), dir_y=float(direction[1]),
            )


def _group_space_labels(items: list[TextItem], *, max_gap: float = 26.0,
                        max_dx: float = 140.0) -> list[DetectedSpace]:
    """Reconstruct room labels of the form ``<area> / <name> / <space code>``.

    Room annotations on a venue design book are stacked text lines. This walks
    outward from each space-code line and attaches the nearest lines above it that
    are horizontally aligned, which recovers the room name and its area tag.
    """
    spaces: list[DetectedSpace] = []
    for i, it in enumerate(items):
        m = SPACE_CODE_RX.search(it.text)
        if not m or len(it.text) > 40:
            continue
        code = m.group(0)
        # The line may be "Toilets FOP SPT.003.03" — name inline with the code.
        inline_name = SPACE_CODE_RX.sub("", it.text).strip(" -–—/")
        name_parts: list[str] = [inline_name] if inline_name else []
        area_label = None
        evidence = [f"space code '{code}' found on page {it.page}"]

        # Which way is this label written? A room label is a stack of lines —
        # area tag, name, code — and "stacked" means different things depending
        # on the writing direction:
        #
        #   horizontal text   the parts share an x and step down in y
        #   rotated text      the parts share a y and step across in x
        #
        # Searching only the horizontal arrangement is what made 158 of the 253
        # spaces in the VCC book arrive as a bare code with no name: the labels
        # are turned a quarter turn, the name sits *beside* the code rather than
        # above it, and the "directly above" test rejected it every time. The
        # room was found and positioned correctly; only its name was lost, which
        # is worse than it sounds — the TEAP is matched on the name.
        for other in items:
            if other is it or other.page != it.page:
                continue
            if it.rotated:
                # The parts of a rotated label stack along x and each part runs
                # along y. Two parts of the *same* label therefore cover the
                # same span of y.
                #
                # The cross-axis test has to be an overlap, not a distance.
                # Reusing ``max_dx`` (140) here was the first attempt and it
                # merged neighbours: on page 10 of the VCC book BRS.002 sits at
                # y=919 and BRS.011 at y=991, only 72 apart, so each label
                # reached into the next and BRS.002 came out named "Technical
                # Operation Center Active Equipment Space Cabin" — itself plus
                # the room next door. A wrong name is worse than a missing one,
                # because it matches the wrong TEAP row instead of none.
                #
                # Overlap is the right test and needs no tuning: it scales with
                # the length of the words themselves.
                lo, hi = max(it.y0, other.y0), min(it.y1, other.y1)
                shorter = min(it.y1 - it.y0, other.y1 - other.y0)
                if shorter <= 0 or (hi - lo) < shorter * 0.5:
                    continue
                # Positive => other comes before the code in reading order.
                dy = it.x0 - other.x1
            else:
                # Same overlap test as the rotated branch, on the other axis.
                # The distance tolerance it replaces (140 points) was wide
                # enough to reach the next room along: on page 10 the cabins sit
                # about 70 points apart, so each label collected its neighbour's
                # words and BRS.002 came out as "Technical Operation Center
                # Active Equipment Space Cabin" — itself plus the room next
                # door. Overlap needs no tuning and cannot reach sideways.
                lo, hi = max(it.x0, other.x0), min(it.x1, other.x1)
                shorter = min(it.x1 - it.x0, other.x1 - other.x0)
                if shorter <= 0 or (hi - lo) < shorter * 0.5:
                    continue
                dy = it.y0 - other.y1      # positive => other is above
            if not (-2.0 <= dy <= max_gap):
                continue
            am = AREA_RX.match(other.text)
            if am:
                area_label = other.text.strip()
                continue
            if SPACE_CODE_RX.search(other.text):
                continue
            if 1 <= len(other.text) <= 60:
                name_parts.append((other.y0, other.text) if False else other.text)

        name = " ".join(dict.fromkeys(p for p in name_parts if p)).strip()
        confidence = 0.55
        if name:
            confidence += 0.25
            evidence.append("room name recovered from adjacent text")
        if area_label:
            confidence += 0.10
            evidence.append(f"area tag '{area_label}' adjacent")
        spaces.append(DetectedSpace(
            space_code=code, name=name or code, page=it.page, x=it.x, y=it.y,
            area_label=area_label, confidence=min(confidence, 0.95), evidence=evidence,
        ))

    # de-duplicate identical codes at (almost) the same coordinates
    out: list[DetectedSpace] = []
    for s in spaces:
        dup = next((o for o in out if o.space_code == s.space_code and o.page == s.page
                    and abs(o.x - s.x) < 4 and abs(o.y - s.y) < 4), None)
        if dup is None:
            out.append(s)
        elif len(s.name) > len(dup.name):
            out[out.index(dup)] = s
    return out


# ---------------------------------------------------------------------------
# Sheets that print no space code — the room name is all there is
# ---------------------------------------------------------------------------
#
# The VEE and VCC books print the TEAP space code beside every room
# label, and the extractor above starts from the code. A cricket venue's
# book (VDD_300_CKT, VDB 3.0) prints none: every room is labelled by its name
# alone — "Venue Media Centre (VMC)", "Workforce Check-in", "LIC Storage" —
# stacked over two or three lines in the same 12 pt black text. Read with the
# code-first grouping that book yields nine pages, ten equipment rooms and no
# spaces at all, and the matching step then refuses to run.
#
# So when a sheet carries no space code, the room-name labels are taken as the
# spaces. The rules below say what a room-name label is; everything else on the
# sheet — legend, client-group key, general notes, title block, revision table,
# scale bar, stamps, the NER markers themselves — is excluded by an explicit
# test, and every space produced this way says so in its evidence and carries a
# low confidence, because the TEAP will be matched on the name alone and a name
# is a weaker key than a code. The review queue does the rest.
#
# The fallback runs only for a sheet with zero codes. A coded sheet is read
# exactly as before, so no existing project changes shape.

#: Words a sheet prints that are never a room: stamps, key-plan captions,
#: scale-bar text, the confidentiality banner.
_NOT_A_ROOM_RX = re.compile(
    r"""^\s*(?:
          CONFIDENTIAL | NOT\s+FOR\s+CONSTRUCTION | PRELIMINARY | DRAFT
        | FOR\s+(?:REVIEW|INFORMATION|COMMENT|APPROVAL)(?:\s+ONLY)? | ISSUED\s+FOR\b.*
        | KEY\s+PLAN | NORTH | TRUE\s+NORTH | PLAN\s+NORTH
        | SCALE\b.* | m | ft | N\.?T\.?S\.?
        | GENERAL\s+NOTES?:? | NOTES?:? | REVISIONS? | REV\.?
        | CLIENT\s+GROUPS? | SITE\s+SYMBOLS | AREAS | FENCES | FLOWS | ACCESS\s+CONTROL
        | \d+(?:\.\d+)? | [\d,.\s]+ (?:m²|m2|sqm|sf|ft²)
        | \d{1,2}[./]\d{1,2}[./]\d{2,4}.*
        | (?:https?|autodesk\s+docs)://.*
        )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

#: The lowest confidence the review queue shows; a name-only space sits here
#: because nothing but the words on the sheet supports it.
NAME_ONLY_CONFIDENCE = 0.45


def _title_block_strip(items: list[TextItem], page_width: float, page_height: float
                       ) -> Optional[tuple[float, float, float, float]]:
    """The region the title block, legend and notes occupy, if the labels show it.

    On the event's sheets the block is a column down the right edge and the legend,
    client-group key and general notes sit in the same column above it. On a
    sheet with a horizontal block along the bottom the same reading gives a
    band. Both are the smallest rectangle from the leftmost (or topmost) block
    label to the page edge. Without any block label there is no strip, and only
    the other tests apply.
    """
    # Anchor on the labels the title-block reader itself trusts — DRAWING
    # NUMBER / DRAWING TITLE. The wider label set includes SCALE, and the scale
    # bar prints "SCALE 1:" in the middle of the sheet, which pulled the strip
    # off its column on the VDD book.
    anchors = [it for it in items
               if _label_key(it.text) in NUMBER_LABELS or _label_key(it.text) in TITLE_LABELS]
    if not anchors:
        return None
    x_min = min(it.x0 for it in anchors)
    y_min = min(it.y0 for it in anchors)
    if x_min > page_width * 0.6:
        # a column down the right edge: everything to its right, full height
        return (x_min - 30.0, 0.0, page_width, page_height)
    if y_min > page_height * 0.6:
        # a band along the bottom: everything below its top, full width
        return (0.0, y_min - 30.0, page_width, page_height)
    return None


def _is_room_name_line(it: TextItem, strip: Optional[tuple[float, float, float, float]],
                       bands: list[tuple[float, float, float, float]]) -> bool:
    t = it.text.strip()
    if len(t) < 2 or len(t) > 60 or not re.search(r"[A-Za-z]", t):
        return False
    if strip is not None and _in_bands(it, [strip]):
        return False
    if _in_bands(it, bands):
        return False
    if _NOT_A_ROOM_RX.match(t) or LEGEND_ENTRY_RX.match(t):
        return False
    if _classify_marker(it) is not None:
        return False
    # A bare title-block label ("VENUE", "STATUS") is only a risk when the
    # block could not be located; inside a located strip it is already out, and
    # a room label may legitimately be one of those words on its own line
    # ("RES On" / "Venue" / "Results" / "(OVR)" on the VDD book).
    if strip is None and _label_key(t) in _BLOCK_LABELS:
        return False
    # Numbered notes ("1. FOR ADDITIONAL INFORMATION …") and bullet text.
    if re.match(r"^\s*(?:\d{1,2}[.)]|[-•*])\s+\S", t):
        return False
    # A sheet reference on a key plan — "311A-CKT-O", "A-101" — is a drawing
    # number, not a room: one token, separators, at least one digit.
    if re.fullmatch(r"[A-Z0-9]+(?:[-._/][A-Z0-9]+)+", t) and any(c.isdigit() for c in t):
        return False
    return True


def _group_name_labels(items: list[TextItem], *, max_gap: float = 2.0,
                       vocab: Optional[SpaceVocabulary] = None) -> list[DetectedSpace]:
    """Room-name labels of a sheet that prints no space code.

    Since 2.14.0 a label is a space only when ``vocab`` knows a name like it
    — an AAM space name or one the project's TEAP prints (see
    :mod:`aam_vocab`). Without a vocabulary every label is taken, as before.

    A room label is a stack of lines in one size that overlap along the reading
    axis and sit within ``max_gap`` of each other on the other one — "Venue" /
    "Technology" / "Operations" / "(VTO)". The lines are merged in reading order
    into one name and the space is placed at the centre of the stack.

    ``max_gap`` is the empty space *between* two line boxes, not the line
    pitch. Lines of one label are set on a pitch shorter than the box the font
    reports (12 pt text, 13.5 pt pitch, 16 pt boxes on the VDD book), so within
    a label the gap is *negative*. Two different labels stacked one above the
    other come as close as 4 pt on page 9 of that book — "SPP Control Room"
    over "Commentator Position" — which is what fixes the limit at 2: a wider
    one merged those two into one room. The code-first grouping's 26 pt is a
    different measure (the reach from a code line to its name) and does not
    apply here.
    """
    cand = list(items)
    n = len(cand)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        a = cand[i]
        for j in range(i + 1, n):
            b = cand[j]
            if a.rotated != b.rotated or abs(a.size - b.size) > 0.6:
                continue
            if a.rotated:
                lo, hi = max(a.y0, b.y0), min(a.y1, b.y1)
                shorter = min(a.y1 - a.y0, b.y1 - b.y0)
                gap = max(a.x0, b.x0) - min(a.x1, b.x1)
            else:
                lo, hi = max(a.x0, b.x0), min(a.x1, b.x1)
                shorter = min(a.x1 - a.x0, b.x1 - b.x0)
                gap = max(a.y0, b.y0) - min(a.y1, b.y1)
            if shorter <= 0 or (hi - lo) < shorter * 0.5:
                continue
            if gap <= max_gap:
                union(i, j)

    groups: dict[int, list[TextItem]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cand[i])

    out: list[DetectedSpace] = []
    for lines in groups.values():
        rotated = lines[0].rotated
        # Reading order: top to bottom for horizontal text; a rotated label
        # reads along x, and PyMuPDF's direction sign says which way.
        if rotated:
            lines.sort(key=lambda it: it.x0, reverse=lines[0].dir_y < 0)
        else:
            lines.sort(key=lambda it: it.y0)
        name = " ".join(it.text.strip() for it in lines)
        name = re.sub(r"\s+", " ", name).strip()
        if not re.search(r"[A-Za-z]{2}", name) or len(name) > 120:
            continue
        known = None
        if vocab is not None:
            known = vocab.match(name)
            if known is None:
                continue
            name = strip_length_tag(name) or name
        x0 = min(it.x0 for it in lines); x1 = max(it.x1 for it in lines)
        y0 = min(it.y0 for it in lines); y1 = max(it.y1 for it in lines)
        evidence = [
            "no space code printed on this sheet: the room-name label is the space",
            f"label '{name}' read from {len(lines)} line(s) of {lines[0].size:.0f} pt text",
        ]
        if known is not None:
            evidence.append(f"reads as the space name '{known[1]}' ({known[0]}% similar)"
                            if known[0] < 100 else f"a known space name ('{known[1]}')")
        evidence.append("matched on the name alone — confirm the room against the TEAP")
        out.append(DetectedSpace(
            space_code=None, name=name, page=lines[0].page,
            x=(x0 + x1) / 2, y=(y0 + y1) / 2,
            confidence=NAME_ONLY_CONFIDENCE if known is None else min(0.6, NAME_ONLY_CONFIDENCE + known[0] / 500),
            evidence=evidence,
        ))
    return out


def _legend_bands(items: list[TextItem]) -> list[tuple[float, float, float, float]]:
    """Rectangles that hold a legend, so their entries can be excluded."""
    bands: list[tuple[float, float, float, float]] = []
    for it in items:
        if LEGEND_HEADING_RX.match(it.text):
            bands.append((it.x0 - 40.0, it.y0 - 10.0,
                          it.x0 + LEGEND_BAND_WIDTH, it.y1 + LEGEND_BAND_HEIGHT))
    return bands


def _in_bands(it: TextItem, bands: list[tuple[float, float, float, float]]) -> bool:
    return any(x0 <= it.x <= x1 and y0 <= it.y <= y1 for x0, y0, x1, y1 in bands)


def _classify_marker(item: TextItem, layer_hint: Optional[str] = None) -> Optional[DetectedElement]:
    if LEGEND_ENTRY_RX.match(item.text):
        return None
    m = ROOM_MARKER_RX.match(item.text.strip().upper())
    if not m or len(item.text) > 40:
        return None

    kind_raw = m.group("kind").upper()
    critical = bool(m.group("crit"))
    num = int(m.group("num")) if m.group("num") else None
    evidence: list[str] = []
    confidence = 0.0

    # -- signal 1: label text (strongest, and the only one that carries criticality)
    evidence.append(f"label text '{item.text.strip()}'")
    confidence += 0.55
    if critical:
        evidence.append("label contains the word 'Critical'")
        confidence += 0.15
    if num is not None:
        evidence.append(f"room number {num} parsed from the label")
        confidence += 0.10

    # -- signal 2: colour (corroborating only, never decisive)
    hexc = item.hex_color
    if hexc in ("#cc0000", "#ff0000", "#e00000"):
        evidence.append(f"marker drawn in red {hexc}")
        confidence += 0.08
    elif hexc in ("#0000cc", "#0000ff"):
        evidence.append(f"marker drawn in blue {hexc}")
        confidence += 0.05
    elif hexc in ("#ffcc00", "#ffff00", "#e6b800"):
        evidence.append(f"marker drawn in yellow {hexc}")
        confidence += 0.05
    else:
        evidence.append(f"marker colour {hexc} does not match the documented convention")

    # -- signal 3: PDF layer
    if layer_hint:
        evidence.append(f"on layer '{layer_hint}'")
        confidence += 0.05

    if kind_raw == "TER":
        kind = ElementKind.TER
    elif kind_raw == "COW":
        kind = ElementKind.COW
    elif kind_raw in ("IDF", "MDF"):
        kind = ElementKind.IDF
    elif kind_raw.startswith("DIVA"):
        kind = ElementKind.DIVA
    else:
        kind = ElementKind.NER_CRITICAL if critical else ElementKind.NER_NONCRITICAL
        if not critical:
            evidence.append(
                "no 'Critical' keyword: classified as non-critical, needs confirmation "
                "because the drawing does not distinguish criticality by colour"
            )
            confidence -= 0.05

    return DetectedElement(
        kind=kind, label=item.text.strip(), page=item.page, x=item.x, y=item.y,
        number=num, confidence=max(0.0, min(confidence, 0.98)),
        evidence=evidence, color=hexc,
    )


#: The font-size guess of :func:`_sheet_context` — a bare ``142`` / ``155A``,
#: as opposed to a ``LEVEL 01`` the sheet prints.
GUESSED_LEVEL_RX = re.compile(r"\d{3}[A-Z]?")


def _sheet_context(items: list[TextItem]) -> tuple[Optional[str], Optional[str]]:
    """Best-effort sheet title and level hint from the title block."""
    title = None
    level = None
    for it in items:
        t = it.text.strip()
        if re.fullmatch(r"(LEVEL|LVL|FLOOR)\s*[-:]?\s*[A-Z0-9]{1,6}", t, re.IGNORECASE):
            level = t
        if re.fullmatch(r"\d{3}[A-Z]?", t) and it.size >= 10 and level is None:
            level = t
        if len(t) > 12 and it.size >= 14 and title is None and not SPACE_CODE_RX.search(t):
            title = t
    return title, level


# ---------------------------------------------------------------------------
# The title block — read by its labels, not guessed from font sizes
# ---------------------------------------------------------------------------
#
# Every sheet of the event's venue design books carries the same title block in the
# lower-right corner: a small label (``DRAWING NUMBER``, ``DRAWING TITLE``,
# ``VENUE``, 7 pt) with the value printed just below it (``VFF-401-CSL-O``,
# ``KEY ENLARGED PLAN - LEVEL 01``, 10–12 pt). Measured on the VFF
# book, 10 Sep 2026: the value sits 11–12 pt below its label and within
# 100 pt of it horizontally, on every page probed.
#
# Reading the block by its labels is what makes this reliable. The earlier
# heuristic — "the longest text at 14 pt or more" — put ``Critical NER 4`` down
# as the sheet title of page 18 because a room label happened to be the
# biggest text on the sheet, and it could not have found the drawing number
# at all: on page 1 a key-plan grid tag ``410C8-CSL-O`` is printed at 16 pt
# in the same corner, larger than the real number and shaped just like it.

NUMBER_LABELS = {"DRAWINGNUMBER", "DRAWINGNO", "DRAWINGNR", "DWGNO", "DWGNUMBER",
                 "SHEETNUMBER", "SHEETNO", "SHEETNR"}
TITLE_LABELS = {"DRAWINGTITLE", "SHEETTITLE", "SHEETNAME", "DRAWINGNAME"}
#: Labels that share the title block and must never be read as a value.
_BLOCK_LABELS = NUMBER_LABELS | TITLE_LABELS | {
    "VENUE", "SPORTDISCIPLINE", "DISCIPLINE", "STATUS", "DRAWN", "CHECKED",
    "APPROVED", "SCALE", "DATE", "REV", "REVISIONS", "DESCRIPTION", "PROJECT",
    "CLIENT", "PAPERSIZE", "SHEET", "DRAWING", "LEVEL", "TITLE", "NUMBER"}

#: What a drawing number may look like, loosely: letters and digits with
#: separators, at least one digit, no spaces — ``VFF-410B8-CSL-O``, ``A-101``,
#: ``E1.01``, ``T-401``. It is only applied to the text found *under the label*,
#: so it is a sanity check, not the search.
SHEET_NUMBER_RX = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{1,30}$")
_DATE_RX = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
_LEVEL_IN_TITLE_RX = re.compile(
    r"\b(?:LEVEL|LVL|FLOOR)\s*[-:]?\s*(\d{1,3}[A-Z]?|[A-Z]{1,2}\d{0,2})\b", re.IGNORECASE)


@dataclass
class TitleBlock:
    number: Optional[str] = None
    title: Optional[str] = None
    level: Optional[str] = None
    evidence: list[str] = field(default_factory=list)


def _label_key(text: str) -> str:
    return re.sub(r"[^A-Z]", "", text.upper())


def _value_below(label: TextItem, items: list[TextItem]) -> Optional[TextItem]:
    """The text printed beside, or else under, a title-block label.

    Two layouts exist. A *horizontal* block writes ``SHEET NO.  A-101`` on one
    line, so a non-label item on the label's own line, to its right, is the
    value. A *vertical* block — the event's books — writes the value 10–15 pt
    under the label, and the label's own line carries nothing else. Beside is
    tried first: in a horizontal block the item *under* a label is the next
    label's value, and it would be read as this one's.
    """
    beside: Optional[tuple[float, TextItem]] = None
    below: Optional[tuple[float, TextItem]] = None
    for it in items:
        if it is label or _label_key(it.text) in _BLOCK_LABELS:
            continue
        dy = it.y - label.y
        dx = it.x - label.x
        if abs(dy) <= 4.0 and it.x0 >= label.x1 - 2.0 and dx <= 320.0:
            if beside is None or dx < beside[0]:
                beside = (dx, it)
        elif 2.0 < dy <= 40.0 and abs(dx) <= 220.0:
            if below is None or dy < below[0]:
                below = (dy, it)
    if beside is not None:
        return beside[1]
    return below[1] if below else None


def _title_block(items: list[TextItem]) -> TitleBlock:
    """Sheet number, title and level read off the title block by its labels."""
    tb = TitleBlock()
    for it in items:
        key = _label_key(it.text)
        if key in NUMBER_LABELS and tb.number is None:
            v = _value_below(it, items)
            if v is not None:
                text = v.text.strip()
                compact = text.replace(" ", "")
                if (SHEET_NUMBER_RX.match(compact.upper()) and any(c.isdigit() for c in compact)
                        and not _DATE_RX.search(text)):
                    tb.number = compact.upper()
                    tb.evidence.append(f"'{text}' printed under '{it.text.strip()}'")
        elif key in TITLE_LABELS and tb.title is None:
            v = _value_below(it, items)
            if v is not None and v.text.strip():
                tb.title = v.text.strip()
                tb.evidence.append(f"'{tb.title}' printed under '{it.text.strip()}'")
    if tb.title:
        m = _LEVEL_IN_TITLE_RX.search(tb.title)
        if m:
            tb.level = f"LEVEL {m.group(1).upper()}"
    return tb


def read_title_blocks(path: str, pages: Optional[Iterable[int]] = None
                      ) -> dict[int, TitleBlock]:
    """Title blocks only — text, no geometry — for a book already imported.

    What the start-up backfill runs over a book imported before the drawing
    number was read at all. Costs one text pass per page; nothing else in the
    extraction is repeated, and nothing already stored is touched by this
    function itself.
    """
    wanted = set(pages) if pages is not None else None
    out: dict[int, TitleBlock] = {}
    doc = pymupdf.open(path)
    try:
        for i in range(doc.page_count):
            page_no = i + 1
            if wanted is not None and page_no not in wanted:
                continue
            out[page_no] = _title_block(list(_iter_text_items(doc[i], page_no)))
    finally:
        doc.close()
    return out


def read_page_spaces(path: str, pages: Iterable[int], *,
                     known_names: Optional[Iterable[str]] = None) -> list[DetectedSpace]:
    """The spaces of the given pages, read as a detail sheet — whatever the
    title block says. For a page taken off the key plans by hand (2.14.0),
    which was imported with no spaces because it was one."""
    vocab = SpaceVocabulary(known_names) if known_names is not None else None
    wanted = set(pages)
    out: list[DetectedSpace] = []
    doc = pymupdf.open(path)
    try:
        for i in range(doc.page_count):
            page_no = i + 1
            if page_no not in wanted:
                continue
            page = doc[i]
            items = list(_iter_text_items(page, page_no))
            bands = _legend_bands(items)
            coded = _group_space_labels([it for it in items if not _in_bands(it, bands)])
            if coded:
                out.extend(coded)
            else:
                strip = _title_block_strip(items, page.rect.width, page.rect.height)
                out.extend(_group_name_labels(
                    [it for it in items if _is_room_name_line(it, strip, bands)], vocab=vocab))
    finally:
        doc.close()
    return out


def _page_drawn_rooms(page: pymupdf.Page, page_no: int, items: list[TextItem],
                      drawings: list[dict], bands) -> list:
    """The NER rooms one sheet states: TEC codes, rack labels and the NER
    block symbols (2.15.0), with the legend and the title block excluded —
    the symbol is explained in the legend and placed on the plan."""
    strip = _title_block_strip(items, page.rect.width, page.rect.height)

    def _excluded(it, _bands=bands, _strip=strip):
        return _in_bands(it, _bands) or (_strip is not None and _in_bands(it, [_strip]))

    def _excluded_point(x, y, _bands=bands, _strip=strip):
        zones = list(_bands) + ([_strip] if _strip is not None else [])
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in zones)

    arrows, segs = leader_geometry(drawings, page.rotation_matrix)
    symbols = find_ner_symbols(drawings, page.rotation_matrix, page_no,
                               excluded_point=_excluded_point)
    return find_drawn_rooms(items, arrows, segs, excluded=_excluded, symbols=symbols)


def read_drawn_rooms(path: str, *, skip_pages: Iterable[int] = (),
                     progress: Optional[Callable[[float, str], None]] = None) -> list:
    """The NER rooms a book prints — codes, labels and block symbols — read
    page by page. ``skip_pages`` are the key plans: no NER is ever read off
    one. Every other page's strokes are walked (the symbols have no text to
    announce them), about a second or two per sheet, so ``progress`` is
    called per page when given.
    """
    skip = set(skip_pages)
    out: list = []
    doc = pymupdf.open(path)
    try:
        for i in range(doc.page_count):
            page_no = i + 1
            if page_no in skip:
                continue
            if progress is not None:
                progress(i / max(doc.page_count, 1), f"reading the NERs drawn on page {page_no}")
            page = doc[i]
            items = list(_iter_text_items(page, page_no))
            bands = _legend_bands(items)
            out.extend(_page_drawn_rooms(page, page_no, items, page.get_drawings(), bands))
    finally:
        doc.close()
    return out


def extract_drawing(path: str, *, max_pages: Optional[int] = None,
                    text_threshold: int = 120,
                    progress: Optional[Callable[[float, str], None]] = None,
                    known_names: Optional[Iterable[str]] = None,
                    ) -> DrawingExtract:
    """Extract everything the coverage engine needs from one PDF.

    Pages whose extracted character count falls below ``text_threshold`` while
    containing a raster image are flagged for OCR rather than silently skipped.

    ``progress`` is called once per page with ``(fraction, stage)``; it may raise
    to abort the extraction, which is how cancellation works.

    ``known_names`` (2.14.0) are the space names the project's TEAP prints;
    with the bundled AAM names they are what a name-only label is checked
    against. ``None`` keeps the old behaviour (every label is a space) —
    for the unit tests of the grouping itself; the service always passes a
    list, empty or not.
    """
    vocab = SpaceVocabulary(known_names) if known_names is not None else None
    doc = pymupdf.open(path)
    try:
        layer_names = [v.get("name", "") for v in doc.get_ocgs().values()]
        pages: list[PageInfo] = []
        spaces: list[DetectedSpace] = []
        elements: list[DetectedElement] = []
        needs_ocr: list[int] = []
        rooms: list = []

        n = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for i in range(n):
            if progress is not None:
                progress(i / max(n, 1), f"reading page {i + 1} of {n}")
            page = doc[i]
            page_no = i + 1
            items = list(_iter_text_items(page, page_no))
            raw_text = page.get_text("text")
            drawings = page.get_drawings()
            images = page.get_images(full=True)

            info = PageInfo(
                number=page_no,
                width=page.rect.width,
                height=page.rect.height,
                rotation=page.rotation,
                is_vector=len(raw_text) >= text_threshold or len(drawings) > 50,
                vector_count=len(drawings),
                image_count=len(images),
                char_count=len(raw_text),
                scale_candidates=parse_scale_candidates(raw_text),
            )
            info.sheet_title, info.level_hint = _sheet_context(items)
            # The title block, read by its labels, outranks the font-size
            # guess above wherever it found something: it is the sheet's own
            # statement of what it is.
            tb = _title_block(items)
            info.sheet_number = tb.number or ""
            if tb.title:
                info.sheet_title = tb.title
            if tb.level:
                info.level_hint = tb.level
            elif tb.number and info.level_hint and GUESSED_LEVEL_RX.fullmatch(info.level_hint):
                # A sheet with a real title block states its level in its
                # DRAWING TITLE ("ENLARGED PLAN B3 - LEVEL 01") or not at all.
                # A bare three-digit figure in a large font is not a level
                # there: on the VAA 600 series it was the seat count of a
                # stand ("142", "138"), which then became the level of the NERs
                # drawn on the sheet (4.1.0).
                info.level_hint = None
            # A key plan, or any other sheet that only illustrates — the
            # drawing index, the venue information, the abbreviations, the
            # typical solutions (2.14.0) — is ticked as such by default; the
            # Scale screen is where the person changes the answer.
            info.key_plan = is_illustrative_title(tb.title or info.sheet_title)
            pages.append(info)

            if info.char_count < text_threshold and info.image_count:
                needs_ocr.append(page_no)
                continue

            bands = _legend_bands(items)
            if info.key_plan:
                # No spaces on a sheet that only illustrates (2.14.0): its
                # rooms are the detail sheets' rooms, drawn small.
                coded = []
            else:
                coded = _group_space_labels([it for it in items if not _in_bands(it, bands)])
            if coded:
                spaces.extend(coded)
            elif not info.key_plan:
                # No code anywhere on the sheet: the room names are the spaces.
                strip = _title_block_strip(items, page.rect.width, page.rect.height)
                spaces.extend(_group_name_labels(
                    [it for it in items if _is_room_name_line(it, strip, bands)], vocab=vocab))
            for it in items:
                if _in_bands(it, bands):
                    continue
                el = _classify_marker(it)
                if el is not None:
                    if info.key_plan and el.kind in (ElementKind.NER_CRITICAL,
                                                     ElementKind.NER_NONCRITICAL):
                        # A key plan only illustrates (2.13.0): a NER written on
                        # it is a picture of a room drawn on a detail sheet, so
                        # it arrives as a reference — drawn with its circles,
                        # counted nowhere — never as a second NER.
                        el.kind = (ElementKind.NER_CRITICAL_REF
                                   if el.kind == ElementKind.NER_CRITICAL
                                   else ElementKind.NER_NONCRITICAL_REF)
                        el.evidence.append("written on a key plan: kept as a reference, "
                                           "not a NER")
                    elements.append(el)

            # NER rooms the sheet prints (2.13.0; block symbols since 2.15.0) —
            # never on a key plan.
            if not info.key_plan:
                rooms.extend(_page_drawn_rooms(page, page_no, items, drawings, bands))

        if progress is not None:
            progress(0.97, f"consolidating {len(spaces)} spaces and {len(elements)} markers")

        # collapse duplicated marker labels on the same page
        deduped: list[DetectedElement] = []
        for el in elements:
            dup = next((o for o in deduped if o.label.upper() == el.label.upper()
                        and o.page == el.page and abs(o.x - el.x) < 6 and abs(o.y - el.y) < 6), None)
            if dup is None:
                deduped.append(el)

        return DrawingExtract(
            path=path, page_count=doc.page_count, pages=pages, spaces=spaces,
            elements=deduped, needs_ocr_pages=needs_ocr, layer_names=layer_names,
            rooms=rooms,
        )
    finally:
        doc.close()


def render_page_png(path: str, page_no: int, dpi: int = 110) -> bytes:
    """Render one page for the viewer / for OCR."""
    doc = pymupdf.open(path)
    try:
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()
