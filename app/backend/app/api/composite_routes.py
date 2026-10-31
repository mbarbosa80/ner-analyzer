"""The composite map (5.0.0) — one map per level of a book, built on request.

Building is a job (a 60-sheet book takes a minute or two); the map window
reads the placement and the overlay, and fetches the picture in tiles so the
browser never holds the whole level at once. Deleting a NER and changing its
criticality use the same requests the Drawing viewer uses.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import composite_service as CS
from ..config import settings
from ..db import SessionLocal, get_session
from ..jobs import manager as job_manager
from ..models import CompositeMap, Drawing, Job, Project, User
from .auth_routes import current_user

router = APIRouter()

_SUBMIT = threading.Lock()
BUSY = ("a composite map of this project is being built — wait for it to finish "
        "(the progress bar shows it)")


def _project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _map(db: Session, project_id: int, map_id: int) -> CompositeMap:
    m = db.get(CompositeMap, map_id)
    if m is None or m.project_id != project_id:
        raise HTTPException(404, "composite map not found")
    return m


def _busy(db: Session, project_id: int, kinds: tuple[str, ...]) -> bool:
    return any(job_manager.is_active(j.id) for j in db.execute(select(Job).where(
        Job.project_id == project_id, Job.kind.in_(kinds),
        Job.state.in_(("pending", "running")))).scalars())


@router.get("/projects/{project_id}/composite")
def composite_plan(project_id: int, db: Session = Depends(get_session)) -> dict:
    """Per book: the groups a build makes, and the maps already built."""
    p = _project(db, project_id)
    return {"books": CS.plan(db, p)}


class BuildIn(BaseModel):
    drawing_id: int
    #: The group keys to build; all of the book when omitted.
    groups: Optional[list[str]] = None


@router.post("/projects/{project_id}/composite/build")
def composite_build(project_id: int, body: BuildIn, user: User = Depends(current_user),
                    db: Session = Depends(get_session)) -> dict:
    p = _project(db, project_id)
    d = db.get(Drawing, body.drawing_id)
    if d is None or d.project_id != p.id:
        raise HTTPException(404, "drawing not found")
    who = user.username

    def work(ctx, jdb: Session) -> dict:
        try:
            return CS.build(jdb, jdb.get(Project, project_id), jdb.get(Drawing, body.drawing_id),
                            only=body.groups, progress=ctx.progress, actor=who)
        except CS.CompositeError as exc:
            raise ValueError(str(exc)) from exc
    with _SUBMIT:
        if _busy(db, p.id, ("composite.build",)):
            raise HTTPException(409, BUSY)
        return {"job_id": job_manager.submit(kind="composite.build", project_id=p.id,
                                             fn=work, db=db), "background": True}


@router.get("/projects/{project_id}/composite/{map_id}")
def composite_overlay(project_id: int, map_id: int, db: Session = Depends(get_session)) -> dict:
    p = _project(db, project_id)
    return CS.overlay(db, p, _map(db, project_id, map_id))


@router.delete("/projects/{project_id}/composite/{map_id}", status_code=204)
def composite_delete(project_id: int, map_id: int, user: User = Depends(current_user),
                     db: Session = Depends(get_session)) -> Response:
    p = _project(db, project_id)
    CS.delete(db, p, _map(db, project_id, map_id), actor=user.username)
    return Response(status_code=204)


def _tile(project_id: int, map_id: int, z: int, x: int, y: int) -> bytes:
    with SessionLocal() as db:
        m = db.get(CompositeMap, map_id)
        if m is None or m.project_id != project_id:
            raise HTTPException(404, "composite map not found")
        try:
            return CS.tile(db, m, z, x, y)
        except CS.CompositeError as exc:
            raise HTTPException(404, str(exc)) from exc


@router.get("/projects/{project_id}/composite/{map_id}/tiles/{z}/{x}/{y}.png")
async def composite_tile(project_id: int, map_id: int, z: int, x: int, y: int) -> Response:
    # Off the event loop: a tile of a 60-sheet level is a second of PyMuPDF
    # the first time it is asked for (cached on disk afterwards).
    png = await run_in_threadpool(_tile, project_id, map_id, z, x, y)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


class ExcludeIn(BaseModel):
    excluded: bool


@router.post("/projects/{project_id}/composite/{map_id}/sheets/{page}/exclude")
def composite_exclude(project_id: int, map_id: int, page: int, body: ExcludeIn,
                      user: User = Depends(current_user),
                      db: Session = Depends(get_session)) -> dict:
    p = _project(db, project_id)
    try:
        return CS.set_excluded(db, p, _map(db, project_id, map_id), page, body.excluded,
                               actor=user.username)
    except CS.CompositeError as exc:
        raise HTTPException(422, str(exc)) from exc


class MoveIn(BaseModel):
    asset_id: int
    x: float
    y: float
    justification: str = Field("", max_length=500)
    #: 5.1.0: say what the move would do (distance, sheets left and drawn on)
    #: without changing anything — the window asks this before its confirm.
    preview: bool = False


@router.post("/projects/{project_id}/composite/{map_id}/move-ner")
def composite_move(project_id: int, map_id: int, body: MoveIn,
                   user: User = Depends(current_user),
                   db: Session = Depends(get_session)) -> dict:
    p = _project(db, project_id)
    try:
        return CS.move_ner(db, p, _map(db, project_id, map_id), body.asset_id, body.x, body.y,
                           actor=user.username, justification=body.justification,
                           preview=body.preview)
    except CS.CompositeError as exc:
        raise HTTPException(409 if "locked" in str(exc) else 422, str(exc)) from exc


@router.post("/projects/{project_id}/composite/undo/{audit_id}")
def composite_undo(project_id: int, audit_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_session)) -> dict:
    p = _project(db, project_id)
    try:
        return CS.undo_move(db, p, audit_id, actor=user.username)
    except CS.CompositeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/composite-report")
def composite_report(project_id: int, legend: bool = Query(True),
                     db: Session = Depends(get_session)) -> dict:
    """The composite map PDF — one page per map built — as a job. Beside the
    marked-up PDF on the Reports screen, never instead of it."""
    p = _project(db, project_id)
    if not any(m.frame for m in CS.maps_of(db, p.id)):
        raise HTTPException(422, "no composite map is built yet — build one first")
    name = f"{p.name.replace(' ', '_')}_composite_map.pdf"

    def work(ctx, jdb: Session) -> dict:
        pp = jdb.get(Project, project_id)
        out_dir = settings.exports_dir / f"project_{project_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        info = CS.export_pdf(jdb, pp, out_dir / name, progress=ctx.progress, draw_legend=legend)
        from .. import services as S
        S.audit(jdb, project_id, "report.generated",
                payload={"format": "composite pdf", "file": name, "pages": info["pages"]})
        jdb.commit()
        return {"file": name, "pages": info["pages"],
                "download": f"/api/projects/{project_id}/reports/download/{name}",
                "source": "composite map"}
    with _SUBMIT:
        if _busy(db, p.id, ("composite.report",)):
            raise HTTPException(409, "the composite map PDF is already being made")
        return {"job_id": job_manager.submit(kind="composite.report", project_id=p.id,
                                             fn=work, db=db), "background": True}
