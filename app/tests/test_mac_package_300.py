"""3.0.0 — the macOS package: setup.command, the mac/ scripts, the lock file,
the packager.

There is no Mac to run these on where the application is built, so what can be
held is held here: the scripts parse, they stay inside what the /bin/bash 3.2
of macOS understands, they install offline into an isolated runtime, an update
backs up and keeps data/, the launch agent is per user, the zip carries the
executable bit, and both systems run the same pinned packages. The install
itself was rehearsed end to end on Linux with a Linux runtime and Linux wheels
(the shell steps are the same) — see the 3.0.0 project notes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAC_SCRIPTS = ["setup.command", "mac/autostart.command", "mac/start.command",
               "mac/stop.command", "mac/backup.command", "mac/run-tests.command",
               "mac/uninstall.command"]

needs_files = pytest.mark.skipif(not (ROOT / "setup.command").exists(),
                                 reason="the macOS installer is not in this copy")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _code(rel: str) -> str:
    """The script without its comment lines."""
    return "\n".join(ln for ln in _read(rel).splitlines() if not ln.lstrip().startswith("#"))


@needs_files
@pytest.mark.parametrize("rel", MAC_SCRIPTS)
def test_every_mac_script_is_there_and_starts_with_bash(rel):
    text = _read(rel)
    assert text.startswith("#!/bin/bash\n"), rel
    assert "\r\n" not in text, f"{rel}: CRLF line endings break bash on a Mac"


@needs_files
@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash on this machine")
@pytest.mark.parametrize("rel", MAC_SCRIPTS)
def test_every_mac_script_parses(rel):
    r = subprocess.run(["bash", "-n", str(ROOT / rel)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@needs_files
@pytest.mark.parametrize("rel", MAC_SCRIPTS)
def test_nothing_newer_than_the_bash_3_2_a_mac_ships(rel):
    code = _code(rel)
    for pattern, why in ((r"declare\s+-A", "associative arrays (bash 4)"),
                         (r"\$\{[A-Za-z_]+(,,|\^\^)", "case conversion (bash 4)"),
                         (r"\bmapfile\b|\breadarray\b", "mapfile (bash 4)"),
                         (r"&>>|\|&", "redirection shorthand (bash 4)"),
                         (r"\bsed\s+-i\b", "sed -i differs on macOS"),
                         (r"\breadlink\s+-f\b", "readlink -f is not on older macOS"),
                         (r"\bsha256sum\b", "no sha256sum on macOS (shasum -a 256)")):
        assert not re.search(pattern, code), f"{rel}: {why}"


@needs_files
def test_setup_installs_offline_into_an_isolated_runtime():
    code = _code("setup.command")
    assert 'TARGET="$HOME/Applications/ner-analyzer"' in code
    assert "pip install" in code
    for flag in ("--no-index", "--no-deps", "--ignore-installed", "-r requirements-lock-mac.txt",
                 "PYTHONNOUSERSITE=1", '"$PY" -s'):
        assert flag in code, flag
    assert "tools/check_env.py" in code
    assert "xattr -dr com.apple.quarantine" in code, "Gatekeeper would stop the runtime"


@needs_files
def test_setup_refuses_an_intel_mac_and_an_old_macos():
    code = _code("setup.command")
    assert '"$ARCH" != "arm64"' in code and "sysctl.proc_translated" in code
    assert '-ge 11' in code


@needs_files
def test_an_update_backs_up_first_keeps_data_and_can_roll_back():
    code = _code("setup.command")
    backup = code.index("tools/backup.py")
    move = code.index('mv "$TARGET" "$PREV"')
    assert backup < move, "back up before anything moves"
    assert 'mv "$PREV/data" "$TARGET/data"' in code
    assert "rollback()" in code and code.count("rollback;") >= 5
    assert "--exclude './data'" in code, "never copies a data folder from a package"
    assert "--exclude './setup.command'" in code, "the installer does not copy itself"


@needs_files
def test_the_clean_up_removes_only_the_package_and_its_zip():
    code = _code("setup.command")
    assert 'rm -rf "$TARGET/vendor"' in code
    guard = code.index('[ -f "$SRC/MANIFEST.txt" ] && [ -f "$SRC/setup.command" ]')
    assert guard < code.index('rm -rf "$SRC"')
    assert "ner-analyzer-*) rmdir" in code, "never rmdir Downloads itself"
    assert 'ZIP="ner-analyzer-$VERSION-macos-arm64.zip"' in code


@needs_files
def test_the_launch_agent_is_per_user_and_restarts_a_crash_only():
    code = _code("mac/autostart.command")
    assert '"$HOME/Library/LaunchAgents/$LABEL.plist"' in code
    assert 'gui/$(id -u)' in code, "the person's own launchd domain, no sudo"
    assert "<key>RunAtLoad</key><true/>" in code
    assert "<key>SuccessfulExit</key><false/>" in code, \
        "serve.py exits 0 when the port is already served — that must not loop"
    assert "<string>-s</string>" in code and "PYTHONNOUSERSITE" in code
    assert "sudo" not in code


@needs_files
def test_stop_takes_down_only_this_folders_server():
    code = _code("mac/stop.command")
    assert 'pkill -f "$ROOT/tools/serve.py"' in code
    assert "killall" not in code


def _pins(rel: str) -> dict[str, str]:
    out = {}
    for line in _read(rel).splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            k, v = line.split("==", 1)
            out[re.sub(r"[-_.]+", "-", k).lower()] = v.strip()
    return out


@needs_files
def test_both_systems_run_the_same_pinned_packages():
    assert _pins("requirements-lock-mac.txt") == _pins("requirements-lock-win.txt")


def test_run_py_finds_the_mac_runtime():
    assert 'EMBEDDED = ROOT / ".python" / ("python.exe" if os.name == "nt" else "bin/python3")' \
        in _read("run.py")


@pytest.mark.skipif(not (ROOT / "tools" / "make_package.py").exists(),
                    reason="the packager is not in this copy")
def test_the_packager_requires_the_mac_scripts_and_keeps_them_executable(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import make_package as M
    finally:
        sys.path.pop(0)
    for rel in MAC_SCRIPTS + ["requirements-lock-mac.txt"]:
        assert rel in M.REQUIRED_MAC, rel
    assert M.MAC_RUNTIME_SHA256 and len(M.MAC_RUNTIME_SHA256) == 64
    src = tmp_path / "x.command"
    src.write_text("#!/bin/bash\necho hi\n")
    z_path = tmp_path / "t.zip"
    with zipfile.ZipFile(z_path, "w") as z:
        M._zip_add(z, src, "ner-analyzer/x.command", True)
        M._zip_add(z, src, "ner-analyzer/y.txt", False)
    with zipfile.ZipFile(z_path) as z:
        modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
        systems = {i.create_system for i in z.infolist()}
    assert modes == {"ner-analyzer/x.command": 0o755, "ner-analyzer/y.txt": 0o644}
    assert systems == {3}, "Unix, so Archive Utility honours the modes"


@pytest.mark.skipif(not (ROOT / "tools" / "make_package.py").exists(),
                    reason="the packager is not in this copy")
def test_the_packager_refuses_a_windows_wheel_in_the_mac_set(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import make_package as M
    finally:
        sys.path.pop(0)
    bad = tmp_path / "numpy-2.5.2-cp312-cp312-win_amd64.whl"
    bad.write_bytes(b"")
    with pytest.raises(SystemExit, match="Windows wheel"):
        M.assert_mac_wheels([bad])
