"""2.13.0 — key plans only illustrate, and the NER rooms the drawing prints become NERs.

Marcelo, 29 Sep 2026:

* *"TEC.003.01.XXX / TEC.003.02.XXX são Network Equipment Rack (NER) – Critical
  e Non-Critical … quando eu subir um VDB ou TVDB … coloque NER críticas ou não
  críticas onde você encontrar esses nomes … mas não faça isso nas páginas que
  são KEY Enlarge Plan"*; and, with a VBB screenshot, *"às vezes pode estar
  só assim também sem nenhum TEC.003 escrito ainda, mas tem essa informação …
  prefiro conferir e validar do que criar tudo do zero."*
* *"Não coloque space names em Key enlarge pages … todas as KEY enlarge PLAN
  pages são só ilustrativas e não podem entrar em todo cruzamento de TEAP x
  drawing. Essa informação fica do lado direito inferior onde tem o nome do
  drawing em title."*

His answers to the four questions: a room somebody already marked a NER
beside is taken as that NER (per place); the name is the code, or ``NERc
p9-1`` / ``NER p9-2``; a rack whose criticality the drawing does not state is
created non-critical with the criticality pending; and all of it applies to
the projects that already exist.

The PDFs here are synthetic — never a real venue document in a test.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

TMP = tempfile.mkdtemp(prefix="ner-2130-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2130.sqlite3")

from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app import ner_register as R                                  # noqa: E402
from app import services as S                                      # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.domain import drawn_rooms as D                            # noqa: E402
from app.domain.pdf_ingest import extract_drawing                  # noqa: E402
from app.models import (AuditLog, Drawing, DrawingSpace, Element, NerAsset,  # noqa: E402
                        NerConsolidation, Page, Project, TeapFile, TeapSpace)
from tests.test_wireless_tie_250 import _line, client  # noqa: E402,F401

BLACK = (0, 0, 0)
RED = (0.8, 0, 0)


# ---------------------------------------------------------------------------
# A synthetic design book
# ---------------------------------------------------------------------------

def _title_block(page, title: str, number: str) -> None:
    page.insert_text((1250, 700), "DRAWING TITLE", fontsize=7)
    page.insert_text((1250, 712), title, fontsize=11)
    page.insert_text((1250, 740), "DRAWING NUMBER", fontsize=7)
    page.insert_text((1250, 752), number, fontsize=11)
    page.insert_text((1250, 780), "SCALE 1:400", fontsize=7)   # 12 m = 85 pt


def _arrow(page, tip, *, down=True, parts=1, start=None) -> None:
    """A leader from ``start`` right then down to an arrowhead at ``tip``."""
    x, y = tip
    sx, sy = start
    sh = page.new_shape()
    if parts == 1:
        sh.draw_polyline([(sx, sy), (x, sy), (x, y)])
        sh.finish(color=BLACK, width=0.24, closePath=False)
    else:                                  # the stub and the drop as two paths
        sh.draw_line((sx, sy), (x, sy))
        sh.finish(color=BLACK, width=0.24, closePath=False)
        sh.draw_line((x, sy), (x, y))
        sh.finish(color=BLACK, width=0.24, closePath=False)
    d = -5 if down else 5
    sh.draw_polyline([(x - 1.2, y + d), (x + 1.2, y + d), (x, y), (x - 1.2, y + d)])
    sh.finish(color=BLACK, fill=BLACK, width=0.24)
    sh.commit()


def _label(page, x, y, lines, size=4.0, color=BLACK):
    """Stacked centred lines starting at baseline ``y`` — returns the text box."""
    pitch = size * 1.15
    for i, t in enumerate(lines):
        page.insert_text((x, y + i * pitch), t, fontsize=size, color=color)
    width = max(pymupdf.get_text_length(t, fontsize=size) for t in lines)
    return (x, y - size, x + width, y + (len(lines) - 1) * pitch + 1)


def make_book(path: Path, *, detail_pages: int = 1, extra=None) -> Path:
    doc = pymupdf.open()
    # page 1: a key plan — its rooms and its NER are pictures, nothing more
    p = doc.new_page(width=1400, height=800)
    _title_block(p, "KEY ENLARGED PLAN - LEVEL 01", "TST-401-XXX-O")
    _label(p, 100, 100, ["Network Equipment Rack (NER) - Critical"], size=8)
    p.insert_text((100, 106), "TEC.003.01-01", fontsize=4)
    _label(p, 400, 100, ["Office"], size=8)
    p.insert_text((400, 106), "OFF.050", fontsize=4)
    p.insert_text((600, 300), "Critical NER 3", fontsize=20, color=RED)
    for n in range(detail_pages):
        p = doc.new_page(width=1400, height=800)
        _title_block(p, f"ENLARGED PLAN LEVEL 01 AREA A{n + 1}", f"TST-410A{n + 1}-XXX-O")
        # a room with its code: the label sits in the room, no arrow
        _label(p, 100, 100, ["Network Equipment Rack (NER) - Critical"], size=8)
        p.insert_text((100, 106), "TEC.003.01-01", fontsize=4)
        _label(p, 400, 100, ["Office"], size=8)
        p.insert_text((400, 106), "OFF.050", fontsize=4)
        if n == 0:
            # a label with no code and an arrow to the room (the VBB book)
            box = _label(p, 600, 400, ["Network Equipment Rack (NER) -", "Non-Critical"])
            _arrow(p, (box[2] + 40, 470), start=(box[2] + 1, 399))
            # the same, the arrow drawn as two separate paths (VAA)
            box = _label(p, 900, 400, ["Network Equipment Rack (NER) -", "Critical"])
            _arrow(p, (box[2] + 30, 480), start=(box[2] + 1, 399), parts=2)
            # criticality not stated, no arrow
            _label(p, 300, 600, ["Network Equipment Rack (NER) -Placeholder"])
        if extra:
            extra(p, n)
    doc.save(str(path))
    doc.close()
    return path


def _project_with_book(name: str, book: Path) -> tuple[int, int]:
    with SessionLocal() as db:
        p = Project(name=name, venue_code="TST")
        db.add(p)
        db.commit()
        d = S.ingest_drawing(db, p, book, book.name, place_ners=True)
        return p.id, d.id


def _assets(pid: int) -> dict[str, NerAsset]:
    """Live register rows by their (sequential, 2.14.0) name."""
    with SessionLocal() as db:
        rows = db.execute(select(NerAsset).where(NerAsset.project_id == pid)).scalars().all()
        for a in rows:
            _ = list(a.occurrences)
            db.expunge(a)
        return {a.display_name: a for a in rows if a.deleted_at is None}


def _by_printed(pid: int) -> dict[str, NerAsset]:
    """The same rows by what the drawing printed (``suggested_name``) — the
    team's "Critical NER 7", the code "TEC.003.01-01"."""
    return {a.suggested_name: a for a in _assets(pid).values()}


def _pending_one(pid: int) -> NerAsset:
    return next(a for a in _assets(pid).values()
                if any(v.startswith("criticality:") for v in a.pending_validations))


@pytest.fixture(scope="module", autouse=True)
def _db():
    init_db()


# ---------------------------------------------------------------------------
# The rules on their own
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("KEY ENLARGED PLAN - LEVEL 01", True),
    ("KEY FLOOR PLAN-LEVEL 02", True),       # the VDD 300 book spells it so
    ("KEY FLOOR PLAN", True),
    ("Key Plan", True),
    ("ENLARGED PLAN LEVEL 01 AREA A5", False),
    ("KEYNOTES PLAN", False),
    ("FLOOR PLAN LEVEL 01 - GOLF - A1", False),
    ("", False), (None, False),
])
def test_a_key_plan_is_known_by_its_title(title, expected):
    assert D.is_key_plan_title(title) is expected


@pytest.mark.parametrize("text,code", [
    ("TEC.003.01-05", "TEC.003.01-05"),       # the usual spelling
    ("TEC.003.01.005", "TEC.003.01-05"),      # the one in the request
    ("TEC.003.02", "TEC.003.02"),             # VEE p22: a real room, no number
    ("TEC.003.02-01", "TEC.003.02-01"),
    ("TEC.004-02", None), ("TEC.003.03-01", None), ("TEC.003.010", None),
    ("SPT.003.01", None),
])
def test_tec003_codes_in_every_spelling(text, code):
    assert D.normalise_code(text) == code


def test_the_code_decides_the_criticality_and_the_words_only_when_there_is_none():
    assert D.criticality_from_code("TEC.003.01-05") is True
    assert D.criticality_from_code("TEC.003.02") is False
    assert D.criticality_from_words("Network Equipment Rack (NER) - Non-Critical") is False
    assert D.criticality_from_words("- Critical") is True
    assert D.criticality_from_words("-Placeholder") is None
    assert D.criticality_from_words("") is None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_rooms_are_read_off_the_detail_sheet_and_never_off_the_key_plan(tmp_path):
    ex = extract_drawing(str(make_book(tmp_path / "book.pdf")))
    assert [p.key_plan for p in ex.pages] == [True, False]
    rooms = ex.rooms
    assert all(r.page == 2 for r in rooms), "nothing is read off the key plan"
    by = {(r.code or r.text): r for r in rooms}
    coded = by["TEC.003.01-01"]
    assert coded.critical is True and coded.source == "code" and not coded.via_leader
    nc = by["Network Equipment Rack (NER) - Non-Critical"]
    assert nc.critical is False and nc.via_leader
    assert abs(nc.y - 470) < 1.5, "placed at the arrow's tip, not on the label"
    two = by["Network Equipment Rack (NER) - Critical"]
    assert two.critical is True and two.via_leader and abs(two.y - 480) < 1.5, \
        "a leader drawn as two paths is followed too"
    ph = by["Network Equipment Rack (NER) -Placeholder"]
    assert ph.critical is None and not ph.via_leader
    assert len(rooms) == 4


def test_a_ner_written_on_a_key_plan_arrives_as_a_reference(tmp_path):
    ex = extract_drawing(str(make_book(tmp_path / "book.pdf")))
    on_key = [e for e in ex.elements if e.page == 1]
    assert [e.kind for e in on_key] == ["NER_CRITICAL_REF"]
    assert any("key plan" in v for v in on_key[0].evidence)


def test_stacked_labels_each_follow_their_own_arrow(tmp_path):
    """The VBB screenshot: "Network Equipment Rack (NER) - Critical" over
    "Commentator Control Room (CCR)", an arrow from each; the NER's arrow is
    the one that leaves the NER's lines."""
    def extra(p, n):
        box = _label(p, 1000, 650, ["Network Equipment Rack (NER) -", "Critical",
                                    "Commentator Control Room (CCR)"])
        # NER: off the left of the first line, up to the NER room
        sh = p.new_shape()
        sh.draw_polyline([(999, 647), (960, 647), (960, 600)])
        sh.finish(color=BLACK, width=0.24, closePath=False)
        sh.draw_polyline([(958.8, 605), (961.2, 605), (960, 600), (958.8, 605)])
        sh.finish(color=BLACK, fill=BLACK, width=0.24)
        # CCR: off the right of the third line, up to the other room
        y3 = 650 + 2 * 4 * 1.15 - 1
        sh.draw_polyline([(box[2] + 1, y3), (box[2] + 20, y3), (box[2] + 20, 610)])
        sh.finish(color=BLACK, width=0.24, closePath=False)
        sh.draw_polyline([(box[2] + 18.8, 615), (box[2] + 21.2, 615), (box[2] + 20, 610),
                          (box[2] + 18.8, 615)])
        sh.finish(color=BLACK, fill=BLACK, width=0.24)
        sh.commit()
    ex = extract_drawing(str(make_book(tmp_path / "book.pdf", extra=extra)))
    r = next(r for r in ex.rooms if r.label_y > 640 and r.label_x > 990)
    assert r.critical is True and r.via_leader
    assert abs(r.x - 960) < 1.5 and abs(r.y - 600) < 1.5


def test_a_label_in_the_legend_is_not_a_room(tmp_path):
    def extra(p, n):
        p.insert_text((1250, 100), "LEGEND", fontsize=8)
        _label(p, 1250, 130, ["Network Equipment Rack (NER) - Critical"])
        p.insert_text((1250, 136), "TEC.003.01-99", fontsize=4)
    ex = extract_drawing(str(make_book(tmp_path / "book.pdf", extra=extra)))
    assert not [r for r in ex.rooms if r.label_x > 1200]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def test_an_import_creates_the_ners_the_drawing_prints(tmp_path, client):
    """Named in sequence since 2.14.0 — NERc_01.1 … / NER_20.1 … (2.18.0) — with what
    the sheet printed kept as "printed as"; the coded rooms come first."""
    pid, did = _project_with_book("drawn-1", make_book(tmp_path / "b1.pdf"))
    assets = _assets(pid)
    assert set(assets) == {"NERc_01.1", "NERc_02.1", "NER_20.1", "NER_21.1"}, set(assets)
    coded = assets["NERc_01.1"]
    assert coded.kind == "NER_CRITICAL" and coded.classification == "critical"
    assert coded.suggested_name == "TEC.003.01-01" and "TEC.003.01-01" in coded.aliases
    assert coded.space_code == "TEC.003.01-01" and coded.origin == "drawing_room"
    assert not coded.classification_confirmed, "the drawing's reading, for him to check"
    assert all(e.label == "NERc_01.1" for e in coded.occurrences), "one name, on the sheet too"
    ph = _pending_one(pid)
    assert ph.kind == "NER_NONCRITICAL" and ph.classification == "pending"
    assert any(v.startswith("position:") for v in ph.pending_validations)
    with SessionLocal() as db:
        d = db.get(Drawing, did)
        assert d.extract_summary["ner_pass"]["created"] == 4
        assert d.extract_summary["drawn_rooms"]["created"] == 4
        assert db.execute(select(AuditLog).where(
            AuditLog.project_id == pid, AuditLog.action == "ner.created_from_drawing")).first()
        assert db.execute(select(AuditLog).where(
            AuditLog.project_id == pid, AuditLog.action == "ner.placed_from_drawing")).first()
    # the key plan's rooms are listed nowhere — they are not even read
    spaces = client.get(f"/api/projects/{pid}/drawing-spaces").json()
    assert spaces and all(s["page"] != 1 for s in spaces)
    pages = client.get(f"/api/projects/{pid}").json()["pages"]
    assert [pg["key_plan"] for pg in pages] == [True, False]


def test_a_ner_already_marked_there_is_not_doubled(tmp_path):
    def extra(p, n):
        # the reviewers' red NERs: one beside the coded room (critical, agrees),
        # one beside the critical label (non-critical: disagrees)
        p.insert_text((110, 125), "Critical NER 7", fontsize=14, color=RED)
        p.insert_text((930, 500), "NER 9", fontsize=14, color=RED)
    pid, _ = _project_with_book("drawn-2", make_book(tmp_path / "b2.pdf", extra=extra))
    printed = _by_printed(pid)
    assert "TEC.003.01-01" not in printed
    seven = printed["Critical NER 7"]
    assert seven.display_name == "NERc_01.1" and seven.space_code == "TEC.003.01-01"
    assert any("taken as this NER" in v for v in seven.classification_evidence)
    n9 = printed["NER 9"]
    assert n9.display_name == "NER_20.1"
    assert any(v.startswith("criticality:") and "critical" in v for v in n9.pending_validations)
    # the rooms nobody marked are created, numbered on after the annotations
    assert set(_assets(pid)) == {"NERc_01.1", "NER_20.1", "NER_21.1", "NER_22.1"}, set(_assets(pid))


def test_racks_labelled_side_by_side_near_one_ner_make_no_new_ner(tmp_path):
    """VAA p4: three "Network Equipment Rack (NER) - Critical" labels,
    stacked, each with its arrow into the same cabin a few metres apart, and
    the team's one NER drawn there. His rule is "create only where there is
    no NER near" — so none is created, not two beside it."""
    def extra(p, n):
        p.insert_text((1060, 300), "Critical NER 5", fontsize=12, color=RED)
        for k in range(3):
            box = _label(p, 1000, 200 + k * 12, ["Network Equipment Rack (NER) - Critical"])
            _arrow(p, (box[2] + 20 + k * 6, 290), start=(box[2] + 1, 199 + k * 12))
    pid, _ = _project_with_book("drawn-cluster", make_book(tmp_path / "bc.pdf", extra=extra))
    five = _by_printed(pid)["Critical NER 5"]
    near = [v for v in five.classification_evidence if "taken as this NER" in v]
    assert len(near) == 3, near
    # the annotation, the coded room, the critical label, the two non-critical
    # labels — and nothing for the three racks beside Critical NER 5
    assert set(_assets(pid)) == {"NERc_01.1", "NERc_02.1", "NERc_03.1", "NER_20.1", "NER_21.1"}, set(_assets(pid))


def test_the_same_code_on_two_sheets_is_one_ner(tmp_path):
    pid, _ = _project_with_book("drawn-3", make_book(tmp_path / "b3.pdf", detail_pages=2))
    with SessionLocal() as db:
        rows = db.execute(select(NerAsset).where(NerAsset.project_id == pid,
                                                 NerAsset.space_code == "TEC.003.01-01")
                          ).scalars().all()
        assert len(rows) == 1
        assert sorted(e.page for e in rows[0].occurrences) == [2, 3]
        c = db.execute(select(NerConsolidation).where(
            NerConsolidation.project_id == pid,
            NerConsolidation.primary_asset_id == rows[0].id)).scalars().first()
        assert c is not None and "identical space code" in c.evidence[0]


def test_an_unstated_criticality_is_chosen_before_it_is_confirmed(tmp_path, client):
    pid, _ = _project_with_book("drawn-4", make_book(tmp_path / "b4.pdf"))
    a = _pending_one(pid)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        asset = db.get(NerAsset, a.id)
        with pytest.raises(R.RegisterError):
            R.set_confirmed(db, p, asset, confirmed=True)
        R.classify(db, p, asset, "critical", confirmed=True)
        db.refresh(asset)
        assert asset.kind == "NER_CRITICAL"
        assert not any(v.startswith("criticality:") for v in asset.pending_validations)
        assert all(e.kind == "NER_CRITICAL" for e in asset.occurrences)
        el = asset.occurrences[0].id
    # dragging it onto the room answers the position question
    r = client.patch(f"/api/projects/{pid}/elements/{el}", json={"x": 320, "y": 610})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert not any(v.startswith("position:")
                       for v in db.get(NerAsset, a.id).pending_validations)


# ---------------------------------------------------------------------------
# Key plans leave the TEAP × drawing crossing
# ---------------------------------------------------------------------------

def _teap(pid, code, name, ports=2) -> str:
    with SessionLocal() as db:
        tf = db.execute(select(TeapFile).where(TeapFile.project_id == pid)).scalars().first()
        if tf is None:
            tf = TeapFile(project_id=pid, filename="t.xlsx", stored_path=f"{TMP}/t.xlsx",
                          sha256="y" * 64)
            db.add(tf)
            db.flush()
        t = TeapSpace(project_id=pid, teap_file_id=tf.id, space_key=f"TST|{code}",
                      space_code=code, space_name=name, total_ports=ports,
                      lines=[_line("Laptop", ports, ports, "LAP", 1)])
        db.add(t)
        db.commit()
        return t.space_key


def _row(client, pid, code):
    return next(m for m in client.get(f"/api/projects/{pid}/matches?all=true").json()
                if m["teap_code"] == code)


def test_matching_never_ties_a_teap_line_to_a_key_plan(tmp_path, client):
    pid, _ = _project_with_book("key-1", make_book(tmp_path / "k1.pdf"))
    _teap(pid, "OFF.050", "Office")
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    row = _row(client, pid, "OFF.050")
    with SessionLocal() as db:
        assert db.get(DrawingSpace, row["drawing_space_id"]).page == 2
        on_key = db.execute(select(DrawingSpace).where(
            DrawingSpace.project_id == pid, DrawingSpace.page == 1)).scalars().first()
        assert on_key is None, "a key plan has no spaces at all (2.14.0)"
        # one put there by hand is still refused as a tie
        ghost = DrawingSpace(project_id=pid, drawing_id=db.execute(select(Drawing.id).where(
            Drawing.project_id == pid)).scalar(), page=1, space_code="OFF.050", name="Office",
            x=400, y=100, origin="manual")
        db.add(ghost)
        db.commit()
        ghost_id = ghost.id
    r = client.patch(f"/api/projects/{pid}/matches/{row['id']}",
                     json={"drawing_space_id": ghost_id, "confirmed": True})
    assert r.status_code == 422 and "key plan" in r.json()["detail"]


def test_no_ner_and_no_access_point_is_placed_on_a_key_plan(tmp_path, client):
    pid, _ = _project_with_book("key-2", make_book(tmp_path / "k2.pdf"))
    for kind in ("NER_CRITICAL", "NER_NONCRITICAL", "WIRELESS"):
        r = client.post(f"/api/projects/{pid}/elements",
                        json={"page": 1, "kind": kind, "label": "X", "x": 10, "y": 10})
        assert r.status_code == 422, kind
    r = client.post(f"/api/projects/{pid}/elements",
                    json={"page": 1, "kind": "NER_CRITICAL_REF", "label": "NERc 01",
                          "x": 10, "y": 10})
    assert r.status_code == 201, "a reference is what a key plan is for"


def test_switching_a_page_releases_the_ties_and_brings_them_back(tmp_path, client):
    pid, _ = _project_with_book("key-3", make_book(tmp_path / "k3.pdf"))
    _teap(pid, "OFF.050", "Office")
    # the title block was read wrong: the person says page 1 is not a key plan
    r = client.post(f"/api/projects/{pid}/pages/1/key-plan", json={"key_plan": False})
    assert r.status_code == 200, r.text
    spaces = client.get(f"/api/projects/{pid}/drawing-spaces").json()
    assert any(s["page"] == 1 for s in spaces)
    on_p1 = next(s for s in spaces if s["page"] == 1 and s["space_code"] == "OFF.050")
    row = _row(client, pid, "OFF.050")
    assert client.patch(f"/api/projects/{pid}/matches/{row['id']}",
                        json={"drawing_space_id": on_p1["id"], "confirmed": True}
                        ).status_code == 200
    # and back: page 1 is a key plan after all — the tie there is let go
    r = client.post(f"/api/projects/{pid}/pages/1/key-plan", json={"key_plan": True})
    body = r.json()
    assert r.status_code == 200 and body["released_decisions"] == 1
    row = _row(client, pid, "OFF.050")
    with SessionLocal() as db:
        assert db.get(DrawingSpace, row["drawing_space_id"]).page == 2, \
            "the matching ran again and found the room on the detail sheet"
        t = db.execute(select(TeapSpace).where(TeapSpace.project_id == pid)).scalars().first()
        assert t.locked_verdict is None
        pg = db.execute(select(Page).join(Drawing).where(
            Drawing.project_id == pid, Page.number == 1)).scalars().first()
        assert pg.key_plan and pg.key_plan_source == "manual"
        assert db.execute(select(AuditLog).where(
            AuditLog.project_id == pid, AuditLog.action == "matching.key_plan_released")).first()


def test_the_ners_are_placed_as_a_step_after_the_key_plans_and_the_scales(tmp_path, client):
    """2.14.0: an import reads what the book says about its NERs and places
    nothing; *Place NERs from the drawing* — after the key plans are ticked
    and the scales confirmed — creates them, and running it again adds only
    what is missing."""
    book = make_book(tmp_path / "step.pdf")
    with SessionLocal() as db:
        p = Project(name="step-1", venue_code="TST")
        db.add(p)
        db.commit()
        d = S.ingest_drawing(db, p, book, book.name)
        pid, did = p.id, d.id
        summary = d.extract_summary
    assert summary["ner_pass"] is None and summary["drawn_rooms_found"] == 4
    # what the book says: one annotation on the key plan (kept as a reference,
    # not an annotation), none on the detail sheet
    assert summary["ner_annotations"] == []
    assert _assets(pid) == {}, "nothing placed at import"
    kinds = {e["kind"] for e in client.get(f"/api/projects/{pid}/elements").json()}
    assert kinds == {"NER_CRITICAL_REF"}, kinds

    r = client.post(f"/api/projects/{pid}/ners/place-from-drawing")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 4 and body["rooms_found"] == 4 and body["books"] == [book.name]
    assert set(_assets(pid)) == {"NERc_01.1", "NERc_02.1", "NER_20.1", "NER_21.1"}
    with SessionLocal() as db:
        assert db.get(Drawing, did).extract_summary["ner_pass"]["created"] == 4

    # again: every candidate finds its NER already there
    again = client.post(f"/api/projects/{pid}/ners/place-from-drawing").json()
    assert again["created"] == 0 and again["same_as_marker"] == 4, again
    assert set(_assets(pid)) == {"NERc_01.1", "NERc_02.1", "NER_20.1", "NER_21.1"}

    # the next NER drawn by hand is offered the next number of its series
    nxt = client.get(f"/api/projects/{pid}/ner-next-name").json()
    assert (nxt["critical"], nxt["non_critical"]) == ("NERc_03.1", "NER_22.1")
    # as a job, too
    r = client.post(f"/api/projects/{pid}/ners/place-from-drawing?background=true")
    assert r.status_code == 200 and r.json().get("job_id")


def test_key_plans_are_ticked_on_the_scale_screen_in_one_act(tmp_path, client):
    """The batch endpoint behind the Scale screen's ticks (2.14.0): pages
    ticked lose their spaces and their ties; pages unticked get their spaces
    read off the book; the matching runs once."""
    pid, _ = _project_with_book("ticks-1", make_book(tmp_path / "t1.pdf", detail_pages=2))
    _teap(pid, "OFF.050", "Office")
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    spaces = client.get(f"/api/projects/{pid}/drawing-spaces").json()
    assert {s["page"] for s in spaces} == {2, 3}
    # page 1 off the key plans, page 3 on to them
    r = client.post(f"/api/projects/{pid}/pages/key-plans", json={"pages": {"1": False, "3": True}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["changed"]) == [1, 3]
    assert body["spaces_read"] >= 1 and body["spaces_removed"] >= 1
    assert "matching" in body
    spaces = client.get(f"/api/projects/{pid}/drawing-spaces").json()
    assert {s["page"] for s in spaces} == {1, 2}
    pages = {pg["number"]: pg for pg in client.get(f"/api/projects/{pid}").json()["pages"]}
    assert (pages[1]["key_plan"], pages[3]["key_plan"]) == (False, True)
    # the same answer again changes nothing and runs nothing
    again = client.post(f"/api/projects/{pid}/pages/key-plans", json={"pages": {"1": False, "3": True}}).json()
    assert again["changed"] == [] and "matching" not in again
    # an unknown page is refused
    assert client.post(f"/api/projects/{pid}/pages/key-plans", json={"pages": {"99": True}}).status_code == 404


def test_the_illustrative_sheets_are_ticked_by_default():
    from app.domain.drawn_rooms import is_illustrative_title
    for t in ("KEY ENLARGED PLAN - LEVEL 01", "VENUE INFORMATION & GAMES MAP", "DRAWING INDEX",
              "CONTAINMENT ABBREVIATIONS", "TYPICAL CONTAINMENT SOLUTIONS", "GENERAL NOTES"):
        assert is_illustrative_title(t), t
    for t in ("ENLARGED PLAN LEVEL 01 AREA A1", "NERs, MER & DIVA - LEVEL 01", "SITE PLAN",
              "KEYNOTES", None, ""):
        assert not is_illustrative_title(t), t
