"""The NER *symbol* the newer venue design books draw (2.15.0).

From the 3.x books on (VCC Softball, October 2026) the design team stopped
writing a space code at every rack. A rack that is not a room gets a CAD
block instead: a small filled square (about 1 m on the sheet — 14 to 20 pt
at the usual 1:200) with the word **NER** inside, inside a dashed rectangle
in the functional area it serves. The word is not text: AutoCAD plots its
SHX lettering as strokes, so ``page.get_text()`` sees nothing and the
extractor of 2.14 found none of them. On the VCC book: 15 such blocks on 13
sheets, four printed labels, and not one "(NER)" in the text layer.

So the block is recognised by its *shape*. The reference block (page 27 of
``VCC_400_SBL_O.pdf``, the one in the dugout) has 55 straight strokes — the
outlines of N, E and R — and every other block in the book is the same
block inserted again, at another size and sometimes turned. ``TEMPLATE`` is
those 55 strokes with the square mapped onto [-1, 1]². A candidate is any
near-square filled rectangle of a plausible size holding a few dozen tiny
strokes; its strokes are aligned the same way, tried in the four flips that
alignment leaves open (either way along the axis, mirrored or not), and
compared with the template by the symmetric Chamfer distance of the stroke
end- and mid-points, after both are brought into one frame (centred,
turned onto the lettering's long axis, scaled by its spread — so a block
inserted at any angle or size reads the same). A block the same as the
template scores 0; the book's other NER blocks score up to 0.05; nothing
else on the book scores under 0.16.

Colour is recorded and decides nothing — the rule since the first real
book (see ``pdf_ingest``): never classify on colour alone. The symbol says
"a NER is here" and nothing about criticality, so the caller creates it
non-critical with the criticality *pending* (Marcelo, 1 Oct 2026: "coloca
NER não crítica e depois eu mudo se precisar").
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: The 55 strokes of the reference block, each ``(x0, y0, x1, y1)`` with the
#: block's square mapped onto [-1, 1]² (centre at the origin).
TEMPLATE: list[tuple[float, float, float, float]] = [
    (0.403, -0.148, 0.369, -0.148), (0.369, -0.148, 0.369, 0.087), (0.369, 0.087, 0.217, -0.148),
    (0.217, -0.148, 0.166, -0.148), (0.166, -0.148, 0.166, 0.155), (0.166, 0.155, 0.217, 0.155),
    (0.217, 0.155, 0.217, -0.082), (0.217, -0.082, 0.369, 0.155), (0.369, 0.155, 0.403, 0.155),
    (0.403, 0.155, 0.403, -0.148), (0.099, -0.148, -0.121, -0.148), (-0.121, -0.148, -0.121, -0.115),
    (-0.121, -0.115, 0.065, -0.115), (0.065, -0.115, 0.065, -0.014), (0.065, -0.014, -0.104, -0.014),
    (-0.104, -0.014, -0.104, 0.019), (-0.104, 0.019, 0.065, 0.019), (0.065, 0.019, 0.065, 0.122),
    (0.065, 0.122, -0.104, 0.122), (-0.104, 0.122, -0.104, 0.155), (-0.104, 0.155, 0.099, 0.155),
    (0.099, 0.155, 0.099, -0.148), (-0.172, -0.148, -0.206, -0.148), (-0.206, -0.148, -0.206, -0.014),
    (-0.206, -0.014, -0.257, -0.014), (-0.257, -0.014, -0.273, -0.014), (-0.273, -0.014, -0.29, -0.03),
    (-0.29, -0.03, -0.307, -0.047), (-0.307, -0.047, -0.341, -0.082), (-0.341, -0.082, -0.375, -0.148),
    (-0.375, -0.148, -0.426, -0.148), (-0.426, -0.148, -0.375, -0.066), (-0.375, -0.066, -0.341, -0.03),
    (-0.341, -0.03, -0.324, -0.014), (-0.324, -0.014, -0.358, 0.003), (-0.358, 0.003, -0.392, 0.019),
    (-0.392, 0.019, -0.409, 0.038), (-0.409, 0.038, -0.409, 0.071), (-0.409, 0.071, -0.409, 0.104),
    (-0.409, 0.104, -0.392, 0.122), (-0.392, 0.122, -0.375, 0.139), (-0.375, 0.139, -0.358, 0.139),
    (-0.358, 0.139, -0.307, 0.155), (-0.307, 0.155, -0.172, 0.155), (-0.172, 0.155, -0.172, -0.148),
    (-0.206, 0.019, -0.206, 0.122), (-0.206, 0.122, -0.307, 0.122), (-0.307, 0.122, -0.324, 0.122),
    (-0.324, 0.122, -0.358, 0.104), (-0.358, 0.104, -0.358, 0.087), (-0.358, 0.087, -0.375, 0.071),
    (-0.375, 0.071, -0.358, 0.054), (-0.358, 0.054, -0.341, 0.019), (-0.341, 0.019, -0.29, 0.019),
    (-0.29, 0.019, -0.206, 0.019),
]

#: The block's square, in points, on the sheet: 6 pt would be 1.2 m at 1:50
#: … 30 pt is 2 m at 1:200 or 6 m at 1:50. Anything larger is a room.
MIN_SIDE_PT = 6.0
MAX_SIDE_PT = 30.0
#: How far from square the fill may be (width/height).
MAX_ASPECT = 1.3
#: A lettering stroke is tiny next to its block.
MAX_STROKE_FRACTION = 0.45
#: Stroke counts that can still be the word: the template has 55; a block
#: plotted twice over itself has them twice (collapsed before counting), one
#: with a glyph or two lost to clipping has a few less.
MIN_STROKES = 40
MAX_STROKES = 75
#: The shape distance at which a block is the symbol. Units: the spread of
#: the lettering along its axis (about 1.3 pt on a 14 pt block, so 0.10 is
#: an eighth of a point). The VCC book's nineteen blocks score 0.002 to
#: 0.05 — the two turned 45° and crossed by other lines the highest — and
#: no other block of the book (toilet, COW, seating symbols) scores under
#: 0.16.
MAX_DISTANCE = 0.10


@dataclass
class SymbolHit:
    """A NER block found on the sheet, in display coordinates."""
    page: int
    x: float
    y: float
    #: The block's side, in points (display space).
    side: float
    #: The shape distance from the template (0 = identical).
    distance: float
    #: How many distinct strokes the block held.
    strokes: int
    #: The fill colour as drawn, ``#rrggbb`` or None.
    colour: Optional[str]
    evidence: list[str] = field(default_factory=list)


def _points(segs: Iterable[tuple[float, float, float, float]]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for x0, y0, x1, y1 in segs:
        pts.append((x0, y0))
        pts.append((x1, y1))
        pts.append(((x0 + x1) / 2, (y0 + y1) / 2))
    return pts


def _align(segs: Iterable[tuple[float, float, float, float]]) -> list[tuple[float, float]]:
    """The strokes' end- and mid-points brought into a canonical frame: centred
    on their centroid, turned so the lettering's long axis (the first
    principal axis of the point cloud) lies along x, and scaled by the
    spread along that axis. Lettering plotted at any angle, at any size inside its
    block, comes out the same — the VCC book has blocks turned by a quarter
    turn and by odd angles, and blocks of 14 to 20 pt holding the same
    letters.
    """
    pts = _points(segs)
    if len(pts) < 3:
        return []
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    c, s = math.cos(-theta), math.sin(-theta)
    turned = [((p[0] - mx) * c - (p[1] - my) * s, (p[0] - mx) * s + (p[1] - my) * c) for p in pts]
    # The unit is the spread along that axis (its standard deviation), not
    # the farthest point: one stray stroke at a corner of the block would
    # otherwise set the scale and shrink the lettering to a third.
    span = math.sqrt(sum(q[0] ** 2 for q in turned) / len(turned)) or 1.0
    return [(q[0] / span, q[1] / span) for q in turned]


_TEMPLATE_POINTS = _align(TEMPLATE)

#: Once aligned, a block can still read the other way along its axis or be
#: mirrored: the four sign choices.
_FLIPS: list[Callable[[float, float], tuple[float, float]]] = [
    lambda x, y: (x, y), lambda x, y: (-x, -y), lambda x, y: (-x, y), lambda x, y: (x, -y),
]


def _chamfer(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Mean distance from each point of ``a`` to its nearest point of ``b``."""
    if not a or not b:
        return math.inf
    total = 0.0
    for p in a:
        best = math.inf
        for q in b:
            d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
            if d < best:
                best = d
        total += math.sqrt(best)
    return total / len(a)


def _best_flip(pts: list[tuple[float, float]]) -> tuple[float, list[tuple[float, float]]]:
    best = (math.inf, pts)
    for flip in _FLIPS:
        turned = [flip(x, y) for x, y in pts]
        d = max(_chamfer(turned, _TEMPLATE_POINTS), _chamfer(_TEMPLATE_POINTS, turned))
        if d < best[0]:
            best = (d, turned)
    return best


#: A stroke none of whose points comes this close to the template is not
#: lettering: a dash of the boundary that runs through the block, a wall.
_OUTLIER_DISTANCE = 0.2
_TRIM_ROUNDS = 3


def shape_distance(segs: list[tuple[float, float, float, float]]
                   ) -> tuple[float, list[tuple[float, float, float, float]]]:
    """How far a block's strokes sit from the template once both are aligned
    (``_align``), in the best of the four flips: the larger of the two one-way
    Chamfer means, so a block that holds the template *and* more, or less, is
    penalised. Units: half the lettering's length.

    Strokes that are not lettering — on the VCC book the dashes of a boundary
    cross one block, and a block turned 45° picks up two strokes of the room
    beside it — would pull the alignment off, so after each alignment every
    stroke with no point near the template is dropped and the rest aligned
    again, a few rounds at most. Returns the distance and the strokes kept.
    """
    if len(segs) < 3:
        return math.inf, []
    kept = list(segs)
    d, aligned = _best_flip(_align(kept))
    for _ in range(_TRIM_ROUNDS):
        inliers: list[tuple[float, float, float, float]] = []
        for i, seg in enumerate(kept):
            trio = aligned[3 * i:3 * i + 3]
            near = min(min(math.dist(p, q) for q in _TEMPLATE_POINTS) for p in trio)
            if near <= _OUTLIER_DISTANCE:
                inliers.append(seg)
        if len(inliers) == len(kept) or len(inliers) < 3:
            break
        d2, aligned2 = _best_flip(_align(inliers))
        if d2 >= d:
            break
        d, aligned, kept = d2, aligned2, inliers
    return d, kept


def _hex(colour) -> Optional[str]:
    if not colour:
        return None
    try:
        r, g, b = (int(round(max(0.0, min(1.0, c)) * 255)) for c in colour[:3])
    except (TypeError, ValueError):
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def normalise_strokes(box, strokes: list[dict]) -> list[tuple[float, float, float, float]]:
    """The straight segments of ``strokes`` mapped onto the block's [-1, 1]²,
    the same stroke drawn twice (a block plotted over itself) kept once."""
    cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    hx, hy = max(box.width / 2, 1e-6), max(box.height / 2, 1e-6)
    seen: set[tuple[float, float, float, float]] = set()
    out: list[tuple[float, float, float, float]] = []
    for d in strokes:
        for it in d.get("items") or ():
            if it[0] != "l":
                continue
            a, b = it[1], it[2]
            seg = (round((a.x - cx) / hx, 3), round((a.y - cy) / hy, 3),
                   round((b.x - cx) / hx, 3), round((b.y - cy) / hy, 3))
            rev = (seg[2], seg[3], seg[0], seg[1])
            if seg in seen or rev in seen:
                continue
            seen.add(seg)
            out.append(seg)
    return out


def find_ner_symbols(drawings: list[dict], rot, page_no: int, *,
                     excluded_point: Callable[[float, float], bool] = lambda x, y: False
                     ) -> list[SymbolHit]:
    """Every NER block on a page.

    ``drawings`` is ``page.get_drawings()`` (unrotated coordinates), ``rot``
    the page's rotation matrix, so the hits come out where the text and the
    markers are. ``excluded_point(x, y)`` (display coordinates) is true inside
    the legend or the title block, where the symbol is explained, not placed.
    """
    fills: list[dict] = []
    grid: defaultdict[tuple[int, int], list[dict]] = defaultdict(list)
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        if d.get("fill") is not None:
            w, h = r.width, r.height
            if (MIN_SIDE_PT <= w <= MAX_SIDE_PT and MIN_SIDE_PT <= h <= MAX_SIDE_PT
                    and max(w, h) / max(min(w, h), 1e-6) <= MAX_ASPECT):
                fills.append(d)
            continue
        if d.get("color") is None:
            continue
        if max(r.width, r.height) <= MAX_SIDE_PT * MAX_STROKE_FRACTION:
            grid[(int(r.x0 // 8), int(r.y0 // 8))].append(d)
    hits: list[SymbolHit] = []
    for f in fills:
        box = f["rect"]
        limit = max(box.width, box.height) * MAX_STROKE_FRACTION
        inner: list[dict] = []
        for gx in range(int(box.x0 // 8) - 1, int(box.x1 // 8) + 2):
            for gy in range(int(box.y0 // 8) - 1, int(box.y1 // 8) + 2):
                for d in grid.get((gx, gy), ()):
                    r = d["rect"]
                    if max(r.width, r.height) <= limit and box.contains(r):
                        inner.append(d)
        if len(inner) < MIN_STROKES:
            continue
        # The lettering is one colour; a dash of another colour that crosses
        # the block (page 10 of the VCC book, grey over black) is not part of it.
        by_colour: defaultdict[tuple, list[dict]] = defaultdict(list)
        for d in inner:
            by_colour[tuple(round(c, 2) for c in (d.get("color") or ()))].append(d)
        inner = max(by_colour.values(), key=len)
        segs = normalise_strokes(box, inner)
        if not MIN_STROKES <= len(segs) <= MAX_STROKES:
            continue
        dist, kept = shape_distance(segs)
        if dist > MAX_DISTANCE or not MIN_STROKES <= len(kept) <= MAX_STROKES:
            continue
        segs = kept
        centre = box.tl + (box.br - box.tl) * 0.5
        q = centre * rot
        x, y = float(q.x), float(q.y)
        if excluded_point(x, y):
            continue
        colour = _hex(f.get("fill"))
        side = max(box.width, box.height)
        hits.append(SymbolHit(
            page=page_no, x=x, y=y, side=side, distance=dist, strokes=len(segs), colour=colour,
            evidence=[f"the NER block symbol on page {page_no}: a {side:.0f} pt square with "
                      f"'NER' drawn as {len(segs)} strokes, shape distance {dist:.3f} from the "
                      f"reference block",
                      f"block filled {colour or 'with no colour'} — colour decides nothing",
                      "the symbol does not say whether the rack is critical"]))
    # The same block twice at one place (two overlapping inserts) is one NER.
    out: list[SymbolHit] = []
    for h in sorted(hits, key=lambda h: h.distance):
        if any(math.dist((o.x, o.y), (h.x, h.y)) < max(o.side, h.side) * 0.75 for o in out):
            continue
        out.append(h)
    out.sort(key=lambda h: (round(h.y / 20.0), h.x))
    return out
