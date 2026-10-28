"""2.17.0 — the foreign keys a screen filters by are indexed, on a new
database and on one that predates the indexes."""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text

TMP = tempfile.mkdtemp(prefix="ner-test-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/test.sqlite3")

from app import migrate                       # noqa: E402
from app.models import Base                   # noqa: E402

EXPECTED = {
    ("elements", "project_id"), ("elements", "ner_asset_id"), ("elements", "drawing_id"),
    ("drawing_spaces", "project_id"), ("drawing_spaces", "drawing_id"),
    ("teap_spaces", "project_id"), ("space_matches", "project_id"),
    ("space_matches", "teap_space_id"), ("space_matches", "drawing_space_id"),
    ("jobs", "project_id"), ("audit_log", "project_id"), ("ner_assets", "project_id"),
    ("pages", "drawing_id"), ("zones", "project_id"), ("aliases", "project_id"),
}


def _indexed(engine) -> set[tuple[str, str]]:
    insp = inspect(engine)
    out = set()
    for t in insp.get_table_names():
        for ix in insp.get_indexes(t):
            if len(ix["column_names"]) == 1:
                out.add((t, ix["column_names"][0]))
        for uq in insp.get_unique_constraints(t):
            if len(uq["column_names"]) == 1:
                out.add((t, uq["column_names"][0]))
    return out


def test_a_new_database_has_the_indexes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/new.sqlite3", future=True)
    migrate.ensure_schema(engine)
    assert EXPECTED <= _indexed(engine)


def test_an_old_database_gets_them_at_start(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.sqlite3", future=True)
    # The schema as it was: every table, no index of ours.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for row in conn.execute(text(
                "select name from sqlite_master where type='index' and name like 'ix_%'")).all():
            conn.execute(text(f'DROP INDEX "{row[0]}"'))
    assert not (EXPECTED & {k for k in _indexed(engine) if k[0] != "pages"})
    changed = migrate.ensure_schema(engine)
    assert any(c.startswith("indexed elements(project_id)") for c in changed), changed
    assert EXPECTED <= _indexed(engine)
    # A second start changes nothing.
    assert not [c for c in migrate.ensure_schema(engine) if c.startswith("indexed")]


def test_elements_use_the_index(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/plan.sqlite3", future=True)
    migrate.ensure_schema(engine)
    with engine.connect() as conn:
        plan = " ".join(r[3] for r in conn.execute(
            text("explain query plan select * from elements where project_id = 1")).all())
        assert "USING INDEX" in plan, plan
        plan = " ".join(r[3] for r in conn.execute(
            text("explain query plan select * from elements where ner_asset_id = 5")).all())
        assert "USING INDEX" in plan, plan
