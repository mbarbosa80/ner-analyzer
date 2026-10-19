"""Room labels written a quarter turn round.

Venue design books turn a label when the room is too narrow to hold it
horizontally, and the OSP book does it constantly. The extractor searched for a
room's name only *above* the space code at the same x — the horizontal
arrangement — so on a rotated label it found the code, positioned the room
correctly, and lost the name.

Measured on ``OSP_400_SBL_O_ VDB Comments June 2026.pdf`` before the fix: 253
spaces extracted, **95 with a name and 158 as a bare code**. Reading the raw PDF
at the coordinates of the "missing" ones showed real rooms every time —
``BRS.002`` is *Technical Operation Center*, 54 m²; ``BRS.011`` is *Active
Equipment Cabin Space*, 12 m². Nothing was invented and nothing was misplaced;
only the names were dropped.

That matters more than a cosmetic gap, because the TEAP is matched on the room
name. A space carrying its code and nothing else cannot match ``Technical
Operation Center`` in the TEAP, so it contributes no demand and can never pull a
NER towards it.
"""

from __future__ import annotations

from app.domain.pdf_ingest import TextItem, _group_space_labels


def item(text, x0, y0, x1, y1, *, page=1, rotated=False, size=6.0):
    """One line of text, horizontal by default."""
    return TextItem(text=text, x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                    x0=x0, y0=y0, x1=x1, y1=y1, page=page, size=size, color=0,
                    dir_x=0.0 if rotated else 1.0,
                    dir_y=1.0 if rotated else 0.0)


# ---------------------------------------------------------------------------
# The direction flag
# ---------------------------------------------------------------------------

def test_horizontal_and_rotated_are_told_apart():
    assert item("x", 0, 0, 10, 6).rotated is False
    assert item("x", 0, 0, 6, 10, rotated=True).rotated is True


def test_the_default_direction_is_horizontal():
    """Anything that does not report a direction must behave as it did before."""
    t = TextItem(text="x", x=1, y=1, x0=0, y0=0, x1=2, y1=2, page=1,
                 size=6.0, color=0)
    assert t.rotated is False


# ---------------------------------------------------------------------------
# Horizontal labels keep working
# ---------------------------------------------------------------------------

def test_a_horizontal_label_still_finds_its_name():
    """The regression guard. The rotated case must not cost the common case."""
    spaces = _group_space_labels([
        item("Broadcast Compound", 100, 100, 180, 108),
        item("BRS.001", 100, 110, 140, 118),
    ])
    assert len(spaces) == 1
    assert spaces[0].space_code == "BRS.001"
    assert "Broadcast Compound" in spaces[0].name


# ---------------------------------------------------------------------------
# Rotated labels
# ---------------------------------------------------------------------------

def test_a_rotated_label_finds_the_name_beside_the_code():
    """Laid out as the real sheet lays it out: same y, stepping x.

    From the actual file::

        'Broadcast'  x=1396.8  y=1228.3
        'Compound'   x=1406.0  y=1228.4
        'BRS.001'    x=1413.9  y=1228.3
    """
    spaces = _group_space_labels([
        item("Broadcast", 1393, 1220, 1401, 1237, rotated=True),
        item("Compound", 1402, 1220, 1410, 1237, rotated=True),
        item("BRS.001", 1410, 1220, 1418, 1237, rotated=True),
    ])
    assert len(spaces) == 1
    assert spaces[0].space_code == "BRS.001"
    assert "Broadcast" in spaces[0].name and "Compound" in spaces[0].name


def test_the_real_missing_room_recovers_its_name():
    """``BRS.002`` — the one from the screenshot, reported as "not in the PDF".

    It was in the PDF all along, as *Technical Operation Center*, 54 m².
    """
    spaces = _group_space_labels([
        item("Center", 898, 892, 906, 908, rotated=True),
        item("Technical", 899, 911, 907, 927, rotated=True),
        item("Operation", 908, 924, 916, 940, rotated=True),
        item("BRS.002", 916, 911, 924, 927, rotated=True),
    ])
    assert len(spaces) == 1
    got = spaces[0]
    assert got.space_code == "BRS.002"
    assert got.name != "BRS.002", "a bare code is the bug this test exists for"
    assert "Technical" in got.name


def test_a_recovered_name_raises_the_confidence():
    """Confidence is what the register shows and what a reviewer sorts by, so
    it has to move with the evidence rather than stay at the floor."""
    bare = _group_space_labels([item("BRS.099", 100, 100, 140, 108)])
    named = _group_space_labels([
        item("Press", 1393, 1220, 1401, 1237, rotated=True),
        item("Room", 1402, 1220, 1410, 1237, rotated=True),
        item("PRS.001", 1410, 1220, 1418, 1237, rotated=True),
    ])
    assert bare[0].confidence < named[0].confidence
    assert any("name recovered" in e for e in named[0].evidence)


def test_a_rotated_label_does_not_absorb_a_distant_neighbour():
    """Widening the search along the wrong axis would glue unrelated rooms
    together, which is a worse failure than a missing name: it invents a room
    that is not on the drawing."""
    spaces = _group_space_labels([
        item("Broadcast", 1393, 1220, 1401, 1237, rotated=True),
        item("BRS.001", 1410, 1220, 1418, 1237, rotated=True),
        # The neighbouring room, at the spacing the real sheet uses: on page 10
        # BRS.002 sits at y=919 and BRS.011 at y=991, only 72 apart. A distance
        # tolerance wide enough for a label's own words is wide enough to reach
        # this, which is exactly how the first attempt glued them together.
        item("Catering", 1393, 1292, 1401, 1309, rotated=True),
    ])
    by_code = {s.space_code: s for s in spaces}
    assert "Catering" not in by_code["BRS.001"].name


def test_two_rotated_rooms_side_by_side_stay_separate():
    spaces = _group_space_labels([
        item("Alpha", 100, 500, 108, 517, rotated=True),
        item("BRS.010", 109, 500, 117, 517, rotated=True),
        item("Beta", 400, 500, 408, 517, rotated=True),
        item("BRS.011", 409, 500, 417, 517, rotated=True),
    ])
    got = {s.space_code: s.name for s in spaces}
    assert "Alpha" in got["BRS.010"] and "Beta" not in got["BRS.010"]
    assert "Beta" in got["BRS.011"] and "Alpha" not in got["BRS.011"]


# ---------------------------------------------------------------------------
# Neighbours, on the horizontal axis too
# ---------------------------------------------------------------------------

def test_a_horizontal_label_does_not_absorb_the_room_next_door():
    """The same gluing bug, on the other axis.

    Once the page rotation is corrected the labels come through horizontal, so
    the horizontal branch handles them — and it had the same 140-point distance
    tolerance. On page 10 the cabins sit about 70 points apart, well inside it,
    so BRS.002 collected BRS.011's words. Overlap on the cross axis is what
    stops it, and it needs no tuning.
    """
    spaces = _group_space_labels([
        item("Technical Operation Center", 1500, 900, 1560, 910),
        item("BRS.002", 1510, 912, 1548, 922),
        # The next cabin along, at the real spacing.
        item("Active Equipment Space Cabin", 1430, 900, 1490, 910),
        item("BRS.011", 1440, 912, 1478, 922),
    ])
    got = {s.space_code: s.name for s in spaces}
    assert "Active Equipment" not in got["BRS.002"], got["BRS.002"]
    assert "Technical" not in got["BRS.011"], got["BRS.011"]
    assert "Technical" in got["BRS.002"]
    assert "Active Equipment" in got["BRS.011"]
