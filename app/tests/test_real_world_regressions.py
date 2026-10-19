"""Regressions found by running the extractor against a real venue design book.

Neither of these was visible against synthetic data. They are pinned here so the
next change to the patterns cannot quietly reintroduce them.
"""

from __future__ import annotations

import pytest

from app.domain.pdf_ingest import ROOM_MARKER_RX, TextItem, _classify_marker
from app.domain.units import parse_scale_candidates, parse_scale_text


def item(text: str, colour: int = 0xCC0000) -> TextItem:
    return TextItem(text=text, x=100, y=100, x0=90, y0=95, x1=110, y1=105,
                    page=1, size=9.0, color=colour)


# ---------------------------------------------------------------------------
# Scale false positives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "VDB 3.0 PUBLICATION 03/31/2026",     # produced a phantom 1:2026
    "1 / 410 B5-VVO-O",                   # detail bubble naming sheet 410
    "430 B2-VVO-O",
    "1 / 470",
    "ISSUED 07/18/2025",
])
def test_title_block_text_is_not_read_as_a_scale(text):
    assert parse_scale_candidates(text) == []


@pytest.mark.parametrize("text,denom", [
    ("SCALE  1 : 200", 200.0),
    ("SCALE 1:1500", 1500.0),
    ("scale 1/50", 50.0),
    ("ESC. 1/100", 100.0),
    ("1:100", 100.0),
])
def test_genuine_scale_notations_still_parse(text, denom):
    s = parse_scale_text(text)
    assert s is not None
    assert s.denominator == pytest.approx(denom)


def test_a_keyword_anchored_scale_outranks_a_bare_one_on_the_same_sheet():
    page_text = "DETAIL 1:50 NOTES ... SCALE 1 : 200 ... TITLE BLOCK"
    cands = parse_scale_candidates(page_text)
    assert cands[0].denominator == pytest.approx(200.0)
    assert {round(c.denominator) for c in cands} == {200, 50}


def test_an_implausible_bare_denominator_is_rejected():
    assert parse_scale_candidates("REF 1:2026") == []
    assert parse_scale_candidates("SECTION 1:437") == []


def test_the_real_sheet_mix_yields_only_the_two_declared_scales():
    """Condensed from the reference document's page text."""
    page_text = (
        "FOR ADDITIONAL INFORMATION REFER TO THE DESIGN ASSUMPTIONS DOCUMENTS DATED "
        "03.31.2026. 01 VDB 2.1.1 PUBLICATION 07/18/2025 02 VDB 3.0 PUBLICATION "
        "03/31/2026 1 / 410 B5-VVO-O 430 B2-VVO-O SCALE  1 : 200 KEY PLAN SCALE 1 : 1500"
    )
    assert sorted(round(c.denominator) for c in parse_scale_candidates(page_text)) == [200, 1500]


# ---------------------------------------------------------------------------
# Marker false positives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Rack (NER)",
    "Rack (NER) -",
    "(TER)",
    "(COW/Temporary",
    "Owner furnished rack in NER",
    "CORNER DETAIL",
])
def test_annotation_callouts_do_not_become_rooms(text):
    assert _classify_marker(item(text)) is None


@pytest.mark.parametrize("text,kind,num", [
    ("Critical NER 1", "NER_CRITICAL", 1),
    ("Critical NER 20", "NER_CRITICAL", 20),
    ("NER 5", "NER_NONCRITICAL", 5),
    ("NER 19", "NER_NONCRITICAL", 19),
    ("COW #1", "COW", 1),
    ("TER", "TER", None),
    ("IDF", "IDF", None),
    ("NER 5 - Level 200", "NER_NONCRITICAL", 5),
])
def test_genuine_room_labels_still_classify(text, kind, num):
    el = _classify_marker(item(text))
    assert el is not None
    assert el.kind == kind
    assert el.number == num


def test_criticality_comes_from_the_text_when_both_share_one_colour():
    """The reference drawing paints every equipment room the same red."""
    crit = _classify_marker(item("Critical NER 3", colour=0xCC0000))
    non = _classify_marker(item("NER 6", colour=0xCC0000))
    assert crit.kind == "NER_CRITICAL"
    assert non.kind == "NER_NONCRITICAL"
    assert crit.color == non.color == "#cc0000"
    assert any("Critical" in e for e in crit.evidence)
    assert any("does not distinguish criticality by colour" in e for e in non.evidence)


def test_the_marker_pattern_is_anchored_at_both_ends():
    assert ROOM_MARKER_RX.match("NER 5")
    assert not ROOM_MARKER_RX.match("Rack (NER)")
    assert not ROOM_MARKER_RX.search("Rack (NER)")
