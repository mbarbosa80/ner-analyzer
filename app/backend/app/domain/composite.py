"""The composite map of one level of one book (5.0.0).

A venue design book cuts each level into detail sheets — ``412A1``, ``412A2``
… — that continue one another across match lines. Marcelo, 30 Oct 2026: *"uma
página nada mais é que a continuidade da outra, e se a gente conseguir montar
isso tudo num mapa só, sobrepondo essas páginas, o trabalho de localização das
NRs fica muito mais fácil"*. This module lays the detail sheets of one group
(one level of one book — never two series, never a key plan) on one plane.

Nothing here touches the database: :func:`align_book` reads the PDF and the
page facts it is handed and returns plain data, so it runs in a child
interpreter like the other heavy readers (``isolate.run``).

How a sheet is placed
---------------------
Every sheet gets a translation ``(tx, ty)`` in its own PDF points and a scale
``s`` to the group's frame. A point ``(x, y)`` of the sheet — in the rotated,
displayed coordinates every marker is stored in — lands at::

    X = s * (x + tx) - x0        Y = s * (y + ty) - y0

on the composite, in points of the group's most common scale (``mpu``
metres per point). ``x0, y0`` move the frame so the map starts at 0.

Two independent measurements, as the feasibility test of 30 Oct 2026 showed
was needed (on two of the books the first one alone put 21 sheets in the wrong
place, silently):

* **A — match lines.** The heavy black dashed lines a sheet prints where it
  continues, read against the grid the key plan draws with the same lines and
  the zone letter of the sheet number (``412A1`` → zone ``A1``). Exact when the
  book follows that pattern.
* **B — correlation.** The edge image of the sheet against the key plan around
  the label the key plan prints for it (``411B3-CTR-OP``, or the zone letter),
  coarse then fine. Works on any book whose key plan shows the linework.

When both are measured and disagree by more than 2 m, B is kept (A assumes a
regular grid; the books that break it are the ones where they disagree). Then
sheets that overlap are correlated against each other at full detail and all
translations are solved together by least squares, dropping the pair
measurements that disagree (:func:`_refine`).

What a sheet is told
--------------------
``state``: ``confirmed`` when A and B agree within 1 m or an overlapping
neighbour confirms it; ``unconfirmed`` otherwise (the services add
``contradicted`` from the spaces two neighbouring sheets share);
``not_aligned`` when neither method could place it — it is listed, never
drawn. The map is a picture to decide on, not a measurement: it changes no
distance the analysis computes.
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

#: Sheets whose A and B placements differ by more than this (m) keep B.
A_B_REJECT_M = 2.0
#: A and B within this (m) confirm each other.
A_B_CONFIRM_M = 1.0
#: The weakest correlation peak (peak / std) B is trusted with to overrule A.
B_OVERRULE_CONF = 20.0
#: Neighbour check: two sheets that overlap are compared directly, at full
#: detail, within this window (m) of where they were placed. A wider window
#: was tried on 30 Oct 2026 and found the wrong match on 6 of 17 neighbour
#: pairs of the test book — and then moved good sheets 7 to 11 m to fit it.
#: Within 4 m it found the right one on every pair, from up to 3.5 m off.
REFINE_SEARCH_M = 4.0
REFINE_PX_PER_M = 6.0
#: The weakest peak a neighbour measurement is kept with (false peaks on the
#: test book stayed under 21).
REFINE_MIN_CONF = 25.0
#: The least overlap (m) two sheets must share to be compared.
REFINE_MIN_OVERLAP_M = 3.0
#: A pair measurement left this far (m) from the joint solution is dropped.
REFINE_DROP_M = 0.6
#: The composite PDF's largest side, in points. PDF readers refuse pages past
#: 200 inches (14,400 pt); the report scales a larger map down to fit.
PDF_MAX_SIDE = 14400.0
#: Tiles: square, this many pixels; zoom level z draws 2**z / 64 px per point.
TILE_PX = 512
TILE_ZMAX = 9


def tile_scale(z: int) -> float:
    """Pixels per composite point at zoom level ``z`` (z=6 → 1 px/pt)."""
    return (2.0 ** z) / 64.0


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

_PREFIX_RX = re.compile(r"-(\d{3}M?)\s?[A-Z]")


def sheet_prefix(sheet_number: Optional[str]) -> Optional[str]:
    """``VVV-412A1-XXX-OP`` → ``412``: the level part of a drawing number.
    The feasibility test found the title-block level wrong on seven books
    ("82 m²", "1 / 420 C5-VVO-O"); the drawing number never was."""
    m = _PREFIX_RX.search(sheet_number or "")
    return m.group(1) if m else None


def group_key(sheet_number: Optional[str], level: Optional[str]) -> str:
    """The group a detail sheet belongs to: its drawing-number prefix, else its
    level, else one group for every sheet that says neither."""
    pfx = sheet_prefix(sheet_number)
    if pfx:
        return pfx
    if level:
        return level.strip().upper()
    return "(no level)"


@dataclass
class _Page:
    number: int
    sheet_number: str
    level: Optional[str]
    key_plan: bool
    mpu: Optional[float]


def _pages(pages: list[dict]) -> list[_Page]:
    return [_Page(int(p["number"]), (p.get("sheet_number") or "").strip(),
                  p.get("level"), bool(p.get("key_plan")),
                  float(p["mpu"]) if p.get("mpu") else None) for p in pages]


def plan_groups(pages: list[dict]) -> list[dict]:
    """What :func:`align_book` would build, without reading the PDF: one entry
    per group with its sheets and the sheets it must leave out (no scale)."""
    out: dict[str, dict] = {}
    for pg in _pages(pages):
        if pg.key_plan:
            continue
        g = out.setdefault(group_key(pg.sheet_number, pg.level),
                           {"sheets": [], "no_scale": [], "levels": collections.Counter()})
        if pg.level:
            g["levels"][pg.level] += 1
        (g["sheets"] if pg.mpu else g["no_scale"]).append(pg.number)
    res = []
    for key, g in sorted(out.items()):
        level = g["levels"].most_common(1)[0][0] if g["levels"] else None
        res.append({"key": key, "level": level, "label": group_label(key, level),
                    "pages": sorted(g["sheets"]), "no_scale": sorted(g["no_scale"])})
    return res


def group_label(key: str, level: Optional[str]) -> str:
    """``412 · LEVEL 02`` — the drawing-number prefix and the level, the way
    the design team names it."""
    if level and level.strip().upper() != key:
        return f"{key} · {level}"
    return key


# ---------------------------------------------------------------------------
# Reading the PDF
# ---------------------------------------------------------------------------

def viewport(rect) -> tuple[float, float, float, float]:
    """The drawing area of a sheet: left of the title block, above the
    disclaimer strip — the layout every sheet of the event shares (title block on the
    right 14 %, disclaimer along the foot)."""
    x0, y0, w, h = rect.x0, rect.y0, rect.width, rect.height
    return (x0 + 0.012 * w, y0 + 0.02 * h, x0 + 0.86 * w, y0 + 0.93 * h)


class _Book:
    """One open PDF with the per-page reads cached."""

    def __init__(self, path: str):
        import pymupdf
        self.pymupdf = pymupdf
        self.doc = pymupdf.open(path)
        self._words: dict[int, list] = {}
        self._lines: dict[int, tuple] = {}

    def page(self, number: int):
        return self.doc[number - 1]

    def words(self, number: int) -> list:
        if number not in self._words:
            pg = self.page(number)
            rm = pg.rotation_matrix
            self._words[number] = [(self.pymupdf.Rect(w[:4]) * rm, w[4])
                                   for w in pg.get_text("words")]
        return self._words[number]

    def match_lines(self, number: int) -> tuple[list[int], list[int], list[float]]:
        """Heavy dark dashed lines that cross the drawing (match lines on a
        detail sheet, the grid on a key plan): their y (horizontal) and x
        (vertical) positions, and the span they cover."""
        if number in self._lines:
            return self._lines[number]
        pg = self.page(number)
        rm = pg.rotation_matrix
        H = collections.defaultdict(lambda: [0.0, 1e9, -1e9, 0])
        V = collections.defaultdict(lambda: [0.0, 1e9, -1e9, 0])
        for d in pg.get_drawings():
            col, w = d.get("color"), d.get("width") or 0
            if col is None or max(col) > 0.15 or w < 2.5:
                continue
            for it in d["items"]:
                if it[0] != "l":
                    continue
                p1, p2 = it[1] * rm, it[2] * rm
                if abs(p1.y - p2.y) < 0.5:
                    a = H[round(p1.y)]
                    a[0] += abs(p1.x - p2.x); a[1] = min(a[1], p1.x, p2.x)
                    a[2] = max(a[2], p1.x, p2.x); a[3] += 1
                elif abs(p1.x - p2.x) < 0.5:
                    a = V[round(p1.x)]
                    a[0] += abs(p1.y - p2.y); a[1] = min(a[1], p1.y, p2.y)
                    a[2] = max(a[2], p1.y, p2.y); a[3] += 1

        def keep(D):
            # Long, broken (dashed: 50–85 % ink), made of many pieces.
            return {k: a for k, a in D.items()
                    if a[2] - a[1] > 400 and a[3] >= 8 and 0.5 < a[0] / (a[2] - a[1]) < 0.85}
        H, V = keep(H), keep(V)
        span = [min([a[1] for a in H.values()] + [1e9]), max([a[2] for a in H.values()] + [-1e9]),
                min([a[1] for a in V.values()] + [1e9]), max([a[2] for a in V.values()] + [-1e9])]
        self._lines[number] = (sorted(H), sorted(V), span)
        return self._lines[number]

    def edges(self, number: int, clip, zoom: float):
        """The sheet's edge image over ``clip`` (display coordinates) at
        ``zoom`` pixels per point, mean-removed — what correlation compares."""
        import numpy as np
        pg = self.page(number)
        # The clip is in displayed (rotated) coordinates; get_pixmap renders
        # the displayed page, so the two agree.
        pix = pg.get_pixmap(matrix=self.pymupdf.Matrix(zoom, zoom), clip=clip,
                            colorspace=self.pymupdf.csGRAY, alpha=False)
        a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).astype(np.float32)
        gx = np.zeros_like(a)
        gy = np.zeros_like(a)
        gx[:, 1:] = np.abs(np.diff(a, axis=1))
        gy[1:, :] = np.abs(np.diff(a, axis=0))
        e = np.minimum(gx + gy, 60.0)
        return e - e.mean()


def _phase_corr(big, small) -> tuple[int, int, float]:
    """Where ``small`` sits inside ``big`` (pixels) and how sharp the peak is
    (peak over the standard deviation of the correlation surface)."""
    import numpy as np
    Hh, Ww = big.shape
    b = np.zeros((Hh, Ww), np.float32)
    h, w = min(small.shape[0], Hh), min(small.shape[1], Ww)
    b[:h, :w] = small[:h, :w]
    win = np.outer(np.hanning(Hh), np.hanning(Ww)).astype(np.float32)
    Fa, Fb = np.fft.rfft2(big * win), np.fft.rfft2(b)
    R = Fa * np.conj(Fb)
    R /= np.abs(R) + 1e-6
    r = np.fft.irfft2(R, s=(Hh, Ww))
    iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)
    conf = float(r[iy, ix] / (r.std() + 1e-9))
    if iy > Hh // 2:
        iy -= Hh
    if ix > Ww // 2:
        ix -= Ww
    return int(ix), int(iy), conf


def _pad_to(big, small):
    import numpy as np
    if small.shape[0] > big.shape[0] or small.shape[1] > big.shape[1]:
        pad = np.zeros((max(big.shape[0], small.shape[0]), max(big.shape[1], small.shape[1])),
                       np.float32)
        pad[:big.shape[0], :big.shape[1]] = big
        return pad
    return big


# ---------------------------------------------------------------------------
# Method A and B
# ---------------------------------------------------------------------------

def _key_grid(book: _Book, key: _Page) -> Optional[dict]:
    """The grid a key plan draws with match lines, and which cell each big
    zone letter (``A1``, ``D4``) sits in."""
    KH, KV, _ = book.match_lines(key.number)
    if not KH or not KV:
        return None
    zones = {}
    for r, t in book.words(key.number):
        if re.fullmatch(r"[A-Z]\d", t) and r.width > 40:
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            zones[t] = (sum(1 for v in KV if v < cx), sum(1 for h in KH if h < cy))
    if not zones:
        return None
    return {"page": key.number, "mpu": key.mpu, "H": KH, "V": KV, "zones": zones}


def _method_a(book: _Book, grid: dict, sheet: _Page) -> Optional[dict]:
    zm = re.search(r"\d{3}([A-Z]\d)-", sheet.sheet_number or "")
    if not zm or zm.group(1) not in grid["zones"] or not sheet.mpu:
        return None
    ratio = grid["mpu"] / sheet.mpu
    col, row = grid["zones"][zm.group(1)]
    KH, KV = grid["H"], grid["V"]
    H, V, span = book.match_lines(sheet.number)
    if not H and not V:
        return None
    mid_x, mid_y = (span[0] + span[1]) / 2, (span[2] + span[3]) / 2
    ox = [(KV[col - 1] if x < mid_x else KV[col]) * ratio - x for x in V
          if (x < mid_x and col > 0) or (x >= mid_x and col < len(KV))]
    oy = [(KH[row - 1] if y < mid_y else KH[row]) * ratio - y for y in H
          if (y < mid_y and row > 0) or (y >= mid_y and row < len(KH))]
    if not ox or not oy:
        return None
    tx, ty = sum(ox) / len(ox), sum(oy) / len(oy)
    clip = ((KV[col - 1] * ratio - tx) if col > 0 else span[0],
            (KH[row - 1] * ratio - ty) if row > 0 else span[2],
            (KV[col] * ratio - tx) if col < len(KV) else span[1],
            (KH[row] * ratio - ty) if row < len(KH) else span[3])
    return {"tx": tx, "ty": ty, "clip": clip,
            "residual_m": round(max(max(ox) - min(ox), max(oy) - min(oy)) * sheet.mpu, 3)}


def _label_on_key(book: _Book, keys: list[_Page], sheet: _Page):
    sn = sheet.sheet_number or ""
    m = re.search(r"(\d{3}[A-Z0-9]*?)-", sn)
    frag = m.group(1) if m else None
    zm = re.search(r"\d{3}([A-Z]\d+)", sn)
    zone = zm.group(1) if zm else None
    for k in keys:
        best = None
        for r, t in book.words(k.number):
            if frag and t.startswith(frag) and (best is None or r.height * r.width >
                                               best.height * best.width):
                best = r
        if best is not None:
            return k, best, "sheet number on the key plan"
    for k in keys:
        cands = [r for r, t in book.words(k.number) if zone and t == zone and r.width > 20]
        if len(cands) == 1:
            return k, cands[0], "zone letter on the key plan"
    return None


def _method_b(book: _Book, keys: list[_Page], sheet: _Page) -> tuple[Optional[dict], str]:
    lab = _label_on_key(book, keys, sheet)
    if not lab:
        return None, "the key plan prints no label for this sheet"
    key, lrect, how = lab
    P = book.pymupdf
    kpg, dpg = book.page(key.number), book.page(sheet.number)
    vp = P.Rect(*viewport(dpg.rect))
    ratio = key.mpu / sheet.mpu
    fw, fh = vp.width / ratio, vp.height / ratio        # the sheet's footprint on the key plan
    cx, cy = (lrect.x0 + lrect.x1) / 2, (lrect.y0 + lrect.y1) / 2
    res = None
    conf = 0.0
    for px_per_m, margin in ((1.5, 1.0), (6.0, 0.08)):
        if res is None:
            kclip = P.Rect(cx - fw * (0.5 + margin), cy - fh * (0.5 + margin),
                           cx + fw * (0.5 + margin), cy + fh * (0.5 + margin))
        else:
            gx0, gy0 = res
            kclip = P.Rect(gx0 - fw * margin, gy0 - fh * margin,
                           gx0 + fw * (1 + margin), gy0 + fh * (1 + margin))
        kclip &= kpg.rect
        if kclip.is_empty:
            return None, "the label sits at the edge of the key plan"
        big = book.edges(key.number, kclip, px_per_m * key.mpu)
        small = book.edges(sheet.number, vp, px_per_m * sheet.mpu)
        big = _pad_to(big, small)
        ix, iy, conf = _phase_corr(big, small)
        res = (kclip.x0 + ix / (px_per_m * key.mpu), kclip.y0 + iy / (px_per_m * key.mpu))
    gx0, gy0 = res
    return ({"tx": gx0 * ratio - vp.x0, "ty": gy0 * ratio - vp.y0, "conf": round(conf, 1),
             "key_page": key.number, "label_by": how,
             "clip": (vp.x0, vp.y0, vp.x1, vp.y1)}, "")


# ---------------------------------------------------------------------------
# Neighbour refinement
# ---------------------------------------------------------------------------

def _rect(P, t: dict):
    v = t["view"]
    return P.Rect(v[0] + t["tx"], v[1] + t["ty"], v[2] + t["tx"], v[3] + t["ty"])


def _measure(book: _Book, i: int, j: int, ti: dict, tj: dict, mpu: float, search_m: float,
             px_per_m: float):
    """Measured ``t_i - t_j`` (points) from the content two sheets share."""
    P = book.pymupdf
    m = search_m / mpu
    Ri, Rj = _rect(P, ti), _rect(P, tj)
    O = P.Rect(Ri) & P.Rect(Rj)
    if O.is_empty or O.width < 4 / mpu or O.height < 4 / mpu:
        O = P.Rect(Ri.x0 - m, Ri.y0 - m, Ri.x1 + m, Ri.y1 + m) & Rj
        if O.is_empty or O.width < 4 / mpu or O.height < 4 / mpu:
            return None
    vpi, vpj = P.Rect(*ti["view"]), P.Rect(*tj["view"])
    si = P.Rect(O.x0 - ti["tx"], O.y0 - ti["ty"], O.x1 - ti["tx"], O.y1 - ti["ty"]) & vpi
    if si.is_empty or si.width * mpu < 4 or si.height * mpu < 4:
        return None
    bj = P.Rect(si.x0 + ti["tx"] - tj["tx"] - m, si.y0 + ti["ty"] - tj["ty"] - m,
                si.x1 + ti["tx"] - tj["tx"] + m, si.y1 + ti["ty"] - tj["ty"] + m) & vpj
    if bj.is_empty or bj.width < si.width * 0.3 or bj.height < si.height * 0.3:
        return None
    z = px_per_m * mpu
    small = book.edges(i, si, z)
    big = book.edges(j, bj, z)
    if small.std() < 1 or big.std() < 1:
        return None
    big = _pad_to(big, small)
    ix, iy, conf = _phase_corr(big, small)
    return ((bj.x0 + ix / z) - si.x0, (bj.y0 + iy / z) - si.y0, conf)


def _refine(book: _Book, sheets: dict[int, dict]) -> dict:
    """Compare overlapping neighbours and solve every translation together.

    Each pair is measured only near where the sheets already are
    (``REFINE_SEARCH_M``): the check confirms a placement and corrects it by a
    few metres at most; it never relocates a sheet. Sheets placed by match
    lines do not move; a pair measurement the joint solution cannot honour is
    dropped. A sheet with at least one neighbour left agreeing is confirmed."""
    import numpy as np
    P = book.pymupdf
    pages = sorted(sheets)
    edges = []
    for a in range(len(pages)):
        for b in range(a + 1, len(pages)):
            i, j = pages[a], pages[b]
            ti, tj = sheets[i], sheets[j]
            if abs(ti["mpu"] - tj["mpu"]) > 1e-9:
                continue
            mpu = ti["mpu"]
            O = _rect(P, ti) & _rect(P, tj)
            if O.is_empty or min(O.width, O.height) * mpu < REFINE_MIN_OVERLAP_M:
                continue
            r = _measure(book, i, j, ti, tj, mpu, REFINE_SEARCH_M, REFINE_PX_PER_M)
            if not r or r[2] < REFINE_MIN_CONF:
                continue
            edges.append({"i": i, "j": j, "dx": r[0], "dy": r[1], "conf": r[2], "mpu": mpu})
    idx = {p: k for k, p in enumerate(pages)}
    active = list(range(len(edges)))
    sx = np.array([sheets[p]["tx"] for p in pages])
    sy = np.array([sheets[p]["ty"] for p in pages])
    # How much each sheet's own placement holds it: match lines are exact and
    # are never moved; a correlation placement holds weakly, and less the
    # farther the neighbours pull it (an iteratively reweighted solve, so one
    # sheet a few metres off is put right instead of dragging the others).
    anchor = {p: (1000.0 if sheets[p]["method"] == "match lines" else 0.05) for p in pages}
    for _ in range(len(edges) + 6):
        rows, rx, ry, w = [], [], [], []
        for k in active:
            e = edges[k]
            r = np.zeros(len(pages)); r[idx[e["i"]]] = 1; r[idx[e["j"]]] = -1
            rows.append(r); rx.append(e["dx"]); ry.append(e["dy"]); w.append(1.0)
        for p in pages:
            r = np.zeros(len(pages)); r[idx[p]] = 1
            rows.append(r); rx.append(sheets[p]["tx"]); ry.append(sheets[p]["ty"])
            w.append(anchor[p])
        A = np.array(rows) * np.array(w)[:, None]
        nsx = np.linalg.lstsq(A, np.array(rx) * np.array(w), rcond=None)[0]
        nsy = np.linalg.lstsq(A, np.array(ry) * np.array(w), rcond=None)[0]
        settled = np.allclose(nsx, sx, atol=0.05) and np.allclose(nsy, sy, atol=0.05)
        sx, sy = nsx, nsy
        for p in pages:
            if sheets[p]["method"] != "match lines":
                pull = math.hypot(sx[idx[p]] - sheets[p]["tx"],
                                  sy[idx[p]] - sheets[p]["ty"]) * sheets[p]["mpu"]
                anchor[p] = 0.05 * min(1.0, 0.3 / max(pull, 1e-6))
        worst, worst_k = 0.0, None
        for k in active:
            e = edges[k]
            res = math.hypot(sx[idx[e["i"]]] - sx[idx[e["j"]]] - e["dx"],
                             sy[idx[e["i"]]] - sy[idx[e["j"]]] - e["dy"]) * e["mpu"]
            if res > worst:
                worst, worst_k = res, k
        if worst > REFINE_DROP_M and worst_k is not None:
            active.remove(worst_k)
        elif settled:
            break
    ok = {p: 0 for p in pages}
    for k in active:
        ok[edges[k]["i"]] += 1
        ok[edges[k]["j"]] += 1
    for p in pages:
        t = sheets[p]
        nx, ny = float(sx[idx[p]]), float(sy[idx[p]])
        moved = math.hypot(nx - t["tx"], ny - t["ty"]) * t["mpu"]
        if ok[p] and moved <= REFINE_SEARCH_M:
            t["tx"], t["ty"] = nx, ny
            t["moved_by_neighbours_m"] = round(moved, 2)
        else:
            ok[p] = 0
            t["moved_by_neighbours_m"] = 0.0
        t["neighbours_ok"] = ok[p]
    return {"pairs": len(edges), "kept": len(active), "dropped": len(edges) - len(active)}


# ---------------------------------------------------------------------------
# The whole book
# ---------------------------------------------------------------------------

def align_book(pdf_path: str, pages: list[dict], only: Optional[list[str]] = None,
               progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """Place every detail sheet of a book on its group's plane.

    ``pages``: one dict per page of the book — ``number``, ``sheet_number``,
    ``level``, ``key_plan``, ``mpu`` (metres per point, None when the sheet
    has no scale). ``only``: the group keys to build (all when None).
    Returns ``{"groups": [...]}`` — see the module docstring.
    """
    prog = progress or (lambda *_: None)
    book = _Book(pdf_path)
    allp = _pages(pages)
    keys_all = [p for p in allp if p.key_plan and p.mpu]
    # A level drawn on one sheet has nothing to lay out (the marked-up PDF
    # already shows it whole).
    plan = [g for g in plan_groups(pages) if (only is None or g["key"] in only)
            and len(g["pages"]) > 1]
    by_no = {p.number: p for p in allp}
    total = max(1, sum(len(g["pages"]) for g in plan))
    done = 0
    groups = []
    for g in plan:
        level = g["level"]
        keys = ([k for k in keys_all if level and k.level == level]
                + [k for k in keys_all if not level or k.level != level])
        grid = _key_grid(book, keys[0]) if keys else None
        sheets: dict[int, dict] = {}
        report = []
        for no in g["pages"]:
            sp = by_no[no]
            prog(done / total, f"{g['label']}: {sp.sheet_number or f'page {no}'}")
            done += 1
            rec: dict[str, Any] = {"page": no, "sheet_number": sp.sheet_number,
                                   "mpu": sp.mpu, "state": "not_aligned"}
            view = viewport(book.page(no).rect)
            a = _method_a(book, grid, sp) if grid else None
            try:
                b, why = _method_b(book, keys, sp) if keys else (None, "the book has no key plan")
            except Exception as exc:                      # noqa: BLE001 - a sheet, not the book
                b, why = None, f"could not be compared with the key plan ({exc})"
            if a and b:
                rec["a_vs_b_m"] = round(math.hypot(a["tx"] - b["tx"], a["ty"] - b["ty"]) * sp.mpu, 2)
                rec["conf"] = b["conf"]
            if a and b and rec["a_vs_b_m"] > A_B_REJECT_M and b["conf"] >= B_OVERRULE_CONF:
                t, method = b, "correlation (match lines rejected)"
            elif a:
                t, method = a, "match lines"
            elif b:
                t, method = b, "correlation"
                rec["conf"] = b["conf"]
            else:
                rec["why"] = why or "no match line and no label on the key plan"
                report.append(rec)
                continue
            rec.update(method=method, tx=t["tx"], ty=t["ty"], clip=list(t["clip"]),
                       view=list(view), residual_m=t.get("residual_m"))
            sheets[no] = {"tx": t["tx"], "ty": t["ty"], "mpu": sp.mpu, "view": list(view),
                          "method": method}
            report.append(rec)
        refine = _refine(book, sheets) if len(sheets) > 1 else {"pairs": 0, "kept": 0, "dropped": 0}
        # The group's frame: its most common scale; a sheet at another scale is
        # drawn scaled to it.
        mpus = collections.Counter(round(s["mpu"], 9) for s in sheets.values())
        M0 = float(mpus.most_common(1)[0][0]) if mpus else None
        xs, ys = [], []
        for rec in report:
            t = sheets.get(rec["page"])
            if not t:
                continue
            rec["tx"], rec["ty"] = t["tx"], t["ty"]
            rec["neighbours_ok"] = t.get("neighbours_ok", 0)
            rec["moved_by_neighbours_m"] = t.get("moved_by_neighbours_m", 0.0)
            rec["s"] = rec["mpu"] / M0
            confirmed = (rec.get("a_vs_b_m") is not None and rec["a_vs_b_m"] <= A_B_CONFIRM_M
                         and rec["method"] == "match lines") or rec["neighbours_ok"] > 0
            rec["state"] = "confirmed" if confirmed else "unconfirmed"
            c = rec["clip"]
            xs += [rec["s"] * (c[0] + t["tx"]), rec["s"] * (c[2] + t["tx"])]
            ys += [rec["s"] * (c[1] + t["ty"]), rec["s"] * (c[3] + t["ty"])]
        margin = 40.0
        frame = ({"x0": min(xs) - margin, "y0": min(ys) - margin,
                  "width": max(xs) - min(xs) + 2 * margin,
                  "height": max(ys) - min(ys) + 2 * margin} if xs else None)
        groups.append({"key": g["key"], "label": g["label"], "level": level, "mpu": M0,
                       "sheets": report, "no_scale": g["no_scale"], "frame": frame,
                       "refine": refine})
    prog(1.0, "done")
    return {"groups": groups}


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------

def to_map(sheet: dict, frame: dict, x: float, y: float) -> tuple[float, float]:
    """A sheet point (displayed coordinates) on the composite."""
    s = sheet.get("s", 1.0)
    return s * (x + sheet["tx"]) - frame["x0"], s * (y + sheet["ty"]) - frame["y0"]


def from_map(sheet: dict, frame: dict, X: float, Y: float) -> tuple[float, float]:
    """A composite point on a sheet (displayed coordinates)."""
    s = sheet.get("s", 1.0)
    return (X + frame["x0"]) / s - sheet["tx"], (Y + frame["y0"]) / s - sheet["ty"]


def inside(rect, x: float, y: float) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def drawn(sheet: dict) -> bool:
    """Whether a sheet is on the picture: aligned and not left out."""
    return sheet.get("state") not in (None, "not_aligned") and not sheet.get("excluded")


# ---------------------------------------------------------------------------
# Composing the picture
# ---------------------------------------------------------------------------

def compose(pdf_path: str, group: dict, out_path: str) -> dict:
    """Write the group's sheets onto one PDF page (vector, 1 pt = 1 pt of the
    group's frame). Sheets left out or not aligned are not drawn. Returns the
    page size."""
    import pymupdf
    frame = group["frame"]
    src = pymupdf.open(pdf_path)
    out = pymupdf.open()
    page = out.new_page(width=frame["width"], height=frame["height"])
    # The surest sheets last, so they sit on top where sheets overlap: a sheet
    # in the wrong place never hides one in the right place.
    order = {"contradicted": 0, "unconfirmed": 1, "confirmed": 2}
    for sh in sorted(group["sheets"], key=lambda s: order.get(s.get("state"), 1)):
        if not drawn(sh):
            continue
        flat = pymupdf.open()
        flat.insert_pdf(src, from_page=sh["page"] - 1, to_page=sh["page"] - 1)
        flat[0].remove_rotation()          # displayed coordinates = page coordinates
        c = sh["clip"]
        X0, Y0 = to_map(sh, frame, c[0], c[1])
        X1, Y1 = to_map(sh, frame, c[2], c[3])
        page.show_pdf_page(pymupdf.Rect(X0, Y0, X1, Y1), flat, 0,
                           clip=pymupdf.Rect(*c))
        flat.close()
    out.save(out_path, garbage=3, deflate=True)
    out.close()
    src.close()
    return {"width": frame["width"], "height": frame["height"]}


_open_docs: "collections.OrderedDict[str, Any]" = collections.OrderedDict()


def render_tile(base_pdf: str, z: int, x: int, y: int) -> bytes:
    """One square PNG of the composite at zoom ``z`` (``tile_scale``), column
    ``x``, row ``y``. Off the map: an empty tile. Callers serialise access."""
    import pymupdf
    doc = _open_docs.get(base_pdf)
    if doc is None:
        doc = pymupdf.open(base_pdf)
        _open_docs[base_pdf] = doc
        while len(_open_docs) > 4:
            _, old = _open_docs.popitem(last=False)
            old.close()
    else:
        _open_docs.move_to_end(base_pdf)
    page = doc[0]
    s = tile_scale(z)
    span = TILE_PX / s
    clip = pymupdf.Rect(x * span, y * span, (x + 1) * span, (y + 1) * span)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(s, s), clip=clip, alpha=False)
    if pix.width < TILE_PX or pix.height < TILE_PX:
        full = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, TILE_PX, TILE_PX), False)
        full.set_rect(full.irect, (255, 255, 255))
        if pix.width and pix.height:
            pix.set_origin(0, 0)
            full.copy(pix, pix.irect)
        pix = full
    return pix.tobytes("png")


def forget(base_pdf: str) -> None:
    """Close a composite another build is about to replace."""
    doc = _open_docs.pop(base_pdf, None)
    if doc is not None:
        doc.close()
