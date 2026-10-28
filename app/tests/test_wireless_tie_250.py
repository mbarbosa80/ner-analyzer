"""2.5.0 — a drawn access point stands in for the wireless port the TEAP requests.

On the event's TEAP every space with Wi-Fi carries one ``DWISA`` line — *Wireless
Connection - Shared Internet Access (SIA) Wireless LAN* — with **one network
port**, the access point's uplink (88 of the 110 VAA spaces). A wireless
point drawn in the viewer takes one port on the NER that reaches it. Nothing
tied the two, so a space with five drawn access points put **six** wireless
ports on the switch: five drawn plus the TEAP's one. The LLD is built from
that number (Marcelo, 21 Sep 2026: *"ter uma porta a mais pode ser uma conta
muito alta"*).

The rule now: a wireless point is tied to the TEAP space it stands in for —
proposed as the nearest matched room on its sheet, changed or cleared in the
Inspector — and a space with at least one point tied to it has its TEAP
wireless port taken off; the points carry the wireless on their own NER. With
nothing drawn the TEAP's port stays: the TEAP rules. Indoor and outdoor
access points follow one rule and differ in symbol, numbering and the report.
"""

from __future__ import annotations

import os
import tempfile

import openpyxl
import pytest

TMP = tempfile.mkdtemp(prefix="ner-250-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t250.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, Page, Project,  # noqa: E402
                        TeapFile, TeapSpace)

DWISA = "Wireless Connection - Shared Internet Access (SIA) Wireless LAN"


@pytest.fixture(scope="module")
def client():
    init_db()
    c = TestClient(app)
    from app import auth as A
    with SessionLocal() as db:
        try:
            A.create_user(db, username="tester", password="a-long-test-phrase",
                          display_name="Test User", is_admin=True, actor="tests")
        except A.AuthError:
            pass
    assert c.post("/api/auth/login", json={"username": "tester",
                                           "password": "a-long-test-phrase"}).status_code == 200
    return c


def _line(product, qty, ports, code="X", row=1):
    return {"row": row, "product": product, "code": code, "qty": qty, "ports": ports,
            "rule": "A", "explanation": ""}


def _project(name) -> int:
    """One sheet at 1 unit = 1 m."""
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="x" * 64, page_count=1)
        db.add(d)
        db.flush()
        db.add(Page(drawing_id=d.id, number=1, width=1000, height=700, metres_per_unit=1.0,
                    scale_label="1u=1m", scale_source="manual", scale_confirmed=True,
                    level="LEVEL 01"))
        db.add(TeapFile(project_id=p.id, filename="teap.xlsx", stored_path=f"{TMP}/t.xlsx",
                        sha256="y" * 64))
        db.commit()
        return p.id


def _room(pid, code, name, x, y) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        r = DrawingSpace(project_id=pid, drawing_id=p.drawings[0].id, page=1,
                         space_code=code, name=name, x=x, y=y, confidence=0.9)
        db.add(r)
        db.commit()
        return r.id


def _teap(pid, code, name, lines) -> str:
    with SessionLocal() as db:
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        t = TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|{code}",
                      space_code=code, space_name=name,
                      total_ports=sum(ln["ports"] for ln in lines), lines=lines,
                      wireless_required=any("Wireless" in ln["product"] for ln in lines))
        db.add(t)
        db.commit()
        return t.space_key


def _ner(pid, label, x, y, *, total_ports=48) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=1,
                    kind="NER_NONCRITICAL", label=label, x=x, y=y, origin="manual",
                    confidence=1.0, confirmed=True, total_ports=total_ports)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        if e.ner_asset is not None:
            e.ner_asset.total_ports = total_ports
            db.commit()
        return e.id


def _ap(client, pid, x, y, kind="WIRELESS", **extra):
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": kind, "label": "", "x": x, "y": y, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _element(client, pid, el_id):
    return next(e for e in client.get(f"/api/projects/{pid}/elements").json() if e["id"] == el_id)


def _match(client, pid):
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200


def _analyse(pid):
    with SessionLocal() as db:
        p = db.get(Project, pid)
        result, ners = S.analyse(db, p)
        S.save_scenario(db, p, "As-Is", "as_is", result, ners)
        db.commit()
    return result


OFFICE = [_line("Laptop", 4, 4, "LAP", 1), _line(DWISA, 1, 1, "DWISA", 2)]


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def test_five_drawn_and_one_in_the_teap_is_the_teap(client):
    """4.0.0 replaces the 2.5.0 rule (Marcelo, 16 Oct 2026: "AP não é um
    produto do TEAP"). Five access points drawn by hand for a space whose DWISA
    line asks for one: the switch gets the TEAP's 4 + 1 — the drawn points are
    positions, never ports. A space that really needs five says so in its
    DWISA quantity."""
    pid = _project("wp-supersede")
    _room(pid, "OFF.010", "Office", 100, 100)
    key = _teap(pid, "OFF.010", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    for i in range(5):
        made = _ap(client, pid, 90 + i * 5, 105)
        assert made["space_key"] == key and made["tie_source"] == "auto"
    result = _analyse(pid)

    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 5, "4 laptops + the DWISA line, nothing else"
    assert load["NER A"]["wireless_points"] == 5 and load["NER A"]["wireless_ports"] == 1
    space = next(a for a in result.assignments if a.kind == "space")
    assert space.ports_required == 5
    assert any("DWISA" in r and "Wi-Fi point drawn" in r for r in space.reasons)
    assert result.summary()["wireless_ports"] == 1


def test_with_nothing_drawn_the_teap_port_stays_and_the_row_says_so(client):
    pid = _project("wp-pending")
    _room(pid, "OFF.011", "Office", 100, 100)
    _teap(pid, "OFF.011", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    result = _analyse(pid)
    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 5, "the TEAP rules until the points are drawn"
    space = result.assignments[0]
    assert space.ports_required == 5
    assert any("no Wi-Fi point drawn" in r for r in space.reasons)
    assert result.summary()["wireless_ports"] == 1


def test_a_point_tied_to_no_space_counts_no_port(client):
    pid = _project("wp-extra")
    _room(pid, "OFF.012", "Office", 100, 100)
    _teap(pid, "OFF.012", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _ner(pid, "NER B", 600, 600)
    _match(client, pid)
    far = _ap(client, pid, 600, 590)            # 490 m from the only room: no tie
    assert far["space_key"] is None and far["tie_source"] == "auto"
    assert any("no matched room" in e for e in far["evidence"])
    result = _analyse(pid)
    load = {v["label"]: v for v in result.ner_load.values()}
    assert load["NER A"]["assigned_ports"] == 5, "the TEAP's wireless port is still counted"
    assert load["NER B"]["assigned_ports"] == 0, "not in the TEAP: no port (4.0.0)"
    assert load["NER B"]["wireless_points"] == 1
    point = next(a for a in result.assignments if a.kind == "wireless_point")
    assert any("tied to no TEAP space" in r and "no port" in r for r in point.reasons)


def test_wireless_line_ports_reads_only_the_wireless_lines():
    with SessionLocal() as db:
        t = TeapSpace(space_key="k", space_name="x", total_ports=5, lines=OFFICE)
        assert S.wireless_line_ports(t) == 1
        t.lines = [_line("Laptop", 4, 4)]
        assert S.wireless_line_ports(t) == 0
        t.lines = None
        assert S.wireless_line_ports(t) == 0


# ---------------------------------------------------------------------------
# The tie: proposed, moved, chosen, cleared
# ---------------------------------------------------------------------------

def test_the_tie_is_the_nearest_matched_room_and_follows_a_move(client):
    pid = _project("wp-tie")
    _room(pid, "OFF.020", "Office", 100, 100)
    _room(pid, "LNG.020", "Lounge", 300, 100)
    _room(pid, "STO.020", "Store", 500, 100)     # on the drawing, not in the TEAP
    a = _teap(pid, "OFF.020", "Office", OFFICE)
    b = _teap(pid, "LNG.020", "Lounge", OFFICE)
    _ner(pid, "NER A", 200, 120)
    _match(client, pid)

    made = _ap(client, pid, 120, 100)
    assert made["space_key"] == a and made["space_name"] == "Office"
    assert any("nearest matched room" in e for e in made["evidence"])

    # Dragged next to the lounge: the proposal moves with it.
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"x": 290, "y": 100}).status_code == 200
    assert _element(client, pid, made["id"])["space_key"] == b

    # Dragged next to the store, which no TEAP line asks for, 200 m from the
    # lounge: the store is not a candidate and the lounge is out of reach, so
    # the point is untied — and says so — rather than tied to a room it does
    # not serve.
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"x": 500, "y": 100}).status_code == 200
    e = _element(client, pid, made["id"])
    assert e["space_key"] is None and e["tie_source"] == "auto"


def test_the_tie_is_capped_at_the_general_limit(client):
    pid = _project("wp-cap")
    _room(pid, "OFF.021", "Office", 100, 100)
    _teap(pid, "OFF.021", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    assert _ap(client, pid, 189, 100)["space_key"] is not None      # 89 m
    assert _ap(client, pid, 191, 100)["space_key"] is None          # 91 m


def test_a_manual_tie_outranks_the_proposal_and_survives_a_move(client):
    pid = _project("wp-manual")
    _room(pid, "OFF.022", "Office", 100, 100)
    _room(pid, "LNG.022", "Lounge", 300, 100)
    a = _teap(pid, "OFF.022", "Office", OFFICE)
    b = _teap(pid, "LNG.022", "Lounge", OFFICE)
    _ner(pid, "NER A", 200, 120)
    _match(client, pid)
    made = _ap(client, pid, 120, 100)
    assert made["space_key"] == a

    r = client.patch(f"/api/projects/{pid}/elements/{made['id']}", json={"space_key": b})
    assert r.status_code == 200, r.text
    e = _element(client, pid, made["id"])
    assert e["space_key"] == b and e["tie_source"] == "manual"
    # A move does not take a person's choice back.
    client.patch(f"/api/projects/{pid}/elements/{made['id']}", json={"x": 100, "y": 100})
    assert _element(client, pid, made["id"])["space_key"] == b

    # Cleared by hand: no space, and a move does not re-propose one.
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"space_key": ""}).status_code == 200
    e = _element(client, pid, made["id"])
    assert e["space_key"] is None and e["tie_source"] == "manual"
    client.patch(f"/api/projects/{pid}/elements/{made['id']}", json={"x": 110, "y": 100})
    assert _element(client, pid, made["id"])["space_key"] is None

    # An unknown key is refused; a room marker cannot be tied at all.
    assert client.patch(f"/api/projects/{pid}/elements/{made['id']}",
                        json={"space_key": "TST|NOPE"}).status_code == 404
    ner_id = client.get(f"/api/projects/{pid}/elements").json()[0]["id"]
    assert client.patch(f"/api/projects/{pid}/elements/{ner_id}",
                        json={"space_key": a}).status_code == 422


def test_a_point_placed_with_a_space_key_is_a_manual_tie(client):
    pid = _project("wp-created-manual")
    _room(pid, "OFF.023", "Office", 100, 100)
    a = _teap(pid, "OFF.023", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    made = _ap(client, pid, 600, 600, space_key=a)
    assert made["space_key"] == a and made["tie_source"] == "manual"


def test_tie_options_list_the_matched_spaces_only(client):
    pid = _project("wp-options")
    _room(pid, "OFF.024", "Office", 100, 100)
    _room(pid, "LNG.024", "Lounge", 300, 100)
    _teap(pid, "OFF.024", "Office", OFFICE)
    _teap(pid, "LNG.024", "Lounge", [_line("Laptop", 2, 2)])
    _teap(pid, "GON.024", "Gone", OFFICE)         # not on the drawing
    _match(client, pid)
    rows = client.get(f"/api/projects/{pid}/wireless/tie-options").json()
    assert [r["space_name"] for r in rows] == ["Lounge", "Office"], "alphabetical within the page"
    assert {r["space_name"]: r["wireless_ports"] for r in rows} == {"Lounge": 0, "Office": 1}


# ---------------------------------------------------------------------------
# One kind of access point (2.14.0)
# ---------------------------------------------------------------------------

def test_points_are_one_kind_numbered_in_sequence_and_the_old_kind_is_folded(client):
    """The indoor/outdoor split of 2.5.0 went in 2.14.0: every point is an AP,
    numbered WIFI-1, WIFI-2 …; a WIRELESS_OUTDOOR point of an older database is
    folded into WIRELESS by the start-up pass, and the old AP-I / AP-E labels
    are renumbered once."""
    pid = _project("wp-kinds")
    _room(pid, "OFF.030", "Office", 100, 100)
    _teap(pid, "OFF.030", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    i1 = _ap(client, pid, 100, 105)
    i2 = _ap(client, pid, 120, 105)
    assert (i1["label"], i2["label"]) == ("WIFI-1", "WIFI-2")
    result = _analyse(pid)
    load = next(iter(result.ner_load.values()))
    assert load["wireless_points"] == 2 and "wireless_indoor" not in load
    assert load["assigned_ports"] == 4 + 1          # the TEAP: laptops + DWISA
    rows = {w["label"]: w for w in client.get(
        f"/api/projects/{pid}/spaces/assignments").json()["wireless_points"]}
    assert rows["WIFI-1"]["ap_kind"] == "Wi-Fi" and rows["WIFI-1"]["space_name"] == "Office"
    # The old kind is not accepted any more.
    assert client.patch(f"/api/projects/{pid}/elements/{i2['id']}",
                        json={"kind": "WIRELESS_OUTDOOR"}).status_code == 422
    # …and one left in the database is folded, with the old labels renumbered.
    with SessionLocal() as db:
        p = db.get(Project, pid)
        db.add(Element(project_id=pid, drawing_id=p.drawings[0].id, page=1,
                       kind="WIRELESS_OUTDOOR", label="AP-E-1", x=130, y=105,
                       origin="manual", confidence=1.0, confirmed=True, evidence=[]))
        db.commit()
        got = migrate.fold_outdoor_wireless(db, p)
        assert got == {"wireless_folded": 1, "wireless_renumbered": 1}
        kinds = sorted((e.kind, e.label) for e in db.execute(select(Element).where(
            Element.project_id == pid, Element.kind.like("WIRELESS%"))).scalars())
        assert kinds == [("WIRELESS", "WIFI-1"), ("WIRELESS", "WIFI-2"), ("WIRELESS", "WIFI-3")]
        assert migrate.fold_outdoor_wireless(db, p) == {"wireless_folded": 0, "wireless_renumbered": 0}
    assert _ap(client, pid, 140, 105)["label"] == "WIFI-4"


# ---------------------------------------------------------------------------
# Points drawn before 2.5.0
# ---------------------------------------------------------------------------

def test_the_backfill_renames_and_ties_old_points_once(client):
    pid = _project("wp-backfill")
    _room(pid, "OFF.040", "Office", 100, 100)
    a = _teap(pid, "OFF.040", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120)
    _match(client, pid)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        old = Element(project_id=pid, drawing_id=p.drawings[0].id, page=1, kind="WIRELESS",
                      label="WP-2", x=105, y=100, origin="manual", confidence=1.0,
                      confirmed=True, evidence=[])
        db.add(old)
        db.commit()
        first = migrate.backfill_wireless_points(db, p)
        assert first == {"wireless_renamed": 1, "wireless_tied": 1, "wireless_untied": 0}
        db.refresh(old)
        assert old.label == "WIFI-2" and old.space_key == a and old.tie_source == "auto"
        second = migrate.backfill_wireless_points(db, p)
        assert second == {"wireless_renamed": 0, "wireless_tied": 0, "wireless_untied": 0}
    # The next point carries the numbering on.
    assert _ap(client, pid, 110, 100)["label"] == "WIFI-3"


# ---------------------------------------------------------------------------
# The workbook
# ---------------------------------------------------------------------------

def test_the_workbook_filters_every_sheet_and_computes_utilisation_live(client):
    pid = _project("wp-workbook")
    _room(pid, "OFF.050", "Office", 100, 100)
    _teap(pid, "OFF.050", "Office", OFFICE)
    _ner(pid, "NER A", 100, 120, total_ports=24)
    _match(client, pid)
    _ap(client, pid, 100, 105)
    _ap(client, pid, 110, 105)
    _analyse(pid)
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    wb = openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])

    for ws in wb.worksheets:
        if ws.title == "Summary":
            continue
        assert ws.auto_filter.ref, f"no filter on {ws.title}"
        assert ws.auto_filter.ref.startswith("A1:"), ws.auto_filter.ref

    ws = wb["NERs and ports"]
    head = [c.value for c in ws[1]]
    # 3.0.0: Full name B, Space code C, Notes last; the rest in its old order
    assert head == ["NER", "Full name", "Space code", "Page", "Critical", "Indoor / outdoor",
                    "Spaces served", "Ports assigned", "Total ports", "Utilisation %",
                    "Wireless points", "of which wireless ports", "Fibre runs to TER", "Notes"]
    row = [c.value for c in ws[2]]
    assert row[7] == 5 and row[8] == 24, row                 # 4 laptops + DWISA (4.0.0)
    assert row[9] == '=IF(OR(I2="",I2=0),"",H2/I2)' and ws["J2"].number_format == "0.0%"
    assert row[10:12] == [2, 1]                                # APs drawn, DWISA ports

    ws = wb["TEAP and coverage"]
    head = [c.value for c in ws[1]]
    assert head[-2:] == ["Needs validation", "Counted ports"]
    by_product = {r[7].value: r for r in ws.iter_rows(min_row=2)}
    assert by_product["Laptop"][9].value == 4 and by_product["Laptop"][-1].value == 4
    assert by_product[DWISA][9].value == 1, "the TEAP as it arrived"
    assert by_product[DWISA][-1].value == 1, "counted: the DWISA line is the wireless port"

    ws = wb["Wireless points"]
    head = [c.value for c in ws[1]]
    # 4.0.0: no Ports column — an access point has no port of its own
    # 4.5.0: "Indoor / outdoor" beside the type
    assert head == ["Wireless point", "Type", "Indoor / outdoor", "Page", "Serving NER",
                    "Distance (m)", "Status", "TEAP space", "Tie", "Notes"]
    rows = {r[0].value: [c.value for c in r] for r in ws.iter_rows(min_row=2)}
    assert rows["WIFI-1"][1] == "Wi-Fi" and rows["WIFI-2"][1] == "Wi-Fi"
    assert rows["WIFI-1"][7] == "Office" and rows["WIFI-1"][8] == "proposed"
