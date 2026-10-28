"""4.6.0 — hand a project to another computer; one book in a project once.

Marcelo, 27 Oct 2026:

* "Se eu subir o mesmo arquivo duas vezes, vc aceita e não critica. Ou evite
  isso ou me deixe apagar desenhos/vdb repetidos" — the same book is refused,
  and a book can be removed from the Import screen;
* several books chosen at once in the file dialog (held by a source check);
* the page numbers on Demand per space open the Drawing viewer (source check);
* "poder exportar todo o projeto no estado atual e permitir que outro VTCM
  importe e dê continuidade" — the package: every row and every document of a
  project in one .zip, imported as a new project owned by whoever imports it.

The decisive test is the round trip: a project worked through the real
screens' API (book, TEAP, scales, matching, a hand tie, a pinned NER, Wi-Fi
points, the analysis) is exported, imported, and must come back with the same
rows, the same documents byte for byte and the same analysis.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-460-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t460.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import func, select                                # noqa: E402

from app import services as S                                      # noqa: E402
from app import transfer as TR                                     # noqa: E402
from app.config import settings                                    # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (AuditLog, Drawing, DrawingSpace, Element, NerAsset, Page,  # noqa: E402
                        Project, SpaceMatchRow, TeapSpace, User, Zone)
from app.sample_data import build_all                              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PANELS = (ROOT / "frontend" / "src" / "pages" / "panels.tsx").read_text(encoding="utf-8")
API_TS = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")


def _sign_in(c: TestClient, username: str = "tester", admin: bool = True) -> None:
    from app import auth as A
    with SessionLocal() as db:
        try:
            A.create_user(db, username=username, password="a-long-test-phrase",
                          display_name=username, is_admin=admin, actor="tests")
        except A.AuthError:
            pass
    r = c.post("/api/auth/login", json={"username": username, "password": "a-long-test-phrase"})
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def client():
    init_db()
    c = TestClient(app)
    _sign_in(c)
    return c


@pytest.fixture(scope="module")
def samples():
    return build_all(str(Path(TMP) / "samples460"))


def _worked_project(client, samples, name: str) -> int:
    """A project taken through the real steps, with decisions of a person."""
    r = client.post("/api/projects", json={"name": name, "venue_code": "SYN"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    with open(samples["pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings?place_ners=true",
                        files={"file": ("plan.pdf", fh, "application/pdf")})
    assert r.status_code == 201, r.text
    with open(samples["teap"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/teap", files={"file": ("teap.xlsx", fh, "x")})
    assert r.status_code == 201, r.text
    tid, proposed = r.json()["id"], r.json()["proposed"]
    r = client.post(f"/api/projects/{pid}/teap/{tid}/import",
                    json={"sheet": proposed["sheet"], "header_row": proposed["header_row"],
                          "mapping": proposed["mapping"]})
    assert r.status_code == 200, r.text
    for page in (1, 2):
        assert client.post(f"/api/projects/{pid}/pages/{page}/scale",
                           json={"denominator": 200.0, "confirm": True}).status_code == 200
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    for m in client.get(f"/api/projects/{pid}/matches", params={"only_review": True}).json():
        client.patch(f"/api/projects/{pid}/matches/{m['id']}",
                     json={"confirmed": True, "justification": "test fixture"})
    # A NER pinned by hand for the space with most ports, a Wi-Fi point, a zone.
    with SessionLocal() as db:
        t = db.execute(select(TeapSpace).where(TeapSpace.project_id == pid)
                       .order_by(TeapSpace.total_ports.desc())).scalars().first()
        a = db.execute(select(NerAsset).where(NerAsset.project_id == pid,
                                              NerAsset.deleted_at.is_(None))
                       .order_by(NerAsset.id.desc())).scalars().first()
        key, aid = t.space_key, a.id
    r = client.post(f"/api/projects/{pid}/spaces/{key}/assign",
                    json={"ner_asset_id": aid, "justification": "the nearer one is full"})
    assert r.status_code == 200, r.text
    client.post(f"/api/projects/{pid}/wireless/place-from-teap")
    r = client.post(f"/api/projects/{pid}/zones",
                    json={"page": 1, "kind": "area", "label": "BTOC", "polygon":
                          [[10, 10], [60, 10], [60, 40]]})
    assert r.status_code in (200, 201), r.text
    r = client.post(f"/api/projects/{pid}/analyse")
    assert r.status_code == 200, r.text
    return pid


def _counts(pid: int) -> dict:
    with SessionLocal() as db:
        out = {}
        for name, model, _fk in TR.TABLES:
            if name == "pages":
                q = select(func.count(Page.id)).join(Drawing).where(Drawing.project_id == pid)
            elif name == "ner_name_history":
                continue
            elif name == "audit_log":
                continue                       # the import adds its own lines
            else:
                q = select(func.count(model.id)).where(model.project_id == pid)
            out[name] = db.execute(q).scalar()
        return out


def _demand(client, pid) -> dict:
    rows = client.get(f"/api/projects/{pid}/spaces/assignments").json()["spaces"]
    return {r["space_key"]: (r["status"], r["serving_ner"], r["assigned_ner"],
                             round(r["distance_m"] or 0, 3), r["ports"]) for r in rows}


def _export(client, pid) -> bytes:
    r = client.post(f"/api/projects/{pid}/export?background=false")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"].startswith("NER-project_") and body["filename"].endswith(".zip")
    dl = client.get(f"/api/projects/{pid}/export/{body['filename']}")
    assert dl.status_code == 200
    return dl.content


def _import(client, blob: bytes, name: str = "", fname: str = "p.zip"):
    return client.post(f"/api/projects/import?background=false&name={name}",
                       files={"file": (fname, blob, "application/zip")})


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------

def test_a_project_comes_back_whole_on_the_other_computer(client, samples):
    pid = _worked_project(client, samples, "Handover Venue")
    before = _counts(pid)
    demand_before = _demand(client, pid)
    blob = _export(client, pid)

    z = zipfile.ZipFile(io.BytesIO(blob))
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["format"] == TR.FORMAT and manifest["app_version"] == settings.version
    assert manifest["project"]["name"] == "Handover Venue"
    names = z.namelist()
    assert any(n.startswith("files/drawings/") and n.endswith("plan.pdf") for n in names)
    assert any(n.startswith("files/teap/") for n in names)
    data = json.loads(z.read("data.json"))
    assert "users" not in data["tables"], "accounts never travel"
    assert "password_hash" not in z.read("data.json").decode()

    r = _import(client, blob)
    assert r.status_code == 201, r.text
    out = r.json()
    new = out["project_id"]
    assert new != pid
    # The name is taken here already: the copy says it is one.
    assert out["name"].startswith("Handover Venue (imported ")
    assert out["analysis"]["same"] is True, out["analysis"]

    assert _counts(new) == before
    assert _demand(client, new) == demand_before
    with SessionLocal() as db:
        p = db.get(Project, new)
        me = db.execute(select(User).where(User.username == "tester")).scalar_one()
        assert p.owner_id == me.id and p.visibility == "private"
        assert p.venue_code == "SYN"
        # Documents byte for byte, in the new project's own folder.
        for d_old, d_new in zip(
                db.execute(select(Drawing).where(Drawing.project_id == pid)
                           .order_by(Drawing.id)).scalars(),
                db.execute(select(Drawing).where(Drawing.project_id == new)
                           .order_by(Drawing.id)).scalars()):
            assert d_new.sha256 == d_old.sha256 == S.sha256_file(Path(d_new.stored_path))
            assert Path(d_new.stored_path).parent == settings.uploads_dir / f"project_{new}"
        # The person's decisions came along.
        pinned = db.execute(select(TeapSpace).where(TeapSpace.project_id == new,
                                                    TeapSpace.assigned_ner_asset_id.is_not(None))
                            ).scalars().all()
        assert pinned and all(db.get(NerAsset, t.assigned_ner_asset_id).project_id == new
                              for t in pinned)
        for e in db.execute(select(Element).where(Element.project_id == new)).scalars():
            if e.ner_asset_id:
                assert db.get(NerAsset, e.ner_asset_id).project_id == new
            assert e.drawing_id is None or db.get(Drawing, e.drawing_id).project_id == new
        for m in db.execute(select(SpaceMatchRow).where(SpaceMatchRow.project_id == new)).scalars():
            if m.drawing_space_id:
                assert db.get(DrawingSpace, m.drawing_space_id).project_id == new
        assert db.execute(select(Zone).where(Zone.project_id == new)).scalars().first().label == "BTOC"
        actions = {a.action for a in db.execute(select(AuditLog).where(
            AuditLog.project_id == new)).scalars()}
        # Its history came with it, and the import is on it.
        assert {"project.imported", "drawing.ingested", "teap.imported"} <= actions
    # The original is untouched.
    assert _counts(pid) == before


def test_the_viewer_serves_the_imported_book(client, samples):
    pid = _worked_project(client, samples, "Viewer Copy")
    new = _import(client, _export(client, pid), name="Viewer Copy B").json()["project_id"]
    proj = client.get(f"/api/projects/{new}").json()
    assert proj["name"] == "Viewer Copy B"
    did = proj["drawings"][0]["id"]
    r = client.get(f"/api/projects/{new}/drawings/{did}/file")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# A package is untrusted
# ---------------------------------------------------------------------------

def _uploads_dirs() -> set[str]:
    return {d.name for d in settings.uploads_dir.iterdir()} if settings.uploads_dir.exists() else set()


def _rewrite(blob: bytes, change) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for info in src.infolist():
            data = src.read(info)
            data = change(info.filename, data)
            if data is not None:
                z.writestr(info.filename, data)
    return out.getvalue()


@pytest.fixture(scope="module")
def package(client, samples):
    return _export(client, _worked_project(client, samples, "Package Source"))


def test_a_book_altered_in_transit_is_refused_and_leaves_nothing(client, package):
    def flip(name, data):
        if name.startswith("files/drawings/"):
            return data[:-10] + b"0123456789"
        return data
    with SessionLocal() as db:
        n_before = db.execute(select(func.count(Project.id))).scalar()
    dirs = _uploads_dirs()
    r = _import(client, _rewrite(package, flip))
    assert r.status_code == 422 and "does not match" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.execute(select(func.count(Project.id))).scalar() == n_before
    assert _uploads_dirs() == dirs
    assert not list((settings.data_dir / "imports").glob("*"))


def test_altered_data_is_refused(client, package):
    def edit(name, data):
        return data.replace(b"Package Source", b"Package Sourcf") if name == "data.json" else data
    r = _import(client, _rewrite(package, edit))
    assert r.status_code == 422 and "does not match its manifest" in r.json()["detail"]


def test_a_package_from_a_newer_app_is_refused(client, package):
    def newer(name, data):
        if name == "manifest.json":
            m = json.loads(data)
            m["app_version"] = "99.0.0"
            return json.dumps(m).encode()
        return data
    r = _import(client, _rewrite(package, newer))
    assert r.status_code == 422 and "Update the app here first" in r.json()["detail"]


def test_a_member_outside_the_files_folder_is_refused(client, package):
    def evil(name, data):
        if name == "manifest.json":
            m = json.loads(data)
            m["files"].append({"member": "../../evil.pdf", "kind": "drawings", "id": 1,
                               "bytes": 3, "sha256": "x"})
            return json.dumps(m).encode()
        return data
    r = _import(client, _rewrite(package, evil))
    assert r.status_code == 422 and "may not hold" in r.json()["detail"]
    assert not (settings.data_dir.parent / "evil.pdf").exists()


def test_a_file_that_is_not_a_package_is_refused(client):
    assert _import(client, b"not a zip").status_code == 422
    other = io.BytesIO()
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("hello.txt", "hi")
    r = _import(client, other.getvalue())
    assert r.status_code == 422 and "not a project package" in r.json()["detail"]
    assert _import(client, b"x", fname="p.pdf").status_code == 422


def test_a_reader_of_a_shared_project_can_take_a_copy(client, samples):
    pid = _worked_project(client, samples, "Shared For Reading")
    assert client.post(f"/api/projects/{pid}/visibility",
                       json={"visibility": "shared"}).status_code == 200
    other = TestClient(app)
    _sign_in(other, "reader460", admin=False)
    assert other.post(f"/api/projects/{pid}/matching/run").status_code == 403
    r = other.post(f"/api/projects/{pid}/export?background=false")
    assert r.status_code == 200, r.text
    blob = other.get(f"/api/projects/{pid}/export/{r.json()['filename']}").content
    r = _import(other, blob, name="My own copy 460")
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        p = db.get(Project, r.json()["project_id"])
        assert db.get(User, p.owner_id).username == "reader460"


def test_the_download_name_is_checked(client, samples):
    pid = client.post("/api/projects", json={"name": "Dl Check 460"}).json()["id"]
    assert client.get(f"/api/projects/{pid}/export/..%2F..%2Fner.sqlite3").status_code == 404
    assert client.get(f"/api/projects/{pid}/export/NER-project_x.zip").status_code == 404


# ---------------------------------------------------------------------------
# One book once, and a book can be removed
# ---------------------------------------------------------------------------

def test_the_same_book_twice_is_refused(client, samples):
    pid = client.post("/api/projects", json={"name": "Dup Venue 460"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        assert client.post(f"/api/projects/{pid}/drawings",
                           files={"file": ("plan.pdf", fh, "application/pdf")}).status_code == 201
    before = sorted(p.name for p in (settings.uploads_dir / f"project_{pid}").iterdir())
    with open(samples["pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings",
                        files={"file": ("plan copy.pdf", fh, "application/pdf")})
    assert r.status_code == 409 and "the same file" in r.json()["detail"]
    with open(samples["scanned_pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings",
                        files={"file": ("PLAN.pdf", fh, "application/pdf")})
    assert r.status_code == 409 and "new revision" in r.json()["detail"]
    after = sorted(p.name for p in (settings.uploads_dir / f"project_{pid}").iterdir())
    assert after == before, "a refused file is not kept"
    assert len(client.get(f"/api/projects/{pid}").json()["drawings"]) == 1


def test_the_job_refuses_a_twin_that_arrived_together(client, samples):
    pid = client.post("/api/projects", json={"name": "Dup Job 460"}).json()["id"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        S.ingest_drawing(db, p, Path(S.store_upload(pid, "a.pdf", open(samples["pdf"], "rb"))), "a.pdf")
        with pytest.raises(S.ValidationError, match="the same file"):
            S.ingest_drawing(db, p, Path(S.store_upload(pid, "b.pdf", open(samples["pdf"], "rb"))),
                             "b.pdf")


def test_removing_a_book_keeps_what_lives_on_another_book(client, samples):
    pid = _worked_project(client, samples, "Two Books 460")
    with open(samples["scanned_pdf"], "rb") as fh:
        r = client.post(f"/api/projects/{pid}/drawings",
                        files={"file": ("second.pdf", fh, "application/pdf")})
    assert r.status_code == 201, r.text
    second = r.json()["id"]
    with SessionLocal() as db:
        first = db.execute(select(Drawing.id).where(Drawing.project_id == pid)
                           .order_by(Drawing.id)).scalars().first()
        assets = db.execute(select(NerAsset).where(NerAsset.project_id == pid,
                                                   NerAsset.deleted_at.is_(None))
                            .order_by(NerAsset.id)).scalars().all()
        both, only = assets[0], assets[1]
        # ``both`` is also drawn on the second book.
        db.add(Element(project_id=pid, drawing_id=second, page=1, kind="NER_NONCRITICAL",
                       label=both.display_name, x=5, y=6, origin="manual",
                       ner_asset_id=both.id, link_status="confirmed"))
        db.commit()
        both_id, only_id, both_name, only_name = both.id, only.id, both.display_name, only.display_name
        tied = db.execute(select(func.count(TeapSpace.id)).where(
            TeapSpace.project_id == pid, TeapSpace.locked_drawing_space_id.is_not(None))).scalar()
        path = Path(db.get(Drawing, first).stored_path)
    imp = client.get(f"/api/projects/{pid}/drawings/{first}/impact").json()
    assert only_name in imp["ners_only_here"] and both_name not in imp["ners_only_here"]
    assert imp["ties"] == tied

    r = client.delete(f"/api/projects/{pid}/drawings/{first}")
    assert r.status_code == 200, r.text
    out = r.json()
    assert both_name in out["ners_moved"] and only_name in out["ners_removed"]
    assert len(out["ties_released"]) == tied
    assert not path.exists()
    with SessionLocal() as db:
        assert db.get(Drawing, first) is None
        b = db.get(NerAsset, both_id)
        assert b.deleted_at is None and b.canonical_drawing_id == second
        assert (b.canonical_x, b.canonical_y) == (5, 6)
        o = db.get(NerAsset, only_id)
        assert o.deleted_at is not None and o.position_known is False
        assert "removed from the project" in o.deleted_reason
        assert not db.execute(select(Element).where(Element.project_id == pid,
                                                    Element.drawing_id == first)).first()
        # The zone had no book recorded: it was the first book's, and went with it.
        assert not db.execute(select(Zone).where(Zone.project_id == pid)).first()
        assert not db.execute(select(TeapSpace).where(
            TeapSpace.project_id == pid, TeapSpace.locked_verdict == "assigned",
            TeapSpace.locked_drawing_space_id.is_(None))).first()
        assert db.execute(select(AuditLog).where(AuditLog.project_id == pid,
                                                 AuditLog.action == "drawing.deleted")).first()
    assert [d["id"] for d in client.get(f"/api/projects/{pid}").json()["drawings"]] == [second]


def test_a_book_of_another_project_cannot_be_removed(client, samples):
    a = client.post("/api/projects", json={"name": "Owner A 460"}).json()["id"]
    b = client.post("/api/projects", json={"name": "Owner B 460"}).json()["id"]
    with open(samples["pdf"], "rb") as fh:
        did = client.post(f"/api/projects/{a}/drawings",
                          files={"file": ("plan.pdf", fh, "application/pdf")}).json()["id"]
    assert client.delete(f"/api/projects/{b}/drawings/{did}").status_code == 404
    assert client.get(f"/api/projects/{a}").json()["drawings"][0]["id"] == did


# ---------------------------------------------------------------------------
# The screens
# ---------------------------------------------------------------------------

def test_several_books_can_be_chosen_at_once():
    m = re.search(r'<input type="file" accept="application/pdf"[^>]*>', PANELS, re.S)
    assert m and "multiple" in m.group(0)
    assert "uploadDrawings" in PANELS
    # One after the other, each to its end, so a twin is refused, not raced.
    assert "startAndWait" in PANELS


def test_a_book_can_be_removed_from_the_import_screen():
    assert "deleteDrawing" in API_TS and "drawingImpact" in API_TS
    assert "removeDrawing" in PANELS and "duplicate_of" in PANELS


def test_demand_pages_open_the_viewer():
    demand = PANELS[PANELS.index("export function DemandPanel"):PANELS.index("export function ExceptionsPanel")]
    # The space's page, the same space on other pages, the Wi-Fi points and
    # the NER load: every page shown is a way to the sheet.
    assert demand.count("<PageButton") >= 4
    assert "{pageName(p, w.page)}" not in demand
    assert "{sheetNo(p, v.page)}" not in demand


def test_the_projects_screen_exports_and_imports():
    assert "exportProject" in API_TS and "importProject" in API_TS
    assert "exportDownloadUrl" in API_TS
    projects = PANELS[PANELS.index("export function ProjectsPanel"):PANELS.index("export function SetupPanel")]
    assert "Export" in projects and "Import a project package" in projects
