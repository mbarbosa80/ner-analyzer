"""NER rooms the drawing already states, and the sheets that only illustrate (2.13.0).

Two rules Marcelo gave on 29 Sep 2026, both about not doing by hand what the
drawing already says.

**1. A NER room printed on the drawing becomes a NER.** The event's space
taxonomy files the network equipment racks under ``TEC.003``: ``TEC.003.01``
is a *Network Equipment Rack (NER) – Critical*, ``TEC.003.02`` a
*Non-Critical* one. The books print it three ways — ``TEC.003.01-05`` (the
usual form, a dash before the room number), ``TEC.003.01.005`` and a bare
``TEC.003.02`` (a real 9 m² room on page 22 of the VEE book). Some
sheets print no code at all, only the room label — "Network Equipment Rack
(NER) - Critical" — with a leader arrow from the label to the room (the
VBB containment book: 27 such labels on 10 pages and not one code). In
his words: *"Eu só quero evitar criar todas as NER manualmente se a
informação já tá no desenho... prefiro conferir e validar do que criar tudo
do zero."* So this module finds those rooms and says where each one is; the
caller decides what becomes of them (see ``services.adopt_drawn_rooms``).

Where a room is placed matters more than it looks. The label is often printed
*outside* the room with an arrow pointing at it — 10 to 40 m away on a site
plan — so the label's own position would put the NER in the car park. The
leader is followed to its arrowhead and the NER goes at the tip. When no
leader can be followed the label's position is used and the room says so.

Criticality comes from the code when there is one (the code decides:
"-Placeholder" + ``.01`` is critical), else from the words after "(NER)".
When neither says, the room is reported with ``critical=None`` — never
guessed.

**The 3.x books (2.15.0, 1 Oct 2026).** The AAM taxonomy moved: ``TEC.010``
is now the *Network Equipment Rack - Critical* and ``TEC.020`` the
*Non-Critical* one (``TEC.003`` became the Mobile Equipment Room, which the
old ``TEC.003.01/.02`` rule does not match — it needs the ``.01``/``.02``
class). The VCC Softball book prints ``TEC.020-003`` under a two-line label
"Network Equipment / Rack - Non-Critical" with no "(NER)" and no arrow (the
label sits in the room), and most racks are not rooms at all but a CAD
block — a small orange square with "NER" plotted as strokes, no text
layer — read by ``ner_symbol`` and handed in here as ``symbols``. Both the
old and the new spellings are read; the three AAM workbooks of 1 Oct 2026
(VDD, VEE, VBB) all file the racks under TEC.010 / TEC.020.

**2. A key plan is illustrative.** The overview sheets of a design book —
"KEY ENLARGED PLAN - LEVEL 01", "KEY FLOOR PLAN" — show the whole venue at a
small scale and repeat every room of the detail sheets. Tying a TEAP line to a
room there sent him to the right room on the wrong page. They are recognised
by the DRAWING TITLE of the title block (lower right) and kept out of every
TEAP × drawing crossing; ``is_key_plan_title`` is the whole test.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Key plans
# ---------------------------------------------------------------------------

#: A key plan's title: KEY … PLAN, in that order — "KEY ENLARGED PLAN - LEVEL
#: 01", "KEY FLOOR PLAN-LEVEL 02", "KEY PLAN". ``\bKEY\b`` keeps "KEYNOTE" out.
KEY_PLAN_TITLE_RX = re.compile(r"\bKEY\b.*\bPLAN\b", re.IGNORECASE)


def is_key_plan_title(title: Optional[str]) -> bool:
    """Whether a sheet title (from the title block) names a key plan."""
    return bool(title and KEY_PLAN_TITLE_RX.search(title))


#: The other sheets of a book that only illustrate (2.14.0): the drawing
#: index, the venue information and games map, the containment
#: abbreviations, the typical solutions, a cover, notes, a legend. Ticked as
#: "key plan" by default on the Scale screen — the tick means "illustrative,
#: out of every crossing", and these are — and untickable there.
ILLUSTRATIVE_TITLE_RX = re.compile(
    r"""\b(?: DRAWING\s+INDEX | SHEET\s+INDEX | \bINDEX\b
           | VENUE\s+INFORMATION | GAMES\s+MAP | ABBREVIATIONS?
           | TYPICAL\b | GENERAL\s+NOTES? | LEGEND | SYMBOLS?
           | COVER\s+(?:SHEET|PAGE) | TITLE\s+SHEET )\b""",
    re.IGNORECASE | re.VERBOSE)


def is_illustrative_title(title: Optional[str]) -> bool:
    """Whether a sheet title names a sheet that only illustrates: a key plan,
    or an index / information / abbreviations / typical-solutions sheet."""
    if not title:
        return False
    return bool(KEY_PLAN_TITLE_RX.search(title) or ILLUSTRATIVE_TITLE_RX.search(title))


# ---------------------------------------------------------------------------
# What a NER room looks like on the sheet
# ---------------------------------------------------------------------------

#: The TEC.003 code of a network equipment rack (the 2.x books):
#: ``TEC.003.01-05``, ``TEC.003.01.005``, ``TEC.003.02``. Group 1 is the
#: class (1 critical, 2 non-critical), group 2 the room number when printed.
#: ``TEC.003-001`` (a Mobile Equipment Room in the 3.x taxonomy) has no
#: ``.01``/``.02`` class and does not match.
TEC003_RX = re.compile(
    r"\bTEC\s*\.\s*003\s*[.\-]\s*0?([12])(?:\s*[.\-]\s*(\d{1,3}))?(?![\d.])", re.IGNORECASE)

#: The 3.x codes: ``TEC.010-003`` (critical), ``TEC.020-003`` (non-critical),
#: or bare ``TEC.010`` / ``TEC.020`` (the class without a room number). Group
#: 1 is the class, group 2 the room number when printed. ``TEC.0100`` and
#: ``TEC.015-2`` (the COW) do not match.
TEC010_RX = re.compile(
    r"\bTEC\s*\.\s*0\s*([12])0(?:\s*[.\-]\s*(\d{1,3}))?(?![\d.])", re.IGNORECASE)

#: A line that *is* the room label (anchored — a sentence in a notes block that
#: mentions a rack is not a room): "Network Equipment Rack (NER) -",
#: "Rack (NER)", "Network Equipment Rack (NER) - Non-Critical".
ROOM_LABEL_RX = re.compile(
    r"""^\s*(?:Network\s+Equipment\s+)?Rack\s*\(\s*NER\s*\)\s*
         (?:[-–—:]\s*(?P<tail>[A-Za-z][A-Za-z \-]{0,24}?)?)?\s*$""",
    re.IGNORECASE | re.VERBOSE)

#: The 3.x label, which drops the "(NER)": "Rack - Non-Critical" under a
#: "Network Equipment" line, or "Network Equipment Rack - Critical" on one
#: line. Without the "(NER)" the criticality words are what makes it a rack
#: label, so they are required — "Rack - 2" or "Rack" alone is not one — and
#: a line that starts at "Rack" needs the "Network Equipment" line above it
#: (checked by the caller).
ROOM_LABEL_PLAIN_RX = re.compile(
    r"""^\s*(?P<head>Network\s+Equipment\s+)?Rack\s*
         [-–—:]\s*(?P<tail>Non[\s-]*Critical|Critical)\s*$""",
    re.IGNORECASE | re.VERBOSE)

NETWORK_EQUIPMENT_LINE_RX = re.compile(r"^\s*Network\s+Equipment\s*$", re.IGNORECASE)

#: The criticality words, alone on the line under the label.
CRIT_LINE_RX = re.compile(r"^\s*[-–—]?\s*(non[\s-]*critical|critical|placeholder)\s*$",
                          re.IGNORECASE)

#: How far (in points) a label's lines may sit from each other and still be
#: one label: the next line's box may touch or overlap the previous one.
_LINE_GAP = 3.0
#: How far a leader's first point may sit from the label's text.
_ANCHOR_PAD_X = 12.0
_ANCHOR_PAD_Y = 3.0
#: How close a leader's end must come to an arrowhead.
_TIP_TOLERANCE = 2.0


def normalise_code(text: str) -> Optional[str]:
    """The rack code in one spelling — ``TEC.003.01-05`` (2.x books),
    ``TEC.010-003`` / ``TEC.020-003`` / ``TEC.010`` (3.x books) — or None when
    ``text`` holds no rack code."""
    m = TEC003_RX.search(text or "")
    if m:
        cls, num = m.group(1), m.group(2)
        return f"TEC.003.0{cls}" + (f"-{int(num):02d}" if num else "")
    m = TEC010_RX.search(text or "")
    if m:
        cls, num = m.group(1), m.group(2)
        return f"TEC.0{cls}0" + (f"-{int(num):03d}" if num else "")
    return None


def code_names_a_room(code: Optional[str]) -> bool:
    """Whether a code carries a room number — ``TEC.020-003`` does, a bare
    ``TEC.010`` or ``TEC.003.02`` does not. Only a numbered code identifies
    one room across sheets; a bare class printed on two sheets is two racks
    until somebody says otherwise."""
    return bool(code) and bool(re.search(r"-\d+$", code))


def criticality_from_code(code: str) -> Optional[bool]:
    m = TEC003_RX.search(code or "")
    if m:
        return m.group(1) == "1"
    m = TEC010_RX.search(code or "")
    return None if not m else m.group(1) == "1"


def has_rack_code(text: str) -> bool:
    return bool(TEC003_RX.search(text or "") or TEC010_RX.search(text or ""))


def criticality_from_words(text: str) -> Optional[bool]:
    """``True`` for "Critical", ``False`` for "Non-Critical", None otherwise
    ("Placeholder", nothing). "Non-Critical" contains "Critical", so it is
    tested first."""
    t = (text or "").lower()
    if re.search(r"non[\s-]*critical", t):
        return False
    if re.search(r"\bcritical\b", t):
        return True
    return None


@dataclass
class DrawnRoom:
    """A NER room the sheet states, and where it is."""
    page: int
    #: Where the NER goes: the arrowhead's tip, else the label.
    x: float
    y: float
    label_x: float
    label_y: float
    #: True critical, False non-critical, None the drawing does not say.
    critical: Optional[bool]
    #: ``TEC.003.01-05`` when printed, else None.
    code: Optional[str]
    #: "code" (a TEC code), "label" (the room label alone) or "symbol" (the
    #: NER block symbol, no text at all).
    source: str
    #: The label as printed, lines joined.
    text: str
    #: The position is the tip of the label's arrow.
    via_leader: bool
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Leaders and arrowheads
# ---------------------------------------------------------------------------

@dataclass
class Arrowhead:
    tip: tuple[float, float]
    base: tuple[float, float]


@dataclass
class Segments:
    """The thin straight strokes of a page, indexed by their end points, so a
    leader can be walked from one segment to the next.

    Leaders come either as one path of a few segments (the VBB book) or
    as one path per segment (the VAA book: the stub off the label and the
    drop to the arrow are two paths). Walking the segments covers both.
    """
    segs: list[tuple[tuple[float, float], tuple[float, float], tuple]] = field(default_factory=list)
    index: dict[tuple[int, int], list[int]] = field(default_factory=dict)

    def add(self, a, b, colour) -> None:
        # The same stroke twice (a path closed back on itself, or drawn over)
        # would make every junction look like a fork.
        for j in self.at(a, 0.3):
            ja, jb, jc = self.segs[j]
            if jc == colour and (math.dist(jb, b) <= 0.3 or math.dist(ja, b) <= 0.3):
                return
        i = len(self.segs)
        self.segs.append((a, b, colour))
        for p in (a, b):
            self.index.setdefault((int(p[0] // 2), int(p[1] // 2)), []).append(i)

    def at(self, p, tol: float = 0.8) -> list[int]:
        """Segments with an end within ``tol`` of ``p``."""
        cx, cy = int(p[0] // 2), int(p[1] // 2)
        out: list[int] = []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for i in self.index.get((gx, gy), ()):
                    a, b, _ = self.segs[i]
                    if (math.dist(a, p) <= tol or math.dist(b, p) <= tol) and i not in out:
                        out.append(i)
        return out

    def starting_in(self, zone) -> list[int]:
        x0, y0, x1, y1 = zone
        out: list[int] = []
        for gx in range(int(x0 // 2), int(x1 // 2) + 1):
            for gy in range(int(y0 // 2), int(y1 // 2) + 1):
                for i in self.index.get((gx, gy), ()):
                    if i not in out:
                        out.append(i)
        return out

    def __len__(self) -> int:
        return len(self.segs)


def _pt(p, rot) -> tuple[float, float]:
    q = p * rot
    return (float(q.x), float(q.y))


def leader_geometry(drawings: list[dict], rot) -> tuple[list[Arrowhead], Segments]:
    """Arrowheads and thin strokes of a page, in display coordinates.

    An arrowhead is a small filled triangle (three straight sides, at most
    14 pt across). The strokes are every straight segment of every thin
    stroked path (walls and heavy lines are wider and left out). Both are
    read from ``page.get_drawings()`` — the same call the extractor already
    makes — and turned with ``rot`` (the page's rotation matrix) so they sit
    in the space the text is in.
    """
    arrows: list[Arrowhead] = []
    segs = Segments()
    for d in drawings:
        items = d.get("items") or []
        if not items:
            continue
        rect = d.get("rect")
        if d.get("fill") is not None:
            # Three sides, or two and a closing stroke (``closePath``).
            if rect is None or len(items) not in (2, 3, 4) or any(it[0] != "l" for it in items):
                continue
            if max(rect.width, rect.height) > 14.0 or max(rect.width, rect.height) < 1.2:
                continue
            verts: list[tuple[float, float]] = []
            for it in items:
                for p in (it[1], it[2]):
                    q = _pt(p, rot)
                    if not any(math.dist(q, v) < 0.3 for v in verts):
                        verts.append(q)
            if len(verts) != 3:
                continue
            # The tip is the vertex farthest from the middle of the other two.
            best = None
            for i, v in enumerate(verts):
                a, b = [w for j, w in enumerate(verts) if j != i]
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                dist = math.dist(v, mid)
                if best is None or dist > best[0]:
                    best = (dist, v, mid)
            arrows.append(Arrowhead(tip=best[1], base=best[2]))
            continue
        if (d.get("width") or 0) > 1.2:
            continue
        colour = tuple(round(c, 2) for c in (d.get("color") or ()))
        for it in items:
            if it[0] != "l":
                continue
            a, b = _pt(it[1], rot), _pt(it[2], rot)
            if math.dist(a, b) < 0.3:
                continue
            segs.add(a, b, colour)
    return arrows, segs


def _inside(p: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


#: How many segments a leader may have: a stub, a bend or two, the drop.
_LEADER_MAX_SEGMENTS = 8


def follow_leader(box: tuple[float, float, float, float], arrows: list[Arrowhead],
                  segs: Segments) -> Optional[tuple[tuple[float, float], float]]:
    """The tip of the arrow a leader carries from the label ``box``.

    ``box`` is the label's text (x0, y0, x1, y1). A leader starts within a few
    points of that text and is walked segment by segment — as long as the way
    on is unambiguous (exactly one segment of the same colour continues it) —
    until it reaches an arrowhead (its tip or its base). Several may qualify:
    a label stacked over another room's name carries two arrows, one from
    each line, so ``box`` must be the NER lines only, and the leader starting
    nearest the text wins. Returns ``(tip, distance from the text)`` or None.
    """
    zone = (box[0] - _ANCHOR_PAD_X, box[1] - _ANCHOR_PAD_Y,
            box[2] + _ANCHOR_PAD_X, box[3] + _ANCHOR_PAD_Y)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    inner = (box[0] + 1.5, box[1] + 1.5, box[2] - 1.5, box[3] - 1.5)

    def arrow_at(p):
        for a in arrows:
            if math.dist(p, a.tip) <= _TIP_TOLERANCE or math.dist(p, a.base) <= _TIP_TOLERANCE:
                return a
        return None

    best: Optional[tuple[float, tuple[float, float]]] = None
    for i in segs.starting_in(zone):
        a, b, colour = segs.segs[i]
        for near, far in ((a, b), (b, a)):
            # The leader starts at the text — beside it or on its edge, never
            # across it (a line through the words is an underline or a wall).
            if not _inside(near, zone) or _inside(near, inner):
                continue
            seen = {i}
            cur = far
            hit = None
            for _ in range(_LEADER_MAX_SEGMENTS):
                hit = arrow_at(cur)
                if hit is not None:
                    break
                nxt = [j for j in segs.at(cur) if j not in seen and segs.segs[j][2] == colour]
                if len(nxt) != 1:
                    break
                j = nxt[0]
                seen.add(j)
                ja, jb, _ = segs.segs[j]
                cur = jb if math.dist(ja, cur) <= 0.8 else ja
            if hit is None or _inside(hit.tip, zone):
                continue
            dx = max(box[0] - near[0], 0.0, near[0] - box[2])
            dy = max(box[1] - near[1], 0.0, near[1] - box[3])
            gap = math.hypot(dx, dy)
            if best is None or gap < best[0]:
                best = (gap, hit.tip)
    if best is None:
        return None
    tip = best[1]
    return tip, math.dist(tip, (cx, cy))


# ---------------------------------------------------------------------------
# Finding the rooms
# ---------------------------------------------------------------------------

def _overlap_x(a, b) -> bool:
    lo, hi = max(a.x0, b.x0), min(a.x1, b.x1)
    shorter = min(a.x1 - a.x0, b.x1 - b.x0)
    return shorter > 0 and (hi - lo) >= shorter * 0.5


def _line_below(it, items):
    """The line set directly under ``it`` (overlapping it across, touching it
    down), or None."""
    best = None
    for o in items:
        if o is it or o.page != it.page or o.rotated != it.rotated:
            continue
        if not _overlap_x(it, o):
            continue
        gap = o.y0 - it.y1
        if -it.size * 0.8 <= gap <= _LINE_GAP and o.y > it.y:
            if best is None or o.y < best.y:
                best = o
    return best


def _line_above(it, items):
    best = None
    for o in items:
        if o is it or o.page != it.page or o.rotated != it.rotated:
            continue
        if not _overlap_x(it, o):
            continue
        gap = it.y0 - o.y1
        if -it.size * 0.8 <= gap <= _LINE_GAP and o.y < it.y:
            if best is None or o.y > best.y:
                best = o
    return best


def _box(lines) -> tuple[float, float, float, float]:
    return (min(l.x0 for l in lines), min(l.y0 for l in lines),
            max(l.x1 for l in lines), max(l.y1 for l in lines))


#: A NER block symbol this close (points) to a room read from a code or a
#: label is that room's rack, not a second one: about 3 m at 1:200.
SYMBOL_IN_ROOM_PT = 40.0


def find_drawn_rooms(items: list, arrows: list[Arrowhead], segs: "Segments",
                     *, excluded=lambda it: False, symbols=()) -> list[DrawnRoom]:
    """Every NER room the sheet states, with its position.

    ``items`` are the page's text lines (``pdf_ingest.TextItem``, display
    coordinates); ``excluded(item)`` is true for text in the legend, the notes
    or the title block, which describes the notation rather than a room;
    ``symbols`` are the NER block symbols ``ner_symbol.find_ner_symbols``
    found on the page.

    A TEC code is read with the lines stacked over it (the room label and
    its area tag) as one label; a room label with no code under it is read with
    the criticality line under it. A label's lines are never read twice. A
    symbol becomes a room of its own unless it sits inside a room already
    read — then it is that room.
    """
    live = [it for it in items if not excluded(it)]
    used: set[int] = set()
    rooms: list[DrawnRoom] = []

    # -- rooms with a code ----------------------------------------------------
    for it in live:
        code = normalise_code(it.text)
        if code is None or len(it.text) > 40:
            continue
        # The label above the code: up to four lines ("Network Equipment" /
        # "Rack (NER)" / "-Placeholder", or "Network Equipment" / "Rack -
        # Non-Critical"), and the area tag under it.
        stack = [it]
        cur = it
        for _ in range(4):
            up = _line_above(cur, live)
            if up is None or normalise_code(up.text):
                break
            stack.insert(0, up)
            cur = up
        down = _line_below(it, live)
        if down is not None and re.search(r"m²|m2|sq", down.text, re.IGNORECASE):
            stack.append(down)
        for s in stack:
            used.add(id(s))
        text = " ".join(s.text.strip() for s in stack if s is not down)
        critical = criticality_from_code(code)
        words = criticality_from_words(text)
        klass = code.split("-")[0]
        evidence = [f"space code {code} printed on page {it.page} — "
                    f"{klass} is a {'critical' if critical else 'non-critical'} "
                    f"network equipment rack"]
        if words is not None and words != critical:
            evidence.append(f"the label says '{text}', the code says "
                            f"{'critical' if critical else 'non-critical'} — the code decides")
        found = follow_leader(_box(stack), arrows, segs)
        if found:
            (x, y), dist = found
            evidence.append(f"placed at the tip of the label's arrow, {dist:.0f} pt from the label")
        else:
            x, y = it.x, it.y
            evidence.append("placed at the label (it sits in the room; no arrow leaves it)")
        rooms.append(DrawnRoom(page=it.page, x=x, y=y, label_x=it.x, label_y=it.y,
                               critical=critical, code=code, source="code", text=text,
                               via_leader=bool(found), evidence=evidence))

    # -- rooms with a label only ------------------------------------------------
    for it in live:
        if id(it) in used:
            continue
        m = ROOM_LABEL_RX.match(it.text.strip())
        plain = None if m else ROOM_LABEL_PLAIN_RX.match(it.text.strip())
        if not m and not plain:
            continue
        lines = [it]
        up = _line_above(it, live)
        if up is not None and NETWORK_EQUIPMENT_LINE_RX.match(up.text):
            lines.insert(0, up)
        elif plain is not None and not plain.group("head"):
            # "Rack - Critical" with nothing over it: a rack of some other
            # kind, or a notes line — not the room label.
            continue
        m = m or plain
        tail = (m.group("tail") or "").strip()
        if not tail:
            below = _line_below(it, live)
            if below is not None and CRIT_LINE_RX.match(below.text):
                lines.append(below)
                tail = below.text.strip()
        # A code set under the label belongs to the code pass above; one that
        # was missed there (a longer line) is still honoured here.
        below_all = _line_below(lines[-1], live)
        code = normalise_code(below_all.text) if below_all is not None else None
        for s in lines:
            used.add(id(s))
        text = " ".join(s.text.strip() for s in lines)
        critical = criticality_from_code(code) if code else criticality_from_words(tail)
        evidence = [f"room label '{text}' printed on page {it.page}"]
        if critical is None:
            evidence.append("the label does not say whether the rack is critical")
        else:
            evidence.append(f"read as {'critical' if critical else 'non-critical'} from the label")
        found = follow_leader(_box(lines), arrows, segs)
        if found:
            (x, y), dist = found
            evidence.append(f"placed at the tip of the label's arrow, {dist:.0f} pt from the label")
        else:
            bx = _box(lines)
            x, y = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
            evidence.append("no arrow could be followed from the label — placed on the label; "
                            "move it onto the room")
        rooms.append(DrawnRoom(page=it.page, x=x, y=y, label_x=it.x, label_y=it.y,
                               critical=critical, code=code,
                               source="code" if code else "label", text=text,
                               via_leader=bool(found), evidence=evidence))

    # -- the NER block symbols ---------------------------------------------------
    for h in symbols:
        inside = [r for r in rooms if r.page == h.page
                  and (math.dist((r.x, r.y), (h.x, h.y)) <= SYMBOL_IN_ROOM_PT
                       or math.dist((r.label_x, r.label_y), (h.x, h.y)) <= SYMBOL_IN_ROOM_PT)]
        if inside:
            inside[0].evidence.append(
                f"the NER block symbol is drawn {math.dist((inside[0].x, inside[0].y), (h.x, h.y)):.0f} pt "
                f"from this room's label — the same rack")
            continue
        rooms.append(DrawnRoom(page=h.page, x=h.x, y=h.y, label_x=h.x, label_y=h.y,
                               critical=None, code=None, source="symbol", text="NER",
                               via_leader=False, evidence=list(h.evidence)))

    # One room per place: the same label read twice (overlapping text runs).
    out: list[DrawnRoom] = []
    for r in rooms:
        if any(o.page == r.page and math.dist((o.x, o.y), (r.x, r.y)) < 4.0 for o in out):
            continue
        out.append(r)
    out.sort(key=lambda r: (r.page, round(r.y / 20.0), r.x))
    return out
