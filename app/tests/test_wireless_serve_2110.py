"""2.11.0 — the NER of a wireless point.

Marcelo, 24 Sep 2026, on ALA page 6 (rooms served from page 7): "os AP
que eu coloquei nas salas da página 6, eu preciso associar uma NER. Já que
eu associei NER para os espaços… pq ao colocar AP nas mesmas salas a mesma
NER não foi atribuída… se isso não for possível me deixa dizer qual NER vai
atender esse AP. Lembrando da continha, 1 que já estava no TEAP + 1 - 1."

* a point tied to a TEAP space whose room was chosen follows that room;
* a NER chosen for the point itself wins, and releasing it goes back;
* the count stays TEAP − 1 + points: the room's load is the same port.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.test_wireless_tie_250 import (DWISA, TMP, _analyse, _ap, _line, _match,  # noqa: F401
                                         _room, _teap, client)
from app.db import SessionLocal
from app.models import Drawing, Element, Page, Project, TeapFile
from app import migrate


def _two_pages(name) -> int:
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=f"{TMP}/d.pdf",
                    sha256="z" * 64, page_count=2)
        db.add(d)
        db.flush()
        for n in (1, 2):
            db.add(Page(drawing_id=d.id, number=n, width=1000, height=700, metres_per_unit=1.0,
                        scale_label="1u=1m", scale_source="manual", scale_confirmed=True,
                        level="LEVEL 01"))
        db.add(TeapFile(project_id=p.id, filename="teap.xlsx", stored_path=f"{TMP}/t.xlsx",
                        sha256="y" * 64))
        db.commit()
        return p.id


def _ner_on(pid, label, x, y, page) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=page,
                    kind="NER_NONCRITICAL", label=label, x=x, y=y, origin="manual",
                    confidence=1.0, confirmed=True, total_ports=48)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        return e.ner_asset_id


def _rows(client, pid):
    body = client.get(f"/api/projects/{pid}/spaces/assignments").json()
    return body, {w["label"]: w for w in body["wireless_points"]}


def test_a_point_follows_the_room_chosen_for_its_space_and_can_be_chosen(client):
    pid = _two_pages("ap-serve")
    _room(pid, "IFO.001", "IF Offices", 100, 100)                  # page 1, no NER on it
    key = _teap(pid, "IFO.001", "IF Offices",
                [_line("Laptop", 4, 4, "LAP", 1), _line(DWISA, 1, 1, "DWISA", 2)])
    far = _ner_on(pid, "NER 23", 100, 120, page=2)                  # served from page 2
    other = _ner_on(pid, "NER 24", 500, 500, page=2)
    _match(client, pid)
    assert client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                       json={"ner_asset_id": far, "justification": "same level"}).status_code == 200
    ap = _ap(client, pid, 110, 105)
    assert ap["space_key"] == key, "tied to the room it sits in"
    _analyse(pid)

    body, w = _rows(client, pid)
    pt = w[ap["label"]]
    assert pt["serving_ner"] == "NER 23" and pt["space_ner"] == "NER 23"
    assert pt["status"] == "cross_level_not_measured"
    load = {r["label"]: r for r in body["ner_load"]}
    # TEAP 4 + 1 wireless (DWISA) on the space's room; the point adds none
    assert load["NER 23"]["assigned_ports"] == 5.0

    # a room chosen for the point itself wins …
    r = client.post(f"/api/projects/{pid}/wireless/{ap['id']}/serve",
                    json={"ner_asset_id": other, "justification": "closer riser"})
    assert r.status_code == 200
    _analyse(pid)
    body, w = _rows(client, pid)
    assert w[ap["label"]]["serving_ner"] == "NER 24"
    assert w[ap["label"]]["assigned_ner"] == "NER 24"
    load = {r["label"]: r for r in body["ner_load"]}
    # 4.0.0: the point moves, the port does not — it is the space's DWISA line
    assert load["NER 23"]["assigned_ports"] == 5.0 and load["NER 24"]["assigned_ports"] == 0.0
    assert load["NER 24"]["wireless_points"] == 1

    # … and releasing it goes back to the space's room
    client.post(f"/api/projects/{pid}/wireless/{ap['id']}/serve", json={"ner_asset_id": None})
    _analyse(pid)
    body, w = _rows(client, pid)
    assert w[ap["label"]]["serving_ner"] == "NER 23"
    with SessionLocal() as db:
        assert db.get(Element, ap["id"]).assigned_ner_asset_id is None
    # only a NER may serve
    assert client.post(f"/api/projects/{pid}/wireless/{ap['id']}/serve",
                       json={"ner_asset_id": 999999}).status_code == 404
