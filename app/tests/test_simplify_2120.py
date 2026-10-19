"""2.12.0 — fewer tiles, one exceptions list, a search box, a name check.

Marcelo, 25 Sep 2026:

* TEAP × drawing needs three tiles — TEAP spaces, matched, no room found —
  and "no room found" and "not on this drawing (rejected by you)" are the
  same answer;
* the Drawing viewer needs a search for the names on the sheet;
* placing a NER under the name of one that exists must ask whether it is the
  same NER on another page or whether to choose another name;
* the Exceptions step showed a near-limit space he then could not find on
  Demand per space, and did not show everything that was left out.
"""

from __future__ import annotations

import os
import re

from sqlalchemy import select

from tests.test_wireless_serve_2110 import _ner_on, _two_pages
from tests.test_wireless_tie_250 import (_analyse, _line, _match, _room, _teap,  # noqa: F401
                                         client)
from app.db import SessionLocal
from app.models import Element, NerAsset


def _src(*parts) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return open(os.path.join(here, "..", "frontend", "src", *parts), encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. Three tiles on TEAP × drawing
# ---------------------------------------------------------------------------

def test_teap_by_drawing_has_exactly_three_tiles():
    panels = _src("pages", "panels.tsx")
    block = panels[panels.index("const TILE_ROWS"):panels.index("export function MatchingPanel")]
    keys = re.findall(r'\[\s*"([a-z_]+)",\s*"', block)
    assert keys == ["all", "matched", "no_room"], keys
    # the rejected rows are in "no room found", not a tile of their own
    assert '"not on this drawing (rejected by you)"' not in panels
    assert '"confirmed by you"' not in block


# ---------------------------------------------------------------------------
# 2. The NER name check
# ---------------------------------------------------------------------------

def test_a_ner_placed_as_the_same_one_joins_it_and_takes_its_name(client):
    pid = _two_pages("same-name-2120")
    first = _ner_on(pid, "NER 21", 100, 100, page=1)
    with SessionLocal() as db:
        before = db.execute(select(NerAsset).where(NerAsset.project_id == pid)).scalars().all()
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 2, "kind": "NER_CRITICAL", "label": "ner21", "x": 50, "y": 60,
                          "same_as_asset_id": first})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ner_asset_id"] == first, "one room, not a second one"
    with SessionLocal() as db:
        after = db.execute(select(NerAsset).where(NerAsset.project_id == pid)).scalars().all()
        e = db.get(Element, body["id"])
        assert len(after) == len(before)
        assert e.label == "NER 21", "the marker takes the room's name"
        assert e.link_status == "confirmed"
        # the room was drawn with the non-critical tool; its classification wins
        assert e.kind == "NER_NONCRITICAL"
        pages = sorted(x.page for x in db.get(NerAsset, first).occurrences)
        assert pages == [1, 2]


def test_same_as_is_refused_for_anything_but_a_ner(client):
    pid = _two_pages("same-name-2120-ter")
    first = _ner_on(pid, "NER 22", 100, 100, page=1)
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 2, "kind": "TER", "label": "TER", "x": 5, "y": 5,
                          "same_as_asset_id": first})
    assert r.status_code == 422
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 2, "kind": "NER_NONCRITICAL", "label": "NER 22", "x": 5, "y": 5,
                          "same_as_asset_id": 987654})
    assert r.status_code == 404


def test_the_viewer_asks_before_reusing_a_ner_name():
    viewer = _src("pages", "Viewer.tsx")
    assert "export function nerNameKey" in viewer
    assert "same_as_asset_id: sameAs ? sameAs.id : undefined" in viewer
    assert "Cancel — it is a different room: choose another name." in viewer


# ---------------------------------------------------------------------------
# 3. The search box
# ---------------------------------------------------------------------------

def test_the_viewer_has_a_search_over_every_page():
    viewer = _src("pages", "Viewer.tsx")
    assert 'className="viewer-search"' in viewer
    # the index is built from every page: no page argument on these calls
    assert "api.drawingSpaces(p.id), api.elements(p.id), api.zones(p.id)" in viewer
    assert "const goTo = (hit: any)" in viewer


# ---------------------------------------------------------------------------
# 4. Exceptions from the Demand rows, with the other NERs and their distance
# ---------------------------------------------------------------------------

def test_assignments_carry_the_other_ners_without_the_serving_one(client):
    pid = _two_pages("alts-2120")
    _room(pid, "SPP.001", "SPP Work Room", 100, 100)
    key = _teap(pid, "SPP.001", "SPP Work Room", [_line("Laptop", 2, 2, "LAP", 1)])
    near = _ner_on(pid, "NERc 02", 180, 100, page=1)     # 80 m
    _ner_on(pid, "NER 27", 100, 150, page=1)             # 50 m — nearest
    _ner_on(pid, "NERc 07", 100, 300, page=1)            # 200 m
    _match(client, pid)
    # confirm the match so the run measures it
    for m in client.get(f"/api/projects/{pid}/matches").json():
        client.patch(f"/api/projects/{pid}/matches/{m['id']}",
                     json={"confirmed": True, "drawing_space_id": m["drawing_space_id"],
                           "justification": "ok"})
    # he pins the 80 m one: the nearest is then an alternative, the pin is not
    assert client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                       json={"ner_asset_id": near, "justification": "critical"}).status_code == 200
    _analyse(pid)
    row = next(s for s in client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"]
               if s["space_key"] == key)
    assert row["serving_ner"] == "NERc 02"
    labels = [a["label"] for a in row["alternatives"]]
    assert labels == ["NER 27", "NERc 07"], labels
    assert row["alternatives"][0]["distance_m"] == 50.0
    assert all(isinstance(a["ner_asset_id"], int) for a in row["alternatives"])


def test_the_exceptions_step_reads_the_demand_rows():
    panels = _src("pages", "panels.tsx")
    block = panels[panels.index("type ExKey"):panels.index("export function ReportsPanel")]
    assert "api.assignments(p.id)" in block
    assert "res.exceptions" not in block, "no second, private run"
    # every pile a space can need you in, near the limit included
    for k in ('"pending"', '"problem"', '"near"', '"not_measured"'):
        assert k in block
    assert "openInDemand(ctx" in block and "openInViewer(ctx" in block
    # Demand has the search box the hand-off fills, and a near-limit counter
    demand = panels[panels.index("export function DemandPanel"):panels.index("export function ExceptionsPanel")]
    assert "HANDOFF.demand" in demand and "rowMatches(q, s, i)" in demand
    assert '"status:near_limit"' in demand
