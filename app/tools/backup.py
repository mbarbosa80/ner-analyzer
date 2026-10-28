"""Back up — or restore — everything the application knows.

    backup.bat                                   # data\\backup-YYYYMMDD-HHMMSS\\
    backup.bat --to D:\\NER-backups
    backup.bat --restore data\\backup-20260910-101500

(backup.bat runs this file on the installation's own Python: .python\\python.exe
of a package, or .venv\\Scripts\\python.exe of a development checkout.)

A backup is the database, the uploaded documents and, where one was loaded,
the installation's criticality matrix.

The database is copied through SQLite's own backup API rather than by copying
the file. The application keeps the database in WAL mode, which means the
most recent changes live in ``ner.sqlite3-wal`` beside the main file until a
checkpoint folds them in; a plain copy of ``ner.sqlite3`` taken while the
server is running can miss the last minutes of work and, worse, look
complete. The backup API reads the live database consistently and writes a
single self-contained file, so the copy is valid whether the server is
running or not.

The uploads folder — the drawings and workbooks exactly as they were
uploaded — is copied as it is. Without it every project opens with its
drawings missing. The database records where each uploaded file is kept; when
a backup is restored into another folder, or on another computer, the server
points those records at this installation's own ``data\\uploads`` the next
time it starts (``migrate.rebase_stored_paths``), so nothing has to be edited
by hand.

``data\\criticality-matrix.xlsx`` is one file per installation, kept beside
the uploads and outside any project. It is copied when it exists (2.16.1 —
before that a restored installation silently had none).

A restore refuses to run while the server is answering: overwriting the
database underneath a running process is how a backup becomes two corrupt
copies. Stop the server first (``stop.bat``), restore, start it again.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
import socket
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("NER_DATA_DIR", ROOT / "data"))
DB = DATA / "ner.sqlite3"
UPLOADS = DATA / "uploads"
#: One per installation, beside the uploads — see ``app/criticality.py``.
MATRIX = DATA / "criticality-matrix.xlsx"
PORT = int(os.environ.get("NER_PORT", "8000"))


def _version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _server_answering() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def backup(dest_root: Path) -> Path:
    if not DB.exists():
        raise SystemExit(f"no database at {DB} — nothing to back up")
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_root / f"backup-{stamp}"
    dest.mkdir(parents=True, exist_ok=False)

    # Consistent copy, WAL included, whether or not the server is running.
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest / "ner.sqlite3")
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    n_files = 0
    if UPLOADS.is_dir():
        shutil.copytree(UPLOADS, dest / "uploads")
        n_files = sum(1 for _ in (dest / "uploads").rglob("*") if _.is_file())

    has_matrix = MATRIX.is_file()
    if has_matrix:
        shutil.copy2(MATRIX, dest / MATRIX.name)

    size = (dest / "ner.sqlite3").stat().st_size
    matrix_line = "criticality matrix included" if has_matrix else "no criticality matrix"
    (dest / "BACKUP.txt").write_text(
        f"NER Spatial Coverage Analyzer {_version()}\n"
        f"backup taken {stamp}\n"
        f"database {size / 1e6:.1f} MB, {n_files} uploaded file(s), {matrix_line}\n"
        f"restore with:  backup.bat --restore \"{dest}\"\n"
        f"(stop the server first)\n", encoding="utf-8")
    print(f"backup written to {dest}")
    print(f"  database {size / 1e6:.1f} MB - {n_files} uploaded file(s) - {matrix_line}")
    return dest


def restore(src: Path) -> None:
    src = src.resolve()
    if not (src / "ner.sqlite3").exists():
        raise SystemExit(f"{src} holds no ner.sqlite3 — is this a backup folder?")
    if _server_answering():
        raise SystemExit(f"the server is answering on port {PORT} — stop it first "
                         f"(stop.bat), then restore")
    DATA.mkdir(parents=True, exist_ok=True)
    # Keep what is there: a restore that destroys the only other copy is a
    # restore nobody can undo. The folder is made only when there is
    # something to keep — a restore into a new installation used to leave an
    # empty ``replaced-…`` behind.
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = DATA / f"replaced-{stamp}"
    moved = 0

    def _keep(p: Path) -> None:
        nonlocal moved
        if p.exists():
            kept.mkdir(exist_ok=True)
            shutil.move(str(p), str(kept / p.name))
            moved += 1

    for name in ("ner.sqlite3", "ner.sqlite3-wal", "ner.sqlite3-shm"):
        _keep(DATA / name)
    _keep(UPLOADS)
    # The matrix of this installation is replaced only by a backup that
    # carries one: it is programme guidance, and a backup taken before 2.16.1
    # (or on an installation that never loaded one) says nothing about it.
    has_matrix = (src / MATRIX.name).is_file()
    if has_matrix:
        _keep(MATRIX)

    shutil.copy2(src / "ner.sqlite3", DB)
    if (src / "uploads").is_dir():
        shutil.copytree(src / "uploads", UPLOADS)
    if has_matrix:
        shutil.copy2(src / MATRIX.name, MATRIX)
    print(f"restored from {src}")
    if has_matrix:
        print("  with its criticality matrix")
    if moved:
        print(f"  the replaced files were kept in {kept} - delete that folder once "
              f"you are sure")
    print("  start the server: on its first start it points the uploaded files' "
          "records at this installation's folder")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", default=str(DATA),
                    help="folder that receives the backup-<stamp> directory")
    ap.add_argument("--restore", default="", metavar="FOLDER",
                    help="restore this backup folder (server must be stopped)")
    args = ap.parse_args()
    if args.restore:
        restore(Path(args.restore))
    else:
        backup(Path(args.to))
    return 0


if __name__ == "__main__":
    sys.exit(main())
