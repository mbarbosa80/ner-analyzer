"""Background job runner.

Ingesting a 34-page venue design book takes about thirty seconds; matching
thousands of spaces and solving the placement model can take minutes. Running any
of that inside an HTTP handler blocks the event loop — the health endpoint on the
reference machine went from 20 ms to 3 s while an oversized optimisation ground
away — and leaves the user with no progress, no estimate, and no way out except
killing the process.

This module is deliberately small: a thread pool, a row per job, a progress
callback and a cancellation flag. It is not a distributed queue, because this is a
single-user desktop tool and a queue would need a broker the user would have to
install and keep running.

A job function receives a :class:`JobContext` and must call ``ctx.progress(...)``
regularly — that is both how the UI learns what is happening and how cancellation
takes effect, since ``progress`` raises :class:`JobCancelled` once the flag is set.
"""

from __future__ import annotations

import datetime as _dt
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Job

#: Two workers: enough to let a user start an analysis while a drawing is still
#: being read, without letting a mistaken double-click start four heavy solves.
MAX_WORKERS = 2


class JobCancelled(Exception):
    """Raised inside a job when the user asks for it to stop."""


@dataclass
class JobContext:
    """Handed to the job function. Carries progress reporting and cancellation."""

    job_id: str
    _cancel: threading.Event
    _db: Session
    _last_pct: int = field(default=-1, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def progress(self, fraction: float, stage: str = "") -> None:
        """Record progress and stop the job if cancellation was requested.

        Writes are throttled to whole percentage points so a tight loop calling
        this thousands of times does not turn into thousands of UPDATEs.
        """
        if self._cancel.is_set():
            raise JobCancelled()
        pct = int(max(0.0, min(1.0, fraction)) * 100)
        if pct == self._last_pct and not stage:
            return
        self._last_pct = pct
        row = self._db.get(Job, self.job_id)
        if row is not None:
            row.progress = pct / 100.0
            if stage:
                row.stage = stage[:300]
            self._db.commit()

    def check(self) -> None:
        """Cancellation checkpoint for loops that have no useful progress figure."""
        if self._cancel.is_set():
            raise JobCancelled()


class JobManager:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="ner-job")
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------------
    def submit(self, *, kind: str, project_id: Optional[int],
               fn: Callable[[JobContext, Session], Any],
               db: Session) -> str:
        job_id = uuid.uuid4().hex
        db.add(Job(id=job_id, project_id=project_id, kind=kind, state="pending",
                   stage="queued"))
        db.commit()

        cancel = threading.Event()
        with self._lock:
            self._cancels[job_id] = cancel

        # The job runs in the context of the request that started it (4.2.0),
        # so its audit entries name the person who pressed the button.
        import contextvars
        self._pool.submit(contextvars.copy_context().run, self._run, job_id, kind, fn, cancel)
        return job_id

    def _run(self, job_id: str, kind: str,
             fn: Callable[[JobContext, Session], Any],
             cancel: threading.Event) -> None:
        """Executed on a worker thread with its own database session."""
        db = SessionLocal()
        try:
            row = db.get(Job, job_id)
            if row is None:
                return
            if cancel.is_set():
                row.state, row.stage = "cancelled", "cancelled before it started"
                row.finished_at = _dt.datetime.now(_dt.timezone.utc)
                db.commit()
                return
            row.state = "running"
            row.started_at = _dt.datetime.now(_dt.timezone.utc)
            row.stage = "starting"
            db.commit()

            ctx = JobContext(job_id=job_id, _cancel=cancel, _db=db)
            try:
                result = fn(ctx, db)
            except JobCancelled:
                db.rollback()
                row = db.get(Job, job_id)
                row.state, row.stage = "cancelled", "cancelled by the user"
                row.progress = 0.0
                row.finished_at = _dt.datetime.now(_dt.timezone.utc)
                db.commit()
                return
            except Exception as exc:                       # noqa: BLE001
                db.rollback()
                row = db.get(Job, job_id)
                row.state = "error"
                row.error = f"{type(exc).__name__}: {exc}"
                row.stage = "failed"
                row.result = {"traceback": traceback.format_exc()[-4000:]}
                row.finished_at = _dt.datetime.now(_dt.timezone.utc)
                db.commit()
                return

            row = db.get(Job, job_id)
            row.state = "done"
            row.progress = 1.0
            row.stage = "finished"
            row.result = result if isinstance(result, dict) else {"value": result}
            row.finished_at = _dt.datetime.now(_dt.timezone.utc)
            db.commit()
        finally:
            db.close()
            with self._lock:
                self._cancels.pop(job_id, None)

    # -- control ------------------------------------------------------------
    def cancel(self, job_id: str) -> bool:
        with self._lock:
            ev = self._cancels.get(job_id)
        if ev is None:
            return False
        ev.set()
        return True

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancels


manager = JobManager()


def job_to_dict(row: Job) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "state": row.state,
        "progress": round(row.progress, 3),
        "stage": row.stage,
        "result": row.result,
        "error": row.error,
        "project_id": row.project_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "running": row.state in ("pending", "running"),
    }
