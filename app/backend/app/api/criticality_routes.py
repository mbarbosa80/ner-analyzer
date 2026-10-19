"""Endpoints for the criticality matrix, the escalation list and overlaps.

The matrix is programme-wide, so it is uploaded once for the installation and
then applied per project. Upload and apply are separate calls on purpose: the
apply writes onto a venue's spaces, and a write that happens as a side effect
of an upload is a write nobody reviewed.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import criticality as C
from .. import services as S
from ..config import settings
from ..db import get_session
from ..domain.criticality_matrix import load_matrix_workbook
from ..domain.overlap import overlapping_candidates
from ..models import Project

router = APIRouter()


def _project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _matrix(sheet: Optional[str] = None, header_row: int = 1):
    path = C.matrix_path(settings.data_dir)
    if not path.exists():
        raise HTTPException(
            422, "no criticality matrix has been uploaded yet. Upload the "
                 "programme's Critical / Non-Critical NER sheet first.")
    try:
        return load_matrix_workbook(str(path), sheet=sheet, header_row=header_row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/criticality/matrix")
def matrix_state() -> dict:
    """Is a matrix loaded, and what does it contain?"""
    path = C.matrix_path(settings.data_dir)
    if not path.exists():
        return {"loaded": False}
    m = load_matrix_workbook(str(path))
    return {
        "loaded": True,
        "filename": path.name,
        "rows": len(m.rows),
        "by_space_code": len(m.by_code),
        "by_name_only": len(m.by_name),
        "critical": sum(1 for v in m.by_code.values() if v == "critical"),
        "non_critical": sum(1 for v in m.by_code.values() if v == "non-critical"),
        "conflicts": m.conflicts,
        "rows_with_no_tick": m.blank,
        "note": ("This matrix is programme guidance, shared by every project on "
                 "this installation. It is applied to a venue only when you ask."),
    }


@router.post("/criticality/matrix", status_code=201)
def upload_matrix(file: UploadFile = File(...)) -> dict:
    dest = C.matrix_path(settings.data_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        fh.write(file.file.read())
    try:
        m = load_matrix_workbook(str(dest))
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"this file could not be read as a criticality "
                                 f"matrix: {exc}") from exc
    return {"ok": True, "rows": len(m.rows), "by_space_code": len(m.by_code),
            "by_name_only": len(m.by_name), "conflicts": m.conflicts}


@router.get("/projects/{project_id}/criticality/preview")
def preview(project_id: int, db: Session = Depends(get_session)) -> dict:
    """What applying the matrix would do to this venue, without doing it."""
    return C.preview(db, _project(db, project_id), _matrix())


class ApplyIn(BaseModel):
    justification: str = ""


@router.post("/projects/{project_id}/criticality/apply")
def apply(project_id: int, body: ApplyIn, db: Session = Depends(get_session)) -> dict:
    project = _project(db, project_id)
    report = C.apply(db, project, _matrix(), actor="user")
    S.audit(db, project.id, "criticality.applied", entity="project",
            entity_id=project.id,
            payload={"written": report["written"],
                     "inherited": report["written_by_inheritance"],
                     "missing_rule": report["rule_missing"]},
            justification=body.justification)
    return report


class EnforceIn(BaseModel):
    value: bool
    justification: str = ""


@router.post("/projects/{project_id}/criticality/enforce")
def set_enforcement(project_id: int, body: EnforceIn,
                    db: Session = Depends(get_session)) -> dict:
    """Let criticality refuse a room, or stop letting it.

    Turning this on changes coverage results that may already have been sent to
    the drawing team, so it is an explicit act with a justification, recorded.
    """
    project = _project(db, project_id)
    project.criticality_enforced = bool(body.value)
    db.commit()
    S.audit(db, project.id, "criticality.enforcement", entity="project",
            entity_id=project.id, payload={"enforced": project.criticality_enforced},
            justification=body.justification)
    return {
        "enforced": project.criticality_enforced,
        "note": ("Re-run the coverage analysis to see the effect. Spaces the "
                 "matrix marks critical will no longer accept a non-critical "
                 "room, so some may move from served to out of coverage."
                 if project.criticality_enforced else
                 "Criticality is now recorded and reported only; it will not "
                 "refuse any assignment."),
    }


@router.get("/projects/{project_id}/criticality/escalations")
def escalations(project_id: int, db: Session = Depends(get_session)) -> dict:
    """Rooms that must be reclassified as critical, and the spaces forcing it."""
    project = _project(db, project_id)
    result, _ners = S.analyse(db, project)
    rows = C.escalations(db, project, result)
    return {
        "escalations": rows,
        "count": len(rows),
        "note": ("Each of these keeps its current assignment. The report is a "
                 "change request for the drawing team, not a refusal — see the "
                 "enforcement switch if you want the analysis to refuse them."),
    }


@router.get("/projects/{project_id}/overlaps")
def overlaps(project_id: int, db: Session = Depends(get_session)) -> dict:
    """Overlapping rooms and which of them could actually be given up."""
    project = _project(db, project_id)
    result, ners = S.analyse(db, project)
    scales = S.scale_map(db, project.id)
    areas = S.collect_areas(db, project)
    by_key = {a[0].key: (a[0], a[1], a[2], a[3]) for a in areas}
    rows = overlapping_candidates(result, ners, S.distance_rules(project), scales,
                                  areas_by_key=by_key)
    removable = [r for r in rows if r["can_be_removed"]]
    return {
        "candidates": rows,
        "removable": len(removable),
        "examined": len(rows),
        "note": ("A room is only proposed for removal when every space it serves "
                 "can still be reached by another room that has the ports free. "
                 "Refusals carry their reason — most often capacity, which is "
                 "the cable-volume case stated in ports rather than a guess."),
    }
