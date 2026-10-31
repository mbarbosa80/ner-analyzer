"""The composite map, against the database (5.0.0).

``domain/composite.py`` places the sheets; this module builds and keeps the
maps of a project, projects what was worked on each sheet onto them — NERs,
Wi-Fi points, the other rooms — finds what only a single plane shows, and
carries out the decisions taken on the map.

Marcelo, 30 Oct 2026: an option generated when he decides, never by default,
in a window of its own and not in the Drawing viewer, that brings
everything already worked on the separate pages; on it he can move, delete and
reclassify NERs, and print the map as one PDF beside the marked-up one. Moving
a NER on the map moves its marker on every sheet of that level that shows the
new spot; a sheet that no longer shows it loses the marker, and the move can
be undone (his choice, the same evening).

The map changes no distance the analysis computes: coverage is still measured
on each sheet. The map is where the decisions are taken.
"""

from __future__ import annotations

import collections
import datetime as _dt
import math
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import isolate
from . import sheets as SH
from .config import settings
from .domain import composite as C
from .models import (AuditLog, CompositeMap, Drawing, DrawingSpace, Element, NerAsset, Page,
                     Project)
from .version import __version__

Progress = Optional[Callable[[float, str], None]]

NER_KINDS = ("NER_CRITICAL", "NER_NONCRITICAL")
#: Kinds drawn on the map besides NERs and Wi-Fi: what is in the building.
VISUAL_KINDS = ("TER", "IDF", "COW", "DIVA")
#: The same NER on two sheets landing farther apart than this (m) is a finding.
SPREAD_M = 1.0
#: Two different NERs closer than this (m): possibly one room under two names.
CLOSE_M = 2.0
#: Space codes two neighbouring sheets share: within this (m) they confirm the
#: placement; two or more shared and none within it contradict it.
SPACE_OK_M = 1.0

#: How each placement state is drawn in the composite map PDF (5.1.0, D27):
#: the window's colours, a line pattern of its own and, when the sheet is not
#: confirmed, the state in words beside the sheet number, so the state reads
#: without the colour (5.0.0 printed "contradicted" exactly as "not confirmed").
STATE_PDF = {
    "confirmed": {"colour": (0x3A / 255, 0x6F / 255, 0xD8 / 255), "dashes": "[6 4] 0",
                  "width": 1.0, "word": ""},
    "unconfirmed": {"colour": (0xF2 / 255, 0x8C / 255, 0x1A / 255), "dashes": "[2 3] 0",
                    "width": 1.5, "word": "NOT CONFIRMED"},
    "contradicted": {"colour": (0xD8 / 255, 0x1B / 255, 0x1B / 255), "dashes": "[14 4 2 4] 0",
                     "width": 2.5, "word": "CONTRADICTED"},
}

#: One lock for the PyMuPDF documents the tiles are cut from, and the folder.
_TILE_LOCK = threading.Lock()


class CompositeError(ValueError):
    """A request the map cannot carry out — the message is for a person."""


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def project_dir(project_id: int) -> Path:
    d = settings.composite_dir / f"project_{project_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def base_path(cmap: CompositeMap) -> Path:
    return project_dir(cmap.project_id) / cmap.base_file


def _tiles_dir(cmap: CompositeMap) -> Path:
    return project_dir(cmap.project_id) / (Path(cmap.base_file).stem + "_tiles")


def _drop_files(cmap: CompositeMap) -> None:
    if not cmap.base_file:
        return
    with _TILE_LOCK:
        C.forget(str(base_path(cmap)))
        base_path(cmap).unlink(missing_ok=True)
        shutil.rmtree(_tiles_dir(cmap), ignore_errors=True)


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_") or "group"


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def page_facts(db: Session, drawing: Drawing) -> list[dict]:
    rows = db.execute(select(Page).where(Page.drawing_id == drawing.id)
                      .order_by(Page.number)).scalars().all()
    return [{"number": p.number, "sheet_number": p.sheet_number, "level": p.level,
             "key_plan": bool(p.key_plan), "mpu": p.metres_per_unit} for p in rows]


def maps_of(db: Session, project_id: int, drawing_id: Optional[int] = None) -> list[CompositeMap]:
    q = select(CompositeMap).where(CompositeMap.project_id == project_id)
    if drawing_id is not None:
        q = q.where(CompositeMap.drawing_id == drawing_id)
    return list(db.execute(q.order_by(CompositeMap.drawing_id, CompositeMap.group_key)).scalars())


def plan(db: Session, project: Project) -> list[dict]:
    """Per book: the groups a build would make and the maps already built."""
    out = []
    for d in sorted(project.drawings, key=lambda d: d.id):
        built = {m.group_key: m for m in maps_of(db, project.id, d.id)}
        groups = []
        for g in C.plan_groups(page_facts(db, d)):
            m = built.pop(g["key"], None)
            groups.append({**g, "sheet_count": len(g["pages"]),
                           "map": summary(m, d) if m else None})
        # A map whose group the book no longer has (the book was re-read).
        for m in built.values():
            groups.append({"key": m.group_key, "label": m.label, "level": m.level, "pages": [],
                           "no_scale": [], "sheet_count": 0, "map": summary(m, d)})
        out.append({"drawing_id": d.id, "filename": d.filename, "groups": groups})
    return out


def summary(m: CompositeMap, drawing: Optional[Drawing] = None) -> dict:
    states = collections.Counter(s.get("state") for s in m.sheets or [])
    excluded = sum(1 for s in m.sheets or [] if s.get("excluded"))
    built = m.built_at
    if built is not None and built.tzinfo is None:
        built = built.replace(tzinfo=_dt.timezone.utc)
    return {"id": m.id, "drawing_id": m.drawing_id, "key": m.group_key, "label": m.label,
            "level": m.level, "sheets": len(m.sheets or []),
            "confirmed": states.get("confirmed", 0),
            "unconfirmed": states.get("unconfirmed", 0),
            "contradicted": states.get("contradicted", 0),
            "not_aligned": states.get("not_aligned", 0), "excluded": excluded,
            "built_at": built.isoformat() if built else None, "built_by": m.built_by,
            "app_version": m.app_version, "has_picture": bool(m.frame),
            # The book was replaced after the map was built.
            "outdated": bool(drawing is not None and m.drawing_sha
                             and drawing.sha256 and m.drawing_sha != drawing.sha256)}


def build(db: Session, project: Project, drawing: Drawing, *, only: Optional[list[str]] = None,
          progress: Progress = None, actor: str = "user") -> dict:
    """Place the sheets of a book and keep one map per group. A sheet a person
    left off a map stays off when the map is built again."""
    prog = progress or (lambda *_: None)
    facts = page_facts(db, drawing)
    if not any(not f["key_plan"] and f["mpu"] for f in facts):
        raise CompositeError(f"{drawing.filename} has no detail sheet with a scale yet — "
                             f"confirm the scales on the Scale screen first")
    if not any(f["key_plan"] for f in facts):
        raise CompositeError(f"{drawing.filename} has no key plan ticked — the map is laid out "
                             f"from the key plan (Scale screen, Key plan column)")

    def _p(frac, stage=""):
        prog(0.85 * frac, stage)
    res = isolate.run("app.domain.composite.align_book", drawing.stored_path, facts, only,
                      progress=_p)
    built = []
    groups = res["groups"]
    if not groups:
        raise CompositeError(f"every level of {drawing.filename} is drawn on one sheet — "
                             f"nothing to lay out")
    for i, g in enumerate(groups):
        prog(0.85 + 0.15 * i / max(1, len(groups)), f"{g['label']}: composing the picture")
        row = db.execute(select(CompositeMap).where(
            CompositeMap.drawing_id == drawing.id,
            CompositeMap.group_key == g["key"])).scalar_one_or_none()
        excluded = {s["page"] for s in (row.sheets if row else []) if s.get("excluded")}
        for s in g["sheets"]:
            s["excluded"] = s["page"] in excluded
        if row is None:
            row = CompositeMap(project_id=project.id, drawing_id=drawing.id, group_key=g["key"])
            db.add(row)
        else:
            _drop_files(row)
        row.label, row.level, row.mpu = g["label"], g["level"], g["mpu"]
        row.frame, row.refine, row.no_scale = g["frame"], g["refine"], g["no_scale"]
        row.sheets = _space_checks(db, drawing, g["sheets"], g["frame"])
        row.drawing_sha = drawing.sha256 or ""
        row.built_at = _dt.datetime.now(_dt.timezone.utc)
        row.built_by = actor
        row.app_version = __version__
        row.base_file = ""
        db.flush()
        if row.frame:
            _compose(row, drawing)
        st = collections.Counter(s["state"] for s in row.sheets)
        _audit(db, project.id, "composite.built", row,
               {"book": drawing.filename, "group": row.label, "sheets": len(row.sheets),
                **{k: v for k, v in st.items()}})
        built.append(summary(row, drawing))
    db.commit()
    prog(1.0, "done")
    return {"maps": built}


def _compose(row: CompositeMap, drawing: Drawing) -> None:
    stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    name = f"d{row.drawing_id}_{_safe(row.group_key)}_{stamp}.pdf"
    out = project_dir(row.project_id) / name
    group = {"frame": row.frame, "sheets": row.sheets}
    isolate.run("app.domain.composite.compose", drawing.stored_path, group, str(out))
    row.base_file = name


def _space_checks(db: Session, drawing: Drawing, sheets: list[dict], frame: Optional[dict]
                  ) -> list[dict]:
    """The spaces two neighbouring sheets both print: when the same code lands
    in the same place on the map the two sheets confirm each other; two or
    more shared codes and none in the same place contradict the placement."""
    sheets = [dict(s) for s in sheets]
    if not frame:
        return sheets
    placed = {s["page"]: s for s in sheets if s.get("state") not in (None, "not_aligned")}
    rows = db.execute(select(DrawingSpace).where(
        DrawingSpace.drawing_id == drawing.id, DrawingSpace.page.in_(list(placed) or [-1]),
        DrawingSpace.space_code.is_not(None))).scalars().all()
    by_code: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        s = placed[r.page]
        X, Y = C.to_map(s, frame, r.x, r.y)
        m0 = s["mpu"] / s.get("s", 1.0)          # metres per point of the frame
        by_code[r.space_code].append((r.page, X * m0, Y * m0))
    pair: dict[tuple, list[float]] = collections.defaultdict(list)
    for code, pts in by_code.items():
        pages = sorted({p for p, _, _ in pts})
        for a in range(len(pages)):
            for b in range(a + 1, len(pages)):
                pa = [q for q in pts if q[0] == pages[a]]
                pb = [q for q in pts if q[0] == pages[b]]
                d = min(math.hypot(u[1] - v[1], u[2] - v[2]) for u in pa for v in pb)
                pair[(pages[a], pages[b])].append(d)
    ok, bad = set(), set()
    for (a, b), ds in pair.items():
        if not _neighbours(placed[a], placed[b], frame):
            continue                     # far apart: a code repeated on purpose
        if min(ds) <= SPACE_OK_M:
            ok |= {a, b}
        elif len(ds) >= 2:
            bad |= {a, b}
    for s in sheets:
        if s["page"] not in placed:
            continue
        s["space_ok"] = s["page"] in ok
        if s["state"] != "confirmed":
            if s["page"] in ok:
                s["state"] = "confirmed"
            elif s["page"] in bad:
                s["state"] = "contradicted"
    return sheets


def _map_rect(sheet: dict, frame: dict, which: str = "view") -> tuple[float, float, float, float]:
    r = sheet[which]
    X0, Y0 = C.to_map(sheet, frame, r[0], r[1])
    X1, Y1 = C.to_map(sheet, frame, r[2], r[3])
    return (min(X0, X1), min(Y0, Y1), max(X0, X1), max(Y0, Y1))


def _neighbours(a: dict, b: dict, frame: dict) -> bool:
    ra, rb = _map_rect(a, frame), _map_rect(b, frame)
    return not (ra[2] < rb[0] or rb[2] < ra[0] or ra[3] < rb[1] or rb[3] < ra[1])


def set_excluded(db: Session, project: Project, cmap: CompositeMap, page: int, excluded: bool,
                 *, actor: str = "user") -> dict:
    """Leave a sheet off the map (or put it back) and compose the picture again."""
    sheets = [dict(s) for s in cmap.sheets or []]
    hit = [s for s in sheets if s["page"] == page]
    if not hit:
        raise CompositeError(f"page {page} is not a sheet of this map")
    if hit[0].get("state") == "not_aligned" and not excluded:
        raise CompositeError("this sheet could not be placed — it cannot be shown")
    hit[0]["excluded"] = bool(excluded)
    cmap.sheets = sheets
    drawing = db.get(Drawing, cmap.drawing_id)
    _drop_files(cmap)
    cmap.base_file = ""
    if cmap.frame:
        _compose(cmap, drawing)
    _audit(db, project.id, "composite.sheet_excluded", cmap,
           {"group": cmap.label, "page": page, "sheet": hit[0].get("sheet_number"),
            "excluded": bool(excluded)}, actor=actor)
    db.commit()
    return summary(cmap, drawing)


def delete(db: Session, project: Project, cmap: CompositeMap, *, actor: str = "user") -> None:
    _drop_files(cmap)
    _audit(db, project.id, "composite.deleted", cmap, {"group": cmap.label}, actor=actor)
    db.delete(cmap)
    db.commit()


def _audit(db: Session, project_id: int, action: str, cmap: Optional[CompositeMap],
           payload: dict, *, actor: Optional[str] = None, justification: str = "") -> AuditLog:
    from . import services as S
    S.audit(db, project_id, action, entity="composite_map",
            entity_id=cmap.id if cmap is not None else None,
            payload=payload, justification=justification,
            **({"actor": actor} if actor else {}))
    db.flush()
    return db.execute(select(AuditLog).where(AuditLog.project_id == project_id,
                                             AuditLog.action == action)
                      .order_by(AuditLog.id.desc()).limit(1)).scalar_one()


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------

def tile(db: Session, cmap: CompositeMap, z: int, x: int, y: int) -> bytes:
    if not cmap.frame:
        raise CompositeError("no sheet of this map could be placed")
    if not 0 <= z <= C.TILE_ZMAX or x < 0 or y < 0:
        raise CompositeError("no such tile")
    path = _tiles_dir(cmap) / str(z) / f"{x}_{y}.png"
    if path.exists():
        return path.read_bytes()
    with _TILE_LOCK:
        # Read the row again inside the lock (5.1.0, D30): the tiles of a
        # window ask in parallel, each request with its own session read
        # before the lock. Without this, every waiting request still saw the
        # picture missing and composed one more copy — six PDFs of one map,
        # five of them never referenced, on 30 Oct 2026.
        db.refresh(cmap)
        if not cmap.base_file or not base_path(cmap).exists():
            # The picture went (a restored backup does not carry it): compose
            # it again from the placement kept in the database.
            drawing = db.get(Drawing, cmap.drawing_id)
            _compose(cmap, drawing)
            db.commit()
        # The tile belongs to the picture the row names now.
        path = _tiles_dir(cmap) / str(z) / f"{x}_{y}.png"
        if path.exists():
            return path.read_bytes()
        png = C.render_tile(str(base_path(cmap)), z, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
    return png


# ---------------------------------------------------------------------------
# What was worked on the sheets, on the map
# ---------------------------------------------------------------------------

def _drawn_sheets(cmap: CompositeMap) -> dict[int, dict]:
    return {s["page"]: s for s in cmap.sheets or [] if C.drawn(s)}


def overlay(db: Session, project: Project, cmap: CompositeMap) -> dict:
    """NERs, Wi-Fi points, the other rooms and the space labels of the map's
    sheets, on the map, with the findings only a single plane shows."""
    sh = SH.for_project(db, project.id)
    drawing = db.get(Drawing, cmap.drawing_id)
    frame = cmap.frame or {"x0": 0, "y0": 0, "width": 0, "height": 0}
    drawn = _drawn_sheets(cmap)
    group_pages = {s["page"] for s in cmap.sheets or []}
    mpu = cmap.mpu or 1.0

    sheets = []
    for s in cmap.sheets or []:
        rec = {k: s.get(k) for k in ("page", "sheet_number", "state", "method", "conf",
                                     "a_vs_b_m", "neighbours_ok", "excluded", "why",
                                     "moved_by_neighbours_m", "space_ok")}
        rec["key"] = sh.key(cmap.drawing_id, s["page"])
        if s.get("state") not in (None, "not_aligned") and cmap.frame:
            rec["rect"] = list(_map_rect(s, frame, "clip"))
        sheets.append(rec)

    rows = db.execute(select(Element).where(
        Element.project_id == project.id, Element.drawing_id == cmap.drawing_id,
        Element.scenario_id.is_(None), Element.page.in_(list(group_pages) or [-1]))).scalars().all()
    assets: dict[int, NerAsset] = {}
    ner_pts: dict[int, list[dict]] = collections.defaultdict(list)
    off_map: dict[int, list[int]] = collections.defaultdict(list)
    wifi, others = [], []
    for e in rows:
        a = e.ner_asset
        if a is not None and (a.deleted_at is not None or a.merged_into_id is not None):
            continue
        s = drawn.get(e.page)
        key = sh.of(e)
        if e.kind in NER_KINDS and a is not None:
            assets[a.id] = a
            if s is None:
                off_map[a.id].append(key)
                continue
            X, Y = C.to_map(s, frame, e.x, e.y)
            ner_pts[a.id].append({"element_id": e.id, "page_key": key, "X": X, "Y": Y,
                                  "x": e.x, "y": e.y, "sheet": s.get("sheet_number")})
        elif s is None:
            continue
        elif e.kind == "WIRELESS":
            X, Y = C.to_map(s, frame, e.x, e.y)
            wifi.append({"id": e.id, "label": e.label, "X": X, "Y": Y, "page_key": key,
                         "environment": e.environment})
        elif e.kind in VISUAL_KINDS:
            X, Y = C.to_map(s, frame, e.x, e.y)
            others.append({"id": e.id, "kind": e.kind, "label": e.label, "X": X, "Y": Y,
                           "page_key": key})

    # Other books the NERs are drawn in: not moved from here, named.
    other_books: dict[int, set] = collections.defaultdict(set)
    for a in assets.values():
        for o in a.occurrences or []:
            if o.drawing_id != cmap.drawing_id and o.scenario_id is None:
                other_books[a.id].add(SH._series(sh.filenames.get(o.drawing_id, "")))

    ners, findings = [], []
    for aid, a in sorted(assets.items(), key=lambda kv: kv[1].display_name or ""):
        pts = ner_pts.get(aid, [])
        crit = a.kind == "NER_CRITICAL"
        rec = {"asset_id": aid, "name": a.display_name, "code": a.code,
               "critical": crit, "classification": a.classification,
               "classification_confirmed": a.classification_confirmed,
               "locked": bool(a.locked), "environment": a.environment,
               "points": pts, "off_map_pages": sorted(off_map.get(aid, [])),
               "other_books": sorted(other_books.get(aid, set()))}
        if pts:
            spread = max(math.hypot(u["X"] - v["X"], u["Y"] - v["Y"])
                         for u in pts for v in pts) * mpu
            rec["spread_m"] = round(spread, 2)
            rec["X"] = sum(p["X"] for p in pts) / len(pts)
            rec["Y"] = sum(p["Y"] for p in pts) / len(pts)
            if spread > SPREAD_M:
                findings.append({"type": "spread", "asset_id": aid, "name": a.display_name,
                                 "distance_m": round(spread, 2),
                                 "pages": sorted({p["page_key"] for p in pts})})
        elif off_map.get(aid):
            findings.append({"type": "off_map", "asset_id": aid, "name": a.display_name,
                             "pages": sorted(off_map[aid])})
        ners.append(rec)
    placed = [n for n in ners if n.get("points")]
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            u, v = placed[i], placed[j]
            d = min(math.hypot(p["X"] - q["X"], p["Y"] - q["Y"])
                    for p in u["points"] for q in v["points"]) * mpu
            if d < CLOSE_M:
                findings.append({"type": "close", "asset_id": u["asset_id"],
                                 "other_asset_id": v["asset_id"], "name": u["name"],
                                 "other_name": v["name"], "distance_m": round(d, 2)})

    spaces = []
    for r in db.execute(select(DrawingSpace).where(
            DrawingSpace.drawing_id == cmap.drawing_id,
            DrawingSpace.page.in_(list(drawn) or [-1]))).scalars():
        X, Y = C.to_map(drawn[r.page], frame, r.x, r.y)
        spaces.append({"code": r.space_code, "name": r.name, "X": X, "Y": Y})

    return {"map": {**summary(cmap, drawing), "width": frame["width"], "height": frame["height"],
                    "mpu": mpu, "filename": drawing.filename if drawing else "",
                    "tile_px": C.TILE_PX, "zmax": C.TILE_ZMAX,
                    "tile_version": Path(cmap.base_file).stem if cmap.base_file else "",
                    "no_scale": [sh.key(cmap.drawing_id, n) for n in cmap.no_scale or []]},
            "limits": {"general_m": project.general_limit_m,
                       "photographer_m": project.photographer_limit_m},
            "sheets": sheets, "ners": ners, "wifi": wifi, "others": others,
            "spaces": spaces, "findings": findings}


# ---------------------------------------------------------------------------
# Moving a NER on the map
# ---------------------------------------------------------------------------

def _row_of(e: Element) -> dict:
    return {c.name: getattr(e, c.name) for c in Element.__table__.columns if c.name != "id"}


def move_ner(db: Session, project: Project, cmap: CompositeMap, asset_id: int, X: float,
             Y: float, *, actor: str = "user", justification: str = "",
             preview: bool = False) -> dict:
    """Move a NER to a spot of the map. Every marker of it on this map's
    sheets follows when its sheet shows the spot; a sheet that does not show
    it any more loses the marker; when no sheet that drew it shows the spot,
    a marker is drawn on the sheet that does. Undo puts every marker back.

    5.1.0 (QA of 5.0.0):
    * a move is a real change of position on the sheets, not a picture: the
      result says how far the NER goes (``distance_m``) and ``preview=True``
      answers that, and which sheets it leaves or is drawn on, without
      changing anything, so the window can say it before the person confirms
      (D26: an 80-pixel drag at the fitted zoom moved a NER about 170 m);
    * a NER whose drawings land more than ``SPREAD_M`` apart on this map is
      refused (D29): the sheets disagree, so there is no single spot to move
      it from; a 0.5 m drag collapsed drawings 77 m and 353 m apart onto the
      middle and erased the finding that showed the disagreement;
    * a drawing taken off a sheet leaves its spot to the NER
      (``released_spots``), so the next *Place NERs from the drawing* takes
      the room printed there as this NER instead of creating a new one (D25).
    """
    from . import services as S
    if not (math.isfinite(X) and math.isfinite(Y)):
        raise CompositeError("the position must be a number")
    a = db.get(NerAsset, asset_id)
    if a is None or a.project_id != project.id:
        raise CompositeError("NER not found")
    if a.deleted_at is not None or a.merged_into_id is not None:
        raise CompositeError(f"{a.display_name} was removed from the register")
    if a.locked:
        raise CompositeError(f"{a.display_name} is locked — unlock it on the NERs screen first")
    frame = cmap.frame
    if not frame:
        raise CompositeError("no sheet of this map could be placed")
    sh = SH.for_project(db, project.id)
    drawn = _drawn_sheets(cmap)
    # Which sheets show the spot (their drawing area), and which one's own
    # zone holds it — the sheet a new marker goes on.
    shows: dict[int, tuple[float, float]] = {}
    home: Optional[int] = None
    for page, s in drawn.items():
        x, y = C.from_map(s, frame, X, Y)
        if C.inside(s["view"], x, y):
            shows[page] = (x, y)
            if home is None and C.inside(s["clip"], x, y):
                home = page
    if not shows:
        raise CompositeError("that spot is on no sheet of this map")
    if home is None:
        home = sorted(shows)[0]
    markers = [e for e in (a.occurrences or [])
               if e.drawing_id == cmap.drawing_id and e.scenario_id is None
               and e.kind in NER_KINDS and e.page in drawn]
    if any(e.locked for e in markers):
        raise CompositeError(f"a marker of {a.display_name} is locked")
    if not markers:
        raise CompositeError(f"{a.display_name} is not drawn on any sheet of this map")
    # Where its drawings are on the map now (D29): they must agree.
    mpu = cmap.mpu or 1.0
    at = [(e, C.to_map(drawn[e.page], frame, e.x, e.y)) for e in markers]
    spread = max((math.hypot(p[0] - q[0], p[1] - q[1]) for _, p in at for _, q in at),
                 default=0.0) * mpu
    if spread > SPREAD_M:
        far = sorted({sh.label(sh.of(e)) for e, _ in at})
        # 5.1.1 (D32): two drawings of it on ONE sheet is not a sheet misplaced
        # on the map — the advice to leave a sheet off would not help.
        twice = []
        for page in sorted({e.page for e, _ in at}):
            here = [p for e, p in at if e.page == page]
            gap = max((math.hypot(p[0] - q[0], p[1] - q[1]) for p in here for q in here),
                      default=0.0) * mpu
            if gap > SPREAD_M:
                twice.append((sh.label(sh.key(cmap.drawing_id, page)), gap))
        if twice:
            where = ", ".join(f"{lab} ({gap:.1f} m apart)" for lab, gap in twice)
            raise CompositeError(
                f"{a.display_name} is drawn twice on the same sheet: {where}, so there is no "
                f"one spot to move it from. Open that sheet in the Drawing viewer and delete "
                f"the extra marker with Delete only this marker, then move it here")
        raise CompositeError(
            f"{a.display_name} is drawn {spread:.1f} m apart on this map ({', '.join(far)}): "
            f"its sheets disagree, so there is no one spot to move it from. Check those "
            f"sheets — one is probably misplaced on the map: leave it off the map, or "
            f"move the NER on each sheet in the Drawing viewer")
    cx = sum(p[0] for _, p in at) / len(at)
    cy = sum(p[1] for _, p in at) / len(at)
    distance_m = round(math.hypot(X - cx, Y - cy) * mpu, 1)
    if preview:
        stay = [e for e in markers if e.page in shows]
        return {"ok": True, "preview": True, "name": a.display_name, "distance_m": distance_m,
                "moved": [sh.of(e) for e in stay],
                "removed": [sh.of(e) for e in markers if e.page not in shows],
                "created": [] if stay else [sh.key(cmap.drawing_id, home)],
                "labels": {str(k): sh.label(k) for k in
                           {sh.of(e) for e in markers} | {sh.key(cmap.drawing_id, home)}}}
    canonical_before = {"drawing_id": a.canonical_drawing_id, "page": a.canonical_page,
                        "x": a.canonical_x, "y": a.canonical_y}
    moved, removed, created = [], [], []
    why = justification or "moved on the composite map"
    for e in markers:
        if e.page in shows:
            nx, ny = shows[e.page]
            frm = {"page": sh.of(e), "x": e.x, "y": e.y}
            e.x, e.y = nx, ny
            moved.append({"element_id": e.id, "from": frm,
                          "to": {"page": sh.of(e), "x": nx, "y": ny}})
            S.audit(db, project.id, "ner.moved", entity="ner_asset", entity_id=a.id,
                    justification=why, payload={"element_id": e.id, "label": e.label,
                                                "from": frm, "to": moved[-1]["to"],
                                                "via": "composite map"})
        else:
            removed.append({"element_id": e.id, "page": sh.of(e), "row": _row_of(e)})
    if not moved:
        e0 = markers[0]
        nx, ny = shows[home]
        ne = Element(project_id=project.id, drawing_id=cmap.drawing_id, page=home,
                     kind=a.kind if a.kind in NER_KINDS else e0.kind, label=a.display_name,
                     x=nx, y=ny, origin="manual", confidence=1.0, confirmed=True,
                     confirmed_by=actor, detection_method="composite map",
                     document_kind="VDB", ner_asset_id=a.id, link_status="confirmed",
                     link_score=1.0, origin_x=nx, origin_y=ny,
                     evidence=[f"drawn here when {a.display_name} was moved on the composite map"])
        db.add(ne)
        db.flush()
        created.append(ne.id)
        S.audit(db, project.id, "element.created", entity="element", entity_id=ne.id,
                justification=why, payload={"kind": ne.kind, "label": ne.label,
                                            "page": sh.of(ne), "x": nx, "y": ny,
                                            "via": "composite map"})
    for r in removed:
        e = db.get(Element, r["element_id"])
        S.audit(db, project.id, "element.deleted", entity="element", entity_id=e.id,
                justification=why, payload={"label": e.label, "kind": e.kind,
                                            "page": r["page"], "scope": "marker",
                                            "via": "composite map — this sheet does not show "
                                                   "the new spot"})
        # The room the sheet prints there is still this NER (D25).
        S.release_spot(a, e, f"its drawing on {sh.label(r['page'])} was taken off by a move "
                             f"on the composite map")
        db.delete(e)
    db.flush()
    db.refresh(a)
    # The register's own position: the marker on the sheet whose zone holds
    # the spot, else the first one left.
    live = [e for e in a.occurrences or [] if e.scenario_id is None and e.kind in NER_KINDS]
    if (a.canonical_drawing_id in (None, cmap.drawing_id)
            and (a.canonical_page in drawn or a.canonical_page is None
                 or not any(SH.on_canonical_sheet(e, a) for e in live))):
        here = [e for e in live if e.drawing_id == cmap.drawing_id and e.page == home] \
            or [e for e in live if e.drawing_id == cmap.drawing_id] or live
        if here:
            a.canonical_drawing_id = here[0].drawing_id
            a.canonical_page = here[0].page
            a.canonical_x, a.canonical_y = here[0].x, here[0].y
    a.pending_validations = [v for v in (a.pending_validations or [])
                             if not v.startswith("position:")]
    a.updated_by = actor
    log = _audit(db, project.id, "composite.ner_moved", cmap,
                 {"asset_id": a.id, "name": a.display_name, "group": cmap.label,
                  "to_map": {"X": X, "Y": Y}, "moved": moved,
                  "removed": [{"element_id": r["element_id"], "page": r["page"],
                               "row": r["row"]} for r in removed],
                  "created": created, "canonical_before": canonical_before},
                 actor=actor, justification=why)
    db.commit()
    other = sorted({SH._series(sh.filenames.get(o.drawing_id, "")) for o in a.occurrences or []
                    if o.drawing_id != cmap.drawing_id and o.scenario_id is None})
    return {"ok": True, "undo_id": log.id, "name": a.display_name, "distance_m": distance_m,
            "moved": [m["to"]["page"] for m in moved],
            "removed": [r["page"] for r in removed],
            "created": [sh.key(cmap.drawing_id, home)] if created else [],
            "other_books": other}


def undo_move(db: Session, project: Project, audit_id: int, *, actor: str = "user") -> dict:
    """Put a NER back where it was before a move on the map — only while
    nothing touched its markers since."""
    from . import services as S
    log = db.get(AuditLog, audit_id)
    if log is None or log.project_id != project.id or log.action != "composite.ner_moved":
        raise CompositeError("no such move on the composite map")
    if any((r.payload or {}).get("undo_of") == audit_id for r in db.execute(
            select(AuditLog).where(AuditLog.project_id == project.id,
                                   AuditLog.action == "composite.ner_move_undone")).scalars()):
        raise CompositeError("this move was undone already")
    p = log.payload or {}
    a = db.get(NerAsset, p.get("asset_id"))
    if a is None or a.deleted_at is not None:
        raise CompositeError("the NER is no longer in the register")
    for m in p.get("moved", []):
        e = db.get(Element, m["element_id"])
        if e is None or abs(e.x - m["to"]["x"]) > 0.01 or abs(e.y - m["to"]["y"]) > 0.01:
            raise CompositeError(f"{a.display_name} was changed after this move — "
                                 f"move it back by hand")
    for eid in p.get("created", []):
        if db.get(Element, eid) is None:
            raise CompositeError(f"{a.display_name} was changed after this move — "
                                 f"move it back by hand")
    for m in p.get("moved", []):
        e = db.get(Element, m["element_id"])
        e.x, e.y = m["from"]["x"], m["from"]["y"]
        S.audit(db, project.id, "ner.moved", entity="ner_asset", entity_id=a.id,
                justification="move on the composite map undone",
                payload={"element_id": e.id, "label": e.label, "from": m["to"],
                         "to": m["from"], "via": "composite map"})
    for eid in p.get("created", []):
        e = db.get(Element, eid)
        S.audit(db, project.id, "element.deleted", entity="element", entity_id=eid,
                justification="move on the composite map undone",
                payload={"label": e.label, "kind": e.kind, "scope": "marker",
                         "via": "composite map"})
        db.delete(e)
    # A drawing the NER already has again on that sheet, at that spot, is not
    # put back a second time (5.1.0, D31): on a stadium project Place NERs had
    # drawn two moved NERs back on the sheets they were taken off (same TEC
    # code), and Undo then gave each of them two markers on one sheet.
    sh = SH.for_project(db, project.id)
    scales = S.scale_map(db, project.id)
    already: list = []
    for r in p.get("removed", []):
        row = dict(r["row"])
        row["ner_asset_id"] = a.id
        spots = [(row["x"], row["y"])]
        if row.get("origin_x") is not None:
            spots.append((row["origin_x"], row["origin_y"]))
        sc = scales.get(sh.key(row.get("drawing_id"), row["page"]))
        limit = S.DRAWN_ROOM_SAME_PLACE_M / sc.metres_per_unit if sc else S.DRAWN_ROOM_SAME_PLACE_PT
        there = [o for o in db.execute(select(Element).where(
            Element.ner_asset_id == a.id, Element.scenario_id.is_(None),
            Element.page == row["page"], Element.kind.in_(NER_KINDS))).scalars()
            if o.drawing_id == row.get("drawing_id")
            and any(math.dist(q, s) <= limit for q in S.marker_spots(o) for s in spots)]
        if there:
            already.append(r["page"])
            S.unrelease_spot(a, Element(**row))       # held by that marker again
            continue
        e = Element(**row)
        db.add(e)
        db.flush()
        S.unrelease_spot(a, e)
        S.audit(db, project.id, "element.created", entity="element", entity_id=e.id,
                justification="move on the composite map undone",
                payload={"kind": e.kind, "label": e.label, "page": r["page"],
                         "x": e.x, "y": e.y, "via": "composite map"})
    cb = p.get("canonical_before") or {}
    a.canonical_drawing_id = cb.get("drawing_id")
    a.canonical_page = cb.get("page")
    a.canonical_x, a.canonical_y = cb.get("x"), cb.get("y")
    a.updated_by = actor
    cmap = db.get(CompositeMap, log.entity_id) if log.entity_id else None
    _audit(db, project.id, "composite.ner_move_undone", cmap,
           {"undo_of": audit_id, "asset_id": a.id, "name": a.display_name,
            "already_drawn": already}, actor=actor)
    db.commit()
    return {"ok": True, "name": a.display_name, "already_drawn": already}


# ---------------------------------------------------------------------------
# The report: one page per map
# ---------------------------------------------------------------------------

def export_pdf(db: Session, project: Project, out_path: Path, *, maps: Optional[list[int]] = None,
               progress: Progress = None, draw_legend: bool = True) -> dict:
    """One page per composite map — the sheets as placed, every NER with its
    reach (the general and the photographer limits, straight line), the Wi-Fi
    points and the other rooms. The legend on the first page only."""
    import pymupdf
    from .domain.reports import (COLOURS, DISCLAIMER, MARKER_LABEL_FONT, PRODUCED_BY,
                                 _draw_wifi, PageSpace)
    prog = progress or (lambda *_: None)
    rows = [m for m in maps_of(db, project.id) if m.frame and (maps is None or m.id in maps)]
    if not rows:
        raise CompositeError("no composite map is built yet — build one first")
    doc = pymupdf.open()
    pages = 0
    for i, m in enumerate(rows):
        prog(i / len(rows), m.label)
        data = overlay(db, project, m)
        fr = m.frame
        head = 70.0
        k = min(1.0, C.PDF_MAX_SIDE / max(fr["width"], fr["height"] + head))
        W, H = fr["width"] * k, fr["height"] * k + head * k
        page = doc.new_page(width=W, height=H)
        with _TILE_LOCK:
            if not m.base_file or not base_path(m).exists():
                _compose(m, db.get(Drawing, m.drawing_id))
                db.commit()
            with pymupdf.open(str(base_path(m))) as base:
                page.show_pdf_page(pymupdf.Rect(0, head * k, W, H), base, 0)

        def P(X, Y):
            return pymupdf.Point(X * k, head * k + Y * k)
        sz = max(0.35, k)
        shape = page.new_shape()
        r_gen = data["limits"]["general_m"] / m.mpu * k
        r_pho = data["limits"]["photographer_m"] / m.mpu * k
        for s in data["sheets"]:
            if s.get("rect") and not s.get("excluded"):
                x0, y0, x1, y1 = s["rect"]
                st = STATE_PDF.get(s["state"], STATE_PDF["unconfirmed"])
                shape.draw_rect(pymupdf.Rect(P(x0, y0), P(x1, y1)))
                shape.finish(color=st["colour"], width=st["width"] * sz, dashes=st["dashes"],
                             stroke_opacity=0.9)
        for n in data["ners"]:
            if "X" not in n:
                continue
            col = COLOURS["NER_CRITICAL"] if n["critical"] else COLOURS["NER_NONCRITICAL"]
            c = P(n["X"], n["Y"])
            shape.draw_circle(c, r_gen)
            shape.finish(color=col, width=1.2 * sz, dashes="[12 8] 0", stroke_opacity=0.75)
            shape.draw_circle(c, r_pho)
            shape.finish(color=col, width=0.8 * sz, dashes="[3 5] 0", stroke_opacity=0.6)
        shape.commit()
        shape = page.new_shape()
        for o in data["others"]:
            col = COLOURS.get(o["kind"], (0.4, 0.4, 0.4))
            shape.draw_circle(P(o["X"], o["Y"]), 9 * sz)
            shape.finish(color=(0, 0, 0), fill=col, width=0.6)
        for n in data["ners"]:
            if "X" not in n:
                continue
            col = COLOURS["NER_CRITICAL"] if n["critical"] else COLOURS["NER_NONCRITICAL"]
            for p in n["points"] if n.get("spread_m", 0) > SPREAD_M else [n]:
                shape.draw_circle(P(p["X"], p["Y"]), 14 * sz)
                shape.finish(color=(0, 0, 0), fill=col, width=0.8)
        shape.commit()
        space = PageSpace(page)
        for w in data["wifi"]:
            _draw_wifi(space, *P(w["X"], w["Y"]), 16 * sz, COLOURS["WIRELESS"])
        space.commit()
        for n in data["ners"]:
            if "X" not in n:
                continue
            c = P(n["X"], n["Y"])
            page.insert_text(pymupdf.Point(c.x + 17 * sz, c.y - 8 * sz), n["name"],
                             fontsize=max(6.0, 18 * sz), fontname=MARKER_LABEL_FONT,
                             color=(0, 0, 0), render_mode=0)
        for o in data["others"]:
            c = P(o["X"], o["Y"])
            page.insert_text(pymupdf.Point(c.x + 11 * sz, c.y - 6 * sz), o["label"],
                             fontsize=max(5.0, 12 * sz), color=(0.2, 0.2, 0.2))
        # Each sheet's number and, when it is not confirmed, its state in words
        # (5.1.0, D27): the state must read without the colour.
        for s in data["sheets"]:
            if s.get("rect") and not s.get("excluded"):
                st = STATE_PDF.get(s["state"], STATE_PDF["unconfirmed"])
                txt = (s.get("sheet_number") or "") + (f"  {st['word']}" if st["word"] else "")
                if txt.strip():
                    fs = max(6.0, 15 * sz)
                    font = "hebo" if st["word"] else "helv"
                    at = P(s["rect"][0] + 6, s["rect"][1] + 18)
                    # A white ground under the words: the sheets print water,
                    # roofs and fills in strong colours (red on the blue of a
                    # harbour read poorly).
                    wdt = pymupdf.get_text_length(txt, fontname=font, fontsize=fs)
                    page.draw_rect(pymupdf.Rect(at.x - 2, at.y - fs, at.x + wdt + 2, at.y + fs * 0.3),
                                   color=None, fill=(1, 1, 1), fill_opacity=0.85)
                    page.insert_text(at, txt, fontsize=fs, color=st["colour"], fontname=font)
        filename = data["map"]["filename"]
        live = [s for s in data["sheets"] if s.get("rect") and not s.get("excluded")]
        n_by = collections.Counter(s["state"] for s in live)
        page.insert_text(pymupdf.Point(20 * k, 30 * k),
                         f"{project.name} — {filename} — {m.label} — composite map",
                         fontsize=max(8.0, 26 * k), fontname="hebo")
        page.insert_text(pymupdf.Point(20 * k, 58 * k),
                         f"{len(live)} sheet(s) placed by the app: {n_by.get('confirmed', 0)} "
                         f"confirmed (blue dashed outline), {n_by.get('unconfirmed', 0)} not "
                         f"confirmed (orange dotted, marked NOT CONFIRMED), "
                         f"{n_by.get('contradicted', 0)} contradicted (red dash-dot, marked "
                         f"CONTRADICTED: its spaces do not line up with a neighbour's — it is "
                         f"probably misplaced). Distances in the analysis are measured on each "
                         f"sheet. Circles: {data['limits']['general_m']:g} m and "
                         f"{data['limits']['photographer_m']:g} m straight line. "
                         f"{PRODUCED_BY}. {DISCLAIMER}",
                         fontsize=max(5.0, 13 * k), color=(0.25, 0.25, 0.25))
        if draw_legend and i == 0:
            _legend(page, k, data["limits"])
        pages += 1
    doc.save(str(out_path), garbage=3, deflate=True)
    doc.close()
    prog(1.0, "done")
    return {"pages": pages}


def _legend(page, k: float, limits: dict) -> None:
    """The legend box, top right of the first page."""
    import pymupdf
    from .domain.reports import COLOURS
    s = max(0.6, k)
    # 5.1.0 (D27, D28): the three placement states, each as it is drawn, and
    # the other markers the page draws (TER, IDF, COW, DIVA).
    rows = [("NER — critical", COLOURS["NER_CRITICAL"], "dot"),
            ("NER — non-critical", COLOURS["NER_NONCRITICAL"], "dot"),
            (f"{limits['general_m']:g} m reach (straight line)", (0.3, 0.3, 0.3), "dash"),
            (f"{limits['photographer_m']:g} m reach — photographers", (0.3, 0.3, 0.3), "dot-dash"),
            ("Wi-Fi point", COLOURS["WIRELESS"], "dot")]
    rows += [(f"{kind}", COLOURS.get(kind, (0.4, 0.4, 0.4)), "dot")
             for kind in ("TER", "IDF", "COW", "DIVA")]
    rows += [("Sheet confirmed", "confirmed", "state"),
             ("Sheet not confirmed — check it against its neighbours", "unconfirmed", "state"),
             ("Sheet contradicted — probably misplaced", "contradicted", "state")]
    w, h = 330 * s, (46 + len(rows) * 18) * s
    x0, y0 = page.rect.width - w - 20 * s, 80 * s
    r = pymupdf.Rect(x0, y0, x0 + w, y0 + h)
    page.draw_rect(r, color=(0, 0, 0), fill=(1, 1, 1), width=0.8, fill_opacity=0.92)
    page.insert_text(pymupdf.Point(x0 + 10 * s, y0 + 18 * s), "Legend", fontsize=11 * s,
                     fontname="hebo")
    for i, (txt, col, how) in enumerate(rows):
        y = y0 + (38 + i * 18) * s
        if how == "dot":
            page.draw_circle(pymupdf.Point(x0 + 18 * s, y - 4 * s), 5 * s, color=(0, 0, 0),
                             fill=col, width=0.5)
        elif how == "state":
            st = STATE_PDF[col]
            page.draw_line(pymupdf.Point(x0 + 4 * s, y - 4 * s), pymupdf.Point(x0 + 32 * s, y - 4 * s),
                           color=st["colour"], width=st["width"], dashes=st["dashes"])
        else:
            page.draw_line(pymupdf.Point(x0 + 8 * s, y - 4 * s), pymupdf.Point(x0 + 28 * s, y - 4 * s),
                           color=col, width=1.2, dashes="[6 4] 0" if how == "dash" else "[2 3] 0")
        page.insert_text(pymupdf.Point(x0 + 36 * s, y), txt, fontsize=9 * s)
