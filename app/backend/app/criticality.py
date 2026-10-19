"""Applying the criticality matrix to a project, and reporting what it changed.

The matrix lives outside any one project — it is programme guidance, not venue
data — so it is uploaded once and stored on disk, then applied to whichever
project you are working on. Applying it is deliberately a separate, explicit
step from uploading it: it writes onto the venue's spaces, and a write that
happens as a side effect of an upload is a write nobody reviewed.

Applying never touches an assignment. It fills in
``TeapSpace.criticality`` and records where the value came from; whether that
value is allowed to *refuse* a room is a different switch entirely
(``Project.criticality_enforced``, off by default). See the note there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain.criticality_matrix import CriticalityMatrix, load_matrix_workbook
from .models import Project, TeapSpace

#: One matrix per installation, stored beside the uploads.
MATRIX_FILENAME = "criticality-matrix.xlsx"


def matrix_path(data_dir: Path) -> Path:
    return Path(data_dir) / MATRIX_FILENAME


def load(data_dir: Path, *, sheet: Optional[str] = None,
         header_row: int = 1) -> Optional[CriticalityMatrix]:
    path = matrix_path(data_dir)
    if not path.exists():
        return None
    return load_matrix_workbook(str(path), sheet=sheet, header_row=header_row)


def _spaces(db: Session, project: Project) -> list[TeapSpace]:
    return list(db.execute(
        select(TeapSpace).where(TeapSpace.project_id == project.id)).scalars())


def preview(db: Session, project: Project, matrix: CriticalityMatrix) -> dict:
    """What applying would do, without doing it."""
    rows = _spaces(db, project)
    report = matrix.coverage([(r.space_code, r.space_name) for r in rows])
    report["project"] = project.name
    report["venue_code"] = project.venue_code
    return report


def apply(db: Session, project: Project, matrix: CriticalityMatrix, *,
          actor: str = "user") -> dict:
    """Write the matrix's verdicts onto this project's spaces.

    Only ``stated`` and ``inherited`` verdicts are written. A ``proposed``
    verdict — matched on room name alone — is returned for review and never
    applied, because a wrong guess here promotes or demotes a room and the
    whole mechanism recovers under 2% of spaces.
    """
    rows = _spaces(db, project)
    applied = inherited = cleared = 0
    changes: list[dict] = []

    for row in rows:
        verdict = matrix.lookup(row.space_code, row.space_name)
        if not verdict.applies:
            # A space the matrix does not reach keeps whatever the TEAP itself
            # said, and stays unknown if the TEAP said nothing. It is never
            # blanked on the strength of the matrix's silence.
            continue
        source = ("matrix" if verdict.provenance == "stated"
                  else f"inherited:{verdict.matched_key}")
        before = row.criticality
        if before == verdict.criticality and row.criticality_source == source:
            continue
        row.criticality = verdict.criticality
        row.criticality_source = source
        row.criticality_confirmed = True
        applied += 1
        if verdict.provenance == "inherited":
            inherited += 1
        if before and before != verdict.criticality:
            cleared += 1
        changes.append({
            "space_key": row.space_key, "space_code": row.space_code,
            "space_name": row.space_name, "was": before,
            "now": verdict.criticality, "why": verdict.explain(),
        })

    db.commit()
    report = matrix.coverage([(r.space_code, r.space_name) for r in rows])
    report.update({
        "written": applied,
        "written_by_inheritance": inherited,
        "changed_an_existing_value": cleared,
        "changes": changes[:400],
        "enforced": bool(project.criticality_enforced),
        "enforcement_note": (
            "Criticality is recorded and reported. It does not refuse any room "
            "for any space unless this project has enforcement switched on, "
            "which it does not by default — turning it on re-opens coverage "
            "results that may already have been sent to the drawing team."
            if not project.criticality_enforced else
            "Enforcement is ON for this project: a non-critical room will be "
            "refused for a space the matrix marks critical."),
    })
    return report


# ---------------------------------------------------------------------------
# The escalation report
# ---------------------------------------------------------------------------

def escalations(db: Session, project: Project, coverage_result) -> list[dict]:
    """NERs that serve a critical space but are not themselves critical.

    This is a change request, not a refusal: the room keeps its assignment and
    the report says it has to be reclassified. That ordering is deliberate —
    refusing the assignment would silently move coverage numbers, while a
    reclassification is a decision a person takes to the drawing team.
    """
    if coverage_result is None:
        return []

    crit_by_key: dict[str, tuple[str, str]] = {}
    for row in _spaces(db, project):
        if (row.criticality or "").strip().lower() == "critical":
            crit_by_key[row.space_key] = (row.space_name or row.space_key,
                                          row.criticality_source or "matrix")

    out: dict[str, dict] = {}
    for a in coverage_result.assignments:
        key = getattr(a, "space_key", None) or getattr(a, "area_key", None)
        if key not in crit_by_key:
            continue
        if getattr(a, "ner_critical", None) is not False:
            continue                       # already critical, or not assigned
        ner_key = getattr(a, "ner_key", None)
        if not ner_key:
            continue
        name, source = crit_by_key[key]
        entry = out.setdefault(ner_key, {
            "ner_key": ner_key,
            "ner_label": getattr(a, "ner_label", None),
            "action": "reclassify as critical",
            "spaces_forcing_it": [],
            "why": ("this room serves at least one space the criticality matrix "
                    "marks as requiring a critical NER"),
        })
        entry["spaces_forcing_it"].append({
            "space_key": key, "space_name": name, "stated_by": source})
    for entry in out.values():
        entry["space_count"] = len(entry["spaces_forcing_it"])
    return sorted(out.values(), key=lambda e: -e["space_count"])
