"""2.16.1 — three defects found the day the application moved to another computer.

2 Oct 2026. The development checkout was copied to a second laptop, the
installation there was updated without administrator rights, and the projects
were carried into it with ``backup.bat`` / ``--restore``. Three things went
wrong, each of them silently:

1. ``autostart.bat`` made the sign-in task with ``schtasks /sc onlogon``, a
   trigger for *every* user of the computer, which only an administrator may
   create. Without the rights: "Access is denied" — and the script stopped
   there, so the watchdog was not installed either. ``setup-noadmin.bat``
   (2.16.0) therefore installed an application that nothing started.
2. The database records each uploaded file by its full path. Restored into
   another folder it went on naming the folder it came from — and, that folder
   still being on the disk, went on *reading* it.
3. The backup did not carry ``data\\criticality-matrix.xlsx``.

The batch and PowerShell files are held to their contract by reading them, as
``test_installer.py`` does; the real run is the installation test on Windows.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="ner-2161-")
os.environ.setdefault("NER_DATA_DIR", TMP)
os.environ.setdefault("NER_DATABASE_URL", f"sqlite:///{TMP}/t2161.sqlite3")

from sqlalchemy import select                                      # noqa: E402

from app import migrate                                            # noqa: E402
from app.config import settings                                    # noqa: E402
from app.db import SessionLocal, init_db                           # noqa: E402
from app.models import AuditLog, Drawing, Project, TeapFile        # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _bat_code(rel: str) -> str:
    return "\n".join(l for l in _read(rel).splitlines()
                     if not l.strip().upper().startswith("REM"))


def _ps_code(rel: str) -> str:
    return "\n".join(l for l in _read(rel).splitlines() if not l.strip().startswith("#"))


# --- 1. the sign-in task, without administrator rights ------------------------

def test_the_sign_in_task_is_no_longer_made_for_every_user():
    code = _bat_code("autostart.bat")
    assert "onlogon" not in code.lower(), \
        "a trigger for every user is refused without administrator rights"
    assert "schtasks /create" not in code.lower(), "both tasks are made by their scripts"
    call = [l for l in code.splitlines() if "signin-task.ps1" in l]
    assert len(call) == 1
    assert '-Name "%TASKNAME%"' in call[0]
    assert '-Pythonw "%PYW%"' in call[0]
    assert '-Script "%~dp0tools\\serve.py"' in call[0]


def test_the_sign_in_task_is_written_for_the_person_signed_in():
    ps = _ps_code("tools/signin-task.ps1")
    assert "<LogonTrigger>" in ps
    # The same account in the trigger and as the one the task runs as — by
    # SID, which resolves where a cloud-directory name may not.
    assert "WindowsIdentity]::GetCurrent().User.Value" in ps
    assert ps.count("<UserId>$sid</UserId>") == 2
    assert "<RunLevel>LeastPrivilege</RunLevel>" in ps
    assert "<LogonType>InteractiveToken</LogonType>" in ps
    # Registered the way a managed machine allows, and never left with the
    # scheduler's battery and 72-hour defaults.
    assert "schtasks.exe /Create /TN $Name /XML" in ps
    assert "Register-ScheduledTask" not in ps
    for setting, value in (("DisallowStartIfOnBatteries", "false"),
                           ("StopIfGoingOnBatteries", "false"),
                           ("ExecutionTimeLimit", "PT0S"),
                           ("MultipleInstancesPolicy", "IgnoreNew")):
        assert f"<{setting}>{value}</{setting}>" in ps
    # A path with an ampersand or an apostrophe must not break the XML.
    assert "SecurityElement]::Escape" in ps
    assert "exit $code" in ps, "a refusal reaches autostart.bat as a failure"


def test_the_watchdog_is_installed_even_when_the_sign_in_task_is_refused():
    """The defect was two: the refusal, and stopping at it."""
    code = _bat_code("autostart.bat")
    signin = code.index("signin-task.ps1")
    watchdog = code.index("watchdog-install.ps1")
    assert signin < watchdog
    between = code[signin:watchdog]
    assert "exit /b" not in between, "nothing may leave before the watchdog is installed"
    assert "if errorlevel 1 set SIGNIN=" in between
    # Without the sign-in task the watchdog alone starts the server, and that
    # is a working installation: setup.bat must not be told it failed.
    tail = code[watchdog:]
    alone = tail[tail.index("if not defined SIGNIN ("):]
    assert "exit /b 0" in alone[:alone.index("\n)")]
    # Only the task that exists is hardened.
    assert 'if defined SIGNIN powershell' in tail and 'task-harden.ps1" -Name "%TASKNAME%"' in tail


def test_the_package_cannot_be_built_without_the_task_scripts():
    packager = _read("tools/make_package.py")
    assert '"signin-task.ps1"' in packager
    required = packager[packager.index("REQUIRED = ("):packager.index("def wanted")]
    assert '"tools/signin-task.ps1"' in required
    assert '"tools/watchdog-install.ps1"' in required


def test_autostart_keeps_its_windows_line_endings():
    raw = (ROOT / "autostart.bat").read_bytes()
    assert b"\r\n" in raw and not __import__("re").findall(rb"(?<!\r)\n", raw)


# --- 2. the uploaded files' records follow the installation -------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def db_ready():
    init_db()
    return True


def _project(db, name: str) -> Project:
    p = Project(name=name, venue_code="TST")
    db.add(p)
    db.commit()
    return p


def _here(project_id: int, name: str, data: bytes) -> Path:
    d = settings.uploads_dir / f"project_{project_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    return d / name


def test_the_part_below_uploads_is_read_from_either_kind_of_path():
    assert migrate._upload_tail(
        r"E:\Work\Other-Laptop\NER_Build\ner-analyzer\data\uploads\project_1\A b.pdf"
    ) == ("project_1", "A b.pdf")
    assert migrate._upload_tail("/srv/ner/data/uploads/project_7/t.xlsx") == ("project_7", "t.xlsx")
    assert migrate._upload_tail("/tmp/sample.pdf") is None
    assert migrate._upload_tail(r"C:\x\uploads\..\secret.txt") is None
    assert migrate._upload_tail("") is None


def test_a_restored_database_points_at_this_installation(db_ready):
    book, sheet = b"%PDF-1.7 the book", b"PK the workbook"
    with SessionLocal() as db:
        p = _project(db, "carried-2161")
        gone = rf"E:\Work\Other-Laptop\NER_Build\ner-analyzer\data\uploads\project_{p.id}"
        d = Drawing(project_id=p.id, filename="VHH_400.pdf", stored_path=gone + r"\VHH_400.pdf",
                    sha256=_sha(book), page_count=1)
        t = TeapFile(project_id=p.id, filename="TEAP v2.3.xlsx",
                     stored_path=gone + r"\TEAP v2.3.xlsx", sha256=_sha(sheet))
        db.add_all([d, t])
        db.commit()
        here_d = _here(p.id, "VHH_400.pdf", book)
        here_t = _here(p.id, "TEAP v2.3.xlsx", sheet)

        report = migrate.rebase_stored_paths(db)
        assert report["upload_paths_rebased"] == 2
        db.refresh(d)
        db.refresh(t)
        assert Path(d.stored_path) == here_d and Path(t.stored_path) == here_t
        # Written down, with where it was.
        rows = db.execute(select(AuditLog).where(
            AuditLog.project_id == p.id, AuditLog.action == "upload.path_rebased")).scalars().all()
        assert {r.entity for r in rows} == {"drawing", "teap_file"}
        assert all(r.actor == "system" and r.payload["from"].startswith("E:\\Work\\Other-Laptop")
                   for r in rows)
        # And only once.
        again = migrate.rebase_stored_paths(db)
        assert again["upload_paths_rebased"] == 0
        assert len(db.execute(select(AuditLog).where(
            AuditLog.project_id == p.id,
            AuditLog.action == "upload.path_rebased")).scalars().all()) == 2


def test_the_other_folder_still_being_there_changes_nothing(db_ready, tmp_path):
    """2 Oct 2026: the folder the backup came from was still on the disk, so
    every file "existed" and the installation went on reading somebody else's."""
    book = b"%PDF-1.7 the same book in two places"
    with SessionLocal() as db:
        p = _project(db, "two-places-2161")
        other = tmp_path / "checkout" / "data" / "uploads" / f"project_{p.id}"
        other.mkdir(parents=True)
        (other / "book.pdf").write_bytes(book)
        d = Drawing(project_id=p.id, filename="book.pdf", stored_path=str(other / "book.pdf"),
                    sha256=_sha(book), page_count=1)
        db.add(d)
        db.commit()
        here = _here(p.id, "book.pdf", book)
        assert Path(d.stored_path).exists(), "the old place answers, which is what hid the defect"

        migrate.rebase_stored_paths(db)
        db.refresh(d)
        assert Path(d.stored_path) == here


def test_a_record_is_never_pointed_at_a_different_file_or_at_nothing(db_ready):
    with SessionLocal() as db:
        p = _project(db, "careful-2161")
        gone = rf"D:\old\data\uploads\project_{p.id}"
        other = Drawing(project_id=p.id, filename="same-name.pdf",
                        stored_path=gone + r"\same-name.pdf", sha256=_sha(b"the recorded book"),
                        page_count=1)
        absent = Drawing(project_id=p.id, filename="not-here.pdf",
                         stored_path=gone + r"\not-here.pdf", sha256=_sha(b"x"), page_count=1)
        db.add_all([other, absent])
        db.commit()
        _here(p.id, "same-name.pdf", b"another book that happens to share the name")

        report = migrate.rebase_stored_paths(db)
        db.refresh(other)
        db.refresh(absent)
        assert other.stored_path == gone + r"\same-name.pdf"
        assert absent.stored_path == gone + r"\not-here.pdf"
        assert report["upload_paths_different_file"] >= 1
        assert report["upload_paths_not_here"] >= 1


def test_the_pass_runs_at_every_start_before_the_books_are_read(db_ready):
    report = init_db()
    assert "uploads" in report and "upload_paths_rebased" in report["uploads"]
    src = _read("backend/app/migrate.py")
    run = src[src.index("def run(engine"):]
    assert run.index("rebase_stored_paths(db)") < run.index("backfill_assets(db, project)")


# --- 3. the backup carries the criticality matrix ------------------------------

def _backup_module(data: Path):
    spec = importlib.util.spec_from_file_location("ner_backup_2161", ROOT / "tools" / "backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DATA = data
    mod.DB = data / "ner.sqlite3"
    mod.UPLOADS = data / "uploads"
    mod.MATRIX = data / "criticality-matrix.xlsx"
    mod._server_answering = lambda: False
    return mod


def _installation(data: Path, *, matrix: bytes | None) -> None:
    (data / "uploads" / "project_1").mkdir(parents=True)
    (data / "uploads" / "project_1" / "book.pdf").write_bytes(b"%PDF book")
    con = sqlite3.connect(data / "ner.sqlite3")
    con.execute("create table t (x)")
    con.execute("insert into t values ('carried')")
    con.commit()
    con.close()
    if matrix is not None:
        (data / "criticality-matrix.xlsx").write_bytes(matrix)


def test_a_backup_carries_the_matrix_and_a_restore_puts_it_back(tmp_path, capsys):
    source = tmp_path / "source-data"
    _installation(source, matrix=b"PK the matrix")
    dest = _backup_module(source).backup(tmp_path / "stick")
    assert (dest / "criticality-matrix.xlsx").read_bytes() == b"PK the matrix"
    assert "criticality matrix included" in (dest / "BACKUP.txt").read_text(encoding="utf-8")

    target = tmp_path / "new-data"
    target.mkdir()
    _backup_module(target).restore(dest)
    assert (target / "criticality-matrix.xlsx").read_bytes() == b"PK the matrix"
    assert (target / "uploads" / "project_1" / "book.pdf").exists()
    assert sqlite3.connect(target / "ner.sqlite3").execute("select x from t").fetchone() == ("carried",)
    # A restore into a new installation replaces nothing, and says so by
    # leaving no empty folder behind.
    assert not list(target.glob("replaced-*"))
    out = capsys.readouterr().out
    assert "criticality matrix" in out and "points the uploaded files' records" in out


def test_a_backup_without_a_matrix_leaves_the_installation_s_own(tmp_path):
    source = tmp_path / "source-data"
    _installation(source, matrix=None)
    dest = _backup_module(source).backup(tmp_path / "stick")
    assert not (dest / "criticality-matrix.xlsx").exists()
    assert "no criticality matrix" in (dest / "BACKUP.txt").read_text(encoding="utf-8")

    target = tmp_path / "used-data"
    _installation(target, matrix=b"PK this installation's matrix")
    _backup_module(target).restore(dest)
    assert (target / "criticality-matrix.xlsx").read_bytes() == b"PK this installation's matrix"
    # What was replaced — the database and the uploads — is kept, not deleted.
    kept = list(target.glob("replaced-*"))
    assert len(kept) == 1
    assert (kept[0] / "ner.sqlite3").exists() and (kept[0] / "uploads").is_dir()
    assert not (kept[0] / "criticality-matrix.xlsx").exists()


def test_a_restore_replaces_the_matrix_only_with_the_backup_s(tmp_path):
    source = tmp_path / "source-data"
    _installation(source, matrix=b"PK the newer matrix")
    dest = _backup_module(source).backup(tmp_path / "stick")
    target = tmp_path / "used-data"
    _installation(target, matrix=b"PK the older matrix")
    _backup_module(target).restore(dest)
    assert (target / "criticality-matrix.xlsx").read_bytes() == b"PK the newer matrix"
    kept = list(target.glob("replaced-*"))[0]
    assert (kept / "criticality-matrix.xlsx").read_bytes() == b"PK the older matrix"


# --- the documents say so ------------------------------------------------------

def test_the_installation_manual_describes_the_three():
    text = _read("docs/INSTALL.html")
    backup = text[text.index('<section id="backup">'):text.index('<section id="migrar">')]
    assert "criticality-matrix.xlsx" in backup
    carry = text[text.index('<section id="migrar">'):text.index('<section id="atualizar">')]
    assert "points" in carry and "data\\uploads" in carry
    auto = text[text.index('<section id="autostart">'):text.index('<section id="conferir">')]
    assert "administrator" in auto and "watchdog" in auto
    assert "onlogon" not in text.lower()
