"""The installation package carries its own Python — and every script agrees.

Since 2.1.0 the package ships the python.org *embeddable* runtime and
``install.bat`` unpacks it into ``.python\\`` next to the application. That
layout is spread over a dozen files that no interpreter checks for us: batch
files, a PowerShell script, the packager, the lock file and the manual. These
tests read them as text and hold them to the same three rules:

1. every launcher resolves the interpreter the same way — ``.python\\`` first,
   ``.venv\\`` (a development checkout) second — so a machine with no Python
   installed never sees a script reaching for a Python that is not there;
2. the packager bundles exactly what the installer expects — the pinned
   runtime zip, the pip wheel it bootstraps from, the numpy wheel it takes
   the C++ runtime from — and never the unpacked result;
3. the documents tell the truth about it: the installation manual no longer
   asks for Python to be installed first.

None of this runs the scripts (they are Windows batch files, and the test
suite also runs on Linux); the fresh-install test on a real machine does that.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _code(rel: str) -> str:
    """The script without its REM lines, so a comment cannot satisfy a test."""
    return "\n".join(l for l in _read(rel).splitlines() if not l.strip().upper().startswith("REM"))


# --- 1. the launchers -------------------------------------------------------

LAUNCHERS = [
    "start.bat", "backup.bat", "run-tests.bat", "build_package.bat",
    "autostart.bat", "tools/server-start.cmd", "tools/watchdog.ps1",
]


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_every_launcher_prefers_the_bundled_runtime(rel):
    text = _read(rel)
    assert ".python\\" in text, f"{rel} never looks for the bundled runtime (.python\\)"
    assert ".venv\\" in text, f"{rel} lost the development fallback (.venv\\)"
    # First mention wins: .python must come before .venv in the resolution.
    assert text.index(".python\\") < text.index(".venv\\"), (
        f"{rel} checks .venv before .python — the bundled runtime must win")


@pytest.mark.parametrize("rel", ["start.bat", "backup.bat", "run-tests.bat", "build_package.bat"])
def test_console_launchers_use_python_exe_not_pythonw(rel):
    text = _read(rel)
    assert ".python\\python.exe" in text
    assert "pythonw" not in text.lower()


@pytest.mark.parametrize("rel", ["autostart.bat", "tools/server-start.cmd", "tools/watchdog.ps1"])
def test_windowless_launchers_use_pythonw(rel):
    text = _read(rel)
    assert ".python\\pythonw.exe" in text
    assert ".venv\\Scripts\\pythonw.exe" in text


def test_batch_files_have_windows_line_endings():
    for rel in ["setup.bat", "install.bat", "start.bat", "stop.bat", "autostart.bat",
                "backup.bat", "run-tests.bat", "build_package.bat",
                "tools/server-start.cmd", "tools/server-stop.cmd"]:
        if not (ROOT / rel).exists():
            continue                      # setup.bat, in a folder it installed
        raw = (ROOT / rel).read_bytes()
        assert b"\r\n" in raw, f"{rel} has no CRLF line endings"
        lone = re.findall(rb"(?<!\r)\n", raw)
        assert not lone, f"{rel} mixes LF-only lines with CRLF ({len(lone)} of them)"


# --- 2. install.bat ---------------------------------------------------------

def test_install_bat_builds_the_bundled_runtime():
    text = _read("install.bat")
    assert 'vendor\\python\\python-3.12.*-embed-amd64.zip' in text
    # The runtime's search path: stdlib zip, the folder, the packages, the app.
    assert "python312._pth" in text
    for line in ("python312.zip", "Lib\\site-packages", "..\\backend", "import site"):
        assert f"echo {line}" in text, f"install.bat does not write {line!r} into ._pth"
    # pip is bootstrapped from the bundled wheel — the embeddable runtime has
    # no ensurepip — and everything installs offline from vendor\wheels.
    assert "runpy.run_module('pip', run_name='__main__', alter_sys=True)" in text
    assert '"%PIPWHL%" install' in text
    assert "--no-index --find-links vendor\\wheels" in text
    assert "--no-deps -r %REQS%" in text
    assert "requirements-lock-win.txt" in text
    # The C++ runtime story, both halves.
    assert "msvcp140.dll" in text
    assert "numpy.libs\\msvcp140-*.dll" in text
    # It still proves the installation works, and it never calls venv on the
    # bundled runtime (which has no venv module).
    assert "import fastapi,uvicorn,sqlalchemy,pymupdf" in text
    embedded = text[text.index("\n:embedded\n"):text.index("\n:sysvenv\n")]
    assert "tar -xf" in embedded and "-m venv" not in embedded


def test_install_bat_keeps_the_development_fallback():
    text = _read("install.bat")
    fallback = text[text.index("\n:sysvenv\n"):text.index("\n:verify\n")]
    assert "-m venv .venv" in fallback
    assert 'for %%C in ("py -3.12" "py -3" "python")' in fallback


def test_no_message_relies_on_a_bare_exclamation_mark():
    """``EnableDelayedExpansion`` eats a lone ``!`` — a ``[!]`` marker prints
    as ``[]``. Markers use ``[*]`` instead."""
    text = _read("install.bat")
    assert "setlocal EnableDelayedExpansion" in text
    assert "[!]" not in text


# --- 3. run.py and serve.py -------------------------------------------------

def test_run_py_uses_the_bundled_runtime_and_names_the_backend_explicitly():
    text = _read("run.py")
    assert 'EMBEDDED = ROOT / ".python" / ("python.exe" if os.name == "nt" else "bin/python3")' in text
    assert '"--app-dir"' in text, "uvicorn must be told where backend/ is: the bundled runtime ignores PYTHONPATH"
    # venv is imported lazily: the module does not exist in the bundled runtime.
    head = text.split("def ")[0]
    assert "import venv" not in head


def test_serve_py_puts_backend_on_the_path_itself():
    text = _read("tools/serve.py")
    assert 'sys.path.insert(0, str(ROOT / "backend"))' in text


# --- 4. the packager --------------------------------------------------------

def test_packager_pins_the_runtime_by_content():
    text = _read("tools/make_package.py")
    m = re.search(r'EMBED_SHA256 = "([0-9a-f]{64})"', text)
    assert m, "the embeddable runtime must be pinned by SHA-256"
    assert re.search(r'EMBED_VERSION = "3\.12\.\d+"', text), "the wheels are built for CPython 3.12"
    assert re.search(r'EMBED_SIZE = [\d_]+', text)
    assert 'EMBED_NAME = f"python-{EMBED_VERSION}-embed-amd64.zip"' in text
    assert "https://www.python.org/ftp/python/" in text


def test_packager_excludes_the_unpacked_runtime_and_requires_its_inputs():
    text = _read("tools/make_package.py")
    exclude = text[text.index("EXCLUDE_DIRS = {"):text.index("}", text.index("EXCLUDE_DIRS = {"))]
    assert '".python"' in exclude and '".venv"' in exclude and '"vendor"' in exclude
    assert 'w.name.startswith("pip-")' in text
    assert 'w.name.startswith("numpy-")' in text
    assert 'f"ner-analyzer/vendor/python/{runtime.name}"' in text


def test_the_lock_file_pins_pip_for_the_bootstrap():
    text = _read("requirements-lock-win.txt")
    assert re.search(r"^pip==\d+\.\d+", text, re.M), "install.bat bootstraps pip from vendor\\wheels"


@pytest.mark.skipif(not list((ROOT / "vendor" / "wheels").glob("*.whl")) if (ROOT / "vendor" / "wheels").is_dir() else True,
                    reason="vendor/wheels is only populated on the machine that builds the package")
def test_the_bundled_wheels_match_the_lock_file_and_the_runtime():
    """Every pin resolves to exactly one wheel, and every compiled wheel is
    built for the runtime being bundled (cp312, win_amd64)."""
    wheels = sorted(p.name for p in (ROOT / "vendor" / "wheels").glob("*.whl"))
    pins = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s#]+)", _read("requirements-lock-win.txt"), re.M)
    assert pins
    for name, ver in pins:
        norm = re.sub(r"[-_.]+", "_", name).lower()
        hits = [w for w in wheels if re.sub(r"[-_.]+", "_", w.split("-")[0]).lower() == norm
                and w.split("-")[1] == ver]
        assert len(hits) == 1, f"{name}=={ver}: {hits or 'no wheel'} in vendor/wheels"
    for w in wheels:
        py, abi, plat = w[:-4].split("-")[-3:]
        if abi == "none":                           # pure Python
            continue
        assert plat == "win_amd64", f"{w} is not a 64-bit Windows wheel"
        # Either built for 3.12 exactly, or on the stable ABI from an older 3.x
        # (abi3 wheels such as protobuf's cp310-abi3 load on any later 3.x).
        assert (py, abi) == ("cp312", "cp312") or (abi == "abi3" and py <= "cp312"), (
            f"{w} is not built for the bundled runtime (CPython 3.12)")


# --- 5. the documents -------------------------------------------------------

def test_the_installation_manual_no_longer_asks_for_python_first():
    text = _read("docs/INSTALL.html")
    assert VERSION in text
    assert "Add python.exe to PATH" not in text, (
        "the manual still walks the reader through installing Python")
    assert "python.org/downloads" not in text
    assert ".python" in text and "msvcp140" in text
    quick = _read("INSTALL.txt")
    assert "precisa ter o Python" not in quick and "needs Python" not in quick
    assert "Python" in quick     # it says the package carries it


# --- 2.2.1: tasks that survive a laptop's day --------------------------------

def test_both_tasks_are_hardened_against_the_scheduler_defaults():
    """schtasks /create cannot set a task's conditions, so both tasks came out
    with 'do not start on battery', 'stop when going on battery' and a 72 h
    limit. On 17 Sep 2026 the watchdog had silently not fired for 45 minutes --
    the laptop was unplugged -- while the server was down."""
    auto = _read("autostart.bat")
    assert auto.count("task-harden.ps1") >= 2
    assert '-Name "%TASKNAME%"' in auto and '-Name "%WATCHDOG%"' in auto
    assert auto.index("watchdog-install.ps1") < auto.index("task-harden.ps1"), \
        "harden after both tasks exist"
    ps = _read("tools/task-harden.ps1")
    for setting, value in (("DisallowStartIfOnBatteries", "false"),
                           ("StopIfGoingOnBatteries", "false"),
                           ("ExecutionTimeLimit", "PT0S"),
                           ("MultipleInstancesPolicy", "IgnoreNew")):
        assert re.search(rf"{setting}\s*=\s*'{value}'", ps), setting
    assert "schtasks.exe /Create" in ps and "/XML" in ps, \
        "Register-ScheduledTask is refused on the managed machine; schtasks is not"
    assert "Set-ScheduledTask" not in ps.split("param(")[1]
    assert "exit 2" in ps, "a failure leaves the old task and says what to untick"


def test_server_start_goes_through_the_scheduled_task_first():
    """'start' makes the server a child of whoever ran the file: started from a
    remote tool session it died with that session, nothing in the log."""
    text = _read("tools/server-start.cmd")
    assert 'schtasks /run /tn "%TASKNAME%"' in text
    assert text.index("schtasks /run") < text.index('start "" "%PYW%"'), \
        "the plain start is the fallback, not the first choice"


def test_the_package_ships_the_hardening_script():
    assert '"task-harden.ps1"' in _read("tools/make_package.py")


# --- 2.4.0: setup.bat, the one-step installer that removes itself ------------
#
# setup.bat installs into a folder of its own and is deliberately NOT copied
# there (it would have nothing left to do: the package's vendor\ is gone too).
# So in an installation *made by* setup.bat these tests have no subject, and
# they skip rather than fail — the same rule as the bundled-wheels test above.
# What must never be skipped is the guarantee that the package carries it, and
# that lives in the packager's REQUIRED list, checked below without the file.

setup_bat = pytest.mark.skipif(
    not (ROOT / "setup.bat").exists(),
    reason="setup.bat is not copied into the folder it installs")

#
# Marcelo's ask (18 Sep 2026): an installer that installs Python and the app,
# brings the services up, and then destroys every installation file, leaving
# only the running application on the machine. These hold the script to that
# contract without running it (it is a Windows batch file; the fresh-install
# test on a real machine runs it).

@setup_bat
def test_setup_installs_into_its_own_folder_and_never_in_place():
    text = _read("setup.bat")
    assert 'set "TARGET=%LOCALAPPDATA%\\Programs\\ner-analyzer"' in text
    # It refuses to install over itself, inside itself, or around itself: the
    # package folder is deleted at the end.
    assert 'if /i "%TARGET%"=="%SRC%"' in text
    assert 'call set "PROBE=%%TARGET:%SRC%\\=%%"' in text
    assert 'call set "PROBE=%%SRC:%TARGET%\\=%%"' in text
    # It only runs from a built package - a development checkout has no manifest.
    assert 'if not exist "MANIFEST.txt"' in text
    assert 'vendor\\python\\python-3.12.*-embed-amd64.zip' in text


@setup_bat
def test_setup_runs_the_existing_scripts_in_order_in_the_target():
    """setup.bat orchestrates; it does not re-implement install.bat."""
    text = _code("setup.bat")
    order = ["robocopy", "call :in_target install.bat", "call :in_target autostart.bat",
             "call :in_target tools\\server-start.cmd", "/healthz", "rmdir /s /q \"%TARGET%\\vendor\""]
    positions = [text.index(s) for s in order]
    assert positions == sorted(positions), order
    # Every call runs inside the target with the pauses off, and the subroutine
    # hands the script's exit code back.
    sub = text[text.index("\n:in_target"):text.index("\n:usage")]
    assert 'pushd "%TARGET%"' in sub and 'set "NER_NOPAUSE=1"' in sub
    assert 'set "RC=%ERRORLEVEL%"' in sub and "exit /b %RC%" in sub
    # The package's data\ (an empty .keep) never lands on an existing data\.
    assert "/XD data" in text
    # The server is started through the scheduled task, never with a bare start
    # (a server started that way belongs to the window that started it).
    assert 'start "" "%PYW%"' not in text


@setup_bat
def test_setup_removes_installer_files_by_manifest_never_by_blind_rmdir():
    """A blind `rmdir /s` of the folder the script lives in would erase the
    Downloads folder of somebody who unzipped the package straight into it."""
    text = _code("setup.bat")
    cleanup = text[text.index("\n:cleanup"):text.index("\n:done")]
    assert 'MANIFEST.txt"' in cleanup and "del /f /q" in cleanup
    # rmdir /s only ever targets vendor\ (the wheels and the runtime zip, which
    # the manifest does not list) - never %SRC% itself.
    for line in cleanup.splitlines():
        if "rmdir /s" in line:
            assert "vendor" in line, line
    assert 'rd "%%%%D"' in cleanup and 'rd "%SRC%"' in cleanup, "folders go only once empty (rd without /s)"
    # The zip goes too, only the one of this version, only where a download lands.
    assert "ner-analyzer-%VER%*windows*.zip" in cleanup
    assert '"%%USERPROFILE%%\\Downloads"' in cleanup
    # The cleanup runs after the window closes, from %TEMP%, and deletes itself.
    assert 'set "CLEAN=%TEMP%\\ner-setup-cleanup-' in text
    assert 'start "" /min cmd /c "%CLEAN%"' in text
    assert 'echo del /f /q "%%~f0"' in cleanup
    # And it can be switched off for whoever wants to keep the package.
    assert "--keep-installer" in text


@setup_bat
def test_setup_updates_an_existing_installation_safely():
    text = _read("setup.bat")
    for marker in ('if exist "%TARGET%\\.python\\python.exe" set "MODE=update"',
                   'if exist "%TARGET%\\data\\ner.sqlite3" set "MODE=update"'):
        assert marker in text
    upd = text[text.index("\n:update"):text.index("\n:copy")]
    # Backup before anything, stop before copying, and the tasks are held so the
    # watchdog does not start the old runtime while it is being replaced.
    assert upd.index("backup.bat") < upd.index("stop.bat")
    assert "/disable" in upd
    assert text.count("/enable") >= 2, "the tasks are re-enabled on failure and on --no-services"


@setup_bat
def test_setup_has_no_parse_time_errorlevel_inside_a_block():
    """`%ERRORLEVEL%` inside `( ... )` is expanded when the block is parsed, so it
    reports the value from *before* the block ran. Every capture is a top-level
    line or inside the :in_target subroutine."""
    text = _read("setup.bat")
    depth = 0
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("REM") or stripped.startswith("echo"):
            continue
        if "%ERRORLEVEL%" in line:
            assert depth == 0, f"line {n}: %ERRORLEVEL% inside a block"
        depth += line.count("(") - line.count("^(") - line.count(")") + line.count("^)")
    assert "[!]" not in text
    assert "setlocal EnableDelayedExpansion" not in text, "the script relies on call-set, not delayed expansion"


@setup_bat
def test_the_clean_up_waits_for_the_folder_to_be_free():
    """Windows refuses to remove a folder any process still has as its working
    directory. setup.bat's own window is not the only candidate: called from
    another script it hands the directory back to the caller on exit, and an
    Explorer window open there holds it too. The files always go on the first
    pass; the empty folder has to be retried."""
    text = _code("setup.bat")
    cleanup = text[text.index("\n:cleanup"):text.index("\n:done")]
    assert "echo :retry" in cleanup and "echo :gone" in cleanup
    assert 'echo if not exist "%SRC%" goto :gone' in cleanup
    assert "goto :retry" in cleanup
    # The wait is bounded, and the loop counter is read on a line of its own
    # (a parenthesised block would freeze it at parse time).
    m = re.search(r"echo if %%N%% lss (\d+) ping -n (\d+)", cleanup)
    assert m, "the retry must be bounded and spaced"
    assert 20 <= int(m.group(1)) * int(m.group(2)) <= 120, "about a minute of retries"


@setup_bat
def test_the_clean_up_converts_the_manifest_paths():
    """MANIFEST.txt writes posix paths (``as_posix()`` in the packager) and
    Windows' ``del`` reads a forward slash as the start of an option: without
    the conversion the clean-up deleted the package's root files and left
    everything inside a folder, silently (every line ends in ``2>nul``)."""
    assert "as_posix()" in _read("tools/make_package.py")
    cleanup = _code("setup.bat")
    cleanup = cleanup[cleanup.index("\n:cleanup"):cleanup.index("\n:done")]
    assert "call :kill" in cleanup, "the manifest path must go through a conversion"
    assert 'echo set "F=%%F:/=\\%%"' in cleanup, "slashes are not converted"
    assert 'echo if exist "%SRC%\\%%F%%" del /f /q "%SRC%\\%%F%%"' in cleanup
    # The subroutine sits before the body, so the script does not fall into it
    # (its last line deletes the script, and cmd cannot read past that).
    assert cleanup.index("echo goto :main") < cleanup.index("echo :kill") < cleanup.index("echo :main")


def test_the_quick_start_carries_the_current_version():
    """INSTALL.txt is the first thing read on the other machine; a 2.4.1 package
    shipped one that said 2.4.0."""
    assert VERSION in _read("INSTALL.txt")


def test_the_package_ships_setup_bat_and_the_documents_describe_it():
    assert '"setup.bat"' in _read("tools/make_package.py")
    inst = _read("docs/INSTALL.html")
    assert "setup.bat" in inst and "--no-services" in inst and "--keep-installer" in inst
    assert "Programs\\ner-analyzer" in inst
    assert "setup.bat" in _read("INSTALL.txt")
    assert "setup.bat" in _read("build_package.bat")
