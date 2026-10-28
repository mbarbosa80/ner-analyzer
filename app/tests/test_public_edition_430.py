"""4.3.0 — the edition that may be published.

Marcelo, 19 Oct 2026: open source, credited, and "não ferir nenhum copyright
ou registros". So:

* the licence is the GNU AGPL-3.0 (PyMuPDF, which the app is built on, is
  AGPL), with the author's credit as an additional term (NOTICE.txt);
* no shipped text names an event, an organiser, a venue or an employer — the
  list of those words is private, and so is a client's reference material;
* a public package leaves the private folder out, and the app works without it.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _packager():
    spec = importlib.util.spec_from_file_location("make_package", ROOT / "tools" / "make_package.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_licence_is_the_agpl_and_the_credit_is_a_term_of_it():
    lic = (ROOT / "LICENSE.txt").read_text(encoding="utf-8")
    assert lic.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in lic
    notice = (ROOT / "NOTICE.txt").read_text(encoding="utf-8")
    assert "Created by Marcelo Barbosa" in notice and "section 7(b)" in notice
    third = (ROOT / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
    assert "pymupdf" in third.lower() and "AGPL" in third
    from app.version import COPYRIGHT
    assert "AGPL-3.0" in COPYRIGHT and "Created by Marcelo Barbosa" in COPYRIGHT
    assert "All rights reserved" not in COPYRIGHT


def test_no_file_says_all_rights_reserved_any_more():
    p = _packager()
    left = []
    for f in p.collect():
        if (f.suffix.lower() in p.PUBLIC_SCAN_SUFFIXES
                and f.name not in ("CHANGELOG.md", "test_public_edition_430.py")):
            text = f.read_text(encoding="utf-8", errors="ignore")
            if "All rights reserved" in text or "Todos os direitos reservados" in text:
                left.append(f.relative_to(ROOT).as_posix())
    assert not left, left


def test_a_public_package_leaves_the_private_folder_out():
    p = _packager()
    p.PUBLIC = True
    try:
        rel = {f.relative_to(ROOT).as_posix() for f in p.collect()}
    finally:
        p.PUBLIC = False
    assert "backend/app/reference_private/README.md" in rel
    assert not any(r.startswith("backend/app/reference_private/") and not r.endswith("README.md")
                   for r in rel)
    assert not any(r.startswith("docs/history/") for r in rel)
    assert {"LICENSE.txt", "NOTICE.txt", "THIRD-PARTY-NOTICES.txt"} <= rel


@pytest.mark.skipif(not (ROOT / "backend" / "app" / "reference_private" / "public_banned.txt").exists(),
                    reason="the list of banned words is private and not in this copy")
def test_no_shipped_text_names_an_event_an_organiser_a_venue_or_an_employer():
    p = _packager()
    p.PUBLIC = True
    try:
        files = p.collect()
    finally:
        p.PUBLIC = False
    hits = p.public_hits(files)
    assert not hits, "\n".join(hits[:80])


def test_the_app_works_without_the_private_reference(monkeypatch, tmp_path):
    from app.domain import aam_vocab as V
    from app.domain import reference_data as RD
    monkeypatch.setattr(RD, "PRIVATE_DIR", tmp_path)
    assert RD.naming_reference() is None
    monkeypatch.setattr(V, "_NAMES_FILE", tmp_path / "aam_names.txt")
    V.aam_names.cache_clear(); V._aam_normalised.cache_clear()
    try:
        assert V.aam_names() == ()
        assert V.SpaceVocabulary(["Boat Storage Barn"]).is_space_name("BOAT STORAGE BARN")
    finally:
        V.aam_names.cache_clear(); V._aam_normalised.cache_clear()


def test_the_naming_panel_reads_its_table_from_the_server():
    src = (ROOT / "frontend" / "src" / "components" / "NamingReference.tsx").read_text(encoding="utf-8")
    assert "api.namingReference()" in src
    assert "NERc_04.1" not in src, "the table is a client's document, not part of the app"


def test_the_reference_file_is_read_when_there_and_ignored_when_broken(monkeypatch, tmp_path):
    from app.domain import reference_data as RD
    monkeypatch.setattr(RD, "PRIVATE_DIR", tmp_path)
    (tmp_path / "naming_reference.json").write_text('{"title": "T", "groups": []}', encoding="utf-8")
    assert RD.naming_reference() == {"title": "T", "groups": []}
    (tmp_path / "naming_reference.json").write_text("not json", encoding="utf-8")
    assert RD.naming_reference() is None
