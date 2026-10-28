"""2.19.0 — the access points the TEAP states, drawn where their rooms are.

Marcelo, 14 Oct 2026: "desenhar nos VDB o AP (access point) nos espaços que já
sabemos que tem wifi, assim como fazemos com as NERs. Somente para espaços que
encontramos automaticamente no TEAP e nos espaços. Só para facilitar os
espaços que já conhecemos."

* one wireless point per wireless port of every matched TEAP space, beside
  the room's label (in rows of four), tied to the space (``tie_source`` ``teap``);
* the count does not change: the tied point stands in for the TEAP's port;
* never twice — a space with a tied point (by hand or an earlier run) is left
  alone; a space with no room is named, not placed; a key plan gets nothing;
* a move never re-ties a TEAP-placed point;
* the same step is reachable over the API and audited.

Also here: a reference's label (*NER, *TER, *COW, *DIVA) is two points larger
than a room's, in the viewer and in the marked PDF.
"""

from __future__ import annotations

import pathlib
import re

from sqlalchemy import select

from tests.test_wireless_tie_250 import (DWISA, OFFICE, _analyse, _ap, _line, _match,  # noqa: F401
                                         _ner, _project, _room, _teap, client)
from app.db import SessionLocal
from app.models import AuditLog, Element, Page, Project
from app import services as S
from app.domain import reports as RP

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _place(client, pid) -> dict:
    r = client.post(f"/api/projects/{pid}/wireless/place-from-teap")
    assert r.status_code == 200, r.text
    return r.json()


def _points(pid) -> list[Element]:
    with SessionLocal() as db:
        return list(db.execute(select(Element).where(
            Element.project_id == pid, Element.kind == "WIRELESS").order_by(Element.id)).scalars())


def test_one_wifi_point_per_space_with_wireless_beside_the_room_tied_to_the_space(client):
    """4.3.0: one Wi-Fi point per space whose TEAP states wireless, whatever
    the DWISA quantity (it was one per wireless port from 2.19.0 to 4.2.3)."""
    pid = _project("ap-teap-basic")
    _room(pid, "OFF.100", "Office", 100, 100)
    _room(pid, "CTL.100", "Control Room", 300, 100)
    _room(pid, "STO.100", "Store", 500, 100)
    key_office = _teap(pid, "OFF.100", "Office", OFFICE)                       # one wireless port
    key_ctl = _teap(pid, "CTL.100", "Control Room",
                    [_line("Laptop", 2, 2, "LAP", 1), _line(DWISA, 2, 2, "DWISA", 2)])  # two
    _teap(pid, "STO.100", "Store", [_line("Laptop", 1, 1, "LAP", 1)])         # no wireless
    _ner(pid, "NER A", 300, 140)
    _match(client, pid)

    r = _place(client, pid)
    assert r["spaces_with_wireless"] == 2
    assert r["spaces_placed"] == 2 and r["placed"] == 2
    assert r["already_had_points"] == 0 and r["no_room"] == 0 and r["on_key_plan"] == 0
    assert r["names"] == ["WIFI-1", "WIFI-2"]

    pts = _points(pid)
    assert len(pts) == 2
    by_space = {}
    for e in pts:
        by_space.setdefault(e.space_key, []).append(e)
        assert e.tie_source == "teap" and e.origin == "teap"
        assert e.detection_method == "teap_wireless" and e.confirmed
        assert e.page == 1
        assert any("placed from the TEAP" in s for s in e.evidence)
    assert len(by_space[key_office]) == 1 and len(by_space[key_ctl]) == 1
    # Beside the label — below and to the right, never on the name.
    office = by_space[key_office][0]
    assert (office.x, office.y) == (100 + S.TEAP_AP_OFFSET[0], 100 + S.TEAP_AP_OFFSET[1])


def test_a_space_asking_for_many_aps_still_gets_one_wifi_point(client):
    """4.3.0: six access points on the wireless line are one Wi-Fi point on
    the sheet — the quantity stays on the TEAP line, not in the drawing."""
    pid = _project("ap-teap-rows")
    _room(pid, "FOP.100", "Field of Play", 100, 100)
    key = _teap(pid, "FOP.100", "Field of Play",
                [_line("Wireless Access Point", 6, 6, "WAP", 1)])
    _match(client, pid)
    r = _place(client, pid)
    assert r["placed"] == 1 and r["spaces_placed"] == 1
    assert len([e for e in _points(pid) if e.space_key == key]) == 1


def test_the_count_does_not_change_the_port_only_gets_a_position(client):
    """4.0.0: the TEAP is the only source of ports. One DWISA port in the TEAP,
    one point placed for it — the NER's load is the same 5 ports before and
    after, and the DWISA line keeps carrying the wireless port."""
    pid = _project("ap-teap-count")
    _room(pid, "OFF.110", "Office", 100, 100)
    _teap(pid, "OFF.110", "Office", OFFICE)
    _ner(pid, "NER A", 100, 140)
    _match(client, pid)
    before = _analyse(pid)
    load = {v["label"]: v for v in before.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 5 and load["NER A"]["wireless_points"] == 0

    _place(client, pid)
    after = _analyse(pid)
    load = {v["label"]: v for v in after.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 5, "4 laptops + the DWISA line, not 4 + 1 + 1"
    assert load["NER A"]["wireless_points"] == 1 and load["NER A"]["wireless_ports"] == 1
    space = next(a for a in after.assignments if a.kind == "space")
    assert space.ports_required == 5
    point = next(a for a in after.assignments if a.kind == "wireless_point")
    assert point.ports_required == 0
    assert after.summary()["wireless_ports"] == 1 and after.summary()["total_ports"] == 5


def test_running_it_again_adds_nothing_and_a_hand_drawn_point_counts_as_done(client):
    pid = _project("ap-teap-again")
    _room(pid, "OFF.120", "Office", 100, 100)
    _room(pid, "OFF.121", "Office B", 400, 100)
    _teap(pid, "OFF.120", "Office", OFFICE)
    key_b = _teap(pid, "OFF.121", "Office B", OFFICE)
    _ner(pid, "NER A", 250, 140)
    _match(client, pid)
    # The person already drew Office B's access point by hand (tied by the
    # nearest-room proposal): that space is done.
    made = _ap(client, pid, 405, 110)
    assert made["space_key"] == key_b

    r1 = _place(client, pid)
    assert r1["placed"] == 1 and r1["already_had_points"] == 1
    r2 = _place(client, pid)
    assert r2["placed"] == 0 and r2["already_had_points"] == 2
    assert len(_points(pid)) == 2
    labels = sorted(e.label for e in _points(pid))
    assert labels == ["WIFI-1", "WIFI-2"], "numbered in one sequence with the hand-drawn one"


def test_a_space_with_no_room_is_named_not_placed_and_a_key_plan_gets_nothing(client):
    pid = _project("ap-teap-unplaced")
    _room(pid, "OFF.130", "Office", 100, 100)
    _teap(pid, "OFF.130", "Office", OFFICE)
    _teap(pid, "MED.130", "Medical Room", OFFICE)        # wireless, but no room drawn
    _ner(pid, "NER A", 100, 140)
    _match(client, pid)

    r = _place(client, pid)
    assert r["placed"] == 1 and r["no_room"] == 1
    assert r["unplaced_spaces"] == ["Medical Room"]

    # The one sheet turned into a key plan: nothing is placed there, and the
    # point placed before is not duplicated.
    pid2 = _project("ap-teap-keyplan")
    _room(pid2, "OFF.131", "Office", 100, 100)
    _teap(pid2, "OFF.131", "Office", OFFICE)
    _match(client, pid2)
    with SessionLocal() as db:
        p = db.get(Project, pid2)
        pg = db.execute(select(Page).where(Page.drawing_id == p.drawings[0].id)).scalars().first()
        pg.key_plan = True
        db.commit()
    r = _place(client, pid2)
    assert r["placed"] == 0 and r["on_key_plan"] == 1
    assert _points(pid2) == []


def test_a_move_never_reties_a_teap_placed_point_but_the_person_still_can(client):
    pid = _project("ap-teap-move")
    _room(pid, "OFF.140", "Office", 100, 100)
    _room(pid, "CTL.140", "Control Room", 400, 100)
    key_office = _teap(pid, "OFF.140", "Office", OFFICE)
    key_ctl = _teap(pid, "CTL.140", "Control Room", [_line("Laptop", 2, 2, "LAP", 1)])
    _ner(pid, "NER A", 250, 140)
    _match(client, pid)
    _place(client, pid)
    e = _points(pid)[0]
    # Dragged into the Control Room — the nearest-room rule would re-tie an
    # auto point; this one stays the Office's wireless port.
    r = client.patch(f"/api/projects/{pid}/elements/{e.id}", json={"x": 402, "y": 104})
    assert r.status_code == 200, r.text
    e = _points(pid)[0]
    assert e.space_key == key_office and e.tie_source == "teap"
    # The person can still say it serves another space.
    r = client.patch(f"/api/projects/{pid}/elements/{e.id}", json={"space_key": key_ctl})
    assert r.status_code == 200, r.text
    e = _points(pid)[0]
    assert e.space_key == key_ctl and e.tie_source == "manual"


def test_the_step_is_audited(client):
    pid = _project("ap-teap-audit")
    _room(pid, "OFF.150", "Office", 100, 100)
    _teap(pid, "OFF.150", "Office", OFFICE)
    _match(client, pid)
    _place(client, pid)
    with SessionLocal() as db:
        rows = db.execute(select(AuditLog).where(
            AuditLog.project_id == pid, AuditLog.action == "wireless.placed_from_teap")).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["placed"] == 1 and rows[0].payload["names"] == ["WIFI-1"]
    assert rows[0].actor == "tester"


def test_the_hand_placed_point_uses_the_same_label_sequence(client):
    """The label helper is one function now; ``create_element`` reads it."""
    pid = _project("ap-teap-labels")
    _room(pid, "OFF.160", "Office", 100, 100)
    _teap(pid, "OFF.160", "Office", OFFICE)
    _match(client, pid)
    _place(client, pid)
    made = _ap(client, pid, 50, 50)
    assert made["label"] == "WIFI-2"
    with SessionLocal() as db:
        assert S.next_wireless_label(db, pid, "WIRELESS") == "WIFI-3"


# ---------------------------------------------------------------------------
# Reference labels two points larger
# ---------------------------------------------------------------------------

def test_reference_labels_are_two_points_larger_in_the_pdf_and_the_viewer():
    assert RP.REFERENCE_LABEL_SIZE == RP.MARKER_LABEL_SIZE + 2.0
    src = (ROOT / "backend" / "app" / "domain" / "reports.py").read_text(encoding="utf-8")
    assert "REFERENCE_LABEL_SIZE if n.kind in REFERENCE_KINDS" in src
    viewer = (ROOT / "frontend" / "src" / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    m = re.search(r"fontSize=\{\(DEMAND_KINDS\.has\(e\.kind\) \? 10 : REFERENCE_KINDS\.has\(e\.kind\) \? (\d+) : (\d+)\) / zoom\}", viewer)
    assert m, "the marker label size expression changed shape"
    assert int(m.group(1)) == int(m.group(2)) + 2


def test_the_scale_screen_offers_the_step_and_the_pt_strings_exist():
    panels = (ROOT / "frontend" / "src" / "pages" / "panels.tsx").read_text(encoding="utf-8")
    assert 'api.placeAccessPoints(p.id)' in panels
    assert 't("Place Wi-Fi from the TEAP")' in panels
    api = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "/wireless/place-from-teap" in api
    pt = (ROOT / "frontend" / "src" / "lib" / "strings.pt.ts").read_text(encoding="utf-8")
    for key in ("Place Wi-Fi from the TEAP", "Wi-Fi from the TEAP",
                "placed from the TEAP", "from the TEAP"):
        assert f'"{key}":' in pt, key
