"""2.6.1 — the watchdog must not kill a server that is starting or merely slow.

What happened on 22 Sep 2026, from data\\watchdog.log and data\\server.log on
Marcelo's laptop (75% CPU, 1 GB of 16 GB free):

    10:23:42  not answering after two probes          <- the server had died
    10:24:15  (restart: serve.py starts importing)
    10:24:49  not answering after two probes          <- a SECOND watchdog run,
    10:24:53  (server-stop kills the importing server;    38 s after the first
               a second serve.py starts)                  restart began)
    10:25:03  restart FAILED                          <- the first run's 45 s
    ...       ERROR [Errno 10048] error while attempting to bind      were up

Two watchdog runs overlapped because the .vbs wrapper returned at once, so the
scheduled task's IgnoreNew policy had no running instance to protect. The
second run could not tell "still importing" from "dead", killed the server
the first had started, and launched another. From the chair: "the app is slow
and opening a project does not work".

These tests hold the scripts to the rules that came out of it. They read the
scripts as text — the watchdog is PowerShell and runs only on Windows — the
same way test_installer.py holds the launchers to the bundled-runtime layout.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --- the wrapper waits, so IgnoreNew applies ---------------------------------

def test_the_hidden_wrapper_waits_for_the_script():
    vbs = _read("tools/watchdog-hidden.vbs")
    line = next((ln for ln in vbs.splitlines() if ln.startswith("sh.Run") and "watchdog.ps1" in ln), None)
    assert line, "the wrapper no longer launches watchdog.ps1 through sh.Run"
    run = re.search(r",\s*0\s*,\s*(True|False)\s*$", line)
    assert run and run.group(1) == "True", (
        "bWaitOnReturn must be True: with False the task instance ends the moment "
        "it fires and IgnoreNew never applies, so two watchdogs can run at once")


def test_the_task_keeps_the_single_instance_policy():
    harden = _read("tools/task-harden.ps1")
    assert "MultipleInstancesPolicy" in harden and "IgnoreNew" in harden


# --- one run at a time, even without the policy -------------------------------

def test_the_watchdog_holds_a_lock_file_for_the_whole_run():
    ps = _read("tools/watchdog.ps1")
    assert "watchdog.lock" in ps
    lock_taken = ps.index("Set-Content -Path $lock")
    probe = ps.index("Invoke-WebRequest -UseBasicParsing -Uri $url")
    assert lock_taken < probe, "the lock must be taken before the first probe"
    assert "Remove-Item $lock -Force" in ps
    assert re.search(r"finally\s*\{\s*Remove-Item \$lock", ps), \
        "the lock is released in a finally block, whatever path the run takes"
    # A lock left by a crashed run must not silence the watchdog forever.
    assert re.search(r"TotalMinutes -lt 5", ps), "a stale lock (> 5 min) is ignored"


# --- starting and slow are not dead ----------------------------------------

def test_a_server_process_younger_than_three_minutes_is_left_alone():
    ps = _read("tools/watchdog.ps1")
    m = re.search(r"\$age\.TotalMinutes -lt 3", ps)
    assert m, "no starting grace: a server still importing would be killed"
    # ...and that check comes before any restart.
    assert ps.index("TotalMinutes -lt 3") < ps.index("'server-stop.ps1')")


def test_a_listening_but_slow_server_is_restarted_only_after_three_runs():
    ps = _read("tools/watchdog.ps1")
    assert "watchdog-slow.txt" in ps, "the slow count must survive between runs"
    assert re.search(r"if \(\$n -lt 3\)", ps)
    assert ps.index("Listening") < ps.index("'server-stop.ps1')")
    # An answering server clears the count.
    alive_block = ps[ps.index("if ($alive)"):ps.index("if ($alive)") + 200]
    assert "Remove-Item $state" in alive_block


def test_after_a_restart_the_health_check_is_polled_not_asked_once():
    ps = _read("tools/watchdog.ps1")
    assert "Start-Sleep -Seconds 45" not in ps, "the fixed 45 s wait is what raised false FAILED"
    assert re.search(r"AddSeconds\(150\)", ps)
    assert re.search(r"while \(\(Get-Date\) -lt \$deadline\)", ps)


def test_the_watchdog_records_the_power_events_before_restarting():
    ps = _read("tools/watchdog.ps1")
    assert "Microsoft-Windows-Kernel-Power" in ps
    for code in ("506", "507", "105"):
        assert code in ps
    assert ps.index("Kernel-Power") < ps.index("'server-stop.ps1')")


def test_the_watchdog_still_only_stops_this_folder_s_server():
    ps = _read("tools/watchdog.ps1")
    stop = _read("tools/server-stop.ps1")
    # The same command-line match as server-stop.ps1: this folder, this launcher.
    for needle in ("serve.py", "uvicorn*app.main:app", "run.py"):
        assert needle in ps and needle in stop
    assert "taskkill" not in ps.lower()


# --- the launcher refuses to run twice ---------------------------------------

def test_the_launcher_takes_a_named_mutex_before_importing_anything():
    py = _read("tools/serve.py")
    assert "CreateMutexW" in py
    assert "ERROR_ALREADY_EXISTS = 183" in py
    assert py.index("_already_running()") < py.index("import uvicorn"), \
        "the mutex must be checked before the slow imports, or it protects nothing"
    # The name carries the folder, so two installations do not block each other.
    assert re.search(r'"Local\\\\ner-analyzer-" \+ hashlib', py)


def test_the_launcher_s_mutex_is_a_no_op_off_windows():
    import importlib.util
    spec = importlib.util.spec_from_file_location("serve_under_test", ROOT / "tools" / "serve.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import sys
    if sys.platform != "win32":
        assert mod._already_running() is False
    else:
        # On Windows the first call takes the mutex — unless this folder's
        # server is running and already holds it, as it is on Marcelo's
        # machine when run-tests.bat runs beside the live server. Either way
        # the second call must see it taken.
        mod._already_running()
        assert mod._already_running() is True


# --- the browser side ---------------------------------------------------------

def test_the_interface_tells_a_dead_server_from_a_dead_session():
    api = _read("frontend/src/lib/api.ts")
    assert "SERVER_UNREACHABLE" in api and "onConnection" in api
    assert re.search(r"catch\s*\{\s*setReachable\(false\);\s*throw new Error\(t\(SERVER_UNREACHABLE\)\)", api)
    app = _read("frontend/src/App.tsx")
    assert "onConnection" in app and "api.health()" in app
    assert "server not answering — reconnecting" in app
    # The session is kept when the server is merely unreachable.
    assert "isReachable()" in app
