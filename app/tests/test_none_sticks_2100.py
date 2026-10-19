"""2.10.0 — "— none —" on TEAP × drawing is an answer that survives a re-run.

Marcelo, 24 Sep 2026: *"qdo eu realmente não encontro com o que cruzar… eu
prefiro poder escolher none e isso valer. toda hora que eu escolho none e
fecho e volto e rodo um run matching essa informação se perde"*. Choosing
none used to *clear* the decision, so the next run proposed the matcher's
room again. It now records "not on this drawing" on the TEAP line; the
space enters the analysis with no room, and a NER chosen for it on Demand
serves it (counted, not measured).
"""

from __future__ import annotations

from tests.test_wireless_tie_250 import (_analyse, _line, _match, _ner,  # noqa: F401
                                         _project, _room, _teap, client)


def test_none_is_kept_across_a_matching_run_and_undo_takes_it_back(client):
    pid = _project("none-sticks")
    _room(pid, "OFF.050", "Office", 100, 100)
    key = _teap(pid, "OFF.050", "Office", [_line("Laptop", 3, 3, "LAP", 1)])
    el = _ner(pid, "NER 21", 100, 120)
    from app.db import SessionLocal
    from app.models import Element
    with SessionLocal() as db:
        a = db.get(Element, el).ner_asset_id          # the register id, not the marker's
    _match(client, pid)
    row = next(m for m in client.get(f"/api/projects/{pid}/matches?all=true").json()
               if m["teap_code"] == "OFF.050")
    assert row["drawing_space_id"], "the matcher found the room"

    # what the screen sends when "— none —" is picked
    r = client.patch(f"/api/projects/{pid}/matches/{row['id']}",
                     json={"rejected": True, "justification": "no room on this drawing"})
    assert r.status_code == 200 and r.json()["drawing_space_id"] is None

    _match(client, pid)                                   # the re-run
    row = next(m for m in client.get(f"/api/projects/{pid}/matches?all=true").json()
               if m["teap_code"] == "OFF.050")
    assert row["drawing_space_id"] is None and row["locked"] == "rejected"

    # no room: pending until a NER is chosen; chosen, it is served (not measured)
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                    json={"ner_asset_id": a, "justification": "I know the venue"})
    assert r.status_code == 200 and r.json()["unplaced"] is True
    _analyse(pid)
    sp = {s["space_key"]: s for s in
          client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"]}[key]
    assert sp["status"] == "assigned_not_placed" and sp["group"] == "not_measured"

    # Undo gives the matcher's room back
    r = client.post(f"/api/projects/{pid}/matches/{row['id']}/undo", json={"justification": "x"})
    assert r.status_code == 200
    _match(client, pid)
    row = next(m for m in client.get(f"/api/projects/{pid}/matches?all=true").json()
               if m["teap_code"] == "OFF.050")
    assert row["drawing_space_id"] and not row["locked"]
