"""2.14.1 — the marked-up PDF with an access point on it, and no name left undefined.

Marcelo, 29 Sep 2026, first export after 2.14.0: ``NameError: name 'wcol' is
not defined``. Folding the two access-point kinds into one (2.14.0) removed
the line that chose the label colour by kind and left the name behind; no test
exported a PDF with a wireless point in the analysis, so 781 tests passed over
it. Two things stay from that:

* an export with an access point on the sheet, end to end;
* a scan of every backend module for a name used in a function that nothing
  defines — module, import, builtin, enclosing scope — because Python only
  raises that at the line, and a branch no test walks hides it until a person
  presses the button.
"""

from __future__ import annotations

import builtins
import os
import symtable
import tempfile
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-2141-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2141.sqlite3")

from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.main import app                                           # noqa: E402
from app.models import (Drawing, DrawingSpace, Element, Page, Project,  # noqa: E402
                        TeapFile, TeapSpace)

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app"
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


def _pdf(path: str) -> str:
    doc = pymupdf.open()
    doc.new_page(width=1000, height=700)
    doc.save(path)
    doc.close()
    return path


def _line(product, qty, ports, code="X", row=1):
    return {"row": row, "product": product, "code": code, "qty": qty, "ports": ports,
            "rule": "A", "explanation": ""}


def _project(name) -> int:
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.flush()
        d = Drawing(project_id=p.id, filename="d.pdf", stored_path=_pdf(f"{TMP}/{name}.pdf"),
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


def test_the_marked_pdf_draws_an_access_point_and_its_label(client):
    pid = _project("ap-on-paper")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        did = p.drawings[0].id
        db.add(DrawingSpace(project_id=pid, drawing_id=did, page=1, space_code="OFF.010",
                            name="Office", x=100, y=100, confidence=0.9))
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key="TST|OFF.010",
                         space_code="OFF.010", space_name="Office", total_ports=5,
                         lines=[_line("Laptop", 4, 4, "LAP", 1), _line(DWISA, 1, 1, "DWISA", 2)],
                         wireless_required=True))
        e = Element(project_id=pid, drawing_id=did, page=1, kind="NER_NONCRITICAL",
                    label="NER 1", x=100, y=120, origin="manual", confidence=1.0,
                    confirmed=True, total_ports=48)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        db.commit()
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": "WIRELESS", "label": "", "x": 95, "y": 105})
    assert r.status_code == 201, r.text
    ap_label = r.json()["label"]
    assert ap_label.startswith("WIFI-")

    with SessionLocal() as db:
        p = db.get(Project, pid)
        result, ners = S.analyse(db, p)
        S.save_scenario(db, p, "As-Is", "as_is", result, ners)
        db.commit()
    assert any(a.kind == "wireless_point" for a in result.assignments)

    r = client.post(f"/api/projects/{pid}/reports/pdf?background=false")
    assert r.status_code == 200, r.text
    from app.config import settings
    doc = pymupdf.open(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    text = doc[0].get_text()
    doc.close()
    assert ap_label in text, "the access point's label is on the sheet"
    assert "Wi-Fi - space with wireless" in text, "and the legend names it"


# ---------------------------------------------------------------------------
# No name used in a function that nothing defines
# ---------------------------------------------------------------------------

def _undefined_names(path: Path) -> list[str]:
    """Names a function reads as *global* that the module never binds.

    ``symtable`` marks every name a function reads without binding as global
    (or free, when an enclosing function binds it); a global name that is not
    bound at module level, not a builtin and not injected by the module's
    ``__all__``/``globals()`` tricks is a NameError waiting for its line.
    """
    src = path.read_text(encoding="utf-8")
    top = symtable.symtable(src, str(path), "exec")
    module_names = {s.get_name() for s in top.get_symbols()
                    if s.is_assigned() or s.is_imported() or s.is_parameter()}
    module_names |= {c.get_name() for c in top.get_children()}
    module_names |= set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__",
                                          "__loader__", "__package__", "__builtins__",
                                          "__path__", "__annotations__"}
    found: list[str] = []
    where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name

    def walk(table: symtable.SymbolTable) -> None:
        for sym in table.get_symbols():
            if sym.is_global() and sym.is_referenced() and not sym.is_assigned():
                if sym.get_name() not in module_names:
                    found.append(f"{where}: {table.get_name()}: {sym.get_name()}")
        for child in table.get_children():
            walk(child)

    for child in top.get_children():
        walk(child)
    return found


def test_no_function_in_the_backend_reads_a_name_nothing_defines():
    problems: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        problems.extend(_undefined_names(path))
    assert not problems, "\n".join(problems)


def test_the_checker_sees_an_undefined_name(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import os\n\ndef f(x):\n    return os.sep + wcol + x\n", encoding="utf-8")
    names = [p.rsplit(": ", 1)[1] for p in _undefined_names(bad)]
    assert names == ["wcol"]
    good = tmp_path / "good.py"
    good.write_text("import os\nY = 1\n\ndef f(x):\n    def g():\n        return x + Y\n"
                    "    return os.sep + str(g())\n", encoding="utf-8")
    assert _undefined_names(good) == []
