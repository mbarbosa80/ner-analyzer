"""One version number, stated in one file, repeated nowhere by hand.

``VERSION`` at the project root is the number. Everything else that states a
version — the front-end's ``package.json``, the top entry of ``CHANGELOG.md``,
the API, the exports, the manuals — is checked here against it, so a release
that bumps one place and forgets another fails on the desk instead of on
somebody else's screen.

The manuals are also held to the other rule agreed on 10 Sep 2026: the user
manual describes the application as it is and carries **no change history**.
That history belongs in ``CHANGELOG.md``.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile

import pytest

# Run alone, this module must not create a database inside the project
# folder. When another module imported the app first, its own temporary
# directory is already in force and these two lines change nothing.
_TMP = tempfile.mkdtemp(prefix="ner-version-test-")
os.environ.setdefault("NER_DATA_DIR", _TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{_TMP}/test.sqlite3")

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_the_version_is_semver_and_at_least_two():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), f"VERSION reads {VERSION!r}"
    major = int(VERSION.split(".")[0])
    assert major >= 2, "the application was numbered 2.0.0 on 10 Sep 2026; it does not go back"


def test_the_backend_reads_the_same_number():
    from app.config import settings
    from app.version import __version__

    assert __version__ == VERSION
    assert settings.version == VERSION


def test_the_front_end_package_carries_the_same_number():
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == VERSION, (
        f"frontend/package.json says {pkg['version']} but VERSION says {VERSION} — "
        "edit both, then rebuild the interface")


def test_the_compiled_interface_was_built_from_this_version():
    """The bundle carries the version it was built from (Vite's ``define``).

    A bundle from an older version is exactly what the browser would show as
    'stale', so it must not ship: rebuild with ``npm run build``.
    """
    assets = ROOT / "backend" / "app" / "static" / "assets"
    if not assets.exists():
        pytest.skip("no compiled interface here")
    bundles = list(assets.glob("index-*.js"))
    assert bundles, "no index-*.js bundle under backend/app/static/assets"
    text = "\n".join(b.read_text(encoding="utf-8", errors="ignore") for b in bundles)
    assert f'"{VERSION}"' in text, (
        f"the compiled interface does not carry {VERSION} — run  cd frontend && npm run build")


def test_the_changelog_top_entry_is_this_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.findall(r"^## (\d+\.\d+\.\d+) — (\d{4}-\d{2}-\d{2})", text, flags=re.M)
    assert entries, "CHANGELOG.md has no '## x.y.z — YYYY-MM-DD' entry"
    assert entries[0][0] == VERSION, (
        f"the newest CHANGELOG entry is {entries[0][0]}, VERSION is {VERSION}")


def test_the_api_reports_the_version():
    from fastapi.testclient import TestClient

    from app.db import init_db
    from app.main import app

    init_db()
    client = TestClient(app)
    assert client.get("/healthz").json()["version"] == VERSION
    state = client.get("/api/auth/state").json()
    assert state["version"] == VERSION
    assert "Marcelo Barbosa" in state["copyright"]
    # 4.3.0: free software, the credit kept as a term of the licence
    assert "AGPL-3.0" in state["copyright"] and "Created by Marcelo Barbosa" in state["copyright"]


def test_every_export_is_stamped_with_the_version(tmp_path):
    from app.domain import reports

    assert reports.PRODUCED_BY.endswith(VERSION)
    # the footnote carries it — the line that survives the legend being off
    lines = reports._footnote_lines("As-Is", reports.DistanceRules(), None, True)
    assert VERSION in lines[0][0]


@pytest.mark.parametrize("name", ["MANUAL.html", "INSTALL.html", "QUICK-INSTALL.html"])
def test_the_manuals_carry_the_current_version(name):
    path = ROOT / "docs" / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    text = path.read_text(encoding="utf-8")
    assert VERSION in text, f"docs/{name} does not mention version {VERSION}"
    assert "Marcelo Barbosa" in text
    # 4.3.0: free software — the licence and the credit, not a no-copy clause
    assert "AGPL" in text and "NOTICE.txt" in text, "the licence line is missing"


def test_the_user_manual_carries_no_change_history():
    """Agreed 10 Sep 2026: the manual says how the application works, and
    nothing about when it changed. Dated revision notes go to CHANGELOG.md."""
    path = ROOT / "docs" / "MANUAL.html"
    if not path.exists():
        pytest.skip("manual not present")
    text = path.read_text(encoding="utf-8")
    for marker in ("revisado em", "Revisão de", "Revised ", "What changed",
                   "O que mudou", "removido em", "removed on", "— removed",
                   "&mdash; removido", "since 3 Sep", "desde 03/09", "since 10 Sep",
                   "desde 10/09"):
        assert marker not in text, f"the manual carries change history: {marker!r}"
