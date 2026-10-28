"""4.8.1 — Wi-Fi points of one space placed side by side must not print their
name tags over each other on the marked-up PDF.

4.8.0 stopped stacking the points of several TEAP lines tied to one room, but
kept the 32 pt pitch chosen for the short ``AP-n`` tags of 2.19.0: on VBB 400
page 15 the tags ``WIFI-37`` to ``WIFI-40`` touched and overlapped. The test
draws the tag boxes the way ``reports`` does and checks every neighbour pair
of the grid, for names up to ``WIFI-999``.
"""

from __future__ import annotations

import pymupdf

# The data folder of the suite is set before the application is imported.
from tests.test_wireless_tie_250 import TMP  # noqa: F401
from app import services as S
from app.domain import reports as R


def _tag(x: float, y: float, name: str) -> pymupdf.Rect:
    # The same box reports.py draws under a Wi-Fi sign.
    tw = pymupdf.get_text_length(name, fontname=R.MARKER_LABEL_FONT, fontsize=R.WIFI_LABEL_SIZE)
    tx = x - tw / 2
    ty = y + R.WIFI_LABEL_SIZE + 5
    return pymupdf.Rect(tx - 2.5, ty - R.WIFI_LABEL_SIZE * 0.78 - 1.5, tx + tw + 2.5, ty + 3)


def _sign(x: float, y: float) -> pymupdf.Rect:
    h = R.WIFI_SIGN_SIZE / 2
    return pymupdf.Rect(x - h, y - h, x + h, y + h)


def _grid(n: int) -> list[tuple[float, float]]:
    taken: list[tuple[float, float]] = []
    for _ in range(n):
        taken.append(S.free_wifi_slot(100.0, 100.0, taken))
    return taken


def _overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    # Touching edges count as overlapping: the frames would merge.
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def test_neighbouring_wifi_tags_do_not_touch_up_to_wifi_999():
    for name in ("WIFI-1", "WIFI-38", "WIFI-100", "WIFI-999"):
        pts = _grid(12)
        tags = [_tag(x, y, name) for x, y in pts]
        for i in range(len(tags)):
            for k in range(i + 1, len(tags)):
                assert not _overlap(tags[i], tags[k]), (name, pts[i], pts[k])


def test_a_tag_does_not_sit_on_the_sign_of_the_next_row():
    pts = _grid(8)
    for i, (x, y) in enumerate(pts):
        tag = _tag(x, y, "WIFI-100")
        for k, (x2, y2) in enumerate(pts):
            if k != i:
                assert not _overlap(tag, _sign(x2, y2)), (pts[i], pts[k])


def test_rows_of_four():
    pts = _grid(9)
    assert len({y for _, y in pts}) == 3
    assert [round(x - pts[0][0]) for x, _ in pts[:4]] == [0, 48, 96, 144]
