"""2.12.1 — what the 26 Sep 2026 manual review found in the application.

Reviewing the whole manual against the code (Marcelo: *"revise e reescreva
todo o manual de acordo com a última versão"*) turned up defects that were
better fixed than documented:

* a TEAP imported with **no venue column mapped**, in a project that has a
  venue code, was filtered by that code anyway — no row matched, the import
  "succeeded" with nothing, and the TEAP already in the project was deleted;
* an import that finds **no row** now refuses and leaves the TEAP as it was;
* an old **.xls** passed the upload filter and failed as a server error;
* picking a **different room** on a row the matcher had confirmed kept the
  old confirmation until the next run;
* Save rules failed silently, and a new shaft was not drawn until the page
  changed (front-end, checked in the source).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-2121-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2121.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import func, select                                # noqa: E402

from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import SpaceMatchRow, TeapSpace                    # noqa: E402
from app.sample_data import build_teap                             # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"


@pytest.fixture(scope="module")
def client():
    init_db()
    c = TestClient(app)
    from app import auth as A
    with SessionLocal() as db:
        try:
            A.create_user(db, username="tester2121", password="a-long-test-phrase",
                          display_name="Test User", is_admin=True, actor="tests")
            db.commit()
        except A.AuthError:
            pass
    assert c.post("/api/auth/login", json={"username": "tester2121",
                                           "password": "a-long-test-phrase"}).status_code == 200
    return c


def _upload(client, pid, name="t.xlsx"):
    path = build_teap(f"{TMP}/{name}")
    with open(path, "rb") as fh:
        up = client.post(f"/api/projects/{pid}/teap",
                         files={"file": (name, fh, "application/octet-stream")})
    assert up.status_code == 201, up.text
    return up.json()["id"], up.json()["proposed"]


def _count(pid):
    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(TeapSpace)
                          .where(TeapSpace.project_id == pid)).scalar()


def test_no_venue_column_means_no_venue_filter(client):
    pid = client.post("/api/projects", json={"name": "novenue", "venue_code": "SYN"}).json()["id"]
    teap_id, proposed = _upload(client, pid)
    mapping = {**proposed["mapping"], "venue_code": None, "venue_name": None}
    r = client.post(f"/api/projects/{pid}/teap/{teap_id}/import",
                    json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                          "mapping": mapping, "venue_filter": None})
    assert r.status_code == 200, r.text
    assert _count(pid) > 0, "the whole sheet is imported, not filtered to nothing"


def test_an_import_that_finds_nothing_keeps_the_teap(client):
    pid = client.post("/api/projects", json={"name": "keep", "venue_code": "SYN"}).json()["id"]
    teap_id, proposed = _upload(client, pid, "k.xlsx")
    body = {"sheet": proposed["sheet"], "header_row": proposed["header_row"],
            "mapping": proposed["mapping"], "venue_filter": "SYN"}
    assert client.post(f"/api/projects/{pid}/teap/{teap_id}/import", json=body).status_code == 200
    before = _count(pid)
    assert before > 0
    body["venue_filter"] = "NO-SUCH-VENUE"
    r = client.post(f"/api/projects/{pid}/teap/{teap_id}/import", json=body)
    assert r.status_code == 422, r.text
    assert "nothing to import" in r.text and "left as it was" in r.text
    assert _count(pid) == before


def test_an_old_xls_is_refused_with_a_reason(client):
    pid = client.post("/api/projects", json={"name": "xls"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/teap",
                    files={"file": ("old.xls", b"\xd0\xcf\x11\xe0 not really", "application/vnd.ms-excel")})
    assert r.status_code == 422
    assert "save it as .xlsx" in r.text


def test_a_different_room_drops_the_old_confirmation(client):
    pid = client.post("/api/projects", json={"name": "reconf", "venue_code": "SYN"}).json()["id"]
    teap_id, proposed = _upload(client, pid, "r.xlsx")
    client.post(f"/api/projects/{pid}/teap/{teap_id}/import",
                json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                      "mapping": proposed["mapping"], "venue_filter": "SYN"})
    with SessionLocal() as db:
        t = db.execute(select(TeapSpace).where(TeapSpace.project_id == pid)).scalars().first()
        m = SpaceMatchRow(project_id=pid, teap_space_id=t.id, drawing_space_id=None,
                          method="exact_code", confidence=0.98, confirmed=True)
        db.add(m)
        db.flush()
        m.drawing_space_id = 1001
        S.record_match_decision(db, m, drawing_space_id=1002)
        assert m.drawing_space_id == 1002 and m.method == "manual"
        assert m.confirmed is False and m.confirmed_by is None
        assert t.locked_confirmed is False and t.locked_verdict == "assigned"
        # Re-sending the same room with Confirm signs it.
        S.record_match_decision(db, m, drawing_space_id=1002, confirmed=True)
        assert m.confirmed is True
        db.rollback()


def test_the_front_end_fixes_are_in_place():
    panels = (SRC / "pages" / "panels.tsx").read_text(encoding="utf-8")
    assert 'accept=".xlsx,.xlsm,.csv"' in panels
    assert 't("Rules not saved")' in panels
    viewer = (SRC / "pages" / "Viewer.tsx").read_text(encoding="utf-8")
    i = viewer.index('kind: "shaft"')
    assert "await reloadAll();" in viewer[i:i + 300]
