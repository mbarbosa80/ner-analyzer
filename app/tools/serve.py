"""Start the analyzer with no console window, from any working directory.

Why this exists rather than a .cmd or a shortcut
------------------------------------------------
The server has to come back on its own after a reboot, and it has to come back
pointing at the *same* database. Three things make that fragile on Windows, and
this file removes all three:

1. **Working directory.** A scheduled task does not start in the project folder.
   Everything here is resolved from ``__file__``, so the paths are the same
   whether it is launched by the task, by a shortcut or by hand.
2. **The data folder.** ``NER_DATA_DIR`` and ``NER_DATABASE_URL`` are pinned to
   absolute paths before the app is imported. The app would derive the same
   paths on its own, but stating them means a wrong one is visible in the log
   instead of silently creating a second, empty database.
3. **No stdout.** Run under ``pythonw.exe`` there is no console, and on some
   configurations a plain ``print`` then raises. Output is redirected to a log
   file first, so a startup failure leaves a readable trace instead of a
   process that vanishes.

Run it with ``pythonw.exe`` for a windowless service, or ``python.exe`` to watch
it in a terminal.
"""

from __future__ import annotations

import datetime as _dt
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The server imports only what install.bat put into its runtime (2.18.1). The
# embedded runtime is isolated by its ._pth file already; a .venv is not, and
# a stray "pip install --user" would put another pymupdf ahead of the tested
# one. The user site-packages leave sys.path before anything is imported.
try:
    import site as _site
    _user_site = _site.getusersitepackages()
    if _user_site:
        sys.path[:] = [p for p in sys.path if not str(p).startswith(str(_user_site))]
    os.environ["PYTHONNOUSERSITE"] = "1"
except Exception:  # noqa: BLE001 — never a reason not to start
    pass

HOST = os.environ.get("NER_HOST", "127.0.0.1")
PORT = int(os.environ.get("NER_PORT", "8000"))

LOG_DIR = ROOT / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "server.log"


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


_MUTEX = None   # held for the life of the process; Windows releases it at exit


def _already_running() -> bool:
    """Is another launcher of THIS folder alive, whether or not it has bound yet?

    The port check only sees a server that has finished starting. On 22 Sep
    2026 two launchers were started 38 seconds apart on a loaded laptop: the
    first was still importing its libraries, so the second saw the port free,
    imported too, and lost the bind with error 10048 (2.6.1). A named mutex is
    taken the moment the launcher starts, before any import, so the second
    launcher can tell and leave. The name carries the folder, so two
    installations on one machine do not block each other. Windows only; on
    other systems this says "no" and the port check stands alone.
    """
    global _MUTEX
    if sys.platform != "win32":
        return False
    import ctypes
    import hashlib
    name = "Local\\ner-analyzer-" + hashlib.sha1(str(ROOT).lower().encode()).hexdigest()[:16]
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, True, name)
    ERROR_ALREADY_EXISTS = 183
    if not handle:
        return False                         # cannot tell; let the port check decide
    if k32.GetLastError() == ERROR_ALREADY_EXISTS:
        k32.CloseHandle(ctypes.c_void_p(handle))
        return True
    _MUTEX = handle
    return False


def main() -> int:
    # Redirect first: under pythonw there is nowhere else for a traceback to go.
    log = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    print(f"\n===== {_stamp()} starting =====")
    print(f"root        {ROOT}")
    print(f"interpreter {sys.executable}")

    if _already_running():
        print("another launcher of this folder is already running — nothing to do, exiting.")
        return 0
    if _port_in_use(HOST, PORT):
        # A second copy would fail on bind anyway; say so plainly and stop.
        print(f"{HOST}:{PORT} is already serving — nothing to do, exiting.")
        return 0

    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("NER_DATA_DIR", str(ROOT / "data"))
    os.environ.setdefault("NER_DATABASE_URL",
                          f"sqlite:///{ROOT / 'data' / 'ner.sqlite3'}")
    print(f"data dir    {os.environ['NER_DATA_DIR']}")
    print(f"database    {os.environ['NER_DATABASE_URL']}")

    try:
        import uvicorn
    except Exception as exc:                       # noqa: BLE001 - want the trace
        print(f"FATAL: uvicorn could not be imported from {sys.executable}: {exc!r}")
        print("       the virtual environment is probably missing or incomplete;")
        print("       run  python run.py  once from a terminal to rebuild it.")
        return 2

    print(f"binding     http://{HOST}:{PORT}/ (first start also runs the migration)")
    try:
        # Uvicorn's own logging is left on deliberately. Under pythonw this file
        # is the only place a startup failure can be seen, and "Application
        # startup complete" with its timestamp is what tells you whether a slow
        # boot was the migration or a hang.
        uvicorn.run("app.main:app", host=HOST, port=PORT)
    except Exception as exc:                       # noqa: BLE001
        import traceback
        print(f"FATAL at {_stamp()}: {exc!r}")
        traceback.print_exc()
        return 1
    print(f"===== {_stamp()} stopped =====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
