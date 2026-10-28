"""2.4.1 — a sheet that prints no space code.

A cricket venue's book (``VDD_300_CKT_VDB 3.0``) labels every room by
name alone — "Venue Media Centre (VMC)", "Workforce Check-in" — over two or
three stacked lines of 12 pt text, and prints no ``XXX.NNN`` code anywhere.
The extractor started from the code, so the book came out with nine pages,
ten equipment rooms and **zero spaces**, and the matching step then refused
to run with "ingest at least one drawing", which was false: the drawing was
ingested; it just had no room the extractor could see.

Measured on the real book with this pass: 58 spaces on the six floor plans,
none on the three key plans, none from the legend / client-group key / general
notes / revision table / title block / scale bar / stamps, and 23 of the 94
TEAP rows matched on the name (all held for review, as a name-only match must
be). What stays unmatched — the press tribune, the photo work room, the photo
positions — is not labelled on that book at all: the pavilion interiors are not
drawn. That is a fact about the document, and the manual says so.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-test-241-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from app.domain.pdf_ingest import (NAME_ONLY_CONFIDENCE, TextItem,  # noqa: E402
                                   _group_name_labels, _is_room_name_line,
                                   _title_block_strip, extract_drawing)


def item(text, x0, y0, x1, y1, *, page=1, rotated=False, size=12.0, color=0):
    return TextItem(text=text, x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                    x0=x0, y0=y0, x1=x1, y1=y1, page=page, size=size, color=color,
                    dir_x=0.0 if rotated else 1.0, dir_y=1.0 if rotated else 0.0)


# ---------------------------------------------------------------------------
# Grouping stacked lines into one label
# ---------------------------------------------------------------------------

def test_a_stacked_label_becomes_one_space_named_in_reading_order():
    """As the VDD book prints it on page 5: four centred lines, 13.5 pt pitch,
    16 pt boxes, so consecutive boxes overlap by about 3 pt."""
    spaces = _group_name_labels([
        item("Venue", 729, 964, 762, 980),
        item("Technology", 716, 977, 776, 993),
        item("Operations", 717, 991, 775, 1007),
        item("(VTO)", 731, 1004, 761, 1020),
    ])
    assert len(spaces) == 1
    s = spaces[0]
    assert s.name == "Venue Technology Operations (VTO)"
    assert s.space_code is None
    assert s.confidence == NAME_ONLY_CONFIDENCE
    assert any("no space code" in e for e in s.evidence)
    assert 716 < s.x < 776 and 964 < s.y < 1020


def test_two_labels_four_points_apart_stay_two_rooms():
    """Page 9 of the VDD book: "SPP Control Room" directly over "Commentator
    Position", 4 pt of clear space between the boxes. One room each."""
    spaces = _group_name_labels([
        item("SPP Control", 1028, 198, 1094, 215),
        item("Room", 1045, 212, 1077, 228),
        item("Commentator", 1028, 232, 1101, 248),
        item("Position", 1043, 245, 1086, 262),
    ])
    assert sorted(s.name for s in spaces) == ["Commentator Position", "SPP Control Room"]


def test_side_by_side_labels_are_not_merged():
    spaces = _group_name_labels([
        item("IVH Kitchen", 1228, 1168, 1291, 1184),
        item("LIC Storage", 1133, 1017, 1197, 1033),
    ])
    assert sorted(s.name for s in spaces) == ["IVH Kitchen", "LIC Storage"]


def test_lines_of_different_sizes_are_different_labels():
    spaces = _group_name_labels([
        item("Broadcast", 470, 1440, 529, 1456),
        item("Compound", 470, 1454, 529, 1470),
        item("NOTE", 470, 1468, 529, 1478, size=7.0),
    ])
    assert [s.name for s in spaces if s.name.startswith("Broadcast")] == ["Broadcast Compound"]


def test_a_rotated_label_reads_along_x():
    spaces = _group_name_labels([
        item("Broadcast", 1393, 1220, 1401, 1290, rotated=True),
        item("Compound", 1402, 1220, 1410, 1290, rotated=True),
    ])
    assert len(spaces) == 1
    assert spaces[0].name == "Broadcast Compound"


# ---------------------------------------------------------------------------
# What is not a room
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "CONFIDENTIAL", "NOT FOR CONSTRUCTION", "KEY PLAN", "GENERAL NOTES:",
    "SCALE 1:", "500", "m", "0", "REVISIONS", "REV.", "CLIENT GROUPS",
    "03/31/2026", "1. FOR ADDITIONAL INFORMATION AND CONTEXT REGARDING KEY",
    "Autodesk Docs://Event-Venues-Design/60443086-ACM-OVY-VN074-A.rvt",
    "311A-CKT-O", "VDD-311B-CKT-O", "A-101",
    "NER 2", "Critical NER 7", "TER", "COW", "DIVA Node 2",
    "NER - Critical",
])
def test_sheet_furniture_and_markers_are_not_rooms(text):
    assert _is_room_name_line(item(text, 100, 100, 300, 116), None, []) is False


@pytest.mark.parametrize("text", [
    "Venue Media Centre (VMC)", "Workforce Check-in", "LIC Storage", "Wicket 4",
    "Athlete Changing Room - A", "Concessions/Points of Sale (POS)",
    "Venue",      # a title-block word, but a legitimate line of a room label
])
def test_room_labels_pass(text):
    strip = (2000.0, 0.0, 2448.0, 1584.0)
    assert _is_room_name_line(item(text, 100, 100, 300, 116), strip, []) is True


def test_anything_inside_the_title_block_strip_is_excluded():
    strip = (2125.0, 0.0, 2448.0, 1584.0)
    assert _is_room_name_line(item("TICKET SCAN", 2174, 662, 2250, 672), strip, []) is False
    assert _is_room_name_line(item("Fixed Seat", 2192, 1020, 2250, 1032), strip, []) is False


def test_the_strip_is_anchored_on_the_drawing_number_label_not_on_scale():
    """The scale bar prints "SCALE 1:" mid-sheet; anchoring on every block
    label pulled the strip off its column on the VDD book."""
    items = [
        item("DRAWING NUMBER", 2155, 1488, 2220, 1496, size=7),
        item("VDD-311B-CKT-O", 2231, 1497, 2330, 1509),
        item("DRAWING TITLE", 2155, 1397, 2220, 1405, size=7),
        item("SCALE 1:", 1900, 1524, 1935, 1532, size=8),
    ]
    strip = _title_block_strip(items, 2448.0, 1584.0)
    assert strip is not None
    assert strip[0] == pytest.approx(2125.0)
    assert strip[1] == 0.0 and strip[2] == 2448.0


def test_no_anchor_no_strip():
    assert _title_block_strip([item("Room", 10, 10, 40, 20)], 2448.0, 1584.0) is None


def test_a_bottom_title_block_gives_a_band():
    items = [item("DRAWING NUMBER", 200, 1500, 280, 1508, size=7)]
    assert _title_block_strip(items, 2448.0, 1584.0) == (0.0, 1470.0, 2448.0, 1584.0)


# ---------------------------------------------------------------------------
# Through the extractor, on synthetic sheets
# ---------------------------------------------------------------------------

def _vdd_like_pdf(path: Path) -> None:
    """One coded sheet and one code-less sheet in the same book."""
    doc = pymupdf.open()
    # page 1: coded, as the Honda book prints it
    p = doc.new_page(width=1000, height=700)
    p.insert_text((100, 100), "Broadcast Compound", fontsize=7.5)
    p.insert_text((100, 110), "BRS.001", fontsize=7.5)
    p.insert_text((900, 600), "DRAWING NUMBER", fontsize=7)
    p.insert_text((900, 612), "TST-101", fontsize=10)
    p.insert_text((400, 650), "SCALE 1:500", fontsize=8)
    # page 2: no code anywhere — the VDD layout
    p = doc.new_page(width=1000, height=700)
    for i, line in enumerate(["Venue", "Technology", "Operations", "(VTO)"]):
        p.insert_text((300, 300 + i * 13.5), line, fontsize=12)
    p.insert_text((500, 400), "LIC Storage", fontsize=12)
    p.insert_text((700, 200), "NER 2", fontsize=18, color=(0.8, 0, 0))
    p.insert_text((50, 650), "CONFIDENTIAL", fontsize=12, color=(1, 0, 0))
    p.insert_text((50, 664), "NOT FOR CONSTRUCTION", fontsize=12, color=(1, 0, 0))
    p.insert_text((880, 100), "CLIENT GROUPS", fontsize=12)
    p.insert_text((890, 120), "FIELD OF PLAY", fontsize=7.8)
    p.insert_text((890, 134), "PRESS OPERATIONS", fontsize=7.8)
    p.insert_text((880, 300), "GENERAL NOTES:", fontsize=6.8)
    p.insert_text((880, 310), "1. FOR ADDITIONAL INFORMATION AND CONTEXT", fontsize=6.8)
    p.insert_text((880, 318), "INDICATIVE AND SUBJECT TO CHANGE.", fontsize=6.8)
    p.insert_text((880, 600), "DRAWING NUMBER", fontsize=7)
    p.insert_text((880, 612), "TST-102", fontsize=10)
    p.insert_text((880, 560), "DRAWING TITLE", fontsize=7)
    p.insert_text((880, 572), "FLOOR PLAN-CRICKET-B", fontsize=10)
    p.insert_text((400, 650), "SCALE 1:500", fontsize=8)
    doc.save(str(path))
    doc.close()


@pytest.fixture(scope="module")
def vdd_like(tmp_path_factory):
    path = tmp_path_factory.mktemp("vdd") / "vdd-like.pdf"
    _vdd_like_pdf(path)
    return extract_drawing(str(path))


def test_a_coded_sheet_is_read_exactly_as_before(vdd_like):
    p1 = [s for s in vdd_like.spaces if s.page == 1]
    assert [s.space_code for s in p1] == ["BRS.001"]
    assert "Broadcast Compound" in p1[0].name


def test_a_code_less_sheet_yields_its_room_names_and_nothing_else(vdd_like):
    p2 = sorted(s.name for s in vdd_like.spaces if s.page == 2)
    assert p2 == ["LIC Storage", "Venue Technology Operations (VTO)"]
    for s in vdd_like.spaces:
        if s.page == 2:
            assert s.space_code is None
            assert s.confidence == NAME_ONLY_CONFIDENCE
            assert any("confirm the room against the TEAP" in e for e in s.evidence)


def test_the_marker_on_the_code_less_sheet_is_still_a_marker_not_a_room(vdd_like):
    assert [e.label for e in vdd_like.elements if e.page == 2] == ["NER 2"]


# ---------------------------------------------------------------------------
# The matching step tells the truth about why it cannot run
# ---------------------------------------------------------------------------

def test_the_two_refusals_are_told_apart():
    """"ingest at least one drawing" was shown on a project *with* a drawing
    whose extraction found nothing. The two situations get their own words."""
    from app import services as S
    from app.db import SessionLocal, init_db
    from app.models import Drawing, Project, TeapFile, TeapSpace

    init_db()
    with SessionLocal() as db:
        p = Project(name="refusals-241", venue_code="TST")
        db.add(p)
        db.flush()
        tf = TeapFile(project_id=p.id, filename="t.xlsx", stored_path="/nowhere/t.xlsx")
        db.add(tf)
        db.flush()
        db.add(TeapSpace(project_id=p.id, teap_file_id=tf.id, space_key="k1",
                         space_code="TST.001", space_name="Room", total_ports=1.0))
        db.commit()
        with pytest.raises(S.ValidationError, match="ingest at least one drawing"):
            S.run_matching(db, p)
        db.add(Drawing(project_id=p.id, filename="x.pdf", stored_path="/nowhere/x.pdf",
                       sha256="0" * 64, page_count=9, extract_summary={"spaces": 0}))
        db.commit()
        with pytest.raises(S.ValidationError, match="no space was recognised"):
            S.run_matching(db, p)


def test_the_no_space_message_is_translated():
    from app.services import NO_SPACE_RECOGNISED
    text = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib"
            / "strings.pt.ts").read_text(encoding="utf-8")
    assert NO_SPACE_RECOGNISED in text


# ---------------------------------------------------------------------------
# A book imported before 2.4.1 gets its spaces without a re-import
# ---------------------------------------------------------------------------

def test_the_backfill_reads_a_space_less_book_once_and_leaves_its_markers(tmp_path):
    from sqlalchemy import select

    from app import migrate
    from app.db import SessionLocal, init_db
    from app.models import AuditLog, Drawing, DrawingSpace, Element, Project

    init_db()
    pdf = tmp_path / "vdd-like.pdf"
    _vdd_like_pdf(pdf)
    # Take the coded page away so the book is one code-less sheet, as VDD is.
    doc = pymupdf.open(str(pdf))
    doc.delete_page(0)
    doc.save(str(tmp_path / "one.pdf"))
    doc.close()

    with SessionLocal() as db:
        p = Project(name="backfill-241", venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="one.pdf", stored_path=str(tmp_path / "one.pdf"),
                    sha256="0" * 64, page_count=1, extract_summary={"spaces": 0})
        db.add(d)
        db.flush()
        marker = Element(project_id=p.id, drawing_id=d.id, page=1, kind="NER_NONCRITICAL",
                         label="NER 2", number=2, x=700, y=200, origin="extracted",
                         confidence=0.7, confirmed=True, locked=True, evidence=[],
                         detection_method="pdf_extraction", document_kind="VDB",
                         link_status="unlinked")
        db.add(marker)
        db.commit()

        first = migrate.backfill_name_only_spaces(db, p)
        assert first["name_only_books_read"] == 1
        assert first["name_only_spaces_found"] == 2
        names = sorted(s.name for s in db.execute(
            select(DrawingSpace).where(DrawingSpace.drawing_id == d.id)).scalars())
        assert names == ["LIC Storage", "Venue Technology Operations (VTO)"]
        db.refresh(d)
        assert d.extract_summary["name_only_pass"] == migrate.NAME_ONLY_PASS
        assert d.extract_summary["spaces"] == 2
        # the marker is exactly as it was
        db.refresh(marker)
        assert marker.locked is True and marker.confirmed is True
        assert db.execute(select(Element).where(Element.drawing_id == d.id)).scalars().all() \
            == [marker]
        assert db.execute(select(AuditLog).where(
            AuditLog.action == "drawing.spaces_backfilled",
            AuditLog.entity_id == d.id)).scalars().first() is not None

        # a second pass is a no-op: the stamp is there
        second = migrate.backfill_name_only_spaces(db, p)
        assert second == {"name_only_books_read": 0, "name_only_spaces_found": 0,
                          "name_only_books_skipped": 0}
        assert len(db.execute(select(DrawingSpace).where(
            DrawingSpace.drawing_id == d.id)).scalars().all()) == 2


def test_the_backfill_leaves_a_book_that_already_has_spaces_alone():
    from sqlalchemy import select

    from app import migrate
    from app.db import SessionLocal, init_db
    from app.models import Drawing, DrawingSpace, Project

    init_db()
    with SessionLocal() as db:
        p = Project(name="backfill-241-coded", venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="coded.pdf", stored_path="/nowhere/coded.pdf",
                    sha256="0" * 64, page_count=1, extract_summary={"spaces": 1})
        db.add(d)
        db.flush()
        db.add(DrawingSpace(project_id=p.id, drawing_id=d.id, page=1, space_code="TST.001",
                            name="Room", x=1, y=1, origin="extracted", confidence=0.9,
                            evidence=[]))
        db.commit()
        out = migrate.backfill_name_only_spaces(db, p)
        assert out["name_only_books_skipped"] == 1 and out["name_only_books_read"] == 0
        assert len(db.execute(select(DrawingSpace).where(
            DrawingSpace.drawing_id == d.id)).scalars().all()) == 1


# ---------------------------------------------------------------------------
# Centre / Center
# ---------------------------------------------------------------------------

def test_british_and_american_centre_normalise_together():
    from app.domain.matching import normalise_name
    assert normalise_name("Venue Media Centre (VMC)") == normalise_name("Venue Media Center (VMC)")
