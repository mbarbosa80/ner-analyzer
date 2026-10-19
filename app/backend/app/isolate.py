"""Run one heavy, self-contained function in a child interpreter (2.17.0).

Why
---
Reading a venue design book — PyMuPDF over 20–90 MB of vector sheets, the
stroke walk of every page for the NER block symbols — leaves the server
process a few hundred megabytes heavier each time, and that memory never
goes back to Windows: the Python heap and the MuPDF store keep it. After a
day of books the server was 650 MB and, on a laptop with little free RAM,
paged out; the next upload then ran at 8–17 s/page instead of 1.5 (8 Oct
2026, the work laptop, eight projects). A child interpreter that reads the
book and exits gives every byte back when it does.

How
---
:func:`run` starts ``sys.executable -c <bootstrap>``, hands it the parent's
``sys.path`` (the embedded runtime ignores PYTHONPATH — its ``._pth`` file is
the whole search path, so the path travels in the request), the dotted name
of the function, its arguments, and reads back length-prefixed pickles:
``('progress', fraction, stage)`` as the function reports it, then
``('done', result)`` or ``('error', type, message, traceback)``. The
parent's ``progress`` callback is called for each progress frame, exactly as
the function would have called it in-process — and may raise, which is how a
job is cancelled: the child is killed and the exception propagates.

What qualifies: a function whose arguments and result pickle (plain data
and dataclasses of plain data) and that touches no database session —
``extract_drawing`` and ``read_drawn_rooms`` do; the report builder, which
reads the register through SQLAlchemy, does not and stays in-process.

If the child cannot be started at all (no interpreter, a locked-down
runtime) the function runs in-process, as before, and a warning is logged:
slower is better than broken. ``NER_INPROCESS=1`` forces that path — for a
debugger, or to compare.
"""

from __future__ import annotations

import importlib
import logging
import os
import pickle
import struct
import subprocess
import sys
import threading
from typing import Any, Callable, Optional

log = logging.getLogger("ner.isolate")

Progress = Optional[Callable[[float, str], None]]

#: Printed in the server log when the fallback is taken, once per process.
_fallback_announced = False

# The child. Kept free of anything but the standard library until the
# request arrives, because the request is what carries the import path.
_BOOTSTRAP = r"""
import importlib, pickle, struct, sys, traceback
_in, _out = sys.stdin.buffer, sys.stdout.buffer
def _send(obj):
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    _out.write(struct.pack('>I', len(data))); _out.write(data); _out.flush()
try:
    n = struct.unpack('>I', _in.read(4))[0]
    req = pickle.loads(_in.read(n))
    sys.path[:0] = [p for p in req['sys_path'] if p not in sys.path]
    sys.stdout = sys.stderr          # a stray print must not corrupt a frame
    mod, _, name = req['target'].rpartition('.')
    fn = getattr(importlib.import_module(mod), name)
    kwargs = dict(req['kwargs'])
    if req['progress']:
        kwargs['progress'] = lambda frac, stage='': _send(('progress', float(frac), str(stage)))
    _send(('done', fn(*req['args'], **kwargs)))
except BaseException as exc:
    _send(('error', type(exc).__name__, str(exc), traceback.format_exc()))
"""


class IsolatedError(RuntimeError):
    """The function failed in the child. ``kind`` is the child's exception
    type name; ``trace`` its traceback, for the job row."""

    def __init__(self, kind: str, message: str, trace: str = "") -> None:
        super().__init__(f"{kind}: {message}" if kind else message)
        self.kind = kind
        self.trace = trace


def _resolve(target: str) -> Callable[..., Any]:
    mod, _, name = target.rpartition(".")
    return getattr(importlib.import_module(mod), name)


def _in_process(target: str, args: tuple, kwargs: dict, progress: Progress) -> Any:
    fn = _resolve(target)
    if progress is not None:
        kwargs = dict(kwargs, progress=progress)
    return fn(*args, **kwargs)


def _read_frame(stream) -> Optional[Any]:
    head = stream.read(4)
    if len(head) < 4:
        return None
    (n,) = struct.unpack(">I", head)
    body = stream.read(n)
    if len(body) < n:
        return None
    return pickle.loads(body)


def _drain(stream, into: list) -> None:
    try:
        into.append(stream.read())
    except Exception:                                   # noqa: BLE001 — the pipe went away
        pass


def run(target: str, *args: Any, progress: Progress = None, **kwargs: Any) -> Any:
    """Call ``target`` (a dotted ``module.function`` name) with ``args`` and
    ``kwargs`` in a child interpreter and return its result.

    ``progress`` receives every ``(fraction, stage)`` the function reports.
    Raising from it stops the child and propagates — that is cancellation.
    A failure inside the function raises :class:`IsolatedError`.
    """
    global _fallback_announced
    if os.environ.get("NER_INPROCESS") == "1":
        return _in_process(target, args, kwargs, progress)

    request = pickle.dumps({
        "sys_path": list(sys.path), "target": target, "args": args, "kwargs": kwargs,
        "progress": progress is not None,
    }, protocol=pickle.HIGHEST_PROTOCOL)

    creation = 0
    if sys.platform == "win32":
        # No console flash when the parent is a python.exe with a window.
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _BOOTSTRAP],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=creation, cwd=os.getcwd(), env=dict(os.environ))
    except OSError as exc:
        if not _fallback_announced:
            log.warning("isolate: cannot start %s (%s) — running %s in-process",
                        sys.executable, exc, target)
            _fallback_announced = True
        return _in_process(target, args, kwargs, progress)

    err_chunks: list[bytes] = []
    err_thread = threading.Thread(target=_drain, args=(proc.stderr, err_chunks),
                                  name="ner-isolate-stderr", daemon=True)
    err_thread.start()
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(struct.pack(">I", len(request)))
        proc.stdin.write(request)
        proc.stdin.flush()
        proc.stdin.close()
        while True:
            frame = _read_frame(proc.stdout)
            if frame is None:
                proc.wait(timeout=10)
                err_thread.join(timeout=5)
                tail = b"".join(err_chunks).decode("utf-8", "replace").strip()[-2000:]
                raise IsolatedError(
                    "ChildExit",
                    f"the reader process ended without a result (exit code {proc.returncode})"
                    + (f": {tail}" if tail else ""))
            kind = frame[0]
            if kind == "progress":
                if progress is not None:
                    progress(frame[1], frame[2])        # may raise: cancellation
            elif kind == "done":
                return frame[1]
            elif kind == "error":
                raise IsolatedError(frame[1], frame[2], frame[3])
            else:                                       # pragma: no cover
                raise IsolatedError("Protocol", f"unexpected frame {kind!r}")
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:                               # noqa: BLE001
            pass
        for s in (proc.stdout, proc.stdin):
            try:
                if s is not None:
                    s.close()
            except Exception:                           # noqa: BLE001
                pass
        err_thread.join(timeout=2)
