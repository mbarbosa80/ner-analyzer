"""Build the installation package of this application.

    python tools/make_package.py                      # dist/ner-analyzer-<version>-windows.zip
    python tools/make_package.py --wheels vendor/wheels --out dist
    python tools/make_package.py --label test         # ...-<version>-test-windows.zip
    python tools/make_package.py --platform mac       # dist/ner-analyzer-<version>-macos-arm64.zip
    python tools/make_package.py --public             # ...-<version>-public-windows.zip (4.3.0)

``--public`` (4.3.0) builds the edition that may be published: the same
application without ``backend/app/reference_private`` (a client's own
reference material — see its README) and without the archived manual under
``docs/history``, and it refuses to build while any shipped text names an
event, an organiser, a venue or an employer (the private list in
``backend/app/reference_private/public_banned.txt``).

The macOS package (3.0.0) is the same application with a different runtime
and installer: a standalone CPython 3.12 build for Apple Silicon
(python-build-standalone, pinned by SHA-256 like the Windows runtime) in
``vendor/python-mac``, the same pinned packages built for macOS arm64 in
``vendor/wheels-mac`` (``requirements-lock-mac.txt``), and ``setup.command``
in place of ``setup.bat``. Inside the zip both are laid out as
``vendor/python`` and ``vendor/wheels``, and every ``.command`` carries the
executable bit whatever system built the zip.

What goes in: the source, the **already-compiled** interface, the manuals,
the tests, the operating scripts, the licence, every Python package the
application needs (``vendor/wheels``, filled by ``build_package.bat``) and
**the Python runtime itself**: the official python.org "embeddable package"
for Windows 64-bit, fetched into ``vendor/python`` on first build and checked
against a pinned SHA-256 on every build. The target machine therefore needs
no internet and no Python — ``install.bat`` unpacks the runtime into
``.python`` and installs the packages into it. ``setup.bat`` (2.4.0) is the
one-step form of the same thing: it installs into a folder of its own,
registers the tasks, starts the server and then deletes the unzipped package
and the zip, so the machine keeps the application and nothing else.

Why 3.12.10 specifically: the wheels are built for CPython 3.12, and 3.12.10
(April 2025) is the last 3.12 release with Windows binaries — later 3.12.x
are source-only security releases. Moving to a newer Python means moving the
whole wheel set (a MINOR version of this application), not just this pin.

What stays out, and this is the part worth reading:

  * ``data/``          the database, the uploads, the backups, the server log.
  * ``.python/``       the runtime *unpacked* by install.bat, with the packages
  * ``.venv/``         installed into it (or, on a development checkout, the
                       virtual environment). Both are built on the target
                       machine by install.bat; the package carries the zip
                       and the wheels they are built from, never the result.
  * ``__pycache__``    compiled for whatever Python built it.
  * ``node_modules``   only needed to *build* the interface, never to run it.
  * ``.git``           carries every earlier revision, including anything that
                       was ever committed and later removed.
  * one-off scripts    the diagnostic probes under ``tools/`` written against
                       one machine's files. Only the scripts listed in
                       ``SHIP_TOOLS`` travel.

The exclusion of ``data/`` is a security property, not tidiness. That folder
holds the venue drawings, the TEAP imports, the NER registers, the audit log
**and the account table with its password hashes**. A package that carries it
is a package that has to be handled like the database itself — encrypted in
transit, tracked, and destroyed afterwards. A package without it is just
software, and can travel on any USB stick. The default is therefore empty, and
carrying data across is a separate, deliberate act with its own instructions
in the installation manual.

The package is verified before it is written: the manifest is checked against
that exclusion list, the version in ``VERSION`` is checked against the
interface bundle and the manuals, and the build refuses rather than shipping
a surprise. A ``.sha256`` file is written beside the zip so the copy on the
other machine can be checked.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

# The Python runtime shipped inside the package. Pinned by content, not just
# by name: a build refuses a file that does not hash to this value, so a
# corrupted or substituted download can never become the runtime other
# people install. install.bat additionally checks the Authenticode signature
# of python.exe (Python Software Foundation) after unpacking.
EMBED_VERSION = "3.12.10"
EMBED_NAME = f"python-{EMBED_VERSION}-embed-amd64.zip"
EMBED_URL = f"https://www.python.org/ftp/python/{EMBED_VERSION}/{EMBED_NAME}"
EMBED_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
EMBED_SIZE = 11_133_606

# The macOS runtime (3.0.0): python-build-standalone's "install_only" CPython
# for Apple Silicon. The same 3.12 line as Windows, so the same cp312 wheels.
MAC_RUNTIME_RELEASE = "20261009"
MAC_RUNTIME_NAME = f"cpython-3.12.15+{MAC_RUNTIME_RELEASE}-aarch64-apple-darwin-install_only.tar.gz"
MAC_RUNTIME_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
                   f"{MAC_RUNTIME_RELEASE}/{MAC_RUNTIME_NAME.replace('+', '%2B')}")
MAC_RUNTIME_SHA256 = "83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8"
MAC_RUNTIME_SIZE = 25_165_569

# Directory names excluded wherever they appear.
EXCLUDE_DIRS = {
    ".python", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", ".git", ".idea", ".vscode", "dist",
    "sample_data", "vendor",
}
# Top-level names excluded by path, not by name, so a source file that happens
# to live in a folder called "data" is not silently dropped.
EXCLUDE_TOP = {"data"}
# Anything starting with these prefixes at any level: working folders that
# accumulate on the development machine and never belong in a package.
EXCLUDE_PREFIXES = ("_backup", "_removed", "_ship", "_sync", "_deploy",
                    "_to_delete", "_install-test", "preview")

EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite3", ".sqlite3-wal",
                    ".sqlite3-shm", ".db", ".tgz", ".zip", ".sha256"}
EXCLUDE_FILES = {"nul", "pytest-full.txt", "npm-install.log", "uitest.mjs", ".DS_Store"}

# The scripts under tools/ that an installation needs. Everything else in that
# folder is a one-off probe written against one machine's files — some carry
# that machine's paths — and stays on the development machine.
SHIP_TOOLS = {
    "serve.py", "server-start.cmd", "server-stop.cmd", "server-stop.ps1",
    "watchdog.ps1", "watchdog-install.ps1", "watchdog-hidden.vbs", "task-harden.ps1",
    "signin-task.ps1",
    "backup.py", "reset_password.py", "check_env.py", "check_title_blocks.py", "validate_against.py",
    "probe_sheet_numbers.py", "profile_report.py", "make_package.py",
}

# Anything matching these must never appear in a package. Checked after the
# file list is built, as a second pair of eyes on the rules above.
FORBIDDEN = ("ner.sqlite3", "server.log", "server.err.log", "pyvenv.cfg",
             "python312.dll", ".deps-installed",
             "/data/", "\\data\\", "/uploads/", "/backup-", "C:\\Users\\")

#: Set by ``--public`` (4.3.0): the edition that may be published.
PUBLIC = False
#: Left out of a public package: a client's reference material, and the
#: verbatim archive of an old manual. The README of the private folder stays,
#: so a reader of the source knows what the folder is for.
PRIVATE_PATHS = ("backend/app/reference_private/", "docs/history/")
PRIVATE_KEEP = {"backend/app/reference_private/README.md"}

#: Words that may not appear in any text a public package ships (4.3.0):
#: events, organisers, rights holders, venues of past or current projects,
#: employers and clients. The tool is the author's own; the documents it was
#: tried on are somebody else's. The list itself names them, so it is private
#: too: ``backend/app/reference_private/public_banned.txt``, one pattern per
#: line (a regular expression, matched case-insensitively as whole words).
#: Without it the public edition is not built — it could not be checked.
PUBLIC_BANNED_FILE = ROOT / "backend" / "app" / "reference_private" / "public_banned.txt"


def public_banned() -> "re.Pattern | None":
    try:
        lines = PUBLIC_BANNED_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    words = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not words:
        return None
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


PUBLIC_SCAN_SUFFIXES = (".py", ".ts", ".tsx", ".css", ".html", ".md", ".txt", ".json",
                        ".bat", ".cmd", ".ps1", ".vbs", ".command", ".sh", ".yml",
                        ".ini", ".js", ".mjs")


def public_hits(files) -> list[str]:
    """``path:line: word`` for every banned word in the given text files."""
    banned = public_banned()
    if banned is None:
        raise SystemExit("refusing to build the public edition: the private list of "
                         f"banned words is missing ({PUBLIC_BANNED_FILE})")
    hits = []
    for f in files:
        f = pathlib.Path(f)
        if f.suffix.lower() not in PUBLIC_SCAN_SUFFIXES:
            continue
        rel = f.relative_to(ROOT).as_posix() if f.is_absolute() and ROOT in f.parents else str(f)
        text = f.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            for m in banned.finditer(line):
                hits.append(f"{rel}:{n}: {m.group(0)}")
    return hits


def assert_public(files) -> None:
    hits = public_hits(files)
    if hits:
        raise SystemExit("refusing to build the public edition: these files name an "
                         "event, an organiser, a venue or an employer\n  "
                         + "\n  ".join(hits[:200]))


# Files without which the package would install something incomplete.
REQUIRED = (
    "VERSION", "LICENSE.txt", "NOTICE.txt", "THIRD-PARTY-NOTICES.txt",
    "CHANGELOG.md", "INSTALL.txt",
    "setup.bat", "setup-noadmin.bat", "install.bat", "start.bat", "stop.bat", "autostart.bat",
    "backup.bat", "reset-password.bat",
    "run-tests.bat", "run.py", "requirements.txt", "requirements-win.txt",
    "requirements-lock-win.txt",
    "backend/app/static/index.html",
    "docs/MANUAL.html", "docs/INSTALL.html", "docs/QUICK-INSTALL.html",
    "tools/serve.py", "tools/server-start.cmd", "tools/server-stop.cmd",
    # autostart.bat cannot register the sign-in task without it (2.16.1).
    "tools/signin-task.ps1", "tools/watchdog-install.ps1",
    # the way back in for a forgotten password (4.0.0)
    "tools/reset_password.py",
)
REQUIRED_MAC = (
    "VERSION", "LICENSE.txt", "NOTICE.txt", "THIRD-PARTY-NOTICES.txt",
    "CHANGELOG.md", "INSTALL.txt",
    "setup.command", "requirements-lock-mac.txt", "run.py",
    "mac/autostart.command", "mac/start.command", "mac/stop.command",
    "mac/backup.command", "mac/run-tests.command", "mac/uninstall.command",
    "mac/reset-password.command", "tools/reset_password.py",
    "backend/app/static/index.html",
    "docs/MANUAL.html", "docs/INSTALL.html", "docs/QUICK-INSTALL.html",
    "tools/serve.py", "tools/backup.py", "tools/check_env.py",
)
#: files that must be executable on macOS once Archive Utility unzips them
MAC_EXECUTABLE_SUFFIXES = (".command", ".sh")


def wanted(path: pathlib.Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return False
    if parts and parts[0] in EXCLUDE_TOP:
        return False
    if any(p.startswith(EXCLUDE_PREFIXES) for p in parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_FILES:
        return False
    if parts[0] == "tools" and (len(parts) != 2 or parts[1] not in SHIP_TOOLS):
        return False
    if PUBLIC:
        posix = rel.as_posix()
        if posix.startswith(PRIVATE_PATHS) and posix not in PRIVATE_KEEP:
            return False
    return True


def collect() -> list[pathlib.Path]:
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and wanted(p))


def assert_clean(files: list[pathlib.Path]) -> None:
    """Refuse to build a package that carries data or a foreign virtualenv."""
    bad = []
    for f in files:
        rel = "/" + f.relative_to(ROOT).as_posix()
        if any(token in rel for token in FORBIDDEN):
            bad.append(rel)
    if bad:
        raise SystemExit(
            "refusing to build: these would have been included and must not be\n  "
            + "\n  ".join(bad))
    # A personal path inside a shipped script is the same mistake one level
    # down: the script would look for a file on somebody else's computer.
    leaks = []
    for f in files:
        if f.suffix in (".py", ".bat", ".cmd", ".ps1", ".txt", ".md", ".html", ".command"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"C:\\Users\\[A-Za-z]", text):
                leaks.append(f.relative_to(ROOT).as_posix())
    if leaks:
        raise SystemExit(
            "refusing to build: these files carry a personal Windows path\n  "
            + "\n  ".join(leaks))


def assert_complete(files: list[pathlib.Path], required=REQUIRED) -> None:
    present = {f.relative_to(ROOT).as_posix() for f in files}
    missing = [r for r in required if r not in present]
    if missing:
        raise SystemExit("refusing to build: the package would be incomplete\n  "
                         + "\n  ".join(missing)
                         + "\n(the interface is built with:  cd frontend && npm run build)")


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_runtime(vendor_python: pathlib.Path, download: bool) -> pathlib.Path:
    """Return the pinned embeddable-Python zip, fetching it once if allowed.

    A file that is present but does not hash to EMBED_SHA256 is refused, not
    replaced: somebody has to look at why it differs.
    """
    target = vendor_python / EMBED_NAME
    if not target.exists():
        if not download:
            raise SystemExit(f"{target} is missing — run build_package.bat on a machine "
                             f"with internet (it fetches {EMBED_URL}), or pass "
                             "--without-python for a package that needs Python "
                             "installed on the target")
        import urllib.request
        vendor_python.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".zip.part")
        print(f"fetching {EMBED_URL} ...")
        with urllib.request.urlopen(EMBED_URL, timeout=120) as r, tmp.open("wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(target)
    digest = _sha256(target)
    if digest != EMBED_SHA256 or target.stat().st_size != EMBED_SIZE:
        raise SystemExit(
            f"refusing to build: {target.name} does not match the pinned runtime\n"
            f"  expected sha256 {EMBED_SHA256} ({EMBED_SIZE} bytes)\n"
            f"  found    sha256 {digest} ({target.stat().st_size} bytes)\n"
            "  delete the file and run again, or update the pin deliberately")
    return target


def ensure_mac_runtime(vendor_python: pathlib.Path, download: bool) -> pathlib.Path:
    """The pinned macOS runtime, fetched once from GitHub when allowed; a file
    that does not hash to the pin is refused, never replaced."""
    target = vendor_python / MAC_RUNTIME_NAME
    if not target.exists():
        if not download:
            raise SystemExit(f"{target} is missing — fetch {MAC_RUNTIME_URL} into "
                             f"{vendor_python} (sha256 {MAC_RUNTIME_SHA256})")
        import urllib.request
        vendor_python.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        print(f"fetching {MAC_RUNTIME_URL} ...")
        with urllib.request.urlopen(MAC_RUNTIME_URL, timeout=300) as r, tmp.open("wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(target)
    digest = _sha256(target)
    if digest != MAC_RUNTIME_SHA256 or target.stat().st_size != MAC_RUNTIME_SIZE:
        raise SystemExit(
            f"refusing to build: {target.name} does not match the pinned macOS runtime\n"
            f"  expected sha256 {MAC_RUNTIME_SHA256} ({MAC_RUNTIME_SIZE} bytes)\n"
            f"  found    sha256 {digest} ({target.stat().st_size} bytes)")
    return target


def _lock_pins(name: str) -> dict[str, str]:
    pins = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            k, v = line.split("==", 1)
            pins[re.sub(r"[-_.]+", "-", k).lower()] = v.strip()
    return pins


def assert_mac_wheels(wheels: list[pathlib.Path]) -> None:
    """Every pin of requirements-lock-mac.txt has exactly one wheel that runs
    on macOS arm64 with CPython 3.12 — and nothing built for Windows."""
    have: dict[str, list[pathlib.Path]] = {}
    for w in wheels:
        parts = w.name[:-4].split("-")
        have.setdefault(re.sub(r"[-_.]+", "-", parts[0]).lower(), []).append(w)
        tag = parts[-1]
        if "win" in tag:
            raise SystemExit(f"refusing to build: {w.name} is a Windows wheel")
        if tag != "any" and not ("arm64" in tag or "universal2" in tag):
            raise SystemExit(f"refusing to build: {w.name} is not for Apple Silicon")
    for pkg, ver in _lock_pins("requirements-lock-mac.txt").items():
        got = [w for w in have.get(pkg, []) if w.name.split("-")[1] == ver]
        if len(got) != 1:
            raise SystemExit(f"refusing to build: {pkg}=={ver} has {len(got)} macOS wheel(s) "
                             f"in vendor/wheels-mac (expected exactly one)")


def _zip_add(z: zipfile.ZipFile, src: pathlib.Path, arc: str, executable: bool) -> None:
    """Add a file with Unix permissions recorded, so Archive Utility on a Mac
    restores the executable bit of a ``.command`` whatever system zipped it."""
    info = zipfile.ZipInfo(arc, date_time=_dt.datetime.fromtimestamp(
        src.stat().st_mtime).timetuple()[:6])
    info.create_system = 3
    info.external_attr = ((0o100755 if executable else 0o100644) & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, src.read_bytes(), compresslevel=6)


def build_mac(args) -> int:
    files = collect()
    assert_complete(files, REQUIRED_MAC)
    assert_clean(files)
    if PUBLIC:
        assert_public(files)
    assert_versions_agree()
    if _lock_pins("requirements-lock-mac.txt") != _lock_pins("requirements-lock-win.txt"):
        raise SystemExit("refusing to build: requirements-lock-mac.txt and "
                         "requirements-lock-win.txt pin different versions")
    wdir = pathlib.Path(args.wheels) if args.wheels != "vendor/wheels" else ROOT / "vendor" / "wheels-mac"
    if not wdir.is_absolute():
        wdir = ROOT / wdir
    wheels = sorted(wdir.glob("*.whl")) if wdir.is_dir() else []
    if not wheels:
        raise SystemExit(f"no wheels in {wdir} — download them with\n  pip download "
                         "--platform macosx_11_0_arm64 --platform macosx_11_0_universal2 "
                         "--python-version 3.12 --implementation cp --only-binary=:all: "
                         f"--no-deps -r requirements-lock-mac.txt -d {wdir}")
    assert_mac_wheels(wheels)
    runtime = ensure_mac_runtime(ROOT / "vendor" / "python-mac", download=not args.no_download)

    out_dir = pathlib.Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    label = f"-{args.label}" if args.label else ""
    zip_path = out_dir / f"ner-analyzer-{VERSION}{label}-macos-arm64.zip"
    if zip_path.exists():
        zip_path.unlink()
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    manifest: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            _zip_add(z, f, f"ner-analyzer/{rel}", f.suffix in MAC_EXECUTABLE_SUFFIXES)
            manifest.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()[:16]}  {rel}")
        for w in wheels:
            _zip_add(z, w, f"ner-analyzer/vendor/wheels/{w.name}", False)
        _zip_add(z, runtime, f"ner-analyzer/vendor/python/{runtime.name}", False)
        z.writestr("ner-analyzer/data/.keep",
                   "The database and uploads live here. Created on first run.\n")
        z.writestr("ner-analyzer/PACKAGE.txt",
                   f"NER Spatial Coverage Analyzer {VERSION} for macOS (Apple Silicon)\n"
                   f"built {stamp}\n"
                   f"{len(files)} files, {len(wheels)} bundled Python packages (offline install)\n"
                   f"Python runtime bundled ({MAC_RUNTIME_NAME}, sha256 {MAC_RUNTIME_SHA256})\n"
                   f"no database, no uploads, no accounts\n"
                   f"(c) 2026 Marcelo Barbosa. Created by Marcelo Barbosa. Free software under the GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.\n"
                   f"{'public edition: no private reference material' if PUBLIC else 'team edition: carries the private reference material it was built with'}\n")
        z.writestr("ner-analyzer/MANIFEST.txt",
                   "\n".join(manifest) + f"\n\n{len(files)} files, "
                   f"{len(wheels)} bundled packages\n")
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (zip_path.with_suffix(".zip.sha256")).write_text(f"{sha}  {zip_path.name}\n",
                                                     encoding="utf-8")
    print(f"{zip_path}")
    print(f"  version {VERSION} · macOS arm64 · {len(files)} source files · {len(wheels)} "
          f"bundled packages · {zip_path.stat().st_size / 1e6:.1f} MB")
    print(f"  runtime {MAC_RUNTIME_NAME}")
    print(f"  sha256 {sha}")
    return 0


def assert_versions_agree() -> None:
    """The bundle and the manuals must carry the version being packaged."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", VERSION):
        raise SystemExit(f"VERSION reads {VERSION!r} — expected MAJOR.MINOR.PATCH")
    assets = ROOT / "backend" / "app" / "static" / "assets"
    bundles = list(assets.glob("index-*.js"))
    if not any(f'"{VERSION}"' in b.read_text(encoding="utf-8", errors="ignore") for b in bundles):
        raise SystemExit(f"the compiled interface does not carry {VERSION}: "
                         "run  cd frontend && npm run build")
    for name in ("MANUAL.html", "INSTALL.html", "QUICK-INSTALL.html"):
        if VERSION not in (ROOT / "docs" / name).read_text(encoding="utf-8"):
            raise SystemExit(f"docs/{name} does not mention {VERSION}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="dist", help="where to write the package")
    ap.add_argument("--wheels", default="vendor/wheels",
                    help="directory of .whl files to bundle for an offline install")
    ap.add_argument("--label", default="", help="extra label for the file name, e.g. test")
    ap.add_argument("--allow-online", action="store_true",
                    help="build even when no wheels are bundled (the target "
                         "machine will then need internet to install)")
    ap.add_argument("--without-python", action="store_true",
                    help="do not bundle the Python runtime (the target machine "
                         "will then need Python 3.12 installed)")
    ap.add_argument("--no-download", action="store_true",
                    help="never fetch the runtime; fail if vendor/python lacks it")
    ap.add_argument("--platform", choices=("windows", "mac"), default="windows",
                    help="windows (default) or mac — Apple Silicon (3.0.0)")
    ap.add_argument("--public", action="store_true",
                    help="the edition that may be published (4.3.0): no private "
                         "reference material, no event or venue names")
    args = ap.parse_args()
    if args.public:
        global PUBLIC
        PUBLIC = True
        if not args.label:
            args.label = "public"
    if args.platform == "mac":
        return build_mac(args)

    files = collect()
    assert_complete(files)
    assert_clean(files)
    if PUBLIC:
        assert_public(files)
    assert_versions_agree()

    wdir = ROOT / args.wheels if not pathlib.Path(args.wheels).is_absolute() \
        else pathlib.Path(args.wheels)
    wheels = sorted(wdir.glob("*.whl")) if wdir.is_dir() else []
    if not wheels and not args.allow_online:
        raise SystemExit(f"no wheels in {wdir} — run build_package.bat (it downloads "
                         "them), or pass --allow-online for a package that installs "
                         "from the internet")
    if wheels and not any(w.name.startswith("pip-") for w in wheels):
        raise SystemExit("refusing to build: vendor/wheels has no pip wheel, and "
                         "install.bat bootstraps pip from it (pip is pinned in "
                         "requirements-lock-win.txt)")
    if wheels and not any(w.name.startswith("numpy-") for w in wheels):
        raise SystemExit("refusing to build: numpy is missing from vendor/wheels "
                         "(install.bat takes its msvcp140.dll from numpy when the "
                         "target machine lacks the Visual C++ runtime)")

    runtime = None
    if not args.without_python:
        runtime = ensure_runtime(ROOT / "vendor" / "python", download=not args.no_download)

    out_dir = pathlib.Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    label = f"-{args.label}" if args.label else ""
    zip_path = out_dir / f"ner-analyzer-{VERSION}{label}-windows.zip"
    if zip_path.exists():
        zip_path.unlink()

    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    manifest: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            z.write(f, f"ner-analyzer/{rel}")
            digest = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
            manifest.append(f"{digest}  {rel}")
        for w in wheels:
            z.write(w, f"ner-analyzer/vendor/wheels/{w.name}")
        if runtime is not None:
            z.write(runtime, f"ner-analyzer/vendor/python/{runtime.name}")
        # The data directory has to exist on the target, and empty directories
        # do not survive a zip. A placeholder creates it on extraction.
        z.writestr("ner-analyzer/data/.keep",
                   "The database and uploads live here. Created on first run.\n")
        runtime_line = (f"Python {EMBED_VERSION} runtime bundled ({EMBED_NAME}, "
                        f"sha256 {EMBED_SHA256})" if runtime is not None
                        else "no Python runtime bundled: the target needs Python 3.12")
        z.writestr("ner-analyzer/PACKAGE.txt",
                   f"NER Spatial Coverage Analyzer {VERSION}\n"
                   f"built {stamp}\n"
                   f"{len(files)} files, {len(wheels)} bundled Python packages"
                   f"{' (offline install)' if wheels else ' (online install)'}\n"
                   f"{runtime_line}\n"
                   f"no database, no uploads, no accounts, no virtual environment\n"
                   f"(c) 2026 Marcelo Barbosa. Created by Marcelo Barbosa. Free software under the GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.\n"
                   f"{'public edition: no private reference material' if PUBLIC else 'team edition: carries the private reference material it was built with'}\n")
        z.writestr("ner-analyzer/MANIFEST.txt",
                   "\n".join(manifest) + f"\n\n{len(files)} files, "
                   f"{len(wheels)} bundled packages\n")

    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (zip_path.with_suffix(".zip.sha256")).write_text(f"{sha}  {zip_path.name}\n",
                                                     encoding="utf-8")
    size = zip_path.stat().st_size
    print(f"{zip_path}")
    print(f"  version {VERSION} · {len(files)} source files · {len(wheels)} bundled "
          f"packages · {size / 1e6:.1f} MB")
    print(f"  runtime {'Python ' + EMBED_VERSION + ' embedded' if runtime else 'NOT bundled'}")
    print(f"  sha256 {sha}")
    print("  no database, no uploads, no accounts, no virtual environment")
    return 0


if __name__ == "__main__":
    sys.exit(main())
