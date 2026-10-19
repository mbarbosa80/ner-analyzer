"""4.1.0 — several books in one project: a sheet is a book *and* a page.

Marcelo, 16 Oct 2026, loading the 300, 400 and 600 series of ALA into one
project: *"cada documento tem sua própria numeração de páginas, começando em 1
… os desenhos ficaram um pouco bagunçados e a localização dos espaços ficou
desorganizada."* The database kept ``(drawing_id, page)`` but everything above
it compared the page number alone, so page 2 of one book and page 2 of another
were one sheet: rooms drawn on the wrong one, distances measured across two
coordinate systems, the viewer always opening the first book.

A sheet key (``app.sheets``) names the sheet everywhere above the database. In
a one-book project it **is** the page number — nothing changes there — and in a
multi-book project it is ``drawing_id * 10000 + page``.
"""

from __future__ import annotations

import pathlib

import openpyxl
import pymupdf
import pytest
from sqlalchemy import select

from tests.test_wireless_tie_250 import TMP, _line, client  # noqa: F401
from app import migrate
from app import services as S
from app import sheets as SH
from app.config import settings
from app.db import SessionLocal
from app.models import (AuditLog, Drawing, DrawingSpace, Element, NerAsset, Page, Project,
                        TeapFile, TeapSpace)


def _pdf(name: str, pages: int) -> str:
    path = pathlib.Path(TMP) / name
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=1000, height=700)
    doc.save(str(path))
    doc.close()
    return str(path)


def _two_books(name: str) -> tuple[int, int, int]:
    """A 400 book (1 unit = 1 m) and a 600 book (1 unit = 0.5 m), two pages each."""
    with SessionLocal() as db:
        p = Project(name=name, venue_code="VEN")
        db.add(p)
        db.flush()
        ids = []
        for fn, mpu in (("VEN_400_XXX_OP.pdf", 1.0), ("VEN_600_XXX_OP.pdf", 0.5)):
            d = Drawing(project_id=p.id, filename=fn, stored_path=_pdf(f"{p.id}-{fn}", 2),
                        sha256="x" * 64, page_count=2)
            db.add(d)
            db.flush()
            for n in (1, 2):
                db.add(Page(drawing_id=d.id, number=n, width=1000, height=700,
                            metres_per_unit=mpu, scale_label=f"{mpu} m/u",
                            scale_source="manual", scale_confirmed=True, level="LEVEL 01",
                            sheet_number=f"VEN-{fn[4:7]}{n}-X"))
            ids.append(d.id)
        db.add(TeapFile(project_id=p.id, filename="teap.xlsx", stored_path=f"{TMP}/t.xlsx",
                        sha256="y" * 64))
        db.commit()
        return p.id, ids[0], ids[1]


def _room(pid, did, page, code, x, y):
    with SessionLocal() as db:
        r = DrawingSpace(project_id=pid, drawing_id=did, page=page, space_code=code,
                         name=code, x=x, y=y, confidence=0.9)
        db.add(r)
        db.commit()
        return r.id


def _teap(pid, code, ports=4):
    with SessionLocal() as db:
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        db.add(TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"VEN|{code}",
                         space_code=code, space_name=code, total_ports=ports,
                         lines=[_line("Laptop", ports, ports, "LAP")]))
        db.commit()


def _ner(pid, did, page, label, x, y):
    with SessionLocal() as db:
        e = Element(project_id=pid, drawing_id=did, page=page, kind="NER_NONCRITICAL",
                    label=label, x=x, y=y, origin="manual", confidence=1.0, confirmed=True)
        db.add(e)
        db.commit()
        migrate.backfill_assets(db, db.get(Project, pid))
        return e.id


def _key(did, page):
    return did * SH.STRIDE + page


def _analyse(client, pid):
    r = client.post(f"/api/projects/{pid}/analyse")
    assert r.status_code == 200, r.text
    return {a["space_key"]: a for a in r.json()["assignments"]}


# ---------------------------------------------------------------------------
# One book: the keys are the page numbers
# ---------------------------------------------------------------------------

def test_a_one_book_project_keeps_its_page_numbers(client):
    from tests.test_wireless_tie_250 import _project
    pid = _project("one book 410")
    proj = client.get(f"/api/projects/{pid}").json()
    assert proj["multi_book"] is False
    assert [(pg["number"], pg["page"]) for pg in proj["pages"]] == [(1, 1)]
    with SessionLocal() as db:
        sh = SH.for_project(db, pid)
        assert sh.key(sh.only, 7) == 7 and sh.split(1) == (sh.only, 1)
        assert sh.label(7) == "page 7"
        # A page the only book does not have is refused (4.2.1, D18).
        import pytest
        with pytest.raises(SH.SheetError):
            sh.split(7)


# ---------------------------------------------------------------------------
# Two books: every page 1 is its own sheet
# ---------------------------------------------------------------------------

def test_every_page_1_is_its_own_sheet(client):
    pid, a, b = _two_books("two books sheets")
    proj = client.get(f"/api/projects/{pid}").json()
    assert proj["multi_book"] is True
    assert [pg["number"] for pg in proj["pages"]] == [_key(a, 1), _key(a, 2), _key(b, 1), _key(b, 2)]
    assert proj["pages"][2]["sheet_label"] == "VEN-6001-X (600 p.1)"
    # A bare page number names no sheet of a two-book project.
    assert client.get(f"/api/projects/{pid}/elements?page=1").status_code == 404


def test_markers_and_rooms_stay_on_their_own_book(client):
    pid, a, b = _two_books("two books markers")
    _room(pid, a, 1, "AAA.001", 100, 100)
    _room(pid, b, 1, "BBB.001", 100, 100)
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": _key(b, 1), "kind": "TER", "label": "TER 1", "x": 50, "y": 60})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        e = db.get(Element, r.json()["id"])
        assert (e.drawing_id, e.page) == (b, 1)       # it used to go to the first book
    on_a = client.get(f"/api/projects/{pid}/elements?page={_key(a, 1)}").json()
    on_b = client.get(f"/api/projects/{pid}/elements?page={_key(b, 1)}").json()
    assert [e["label"] for e in on_a] == [] and [e["label"] for e in on_b] == ["TER 1"]
    assert on_b[0]["page"] == _key(b, 1)
    sp_a = client.get(f"/api/projects/{pid}/drawing-spaces?page={_key(a, 1)}").json()
    assert [s["space_code"] for s in sp_a] == ["AAA.001"]


def test_a_ner_on_another_books_page_1_does_not_serve(client):
    """The space is on page 1 of the 600 book; the only NER is on page 1 of the
    400 book. Same page number, another sheet: nothing is measured."""
    pid, a, b = _two_books("two books coverage")
    _room(pid, b, 1, "SPC.001", 100, 100)
    _teap(pid, "SPC.001")
    _ner(pid, a, 1, "NER 21", 110, 100)
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    rows = _analyse(client, pid)
    assert rows["VEN|SPC.001"]["status"] == "not_analysable"
    assert rows["VEN|SPC.001"]["ner_label"] is None


def test_the_distance_uses_the_scale_of_its_own_book(client):
    pid, a, b = _two_books("two books scale")
    _room(pid, b, 2, "SPC.002", 100, 100)
    _teap(pid, "SPC.002")
    _ner(pid, b, 2, "NER 22", 140, 100)            # 40 units on the 600 book = 20 m
    _ner(pid, a, 2, "NER 23", 100, 100)            # same x, y on the 400 book's page 2
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    row = _analyse(client, pid)["VEN|SPC.002"]
    assert row["ner_label"] == "NER 22"
    assert row["evaluation"]["effective_distance_m"] == pytest.approx(20.0)
    assert row["page"] == _key(b, 2)


def test_a_key_plan_in_one_book_is_not_one_in_the_other(client):
    pid, a, b = _two_books("two books key plans")
    r = client.post(f"/api/projects/{pid}/pages/key-plans", json={"pages": {str(_key(a, 1)): True}})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert S.key_plan_pages(db, pid) == {_key(a, 1)}
        assert S.key_plan_numbers(db, a) == {1} and S.key_plan_numbers(db, b) == set()


def test_the_same_code_in_two_books_is_linked_on_the_same_level(client):
    pid, a, b = _two_books("two books links")
    first = _room(pid, a, 2, "PRS.006", 100, 100)
    other = _room(pid, b, 1, "PRS.006", 300, 300)
    _teap(pid, "PRS.006")
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    links = client.get(f"/api/projects/{pid}/occurrence-links").json()
    assert len(links) == 1 and links[0]["drawing_space_id"] in (first, other)
    assert links[0]["verdict"] == "confirmed"
    ev = " ".join(links[0]["evidence"])
    assert "VEN-4002-X (400 p.2)" in ev and "VEN-6001-X (600 p.1)" in ev, ev


def test_the_marked_pdf_has_every_book(client):
    pid, a, b = _two_books("two books pdf")
    _ner(pid, a, 1, "NER 24", 100, 100)
    _ner(pid, b, 2, "NER 25", 200, 200)
    r = client.post(f"/api/projects/{pid}/reports/pdf?background=false")
    assert r.status_code == 200, r.text
    out = settings.exports_dir / f"project_{pid}" / r.json()["file"]
    with pymupdf.open(str(out)) as doc:
        assert doc.page_count == 4
        assert "NER 24" in doc[0].get_text() and "NER 24" not in doc[2].get_text()
        assert "NER 25" in doc[3].get_text() and "NER 25" not in doc[1].get_text()


def test_the_workbook_names_the_sheet(client):
    pid, a, b = _two_books("two books workbook")
    _room(pid, b, 2, "SPC.003", 100, 100)
    _teap(pid, "SPC.003")
    _ner(pid, b, 2, "NER 26", 120, 100)
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    _analyse(client, pid)
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    cells = {str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row}
    assert "VEN-6002-X (600 p.2)" in cells
    assert str(_key(b, 2)) not in cells


def test_a_guessed_three_digit_level_is_taken_back():
    """The 600 series' seat counts ("142") were read as the level of the
    sheet and of the NERs created there."""
    pid, a, b = _two_books("two books guessed level")
    with SessionLocal() as db:
        pg = db.execute(select(Page).where(Page.drawing_id == b, Page.number == 1)).scalar_one()
        pg.level = "142"
        db.commit()
    eid = _ner(pid, b, 1, "NER 27", 10, 10)
    with SessionLocal() as db:
        e = db.get(Element, eid)
        assert e.ner_asset.level == "142"
        assert migrate.clear_guessed_levels(db, db.get(Project, pid)) == {"guessed_levels_cleared": 1}
        db.refresh(e.ner_asset)
        assert e.ner_asset.level is None
        assert db.execute(select(Page).where(Page.drawing_id == b, Page.number == 1)
                          ).scalar_one().level is None
        assert db.execute(select(AuditLog).where(
            AuditLog.project_id == pid,
            AuditLog.action == "page.guessed_level_cleared")).first() is not None
        # Idempotent, and a "LEVEL 01" is never touched.
        assert migrate.clear_guessed_levels(db, db.get(Project, pid)) == {"guessed_levels_cleared": 0}
