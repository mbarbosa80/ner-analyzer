"""A synthetic venue design book for the composite map tests (5.0.0).

An invented site — buildings, roads, trees, room labels — 400 m by 198 m, cut
the way the venue design books are cut: a key plan of the level at 1:600 with the zone
grid in heavy dashed lines, a big zone letter in each cell and the sheet's
number under it, and one detail sheet per zone at 1:150 that shows its cell
plus a margin, with match lines where it continues and a title block on the
right. Every sheet is ANSI D (2448 × 1584 pt).

Because the site is invented in metres, the true place of every sheet is
known, and a test can say how far the composite put it from there.
"""
from __future__ import annotations

import random
from typing import Optional

import pymupdf

W, H = 2448.0, 1584.0
PT_M = 0.0254 / 72                    # metres per point at 1:1
KEY_MPU = 600 * PT_M                  # 1:600
DET_MPU = 150 * PT_M                  # 1:150
COLS, ROWS = 4, 3
CELL_W, CELL_H = 100.0, 66.0          # metres
SITE_W, SITE_H = COLS * CELL_W, ROWS * CELL_H
# The drawing area of every sheet (the same proportions the app assumes).
VP = (0.012 * W, 0.02 * H, 0.86 * W, 0.93 * H)
LETTERS = "ABCD"


def zone_name(col: int, row: int) -> str:
    """Rows are lettered from the bottom of the key plan, columns numbered."""
    return f"{LETTERS[ROWS - 1 - row]}{col + 1}"


def sheet_number(prefix: str, col: int, row: int) -> str:
    return f"TST-{prefix}{zone_name(col, row)}-TST-OP"


def _features(seed: int = 7):
    rnd = random.Random(seed)
    feats = []
    for _ in range(260):          # buildings and tents
        x, y = rnd.uniform(0, SITE_W), rnd.uniform(0, SITE_H)
        w, h = rnd.uniform(3, 22), rnd.uniform(3, 16)
        feats.append(("rect", (x, y, x + w, y + h), rnd.random() < 0.3))
    for _ in range(40):           # roads and paths
        pts = [(rnd.uniform(0, SITE_W), rnd.uniform(0, SITE_H))]
        for _ in range(5):
            px, py = pts[-1]
            pts.append((px + rnd.uniform(-40, 40), py + rnd.uniform(-30, 30)))
        feats.append(("poly", pts, False))
    for _ in range(300):          # trees
        feats.append(("tree", (rnd.uniform(0, SITE_W), rnd.uniform(0, SITE_H),
                               rnd.uniform(1.5, 4.5)), False))
    for i in range(120):          # room labels
        feats.append(("text", (rnd.uniform(0, SITE_W), rnd.uniform(0, SITE_H),
                               f"SPT.{i:03d}"), False))
    return feats


FEATURES = _features()


class _Pen:
    """Draws in displayed coordinates on a page that may be rotated."""

    def __init__(self, page: pymupdf.Page):
        self.page = page
        self.shape = page.new_shape()
        self.m = page.derotation_matrix

    def p(self, x, y):
        return pymupdf.Point(x, y) * self.m

    def line(self, a, b, width=0.5, color=(0.3, 0.3, 0.3)):
        self.shape.draw_line(self.p(*a), self.p(*b))
        self.shape.finish(color=color, width=width, closePath=False)

    def rect(self, x0, y0, x1, y1, fill=None, width=0.5):
        q = pymupdf.Quad(self.p(x0, y0), self.p(x1, y0), self.p(x0, y1), self.p(x1, y1))
        self.shape.draw_quad(q)
        self.shape.finish(color=(0.2, 0.2, 0.2), fill=fill, width=width)

    def circle(self, x, y, r):
        self.shape.draw_circle(self.p(x, y), r)
        self.shape.finish(color=(0.3, 0.5, 0.3), width=0.4)

    def commit(self):
        self.shape.commit()

    def text(self, x, y, s, size=6.0):
        self.page.insert_text(self.p(x, y), s, fontsize=size,
                              rotate=self.page.rotation)


def _draw_site(pen: _Pen, to_pt, mpu: float, clip) -> None:
    """Every feature of the site that falls in ``clip`` (points)."""
    x0c, y0c, x1c, y1c = clip

    def vis(x, y):
        return x0c <= x <= x1c and y0c <= y <= y1c
    texts = []
    for kind, g, filled in FEATURES:
        if kind == "rect":
            a, b = to_pt(g[0], g[1]), to_pt(g[2], g[3])
            if vis(*a) and vis(*b):
                pen.rect(a[0], a[1], b[0], b[1], fill=(0.75, 0.85, 0.95) if filled else None)
        elif kind == "poly":
            pts = [to_pt(*q) for q in g]
            for a, b in zip(pts, pts[1:]):
                if vis(*a) and vis(*b):
                    pen.line(a, b, width=1.2)
        elif kind == "tree":
            c = to_pt(g[0], g[1])
            if vis(*c):
                pen.circle(c[0], c[1], g[2] / mpu)
        elif kind == "text":
            c = to_pt(g[0], g[1])
            if vis(*c) and mpu < 0.1:
                texts.append((c, g[2]))
    pen.commit()
    for c, s in texts:
        pen.text(c[0], c[1], s)


def _dashed(pen: _Pen, a, b, width=2.76):
    """A match line: 20 pt on, 8 pt off, heavy and black."""
    (x0, y0), (x1, y1) = a, b
    L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    s = 0.0
    while s < L:
        e = min(L, s + 20)
        pen.line((x0 + ux * s, y0 + uy * s), (x0 + ux * e, y0 + uy * e), width=width,
                 color=(0, 0, 0))
        s += 28


def _new_page(doc, rotated: bool) -> pymupdf.Page:
    if rotated:
        pg = doc.new_page(width=H, height=W)
        pg.set_rotation(90)
        return pg
    return doc.new_page(width=W, height=H)


def _title_block(pen: _Pen, number: str, title: str) -> None:
    pen.rect(0.86 * W, 0.02 * H, 0.99 * W, 0.98 * H)
    pen.commit()
    pen.text(0.87 * W, 0.90 * H, "DRAWING TITLE", 7)
    pen.text(0.87 * W, 0.92 * H, title, 8)
    pen.text(0.87 * W, 0.95 * H, "DRAWING NUMBER", 7)
    pen.text(0.87 * W, 0.97 * H, number, 10)


#: Where the key plan puts the site's (0, 0), in points.
KEY_ORIGIN = (VP[0] + 120, VP[1] + 160)


def key_to_pt(x_m: float, y_m: float) -> tuple[float, float]:
    return KEY_ORIGIN[0] + x_m / KEY_MPU, KEY_ORIGIN[1] + y_m / KEY_MPU


def detail_origin(col: int, row: int) -> tuple[float, float]:
    """The site point (metres) at the top-left of a detail sheet's drawing
    area: the cell centred in it."""
    cx, cy = (col + 0.5) * CELL_W, (row + 0.5) * CELL_H
    aw, ah = (VP[2] - VP[0]) * DET_MPU, (VP[3] - VP[1]) * DET_MPU
    return cx - aw / 2, cy - ah / 2


def detail_to_pt(col: int, row: int, x_m: float, y_m: float) -> tuple[float, float]:
    ox, oy = detail_origin(col, row)
    return VP[0] + (x_m - ox) / DET_MPU, VP[1] + (y_m - oy) / DET_MPU


def make_book(path: str, *, prefix: str = "412", level: str = "LEVEL 02",
              zones: Optional[list[tuple[int, int]]] = None, rotated: bool = False,
              match_lines: bool = True, shift_m: Optional[dict] = None) -> list[dict]:
    """Write the book and return the page facts the app would hold for it:
    ``number``, ``sheet_number``, ``level``, ``key_plan``, ``mpu``, plus
    ``zone`` (col, row) for the detail sheets.

    ``shift_m`` — ``{(col, row): (dx, dy)}``: draw that sheet's match lines
    off by so many metres (a book whose grid is not regular), to prove the
    correlation check overrules them."""
    zones = zones if zones is not None else [(c, r) for r in range(ROWS) for c in range(COLS)]
    doc = pymupdf.open()
    facts = []
    # Key plan.
    pg = _new_page(doc, rotated)
    pen = _Pen(pg)
    _draw_site(pen, key_to_pt, KEY_MPU, VP)
    for c in range(1, COLS):
        _dashed(pen, key_to_pt(c * CELL_W, -5), key_to_pt(c * CELL_W, SITE_H + 5))
    for r in range(1, ROWS):
        _dashed(pen, key_to_pt(-5, r * CELL_H), key_to_pt(SITE_W + 5, r * CELL_H))
    pen.commit()
    for (c, r) in [(c, r) for r in range(ROWS) for c in range(COLS)]:
        x, y = key_to_pt((c + 0.35) * CELL_W, (r + 0.55) * CELL_H)
        pen.text(x, y, zone_name(c, r), 48)
        if (c, r) in zones:
            pen.text(x - 10, y + 30, f"{prefix}{zone_name(c, r)}-TST-OP", 14)
    _title_block(pen, f"TST-{prefix[:2]}1-TST-OP", f"KEY ENLARGED PLAN - {level}")
    facts.append({"number": 1, "sheet_number": f"TST-{prefix[:2]}1-TST-OP", "level": level,
                  "key_plan": True, "mpu": KEY_MPU})
    for i, (c, r) in enumerate(zones):
        pg = _new_page(doc, rotated)
        pen = _Pen(pg)
        to_pt = (lambda xm, ym, _c=c, _r=r: detail_to_pt(_c, _r, xm, ym))
        _draw_site(pen, to_pt, DET_MPU, VP)
        if match_lines:
            dx, dy = (shift_m or {}).get((c, r), (0.0, 0.0))
            if c > 0:
                a = to_pt(c * CELL_W + dx, -1e3)
                _dashed(pen, (a[0], VP[1]), (a[0], VP[3]))
            if c < COLS - 1:
                a = to_pt((c + 1) * CELL_W + dx, -1e3)
                _dashed(pen, (a[0], VP[1]), (a[0], VP[3]))
            if r > 0:
                a = to_pt(-1e3, r * CELL_H + dy)
                _dashed(pen, (VP[0], a[1]), (VP[2], a[1]))
            if r < ROWS - 1:
                a = to_pt(-1e3, (r + 1) * CELL_H + dy)
                _dashed(pen, (VP[0], a[1]), (VP[2], a[1]))
            pen.commit()
        sn = sheet_number(prefix, c, r)
        _title_block(pen, sn, f"ENLARGED PLAN - {level}")
        facts.append({"number": i + 2, "sheet_number": sn, "level": level,
                      "key_plan": False, "mpu": DET_MPU, "zone": (c, r)})
    doc.save(path)
    doc.close()
    return facts
