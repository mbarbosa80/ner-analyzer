#!/usr/bin/env python3
"""One-command launcher.

Starts the server with the compiled front-end already bundled, on the private
runtime install.bat built:

* ``.python`` — the Python bundled with an installation package. Nothing else
  is needed on the machine; ``install.bat`` unpacks it and installs the packages.
* ``.venv`` — a development checkout using the machine's own Python 3.11+.
  Created here on first run if it is missing, with the dependencies installed
  from ``vendor/wheels`` when present, otherwise from the internet.

    python run.py                 # start on port 8000
    python run.py --port 8080
    python run.py --no-browser
    python run.py --sample         # also generate the synthetic demo documents
    python run.py --reinstall      # rebuild the .venv (development checkouts)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
# The bundled runtime: python.org's embeddable package on Windows, a
# standalone CPython build on macOS (3.0.0) — each unpacked into .python.
EMBEDDED = ROOT / ".python" / ("python.exe" if os.name == "nt" else "bin/python3")
MIN_PY = (3, 11)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def interpreter(reinstall: bool) -> Path:
    """The bundled runtime when install.bat built one, else the .venv."""
    if EMBEDDED.exists():
        marker = EMBEDDED.parent / ".deps-installed"
        if reinstall or not marker.exists():
            print("The bundled runtime in .python is not fully installed. "
                  + ("Run install.bat" if os.name == "nt" else "Run setup.command")
                  + (" again" if reinstall else "") + ".")
            raise SystemExit(1)
        return EMBEDDED
    return ensure_venv(reinstall)


def ensure_venv(reinstall: bool) -> Path:
    py = venv_python()
    if reinstall and VENV.exists():
        import shutil
        print("Removing the existing virtual environment…")
        shutil.rmtree(VENV)
    if not py.exists():
        import venv  # not present in the bundled runtime, which never gets here
        print(f"Creating a virtual environment in {VENV}…")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    marker = VENV / ".deps-installed"
    wheels = ROOT / "vendor" / "wheels"
    reqs = ROOT / ("requirements-win.txt" if (os.name == "nt" and
                                             (ROOT / "requirements-win.txt").exists())
                   else "requirements.txt")
    if not marker.exists() or marker.stat().st_mtime < reqs.stat().st_mtime:
        # A packaged copy carries its own wheels. Installing from those instead of
        # PyPI is not just faster — it is the only thing that works on a venue
        # network with no outbound access, and it means the machine gets exactly
        # the versions this build was tested against rather than whatever PyPI
        # is serving today.
        offline = wheels.is_dir() and any(wheels.glob("*.whl"))
        if offline:
            print(f"Installing from the bundled packages in {wheels} (no internet needed)…")
            pip = [str(py), "-m", "pip", "install", "--no-index",
                   "--find-links", str(wheels)]
            subprocess.check_call(pip + ["--upgrade", "pip", "-q"])
            subprocess.check_call(pip + ["-r", str(reqs)])
        else:
            print("Installing dependencies from the internet (first run takes a few "
                  "minutes)…")
            subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"])
            subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(reqs)])
        marker.write_text("ok", encoding="utf-8")
    return py


def main() -> int:
    if sys.version_info < MIN_PY:
        print(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ is required; this is "
              f"{sys.version_info.major}.{sys.version_info.minor}.")
        return 1

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reinstall", action="store_true")
    ap.add_argument("--sample", action="store_true",
                    help="generate the synthetic demonstration documents in sample_data/")
    ap.add_argument("--reload", action="store_true", help="developer auto-reload")
    args = ap.parse_args()

    py = interpreter(args.reinstall)

    static = ROOT / "backend" / "app" / "static"
    if not (static / "index.html").exists():
        print("WARNING: the compiled front-end is missing "
              f"({static}).\n         Rebuild it with:  cd frontend && npm install && npm run build\n"
              "         The API and the reports still work without it.")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + env.get("PYTHONPATH", "")
    # Never the user's own site-packages (2.18.1): the server must see exactly
    # what install.bat put into the runtime, and nothing a stray
    # "pip install --user" left under %APPDATA%.
    env["PYTHONNOUSERSITE"] = "1"

    if args.sample:
        print("Generating synthetic demonstration documents…")
        subprocess.check_call([str(py), "-m", "app.sample_data", "--out",
                               str(ROOT / "sample_data")], env=env, cwd=ROOT / "backend")

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        # Open the browser when the server answers, not two seconds after it
        # was asked to start: a cold start is 20-40 s (PyMuPDF, OR-Tools, the
        # migration), and a tab opened before that shows "cannot be reached".
        def _open_when_up() -> None:
            import socket
            deadline = time.time() + 120
            while time.time() < deadline:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((args.host, args.port)) == 0:
                        break
                time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=_open_when_up, daemon=True).start()

    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"
    print(f"\n  NER Spatial Coverage Analyzer {version}\n  {url}\n"
          f"  Cold start takes 20-40 s. Press Ctrl+C (or close this window) to stop.\n")
    # --app-dir puts backend/ on the import path explicitly. The bundled
    # runtime ignores PYTHONPATH and the working directory by design (its
    # ._pth file is the whole search path), so the env var above is only for
    # the .venv case; this flag works for both.
    cmd = [str(py), "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
           "--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    try:
        return subprocess.call(cmd, env=env, cwd=ROOT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
