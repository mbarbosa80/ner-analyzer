"""The marked-up PDF has to land on the same drawing the viewer shows.

The venue books arrive with ``/Rotate 90`` on every page, and the extractor was
corrected to report display coordinates so that it agrees with PDF.js — the
viewer draws a room where the room is. The exporter was never corrected with
it, and PyMuPDF's writing methods address the *unrotated* MediaBox: on the OSP
book the displayed page is 2448 x 1584 while the box PyMuPDF writes into is
1584 x 2448, so a marker stored at x=2040 was written past the right edge of a
1584-wide box and disappeared off the sheet, dragging its leader line to an area
that had gone with it.

That is exactly the reported defect — "the NERs are out of place and pointing at
areas also outside the drawing" — and it existed only in the export. These tests
pin the correction on a page that is rotated and on one that is not, because a
fix that only works on rotated pages would break every book that is upright.
"""

from __future__ import annotations

import pymupdf
import pytest

from app.domain.coverage import NER, compute_coverage
from app.domain.distance import DemandType, DistanceRules
from app.domain.geometry import Area, Point
from app.domain.pdf_ingest import ElementKind
from app.domain.reports import PageSpace, export_marked_pdf
from app.domain.units import Scale

RULES = DistanceRules()

# The real page geometry from ``OSP_400_SBL_O_ VDB Comments June 2026.pdf``:
# MediaBox 1584 x 2448 portrait, /Rotate 90, displayed 2448 x 1584 landscape.
MEDIA_W, MEDIA_H = 1584.0, 2448.0
DISPLAY_W, DISPLAY_H = 2448.0, 1584.0

# A marker position taken from the loaded database. x=2040 is *inside* the
# displayed page and *outside* the MediaBox: the coordinate that exposes the bug.
NER_X, NER_Y = 2040.0, 368.0
AREA_X, AREA_Y = 1900.0, 500.0


def rotated_source(tmp_path, rotation: int):
    doc = pymupdf.open()
    page = doc.new_page(width=MEDIA_W, height=MEDIA_H)
    page.set_rotation(rotation)
    path = tmp_path / f"src_{rotation}.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def upright_source(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=DISPLAY_W, height=DISPLAY_H)
    path = tmp_path / "src_upright.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def scene():
    area = Area(key="BRS.002", name="Technical Operation Center", page=1,
                label_point=Point(AREA_X, AREA_Y, 1))
    ner = NER(key="N1", label="NER 12", kind=ElementKind.NER_NONCRITICAL,
              point=Point(NER_X, NER_Y, 1), critical=False, total_ports=100)
    scales = {1: Scale(metres_per_unit=0.05, source="manual", label="1:20",
                       confirmed=True)}
    result = compute_coverage(
        areas=[(area, 5.0, DemandType.GENERAL, None, True)],
        ners=[ner], scale_for_page=scales, rules=RULES)
    return result, [ner], scales


def drawn_points_in_display_space(path: str) -> list[tuple[float, float]]:
    """Every vector item written into the file, expressed as the reader sees it.

    ``get_drawings`` reports the unrotated box, the same space the writing
    methods use, so the rotation matrix takes it back to display coordinates —
    the space the application stores and the viewer paints.
    """
    doc = pymupdf.open(path)
    try:
        page = doc[0]
        m = page.rotation_matrix
        out = []
        for d in page.get_drawings():
            r = pymupdf.Rect(d["rect"]) * m
            out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        return out
    finally:
        doc.close()


def near(points, x, y, tol=14.0):
    return any(abs(px - x) <= tol and abs(py - y) <= tol for px, py in points)


# ---------------------------------------------------------------------------
# The translation itself
# ---------------------------------------------------------------------------

def test_page_space_reports_the_displayed_size_not_the_media_box(tmp_path):
    doc = pymupdf.open(rotated_source(tmp_path, 90))
    sp = PageSpace(doc[0])
    assert (sp.width, sp.height) == (DISPLAY_W, DISPLAY_H)
    assert sp.contains(NER_X, NER_Y), \
        "x=2040 is on the displayed page; only the MediaBox is too narrow for it"
    doc.close()


def test_a_display_point_is_moved_into_the_box_pymupdf_writes_in(tmp_path):
    doc = pymupdf.open(rotated_source(tmp_path, 90))
    sp = PageSpace(doc[0])
    p = sp.pt(NER_X, NER_Y)
    assert 0 <= p.x <= MEDIA_W and 0 <= p.y <= MEDIA_H, \
        "the translated point must land inside the MediaBox, or nothing is drawn"
    assert (p.x, p.y) != (NER_X, NER_Y), "a rotated page must be translated"
    doc.close()


def test_an_upright_page_is_left_exactly_as_it_is(tmp_path):
    """The regression guard: most books are not rotated and must not move."""
    doc = pymupdf.open(upright_source(tmp_path))
    sp = PageSpace(doc[0])
    p = sp.pt(NER_X, NER_Y)
    assert (round(p.x, 6), round(p.y, 6)) == (NER_X, NER_Y)
    assert sp.text_rotate == 0
    doc.close()


# ---------------------------------------------------------------------------
# The export
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_the_marker_lands_where_it_is_stored(tmp_path, rotation):
    """Whatever the page carries, the NER is drawn at the stored position."""
    src = (upright_source(tmp_path) if rotation == 0
           else rotated_source(tmp_path, rotation))
    out = str(tmp_path / f"marked_{rotation}.pdf")
    result, ners, scales = scene()
    export_marked_pdf(src, out, coverage=result, ners=ners,
                      scale_for_page=scales, rules=RULES, draw_radii=False)
    pts = drawn_points_in_display_space(out)
    assert near(pts, NER_X, NER_Y), \
        f"no marker near the stored NER position on a /Rotate {rotation} page"
    assert near(pts, AREA_X, AREA_Y), \
        f"no area marker near the stored space position on a /Rotate {rotation} page"


def test_nothing_is_written_outside_the_sheet(tmp_path):
    """The visible symptom: overlays that leave the page altogether."""
    src = rotated_source(tmp_path, 90)
    out = str(tmp_path / "marked.pdf")
    result, ners, scales = scene()
    export_marked_pdf(src, out, coverage=result, ners=ners,
                      scale_for_page=scales, rules=RULES, draw_radii=False)
    doc = pymupdf.open(out)
    page = doc[0]
    box = pymupdf.Rect(0, 0, MEDIA_W, MEDIA_H)
    strays = [d["rect"] for d in page.get_drawings()
              if not box.contains(pymupdf.Rect(d["rect"]))]
    doc.close()
    assert not strays, f"{len(strays)} overlay(s) written off the sheet: {strays[:3]}"


def test_the_legend_is_drawn_on_the_page_the_reader_sees(tmp_path):
    """The legend sits at the top-left of the *displayed* sheet, not of a box
    turned a quarter round where the reader will never look for it."""
    src = rotated_source(tmp_path, 90)
    out = str(tmp_path / "legend.pdf")
    result, ners, scales = scene()
    export_marked_pdf(src, out, coverage=result, ners=ners,
                      scale_for_page=scales, rules=RULES, draw_radii=False)
    pts = drawn_points_in_display_space(out)
    assert any(px < 360 and py < 240 for px, py in pts), \
        "the legend panel should be in the top-left corner as displayed"


def test_off_page_items_are_reported_rather_than_hidden(tmp_path):
    """A position that really is off the sheet is still drawn, and named.

    Silently dropping it would leave a reviewer comparing an export against a
    register and finding no explanation for the difference.
    """
    src = rotated_source(tmp_path, 90)
    out = str(tmp_path / "stray.pdf")
    area = Area(key="X", name="Nowhere", page=1,
                label_point=Point(9000.0, 9000.0, 1))
    ner = NER(key="N1", label="NER 12", kind=ElementKind.NER_NONCRITICAL,
              point=Point(NER_X, NER_Y, 1), critical=False, total_ports=100)
    scales = {1: Scale(metres_per_unit=0.05, source="manual", label="1:20",
                       confirmed=True)}
    result = compute_coverage(areas=[(area, 5.0, DemandType.GENERAL, None, True)],
                              ners=[ner], scale_for_page=scales, rules=RULES)
    strays: list = []
    export_marked_pdf(src, out, coverage=result, ners=[ner], scale_for_page=scales,
                      rules=RULES, draw_radii=False, off_page=strays)
    assert [s["key"] for s in strays] == ["X"]
    assert strays[0]["page_width"] == DISPLAY_W


def test_a_page_with_nothing_on_it_still_gets_a_legend(tmp_path):
    src = rotated_source(tmp_path, 90)
    out = str(tmp_path / "empty.pdf")
    result, ners, scales = scene()
    export_marked_pdf(src, out, coverage=result, ners=[], scale_for_page={},
                      rules=RULES)
    doc = pymupdf.open(out)
    assert doc[0].get_drawings(), "the legend must be there even with no overlays"
    doc.close()


# ---------------------------------------------------------------------------
# Speed: the export must not freeze the server
# ---------------------------------------------------------------------------

def dense_source(tmp_path, pages: int = 6):
    """A book with a heavy content stream on every page.

    Venue design books are dense vector CAD — 35 MB over 75 pages, about 475 KB
    per page. That is what made the export slow: every ``page.draw_*`` call
    commits its own shape, which appends to and re-parses the whole stream, so
    the cost is paid per drawing operation *and* scales with how much is already
    on the page. A synthetic page with a few thousand strokes reproduces the
    shape of that cost without shipping a 35 MB fixture.
    """
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=MEDIA_W, height=MEDIA_H)
        page.set_rotation(90)
        sh = page.new_shape()
        for i in range(2500):
            sh.draw_line(pymupdf.Point(i % 1500, i % 2400),
                         pymupdf.Point((i * 7) % 1500, (i * 13) % 2400))
        sh.finish(width=0.3, color=(0.4, 0.4, 0.4))
        sh.commit()
    path = tmp_path / "dense.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_one_commit_per_page_not_one_per_drawn_item(tmp_path):
    """The defect, pinned structurally rather than by a stopwatch.

    A wall-clock threshold would be flaky on a loaded machine. What actually
    went wrong is countable: the legend alone is twenty-two drawing operations,
    and each used to become its own content-stream entry. Counting the entries
    the export adds catches a regression to per-item commits on any machine.
    """
    src = rotated_source(tmp_path, 90)
    before = len(pymupdf.open(src)[0].get_drawings())
    out = str(tmp_path / "counted.pdf")
    result, ners, scales = scene()
    export_marked_pdf(src, out, coverage=result, ners=ners,
                      scale_for_page=scales, rules=RULES)

    doc = pymupdf.open(out)
    page = doc[0]
    # ``xref_get_key`` tells us how the content arrives: one stream, or many.
    contents = page.get_contents()
    doc.close()
    assert before == 0
    assert len(contents) <= 2, (
        f"the export added {len(contents)} content streams to one page; it should "
        f"commit once per page, not once per drawn item")


def test_a_dense_book_exports_in_a_sane_time(tmp_path):
    """A guard on the thing the user actually felt.

    Generous on purpose — this is a smoke alarm for a twenty-fold regression,
    not a benchmark. Before the fix the same six pages took well over a minute.
    """
    import time
    src = dense_source(tmp_path, pages=6)
    out = str(tmp_path / "dense_marked.pdf")
    result, ners, scales = scene()
    t0 = time.time()
    export_marked_pdf(src, out, coverage=result, ners=ners,
                      scale_for_page=scales, rules=RULES)
    elapsed = time.time() - t0
    assert elapsed < 20, f"six dense pages took {elapsed:.0f}s — the per-item " \
                         f"commit is back"


def multi_page_source(tmp_path, pages: int = 4):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=MEDIA_W, height=MEDIA_H).set_rotation(90)
    path = tmp_path / f"multi_{pages}.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def scene_on_page(page: int):
    """The same scene, placed on a given page of a multi-page book."""
    area = Area(key=f"BRS.{page:03d}", name="Technical Operation Center", page=page,
                label_point=Point(AREA_X, AREA_Y, page))
    ner = NER(key=f"N{page}", label=f"NER {page}", kind=ElementKind.NER_NONCRITICAL,
              point=Point(NER_X, NER_Y, page), critical=False, total_ports=100)
    scales = {page: Scale(metres_per_unit=0.05, source="manual", label="1:20",
                          confirmed=True)}
    result = compute_coverage(
        areas=[(area, 5.0, DemandType.GENERAL, None, True)],
        ners=[ner], scale_for_page=scales, rules=RULES)
    return result, [ner], scales


def test_progress_survives_a_page_that_carries_a_marker(tmp_path):
    """The regression that shipped, and why the first progress test missed it.

    The page count was held in ``n``, and the marker loop further down used the
    same name for the NER it was drawing. From the first page carrying a marker
    onwards the page count *was* a NER, and the next page's progress line raised
    ``'>' not supported between instances of 'int' and 'NER'``.

    It needed three things at once to fire: a progress callback (so only the
    background job), a page with a marker on it, and *another page after that
    one*. The original test had a single-page document, so it could never bite.
    """
    src = multi_page_source(tmp_path, pages=4)
    out = str(tmp_path / "multi_progress.pdf")
    result, ners, scales = scene_on_page(2)      # marker on page 2 of 4
    seen: list = []
    export_marked_pdf(src, out, coverage=result, ners=ners, scale_for_page=scales,
                      rules=RULES, progress=lambda f, stage: seen.append((f, stage)))
    assert len([1 for _, stage in seen if "marking page" in stage]) == 4, \
        "every page must report, including the ones after a page with a marker"
    assert any("of 4" in stage for _, stage in seen), \
        "the page count must stay the page count all the way through"


def test_progress_is_reported_for_every_page_and_the_write(tmp_path):
    """The button used to give no sign of life for minutes. It has to say what
    it is doing, page by page, and again while the file is written."""
    src = rotated_source(tmp_path, 90)
    out = str(tmp_path / "progress.pdf")
    result, ners, scales = scene()
    seen: list = []
    export_marked_pdf(src, out, coverage=result, ners=ners, scale_for_page=scales,
                      rules=RULES, progress=lambda f, stage: seen.append((f, stage)))
    assert seen, "the export must report progress"
    assert any("marking page" in stage for _, stage in seen)
    assert any("writing" in stage for _, stage in seen)
    assert seen[-1][0] == 1.0, "it must finish at 100%, or the bar never closes"
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions), "progress must not go backwards"


def test_progress_can_abort_the_export(tmp_path):
    """Cancellation is the callback raising — the same contract the drawing
    import already uses."""
    src = rotated_source(tmp_path, 90)
    out = str(tmp_path / "aborted.pdf")
    result, ners, scales = scene()

    class Cancelled(Exception):
        pass

    def stop(_f, _stage):
        raise Cancelled

    with pytest.raises(Cancelled):
        export_marked_pdf(src, out, coverage=result, ners=ners,
                          scale_for_page=scales, rules=RULES, progress=stop)
