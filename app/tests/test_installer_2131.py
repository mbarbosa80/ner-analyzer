"""2.13.1: the installer asks for administrator rights, refuses the wrong
account, replaces an existing installation instead of overlaying it (with a
way back), and is the one way in; the manuals are English only.

setup.bat is a Windows batch file: these tests hold it to its contract
without running it. The install tests on a real machine run it.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _code(rel: str) -> str:
    """The script without its REM lines, so a comment cannot satisfy a test."""
    return "\n".join(l for l in _read(rel).splitlines() if not l.strip().upper().startswith("REM"))


setup_bat = pytest.mark.skipif(
    not (ROOT / "setup.bat").exists(),
    reason="setup.bat is not copied into the folder it installs")


@setup_bat
def test_setup_asks_windows_for_administrator_rights():
    code = _code("setup.bat")
    # The check comes before anything is changed, and a test switch exists.
    check = code.index("fltmc >nul 2>nul")
    assert check < code.index(":update") and check < code.index("robocopy")
    assert "if defined NER_SKIP_ADMIN goto :admin_ok" in code
    # Without the rights: the same script again, elevated, and this one ends.
    assert "Verb = 'RunAs'" in code and "Start-Process @a" in code
    assert 'set "NER_SELF=%~f0"' in code
    elevate = code[code.index("fltmc >nul 2>nul"):code.index("\n:admin_ok\n")]
    assert "exit /b 0" in elevate, "the unelevated window must end once the elevated one starts"
    assert "The administrator rights were not granted" in elevate


@setup_bat
def test_setup_refuses_an_elevation_as_another_account():
    code = _code("setup.bat")
    who = code[code.index("\n:admin_ok\n"):code.index("\n:who_ok")]
    assert "Win32_ComputerSystem" in who and "WindowsIdentity]::GetCurrent().Name" in who
    # An empty console user (Remote Desktop) is never compared.
    assert "if ($c -and ($c -ne $w))" in who
    assert "goto :fail" in who
    assert who.index("Win32_ComputerSystem") < who.index("goto :fail")


@setup_bat
def test_setup_moves_the_old_installation_aside_and_brings_the_data_across():
    code = _code("setup.bat")
    upd = code[code.index("\n:update\n"):code.index("\n:copy")]
    # Backup, stop, then the move - in that order.
    order = ["backup.bat", "stop.bat", 'move "%TARGET%" "%PREV%"', 'move "%PREV%\\data" "%TARGET%\\data"']
    pos = [upd.index(s) for s in order]
    assert pos == sorted(pos), order
    assert 'set "PREV=%TARGET%.previous"' in code
    # Only an older .previous is removed, never the installation itself.
    for line in upd.splitlines():
        if "rmdir /s" in line:
            assert '"%PREV%"' in line, line
    # The move is retried (something may still hold the folder) and bounded.
    assert ":move_again" in upd and "if %MOVES% geq 10 goto :move_failed" in upd
    assert 'set "MOVED=1"' in upd


@setup_bat
def test_a_failure_after_the_move_puts_the_old_installation_back():
    code = _code("setup.bat")
    body = code[code.index("\n:copy"):code.index("\n:services")]
    # Every failure between the move and the services goes to the rollback.
    assert body.count("goto :rollback") >= 4
    assert "goto :fail_reenable" not in body
    rb = code[code.index("\n:rollback\n"):code.index("\n:fail_reenable")]
    assert "if not defined MOVED goto :fail_reenable" in rb
    # The data goes back BEFORE the half-built folder is removed, and the
    # folder is removed only when the data is out of it.
    assert rb.index('move "%TARGET%\\data" "%PREV%\\data"') < rb.index('rmdir /s /q "%TARGET%"')
    guard = rb.index('if not exist "%TARGET%\\data" goto :rollback_data_out')
    assert guard < rb.index('rmdir /s /q "%TARGET%"')
    assert rb.index(":rollback_data_out") < rb.index('rmdir /s /q "%TARGET%"')
    assert 'move "%PREV%" "%TARGET%"' in rb


@setup_bat
def test_setup_opens_the_browser_unelevated_and_writes_a_desktop_shortcut():
    code = _code("setup.bat")
    assert 'start "" explorer.exe "%URL%/"' in code
    assert 'start "" "%URL%/"' not in code, "an elevated window would open an elevated browser"
    assert "GetFolderPath('Desktop')" in code and "NER Analyzer.url" in code
    assert "[InternetShortcut]" in code
    # The shortcut belongs to the services path, not to --no-services.
    assert code.index("\n:shortcut") > code.index("\n:services")
    assert "Unblock-File" in code


@setup_bat
def test_setup_marks_its_calls_so_install_bat_does_not_hand_back():
    sub = _code("setup.bat")
    sub = sub[sub.index("\n:in_target"):sub.index("\n:usage")]
    assert 'set "NER_FROM_SETUP=1"' in sub


def test_install_bat_hands_over_to_setup_in_a_package_only():
    code = _code("install.bat")
    hand = code.index('call "%~dp0setup.bat" %*')
    # Before delayed expansion: setup.bat must not inherit it.
    assert hand < code.index("setlocal EnableDelayedExpansion")
    head = code[:hand]
    assert "if defined NER_FROM_SETUP goto :install_here" in head
    assert 'if not exist "%~dp0setup.bat" goto :install_here' in head
    assert 'if not exist "%~dp0MANIFEST.txt" goto :install_here' in head
    assert code.index("\n:install_here") < code.index("setlocal EnableDelayedExpansion")


def test_batch_files_keep_windows_line_endings():
    for rel in ("setup.bat", "install.bat"):
        path = ROOT / rel
        if not path.exists():
            continue
        data = path.read_bytes()
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), rel


# --- the manuals: English only ------------------------------------------------

DOCS = ("MANUAL.html", "INSTALL.html", "HISTORY.html")


@pytest.mark.parametrize("name", DOCS)
def test_the_manuals_are_english_only(name):
    path = ROOT / "docs" / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    text = path.read_text(encoding="utf-8")
    assert not re.search(r'class="[^"]*\bpt\b', text), "a Portuguese block is left"
    assert "langswitch" not in text and "data-lang" not in text and "setLang" not in text
    assert "INSTALACAO" not in text and "HISTORICO" not in text


def test_the_old_bilingual_names_are_gone():
    for old in ("INSTALACAO.html", "HISTORICO.html", "MANUAL.en.pdf"):
        assert not (ROOT / "docs" / old).exists(), old
    # render_docs.py and make_package.py are development tools: the package
    # does not ship them, so an installed copy has nothing to check there.
    for rel in ("tools/render_docs.py", "tools/make_package.py"):
        if (ROOT / rel).exists():
            assert "INSTALACAO" not in _read(rel), rel
    assert "INSTALACAO" not in _read("INSTALL.txt")


def test_the_installation_manual_describes_the_new_installer():
    text = _read("docs/INSTALL.html")
    for needle in ("Run as administrator", "ner-analyzer.previous", "another account",
                   "NER Analyzer", "Firefox", "Edge", "Chrome", "Unblock",
                   "handing over to setup.bat"):
        assert needle in text, needle
    quick = _read("INSTALL.txt")
    # 2.16.0: the rights are no longer required; the quick start names both ways.
    assert "Run as administrator" in quick and "setup-noadmin.bat" in quick
    assert "Firefox" in quick
