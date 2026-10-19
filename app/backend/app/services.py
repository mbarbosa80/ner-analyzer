"""Service layer: turns persisted rows into domain objects and back.

The API stays thin; everything that decides a number lives in ``app.domain``.
"""

from __future__ import annotations

import contextlib
import threading

import datetime as _dt
import hashlib
import re
import shutil
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from . import isolate
from .domain import matching as M
from .domain.coverage import (NER, SERVING_KINDS, Assignment, CoverageResult, compute_coverage,
                              redundancy_candidates)
from .domain.demand import WIRELESS_HINTS, DemandRuleSet, SpaceDemand, compute_demand
from .domain.distance import DemandType, DistanceRules, Status
from .domain.geometry import Area, Point
from .domain.pdf_ingest import (DEMAND_KINDS, WIRELESS_NAME, WIRELESS_POINT_PORTS,
                                DetectedSpace, ElementKind)
from .domain.scope import teap_scope
from .domain.routes import RouteNetwork, RouteSegment, VerticalLink, build_network
from .domain.teap_import import (load_product_catalogue, preview_venues, profile_csv,
                                 profile_workbook, read_csv, read_sheet)
from .domain.units import Scale
from . import sheets as SH
from .models import (SpaceOccurrenceLink, Alias, AuditLog, Criticality, Drawing, DrawingSpace, Element,
                     KeepDecision, NerAsset, NerStatus, Page, Project, RouteSegmentRow,
                     Scenario, SpaceMatchRow, TeapFile, TeapSpace, VerticalLinkRow, Zone)

#: A job's progress callback: ``(fraction, stage)``. Raising from it aborts the
#: operation, which is how cancellation propagates into the domain code.
Progress = Optional[Callable[[float, str], None]]


def _noop(_frac: float, _stage: str = "") -> None:
    return None


def _prog(progress: Progress) -> Callable[[float, str], None]:
    return progress if progress is not None else _noop


class ValidationError(ValueError):
    """Raised for user-correctable input problems."""


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_upload(project_id: int, filename: str, src, *,
                 allowed_suffixes: Optional[tuple[str, ...]] = None) -> Path:
    """Persist an upload inside the project's own directory.

    Documents are treated as untrusted: the extension is validated, the name is
    flattened so it cannot escape the directory, the size is capped and macros are
    never executed (the readers open workbooks with ``keep_vba=False``).
    """
    safe = Path(filename).name.replace("\\", "_")
    suffix = Path(safe).suffix.lower()
    if allowed_suffixes and suffix not in allowed_suffixes:
        raise ValidationError(f"file type {suffix!r} is not accepted "
                              f"(allowed: {', '.join(allowed_suffixes)})")
    target_dir = settings.uploads_dir / f"project_{project_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe
    n = 1
    while target.exists():
        target = target_dir / f"{Path(safe).stem}_{n}{suffix}"
        n += 1
    with open(target, "wb") as out:
        shutil.copyfileobj(src, out, length=1 << 20)
    size_mb = target.stat().st_size / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        target.unlink(missing_ok=True)
        raise ValidationError(f"file is {size_mb:.0f} MB, over the "
                              f"{settings.max_upload_mb} MB limit")
    return target


def next_project_id(db: Session) -> int:
    """An id no project has had on this installation (4.2.0): above the live
    ones, the highest ever handed out, and every project folder on disk."""
    from .models import AppCounter
    live = db.execute(select(func.max(Project.id))).scalar() or 0
    row = db.get(AppCounter, "project_id")
    high = row.value if row else 0
    on_disk = 0
    for base in (settings.uploads_dir, settings.exports_dir):
        try:
            for d in base.iterdir():
                m = re.fullmatch(r"project_(\d+)", d.name)
                if m:
                    on_disk = max(on_disk, int(m.group(1)))
        except OSError:
            pass
    nid = max(live, high, on_disk) + 1
    if row is None:
        db.add(AppCounter(name="project_id", value=nid))
    else:
        row.value = nid
    return nid


def remove_project_files(project_id: int) -> list[str]:
    """Delete a deleted project's uploads and exports from disk (4.2.0). The
    manual promised it; the folders stayed, with the venue's documents in them."""
    gone = []
    for base in (settings.uploads_dir, settings.exports_dir):
        d = base / f"project_{project_id}"
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            gone.append(str(d))
    return gone


#: Who is signed in on the request being served (4.2.0) — set by a middleware
#: from the session cookie and carried into the background jobs that request
#: starts. The audit log used to write "user" for most actions, and the NER
#: routes took the author from the request body.
import contextvars as _cv
CURRENT_ACTOR: "_cv.ContextVar[Optional[str]]" = _cv.ContextVar("ner_current_actor", default=None)


def current_actor(fallback: str = "user") -> str:
    """The signed-in username, or ``fallback`` outside a request."""
    return CURRENT_ACTOR.get() or fallback


def audit(db: Session, project_id: Optional[int], action: str, *, entity: str = "",
          entity_id: Optional[int] = None, actor: str = "user",
          justification: str = "", payload: Optional[dict] = None) -> None:
    # "user" is what every caller passes when it does not know who: the person
    # signed in is the answer whenever there is one. "system" stays system.
    if actor in ("user", "", None) or actor.startswith("user ("):
        who = CURRENT_ACTOR.get()
        if who:
            actor = who + (actor[4:] if actor and actor.startswith("user (") else "")
    db.add(AuditLog(project_id=project_id, action=action, entity=entity,
                    entity_id=entity_id, actor=actor, justification=justification,
                    payload=payload or {}))


# ---------------------------------------------------------------------------
# Drawings
# ---------------------------------------------------------------------------

def ingest_drawing(db: Session, project: Project, path: Path, filename: str,
                   progress: Progress = None, *, place_ners: bool = False) -> Drawing:
    """Read a book into the project: pages, scales, title blocks, spaces and the
    markers that only illustrate (TER, IDF, COW, DIVA).

    The NERs are **not** placed here any more (2.14.0). What the book says
    about them — the team's own NER annotations, the ``TEC.003`` rooms, the
    "Network Equipment Rack (NER)" labels — is read and kept on the drawing
    (``extract_summary["ner_annotations"]``), and becomes NERs when the person
    presses *Place NERs from the drawing* on the Scale screen, after the key
    plans are ticked and the scales confirmed. Marcelo, 29 Sep 2026: *"seria
    melhor a ferramenta só posicionar NER depois de eu marcar e desmarcar
    páginas key e confirmar scale."* ``place_ners=True`` runs that step at
    once (the tests, and anyone who wants the old one-shot import).
    """
    report = _prog(progress)
    report(0.02, f"opening {filename}")
    # The names the project's TEAP prints are what a name-only room label is
    # checked against, with the bundled AAM names (2.14.0).
    known = [n for n in db.execute(select(TeapSpace.space_name).where(
        TeapSpace.project_id == project.id)).scalars() if n]
    # Read in a child interpreter (2.17.0): a 70 MB book leaves a few hundred
    # megabytes behind in whichever process reads it, and a child gives them
    # back when it exits — the server does not. See ``isolate.py``.
    extract = isolate.run("app.domain.pdf_ingest.extract_drawing", str(path),
                          progress=lambda f, s: report(0.02 + f * 0.88, s),
                          known_names=known)
    if not extract.page_count:
        # A damaged or truncated PDF can open with no page at all (4.2.1): it
        # used to come in as a book of 0 pages, which made a one-book project a
        # multi-book one and changed what every page number named.
        raise ValidationError(f"'{filename}' could not be read as a PDF — it opens with no "
                              f"page (damaged, truncated or not a drawing). Nothing was imported.")
    report(0.92, "storing pages, spaces and markers")
    annotations = [e for e in extract.elements
                   if e.kind in (ElementKind.NER_CRITICAL, ElementKind.NER_NONCRITICAL)]
    others = [e for e in extract.elements if e not in annotations]
    drawing = Drawing(project_id=project.id, filename=filename, stored_path=str(path),
                      sha256=sha256_file(path), page_count=extract.page_count,
                      extract_summary={
                          "spaces": len(extract.spaces),
                          "elements": len(extract.elements),
                          "needs_ocr_pages": extract.needs_ocr_pages,
                          "layers": extract.layer_names,
                          "spaces_pass": SPACES_PASS,
                          # What the book says about its NERs, kept for the
                          # placing step (2.14.0).
                          "ner_annotations": [
                              {"page": e.page, "kind": e.kind, "label": e.label, "x": e.x,
                               "y": e.y, "number": e.number, "confidence": e.confidence,
                               "evidence": list(e.evidence), "color": e.color}
                              for e in annotations],
                          "drawn_rooms_found": len(extract.rooms),
                          "ner_pass": None,
                      })
    db.add(drawing)
    db.flush()

    for p in extract.pages:
        best = p.scale_candidates[0] if p.scale_candidates else None
        db.add(Page(
            drawing_id=drawing.id, number=p.number, width=p.width, height=p.height,
            rotation=p.rotation, is_vector=p.is_vector,
            needs_ocr=p.number in extract.needs_ocr_pages,
            sheet_title=p.sheet_title, level=p.level_hint,
            sheet_number=p.sheet_number,
            key_plan=bool(p.key_plan), key_plan_source="title",
            metres_per_unit=best.metres_per_unit if best else None,
            scale_label=best.label if best else None,
            scale_source=best.source if best else None,
            scale_confirmed=False,
            scale_candidates=[{"label": s.label, "source": s.source,
                               "metres_per_unit": s.metres_per_unit}
                              for s in p.scale_candidates],
        ))

    for s in extract.spaces:
        db.add(DrawingSpace(project_id=project.id, drawing_id=drawing.id, page=s.page,
                            space_code=s.space_code, name=s.name, x=s.x, y=s.y,
                            area_label=s.area_label, confidence=s.confidence,
                            origin="extracted", evidence=s.evidence))

    for e in others:
        db.add(Element(project_id=project.id, drawing_id=drawing.id, page=e.page,
                       kind=e.kind, label=e.label, number=e.number, x=e.x, y=e.y,
                       origin="extracted", confidence=e.confidence,
                       confirmed=False, evidence=e.evidence,
                       detection_method="pdf_extraction", document_kind="VDB",
                       colour=getattr(e, "color", None),
                       link_status="unlinked"))

    audit(db, project.id, "drawing.ingested", entity="drawing", entity_id=drawing.id,
          payload={k: v for k, v in drawing.extract_summary.items() if k != "ner_annotations"}
          | {"ner_annotations": len(annotations)})
    db.commit()

    placed = None
    if place_ners:
        placed = place_ners_from_drawing(db, project, drawing)

    report(1.0, f"{extract.page_count} pages, {len(extract.spaces)} spaces, "
                f"{len(others)} rooms drawn (TER, IDF, COW, DIVA); "
                + (f"{placed['created']} NER(s) placed" if placed is not None else
                   f"{len(annotations)} NER annotation(s) and {len(extract.rooms)} NER room(s) "
                   f"read — tick the key plans, confirm the scales, then place the NERs"))
    return drawing


#: Stamped into ``Drawing.extract_summary`` by the extraction of 2.14.0, and
#: by the start-up clean-up that brings an older book's spaces up to it.
SPACES_PASS = "spaces-2.14.0"


def place_ners_from_drawing(db: Session, project: Project, drawing: Optional[Drawing] = None,
                            *, actor: str = "system", progress: Progress = None) -> dict:
    """See ``_place_ners_from_drawing``. One run at a time per project (4.0.0):
    a second press while the first is still reading the books is refused with
    :class:`BusyError` instead of placing every NER a second time."""
    with one_at_a_time(project.id, "ners", PLACE_NERS_BUSY):
        return _place_ners_from_drawing(db, project, drawing, actor=actor, progress=progress)


def _place_ners_from_drawing(db: Session, project: Project, drawing: Optional[Drawing] = None,
                             *, actor: str = "system", progress: Progress = None) -> dict:
    """The NER placing step (2.14.0): what the book says about its NERs
    becomes NERs, in this order — the team's own annotations ("Critical NER
    8" written on the sheet), then the ``TEC.003.01 / .02`` and (2.15.0)
    ``TEC.010 / TEC.020`` rooms, then the "Network Equipment Rack (NER)" /
    "Network Equipment Rack - Non-Critical" labels, then (2.15.0) the NER
    block symbols the 3.x books draw. Never on a key plan. A candidate
    within ``DRAWN_ROOM_SAME_PLACE_M`` of a NER already on the sheet is taken
    as that NER (no second one); a duplicate that slips through is for the
    person to delete in the Drawing viewer — his choice over placing every
    NER by hand.

    Runs on every book of the project unless ``drawing`` is given. Safe to run
    again: what was placed before is on the sheet and absorbs its candidates.
    Every NER it creates is named in sequence (``NERc01`` …, ``NER01`` …), the
    label the drawing printed kept as *printed as*.
    """
    from . import migrate as MG

    report = _prog(progress)
    drawings = [drawing] if drawing is not None else list(db.execute(
        select(Drawing).where(Drawing.project_id == project.id).order_by(Drawing.id)).scalars())
    totals = {"annotations": 0, "annotations_absorbed": 0, "annotations_on_removed": 0,
              "annotations_on_key_plan": 0,
              "rooms_found": 0, "created": 0, "same_as_marker": 0, "on_removed_ner": 0,
              "same_code_other_page": 0, "criticality_unstated": 0,
              "placed_on_label": 0, "on_key_plan": 0, "symbols": 0,
              "same_place_other_page": 0, "names": [], "books": []}
    for i, d in enumerate(drawings):
        report(i / max(len(drawings), 1), f"placing the NERs of {d.filename}")
        summary = dict(d.extract_summary or {})
        # This book's key plans, by its own page numbers (4.1.0: another
        # book's page 1 being a key plan says nothing about this one's).
        key_pages = key_plan_numbers(db, d.id)
        # 1. The team's annotations.
        made: list[Element] = []
        for ann in summary.get("ner_annotations") or []:
            if ann["page"] in key_pages:
                totals["annotations_on_key_plan"] += 1
                continue
            near = _ner_marker_near(db, project, ann["page"], ann["x"], ann["y"],
                                    drawing_id=d.id)
            if near is None and _removed_spot_near(db, project, d.id, ann["page"],
                                                   ann["x"], ann["y"]) is not None:
                # Where a removed NER stood (4.2.1), even with no marker left.
                totals["annotations_on_removed"] += 1
                continue
            if near is not None:
                # A removed room's marker absorbs the annotation too (2.18.1):
                # the person took that NER out; the pass does not put it back.
                na = near.ner_asset
                totals["annotations_on_removed" if na is not None and na.deleted_at is not None
                       else "annotations_absorbed"] += 1
                continue
            e = Element(project_id=project.id, drawing_id=d.id, page=ann["page"],
                        kind=ann["kind"], label=ann["label"], number=ann.get("number"),
                        x=ann["x"], y=ann["y"], origin="extracted",
                        confidence=ann.get("confidence") or 0.0, confirmed=False,
                        evidence=list(ann.get("evidence") or []),
                        detection_method="pdf_extraction", document_kind="VDB",
                        colour=ann.get("color"), nearby_text=ann["label"],
                        link_status="unlinked")
            db.add(e)
            made.append(e)
        db.flush()
        if made:
            reg = MG.backfill_assets(db, project)
            totals["annotations"] += len(made)
            totals["created"] += reg.get("created", 0)
            totals["names"] += [e.label for e in made if e.ner_asset_id is not None]
        # 2, 3 and 4. The rooms the sheets print: TEC codes, then labels,
        # then the block symbols.
        rooms = []
        if d.stored_path and Path(d.stored_path).exists():
            base, span = i / max(len(drawings), 1), 1 / max(len(drawings), 1)

            def _page_progress(frac, msg, _base=base, _span=span, _name=d.filename):
                report(_base + frac * _span * 0.8, f"{_name}: {msg}")

            try:
                # In a child interpreter (2.17.0), like the import — this
                # walks every stroke of every sheet.
                rooms = isolate.run("app.domain.pdf_ingest.read_drawn_rooms",
                                    d.stored_path, skip_pages=sorted(key_pages),
                                    progress=_page_progress)
            except Exception as exc:  # noqa: BLE001 — a book that cannot be re-read
                summary["ner_pass_error"] = str(exc)
        order = {"code": 0, "label": 1, "symbol": 2}
        rooms.sort(key=lambda r: (order.get(r.source, 3), r.page, round(r.y / 20.0), r.x))
        stats = adopt_drawn_rooms(db, project, d, rooms, actor=actor)
        totals["rooms_found"] += stats["found"]
        for k in ("created", "same_as_marker", "on_removed_ner", "same_code_other_page",
                  "criticality_unstated", "placed_on_label", "on_key_plan",
                  "symbols", "same_place_other_page"):
            totals[k] += stats[k]
        totals["names"] += stats["names"]
        summary["ner_pass"] = {"at": _dt.datetime.utcnow().isoformat(timespec="seconds"),
                               "by": actor, "annotations": len(made),
                               "rooms": stats["found"], "created": totals["created"]}
        summary["drawn_rooms"] = stats
        summary["drawn_rooms_pass"] = DRAWN_ROOMS_PASS
        d.extract_summary = summary
        totals["books"].append(d.filename)
        db.commit()
    audit(db, project.id, "ner.placed_from_drawing", entity="project", entity_id=project.id,
          actor=actor, payload={k: v for k, v in totals.items() if k != "names"}
          | {"names": totals["names"][:200]},
          justification="the NERs the drawings state — team annotations, TEC.003 / TEC.010 / "
                        "TEC.020 rooms, NER room labels, NER block symbols — placed after "
                        "key plans and scales")
    db.commit()
    report(1.0, f"{totals['created']} NER(s) placed")
    return totals


def _removed_spot_near(db: Session, project: Project, drawing_id: int, page: int,
                       x: float, y: float) -> Optional[NerAsset]:
    """A removed NER whose recorded position is within ``DRAWN_ROOM_SAME_PLACE_M``
    of (x, y) on that page of that book, or None (4.2.1)."""
    import math

    sh = SH.for_project(db, project.id)
    first = sh.drawing_ids[0] if sh.drawing_ids else None
    sc = scale_map(db, project.id).get(sh.key(drawing_id, page))
    limit = DRAWN_ROOM_SAME_PLACE_M / sc.metres_per_unit if sc else DRAWN_ROOM_SAME_PLACE_PT
    best: Optional[tuple[float, NerAsset]] = None
    for a in db.execute(select(NerAsset).where(
            NerAsset.project_id == project.id, NerAsset.deleted_at.is_not(None),
            NerAsset.merged_into_id.is_(None), NerAsset.canonical_page == page)).scalars():
        if a.position_known is False or (a.canonical_drawing_id or first) != drawing_id:
            continue
        dist = math.dist((a.canonical_x, a.canonical_y), (x, y))
        if dist <= limit and (best is None or dist < best[0]):
            best = (dist, a)
    return best[1] if best else None


def _ner_marker_near(db: Session, project: Project, page: int, x: float, y: float,
                     *, drawing_id: Optional[int] = None) -> Optional[Element]:
    """A NER marker within ``DRAWN_ROOM_SAME_PLACE_M`` of (x, y) on ``page``,
    or None — the "is there a NER here already?" test.

    A marker of a NER somebody *removed* counts (2.18.1). Removing a room is a
    decision about that spot on the sheet; until then this test skipped the
    removed room's markers, so the next *Place NERs from the drawing* read
    the team's annotation at the same point and created the room again under
    a new name — "ela volta". A merged row's markers belong to the room it
    was merged into and count the same way.
    """
    import math

    sh = SH.for_project(db, project.id)
    if drawing_id is None:                  # one-book callers: its only book
        drawing_id = sh.drawing_ids[0] if sh.drawing_ids else None
    sc = scale_map(db, project.id).get(sh.key(drawing_id, page))
    limit = DRAWN_ROOM_SAME_PLACE_M / sc.metres_per_unit if sc else DRAWN_ROOM_SAME_PLACE_PT
    best: Optional[tuple[float, Element]] = None
    first = sh.drawing_ids[0] if sh.drawing_ids else None
    for e in db.execute(select(Element).where(
            Element.project_id == project.id, Element.page == page,
            on_book(Element.drawing_id, drawing_id, first),
            Element.scenario_id.is_(None),
            Element.kind.in_((ElementKind.NER_CRITICAL, ElementKind.NER_NONCRITICAL)))).scalars():
        dist = math.dist((e.x, e.y), (x, y))
        if dist <= limit and (best is None or dist < best[0]):
            best = (dist, e)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Key plans and the NER rooms the drawing prints (2.13.0)
# ---------------------------------------------------------------------------

#: Stamped into ``Drawing.extract_summary`` once a book's NER rooms have been
#: read, so the start-up pass reads each existing book once.
DRAWN_ROOMS_PASS = "drawn-rooms-2.13.0"

#: Two things this close on the same sheet are one room: a NER somebody wrote
#: on the drawing and the NER room the drawing prints beside it. Measured on
#: the HND book: the reviewers' red "Critical NER 8" sits 6.3 m from
#: the room TEC.003.01-04 it marks, "NER 19" 3.3 m from TEC.003.01-16, and
#: the nearest *different* rack is more than 15 m away.
DRAWN_ROOM_SAME_PLACE_M = 12.0
#: The same in points, for a sheet with no scale: 12 m at 1:200.
DRAWN_ROOM_SAME_PLACE_PT = 170.0


def key_plan_pages(db: Session, project_id: int) -> set[int]:
    """The **sheet keys** of a project's key plans (4.1.0 — the page numbers
    themselves in a one-book project; see :mod:`app.sheets`)."""
    sh = SH.for_project(db, project_id)
    return {sh.key(d, n) for d, n in db.execute(
        select(Page.drawing_id, Page.number).join(Drawing)
        .where(Drawing.project_id == project_id, Page.key_plan.is_(True))).all()}


def on_book(column, drawing_id: Optional[int], first_drawing_id: Optional[int]):
    """``column == drawing_id`` — and, for the project's first book, a row with
    no book recorded too: :class:`app.sheets.Sheets` reads such a row as
    drawn on the first book, and a query must agree with it (4.1.0)."""
    if drawing_id is not None and drawing_id == first_drawing_id:
        return or_(column == drawing_id, column.is_(None))
    return column == drawing_id


def key_plan_numbers(db: Session, drawing_id: int) -> set[int]:
    """The page numbers of one book that are key plans — for the passes that
    walk a single PDF (4.1.0)."""
    return set(db.execute(select(Page.number).where(
        Page.drawing_id == drawing_id, Page.key_plan.is_(True))).scalars())


def _add_once(row, field: str, text: str) -> None:
    """Append ``text`` to a list field unless it is there already (4.2.1): each
    *Place NERs* run added the same evidence lines again — +105 lines on the
    40 NERs of one project after two runs, with nothing new found."""
    cur = list(getattr(row, field) or [])
    if text not in cur:
        setattr(row, field, cur + [text])


def adopt_drawn_rooms(db: Session, project: Project, drawing: Drawing, rooms,
                      *, actor: str = "system") -> dict:
    """Turn the NER rooms the drawing prints into NERs — where nobody has yet.

    Marcelo, 29 Sep 2026: *"Eu só quero evitar criar todas as NER manualmente
    se a informação já tá no desenho... prefiro conferir e validar do que criar
    tudo do zero."* Each room found by ``domain.drawn_rooms`` is, in order:

    1. **already a NER on the sheet** — a marker (written on the drawing, or
       placed by hand) within ``DRAWN_ROOM_SAME_PLACE_M`` on the same page. No
       second NER: the code is recorded on it, and a criticality that
       disagrees with the drawing's is raised as a question on the row;
    2. **the same code on another sheet** — ``TEC.003.02-01`` printed on two
       detail sheets is one room: a second marker of the NER that exists;
    3. **new** — a NER named in sequence (``NERc_01.1`` …, ``NER_20.1`` …), the
       code or label the sheet printed kept as *printed as*. Never
       confirmed: it is the drawing's reading, for him to check. A rack whose
       criticality the drawing does not state — every NER block symbol
       (2.15.0), a label with no criticality words — is created non-critical
       with the criticality *pending* — the NERs screen will not confirm it
       until he chooses — and one whose label arrow could not be followed
       says so. Only a code with a room number (``TEC.020-003``) identifies
       one room across sheets; a bare ``TEC.010`` printed twice is two racks.
       A symbol at the same position as a symbol on another sheet of the
       book (the OSP book repeats a level-01 rack on the level-02 plan) is
       created and asked about.

    Nothing here runs on a key plan (the rooms are not even read there).
    """
    import math

    from . import migrate as MG
    from .models import NerConsolidation

    from .domain.drawn_rooms import code_names_a_room

    stats = {"found": len(rooms), "created": 0, "same_as_marker": 0, "on_removed_ner": 0,
             "same_code_other_page": 0, "criticality_differs": 0,
             "criticality_unstated": 0, "placed_on_label": 0, "on_key_plan": 0,
             "symbols": 0, "same_place_other_page": 0, "names": []}
    if not rooms:
        return stats
    # This book's key plans and pages, by its own page numbers; scales by
    # sheet key (4.1.0).
    key_pages = key_plan_numbers(db, drawing.id)
    scales = scale_map(db, project.id)
    sh = SH.for_project(db, project.id)
    pages = db.execute(select(Page).where(Page.drawing_id == drawing.id)).scalars().all()
    page_meta = {sh.key(p.drawing_id, p.number): (p.level, p.building) for p in pages}
    markers = list(db.execute(select(Element).where(
        Element.project_id == project.id, Element.drawing_id == drawing.id,
        Element.scenario_id.is_(None),
        Element.kind.in_((ElementKind.NER_CRITICAL, ElementKind.NER_NONCRITICAL)))).scalars())
    live = [a for a in db.execute(select(NerAsset).where(NerAsset.project_id == project.id)).scalars()
            if a.deleted_at is None and a.merged_into_id is None]
    assets = {a.id: a for a in live}
    by_code = {a.space_code: a for a in live if code_names_a_room(a.space_code)}
    # A numbered room a person removed keeps its code (4.2.0). Its markers held
    # its spot only on the sheets they are on, so the same code printed on
    # another sheet — or on another series of the book — came back as a new
    # NER under the next free name. On the RIV project, 16 Oct 2026: seven
    # removed rooms re-created by one run, deleted again by hand.
    removed_by_code = {
        a.space_code: a for a in db.execute(select(NerAsset).where(
            NerAsset.project_id == project.id, NerAsset.deleted_at.is_not(None),
            NerAsset.merged_into_id.is_(None))).scalars()
        if code_names_a_room(a.space_code) and a.space_code not in by_code}
    # Where a person removed a NER, by the position the register keeps (4.2.1).
    # A room removed before 2.18.1 lost its marker for good, and one with no
    # TEC code has no code to hold its place either: a NER block symbol or a
    # label read at that spot came back as a new NER (a softball project and
    # a velodrome project, 16 Oct 2026: five rooms removed on 8 Oct).
    first_book = sh.drawing_ids[0] if sh.drawing_ids else None
    removed_spots = [
        (a.canonical_page, a.canonical_x, a.canonical_y, a)
        for a in db.execute(select(NerAsset).where(
            NerAsset.project_id == project.id, NerAsset.deleted_at.is_not(None),
            NerAsset.merged_into_id.is_(None))).scalars()
        if a.position_known is not False and a.canonical_page
        and (a.canonical_drawing_id or first_book) == drawing.id]
    names = [a.display_name for a in live]
    # Where the symbols of this pass land, per page, for the same-position
    # question across sheets.
    placed_symbols: list[tuple[int, float, float, str]] = []
    # What each code or label room of this pass became (4.2.0): page, x, y,
    # the asset, and whether that asset is a removed one. A NER block symbol
    # drawn inside a room whose code this pass also read is the same room
    # read twice — on the RIV 400 book the symbol of TEC.010-021 sat 4 m
    # from its code, and the room came back twice, once from each.
    this_pass: list[tuple[int, float, float, NerAsset, bool]] = []

    # 1. A NER already on the sheet, here — his rule, 29 Sep 2026: create one
    #    only where there is no NER near. Each room goes to the nearest marker
    #    that existed before this pass within the distance, and one marker may
    #    answer for several rooms (three racks labelled side by side in one
    #    cabin, one NER drawn for them — the ALA book). Only markers that
    #    were there before count: the rooms read in this pass are distinct
    #    labels, never merged with each other. A marker whose room already
    #    carries a different TEC.003 code is a different room.
    def limit_for(page: int) -> tuple[float, Optional[float]]:
        sc = scales.get(sh.key(drawing.id, page))
        mpu = sc.metres_per_unit if sc else None
        return (DRAWN_ROOM_SAME_PLACE_M / mpu if mpu else DRAWN_ROOM_SAME_PLACE_PT), mpu

    claimed: dict[int, tuple[float, Element]] = {}
    for ri, r in enumerate(rooms):
        if r.page in key_pages:
            continue
        limit, _mpu = limit_for(r.page)
        best_pair: Optional[tuple[float, Element]] = None
        for e in markers:
            if e.page != r.page:
                continue
            a = assets.get(e.ner_asset_id)
            if r.code and a is not None and a.space_code and a.space_code != r.code:
                continue
            d = min(math.dist((e.x, e.y), (r.x, r.y)),
                    math.dist((e.x, e.y), (r.label_x, r.label_y)))
            if d <= limit and (best_pair is None or d < best_pair[0]):
                best_pair = (d, e)
        if best_pair is not None:
            claimed[ri] = best_pair

    for ri, r in enumerate(rooms):
        if r.page in key_pages:
            stats["on_key_plan"] += 1
            continue
        _limit, mpu = limit_for(r.page)
        what = r.code or f"'{r.text}'"

        if ri in claimed:
            d, e = claimed[ri]
            where = f"{d * mpu:.1f} m" if mpu else f"{d:.0f} pt"
            a = assets.get(e.ner_asset_id)
            if r.source != "symbol" and e.ner_asset_id is not None:
                held = a if a is not None else db.get(NerAsset, e.ner_asset_id)
                if held is not None:
                    this_pass.append((r.page, r.x, r.y, held, a is None))
            if a is None and e.ner_asset_id is not None:
                # The room drawn here was removed by a person (2.18.1): its
                # marker still holds the spot, and the pass creates nothing.
                stats["on_removed_ner"] += 1
                continue
            if a is not None:
                if r.code and not a.space_code:
                    a.space_code = r.code
                    other = by_code.get(r.code)
                    if other is not None and other.id != a.id:
                        _add_once(a, "classification_evidence", 
                            f"{other.display_name} ({sh.label(sh.of_asset(other))}) carries the "
                            f"same code {r.code} — possibly the same NER on two sheets")
                    if code_names_a_room(r.code):
                        by_code.setdefault(r.code, a)
                _add_once(a, "classification_evidence", 
                    f"the drawing prints the NER room {what} {where} from this marker "
                    f"({sh.label(sh.key(drawing.id, r.page))}) — taken as this NER, no second one created")
                marked_critical = e.kind == ElementKind.NER_CRITICAL
                if r.critical is not None and r.critical != marked_critical:
                    _add_once(a, "pending_validations", 
                        f"criticality: the drawing prints {what} as "
                        f"{'critical' if r.critical else 'non-critical'} {where} from this "
                        f"NER, which is marked {'critical' if marked_critical else 'non-critical'}"
                        f" — check which is right")
                    stats["criticality_differs"] += 1
            stats["same_as_marker"] += 1
            continue

        # 1a. Where a removed NER stood (4.2.1): the room stays removed, by its
        #     position, whatever read it this time — a code other than its own
        #     is another room. A marker is added, hidden with it, so the next
        #     run finds it by marker and Restore brings it back here too.
        spot = min(((math.dist((x, y), (r.x, r.y)), gone) for (pg, x, y, gone) in removed_spots
                    if pg == r.page and not (r.code and gone.space_code and gone.space_code != r.code)),
                   key=lambda z: z[0], default=None)
        if spot is not None and spot[0] <= limit_for(r.page)[0]:
            gone = spot[1]
            hidden = Element(project_id=project.id, drawing_id=drawing.id, page=r.page,
                             kind=gone.kind, label=gone.display_name, x=r.x, y=r.y,
                             origin="extracted", confidence=0.8, confirmed=False,
                             evidence=list(r.evidence) + [
                                 f"{what} is read where {gone.display_name} stood, which was "
                                 f"removed — kept removed; Restore brings it back here too"],
                             detection_method="drawing_room", document_kind="VDB",
                             nearby_text=r.text, ner_asset_id=gone.id,
                             link_status="auto_linked", link_score=1.0)
            db.add(hidden)
            markers.append(hidden)
            if r.source != "symbol":
                this_pass.append((r.page, r.x, r.y, gone, True))
            stats["on_removed_ner"] += 1
            continue

        # 1b. A symbol inside a room this pass already read by its code or
        #     label: the same room, whatever that room became.
        if r.source == "symbol":
            limit, _m = limit_for(r.page)
            near = min(((math.dist((t[1], t[2]), (r.x, r.y)), t) for t in this_pass
                        if t[0] == r.page), key=lambda z: z[0], default=None)
            if near is not None and near[0] <= limit:
                held, removed = near[1][3], near[1][4]
                if removed:
                    stats["on_removed_ner"] += 1
                else:
                    _add_once(held, "classification_evidence", 
                        f"a NER block symbol {near[0] * mpu:.1f} m from it on "
                        f"{sh.label(sh.key(drawing.id, r.page))} — the same room, no second "
                        f"NER created" if mpu else
                        f"a NER block symbol {near[0]:.0f} pt from it — the same room")
                    stats["same_as_marker"] += 1
                continue

        # 2a. The same code is a NER a person removed: the room stays removed.
        #     Its marker is added here too, hidden with it, so Restore brings
        #     the room back on this sheet as well.
        if r.code and r.code not in by_code and r.code in removed_by_code:
            gone = removed_by_code[r.code]
            db.add(Element(project_id=project.id, drawing_id=drawing.id, page=r.page,
                           kind=gone.kind, label=gone.display_name, x=r.x, y=r.y,
                           origin="extracted", confidence=0.8, confirmed=False,
                           evidence=list(r.evidence) + [
                               f"the same code {r.code} is {gone.display_name}, which was "
                               f"removed — kept removed; Restore brings it back here too"],
                           detection_method="drawing_room", document_kind="VDB",
                           nearby_text=r.text, ner_asset_id=gone.id,
                           link_status="auto_linked", link_score=1.0))
            this_pass.append((r.page, r.x, r.y, gone, True))
            stats["on_removed_ner"] += 1
            continue

        # 2. The same code is already a NER — the room drawn on another sheet.
        if r.code and r.code in by_code:
            a = by_code[r.code]
            e = Element(project_id=project.id, drawing_id=drawing.id, page=r.page,
                        kind=a.kind, label=a.display_name, x=r.x, y=r.y,
                        origin="extracted", confidence=0.8, confirmed=False,
                        evidence=list(r.evidence) + [
                            f"the same code {r.code} is {a.display_name} on "
                            f"{sh.label(sh.of_asset(a))} — one room, drawn on both sheets"],
                        detection_method="drawing_room", document_kind="VDB",
                        nearby_text=r.text, ner_asset_id=a.id,
                        link_status="auto_linked", link_score=1.0)
            db.add(e)
            db.flush()
            db.add(NerConsolidation(
                project_id=project.id, primary_asset_id=a.id, merged_asset_id=None,
                decision="merged", method="auto", score=1.0,
                evidence=[f"identical space code {r.code} on "
                          + (f"pages {a.canonical_page} and {r.page}" if not sh.multi else
                             f"{sh.label(sh.of_asset(a))} and {sh.label(sh.key(drawing.id, r.page))}")],
                differences=[],
                undo_snapshot={"occurrence_ids": [e.id], "previous_asset_id": None},
                justification="the same TEC.003 space code printed on two sheets is one room",
                actor=actor))
            markers.append(e)
            this_pass.append((r.page, r.x, r.y, a, False))
            stats["same_code_other_page"] += 1
            continue

        # 3. A new NER — named in sequence (2.14.0): NERc_01.1 … / NER_20.1 …; the
        #    code or the label the sheet printed is kept as "printed as".
        critical = bool(r.critical)
        kind = ElementKind.NER_CRITICAL if critical else ElementKind.NER_NONCRITICAL
        if r.source == "symbol":
            confidence = 0.6
        else:
            confidence = 0.8 if r.code else (0.7 if r.via_leader else 0.55)
        if r.critical is None:
            confidence -= 0.1
        printed = r.code or r.text
        e = Element(project_id=project.id, drawing_id=drawing.id, page=r.page, kind=kind,
                    label=printed, x=r.x, y=r.y, origin="extracted", confidence=confidence,
                    confirmed=False, evidence=list(r.evidence),
                    detection_method="drawing_room", document_kind="VDB",
                    nearby_text=printed, link_status="unlinked")
        db.add(e)
        db.flush()
        # ``_asset_from_element`` names it in sequence and relabels the marker.
        a = MG._asset_from_element(db, e, page_meta, names)
        name = a.display_name
        a.origin = "drawing_room"
        a.space_code = r.code
        a.space_name = r.text
        a.updated_by = actor
        e.ner_asset_id = a.id
        e.link_score = 1.0
        if r.critical is None:
            a.classification = Criticality.PENDING
            a.suggested_classification = Criticality.PENDING
            _add_once(a, "pending_validations", 
                f"criticality: the drawing does not say whether this rack is critical "
                f"('{r.text}') — created as non-critical; choose its criticality")
            stats["criticality_unstated"] += 1
        if r.source == "label" and not r.via_leader:
            _add_once(a, "pending_validations", 
                "position: no arrow could be followed from the label — the NER sits on "
                "the label; drag it onto the room")
            stats["placed_on_label"] += 1
        if r.source == "symbol":
            stats["symbols"] += 1
            twin = next((t for t in placed_symbols if t[0] != r.page
                         and math.dist((t[1], t[2]), (r.x, r.y)) <= 6.0), None)
            if twin is not None:
                _add_once(a, "pending_validations", 
                    f"position: the same NER symbol sits at the same place on "
                    f"{sh.label(sh.key(drawing.id, twin[0]))} "
                    f"({twin[3]}) — one rack shown on two levels, or two racks one above "
                    f"the other? Delete this one if it is the same")
                stats["same_place_other_page"] += 1
            placed_symbols.append((r.page, r.x, r.y, name))
        markers.append(e)
        assets[a.id] = a
        if r.source != "symbol":
            this_pass.append((r.page, r.x, r.y, a, False))
        if code_names_a_room(r.code):
            by_code[r.code] = a
        stats["created"] += 1
        stats["names"].append(name)

    audit(db, project.id, "ner.created_from_drawing", entity="drawing", entity_id=drawing.id,
          actor=actor, payload=stats,
          justification="NER rooms the drawing prints (TEC code, NER room label or NER block symbol)")
    db.commit()
    return stats


def release_key_plan_ties(db: Session, project: Project, *, actor: str = "system") -> dict:
    """Undo every tie between a TEAP line and a room on a key plan.

    A key plan repeats every room of the detail sheets; a TEAP line tied to a
    room there points at the right room on the wrong page (Marcelo, 29 Sep
    2026). The person's own tie is released too — the rule is that key plans
    take part in no crossing — and each release is audited with the room and
    the page it pointed at, so it can be redone on a detail sheet.
    """
    pages = key_plan_pages(db, project.id)
    released_locks: list[dict] = []
    cleared_rows = 0
    if not pages:
        return {"released_decisions": 0, "cleared_matches": 0}
    sh = SH.for_project(db, project.id)
    ids_on_key = {ds.id: ds for ds in db.execute(select(DrawingSpace).where(
        DrawingSpace.project_id == project.id)).scalars() if sh.of(ds) in pages}
    if not ids_on_key:
        return {"released_decisions": 0, "cleared_matches": 0}
    for t in db.execute(select(TeapSpace).where(
            TeapSpace.project_id == project.id,
            TeapSpace.locked_drawing_space_id.in_(list(ids_on_key)))).scalars():
        ds = ids_on_key[t.locked_drawing_space_id]
        released_locks.append({"teap": t.space_code or t.space_name,
                               "room": ds.space_code or ds.name, "page": sh.of(ds),
                               "was_confirmed": bool(t.locked_confirmed)})
        t.locked_verdict = None
        t.locked_drawing_space_id = None
        t.locked_confirmed = False
    for m in db.execute(select(SpaceMatchRow).where(
            SpaceMatchRow.project_id == project.id,
            SpaceMatchRow.drawing_space_id.in_(list(ids_on_key)))).scalars():
        m.drawing_space_id = None
        m.method = "none"
        m.score = 0.0
        m.confidence = 0.0
        m.confirmed = False
        m.confirmed_by = None
        m.reason = "the room was on a key plan — key plans take part in no crossing"
        cleared_rows += 1
    if released_locks or cleared_rows:
        audit(db, project.id, "matching.key_plan_released", actor=actor,
              payload={"released_decisions": released_locks, "cleared_matches": cleared_rows},
              justification="key plans are illustrative — a TEAP line is tied to a room "
                            "on a detail sheet")
    db.flush()
    return {"released_decisions": len(released_locks), "cleared_matches": cleared_rows}


def set_key_plans(db: Session, project: Project, answers: dict[int, bool],
                  *, actor: str = "user") -> dict:
    """The Scale screen's key-plan ticks (2.14.0), several pages in one act.

    A page ticked is a key plan: it only illustrates, its spaces are removed
    (unless a TEAP line is tied to one — then the tie is released first, as
    ``release_key_plan_ties`` does) and it takes part in no crossing. A page
    unticked is a detail sheet again: its spaces are read off the book if it
    has none. The matching runs once at the end, when anything changed and
    there is something to match.
    """
    from pathlib import Path

    from .domain.pdf_ingest import read_page_spaces

    # Keyed by sheet (4.1.0): the answers name sheets, which in a one-book
    # project are the page numbers.
    sh = SH.for_project(db, project.id)
    pages = {sh.key(pg.drawing_id, pg.number): pg for pg in db.execute(
        select(Page).join(Drawing).where(Drawing.project_id == project.id)).scalars()}
    unknown = [n for n in answers if n not in pages]
    if unknown:
        raise ValidationError(f"page(s) not found: {', '.join(map(str, unknown))}")
    changed: list[dict] = []
    for n, on in answers.items():
        pg = pages[n]
        if bool(pg.key_plan) == bool(on) and pg.key_plan_source == "manual":
            continue
        if bool(pg.key_plan) != bool(on):
            changed.append({"page": n, "key_plan": bool(on), "was": bool(pg.key_plan)})
        pg.key_plan = bool(on)
        pg.key_plan_source = "manual"
    out: dict = {"changed": [c["page"] for c in changed], "spaces_removed": 0,
                 "spaces_read": 0, "released_decisions": 0, "cleared_matches": 0}
    if not changed:
        db.commit()
        return out
    audit(db, project.id, "page.key_plans_set", entity="project", entity_id=project.id,
          actor=actor, payload={"changes": changed})
    db.flush()
    out.update(release_key_plan_ties(db, project, actor=actor))
    # Pages that became key plans lose their spaces; pages that stopped being
    # one get theirs read.
    now_key = [c["page"] for c in changed if c["key_plan"]]
    now_detail = [c["page"] for c in changed if not c["key_plan"]]
    if now_key:
        removed = 0
        for sp in db.execute(select(DrawingSpace).where(
                DrawingSpace.project_id == project.id,
                DrawingSpace.origin == "extracted")).scalars():
            if sh.of(sp) not in now_key:
                continue
            db.delete(sp)
            removed += 1
        out["spaces_removed"] = removed
        db.flush()
    if now_detail:
        known = [n for n in db.execute(select(TeapSpace.space_name).where(
            TeapSpace.project_id == project.id)).scalars() if n]
        for d in db.execute(select(Drawing).where(Drawing.project_id == project.id)).scalars():
            mine = [pages[k].number for k in now_detail if pages[k].drawing_id == d.id]
            empty = [n for n in mine if db.execute(select(DrawingSpace.id).where(
                DrawingSpace.drawing_id == d.id, DrawingSpace.page == n).limit(1)).first() is None]
            if not empty or not d.stored_path or not Path(d.stored_path).exists():
                continue
            try:
                found = read_page_spaces(d.stored_path, empty, known_names=known)
            except Exception as exc:  # noqa: BLE001
                out["read_error"] = str(exc)
                continue
            for sp in found:
                db.add(DrawingSpace(project_id=project.id, drawing_id=d.id, page=sp.page,
                                    space_code=sp.space_code, name=sp.name, x=sp.x, y=sp.y,
                                    area_label=sp.area_label, confidence=sp.confidence,
                                    origin="extracted", evidence=sp.evidence))
            out["spaces_read"] += len(found)
        db.flush()
    has_teap = db.execute(select(TeapSpace.id).where(
        TeapSpace.project_id == project.id).limit(1)).first() is not None
    has_spaces = db.execute(select(DrawingSpace.id).where(
        DrawingSpace.project_id == project.id).limit(1)).first() is not None
    if has_teap and has_spaces:
        try:
            out["matching"] = run_matching(db, project)["stats"]
        except ValidationError as exc:
            out["matching_skipped"] = str(exc)
    db.commit()
    return out


def set_key_plan(db: Session, project: Project, page_no: int, key_plan: bool,
                 *, actor: str = "user") -> dict:
    """The person's answer to "is this page a key plan?" — for a title block
    read wrong. Ties to rooms on a page that becomes a key plan are released,
    and the matching is run again either way, so the rooms of a page that
    stops being one are offered again."""
    out = set_key_plans(db, project, {page_no: bool(key_plan)}, actor=actor)
    out.update({"page": page_no, "key_plan": bool(key_plan)})
    return out


def scale_map(db: Session, project_id: int, *, require_confirmed: bool = False
              ) -> dict[int, Scale]:
    """Sheet key -> :class:`Scale` for a project (4.1.0: keyed by sheet, see
    :mod:`app.sheets` — the page number itself in a one-book project)."""
    rows = db.execute(
        select(Page).join(Drawing).where(Drawing.project_id == project_id)
    ).scalars().all()
    sh = SH.for_project(db, project_id)
    out: dict[int, Scale] = {}
    for p in rows:
        if p.metres_per_unit is None:
            continue
        if require_confirmed and not p.scale_confirmed:
            continue
        out[sh.key(p.drawing_id, p.number)] = Scale(metres_per_unit=p.metres_per_unit,
                              source=p.scale_source or "unknown",
                              label=p.scale_label or "", confirmed=p.scale_confirmed)
    return out


# ---------------------------------------------------------------------------
# TEAP
# ---------------------------------------------------------------------------

def profile_teap(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        profiles = [profile_csv(str(path))]
    else:
        profiles = profile_workbook(str(path))
    return [{"sheet": p.name, "header_row": p.header_row, "headers": p.headers,
             "data_rows": p.data_rows, "score": round(p.score, 2),
             "proposed_mapping": p.proposed_mapping} for p in profiles]


#: What a person decided about a TEAP space, as opposed to what the TEAP says
#: about it. These are the columns a re-import carries across.
_DECISION_COLUMNS = (
    "assigned_ner_asset_id", "assignment_reason", "assignment_by", "assignment_at",
    "assigned_cross_level", "locked_drawing_space_id", "locked_verdict",
    "locked_confirmed", "locked_by", "locked_at", "locked_method",
)


def match_rows_for_export(db: Session, project: Project) -> list[dict]:
    """The TEAP × drawing matching as the project holds it, for the workbook.

    One row per TEAP line that requests ports (the study), with the room it
    is tied to, how, and who signed it. Codes tied on more than one page are
    reported so the Match exceptions sheet can list them.
    """
    rows = db.execute(
        select(SpaceMatchRow, TeapSpace, DrawingSpace)
        .join(TeapSpace, TeapSpace.id == SpaceMatchRow.teap_space_id)
        .outerjoin(DrawingSpace, DrawingSpace.id == SpaceMatchRow.drawing_space_id)
        .where(SpaceMatchRow.project_id == project.id)).all()
    sh = SH.for_project(db, project.id)
    pages_by_code: dict[str, set] = {}
    for _m, _t, ds in rows:
        if ds is not None and ds.space_code:
            pages_by_code.setdefault(ds.space_code, set()).add(sh.of(ds))
    out: list[dict] = []
    for m, t, ds in rows:
        if not in_scope(t):
            continue
        out.append({
            "teap_code": t.space_code, "teap_name": t.space_name,
            "drawing_space_id": m.drawing_space_id,
            "drawing_code": ds.space_code if ds is not None else "",
            "drawing_name": ds.name if ds is not None else "",
            "page": sh.of(ds) if ds is not None else None,
            "method": m.method, "score": m.score, "confidence": m.confidence,
            "reason": m.reason, "confirmed": bool(m.confirmed),
            "confirmed_by": m.confirmed_by or ("the matcher" if m.confirmed else ""),
            "rejected": bool(m.rejected), "exception": m.exception,
            "notes": list(m.notes or []),
            "pages_of_code": sorted(pages_by_code.get(ds.space_code, set())) if ds is not None else [],
        })
    out.sort(key=lambda r: (-(float(r.get("score") or 0)), r["teap_code"] or ""))
    return out


def _lift_decisions(db: Session, project: Project) -> dict[str, dict]:
    """Every human decision on this project's TEAP spaces, keyed by ``space_key``.

    Read before a TEAP import replaces the rows. Where two files hold the same
    space (the state the old importer left behind) the row that actually
    carries a decision wins over the one that does not.
    """
    out: dict[str, dict] = {}
    rows = db.execute(select(TeapSpace).where(TeapSpace.project_id == project.id)
                      .order_by(TeapSpace.id)).scalars().all()
    links: dict[int, list[dict]] = {}
    for ln in db.execute(select(SpaceOccurrenceLink).where(
            SpaceOccurrenceLink.project_id == project.id,
            SpaceOccurrenceLink.decided_by.is_not(None))).scalars():
        links.setdefault(ln.teap_space_id, []).append({
            "drawing_space_id": ln.drawing_space_id, "verdict": ln.verdict,
            "method": ln.method, "evidence": list(ln.evidence or []),
            "decided_by": ln.decided_by, "decided_at": ln.decided_at})
    for t in rows:
        cols = {c: getattr(t, c) for c in _DECISION_COLUMNS}
        # A photographer type set by hand is a decision too, even on a row
        # with nothing else decided: it is the stricter limit, and a re-import
        # used to drop it unless the row also carried a room or a NER.
        decided = bool(t.locked_verdict or t.assigned_ner_asset_id or links.get(t.id)
                       or t.demand_type == DemandType.PHOTOGRAPHER.value)
        if not decided:
            continue
        prev = out.get(t.space_key)
        if prev is None or not prev["cols"].get("locked_verdict"):
            out[t.space_key] = {"cols": cols, "links": links.get(t.id, []),
                                "demand_type": t.demand_type}
    return out


def _lay_decisions(db: Session, project: Project, rows: Sequence[TeapSpace],
                   carried: dict[str, dict]) -> int:
    """Put the lifted decisions on the new rows. Returns how many found a row."""
    kept = 0
    for t in rows:
        c = carried.get(t.space_key)
        if c is None:
            continue
        for col, val in c["cols"].items():
            setattr(t, col, val)
        # "photographer" is set by hand on the Demand row when the TEAP does not
        # say it, and it is the stricter limit (70 m): a re-import never loosens it.
        hand_photographer = (c.get("demand_type") == DemandType.PHOTOGRAPHER.value
                             and t.demand_type != DemandType.PHOTOGRAPHER.value)
        if c.get("demand_type") == DemandType.PHOTOGRAPHER.value:
            t.demand_type = DemandType.PHOTOGRAPHER.value
        for ln in c["links"]:
            db.add(SpaceOccurrenceLink(
                project_id=project.id, teap_space_id=t.id,
                drawing_space_id=ln["drawing_space_id"], verdict=ln["verdict"],
                auto=False, method=ln["method"], evidence=ln["evidence"],
                decided_by=ln["decided_by"], decided_at=ln["decided_at"]))
        # Counted only when a person decided something (4.2.0): a photographer
        # type the import itself gave the space (its name says "photo") is not
        # a decision, and counting it said "33 decisions carried" for four.
        cols = c["cols"]
        if (cols.get("locked_verdict") or cols.get("assigned_ner_asset_id") or c["links"]
                or hand_photographer):
            kept += 1
    return kept



def import_teap(db: Session, project: Project, teap: TeapFile,
                progress: Progress = None, *, allow_all_venues: bool = False
                ) -> list[TeapSpace]:
    report = _prog(progress)
    path = Path(teap.stored_path)

    # A master allocation plan covers the whole programme. Importing every venue
    # against one venue's drawings is never intended and is catastrophic in
    # practice: on the reference workbook it produced 5,543 spaces instead of 115
    # and left the optimiser building a model with hundreds of thousands of
    # variables. Refuse it unless the user says so explicitly.
    if path.suffix.lower() != ".csv" and not teap.venue_filter and not allow_all_venues:
        report(0.05, "checking which venues the sheet covers")
        venues = preview_venues(str(path), teap.sheet, teap.header_row, teap.mapping)
        if len(venues) > 1:
            top = ", ".join(f"{v['venue_code'] or v['venue_name']} ({v['rows']:,} rows)"
                            for v in venues[:6])
            raise ValidationError(
                f"this sheet covers {len(venues)} venues ({top}"
                f"{', …' if len(venues) > 6 else ''}). Set a venue filter — the project's "
                f"venue code is {project.venue_code or 'not set'} — or confirm explicitly "
                f"that you want every venue in one project.")

    report(0.15, "reading rows")
    if path.suffix.lower() == ".csv":
        imp = read_csv(str(path), teap.mapping)
    else:
        imp = read_sheet(str(path), teap.sheet, teap.header_row, teap.mapping,
                         venue_filter=teap.venue_filter)
        imp.product_ports = load_product_catalogue(str(path))

    # An import that finds no row must not replace anything (2.12.1). The
    # replacement below deletes every TEAP space of the project first, so a
    # filter that matched nothing — a venue code with no venue column mapped,
    # a typo in the filter, the wrong sheet — used to leave the project with
    # an empty TEAP and every decision on it gone.
    if not imp.rows:
        why = (f"no row matched the venue filter {teap.venue_filter!r}"
               + ("" if (teap.mapping or {}).get("venue_code") or (teap.mapping or {}).get("venue_name")
                  else " (no venue column is mapped)")) if teap.venue_filter else \
            "the sheet has no data row under the header row"
        raise ValidationError(f"nothing to import: {why}. The TEAP already in the project "
                              f"was left as it was.")

    report(0.6, f"computing demand for {len(imp.rows):,} rows")
    rules = DemandRuleSet(**(project.demand_rules or {})) if project.demand_rules \
        else DemandRuleSet()
    demands = compute_demand(imp, rules)
    report(0.8, f"storing {len(demands):,} spaces")

    # **A newer TEAP supersedes the older one** — the TEAP is the document that
    # rules, and there is one of it. Until 17 Sep 2026 only the spaces of *this
    # file* were replaced, so importing v2.3 into a project that already held
    # v2.0 left both sets of spaces side by side: on the OWC project
    # that was 102 + 105 rows for one venue, every port counted twice, and the
    # forty-five decisions made on the v2.0 rows nowhere to be seen on the v2.3
    # ones. Everything a person decided is lifted off the rows about to go and
    # laid back on the rows that replace them, found by the stable
    # ``space_key`` — the promise the ``locked_*`` columns were written for.
    carried = _lift_decisions(db, project)
    db.execute(delete(TeapSpace).where(TeapSpace.project_id == project.id))
    out: list[TeapSpace] = []
    for d in demands:
        row = TeapSpace(
            project_id=project.id, teap_file_id=teap.id, space_key=d.space_key,
            space_code=d.space_code, space_name=d.space_name, venue_code=d.venue_code,
            building=d.building, level=d.level, functional_area=d.functional_area,
            criticality=d.criticality, criticality_confirmed=bool(d.criticality),
            demand_type=d.demand_type.value, total_ports=d.total_ports,
            wireless_required=d.wireless_required,
            teap_serving_ner=d.serving_ner,
            lines=[{"row": l.row_number, "product": l.product_description,
                    "code": l.product_code, "qty": l.quantity, "ports": l.ports,
                    "rule": l.rule, "explanation": l.explanation} for l in d.lines],
            warnings=d.warnings,
        )
        db.add(row)
        out.append(row)
    db.flush()
    kept = _lay_decisions(db, project, out, carried)
    teap.imported_rows = len(imp.rows)
    # Said back to the screen (2.8.1): the import notice names how many
    # earlier decisions the new rows received.
    teap.last_import_decisions_carried = kept
    audit(db, project.id, "teap.imported", entity="teap_file", entity_id=teap.id,
          payload={"rows": len(imp.rows), "spaces": len(out),
                   "venue_filter": teap.venue_filter,
                   "decisions_carried": kept,
                   "decisions_without_a_space": len(set(carried) - {t.space_key for t in out}),
                   "warnings": imp.warnings[:20]})
    db.commit()
    report(1.0, f"{len(imp.rows):,} rows imported into {len(out):,} spaces")
    return out


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def load_aliases(db: Session, project_id: int) -> tuple[dict[str, str], dict[str, str]]:
    """Curated aliases for this project plus the global ones.

    A project-scoped alias overrides a global one with the same key, so a venue
    can differ from the programme-wide convention without editing it.
    """
    rows = db.execute(select(Alias).where(
        (Alias.project_id == project_id) | (Alias.project_id.is_(None))
    ).order_by(Alias.project_id.is_(None).desc())).scalars().all()
    codes: dict[str, str] = {}
    names: dict[str, str] = {}
    for a in rows:
        if a.kind == "code":
            codes[M.normalise_code(a.teap_value) or a.teap_value.strip().upper()] = a.drawing_value
        else:
            names[M.normalise_name(a.teap_value)] = a.drawing_value
    return codes, names


def record_match_decision(db: Session, m: SpaceMatchRow, *,
                          drawing_space_id: Optional[int] = None,
                          clear_room: bool = False,
                          confirmed: Optional[bool] = None,
                          rejected: Optional[bool] = None,
                          actor: str = "user") -> TeapSpace | None:
    """Write one worklist decision to both places it has to be.

    ``space_matches`` is what the screen reads and what the matching step
    rebuilds; ``teap_spaces`` is where the answer has to outlive that rebuild.
    Keeping the two writes in one function is the point — the earlier design
    wrote only the first, from the route, and every re-run quietly reverted it.

    Returns the TEAP space that now carries the decision, so a caller can audit
    it by the code a person would recognise rather than by a row id the database
    is free to recycle.
    """
    t = db.get(TeapSpace, m.teap_space_id)
    now = _dt.datetime.utcnow()

    if clear_room:
        m.drawing_space_id = None
        m.method = "none"
        m.confidence = 0.0
        m.reason = ""
        m.confirmed = False
        m.confirmed_by = None
        if t is not None:
            t.locked_verdict = None
            t.locked_drawing_space_id = None
            t.locked_confirmed = False
            t.locked_by = None
            t.locked_at = now
    elif drawing_space_id is not None:
        # Re-sending the room the row already holds is a re-affirmation, not a
        # fresh hand pick — Confirm does exactly that. Relabelling it "manual"
        # there would erase how the match was actually found.
        if m.drawing_space_id != drawing_space_id:
            m.method = "manual"
            m.confidence = 1.0
            m.reason = "selected by the user"
            # A different room is a new answer: whatever confirmation the old
            # one carried — the matcher's own, on an exact code — does not
            # transfer to it (2.12.1). It showed as confirmed until the next run.
            m.confirmed = False
            m.confirmed_by = None
            if t is not None:
                t.locked_confirmed = False
        m.drawing_space_id = drawing_space_id
        m.rejected = False
        if t is not None:
            t.locked_verdict = "assigned"
            t.locked_drawing_space_id = drawing_space_id
            t.locked_method = m.method or "manual"
            t.locked_by = actor
            t.locked_at = now

    if confirmed is not None:
        m.confirmed = confirmed
        m.confirmed_by = actor if confirmed else None
        if t is not None:
            t.locked_confirmed = bool(confirmed)
            t.locked_at = now
            # Confirming an automatic match is the moment that answer becomes a
            # human decision. Without this it would carry no lock, and the next
            # run would be free to answer it differently.
            if confirmed and not t.locked_verdict and m.drawing_space_id:
                t.locked_verdict = "assigned"
                t.locked_drawing_space_id = m.drawing_space_id
                t.locked_method = m.method or "manual"
                t.locked_by = actor
            if not confirmed:
                t.locked_by = None

    if rejected is not None:
        m.rejected = rejected
        if rejected:
            # "No room on this drawing" is an answer about the room, so the
            # row stops showing one — the same thing a later run lays down
            # from the lock (2.10.0: choosing "— none —" records this).
            m.drawing_space_id = None
            m.method = "none"
            m.confidence = 0.0
            m.reason = "you said this space is not on this drawing"
            m.confirmed = False
            m.confirmed_by = actor
        if t is not None:
            if rejected:
                t.locked_verdict = "rejected"
                t.locked_drawing_space_id = None
                t.locked_confirmed = True
                t.locked_by = actor
            elif t.locked_verdict == "rejected":
                t.locked_verdict = None
                t.locked_confirmed = False
                t.locked_by = None
            t.locked_at = now
    return t


#: Undo on a row no run has refreshed since 2.6.0: the matcher's answer is not
#: on the row yet. Kept static so the interface can translate it.
UNDO_NEEDS_RUN = ("your decision was undone; run the matching to bring the matcher's "
                  "answer back on this row")


def undo_match_decision(db: Session, m: SpaceMatchRow, *, actor: str = "user") -> dict:
    """Take back every decision a person made on one worklist row (2.6.0).

    Marcelo, 21 Sep 2026: *"me permitir desfazer algo é importante, caso eu
    tenha feito errado."* A room chosen by hand, a confirmation, a rejection
    — all of them are one lock on the TEAP space. Undo releases the lock and
    hands the row back to **the matcher's own answer**, exactly as the next
    run would show it: the same room, the same method, and confirmed only if
    the matcher would have confirmed it (an unambiguous exact code). Nothing
    is invented; a row the matcher could not place goes back to *no room*.

    Rows written before 2.6.0 carry no stored answer. Those are released and
    left with no room, and the caller is told to run the matching — the run
    refreshes every undecided row, so the answer comes back on its own.
    """
    t = db.get(TeapSpace, m.teap_space_id)
    before = {"drawing_space_id": m.drawing_space_id, "confirmed": m.confirmed,
              "rejected": m.rejected, "verdict": t.locked_verdict if t else None,
              "confirmed_by": m.confirmed_by}
    if t is not None:
        t.locked_verdict = None
        t.locked_drawing_space_id = None
        t.locked_confirmed = False
        t.locked_by = None
        t.locked_at = _dt.datetime.utcnow()
    restored = m.auto_method is not None
    if restored:
        m.drawing_space_id = m.auto_drawing_space_id
        m.method = m.auto_method
        m.score = m.auto_score
        m.confidence = m.auto_confidence
        m.reason = m.auto_reason
        m.confirmed = bool(m.auto_confirmed and m.auto_drawing_space_id is not None)
    else:
        m.drawing_space_id = None
        m.method = "none"
        m.score = 0.0
        m.confidence = 0.0
        m.reason = ""
        m.confirmed = False
    m.rejected = False
    m.confirmed_by = None
    return {"restored": restored, "before": before,
            "drawing_space_id": m.drawing_space_id, "method": m.method,
            "confirmed": m.confirmed,
            "note": None if restored else UNDO_NEEDS_RUN}


#: Kept static (no counts inside) so the interface can translate it.
NO_SPACE_RECOGNISED = (
    "the drawing was ingested but no space was recognised on it — no space code and no "
    "room-name label was found, so there is nothing to match the TEAP against; "
    "ingest the drawing again on this version, or check that the sheets carry room labels")

#: Every room the drawing carries is on a key plan (2.13.0).
ONLY_KEY_PLAN_SPACES = (
    "every room found on the drawing is on a key plan, and key plans take part in no "
    "TEAP × drawing crossing; if a page was taken for a key plan by mistake, untick "
    "Key plan for it in the Drawing viewer")


def run_matching(db: Session, project: Project, progress: Progress = None, *,
                 actor: str = "user") -> dict:
    say = _prog(progress)
    say(0.05, "loading spaces")
    teap_rows = db.execute(select(TeapSpace).where(TeapSpace.project_id == project.id)
                           ).scalars().all()
    draw_rows = db.execute(select(DrawingSpace)
                           .where(DrawingSpace.project_id == project.id)).scalars().all()
    # A key plan only illustrates (2.13.0): its rooms repeat the detail
    # sheets' and a tie there points at the right room on the wrong page. They
    # are not offered to the matcher at all, and any tie to one is let go.
    key_pages = key_plan_pages(db, project.id)
    sh = SH.for_project(db, project.id)
    all_on_key = False
    if key_pages:
        all_on_key = bool(draw_rows) and all(sh.of(r) in key_pages for r in draw_rows)
        draw_rows = [r for r in draw_rows if sh.of(r) not in key_pages]
        release_key_plan_ties(db, project)
    if not teap_rows:
        raise ValidationError("import a TEAP before running the matching step")
    if not draw_rows:
        # Two different situations used to share one message, and the wrong one
        # was read on the FRG book: the drawing *was* ingested, the extractor
        # simply found no room on it. Say which it is.
        drawings = db.execute(select(Drawing).where(Drawing.project_id == project.id)
                              ).scalars().all()
        if not drawings:
            raise ValidationError("ingest at least one drawing before running the matching step")
        if all_on_key:
            raise ValidationError(ONLY_KEY_PLAN_SPACES)
        raise ValidationError(NO_SPACE_RECOGNISED)


    id_by_obj: dict[int, int] = {}
    detected: list[DetectedSpace] = []
    for r in draw_rows:
        ds = DetectedSpace(space_code=r.space_code, name=r.name, page=sh.of(r),
                           x=r.x, y=r.y, area_label=r.area_label,
                           confidence=r.confidence, evidence=list(r.evidence or []))
        id_by_obj[id(ds)] = r.id
        detected.append(ds)

    st = M.MatchSettings(**(project.match_settings or {})) if project.match_settings \
        else M.MatchSettings()
    st.synonyms = dict(project.synonyms or {})
    st.code_aliases, st.name_aliases = load_aliases(db, project.id)
    # The plot scale tells the matcher which sheet details a room and which merely
    # locates it, which is what resolves a code printed on both a key plan and a
    # level plan without sending it to a human.
    st.page_scale_denominator = {p: sc.denominator
                                 for p, sc in scale_map(db, project.id).items()}

    say(0.4, f"matching {len(teap_rows):,} TEAP spaces against "
             f"{len(draw_rows):,} drawing spaces")
    with SH.naming(sh):
        report = M.match_spaces(
            [(t.space_key, t.space_code, t.space_name, t.building, t.level) for t in teap_rows],
            detected, st,
            demand_by_key={t.space_key: t.total_ports for t in teap_rows})
    say(0.75, "storing results")

    by_key = {t.space_key: t for t in teap_rows}

    # A re-run must not destroy human decisions — and must not need to try.
    #
    # The first version of this deleted every match row and rebuilt from
    # scratch, which threw away every confirmation, every rejection and every
    # room a person had chosen by hand. It reads as "the app is not saving my
    # work" rather than as a wipe, because the rows come straight back wearing
    # the automatic answer. The audit log for 1 September shows what that cost:
    # the same room picked for the same row six times in fifteen minutes.
    #
    # The second version snapshotted the decided rows just before the delete and
    # wrote them back afterwards. Better, but still a preservation — it holds
    # only while nothing disturbs the snapshot, and when it fails it fails
    # silently, in the same shape as the original bug.
    #
    # This version does not preserve anything, because it no longer destroys
    # anything. The human answer lives on the TEAP space (``locked_verdict`` and
    # friends), written at the moment it is given; ``space_matches`` is a
    # *derived* table that this function refreshes in place, row by row, keyed
    # on the TEAP space. Nothing here can clear a decision, because nothing here
    # is where the decision is kept.
    #
    # Refreshing in place rather than delete-and-insert also keeps the row ids
    # stable. SQLite recycles rowids after a bulk delete, so the old code handed
    # each id to a different TEAP line on every run: the screen a reviewer was
    # looking at could patch a row other than the one under the cursor, and the
    # audit trail pointed at whichever line happened to inherit the number.
    existing: dict[int, SpaceMatchRow] = {
        r.teap_space_id: r for r in db.execute(
            select(SpaceMatchRow).where(SpaceMatchRow.project_id == project.id)).scalars()}

    locked = released = 0
    seen: set[int] = set()
    touched: dict[int, SpaceMatchRow] = {}
    for m in list(report.matches) + list(report.unmatched_teap):
        t = by_key.get(m.teap_key)
        if t is None or t.id in seen:
            continue
        seen.add(t.id)
        row = existing.get(t.id)
        if row is None:
            row = SpaceMatchRow(project_id=project.id, teap_space_id=t.id)
            db.add(row)
        touched[t.id] = row

        # The matcher's own answer, which is what an undecided row shows.
        row.exception = m.exception
        row.alternatives = [
            {"drawing_space_id": id_by_obj.get(id(c.drawing_space)),
             "name": c.drawing_space.name, "page": c.drawing_space.page,
             "method": c.method.value, "confidence": round(c.confidence, 3),
             "reason": c.reason} for c in m.alternatives]

        # The matcher's answer is kept on the row whatever the person decided,
        # so ``Undo`` can hand the row back to it without another run (2.6.0).
        row.auto_drawing_space_id = (id_by_obj.get(id(m.best.drawing_space))
                                     if m.best else None)
        row.auto_method = m.best.method.value if m.best else "none"
        row.auto_score = m.best.score if m.best else 0.0
        row.auto_confidence = m.confidence
        row.auto_reason = m.best.reason if m.best else ""
        row.auto_confirmed = bool(m.confirmed)

        verdict = t.locked_verdict
        # A room can disappear under a lock — re-ingesting the drawing sets the
        # foreign key to NULL. That is the one case where a person's answer
        # cannot stand, because it names a room nobody can now look at. It is
        # released back into the queue and counted, never kept and never quietly
        # dropped. A rejection names no room, so it survives regardless.
        if verdict == "assigned" and t.locked_drawing_space_id is None:
            t.locked_verdict = None
            t.locked_confirmed = False
            verdict = None
            released += 1

        if verdict == "assigned":
            row.drawing_space_id = t.locked_drawing_space_id
            row.method = t.locked_method or "manual"
            row.confidence = 1.0
            row.score = 1.0
            row.reason = "you assigned this room"
            row.confirmed = bool(t.locked_confirmed)
            row.rejected = False
            row.confirmed_by = t.locked_by if t.locked_confirmed else None
            locked += 1
        elif verdict == "rejected":
            row.drawing_space_id = None
            row.method = "none"
            row.confidence = 0.0
            row.score = 0.0
            row.reason = "you said this space is not on this drawing"
            row.confirmed = False
            row.rejected = True
            row.confirmed_by = t.locked_by
            locked += 1
        else:
            row.drawing_space_id = (id_by_obj.get(id(m.best.drawing_space))
                                    if m.best else None)
            row.method = m.best.method.value if m.best else "none"
            row.score = m.best.score if m.best else 0.0
            row.confidence = m.confidence
            row.reason = m.best.reason if m.best else ""
            row.confirmed = m.confirmed
            row.rejected = m.rejected
            row.confirmed_by = None
            row.notes = m.notes

    # TEAP lines that no longer exist have no question left to answer.
    for teap_id, row in existing.items():
        if teap_id not in seen:
            db.delete(row)

    stats = report.stats()
    # The figures the screen shows are counted *after* the decisions are laid
    # back over the matcher's answer, not before. The matcher's own tally
    # said "30 need review" on a project whose thirty rows had all been
    # confirmed the day before — every decision had in fact been kept, but
    # a message that repeats the pre-decision count after every run reads as
    # "the app lost my work", which is what Marcelo reported on 3 Sep 2026.
    # ``matcher_needs_review`` keeps the raw number for anyone comparing runs.
    stats["matcher_needs_review"] = stats["needs_review"]
    # Only the spaces the study is about are counted. A TEAP space that asks
    # for no port is still matched — silently, so its room is known if a later
    # TEAP gives it one — but it is nobody's work and is on no tile.
    scope_by_id = {t.id: in_scope(t) for t in teap_rows}
    rows = [r for tid, r in touched.items() if scope_by_id.get(tid, True)]
    stats["teap_spaces"] = len(rows)
    stats["zero_port_hidden"] = len(touched) - len(rows)
    stats["placeholders"] = sum(
        1 for t in teap_rows if scope_by_id.get(t.id, True)
        and M.is_placeholder_code(t.space_code))
    with_room = [r for r in rows if r.drawing_space_id is not None and not r.rejected]
    stats["matched"] = len(with_room)
    # Rows a person declared "not on this drawing" are neither matched nor
    # waiting for a room; they are counted apart so the tiles add up.
    stats["rejected"] = sum(1 for r in rows if r.rejected)
    stats["unmatched_teap"] = len(rows) - len(with_room) - stats["rejected"]
    stats["needs_review"] = sum(1 for r in with_room if not r.confirmed)
    stats["confirmed"] = sum(1 for r in with_room if r.confirmed)
    # Who signed: a person, or the matcher on an unambiguous exact code. The
    # tile that says "confirmed by you" must count only the first (2.6.0).
    stats["confirmed_by_you"] = sum(1 for r in with_room if r.confirmed and r.confirmed_by)
    stats["confirmed_by_matcher"] = stats["confirmed"] - stats["confirmed_by_you"]
    stats["match_rate"] = round(len(with_room) / len(rows), 4) if rows else 0.0
    stats["decisions_kept"] = locked
    if released:
        stats["decisions_released_room_gone"] = released
    # The check runs from the TEAP to the drawing and never back: a room on the
    # drawing that no TEAP line points at is not a finding, so it is neither
    # counted nor listed (Marcelo, 17 Sep 2026).
    stats.pop("unmatched_drawing", None)
    db.flush()
    stats["same_space_other_pages"] = refresh_occurrence_links(db, project)
    audit(db, project.id, "matching.run", actor=actor, payload=stats)
    db.commit()
    say(1.0, f"{stats['matched']:,} matched, "
             f"{stats['needs_review']:,} awaiting validation"
             + (f", {locked:,} of your decision(s) kept" if locked else ""))
    return {"stats": stats}


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def distance_rules(project: Project) -> DistanceRules:
    return DistanceRules(
        general_limit_m=project.general_limit_m,
        photographer_limit_m=project.photographer_limit_m,
        near_limit_ratio=project.near_limit_ratio,
        routing_slack_factor=project.routing_slack_factor,
    )


def _sk(sh: Optional["SH.Sheets"], drawing_id: Optional[int], page: Optional[int]):
    """A row's sheet key — its page number when no :class:`app.sheets.Sheets`
    is given (the callers that predate 4.1.0, and every one-book project)."""
    return page if sh is None else sh.key(drawing_id, page)


def _element_to_ner(e: Element, sh: Optional["SH.Sheets"] = None) -> NER:
    """V1 fallback: build a coverage NER straight from a marker.

    Kept for projects whose migration has not run (and for the unit tests that
    exercise the coverage engine in isolation). Live analysis goes through
    :func:`_asset_to_ner` instead.
    """
    return NER(
        key=f"E{e.id}", label=e.label, kind=e.kind,
        point=Point(e.x, e.y, _sk(sh, e.drawing_id, e.page)),
        critical=(e.kind == ElementKind.NER_CRITICAL),
        total_ports=e.total_ports, used_ports=e.used_ports,
        reserved_ports=e.reserved_ports, locked=e.locked, removable=e.removable,
        movable=e.movable, confidence=e.confidence,
        proposed=(e.origin == "proposed"), notes=[e.notes] if e.notes else [],
    )


#: two positions on one sheet closer than this (PDF points) are one marker
SAME_MARKER_PT = 0.5


def asset_points(a: NerAsset, sh: Optional["SH.Sheets"] = None
                 ) -> tuple[Point, list[Point]]:
    """Where a register room is drawn: the canonical point and every other
    marker of it (3.0.0).

    The canonical point is the room's marker on its canonical page. Until
    3.0.0 a drag on *any* sheet copied that marker's x/y into the canonical
    position while the canonical page stayed put, so a room drawn on two
    sheets ended up at sheet B's coordinates on sheet A: drawn in the wrong
    place on the marked-up PDF, missing from sheet B, and measured from the
    wrong spot (ALA, NERc_04.1, 14 Oct 2026). Reading the marker itself
    makes the answer right whatever the stored canonical says;
    :func:`migrate.repair_canonical_positions` puts the stored value right.
    """
    markers = [e for e in (a.occurrences or [])
               if e.scenario_id is None and e.kind in ("NER_CRITICAL", "NER_NONCRITICAL")]
    canonical = Point(a.canonical_x, a.canonical_y,
                      _sk(sh, a.canonical_drawing_id, a.canonical_page))
    if a.position_source == "occurrence" and markers:
        here = [e for e in markers if SH.on_canonical_sheet(e, a)]
        if here:
            m = min(here, key=lambda e: (e.x - (a.canonical_x or 0)) ** 2
                    + (e.y - (a.canonical_y or 0)) ** 2)
            canonical = Point(m.x, m.y, _sk(sh, m.drawing_id, m.page))
    others: list[Point] = []
    for e in sorted(markers, key=lambda e: (_sk(sh, e.drawing_id, e.page), e.id)):
        q = Point(e.x, e.y, _sk(sh, e.drawing_id, e.page))
        if any(o.page == q.page and abs(o.x - q.x) < SAME_MARKER_PT
               and abs(o.y - q.y) < SAME_MARKER_PT for o in (canonical, *others)):
            continue
        others.append(q)
    return canonical, others


def _asset_to_ner(a: NerAsset, sh: Optional["SH.Sheets"] = None) -> NER:
    """One canonical equipment room as the coverage engine sees it.

    Two deliberate choices:

    * ``critical`` follows the **marker kind**, not the confirmed classification.
      Reading a room's criticality off the drawing is what V1 did, and changing
      it here would silently move coverage numbers under a user who only asked
      for a register. What V2 adds is honesty about it: an unconfirmed
      classification is carried into ``notes`` and reported as a pending
      validation everywhere the room appears.
    * ``key`` is ``A<id>`` — the canonical asset — so a room drawn on four pages
      is one NER in the result rather than four.
    """
    notes = [a.notes] if a.notes else []
    point, others = asset_points(a, sh)
    if not a.classification_confirmed:
        notes.append("criticality read from the drawing and not yet confirmed")
    if a.status == NerStatus.SUGGESTED:
        notes.append("suggested position — not an approved location")
    return NER(
        key=f"A{a.id}", label=a.display_name, kind=a.kind,
        point=point, other_points=others,
        critical=(a.kind == ElementKind.NER_CRITICAL),
        total_ports=a.total_ports, used_ports=a.used_ports,
        reserved_ports=a.reserved_ports, locked=a.locked,
        removable=not a.locked, movable=a.movable, confidence=a.confidence,
        level=a.level, environment=a.environment,
        proposed=(a.status == NerStatus.SUGGESTED), notes=notes,
    )


def ner_info_for_export(db: Session, project: Project) -> dict[str, dict]:
    """What the workbook's NERs sheet needs from the register and the analysis
    does not carry (3.0.0): the room's space code (AAM / VDB) and the notes
    written on the NERs screen, by the room's analysis key ``A<id>``."""
    return {f"A{a.id}": {"space_code": (a.space_code or "").strip(),
                         "notes": (a.notes or "").strip()}
            for a in db.execute(select(NerAsset)
                                .where(NerAsset.project_id == project.id)).scalars()}


def register_ners(db: Session, project: Project, *, include_suggested: bool = False
                  ) -> list[NER]:
    """The equipment rooms an analysis should consider.

    Rejected rooms and rooms consolidated into another are excluded — that is the
    whole point of the register. A project that predates the migration falls back
    to its markers so an old database still analyses.

    A row with no position is excluded whatever its status. A proposal read from
    a comments tracker can name a room the drawing set does not contain yet; it
    is a real requirement and belongs in the register, but it is not a place a
    cable can reach, and letting it through would have the engine measure
    distances to the corner of page one.
    """
    assets = [a for a in db.execute(
        select(NerAsset).where(NerAsset.project_id == project.id)).scalars()
        if a.deleted_at is None and a.merged_into_id is None
        and a.keep_decision != KeepDecision.REJECT
        and a.status != NerStatus.REJECTED
        and a.position_known
        and (include_suggested or a.status != NerStatus.SUGGESTED)]
    sh = SH.for_project(db, project.id)
    if assets:
        return [_asset_to_ner(a, sh) for a in assets]
    return [_element_to_ner(e, sh) for e in db.execute(
        select(Element).where(Element.project_id == project.id,
                              Element.scenario_id.is_(None))).scalars().all()]


def build_route_network(db: Session, project: Project,
                        scales: dict[int, Scale]) -> Optional[RouteNetwork]:
    segs = db.execute(select(RouteSegmentRow)
                      .where(RouteSegmentRow.project_id == project.id)).scalars().all()
    verts = db.execute(select(VerticalLinkRow)
                       .where(VerticalLinkRow.project_id == project.id)).scalars().all()
    if not segs and not verts:
        return None
    sh = SH.for_project(db, project.id)
    return build_network(
        [RouteSegment(Point(s.x0, s.y0, sh.of(s)), Point(s.x1, s.y1, sh.of(s)), sh.of(s),
                      s.kind, s.label) for s in segs],
        [VerticalLink(v.key, Point(v.lower_x, v.lower_y, sh.key(v.lower_drawing_id, v.lower_page)),
                      Point(v.upper_x, v.upper_y, sh.key(v.upper_drawing_id, v.upper_page)),
                      v.length_m, v.kind, v.label) for v in verts],
        scales)


def in_scope(t: TeapSpace) -> bool:
    """Whether the study is about this TEAP space — see :mod:`app.domain.scope`."""
    return teap_scope(t.total_ports, t.lines)[0]


def scope_note(t: TeapSpace) -> Optional[str]:
    return teap_scope(t.total_ports, t.lines)[1]


def _space_area(teap: TeapSpace, ds: DrawingSpace, sh: Optional["SH.Sheets"] = None,
                **meta) -> Area:
    # ``drawing_space_id`` travels in ``meta`` so the viewer can find the room
    # this row was measured from by its id (2.8.0). It used to match the TEAP
    # key's tail against the room code on the sheet, which holds only when
    # the two codes are spelled the same — and the matcher exists precisely
    # because they often are not, so on most rows the overlay found nothing.
    return Area(
        key=teap.space_key, name=teap.space_name, page=_sk(sh, ds.drawing_id, ds.page),
        label_point=Point(ds.x, ds.y, _sk(sh, ds.drawing_id, ds.page)),
        polygon=[tuple(p) for p in (ds.polygon or [])] or None,
        space_code=teap.space_code or ds.space_code,
        level=teap.level, building=teap.building,
        estimated=not bool(ds.polygon), meta={"drawing_space_id": ds.id, **meta},
    )


def collect_areas(db: Session, project: Project
                  ) -> list[tuple[Area, float, DemandType, Optional[bool], bool]]:
    """Every matched TEAP space **in scope**, positioned on the drawing, with its
    demand — plus the wireless points a person drew.

    A TEAP space that requests no port is not here (``domain/scope.py``): there
    is nothing for a NER to serve, so it is neither measured nor reported.

    Each area carries the other confirmed labels of the same space
    (``Area.occurrences``) so the engine can measure from the sheet the serving
    room is actually on, and the unconfirmed ones in ``meta`` so a space that
    comes back unserved can say what it is waiting for.
    """
    rows = db.execute(
        select(TeapSpace, SpaceMatchRow, DrawingSpace)
        .join(SpaceMatchRow, SpaceMatchRow.teap_space_id == TeapSpace.id)
        .outerjoin(DrawingSpace, DrawingSpace.id == SpaceMatchRow.drawing_space_id)
        .where(TeapSpace.project_id == project.id)
    ).all()

    links: dict[int, list[tuple[SpaceOccurrenceLink, DrawingSpace]]] = {}
    for ln, other in db.execute(
            select(SpaceOccurrenceLink, DrawingSpace)
            .join(DrawingSpace, DrawingSpace.id == SpaceOccurrenceLink.drawing_space_id)
            .where(SpaceOccurrenceLink.project_id == project.id,
                   SpaceOccurrenceLink.verdict != "rejected")).all():
        links.setdefault(ln.teap_space_id, []).append((ln, other))

    # The access points tied to each TEAP space — said on the row, never
    # counted: since 4.0.0 the space's DWISA line is its wireless port whether
    # or not its access points are drawn.
    tied: dict[str, int] = {}
    for key, in db.execute(select(Element.space_key).where(
            Element.project_id == project.id, Element.scenario_id.is_(None),
            Element.kind.in_(DEMAND_KINDS), Element.space_key.is_not(None))).all():
        tied[key] = tied.get(key, 0) + 1

    sh = SH.for_project(db, project.id)
    out = []
    for teap, match, ds in rows:
        if ds is None or match.rejected or not in_scope(teap):
            continue
        area = _space_area(teap, ds, sh)
        ports = float(teap.total_ports or 0.0)
        w = wireless_line_ports(teap)
        if w > 0:
            area.meta["teap_wireless_ports"] = w
            area.meta["wireless_points_tied"] = tied.get(teap.space_key, 0)
        proposed: list[Area] = []
        for ln, other in sorted(links.get(teap.id, []), key=lambda t: (sh.of(t[1]), t[1].id)):
            if other.id == ds.id or sh.of(other) == sh.of(ds):
                continue
            basis = ("same space code on the same level" if ln.auto
                     else f"confirmed by {ln.decided_by or 'you'}")
            occ = _space_area(teap, other, sh, link_id=ln.id, link_method=ln.method,
                              link_basis=basis)
            if ln.verdict == "confirmed":
                area.occurrences.append(occ)
            else:
                proposed.append(occ)
        if proposed:
            area.meta["proposed_occurrences"] = proposed
        # Criticality is carried as *data* and reported on; it only constrains
        # an assignment when the project explicitly says so. See
        # ``Project.criticality_enforced`` for why the default is off.
        crit: Optional[bool] = None
        if project.criticality_enforced and teap.criticality_confirmed and teap.criticality:
            crit = str(teap.criticality).strip().lower() in ("critical", "yes", "true",
                                                             "high", "1", "crítico")
        out.append((area, ports,
                    DemandType(teap.demand_type), crit, bool(match.confirmed)))
    out.extend(unplaced_areas(db, project, placed={a[0].key for a in out}))
    out.extend(wireless_point_areas(db, project))
    return out


def unplaced_areas(db: Session, project: Project, *, placed: set[str]
                   ) -> list[tuple[Area, float, DemandType, Optional[bool], bool]]:
    """Every TEAP space **in scope** that has no room on the drawing.

    Not tied to a room by the matcher or by hand, or tied and then rejected
    ("not on this drawing"). Until 2.7.0 these never reached the engine and
    so were counted on no room, absent from the summary and "not analysed"
    in the workbook. They are areas now — with **page 0 and no position**
    (``meta["unplaced"]``), which the engine reads as "nothing to measure":
    served only by a NER a person chooses, pending otherwise, and on the
    list either way.
    """
    rows = db.execute(select(TeapSpace).where(TeapSpace.project_id == project.id)
                      .order_by(TeapSpace.space_key)).scalars().all()
    out = []
    for teap in rows:
        if teap.space_key in placed or not in_scope(teap):
            continue
        ports = float(teap.total_ports or 0.0)
        area = Area(key=teap.space_key, name=teap.space_name, page=0,
                    label_point=Point(0.0, 0.0, 0), polygon=None,
                    space_code=teap.space_code, level=teap.level,
                    building=teap.building, estimated=True,
                    meta={"unplaced": True})
        w = wireless_line_ports(teap)
        if w > 0:
            area.meta["teap_wireless_ports"] = w
        out.append((area, ports, DemandType(teap.demand_type), None, False))
    return out


def wireless_line_ports(teap: TeapSpace) -> float:
    """The ports the TEAP requests for this space's **wireless** lines.

    On the event's TEAP that is the ``DWISA`` line — *Wireless Connection -
    Shared Internet Access (SIA) Wireless LAN* — one port per space, the
    access point's uplink. It is real demand and stays counted until the
    person draws the access points for the space; from then on the drawn
    points carry the wireless ports and this figure is taken off the space
    (Marcelo, 21 Sep 2026: *"5 no desenho + 1 que já estava no TEAP … quando
    de verdade eu só vou usar 5"*). Recognised by the same words the importer
    uses to set ``wireless_required``.
    """
    total = 0.0
    for ln in (teap.lines or []):
        text = " ".join(str(ln.get(k) or "") for k in ("product", "code"))
        if WIRELESS_HINTS.search(text):
            try:
                total += float(ln.get("ports") or 0.0)
            except (TypeError, ValueError):
                continue
    return total


#: Where a TEAP-placed access point lands relative to the room's label: a
#: little below and to the right, so the wireless sign does not sit on the
#: name the sheet prints, and one step further right per extra point.
TEAP_AP_OFFSET = (18.0, 14.0)
#: Column and row pitch of the points of one space — wide enough that the
#: ``AP-n`` tags do not sit on each other in the marked-up PDF.
TEAP_AP_STEP = (32.0, 26.0)
#: A space asking for many points gets them in rows of this many, not one long
#: line across the neighbouring rooms.
TEAP_AP_PER_ROW = 4


def next_wireless_label(db: Session, project_id: int, kind: str) -> str:
    """The next free ``WIFI-n`` of this project — numbered per project, never
    reused within it, whatever placed the earlier ones."""
    from .domain.pdf_ingest import WIRELESS_PREFIX
    import re as _re
    prefix = WIRELESS_PREFIX[kind]
    taken = [e.label for e in db.execute(select(Element).where(
        Element.project_id == project_id, Element.kind == kind)).scalars()]
    n = 1 + max([int(m.group(1)) for m in
                 (_re.fullmatch(_re.escape(prefix) + r"-(\d+)", t or "") for t in taken)
                 if m] or [0])
    return f"{prefix}-{n}"


def ap_quantity(teap: TeapSpace) -> int:
    """How many access points the TEAP states for this space: the quantity on
    its wireless line — ``DWISA`` (*Wireless Connection - Shared Internet
    Access (SIA) Wireless LAN*) on the event's TEAP — the port count when the
    line carries no quantity. Recognised by the same words as
    ``wireless_line_ports``."""
    total = 0.0
    for ln in (teap.lines or []):
        text = " ".join(str(ln.get(k) or "") for k in ("product", "code"))
        if not WIRELESS_HINTS.search(text):
            continue
        raw = ln.get("qty")
        if raw in (None, ""):
            raw = ln.get("ports")
        try:
            total += max(0.0, float(raw or 0.0))
        except (TypeError, ValueError):
            continue
    return int(round(total))


def wifi_points_wanted(teap: TeapSpace) -> int:
    """How many Wi-Fi points the placing step draws for this space (4.3.0):
    **one** when the TEAP states any wireless for it, none otherwise. The point
    marks the space as having Wi-Fi; it is not an access point count — the
    quantity stays on the DWISA line, in the TEAP and in the workbook, and the
    final number of access points comes from the wireless design. Marcelo, 19
    Oct 2026: *"não quero mais associar isso com qtde de AP"*."""
    return 1 if ap_quantity(teap) > 0 else 0


class BusyError(RuntimeError):
    """The same placing step is already running for this project."""


_RUNNING_GUARD = threading.Lock()
_RUNNING: dict[tuple[int, str], threading.Lock] = {}

PLACE_NERS_BUSY = ("Place NERs from the drawing is already running for this project "
                   "— wait for it to finish")
PLACE_APS_BUSY = ("Place Wi-Fi from the TEAP is already running for this project "
                  "— wait for it to finish")


@contextlib.contextmanager
def one_at_a_time(project_id: int, what: str, message: str):
    """Refuse a second run of a placing step while the first is still running
    (4.0.0). A double click on *Place NERs from the drawing* or *Place APs
    from the TEAP* could send two requests that each read "nothing placed yet"
    and each placed everything — the second copy on top of the first. Each step
    is idempotent on its own; this makes it idempotent against itself."""
    with _RUNNING_GUARD:
        lock = _RUNNING.setdefault((project_id, what), threading.Lock())
    if not lock.acquire(blocking=False):
        raise BusyError(message)
    try:
        yield
    finally:
        lock.release()


def place_access_points_from_teap(db: Session, project: Project, *, actor: str = "system"
                                  ) -> dict:
    """The AP placing step: every TEAP space that requests wireless and has its
    room on a drawing gets **exactly** the access points its DWISA line states,
    drawn beside the room's label and tied to the space. Marcelo, 14 Oct 2026:
    *"desenhar nos VDB o AP nos espaços que já sabemos que tem wifi"*; and 16
    Oct 2026: *"o número de AP placed nos desenhos deveria seguir rigorosamente
    esta qtde, e para os lugares não encontrados no VDB, não fazer nada"*.

    The access point is not a TEAP product and adds no port (4.0.0): the
    space's DWISA line is its wireless port, counted on the space's row. The
    drawn point is the position of that AP, for the person to drag to where it
    really goes and for the 90 m check from there.

    Running it again reconciles, never duplicates: a space that already has as
    many tied points as its DWISA quantity is left alone; one with fewer gets
    only the missing ones; one with **more** loses the extra points this step
    placed (newest first) — a point a person drew or tied by hand is never
    removed, only reported. Never on a key plan; a space with no room on any
    sheet gets nothing and stays pending, named in the answer.
    """
    with one_at_a_time(project.id, "aps", PLACE_APS_BUSY):
        return _place_access_points_from_teap(db, project, actor=actor)


def _place_access_points_from_teap(db: Session, project: Project, *, actor: str) -> dict:
    key_pages = key_plan_pages(db, project.id)
    sh = SH.for_project(db, project.id)
    rows = db.execute(
        select(TeapSpace, SpaceMatchRow, DrawingSpace)
        .join(SpaceMatchRow, SpaceMatchRow.teap_space_id == TeapSpace.id)
        .outerjoin(DrawingSpace, DrawingSpace.id == SpaceMatchRow.drawing_space_id)
        .where(TeapSpace.project_id == project.id)
        .order_by(TeapSpace.space_key)
    ).all()
    tied: dict[str, list[Element]] = {}
    for e in db.execute(select(Element).where(
            Element.project_id == project.id, Element.scenario_id.is_(None),
            Element.kind.in_(DEMAND_KINDS), Element.space_key.is_not(None))
            .order_by(Element.id)).scalars():
        tied.setdefault(e.space_key, []).append(e)

    totals = {"spaces_with_wireless": 0, "placed": 0, "spaces_placed": 0,
              "already_had_points": 0, "removed_extra": 0, "extra_by_hand": 0,
              "no_room": 0, "on_key_plan": 0,
              "names": [], "removed_names": [], "unplaced_spaces": []}
    seen: set[str] = set()
    for teap, match, ds in rows:
        if teap.space_key in seen or not in_scope(teap):
            continue
        seen.add(teap.space_key)
        want = wifi_points_wanted(teap)
        have = tied.get(teap.space_key, [])
        if len(have) > want:
            # More points than one per space — placed by a version before
            # 4.3.0 (one per DWISA unit), or a space whose DWISA line went
            # away in a new TEAP. Only what this step placed is taken back,
            # newest first; the oldest — the one most likely dragged into
            # place — stays.
            extra = len(have) - want
            for e in sorted((e for e in have if e.origin == "teap"),
                            key=lambda e: e.id, reverse=True)[:extra]:
                totals["removed_names"].append(e.label)
                db.delete(e)
                extra -= 1
            totals["removed_extra"] += len(have) - want - extra
            totals["extra_by_hand"] += extra
        if want <= 0:
            continue
        totals["spaces_with_wireless"] += 1
        missing = want - len(have)
        if missing <= 0:
            totals["already_had_points"] += 1
            continue
        if ds is None or match.rejected:
            totals["no_room"] += 1
            totals["unplaced_spaces"].append(teap.space_name)
            continue
        if sh.of(ds) in key_pages:
            totals["on_key_plan"] += 1
            continue
        for i in range(len(have), want):
            label = next_wireless_label(db, project.id, ElementKind.WIRELESS)
            e = Element(project_id=project.id, drawing_id=ds.drawing_id, page=ds.page,
                        kind=ElementKind.WIRELESS, label=label,
                        x=ds.x + TEAP_AP_OFFSET[0] + (i % TEAP_AP_PER_ROW) * TEAP_AP_STEP[0],
                        y=ds.y + TEAP_AP_OFFSET[1] + (i // TEAP_AP_PER_ROW) * TEAP_AP_STEP[1],
                        origin="teap", confidence=1.0, confirmed=True,
                        detection_method="teap_wireless", document_kind="TEAP",
                        link_status="unlinked", space_key=teap.space_key,
                        tie_source="teap",
                        evidence=[f"placed from the TEAP: {teap.space_name} has wireless "
                                  f"(DWISA) — one Wi-Fi point per space, not an access "
                                  f"point count — drawn beside the room's label on "
                                  f"{sh.label(sh.of(ds))}"])
            db.add(e)
            db.flush()          # the label sequence reads the rows already added
            totals["names"].append(label)
        totals["placed"] += missing
        totals["spaces_placed"] += 1
    audit(db, project.id, "wireless.placed_from_teap", entity="project", entity_id=project.id,
          actor=actor, payload={k: v for k, v in totals.items()
                                if k not in ("names", "removed_names")}
          | {"names": totals["names"][:200], "removed_names": totals["removed_names"][:200]},
          justification="one Wi-Fi point for every matched space whose TEAP states "
                        "wireless (DWISA), drawn beside the room label, tied to the "
                        "space; not an access point count, no port of its own")
    db.commit()
    return totals


def propose_wireless_tie(db: Session, project: Project, page: int, x: float, y: float
                         ) -> Optional[dict]:
    """The TEAP space a wireless point at ``(x, y)`` on sheet ``page`` (a
    sheet key, 4.1.0 — the page number in a one-book project) most plausibly
    belongs to.

    The nearest room label on the same sheet among the rooms already tied to a
    TEAP line (matched and not rejected), measured from the point to the
    label. When the sheet's scale is known the search stops at the project's
    general limit: an access point farther than a cable could run is not
    serving that room, and tying it would take a wireless port off a space it
    does not serve. A proposal, never a decision — the Inspector shows it and
    lets the person change or clear it; the distance is kept as evidence.
    """
    sh = SH.for_project(db, project.id)
    book, book_page = sh.split(page)
    first = sh.drawing_ids[0] if sh.drawing_ids else None
    rows = db.execute(
        select(TeapSpace, DrawingSpace)
        .join(SpaceMatchRow, SpaceMatchRow.teap_space_id == TeapSpace.id)
        .join(DrawingSpace, DrawingSpace.id == SpaceMatchRow.drawing_space_id)
        .where(TeapSpace.project_id == project.id, DrawingSpace.page == book_page,
               on_book(DrawingSpace.drawing_id, book, first),
               SpaceMatchRow.rejected.is_(False))
    ).all()
    if not rows:
        return None
    scale = scale_map(db, project.id).get(page)
    best: Optional[tuple[float, TeapSpace, DrawingSpace]] = None
    for teap, ds in rows:
        d = ((ds.x - x) ** 2 + (ds.y - y) ** 2) ** 0.5
        if best is None or d < best[0]:
            best = (d, teap, ds)
    d, teap, ds = best
    metres = d * scale.metres_per_unit if scale else None
    if metres is not None and metres > float(project.general_limit_m or 90.0):
        return None
    return {"space_key": teap.space_key, "space_name": teap.space_name,
            "space_code": teap.space_code, "drawing_space_id": ds.id,
            "distance_m": (None if metres is None else round(metres, 1)),
            "distance_units": round(d, 1)}


def wireless_point_key(element_id: int) -> str:
    return f"WP{element_id}"


def wireless_point_areas(db: Session, project: Project
                         ) -> list[tuple[Area, float, DemandType, Optional[bool], bool]]:
    """The wireless points drawn in the viewer, as the engine sees them.

    Each is one position on one page under the **general** limit, measured to
    the NER that reaches it so the 90 m rule is checked where the access point
    really is. It carries **no port** (4.0.0): the port is the TEAP's DWISA
    line of its space, counted on the space's row. Otherwise it goes through
    the same rule as a TEAP space — the NER pinned for its space, else the
    nearest NER within the limit; nothing within the limit lands it on the
    exceptions list. It is where the person put it, so it is not an estimate
    and there is no match to confirm.
    """
    rows = db.execute(
        select(Element).where(Element.project_id == project.id,
                              Element.scenario_id.is_(None),
                              Element.kind.in_(DEMAND_KINDS))
        .order_by(Element.page, Element.id)).scalars().all()
    names = {t.space_key: t.space_name for t in db.execute(
        select(TeapSpace).where(TeapSpace.project_id == project.id)).scalars()}
    sh = SH.for_project(db, project.id)
    rows = sorted(rows, key=lambda e: (sh.of(e), e.id))
    out = []
    for e in rows:
        area = Area(key=wireless_point_key(e.id), name=e.label or f"Wireless point {e.id}",
                    page=sh.of(e), label_point=Point(e.x, e.y, sh.of(e)),
                    estimated=False,
                    meta={"kind": "wireless_point", "element_id": e.id,
                          "ap_kind": WIRELESS_NAME.get(e.kind, "Wi-Fi"),
                          "space_key": e.space_key,
                          "space_name": names.get(e.space_key) if e.space_key else None,
                          "tie_source": e.tie_source})
        out.append((area, WIRELESS_POINT_PORTS, DemandType.GENERAL, None, True))
    return out


# ---------------------------------------------------------------------------
# The same space on more than one page
# ---------------------------------------------------------------------------

def refresh_occurrence_links(db: Session, project: Project) -> dict:
    """Find, for every TEAP space in scope, the other pages that label the same
    room as the one it is tied to — and say how sure that is.

    Runs from the TEAP outward, like everything else: only rooms a TEAP line is
    tied to are looked for. The identity is the **drawing room's** full space
    code (so a line redirected to another room follows that room); a room with
    no code falls back to its normalised name, and a name alone is never more
    than a question.

    * code equal, both pages on the same known level → ``confirmed``, ``auto``;
    * code equal but a level unread on either page, or name-only → ``proposed``;
    * both levels known and different → nothing. Another floor is declared
      with the ``other level`` box, not inferred from a label.

    A verdict a person gave is never touched. Rows the rule made that no longer
    hold (the line was tied to another room, the label went with a re-ingest)
    are removed.
    """
    rows = db.execute(
        select(TeapSpace, SpaceMatchRow, DrawingSpace)
        .join(SpaceMatchRow, SpaceMatchRow.teap_space_id == TeapSpace.id)
        .join(DrawingSpace, DrawingSpace.id == SpaceMatchRow.drawing_space_id)
        .where(TeapSpace.project_id == project.id,
               SpaceMatchRow.rejected.is_(False))).all()
    spaces = db.execute(select(DrawingSpace)
                        .where(DrawingSpace.project_id == project.id)
                        .order_by(DrawingSpace.page, DrawingSpace.id)).scalars().all()
    # A key plan repeats the rooms of the detail sheets; it is never "another
    # page the same room is on" (2.13.0).
    key_pages = key_plan_pages(db, project.id)
    sh = SH.for_project(db, project.id)
    sk = sh.of
    if key_pages:
        spaces = [s_ for s_ in spaces if sk(s_) not in key_pages]
        rows = [r for r in rows if sk(r[2]) not in key_pages]
    # The level of each page, and how it is known: read off the title block, or
    # — weaker — implied by the drawing number when the title block gave none.
    level: dict[int, Optional[str]] = {}
    level_read: dict[int, bool] = {}
    sheet_no: dict[int, str] = {}
    for pg in db.execute(select(Page).join(Drawing)
                         .where(Drawing.project_id == project.id)).scalars():
        read = (pg.level or "").strip().upper() or None
        n = sh.key(pg.drawing_id, pg.number)
        level[n] = read or M.level_from_sheet_number(pg.sheet_number)
        level_read[n] = read is not None
        sheet_no[n] = pg.sheet_number or ""
    synonyms = dict(project.synonyms or {})

    by_code: dict[str, list[DrawingSpace]] = {}
    by_name: dict[str, list[DrawingSpace]] = {}
    for s_ in spaces:
        code = M.normalise_code(s_.space_code)
        if code:
            by_code.setdefault(code, []).append(s_)
        else:
            name = M.normalise_name(s_.name, synonyms)
            if name:
                by_name.setdefault(name, []).append(s_)

    existing: dict[tuple[int, int], SpaceOccurrenceLink] = {
        (ln.teap_space_id, ln.drawing_space_id): ln for ln in db.execute(
            select(SpaceOccurrenceLink).where(
                SpaceOccurrenceLink.project_id == project.id)).scalars()}
    wanted: set[tuple[int, int]] = set()
    stats = {"confirmed_by_rule": 0, "proposed": 0, "kept_yours": 0}

    for teap, _match, primary in rows:
        if not in_scope(teap):
            continue
        code = M.normalise_code(primary.space_code)
        if code:
            pool, method = by_code.get(code, []), "exact_code"
        else:
            pool = by_name.get(M.normalise_name(primary.name, synonyms), [])
            method = "name"
        # One label per other page: the one carrying the room's area figure is
        # the real room label, the same preference the matcher uses.
        per_page: dict[int, DrawingSpace] = {}
        for o in pool:
            if o.id == primary.id or sk(o) == sk(primary):
                continue
            cur = per_page.get(sk(o))
            if cur is None or (o.area_label and not cur.area_label):
                per_page[sk(o)] = o
        for page, other in per_page.items():
            lp, lo = level.get(sk(primary)), level.get(page)
            if lp and lo and lp != lo:
                continue                      # another floor — never inferred
            key = (teap.id, other.id)
            wanted.add(key)
            same_level = bool(lp and lo and lp == lo)
            both_read = level_read.get(sk(primary), False) and level_read.get(page, False)
            verdict = ("confirmed" if (method == "exact_code" and same_level and both_read)
                       else "proposed")
            label = primary.space_code or primary.name
            evidence = [
                (f"space code {label} is printed on {sh.label(sk(primary))} and on {sh.label(page)}"
                 if method == "exact_code" else
                 f"the name '{primary.name}' is on {sh.label(sk(primary))} and on {sh.label(page)}, "
                 f"with no space code on either — a name alone is not proof"),
                (f"both pages are {lp}" if same_level and both_read else
                 "; ".join(
                     f"{sh.label(n)}: " + (
                         f"{level[n]} (title block)" if level_read.get(n) else
                         f"{level[n]} — implied by the drawing number {sheet_no.get(n)}, "
                         f"the title block gave no level" if level.get(n) else
                         "level not read")
                     for n in (sk(primary), page))
                 + (" — the same level, but not read off both sheets: yours to confirm"
                    if same_level else " — not enough to be sure")),
            ]
            basis = ("title_block" if same_level and both_read else
                     "drawing_number" if same_level else "unknown")
            ln = existing.get(key)
            if ln is None:
                db.add(SpaceOccurrenceLink(
                    project_id=project.id, teap_space_id=teap.id,
                    drawing_space_id=other.id, verdict=verdict, auto=True,
                    method=method, evidence=evidence, level_basis=basis))
            elif ln.decided_by:
                ln.evidence, ln.level_basis = evidence, basis      # the facts, not the verdict
                stats["kept_yours"] += 1
                continue
            else:
                ln.verdict, ln.method, ln.evidence, ln.auto = verdict, method, evidence, True
                ln.level_basis = basis
            stats["confirmed_by_rule" if verdict == "confirmed" else "proposed"] += 1

    # What is left over. A row the rule made and no longer makes goes. A row a
    # person decided stays for as long as it is still about the room this line
    # is tied to — a level read later off a title block does not overrule
    # someone who looked at the sheet — and goes once the line is tied elsewhere.
    def identity(d: DrawingSpace) -> str:
        return M.normalise_code(d.space_code) or "name:" + M.normalise_name(d.name, synonyms)

    primary_of = {teap.id: primary for teap, _m, primary in rows}
    by_id = {d.id: d for d in spaces}
    for key, ln in existing.items():
        if key in wanted:
            continue
        primary, other = primary_of.get(ln.teap_space_id), by_id.get(ln.drawing_space_id)
        still_about_it = (ln.decided_by and primary is not None and other is not None
                          and sk(other) != sk(primary)
                          and identity(other) == identity(primary))
        if still_about_it:
            stats["kept_yours"] += 1
        else:
            db.delete(ln)
    db.flush()
    return stats


def resolve_teap_ner_names(db: Session, project: Project) -> dict[str, Optional[int]]:
    """TEAP-named NER → register row, by name, for every space the TEAP names one.

    Keyed by the space key; the value is the asset id, or ``None`` when no live
    NER in the register answers to that name. Matching goes through
    ``normalise_label`` so "NER 03" finds "NER 3", and a name a room used to
    have (an alias, or the label the drawing printed) still resolves after a
    rename — the TEAP does not follow the register's renames, and a fixed
    choice that silently stopped applying would be worse than none.
    """
    from .domain.consolidation import normalise_label

    rows = db.execute(select(TeapSpace).where(
        TeapSpace.project_id == project.id,
        TeapSpace.teap_serving_ner.is_not(None))).scalars().all()
    if not rows:
        return {}
    by_name: dict[str, int] = {}
    for a in db.execute(select(NerAsset).where(
            NerAsset.project_id == project.id)).scalars():
        if (a.deleted_at is not None
                or a.merged_into_id is not None
                or a.keep_decision == KeepDecision.REJECT
                or a.status == NerStatus.REJECTED
                or a.kind not in SERVING_KINDS):
            continue
        for name in [a.display_name, a.suggested_name, *(a.aliases or [])]:
            key = normalise_label(name or "")
            if key and key not in by_name:
                by_name[key] = a.id
    return {r.space_key: by_name.get(normalise_label(r.teap_serving_ner or ""))
            for r in rows if (r.teap_serving_ner or "").strip()}


def pin_map(db: Session, project: Project
            ) -> tuple[dict[str, str], dict[str, str]]:
    """Space key → NER key for every space whose room is fixed, plus who fixed it.

    Two sources, in the order Marcelo set: the TEAP first ("se está no TEAP,
    não existe dúvida"), then a person's choice on the Demand screen. A
    person's choice still wins over the TEAP when both exist — the person is
    looking at the drawing and the TEAP is not — but the row says which one it
    used. The second dict carries that provenance: ``"you"`` or ``"the TEAP"``.
    """
    pins: dict[str, str] = {}
    sources: dict[str, str] = {}
    for key, asset_id in resolve_teap_ner_names(db, project).items():
        if asset_id is not None:
            pins[key] = f"A{asset_id}"
            sources[key] = "the TEAP"
    rows = db.execute(select(TeapSpace).where(
        TeapSpace.project_id == project.id,
        TeapSpace.assigned_ner_asset_id.is_not(None))).scalars().all()
    for r in rows:
        pins[r.space_key] = f"A{r.assigned_ner_asset_id}"
        sources[r.space_key] = "you"
    # Wireless points (2.11.0, Marcelo 24 Sep 2026: "já que eu associei NER
    # para os espaços… pq ao colocar AP nas mesmas salas a mesma NER não foi
    # atribuída"). A NER chosen for the point itself comes first; otherwise a
    # point tied to a TEAP space whose room is fixed — by a person or by the
    # TEAP — is served by that same room; otherwise the rule, as before.
    from .domain.pdf_ingest import DEMAND_KINDS
    for e in db.execute(select(Element).where(
            Element.project_id == project.id, Element.scenario_id.is_(None),
            Element.kind.in_(DEMAND_KINDS))).scalars():
        k = wireless_point_key(e.id)
        if e.assigned_ner_asset_id:
            pins[k] = f"A{e.assigned_ner_asset_id}"
            sources[k] = "you"
        elif e.space_key and e.space_key in pins:
            pins[k] = pins[e.space_key]
            sources[k] = "the space"
    return pins, sources


def cross_level_declarations(db: Session, project: Project) -> set[str]:
    """Space keys whose person ticked ``other level`` on the Demand row.

    The declaration that the room they chose sits on another level than the
    space — the one statement that lets the engine honour a pin to a room on
    another page when no vertical route is registered. It is stored on the
    TEAP space beside the assignment, and cleared whenever the assignment
    changes, so it can never outlive the room it was said about.
    """
    rows = db.execute(select(TeapSpace.space_key).where(
        TeapSpace.project_id == project.id,
        TeapSpace.assigned_ner_asset_id.is_not(None),
        TeapSpace.assigned_cross_level.is_(True))).scalars().all()
    return set(rows)


def pinned_assignments(db: Session, project: Project) -> dict[str, str]:
    """Space key -> NER key, for every space whose room is fixed.

    A person's choice on the Demand screen, or the NER the TEAP names when the
    imported sheet carries that column. Returned separately from
    ``collect_areas`` rather than folded into its tuple: that tuple is
    consumed in several places, and widening it to carry one more field would
    have meant touching all of them for no gain.
    """
    return pin_map(db, project)[0]


def rooms_to_draw(db: Session, project: Project,
                  already: Sequence[NER] = ()) -> list[NER]:
    """Every room a drawing should show, on top of the ones the analysis used.

    The marked-up PDF used to draw exactly what the coverage engine counted, and
    that is not the same set. A proposal — read from a comments tracker, or put
    up by the solver — is deliberately kept out of the As-Is numbers, because it
    is not an approved room and letting it serve spaces would inflate the study.
    But keeping it out of the *picture* is a different decision, and the wrong
    one: the whole point of asking for a marked-up VDB with proposals on it is
    to see them on the sheet and argue about them.

    So the two questions are separated. What the engine counts stays exactly as
    it was. What the exporter draws is that, plus every other positioned room in
    the register, flagged ``proposed`` so it comes out dashed and in the
    proposal colour rather than passing itself off as built.

    Rooms with no position are not here. There is nowhere to draw them, and a
    marker invented for the sake of completeness is a lie on a construction
    document.
    """
    seen = {n.key for n in already}
    sh = SH.for_project(db, project.id)
    out: list[NER] = []
    for a in db.execute(select(NerAsset)
                        .where(NerAsset.project_id == project.id)).scalars():
        if a.deleted_at is not None or a.merged_into_id is not None:
            continue
        if a.keep_decision == KeepDecision.REJECT or a.status == NerStatus.REJECTED:
            continue
        if not a.position_known or f"A{a.id}" in seen:
            continue
        out.append(_asset_to_ner(a, sh))
    return out


def markers_to_draw(db: Session, project: Project) -> list[NER]:
    """The visual-only markers — every TER, IDF, COW and DIVA node on the plan,
    and (2.7.0) every NER reference drawn on a key plan.

    The exporter used to draw only the register, and the register holds NERs,
    so a TER read off the sheet on import — or placed by hand in the viewer —
    was on the screen and missing from the paper, while the paper's legend
    still had a row for it. These come out exactly as the viewer shows them:
    filled in their kind colour, ringed in black, named. None of them is in
    ``SERVING_KINDS``, so the exporter draws no reach circle around any of them
    and the coverage figures never see them.
    """
    from .domain.pdf_ingest import REFERENCE_KINDS, VISUAL_ONLY_KINDS

    rows = db.execute(
        select(Element).where(Element.project_id == project.id,
                              Element.scenario_id.is_(None),
                              Element.kind.in_(list(VISUAL_ONLY_KINDS) + list(REFERENCE_KINDS)))
        .order_by(Element.page, Element.id)).scalars().all()
    sh = SH.for_project(db, project.id)
    return [_element_to_ner(e, sh) for e in sorted(rows, key=lambda e: (sh.of(e), e.id))]


def areas_to_draw(db: Session, project: Project) -> list[dict]:
    """The named areas a person drew on the sheets (2.8.0): ``Zone`` rows of
    kind ``area`` — "BTOC", "TER", a compound — as ``{page, label, polygon}``
    for the exporter. Illustrative, and part of no figure."""
    rows = db.execute(select(Zone).where(Zone.project_id == project.id,
                                         Zone.kind == "area")
                      .order_by(Zone.page, Zone.id)).scalars().all()
    sh = SH.for_project(db, project.id)
    return [{"id": z.id, "page": sh.of(z), "label": z.label, "polygon": z.polygon}
            for z in sorted(rows, key=lambda z: (sh.of(z), z.id))]


def fibre_rule(project: Project) -> tuple[int, int]:
    """``(runs per critical NER, runs per non-critical NER)`` — the fibre
    runs from the TER the workbook counts per room (2.8.0). Defaults 2 / 1;
    a project setting."""
    c = project.fibre_runs_critical
    n = project.fibre_runs_noncritical
    return (2 if c is None else int(c), 1 if n is None else int(n))


def analyse(db: Session, project: Project, *, scenario_name: str = "As-Is",
            require_confirmed_scale: bool = False,
            progress: Progress = None) -> tuple[CoverageResult, list[NER]]:
    say = _prog(progress)
    say(0.1, "loading scales, equipment rooms and matched spaces")
    scales = scale_map(db, project.id, require_confirmed=require_confirmed_scale)
    ners = register_ners(db, project)
    # Cheap, and it keeps the "same space on other pages" ties in step with
    # whatever was re-ingested or re-tied since the last matching run.
    refresh_occurrence_links(db, project)
    db.commit()
    areas = collect_areas(db, project)
    if not areas:
        # Since 2.7.0 a TEAP space with no room on the drawing is an area too
        # (pending, or served by a NER a person chose), so this fires only
        # with no TEAP space in scope at all.
        raise ValidationError("no TEAP space to analyse — import a TEAP that requests "
                              "network ports first")
    net = build_route_network(db, project, scales)
    say(0.4, f"evaluating {len(areas):,} spaces against {len(ners):,} equipment rooms")
    pins, pin_sources = pin_map(db, project)
    # Every "on page N" the engine writes names the sheet (4.1.0): the drawing
    # number in a project with several books, "page N" as before otherwise.
    with SH.naming(SH.for_project(db, project.id)):
        result = compute_coverage(areas=areas, ners=ners, scale_for_page=scales,
                                  rules=distance_rules(project), network=net,
                                  pinned=pins, pin_sources=pin_sources,
                                  cross_level=cross_level_declarations(db, project))
    say(1.0, f"{result.summary()['served']:,} of {len(areas):,} within limits")
    return result, ners


class _StoredEvaluation:
    """Just enough of a distance evaluation to redraw a saved scenario."""

    def __init__(self, data: Optional[dict]):
        data = data or {}
        self.effective_distance_m = data.get("effective_distance_m")
        self.geometric_distance_m = data.get("geometric_distance_m")
        self.limit_m = data.get("limit_m")
        self.margin_m = data.get("margin_m")
        self.scale_label = data.get("scale_label", "")
        self.scale_confirmed = bool(data.get("scale_confirmed"))
        self.assumptions = data.get("assumptions", [])
        self.warnings = data.get("warnings", [])
        self.requires_human_validation = bool(data.get("requires_human_validation"))
        self.farthest_point_distance_m = data.get("farthest_point_distance_m")
        self.method = type("M", (), {"value": data.get("method", "")})()


# ``_optimisation_view`` drew what the solver proposed, from what the solver
# recorded. Removed with the solver itself.


def scenario_view(db: Session, project: Project, name: str
                  ) -> Optional[tuple[CoverageResult, list[NER]]]:
    """Replay a saved scenario as something the exporters can draw.

    A scenario is a snapshot: the assignments and the equipment rooms as they
    stood when it was saved, proposed rooms included, each with the position it
    was proposed at. Until now the exporters ignored all of that and re-analysed
    the live project, so asking for the Proposed drawing produced the As-Is
    drawing with a different word in the legend — the two exports were
    byte-identical apart from the title, which is why comparing them showed
    nothing.

    Geometry is the one thing the snapshot does not carry: assignments record
    which space, not where it sits. So the spaces are looked up from the
    drawing as it is now and joined by key. A space that has since been
    unmatched or removed simply drops out of the drawing, and the caller is
    told how many did, rather than the export inventing a position for it.

    Returns ``None`` when no scenario of that name exists, so the caller can
    fall back to a live analysis.
    """
    row = db.execute(select(Scenario).where(Scenario.project_id == project.id,
                                            Scenario.name == name)).scalar_one_or_none()
    if row is None or not isinstance(row.result, dict):
        return None
    payload = row.result
    areas = {a[0].key: a for a in collect_areas(db, project)}

    # A scenario written by the old optimiser stores a different shape
    # (``{"optimisation": ...}``) and no longer has a reader. It is treated as
    # having nothing to draw, which is what it is now, rather than being
    # silently redrawn as the live state.
    if "optimisation" in payload and not payload.get("ners"):
        return None

    if not payload.get("ners") and not payload.get("assignments"):
        return None

    ners: list[NER] = []
    for n in payload.get("ners", []):
        point = Point(float(n["x"]), float(n["y"]), int(n["page"]))
        others = [Point(float(o["x"]), float(o["y"]), int(o["page"]))
                  for o in n.get("other") or []]
        if "other" not in n and str(n["key"]).startswith("A") and str(n["key"])[1:].isdigit():
            # Saved before 3.0.0: the snapshot kept one point per room. Where
            # the room is still in the register, draw it where its markers are
            # now — the old canonical point could carry another sheet's
            # coordinates (see :func:`asset_points`).
            asset = db.get(NerAsset, int(str(n["key"])[1:]))
            if asset is not None and asset.position_known:
                point, others = asset_points(asset)
        ners.append(NER(
            key=n["key"], label=n.get("label", n["key"]), kind=n.get("kind", ""),
            point=point, other_points=others,
            critical=bool(n.get("critical")), total_ports=n.get("total_ports"),
            proposed=bool(n.get("proposed"))))

    assignments: list[Assignment] = []
    dropped: list[str] = []
    for a in payload.get("assignments", []):
        entry = areas.get(a.get("space_key"))
        if entry is None:
            dropped.append(a.get("space_key", "?"))
            continue
        area = entry[0]
        try:
            status = Status(a.get("status"))
        except ValueError:
            status = Status.NOT_ANALYSABLE
        try:
            demand = DemandType(a.get("demand_type"))
        except ValueError:
            demand = DemandType.GENERAL
        # The ports are read from the project as it is now (4.0.0), not from
        # the snapshot: a run saved before 4.0.0 counted a drawn access point
        # as a port and took the DWISA line off its space, and a TEAP imported
        # since may have changed a line. The snapshot keeps what it is for —
        # which NER serves which space — and every sheet counts the same ports.
        assignments.append(Assignment(
            space_key=a["space_key"], space_name=a.get("space_name", ""), area=area,
            demand_type=demand, ports_required=float(entry[1] or 0.0),
            ner_key=a.get("ner_key"), ner_label=a.get("ner_label"),
            ner_critical=a.get("ner_critical"),
            evaluation=_StoredEvaluation(a.get("evaluation")),
            status=status, match_confirmed=bool(a.get("match_confirmed")),
            reasons=list(a.get("reasons") or []), pinned=bool(a.get("pinned")),
            ner_page=a.get("ner_page"), cross_level=bool(a.get("cross_level")),
            measured_page=a.get("measured_page"),
            occurrence_hint=a.get("occurrence_hint"),
            kind=str(a.get("kind") or "space")))

    result = CoverageResult(assignments=assignments,
                            ner_load=_reload_ports(payload.get("ner_load") or {}, assignments),
                            exceptions=list(payload.get("exceptions") or []),
                            uncovered=list(payload.get("uncovered") or []))
    if dropped:
        result.exceptions = list(result.exceptions) + [{
            "space_key": k, "space_name": "", "page": 0,
            "status": "not_on_the_drawing_any_more",
            "detail": ("this space was in the saved scenario but is no longer "
                       "matched to the drawing, so it could not be positioned"),
        } for k in dropped]
    return result, ners


def _reload_ports(load: dict, assignments: Sequence[Assignment]) -> dict:
    """A saved run's per-NER load with its port figures summed again from the
    assignments (4.0.0) — so the NERs sheet, the Summary and Coverage figures
    of an export drawn from a snapshot add up to the same numbers."""
    out = {k: {**v, "assigned_ports": 0.0, "wireless_ports": 0.0, "wireless_points": 0,
               "spaces": []} for k, v in load.items()}
    for a in assignments:
        info = out.get(a.ner_key or "")
        if info is None:
            continue
        info["assigned_ports"] += a.ports_required
        if a.kind == "wireless_point" or a.area.meta.get("kind") == "wireless_point":
            info["wireless_points"] += 1
        else:
            info["spaces"].append(a.space_key)
            info["wireless_ports"] += float(a.area.meta.get("teap_wireless_ports") or 0)
    for info in out.values():
        total = info.get("total_ports")
        info["utilisation_pct"] = (round(100.0 * info["assigned_ports"] / total, 1)
                                   if total else None)
    return out


#: Audit actions that change nothing an analysis reads: an analysis saved
#: before them is still current (4.2.0).
_ANALYSIS_NEUTRAL = {
    "report.generated", "scenario.saved", "project.visibility", "teap.uploaded",
    "upload.path_rebased", "ner.locked", "zone.created", "zone.updated", "zone.deleted",
    "matching.decisions_made_durable", "report.analysis_refreshed",
}


def analysis_stale(db: Session, project: Project, scenario: str = "As-Is") -> Optional[dict]:
    """Whether something changed since the saved analysis was run (4.2.0).

    The exports read the saved analysis; until 4.1.0 a NER deleted after the
    last run still came out on *NERs and ports* with its ports, and nothing
    said so. ``None`` when the analysis is current (or there is none);
    otherwise when it ran and how many changes came after it.
    """
    sc = db.execute(select(Scenario).where(Scenario.project_id == project.id,
                                           Scenario.name == scenario)).scalar_one_or_none()
    if sc is None:
        return None
    last = db.execute(select(func.max(AuditLog.at)).where(
        AuditLog.project_id == project.id, AuditLog.action == "scenario.saved",
        AuditLog.entity_id == sc.id)).scalar()
    if last is None:
        # Until 4.1.0 a scenario's first save was audited without its id.
        last = db.execute(select(func.max(AuditLog.at)).where(
            AuditLog.project_id == project.id, AuditLog.action == "scenario.saved",
            AuditLog.entity_id.is_(None))).scalar()
    if last is None:
        return None
    later = [a.action for a in db.execute(select(AuditLog).where(
        AuditLog.project_id == project.id, AuditLog.at > last)).scalars()
        if a.action not in _ANALYSIS_NEUTRAL and not a.action.startswith("user.")]
    if not later:
        return None
    return {"since": last.isoformat(), "changes": len(later),
            "kinds": sorted(set(later))[:10]}


def save_scenario(db: Session, project: Project, name: str, kind: str,
                  result: CoverageResult, ners: list[NER], *,
                  description: str = "", actor: str = "user",
                  extra: Optional[dict] = None) -> Scenario:
    existing = db.execute(select(Scenario).where(Scenario.project_id == project.id,
                                                 Scenario.name == name)).scalar_one_or_none()
    payload = {
        "assignments": [a.to_dict() for a in result.assignments],
        "ner_load": result.ner_load,
        "exceptions": result.exceptions,
        "uncovered": result.uncovered,
        "ners": [{"key": n.key, "label": n.label, "kind": n.kind, "page": n.point.page,
                  "x": n.point.x, "y": n.point.y, "critical": n.critical,
                  "proposed": n.proposed, "total_ports": n.total_ports,
                  "other": [{"page": q.page, "x": q.x, "y": q.y}
                            for q in getattr(n, "other_points", None) or []]}
                 for n in ners],
        **(extra or {}),
    }
    if existing:
        existing.result = payload
        existing.summary = result.summary()
        existing.description = description or existing.description
        sc = existing
    else:
        sc = Scenario(project_id=project.id, name=name, kind=kind,
                      description=description, created_by=actor,
                      result=payload, summary=result.summary())
        db.add(sc)
        db.flush()   # 4.2.0: the audit names the scenario by id from the first save
    audit(db, project.id, "scenario.saved", entity="scenario", entity_id=sc.id,
          actor=actor, justification=description, payload=result.summary())
    db.commit()
    return sc


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------

# ``run_optimisation`` stood here.

def redundancy(db: Session, project: Project, result: CoverageResult,
               ners: list[NER]) -> list[dict]:
    return redundancy_candidates(result, ners, distance_rules(project))


# ---------------------------------------------------------------------------
# The figures: how much of the TEAP is placed, served, pending
# ---------------------------------------------------------------------------

def coverage_figures(db: Session, project: Project, result: CoverageResult
                     ) -> list[dict]:
    """The percentages Marcelo asked for on 22 Sep 2026: how many TEAP spaces
    were found on the drawing, how many were not, how many were tied by hand,
    how many are served, how many are still pending — as counts and as a
    share of the spaces in the study.

    One flat list of rows ``{section, label, count, of, share, note}`` so the
    workbook sheet, the Demand screen and a test all read the same numbers.
    ``of`` is the denominator (``None`` for a heading row); ``share`` is
    ``count / of`` or ``None``. Counts come from the database as it stands
    (the rooms tied now) and from ``result`` (the run being reported), which
    is the same split the Demand screen makes.
    """
    from .domain.distance import (GROUP_LABEL, PENDING_NO_ROOM, STATUS_LABEL, Group,
                                  group_of)
    from .domain.pdf_ingest import DEMAND_KINDS

    every = db.execute(select(TeapSpace).where(TeapSpace.project_id == project.id)
                       ).scalars().all()
    scope = [t for t in every if in_scope(t)]
    n_all, n_scope = len(every), len(scope)
    scope_keys = {t.space_key for t in scope}

    # The room each TEAP line is tied to, from the match rows: found / not
    # found / rejected, and who tied it.
    matched: dict[int, SpaceMatchRow] = {}
    for m in db.execute(select(SpaceMatchRow).where(
            SpaceMatchRow.project_id == project.id)).scalars():
        matched.setdefault(m.teap_space_id, m)
    found = [t for t in scope if (m := matched.get(t.id)) is not None
             and m.drawing_space_id is not None and not m.rejected]
    rejected = [t for t in scope if (m := matched.get(t.id)) is not None and m.rejected]
    by_hand = [t for t in found if matched[t.id].method == "manual"
               or t.locked_method == "manual" and t.locked_verdict == "assigned"]
    confirmed_by_you = [t for t in found if matched[t.id].confirmed
                        and matched[t.id].confirmed_by]
    confirmed_by_matcher = [t for t in found if matched[t.id].confirmed
                            and not matched[t.id].confirmed_by]
    not_confirmed = [t for t in found if not matched[t.id].confirmed]
    not_found = [t for t in scope if t not in found]
    chosen_unplaced = [t for t in not_found if t.assigned_ner_asset_id]

    spaces = [a for a in result.assignments if a.kind != "wireless_point"
              and a.space_key in scope_keys]
    #: status words -> count; "no room on the drawing" is told apart from
    #: "no NER reaches it", which share the engine status.
    by_reason: dict[Group, dict[str, int]] = {}
    by_group: dict[Group, int] = {}
    for a in spaces:
        g = group_of(a.status.value)
        by_group[g] = by_group.get(g, 0) + 1
        reason = (PENDING_NO_ROOM if a.unplaced and a.ner_key is None
                  else STATUS_LABEL[a.status])
        by_reason.setdefault(g, {})
        by_reason[g][reason] = by_reason[g].get(reason, 0) + 1
    analysed_keys = {a.space_key for a in spaces}
    never_analysed = [t for t in scope if t.space_key not in analysed_keys]

    ports_total = sum(float(t.total_ports or 0.0) for t in scope)
    ports_on_ner = sum(a.ports_required for a in spaces if a.ner_key)
    ports_pending = sum(a.ports_required for a in spaces if not a.ner_key) \
        + sum(float(t.total_ports or 0.0) for t in never_analysed)

    live = [a for a in db.execute(select(NerAsset).where(
        NerAsset.project_id == project.id)).scalars()
        if a.deleted_at is None and a.merged_into_id is None
        and a.keep_decision != KeepDecision.REJECT and a.status != NerStatus.REJECTED]
    load = result.ner_load
    over = sum(1 for v in load.values() if (v.get("utilisation_pct") or 0) > 100)
    idle = sum(1 for v in load.values() if not v.get("spaces") and not v.get("wireless_points"))

    points = [a for a in result.assignments if a.kind == "wireless_point"]
    n_points = db.execute(select(Element).where(
        Element.project_id == project.id, Element.scenario_id.is_(None),
        Element.kind.in_(DEMAND_KINDS))).scalars().all()

    rows: list[dict] = []

    def add(section: str, label: str, count, of=None, note: str = "") -> None:
        share = (round(count / of, 4) if of else None)
        rows.append({"section": section, "label": label, "count": count,
                     "of": of, "share": share, "note": note})

    S1 = "TEAP spaces"
    add(S1, "TEAP spaces in the file", n_all)
    add(S1, "requesting network ports — the study", n_scope, n_all,
        "every share below is of this number unless the row says otherwise")
    add(S1, "requesting no port — left out", n_all - n_scope, n_all)

    S2 = "Found on the drawing"
    add(S2, "found on the drawing (tied to a room)", len(found), n_scope)
    add(S2, "  confirmed by you", len(confirmed_by_you), n_scope)
    add(S2, "  confirmed by the matcher (exact code, no rival)",
        len(confirmed_by_matcher), n_scope)
    add(S2, "  matched, not yet confirmed", len(not_confirmed), n_scope)
    add(S2, "  tied by hand", len(by_hand), n_scope,
        "a room chosen on TEAP × drawing rather than found by the matcher")
    add(S2, "not found on the drawing", len(not_found), n_scope)
    add(S2, "  of which served by a NER you chose", len(chosen_unplaced), n_scope,
        "counted on that NER, distance not measured")
    add(S2, "  of which rejected — not on this drawing", len(rejected), n_scope)

    S3 = "Coverage (last run)"
    for g in Group:
        add(S3, GROUP_LABEL[g], by_group.get(g, 0), n_scope)
        for reason, n in sorted(by_reason.get(g, {}).items()):
            add(S3, f"  {reason}", n, n_scope)
    if never_analysed:
        add(S3, "  not in the last run (placed or imported after it)",
            len(never_analysed), n_scope, "run the analysis again")

    # The same three numbers as the Summary and the TOTAL of "NERs and ports"
    # (4.0.0): every port is a TEAP port — the DWISA wireless line included —
    # and on a NER or pending, so the two lines below add up to the first.
    S4 = "Ports"
    add(S4, "ports requested by the study (TEAP)", round(ports_total, 1))
    add(S4, "  of which wireless (DWISA)",
        round(sum(wireless_line_ports(t) for t in scope), 1), ports_total or None)
    add(S4, "ports on a NER", round(ports_on_ner, 1), ports_total or None)
    add(S4, "ports on no NER yet (pending)", round(ports_pending, 1), ports_total or None)

    S5 = "NERs"
    add(S5, "NERs in the register", len(live))
    add(S5, "  drawn by you", sum(1 for a in live if a.origin == "manual"), len(live) or None)
    add(S5, "  from the drawing", sum(1 for a in live if a.origin != "manual"), len(live) or None)
    # 2.13.0: of those, the ones read off the room the drawing prints (a
    # TEC.003 code or a "Network Equipment Rack (NER)" label).
    add(S5, "    of which read from the room label",
        sum(1 for a in live if a.origin == "drawing_room"), len(live) or None)
    add(S5, "  criticality not stated", sum(1 for a in live if a.classification == "pending"),
        len(live) or None)
    add(S5, "  capacity known", sum(1 for a in live if a.total_ports is not None), len(live) or None)
    add(S5, "  over capacity (last run)", over, len(live) or None)
    add(S5, "  serving nothing (last run)", idle, len(live) or None)
    # Fibre runs to the TER (2.8.0): counted over the rooms of the last run —
    # the same rows as the "NERs and ports" sheet — with the project's rule.
    fc, fn = fibre_rule(project)
    n_crit = sum(1 for v in load.values() if v.get("critical"))
    n_non = len(load) - n_crit
    add(S5, "  on the drawing (last run)", len(load), len(live) or None)
    # Indoor / outdoor over the same rooms as the Summary and the NERs sheet
    # (4.0.0) — rooms a person removed are never counted.
    add(S5, "    indoor", sum(1 for v in load.values() if v.get("environment") == "indoor"),
        len(load) or None)
    add(S5, "    outdoor", sum(1 for v in load.values() if v.get("environment") == "outdoor"),
        len(load) or None)
    add(S5, "    indoor / outdoor not said",
        sum(1 for v in load.values() if not v.get("environment")), len(load) or None,
        "set it on the NERs screen")
    add(S5, f"  fibre runs to the TER — {n_crit} critical x {fc} + {n_non} non-critical x {fn}",
        n_crit * fc + n_non * fn, None, "a count of runs from the TER, not a length")

    if n_points:
        S6 = "Wi-Fi points drawn"
        add(S6, "Wi-Fi points drawn", len(n_points), None,
            "one per space with wireless; not an access point count — the DWISA line of "
            "their space is the port, the AP count comes from the wireless design")
        add(S6, "  tied to a TEAP space", sum(1 for e in n_points if e.space_key),
            len(n_points))
        add(S6, "  tied to no TEAP space", sum(1 for e in n_points if not e.space_key),
            len(n_points), "not in the TEAP: no port counted")
        add(S6, "  within reach of a NER (last run)", sum(1 for a in points if a.ner_key),
            len(n_points))
        add(S6, "  no NER within reach (last run)", sum(1 for a in points if not a.ner_key),
            len(n_points))
    return rows
