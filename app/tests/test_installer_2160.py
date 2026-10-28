"""2.16.0 — the installer without administrator rights.

Marcelo, 1 Oct 2026: the team's managed computers do not let a
non-administrator install software, and the rights will not be granted. The
2.13.1 check was the only thing in the installation that needed them, so
``setup.bat --no-admin`` (and its double-click form ``setup-noadmin.bat``)
skips the request and installs for the account signed in — and a refused
Windows prompt now offers the same instead of stopping.

setup.bat is a Windows batch file: these tests hold it to its contract by
reading it, as ``test_installer_2131.py`` does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _code(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


setup_bat = pytest.mark.skipif(
    not (ROOT / "setup.bat").exists(),
    reason="setup.bat is not copied into the folder it installs")


@setup_bat
def test_the_no_admin_switch_skips_the_prompt_before_anything_changes():
    code = _code("setup.bat")
    assert 'if /i "%~1"=="--no-admin" (set "NOADMIN=1" & shift & goto :args)' in code
    assert "if defined NOADMIN goto :noadmin" in code
    skip = code.index("if defined NOADMIN goto :noadmin")
    assert skip < code.index("fltmc >nul 2>nul"), "decided before Windows is asked"
    assert skip < code.index(":update") and skip < code.index("robocopy")
    path = code[code.index("\n:noadmin\n"):code.index("\n:admin_ok\n")]
    assert "for this account only" in path
    # The wrong-account guard still runs after it: :admin_ok comes before :who_ok.
    assert code.index("\n:admin_ok\n") < code.index("\n:who_ok")


@setup_bat
def test_a_refused_prompt_offers_the_no_admin_installation():
    code = _code("setup.bat")
    refused = code[code.index("\n:no_rights\n"):code.index("\n:noadmin\n")]
    assert "The administrator rights were not granted" in refused
    assert "choice /c YN" in refused and "for this account only? [Y/N]" in refused
    assert "if errorlevel 2 goto :fail_noadmin" in refused and "goto :noadmin" in refused
    # A script (NER_NOPAUSE) gets no question: it fails as before.
    assert "if defined USER_NOPAUSE goto :fail_noadmin" in refused
    assert refused.index("if defined USER_NOPAUSE goto :fail_noadmin") < refused.index("choice /c YN")
    assert "setup-noadmin.bat" in refused


@setup_bat
def test_the_double_click_form_calls_setup_with_no_admin():
    code = _code("setup-noadmin.bat")
    assert 'call "%~dp0setup.bat" --no-admin %*' in code
    raw = (ROOT / "setup-noadmin.bat").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "CRLF, like every .bat"


def test_the_packager_ships_the_wrapper_and_setup_leaves_it_out_of_the_target():
    pkg = _code("tools/make_package.py")
    assert '"setup-noadmin.bat"' in pkg[pkg.index("REQUIRED = ("):pkg.index(")", pkg.index("REQUIRED = ("))]
    if (ROOT / "setup.bat").exists():
        code = _code("setup.bat")
        assert "/XF setup.bat setup-noadmin.bat" in code


@setup_bat
def test_the_usage_names_the_switch():
    code = _code("setup.bat")
    usage = code[code.index("\n:usage"):code.index("\n:rollback")]
    assert "--no-admin" in usage and "setup-noadmin.bat" in usage


def test_the_documents_name_the_no_admin_way():
    for rel in ("docs/INSTALL.html", "docs/QUICK-INSTALL.html", "INSTALL.txt", "docs/MANUAL.html"):
        assert "setup-noadmin.bat" in _code(rel), rel
    inst = _code("docs/INSTALL.html")
    assert "--no-admin" in inst and "for this account only? [Y/N]" in inst
