"""The memory guard: does it fire, and does it stay out of the way?

A guard nobody can trigger is decoration, and a guard that fires on a healthy
machine is worse than none. Both directions are asserted here.

The incident these tests exist for: on 2026-08-28 the server was killed by
Windows while starting a legal-sized solve on a machine at 97% commit charge.
No traceback, no log line — a process killed for memory does not get to write
one. The application appeared to freeze; it had been dead for five hours.
"""

from __future__ import annotations

import pytest

from app.domain import capacity as C


# ---------------------------------------------------------------------------
# Measuring the machine
# ---------------------------------------------------------------------------

def test_the_machine_can_be_measured_or_says_so_plainly():
    st = C.memory_status()
    assert st.source in ("windows-commit", "linux-memavailable", "unknown")
    if st.known:
        assert st.available > 0
        assert st.total >= st.available
    else:
        # An unmeasurable platform must be honest about it rather than
        # reporting a plausible-looking zero as if it were a reading.
        assert st.available == 0


def test_an_unmeasurable_machine_is_never_refused():
    """A guard that blocks work because it could not take a reading is worse
    than no guard at all."""
    unknown = C.MemoryStatus(available=0, total=0, source="unknown")
    assert C.check(10_000_000, unknown) == []
    assert C.affordable_vars(unknown) is None


# ---------------------------------------------------------------------------
# The estimate
# ---------------------------------------------------------------------------

def test_the_estimate_grows_with_the_model():
    assert C.estimate_bytes(200_000) > C.estimate_bytes(100_000)
    # and carries the fixed overhead even for a trivial model
    assert C.estimate_bytes(0) == C.BASE_OVERHEAD_BYTES


def test_the_estimate_matches_what_was_actually_measured():
    """240,000 variables measured 232 MB peak, single-worker.

    The estimate must be at or above that — erring low is the failure mode that
    kills the server, which is the whole point of the module.
    """
    measured_peak = 232 * 1024 ** 2
    assert C.estimate_bytes(240_000) >= measured_peak
    # ...but not so conservative that it refuses reasonable work on a normal
    # machine. Ten times the measured cost would make the guard useless.
    assert C.estimate_bytes(240_000) < measured_peak * 3


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def _machine(free_gb: float, total_gb: float = 16.0) -> C.MemoryStatus:
    return C.MemoryStatus(available=int(free_gb * 1024 ** 3),
                          total=int(total_gb * 1024 ** 3),
                          source="windows-commit",
                          commit_available=int(free_gb * 1024 ** 3))


def test_a_healthy_machine_runs_without_comment():
    """The common case must be silent. Notes on every run become noise, and
    noise is how a real warning gets ignored."""
    assert C.check(120_000, _machine(free_gb=8.0)) == []


def test_the_machine_from_the_incident_is_refused():
    """721 MB free — the reading taken while diagnosing the dead server."""
    incident = _machine(free_gb=0.70, total_gb=15.6)
    with pytest.raises(C.InsufficientMemory) as e:
        C.check(120_000, incident)
    msg = str(e.value)
    assert "not enough memory" in msg.lower()


def test_the_refusal_tells_the_operator_what_to_do():
    """A refusal that does not say what to close is just a different failure."""
    with pytest.raises(C.InsufficientMemory) as e:
        C.check(200_000, _machine(free_gb=0.70))
    detail = " ".join(e.value.detail).lower()
    assert "close" in detail, "must say to close something"
    assert "browser" in detail, "must name the usual culprit"
    assert "venue" in detail, "must point at the real cause when it recurs"
    assert "no work was lost" in detail, "must reassure that nothing was changed"
    # The refusal can happen while raw free memory still looks larger than the
    # estimate, because most of it is the safety margin. If the message does not
    # say so it reads as nonsense — "needs 0.4 GB, you have 0.7 GB free" — and
    # invites whoever reads it to override the guard.
    assert "margin" in detail, "must explain why free memory is not all spendable"
    assert "safely be spent" in detail


def test_a_tight_machine_warns_before_it_refuses():
    """There is a band where the run fits but only just. Saying so early is
    what lets someone close a browser before the next run instead of after."""
    st = _machine(free_gb=16.0)
    room = C.budget(st)
    # size a model at ~85% of the budget: fits, but not comfortably
    n = int((room * 0.85 - C.BASE_OVERHEAD_BYTES) / C.BYTES_PER_VAR)
    notes = C.check(n, st)
    assert len(notes) == 1
    assert "close to its limit" in notes[0]


def test_the_floor_is_respected_on_an_empty_machine():
    """Never plan to use the last of the machine: below the floor the operating
    system is already paging and everything else is suffering."""
    st = _machine(free_gb=0.35)
    assert C.budget(st) == 0
    assert C.affordable_vars(st) == 0


def test_affordable_vars_tracks_the_free_memory():
    big = C.affordable_vars(_machine(free_gb=12.0)) or 0
    small = C.affordable_vars(_machine(free_gb=3.0)) or 0
    assert big > small > 0


# ---------------------------------------------------------------------------
# The wiring
#
# One case stood here, proving the memory guard reached the CP-SAT solver as a
# rendered refusal rather than an exception thrown through the job runner. The
# solver is gone; the guard above is not, because ``affordable_vars`` is still
# what stops a multi-venue import from being attempted on a machine that cannot
# hold it.
# ---------------------------------------------------------------------------

def test_describe_is_readable_and_safe_to_log():
    d = C.describe()
    assert "measured" in d
    if d["measured"]:
        assert d["available_gb"] >= 0
        assert d["affordable_assignment_vars"] >= 0
    # Nothing in the snapshot should be a path, a name, or anything from the
    # study — it goes into the log and possibly into a support message.
    assert not any(isinstance(v, str) and ("/" in v or "\\" in v)
                   for v in d.values())
