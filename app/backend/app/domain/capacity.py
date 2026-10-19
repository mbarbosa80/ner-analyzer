"""Will this machine survive the solver?

The application already refuses a model that is too large *in the abstract*
(``optimise``'s ``max_assignment_vars`` ceiling). That guard answers one
question — "is this input unreasonable?" — and it does not answer the other one:
**does this computer have room right now?**

Those come apart in practice. On 2026-08-28 a perfectly legal model was started
on a machine sitting at 97% commit charge (38.5 GB of a 39.7 GB limit, with
721 MB of physical RAM free). Windows refused the allocation and killed the
server. Nothing appeared in either log, because a process killed for memory does
not get to write a traceback. From the operator's chair the application had
simply frozen, five hours earlier, and the browser tab was talking to nothing.

So this module measures the machine rather than the model.

**Why commit charge and not free RAM.** On Windows the binding constraint is the
commit limit (RAM + page file), not physical memory. A process can be killed
with gigabytes of RAM apparently free if the commit charge is exhausted, and
that is exactly what happened. ``GlobalMemoryStatusEx`` reports both;
``ullAvailPageFile`` is the number that matters and is the one used here.

**Where the coefficient comes from.** It was measured against the configuration
this application actually uses, which is a **single-worker** solve — ``optimise``
pins ``num_search_workers = 1`` for determinism, so there is no parallel search
to shed under pressure. Building models of the shape ``optimise`` builds (three
dicts keyed by ``(i, j)`` plus the CP-SAT variables, then the constraints, then
a solve) and taking peak resident size:

     60,000 vars    103 MB
    120,000 vars    118 MB
    240,000 vars    232 MB     → ~970 B/var at the sizes that matter

A first draft of this module measured 1,661 B/var and offered to reduce the
worker count under pressure. Both were wrong: the measurement was taken at eight
workers, and the degradation path could never have fired, because the solver is
already single-threaded. The number below is the single-worker figure, rounded
up for margin.

**The policy**, therefore, is a straight yes or no — there is no middle setting
to fall back to:

* Enough room → run.
* Not enough → refuse, naming what is needed, what is free, and what to close.
  A refusal the operator can act on beats a process that vanishes.
* Cannot measure → run. A guard that blocks work because it could not take a
  reading is worse than no guard.

The estimate is deliberately conservative and openly approximate. Being wrong in
the direction of caution costs a refused run the operator can retry after
closing a browser; being wrong the other way costs the server and everything in
flight with it.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Optional

#: Peak bytes per assignment variable, single-worker. Measured; see above.
BYTES_PER_VAR = 1_100

#: Fixed overhead of the request itself — the demand and candidate lists, the
#: coverage result being compared against, the response being assembled.
BASE_OVERHEAD_BYTES = 150 * 1024 * 1024

#: Never plan to use the last of the machine. On a Windows desktop running a
#: browser and a security agent, commit headroom below about a gigabyte means
#: the machine is already one tab away from refusing an allocation — which is
#: precisely the state the server died in. A lower floor was tried first and let
#: the incident machine through with 39 MB to spare, which is inside the
#: estimate's own error bars.
SAFETY_FLOOR_BYTES = 1024 * 1024 * 1024

#: Never budget more than this share of what is free.
SAFETY_FRACTION = 0.70


class InsufficientMemory(RuntimeError):
    """Raised instead of letting the operating system kill the process."""

    def __init__(self, message: str, *, needed: int, available: int,
                 detail: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.needed = needed
        self.available = available
        self.detail = detail or []


@dataclass(frozen=True)
class MemoryStatus:
    """What the machine has left, from whichever source could answer."""

    available: int          # the binding constraint, in bytes
    total: int
    source: str
    physical_available: Optional[int] = None
    commit_available: Optional[int] = None

    @property
    def known(self) -> bool:
        return self.available > 0

    def human(self) -> str:
        return f"{self.available / 1024 ** 3:.1f} GB"


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_memory() -> Optional[MemoryStatus]:
    try:
        st = _MemoryStatusEx()
        st.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
    except Exception:
        return None
    # The commit limit is what actually refuses an allocation on Windows, so it
    # is the binding constraint even when physical RAM looks comfortable.
    binding = min(st.ullAvailPageFile, st.ullAvailVirtual)
    return MemoryStatus(
        available=int(binding),
        total=int(st.ullTotalPageFile),
        source="windows-commit",
        physical_available=int(st.ullAvailPhys),
        commit_available=int(st.ullAvailPageFile),
    )


def _linux_memory() -> Optional[MemoryStatus]:
    try:
        fields: dict[str, int] = {}
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    fields[key] = int(parts[0]) * 1024
    except Exception:
        return None
    avail = fields.get("MemAvailable")
    if avail is None:
        return None
    return MemoryStatus(available=avail, total=fields.get("MemTotal", 0),
                        source="linux-memavailable", physical_available=avail)


def memory_status() -> MemoryStatus:
    """What is free, by the measure that can actually refuse an allocation.

    Returns a status with ``known`` False when the platform cannot be measured.
    """
    st = _windows_memory() if sys.platform == "win32" else _linux_memory()
    if st is not None and st.available > 0:
        return st
    return MemoryStatus(available=0, total=0, source="unknown")


def estimate_bytes(n_vars: int) -> int:
    """Peak bytes the solve is expected to need for this many variables."""
    return BASE_OVERHEAD_BYTES + int(n_vars) * BYTES_PER_VAR


def budget(status: MemoryStatus) -> int:
    """How much of what is free this application is willing to plan on using."""
    if not status.known:
        return 0
    return max(0, int(min(status.available * SAFETY_FRACTION,
                          status.available - SAFETY_FLOOR_BYTES)))


def affordable_vars(status: Optional[MemoryStatus] = None) -> Optional[int]:
    """How many assignment variables this machine could carry right now.

    ``None`` when the machine cannot be measured.
    """
    st = status or memory_status()
    if not st.known:
        return None
    room = budget(st) - BASE_OVERHEAD_BYTES
    return max(0, room // BYTES_PER_VAR)


def check(n_vars: int, status: Optional[MemoryStatus] = None) -> list[str]:
    """Refuse the solve if this machine cannot carry it.

    Returns notes to surface to the operator (empty when there is comfortable
    room). Raises :class:`InsufficientMemory` when the model does not fit — the
    case worth refusing, because running it anyway takes the server down and
    loses whatever else was in flight.
    """
    st = status or memory_status()
    if not st.known:
        return []

    room = budget(st)
    need = estimate_bytes(n_vars)

    if need > room:
        fits = affordable_vars(st) or 0
        raise InsufficientMemory(
            "not enough memory on this computer to run the optimiser right now",
            needed=need, available=st.available,
            detail=[
                f"this run needs about {need / 1024 ** 3:.1f} GB; of the "
                f"{st.human()} this machine has free, only "
                f"{room / 1024 ** 3:.1f} GB can safely be spent — the rest is "
                f"the margin that keeps Windows from killing the server "
                f"mid-run, which is what happened on 28 August",
                f"{n_vars:,} assignment variables; there is room for about "
                f"{fits:,} right now",
                "close what you can spare and run this again — a browser with "
                "many tabs open is usually the largest single consumer",
                "if it keeps happening the input is too broad: importing the "
                "TEAP for a single venue instead of every venue in the "
                "programme typically shrinks the model by more than an order "
                "of magnitude",
                "nothing was changed, and no work was lost",
            ])

    if need > room * 0.75:
        return [f"this machine is close to its limit: the run needs about "
                f"{need / 1024 ** 3:.1f} GB of the {st.human()} available. "
                f"Closing a few browser tabs before the next run would give it "
                f"more room."]
    return []


def describe() -> dict:
    """A readable snapshot, for the diagnostics endpoint and the logs."""
    st = memory_status()
    if not st.known:
        return {"measured": False, "platform": sys.platform,
                "note": "this platform's free memory could not be measured; "
                        "the optimiser runs without a memory guard"}
    out: dict = {
        "measured": True,
        "source": st.source,
        "available_gb": round(st.available / 1024 ** 3, 2),
        "total_gb": round(st.total / 1024 ** 3, 2),
        "budget_gb": round(budget(st) / 1024 ** 3, 2),
        "affordable_assignment_vars": affordable_vars(st),
        "used_fraction": round(1 - (st.available / st.total), 3) if st.total else None,
    }
    if st.physical_available is not None:
        out["physical_available_gb"] = round(st.physical_available / 1024 ** 3, 2)
    if st.commit_available is not None:
        out["commit_available_gb"] = round(st.commit_available / 1024 ** 3, 2)
    return out
