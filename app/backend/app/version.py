"""The application version — one number, read from one file.

The version lives in ``VERSION`` at the root of the project and nowhere else.
Everything that states a version reads it from here: the API (``/healthz``,
``/api/meta``, ``/api/auth/state``), the interface, the workbook's Summary
sheet, the marked-up PDF's footnote, the package file name and the tests that
keep ``frontend/package.json`` and ``CHANGELOG.md`` in step with it.

The scheme is semantic versioning, ``MAJOR.MINOR.PATCH``, from 2.0.0 onwards:

* **PATCH** (2.0.1) — a correction that changes no screen and no file shape:
  a bug fix, a wording fix, a performance fix.
* **MINOR** (2.1.0) — something new that keeps every existing project,
  export and workflow valid: a new column, a new switch, a new report.
* **MAJOR** (3.0.0) — a change an existing installation cannot absorb
  silently: a database that needs re-importing, an export whose columns
  change shape, a screen removed.

Releasing a version means, in this order: edit ``VERSION``, edit the
``"version"`` in ``frontend/package.json``, add the entry at the top of
``CHANGELOG.md``, rebuild the interface (``npm run build``), run the tests
(``tests/test_version.py`` refuses a mismatch), and build the package with
``build_package.bat``. The tests are what make the order stick.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE = ROOT / "VERSION"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    """The version as written in ``VERSION``, or ``0.0.0`` when it is missing.

    A missing file is not an error at import time — the application still has
    to start on a folder somebody copied by hand — but it is a visible one:
    ``0.0.0`` on every screen is what says the copy is incomplete.
    """
    try:
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text if SEMVER.match(text) else "0.0.0"


__version__ = read_version()
APP_NAME = "NER Spatial Coverage Analyzer"
AUTHOR = "Marcelo Barbosa"
#: Free software since 4.3.0 (GNU AGPL-3.0). The credit to the author is an
#: additional term of the licence (section 7(b), see NOTICE.txt): it stays on
#: every copy and every modified version.
LICENCE = "GNU AGPL-3.0"
COPYRIGHT = (f"© 2026 {AUTHOR}. Created by {AUTHOR}. Free software under the "
             f"{LICENCE}: you may use, study, change and share it, keeping this "
             f"credit (see LICENSE.txt and NOTICE.txt).")
