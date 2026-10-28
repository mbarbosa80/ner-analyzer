"""2.18.1 — deleting a NER deletes it everywhere.

Marcelo, 13 Oct 2026: a NER drawn on several sheets, deleted in the Drawing
viewer, stayed on the other sheets and in the NERs list; and a NER removed on
the NERs screen came back when the NERs were placed from the drawing again.

What this file holds:

* the viewer's Delete of a NER marker removes **the NER** — every marker of it
  disappears from ``GET /elements`` on every page, the row leaves the live
  list and sits under *removed*, with a reason that names the page and the
  other sheets; Restore brings every page back without redrawing anything;
* ``scope=marker`` is the narrower act: this one drawing goes, the NER stays
  on its other sheets; when it was the last marker the NER is retired (the
  behaviour every version before this one had);
* a marker of a removed NER still occupies its spot, so the "is there a NER
  here already?" test says yes and the placing pass does not create the room
  again;
* the other kinds of marker (a TER) are plain rows and are simply deleted;
* a locked NER cannot be deleted from the viewer.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-2181-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2181.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import AuditLog, Drawing, Element, NerAsset, Page, Project  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


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


def _pdf(path: str, pages: int = 3) -> str:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=1000, height=700)
    doc.save(path)
    doc.close()
    return path


def _project(name: str) -> int:
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=_pdf(f"{TMP}/{name}.pdf"),
                    sha256="x" * 64, page_count=3)
        db.add(d)
        db.flush()
        for n in (1, 2, 3):
            db.add(Page(drawing_id=d.id, number=n, width=1000, height=700, metres_per_unit=1.0,
                        scale_label="1u=1m", scale_source="manual", scale_confirmed=True,
                        level="LEVEL 01"))
        db.commit()
        return p.id


def _marker(pid: int, label: str, page: int, x: float, y: float, *, kind="NER_NONCRITICAL",
            asset_id=None) -> int:
    with SessionLocal() as db:
        p = db.get(Project, pid)
        e = Element(project_id=pid, drawing_id=p.drawings[0].id, page=page, kind=kind,
                    label=label, x=x, y=y, origin="manual", confidence=1.0, confirmed=True,
                    ner_asset_id=asset_id, link_status="confirmed" if asset_id else "unlinked")
        db.add(e)
        db.commit()
        if asset_id is None and kind.startswith("NER_"):
            migrate.backfill_assets(db, db.get(Project, pid))
        db.refresh(e)
        return e.id


def _ner_on_pages(pid: int, label: str, pages: tuple[int, ...]) -> tuple[int, list[int]]:
    """One register NER drawn on several sheets: (asset id, [element ids])."""
    first = _marker(pid, label, pages[0], 400, 300)
    with SessionLocal() as db:
        asset_id = db.get(Element, first).ner_asset_id
    assert asset_id is not None
    ids = [first] + [_marker(pid, label, n, 400, 300, asset_id=asset_id) for n in pages[1:]]
    return asset_id, ids


def _pages_drawn(client, pid: int, label: str) -> list[int]:
    return sorted({e["page"] for e in client.get(f"/api/projects/{pid}/elements").json()
                   if e["label"] == label})


def _live_names(client, pid: int) -> list[str]:
    return [r["display_name"] for r in client.get(f"/api/projects/{pid}/ners").json()["ners"]]


# ---------------------------------------------------------------------------
# 1. Delete in the viewer = the NER leaves every page and the list
# ---------------------------------------------------------------------------

def test_deleting_a_ner_marker_in_the_viewer_removes_the_ner_from_every_page(client):
    pid = _project("delete-everywhere")
    asset_id, ids = _ner_on_pages(pid, "NER 21", (1, 2, 3))
    assert _pages_drawn(client, pid, "NER 21") == [1, 2, 3]
    assert "NER 21" in _live_names(client, pid)

    # Delete on page 2 — the middle sheet, not the first and not the last.
    assert client.delete(f"/api/projects/{pid}/elements/{ids[1]}").status_code == 204

    assert _pages_drawn(client, pid, "NER 21") == [], "no page draws it any more"
    for n in (1, 2, 3):
        assert "NER 21" not in [e["label"] for e in
                                client.get(f"/api/projects/{pid}/elements?page={n}").json()]
    assert "NER 21" not in _live_names(client, pid), "gone from the NERs list"
    removed = [r for r in client.get(f"/api/projects/{pid}/ners?include_removed=true").json()["ners"]
               if r["id"] == asset_id]
    assert removed and removed[0]["deleted_at"]
    assert "page 2" in removed[0]["deleted_reason"]
    assert "1, 3" in removed[0]["deleted_reason"], "the reason names the other sheets"
    # the register's own positions layer hides it too
    assert asset_id not in {r["id"] for r in
                            client.get(f"/api/projects/{pid}/ner-assets/positions").json()["positions"]}
    with SessionLocal() as db:
        a = db.get(NerAsset, asset_id)
        assert a.deleted_at is not None and len(list(a.occurrences)) == 3, \
            "the markers stay in the table, hidden with their room"
        log = db.execute(select(AuditLog).where(AuditLog.project_id == pid)
                         .order_by(AuditLog.id.desc())).scalars().first()
        assert log.action == "ner.removed" and log.entity_id == asset_id


def test_restore_brings_every_page_back(client):
    pid = _project("restore-everywhere")
    asset_id, ids = _ner_on_pages(pid, "NER 22", (1, 2, 3))
    assert client.delete(f"/api/projects/{pid}/elements/{ids[2]}").status_code == 204
    assert _pages_drawn(client, pid, "NER 22") == []
    assert client.post(f"/api/projects/{pid}/ners/{asset_id}/restore").status_code == 200
    assert _pages_drawn(client, pid, "NER 22") == [1, 2, 3]
    assert "NER 22" in _live_names(client, pid)
    with SessionLocal() as db:
        log = db.execute(select(AuditLog).where(AuditLog.project_id == pid,
                                                 AuditLog.action == "ner.restored")).scalars().all()
        assert log and "marker_redrawn" not in (log[-1].payload or {}), \
            "nothing to redraw — the markers were never deleted"


def test_the_analysis_and_the_export_no_longer_see_the_deleted_ner(client):
    pid = _project("delete-analysis")
    asset_id, ids = _ner_on_pages(pid, "NER 23", (1, 2))
    keep_id = _marker(pid, "NER 24", 1, 50, 50)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        assert {n.label for n in S.register_ners(db, p)} == {"NER 23", "NER 24"}
        assert {n.label for n in S.rooms_to_draw(db, p)} == {"NER 23", "NER 24"}
    assert client.delete(f"/api/projects/{pid}/elements/{ids[0]}").status_code == 204
    with SessionLocal() as db:
        p = db.get(Project, pid)
        assert {n.label for n in S.register_ners(db, p)} == {"NER 24"}
        assert {n.label for n in S.rooms_to_draw(db, p)} == {"NER 24"}
    assert keep_id  # the other room is untouched


# ---------------------------------------------------------------------------
# 2. scope=marker — the narrower act
# ---------------------------------------------------------------------------

def test_scope_marker_deletes_this_drawing_only_and_keeps_the_ner(client):
    pid = _project("marker-only")
    asset_id, ids = _ner_on_pages(pid, "NER 25", (1, 2, 3))
    assert client.delete(f"/api/projects/{pid}/elements/{ids[1]}?scope=marker").status_code == 204
    assert _pages_drawn(client, pid, "NER 25") == [1, 3]
    assert "NER 25" in _live_names(client, pid)
    with SessionLocal() as db:
        a = db.get(NerAsset, asset_id)
        assert a.deleted_at is None and sorted(o.page for o in a.occurrences) == [1, 3]
        log = db.execute(select(AuditLog).where(AuditLog.project_id == pid,
                                                 AuditLog.action == "element.deleted")).scalars().all()
        assert log and log[-1].payload.get("scope") == "marker" and log[-1].payload.get("page") == 2


def test_scope_marker_on_the_last_marker_retires_the_ner(client):
    pid = _project("marker-last")
    asset_id, ids = _ner_on_pages(pid, "NER 26", (2,))
    assert client.delete(f"/api/projects/{pid}/elements/{ids[0]}?scope=marker").status_code == 204
    assert "NER 26" not in _live_names(client, pid)
    with SessionLocal() as db:
        a = db.get(NerAsset, asset_id)
        assert a.deleted_at is not None and not list(a.occurrences)
        assert "last document occurrence" in a.deleted_reason


def test_scope_must_be_ner_or_marker(client):
    pid = _project("scope-bad")
    _, ids = _ner_on_pages(pid, "NER 27", (1,))
    assert client.delete(f"/api/projects/{pid}/elements/{ids[0]}?scope=everything").status_code == 422


# ---------------------------------------------------------------------------
# 3. A removed NER keeps its spot — the placing pass does not bring it back
# ---------------------------------------------------------------------------

def test_a_removed_ners_marker_still_occupies_its_spot(client):
    pid = _project("occupied")
    asset_id, ids = _ner_on_pages(pid, "NER 28", (1,))
    with SessionLocal() as db:
        p = db.get(Project, pid)
        assert S._ner_marker_near(db, p, 1, 403, 302) is not None
    # removed on the NERs screen
    r = client.post(f"/api/projects/{pid}/ners/{asset_id}/remove",
                    json={"reason": "not in the design", "actor": "user"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        p = db.get(Project, pid)
        near = S._ner_marker_near(db, p, 1, 403, 302)
        assert near is not None and near.ner_asset_id == asset_id, \
            "the spot is taken by the removed room — nothing is created there"
        assert S._ner_marker_near(db, p, 1, 900, 600) is None


def test_placing_from_the_drawing_does_not_recreate_a_removed_annotation(client):
    pid = _project("no-resurrection")
    asset_id, ids = _ner_on_pages(pid, "NER 29", (1,))
    with SessionLocal() as db:
        d = db.get(Project, pid).drawings[0]
        d.extract_summary = {"ner_annotations": [
            {"page": 1, "kind": "NER_NONCRITICAL", "label": "NER 29", "x": 402.0, "y": 301.0,
             "confidence": 0.9, "evidence": ["test"], "color": None}]}
        db.commit()
    assert client.post(f"/api/projects/{pid}/ners/{asset_id}/remove",
                       json={"reason": "wrong rack", "actor": "user"}).status_code == 200
    before = _live_names(client, pid)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        totals = S.place_ners_from_drawing(db, p, actor="tests")
    assert totals["created"] == 0
    assert totals["annotations_on_removed"] == 1
    assert _live_names(client, pid) == before
    assert _pages_drawn(client, pid, "NER 29") == []


def test_a_room_printed_where_a_removed_ner_stood_is_not_created_again(client):
    """The drawn-rooms pass (TEC codes, labels, symbols) answers the same way."""
    from types import SimpleNamespace
    pid = _project("no-resurrection-room")
    asset_id, ids = _ner_on_pages(pid, "NER 30", (1,))
    assert client.post(f"/api/projects/{pid}/ners/{asset_id}/remove",
                       json={"reason": "wrong rack", "actor": "user"}).status_code == 200
    room = SimpleNamespace(page=1, x=405.0, y=303.0, label_x=405.0, label_y=303.0,
                           code="TEC.020-003", text="TEC.020-003", critical=False,
                           source="code", via_leader=False, evidence=["test"])
    with SessionLocal() as db:
        p = db.get(Project, pid)
        stats = S.adopt_drawn_rooms(db, p, p.drawings[0], [room], actor="tests")
    assert stats["created"] == 0 and stats["on_removed_ner"] == 1
    assert _pages_drawn(client, pid, "NER 30") == []
    assert "NER 30" not in _live_names(client, pid)


# ---------------------------------------------------------------------------
# 4. Other markers, locks
# ---------------------------------------------------------------------------

def test_a_ter_is_simply_deleted(client):
    pid = _project("ter-delete")
    tid = _marker(pid, "TER", 1, 100, 100, kind="TER")
    assert client.delete(f"/api/projects/{pid}/elements/{tid}").status_code == 204
    with SessionLocal() as db:
        assert db.get(Element, tid) is None
    assert client.delete(f"/api/projects/{pid}/elements/{tid}").status_code == 404


def test_a_locked_ner_cannot_be_deleted_from_the_viewer(client):
    pid = _project("locked-delete")
    asset_id, ids = _ner_on_pages(pid, "NER 31", (1, 2))
    assert client.post(f"/api/projects/{pid}/ners/{asset_id}/lock",
                       json={"locked": True, "actor": "user"}).status_code == 200
    assert client.delete(f"/api/projects/{pid}/elements/{ids[0]}").status_code == 409
    assert client.delete(f"/api/projects/{pid}/elements/{ids[0]}?scope=marker").status_code == 409
    assert _pages_drawn(client, pid, "NER 31") == [1, 2]


# ---------------------------------------------------------------------------
# 5. The interface says what Delete does
# ---------------------------------------------------------------------------

def test_the_viewer_and_the_ners_screen_carry_the_new_wording():
    viewer = (ROOT / "frontend/src/pages/Viewer.tsx").read_text(encoding="utf-8")
    assert "Delete the NER" in viewer and "Delete only this marker" in viewer
    assert 'scope: "ner" | "marker"' in viewer
    api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
    assert "?scope=${scope}" in api
    reg = (ROOT / "frontend/src/pages/NerRegister.tsx").read_text(encoding="utf-8")
    assert "Other NER rows carry the same name" in reg
    pt = (ROOT / "frontend/src/lib/strings.pt.ts").read_text(encoding="utf-8")
    for key in ("Delete the NER", "Delete only this marker", "Other NER rows carry the same name"):
        assert f'"{key}"' in pt


# ---------------------------------------------------------------------------
# 6. The installer and the server see the same environment (2.18.1)
# ---------------------------------------------------------------------------

def test_pip_and_the_server_ignore_the_users_own_site_packages():
    """Found on the work laptop, 9 Oct 2026: a stray
    %APPDATA%\\Python\\Python312\\site-packages\\pymupdf made pip say "already
    satisfied", nothing was copied into .python\\, and the isolated server
    started without pymupdf. pip, the component check and the server now all
    run without the user site."""
    bat = (ROOT / "install.bat").read_bytes().decode("utf-8")
    assert "\r\n" in bat, "batch files keep CRLF"
    embedded = [ln for ln in bat.splitlines()
                if ".python\\python.exe" in ln and "pip" in ln and "install" in ln]
    assert embedded, "the embedded-runtime pip lines are there"
    for ln in embedded:
        assert " -s " in ln, ln
        assert "--ignore-installed" in ln, ln
    venv = [ln for ln in bat.splitlines() if ".venv\\Scripts\\python.exe" in ln and "find-links vendor" in ln]
    assert venv and all(" -s " in ln for ln in venv)
    assert "set PYTHONNOUSERSITE=1" in bat
    assert "%PY% -s tools\\check_env.py" in bat
    assert 'env["PYTHONNOUSERSITE"] = "1"' in (ROOT / "run.py").read_text(encoding="utf-8")
    serve = (ROOT / "tools" / "serve.py").read_text(encoding="utf-8")
    assert "getusersitepackages" in serve and 'os.environ["PYTHONNOUSERSITE"] = "1"' in serve
