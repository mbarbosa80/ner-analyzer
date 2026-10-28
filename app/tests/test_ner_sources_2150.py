"""2.15.0 — the NERs the 3.x design books state: TEC.010 / TEC.020, the label
without "(NER)", the NER block symbol, and non-critical names from NER21.

Marcelo, 1 Oct 2026, with the VCC Softball book (``VCC_400_SBL_O.pdf``) and
the VDD, VEE and VBB AAM workbooks:

* *"Os novos VDBs estão vindo dessa forma. Decidiram não colocar os nomes
  tec.003.xxx.xxx ainda. Tem como usar isso para desenhar NERs ali além de
  todas as outras regras que já temos?"* — a screenshot of the block: a small
  orange square with "NER" inside, in a dashed rectangle.
* *"Eu sugiro colocar nesses lugares NER não crítica e depois eu mudo se
  precisar e segue tudo em sequência como NER XX começando com 21 em
  diante."*
* *"O rótulo 'Network Equipment Rack (NER) - Critical/Non-Critical' sem seta
  poderia receber NER"* and *"considere também TEC.010-xxx e TEC.020-xxx como
  NER crítica e não crítica, respectivamente, como você pode observar nas
  planilhas de AAM anexas."* In those workbooks ``TEC.003`` is now the Mobile
  Equipment Room.

The block's word is not text — AutoCAD plots SHX lettering as strokes — so
it is recognised by shape against a template (``domain.ner_symbol``). The
PDFs here are synthetic; the template itself was taken from the VCC book's
page 27 and is the one constant that came from a real document.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-2150-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2150.sqlite3")

from sqlalchemy import select                                      # noqa: E402

from app import ner_register as R                                  # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal                                    # noqa: E402
from app.domain import drawn_rooms as D                            # noqa: E402
from app.domain import ner_symbol as Y                             # noqa: E402
from app.domain.pdf_ingest import extract_drawing, read_drawn_rooms  # noqa: E402
from app.models import Drawing                                     # noqa: E402
from tests.test_key_plans_drawn_rooms_2130 import (  # noqa: E402,F401 — fixtures
    BLACK, _assets, _db, _label, _project_with_book, _title_block, client)

ORANGE = (1.0, 0.59, 0.2)


# ---------------------------------------------------------------------------
# Codes and labels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,code,critical,names_room", [
    ("TEC.010-003", "TEC.010-003", True, True),
    ("TEC.020-003", "TEC.020-003", False, True),
    ("TEC.020-021", "TEC.020-021", False, True),
    ("TEC . 010 - 7", "TEC.010-007", True, True),
    ("TEC.010", "TEC.010", True, False),                 # page 69 of the VCC book
    ("TEC.020", "TEC.020", False, False),
    ("TEC.003.01-05", "TEC.003.01-05", True, True),      # the 2.x books still read
    ("TEC.003.02", "TEC.003.02", False, False),
])
def test_the_3x_codes_are_ner_codes(text, code, critical, names_room):
    assert D.normalise_code(text) == code
    assert D.criticality_from_code(code) is critical
    assert D.code_names_a_room(code) is names_room


@pytest.mark.parametrize("text", [
    "TEC.003-001", "TEC.003-002",   # Mobile Equipment Room in the 3.x taxonomy
    "TEC.015-2",                    # the COW
    "TEC.0100", "TEC.107", "TEC.100-001", "SPT.010-001",
])
def test_what_is_not_a_ner_code(text):
    assert D.normalise_code(text) is None
    assert not D.has_rack_code(text)


def test_the_label_without_ner_in_brackets():
    assert D.ROOM_LABEL_PLAIN_RX.match("Rack - Non-Critical").group("tail") == "Non-Critical"
    assert D.ROOM_LABEL_PLAIN_RX.match("Network Equipment Rack - Critical").group("head")
    assert D.ROOM_LABEL_PLAIN_RX.match("Rack - 2") is None, "no criticality words, no rack label"
    assert D.ROOM_LABEL_PLAIN_RX.match("Rack") is None
    assert D.ROOM_LABEL_RX.match("Rack (NER) - Critical"), "the 2.x label still reads"


# ---------------------------------------------------------------------------
# The symbol on its own
# ---------------------------------------------------------------------------

def _turned(segs, angle, scale=1.0, dx=0.0, dy=0.0):
    c, s = math.cos(angle), math.sin(angle)
    return [(scale * (x0 * c - y0 * s) + dx, scale * (x0 * s + y0 * c) + dy,
             scale * (x1 * c - y1 * s) + dx, scale * (x1 * s + y1 * c) + dy)
            for x0, y0, x1, y1 in segs]


def test_the_template_matches_itself_at_any_angle_and_size():
    assert Y.shape_distance(Y.TEMPLATE)[0] < 1e-9
    for angle in (0.3, math.pi / 4, math.pi / 2, 2.1):
        d, kept = Y.shape_distance(_turned(Y.TEMPLATE, angle, scale=0.4, dx=0.2, dy=-0.1))
        assert d < 0.01 and len(kept) == len(Y.TEMPLATE), (angle, d)


def test_another_word_is_not_the_symbol():
    # The N and the E without the R: the same lettering, a different word.
    n_and_e = [s for s in Y.TEMPLATE if s[0] > -0.15 and s[2] > -0.15]
    assert 15 < len(n_and_e) < 40
    d, _ = Y.shape_distance(n_and_e)
    assert d > Y.MAX_DISTANCE
    # Mirror-invariance is deliberate (a block can be inserted mirrored),
    # but a scrambled set of the same strokes is not the word.
    import random
    rnd = random.Random(7)
    scrambled = [(rnd.uniform(-0.4, 0.4), rnd.uniform(-0.15, 0.15),
                  rnd.uniform(-0.4, 0.4), rnd.uniform(-0.15, 0.15)) for _ in Y.TEMPLATE]
    assert Y.shape_distance(scrambled)[0] > Y.MAX_DISTANCE


def _block(page, cx, cy, side=14.0, *, angle=0.0, fill=ORANGE, strokes=None,
           stroke_colour=BLACK, extra_dashes=0):
    """The CAD block: a filled square with the lettering as strokes."""
    half = side / 2
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(cx - half, cy - half, cx + half, cy + half))
    sh.finish(fill=fill, color=None)
    sh.commit()
    for x0, y0, x1, y1 in _turned(strokes or Y.TEMPLATE, angle, scale=half, dx=cx, dy=cy):
        sh = page.new_shape()
        sh.draw_line((x0, y0), (x1, y1))
        sh.finish(color=stroke_colour, width=0.24)
        sh.commit()
    # dashes of a boundary crossing the block, in another colour (VCC page 10)
    for i in range(extra_dashes):
        sh = page.new_shape()
        y = cy - half + 1.5 + i * 2.5
        sh.draw_line((cx - half + 0.5, y), (cx - half + 2.5, y))
        sh.finish(color=(0.5, 0.5, 0.5), width=0.24)
        sh.commit()


def test_the_symbol_is_found_on_a_sheet_turned_or_not_and_not_in_the_legend(tmp_path):
    doc = pymupdf.open()
    p = doc.new_page(width=1400, height=800)
    _title_block(p, "ENLARGED PLAN LEVEL 01 AREA A1", "TST-410A1-XXX-O")
    _block(p, 200, 300)                                   # plain
    _block(p, 500, 300, side=20, angle=math.pi / 4)      # bigger, turned 45°
    _block(p, 800, 300, angle=1.0, extra_dashes=4)        # crossed by grey dashes
    _block(p, 200, 600, strokes=[s for s in Y.TEMPLATE if s[0] > -0.15 and s[2] > -0.15])  # "NE"
    p.insert_text((1000, 500), "LEGEND", fontsize=8)
    _block(p, 1030, 560)                                  # the legend's own sample
    doc.save(str(tmp_path / "sym.pdf"))
    doc.close()

    rooms = read_drawn_rooms(str(tmp_path / "sym.pdf"))
    syms = sorted((round(r.x), round(r.y)) for r in rooms if r.source == "symbol")
    assert syms == [(200, 300), (500, 300), (800, 300)], syms
    assert all(r.critical is None and r.text == "NER" and r.code is None
               for r in rooms if r.source == "symbol")
    assert all(any("shape distance" in e for e in r.evidence) for r in rooms)


# ---------------------------------------------------------------------------
# The whole step on a 3.x-style book
# ---------------------------------------------------------------------------

def make_3x_book(path: Path) -> Path:
    doc = pymupdf.open()
    p = doc.new_page(width=1400, height=800)
    _title_block(p, "KEY ENLARGED PLAN - LEVEL 01", "TST-401-XXX-O")
    _block(p, 300, 300)                                   # a picture, on the key plan
    # page 2
    p = doc.new_page(width=1400, height=800)
    _title_block(p, "ENLARGED PLAN LEVEL 01 AREA A1", "TST-410A1-XXX-O")
    # the 3.x room label: two lines, no "(NER)", code under it, no arrow
    _label(p, 100, 100, ["Network Equipment", "Rack - Non-Critical"], size=8)
    p.insert_text((100, 114), "TEC.020-003", fontsize=4)
    p.insert_text((100, 119), "7 m²", fontsize=4)
    # a critical one with the bare class as its code (VCC page 69)
    _label(p, 500, 100, ["Network Equipment", "Rack - Critical"], size=8)
    p.insert_text((500, 114), "TEC.010", fontsize=4)
    # a symbol inside that critical room — the same rack, not a second NER
    _block(p, 530, 140)
    # two symbols in the open
    _block(p, 900, 400)
    _block(p, 900, 650, side=18, angle=0.6)
    # a "Rack - Critical" line with nothing over it: not a rack label
    p.insert_text((1100, 300), "Rack - Critical", fontsize=8)
    # page 3: the level above, repeating one symbol at the same place and a
    # second bare TEC.010 — two racks, not one
    p = doc.new_page(width=1400, height=800)
    _title_block(p, "ENLARGED PLAN LEVEL 02 AREA A1", "TST-420A1-XXX-O")
    _block(p, 900, 400)
    _label(p, 500, 100, ["Network Equipment", "Rack - Critical"], size=8)
    p.insert_text((500, 114), "TEC.010", fontsize=4)
    doc.save(str(path))
    doc.close()
    return path


def test_extraction_reads_codes_labels_and_symbols_off_the_detail_sheets(tmp_path):
    ex = extract_drawing(str(make_3x_book(tmp_path / "b3x.pdf")))
    assert [pg.key_plan for pg in ex.pages] == [True, False, False]
    rooms = ex.rooms
    assert all(r.page in (2, 3) for r in rooms), "nothing off the key plan"
    coded = {r.code: r for r in rooms if r.source == "code" and r.page == 2}
    nc = coded["TEC.020-003"]
    assert nc.critical is False and "Rack - Non-Critical" in nc.text and not nc.via_leader
    assert any("TEC.020 is a non-critical" in e for e in nc.evidence)
    cr = coded["TEC.010"]
    assert cr.critical is True and any("the same rack" in e for e in cr.evidence), \
        "the symbol drawn in the room is this room's rack"
    syms = [r for r in rooms if r.source == "symbol"]
    assert sorted((r.page, round(r.x), round(r.y)) for r in syms) == \
        [(2, 900, 400), (2, 900, 650), (3, 900, 400)]
    assert not any("Rack - Critical" == r.text for r in rooms), \
        "a 'Rack - Critical' line with no 'Network Equipment' over it is not a room"
    assert len(rooms) == 6


def test_the_step_names_them_in_sequence_from_ner20_and_asks_the_right_questions(tmp_path):
    pid, did = _project_with_book("drawn-3x", make_3x_book(tmp_path / "b3x2.pdf"))
    assets = _assets(pid)
    assert set(assets) == {"NERc_01.1", "NERc_02.1", "NER_20.1", "NER_21.1", "NER_22.1", "NER_23.1"}, set(assets)
    nc = assets["NER_20.1"]
    assert nc.space_code == "TEC.020-003" and nc.classification == "non_critical"
    assert not any(v.startswith("position:") for v in nc.pending_validations), \
        "the label sits in the room — nothing to drag"
    crit = [assets["NERc_01.1"], assets["NERc_02.1"]]
    assert all(a.space_code == "TEC.010" and a.kind == "NER_CRITICAL" for a in crit), \
        "a bare TEC.010 on two sheets is two racks, never merged as one code"
    assert {a.canonical_page for a in crit} == {2, 3}
    symbols = [a for a in assets.values() if a.suggested_name == "NER"]
    assert len(symbols) == 3
    assert all(a.kind == "NER_NONCRITICAL" and a.classification == "pending"
               and any(v.startswith("criticality:") for v in a.pending_validations)
               for a in symbols), "non-critical, criticality for him to choose"
    assert not any(any(v.startswith("position: no arrow") for v in a.pending_validations)
                   for a in symbols), "a symbol is where the rack is"
    twin = [a for a in symbols if a.canonical_page == 3]
    assert len(twin) == 1 and any("same place on page 2" in v for v in twin[0].pending_validations)
    assert all(e.label == a.display_name for a in symbols for e in a.occurrences)
    with SessionLocal() as db:
        d = db.get(Drawing, did)
        stats = d.extract_summary["drawn_rooms"]
        assert stats["created"] == 6 and stats["symbols"] == 3
        assert stats["same_place_other_page"] == 1 and stats["criticality_unstated"] == 3


def test_running_the_step_again_creates_nothing_new(tmp_path):
    pid, did = _project_with_book("drawn-3x-again", make_3x_book(tmp_path / "b3x3.pdf"))
    before = set(_assets(pid))
    with SessionLocal() as db:
        p = db.execute(select(S.Project).where(S.Project.id == pid)).scalar_one()
        totals = S.place_ners_from_drawing(db, p, actor="test")
    assert totals["created"] == 0 and totals["same_as_marker"] == 6
    assert set(_assets(pid)) == before


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def test_non_critical_names_start_at_20_and_critical_at_01():
    # 2.18.0: the naming sheet v2.0 — NER 20.1 onwards; the form is NERc_NN.1 / NER_NN.1
    assert R.SEQUENCE_START == {True: 1, False: 20}
    assert R.next_sequential_name([], False) == "NER_20.1"
    assert R.next_sequential_name([], True) == "NERc_01.1"
    assert R.next_sequential_name(["NER 02", "NER 7"], False) == "NER_20.1", \
        "an old low number never pulls the series below 20"
    assert R.next_sequential_name(["NER_20.1", "NER_21.1"], False) == "NER_22.1"
    assert R.next_sequential_name(["NER 30"], False) == "NER_31.1"
    assert R.next_sequential_name(["NERc_01.1", "NER_20.1"], True) == "NERc_02.1"
    # the older forms the register still holds count in their series
    assert R.next_sequential_name(["NERc01", "NERc 02", "NER21"], True) == "NERc_03.1"
    assert R.next_sequential_name(["NERc01", "NERc 02", "NER21"], False) == "NER_22.1"
