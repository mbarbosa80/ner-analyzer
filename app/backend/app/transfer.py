"""Hand a project to another computer (4.6.0).

Marcelo, 27 Oct 2026: a VTCM who has to stop, or pass a venue to a colleague,
should not leave the next person starting from zero — "poder exportar todo o
projeto no estado atual e permitir que outro VTCM importe e dê continuidade".

A **project package** is one ``.zip`` file:

* ``manifest.json`` — what it is: the format, the app version that wrote it,
  who exported it and when, the project's name, how many rows of each kind,
  every document with its SHA-256, and the summary of the last analysis (so
  the receiving computer can say whether its own run came out the same);
* ``data.json`` — every row of the project, table by table, with the ids it
  had on the exporting computer;
* ``files/drawings/<id>/<name>.pdf`` and ``files/teap/<id>/<name>`` — the
  design books and the TEAP workbooks as they were imported.

What it deliberately does **not** carry:

* accounts, passwords and sessions — the person who imports becomes the
  owner, and the project is private until they share it;
* the saved analysis itself — it holds ids and sheet keys of the exporting
  database; the analysis is run again on import (it is deterministic, so the
  same inputs give the same answer, and the import says whether they did);
* background jobs, and the installation's own settings (the criticality
  matrix, global aliases).

Importing never touches an existing project: it always creates a new one, with
new ids. The two copies are then independent — there is no merge. A package
is a **handover**, not a synchronisation.

The package is untrusted input, like any upload: only the members the
manifest lists are read, each one is checked against its SHA-256 and a size
ceiling, file names are flattened, only known columns of known tables are
written, and every value is coerced to its column's type.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import shutil
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (Alias, AuditLog, Drawing, DrawingSpace, Element, MappingTemplate,
                     NerAsset, NerConsolidation, NerNameHistory, Page, Project,
                     RegisterSnapshot, RouteSegmentRow, Scenario, SpaceMatchRow,
                     SpaceOccurrenceLink, TeapFile, TeapSpace, VerticalLinkRow, Visibility,
                     Zone)
from .version import __version__

FORMAT = "ner-analyzer-project"
#: Bumped only when an older app could no longer read what a newer one writes.
FORMAT_VERSION = 1

#: Ceiling on the whole package and on any one member, in MB.
MAX_PACKAGE_MB = int(__import__("os").environ.get("NER_MAX_IMPORT_MB", "4096"))
MAX_DATA_MB = 512

Progress = Optional[Callable[[float, str], None]]


class TransferError(ValueError):
    """A package that cannot be written or read — the message is for a person."""


# ---------------------------------------------------------------------------
# What is carried, in the order it is written back
# ---------------------------------------------------------------------------

#: table name → (model, {column: table it points at}). The order is the
#: insertion order: every table comes after the tables it points at.
#: ``ner_assets.merged_into_id`` points at its own table and is set in a
#: second pass.
TABLES: list[tuple[str, Any, dict[str, str]]] = [
    ("drawings", Drawing, {"project_id": "projects"}),
    ("pages", Page, {"drawing_id": "drawings"}),
    ("teap_files", TeapFile, {"project_id": "projects"}),
    ("drawing_spaces", DrawingSpace, {"project_id": "projects", "drawing_id": "drawings"}),
    ("ner_assets", NerAsset, {"project_id": "projects", "canonical_drawing_id": "drawings"}),
    ("elements", Element, {"project_id": "projects", "drawing_id": "drawings",
                           "ner_asset_id": "ner_assets",
                           "assigned_ner_asset_id": "ner_assets"}),
    ("teap_spaces", TeapSpace, {"project_id": "projects", "teap_file_id": "teap_files",
                                "assigned_ner_asset_id": "ner_assets",
                                "locked_drawing_space_id": "drawing_spaces"}),
    ("space_matches", SpaceMatchRow, {"project_id": "projects",
                                      "teap_space_id": "teap_spaces",
                                      "drawing_space_id": "drawing_spaces",
                                      "auto_drawing_space_id": "drawing_spaces"}),
    ("space_occurrence_links", SpaceOccurrenceLink, {"project_id": "projects",
                                                     "teap_space_id": "teap_spaces",
                                                     "drawing_space_id": "drawing_spaces"}),
    ("zones", Zone, {"project_id": "projects", "drawing_id": "drawings"}),
    ("route_segments", RouteSegmentRow, {"project_id": "projects", "drawing_id": "drawings"}),
    ("vertical_links", VerticalLinkRow, {"project_id": "projects",
                                         "lower_drawing_id": "drawings",
                                         "upper_drawing_id": "drawings"}),
    ("aliases", Alias, {"project_id": "projects"}),
    ("ner_name_history", NerNameHistory, {"ner_asset_id": "ner_assets"}),
    ("ner_consolidations", NerConsolidation, {"project_id": "projects",
                                              "primary_asset_id": "ner_assets",
                                              "merged_asset_id": "ner_assets"}),
    ("register_snapshots", RegisterSnapshot, {"project_id": "projects"}),
    ("audit_log", AuditLog, {"project_id": "projects"}),
]

#: A row that cannot exist without the row it points at: when that one is not
#: in the package, the row is left out (a nullable pointer is just cleared).
REQUIRED_POINTERS = {"pages": "drawing_id", "drawing_spaces": "drawing_id",
                     "teap_spaces": "teap_file_id", "space_matches": "teap_space_id",
                     "space_occurrence_links": "teap_space_id",
                     "ner_name_history": "ner_asset_id",
                     "ner_consolidations": "primary_asset_id"}

#: The audit log names its subject by kind and id; the id is renumbered when
#: the kind is one of these tables, and cleared otherwise.
AUDIT_ENTITY_TABLE = {
    "project": "projects", "drawing": "drawings", "page": "pages",
    "drawing_space": "drawing_spaces", "element": "elements", "ner_asset": "ner_assets",
    "teap_file": "teap_files", "teap_space": "teap_spaces", "space_match": "space_matches",
    "space_occurrence_link": "space_occurrence_links", "zone": "zones",
    "route_segment": "route_segments", "vertical_link": "vertical_links", "alias": "aliases",
}

#: Project columns that are the receiving computer's to set.
PROJECT_SKIP = {"id", "name", "owner_id", "visibility", "created_at"}

_FILE_MEMBER = re.compile(r"^files/(drawings|teap)/(\d+)/([^/\\]+)$")


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def _out(v: Any) -> Any:
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    return v


def _row(obj, skip: frozenset = frozenset()) -> dict:
    return {c.name: _out(getattr(obj, c.key)) for c in obj.__table__.columns
            if c.name not in skip}


def _coerce(col, v: Any, where: str) -> Any:
    """A value from the package, as its column's type — or a refusal."""
    if v is None:
        return None
    t = col.type
    try:
        if isinstance(t, Boolean):
            if isinstance(v, bool):
                return v
            if isinstance(v, int) and v in (0, 1):
                return bool(v)
            raise TypeError
        if isinstance(t, Integer):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
                raise TypeError
            return int(v)
        if isinstance(t, Float):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError
            return float(v)
        if isinstance(t, DateTime):
            if not isinstance(v, str):
                raise TypeError
            return _dt.datetime.fromisoformat(v)
        if isinstance(t, JSON):
            if not isinstance(v, (dict, list, str, int, float, bool)):
                raise TypeError
            return v
        if isinstance(t, (String, Text)):
            if not isinstance(v, str):
                raise TypeError
            limit = getattr(t, "length", None)
            return v[:limit] if limit else v
    except (TypeError, ValueError):
        raise TransferError(f"the package is damaged — {where} holds a value of the wrong "
                            f"kind. Nothing was imported.") from None
    return v


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v or "")[:3]
    return tuple(int(x) for x in parts) if parts else (0,)


def _safe_name(name: str) -> str:
    """A file name that cannot leave its folder or upset Windows."""
    base = Path(str(name).replace("\\", "/")).name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    return base[:180] or "file"


def package_filename(project: Project, when: Optional[_dt.datetime] = None) -> str:
    when = when or _dt.datetime.now()
    name = project.name or ""
    code = (project.venue_code or "").strip()
    # "VVV Venue - VVV" would say the code twice.
    said = bool(code) and re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])",
                                     name, re.IGNORECASE)
    label = name if not code or said else f"{code} {name}"
    label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._]+", "-", label).strip("-.")
    stem = re.sub(r"-{2,}", "-", stem)[:80] or f"project-{project.id}"
    return f"NER-project_{stem}_{when:%Y%m%d-%H%M}.zip"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_project(db: Session, project: Project, *, actor: str,
                   progress: Progress = None) -> dict:
    """Write the project's package into the export folder; return its name,
    size and SHA-256.

    Every row is read before anything else happens, in one read, so the
    package is the project at one moment even if someone keeps working while
    the books are copied in.
    """
    say = progress or (lambda f, s="": None)
    pid = project.id
    data: dict[str, list[dict]] = {"projects": [_row(project)]}
    ids: dict[str, set[int]] = {"projects": {pid}}

    def rows_of(name: str, model) -> list:
        if name == "pages":
            return list(db.execute(select(Page).join(Drawing)
                                   .where(Drawing.project_id == pid)
                                   .order_by(Page.id)).scalars())
        if name == "ner_name_history":
            return list(db.execute(select(NerNameHistory).join(
                NerAsset, NerAsset.id == NerNameHistory.ner_asset_id)
                .where(NerAsset.project_id == pid).order_by(NerNameHistory.id)).scalars())
        q = select(model).where(model.project_id == pid).order_by(model.id)
        if name == "elements":
            # Proposals of a scenario belong to that scenario, which is not carried.
            q = q.where(Element.scenario_id.is_(None))
        return list(db.execute(q).scalars())

    for name, model, _fk in TABLES:
        rows = rows_of(name, model)
        data[name] = [_row(r) for r in rows]
        ids[name] = {r.id for r in rows}
    templates = [_row(t, frozenset({"id"})) for t in db.execute(
        select(MappingTemplate).order_by(MappingTemplate.id)).scalars()]
    last = db.execute(select(Scenario).where(Scenario.project_id == pid,
                                             Scenario.name == "As-Is")).scalar_one_or_none()
    if last is not None:
        from . import services as S
        # When it was last *run* (4.8.0) — ``created_at`` is the scenario's
        # first save, weeks before; the import message quoted that date.
        analysis = {"summary": last.summary or {},
                    "created_at": S.scenario_saved_at(db, project, last) or _out(last.created_at),
                    "stale": bool(S.analysis_stale(db, project))}
    else:
        analysis = None

    # The documents, as stored.
    files: list[dict] = []
    for kind, rows in (("drawings", data["drawings"]), ("teap", data["teap_files"])):
        for r in rows:
            src = Path(r.get("stored_path") or "")
            if not src.is_file():
                if kind == "drawings":
                    raise TransferError(f"the stored file of the book '{r['filename']}' is "
                                        f"missing from this computer — the project cannot be "
                                        f"exported complete. Nothing was written.")
                continue                        # the TEAP's rows are in data.json
            files.append({"kind": kind, "id": r["id"], "src": src,
                          "member": f"files/{kind}/{r['id']}/{_safe_name(r['filename'])}"})

    out_dir = settings.exports_dir / f"project_{pid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / package_filename(project)
    tmp = final.with_suffix(".zip.part")
    exported_at = _dt.datetime.now(_dt.timezone.utc)
    total = sum(f["src"].stat().st_size for f in files) or 1
    done = 0
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
            listed = []
            for f in files:
                say(0.05 + 0.85 * done / total, f"adding {f['src'].name}")
                h = hashlib.sha256()
                size = 0
                # Books are already compressed; storing them is faster and as small.
                with open(f["src"], "rb") as src, z.open(
                        zipfile.ZipInfo(f["member"], date_time=exported_at.timetuple()[:6]),
                        "w", force_zip64=True) as dst:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        h.update(chunk)
                        dst.write(chunk)
                        size += len(chunk)
                done += size
                listed.append({"member": f["member"], "kind": f["kind"], "id": f["id"],
                               "bytes": size, "sha256": h.hexdigest()})
            say(0.92, "writing the project's rows")
            body = json.dumps({"tables": data, "mapping_templates": templates},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            z.writestr(zipfile.ZipInfo("data.json", date_time=exported_at.timetuple()[:6]),
                       body, compress_type=zipfile.ZIP_DEFLATED)
            manifest = {
                "format": FORMAT, "format_version": FORMAT_VERSION,
                "app_version": __version__,
                "exported_at": exported_at.isoformat(), "exported_by": actor,
                "project": {"id": pid, "name": project.name, "venue_code": project.venue_code,
                            "description": project.description},
                "counts": {k: len(v) for k, v in data.items()},
                "data_sha256": hashlib.sha256(body).hexdigest(),
                "files": listed,
                "analysis": analysis,
                "note": ("A copy of the project at the moment of export. Importing it creates a "
                         "new project; the two copies are independent from then on."),
            }
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        tmp.replace(final)
        # Only the newest package of a project is kept here: each one holds
        # every book of the venue, and they add up fast.
        for old in out_dir.glob("NER-project_*.zip"):
            if old != final:
                old.unlink(missing_ok=True)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    digest = _sha256(final)
    return {"filename": final.name, "bytes": final.stat().st_size, "sha256": digest,
            "counts": {k: len(v) for k, v in data.items()},
            "documents": len(files), "path": str(final)}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def read_manifest(path: Path) -> dict:
    """The package's manifest, checked — or a :class:`TransferError`."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise TransferError("this file is not a project package (not a readable .zip). "
                            "Nothing was imported.") from None
    with z:
        try:
            info = z.getinfo("manifest.json")
        except KeyError:
            raise TransferError("this .zip is not a project package of the NER Analyzer "
                                "(it has no manifest). Nothing was imported.") from None
        if info.file_size > 16 << 20:
            raise TransferError("the package's manifest is too large. Nothing was imported.")
        try:
            m = json.loads(z.read(info).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise TransferError("the package's manifest is damaged. Nothing was imported.") from None
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        raise TransferError("this .zip is not a project package of the NER Analyzer. "
                            "Nothing was imported.")
    fv = m.get("format_version")
    if not isinstance(fv, int) or fv > FORMAT_VERSION:
        raise TransferError(f"this package was written by a newer NER Analyzer "
                            f"({m.get('app_version', '?')}) in a format this one ({__version__}) "
                            f"cannot read — update the app on this computer, then import it.")
    if _version_tuple(str(m.get("app_version", ""))) > _version_tuple(__version__):
        raise TransferError(f"this package was exported by NER Analyzer {m.get('app_version')}; "
                            f"this computer runs {__version__}. Update the app here first, then "
                            f"import it — an older version would drop what it does not know.")
    if not isinstance(m.get("files"), list) or not isinstance(m.get("project"), dict):
        raise TransferError("the package's manifest is incomplete. Nothing was imported.")
    return m


def _unique_name(db: Session, wanted: str) -> str:
    wanted = (wanted or "").strip()[:180] or "Imported project"

    def taken(n: str) -> bool:
        return db.execute(select(Project.id).where(
            func.lower(Project.name) == n.lower())).first() is not None

    if not taken(wanted):
        return wanted
    base = f"{wanted} (imported {_dt.date.today():%Y-%m-%d})"
    if not taken(base):
        return base
    n = 2
    while taken(f"{base} {n}"):
        n += 1
    return f"{base} {n}"


def import_project(db: Session, package: Path, *, user, name: Optional[str] = None,
                   progress: Progress = None) -> dict:
    """Create a new project from a package. All or nothing: a package that
    fails any check leaves no project, no row and no file behind."""
    from . import services as S

    say = progress or (lambda f, s="": None)
    say(0.02, "checking the package")
    if package.stat().st_size > MAX_PACKAGE_MB << 20:
        raise TransferError(f"the package is larger than {MAX_PACKAGE_MB} MB. Nothing was imported.")
    m = read_manifest(package)

    staging = settings.data_dir / "imports" / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=True)
    target_dir: Optional[Path] = None
    try:
        with zipfile.ZipFile(package) as z:
            # data.json
            try:
                dinfo = z.getinfo("data.json")
            except KeyError:
                raise TransferError("the package has no data. Nothing was imported.") from None
            if dinfo.file_size > MAX_DATA_MB << 20:
                raise TransferError("the package's data is too large. Nothing was imported.")
            body = z.read(dinfo)
            if m.get("data_sha256") and hashlib.sha256(body).hexdigest() != m["data_sha256"]:
                raise TransferError("the package's data does not match its manifest (damaged or "
                                    "altered in transit). Nothing was imported.")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise TransferError("the package's data is damaged. Nothing was imported.") from None
            tables = payload.get("tables") if isinstance(payload, dict) else None
            if not isinstance(tables, dict) or not isinstance(tables.get("projects"), list) \
                    or len(tables["projects"]) != 1:
                raise TransferError("the package's data is incomplete. Nothing was imported.")

            # The documents: only those the manifest lists, each checked.
            staged: dict[tuple[str, int], tuple[Path, str]] = {}
            listed = [f for f in m["files"] if isinstance(f, dict)]
            total = sum(int(f.get("bytes") or 0) for f in listed) or 1
            done = 0
            for f in listed:
                member = str(f.get("member", ""))
                mm = _FILE_MEMBER.match(member)
                if not mm:
                    raise TransferError(f"the package lists a file it may not hold ({member!r}). "
                                        f"Nothing was imported.")
                try:
                    info = z.getinfo(member)
                except KeyError:
                    raise TransferError(f"the package is missing {Path(member).name}. "
                                        f"Nothing was imported.") from None
                if info.file_size > settings.max_upload_mb * 4 << 20:
                    raise TransferError(f"{Path(member).name} is larger than any book this app "
                                        f"accepts. Nothing was imported.")
                kind, old_id, fname = mm.group(1), int(mm.group(2)), _safe_name(mm.group(3))
                dest = staging / kind / str(old_id) / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                say(0.05 + 0.6 * done / total, f"checking {fname}")
                h = hashlib.sha256()
                size = 0
                with z.open(info) as src, open(dest, "wb") as out:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        size += len(chunk)
                        if size > info.file_size:
                            raise TransferError("the package is damaged. Nothing was imported.")
                        h.update(chunk)
                        out.write(chunk)
                done += size
                if f.get("sha256") and h.hexdigest() != f["sha256"]:
                    raise TransferError(f"{fname} does not match the copy that was exported "
                                        f"(damaged or altered in transit). Nothing was imported.")
                staged[(kind, old_id)] = (dest, fname)

        say(0.68, "creating the project")
        result = _write_rows(db, tables, payload.get("mapping_templates") or [], staged,
                             user=user, name=name or m["project"].get("name") or "")
        new_id = result["project_id"]
        target_dir = settings.uploads_dir / f"project_{new_id}"
        project = db.get(Project, new_id)
        S.audit(db, new_id, "project.imported", entity="project", entity_id=new_id,
                actor=user.username,
                payload={"from_app_version": m.get("app_version"),
                         "exported_by": m.get("exported_by"),
                         "exported_at": m.get("exported_at"),
                         "source_name": m["project"].get("name"),
                         "rows": result["rows"], "skipped": result["skipped"],
                         "documents": len(staged)},
                justification="project package imported — a copy, independent of the original")
        db.commit()
    except BaseException:
        db.rollback()
        if target_dir is not None:
            shutil.rmtree(target_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    # The analysis, run again here — and compared with the one exported.
    out = {"project_id": new_id, "name": project.name, "rows": result["rows"],
           "skipped": result["skipped"], "documents": len(staged),
           "exported_by": m.get("exported_by"), "exported_at": m.get("exported_at"),
           "from_app_version": m.get("app_version"), "analysis": None}
    source = m.get("analysis") if isinstance(m.get("analysis"), dict) else None
    if source is not None:
        say(0.75, "running the analysis again")
        try:
            res, ners = S.analyse(db, project, progress=lambda f, s="": say(0.75 + 0.2 * f, s))
            S.save_scenario(db, project, "As-Is", "as_is", res, ners,
                            actor=user.username)
            mine = res.summary()
            theirs = source.get("summary") or {}
            if source.get("stale"):
                # Something had changed after the exporter's last run: there
                # is nothing to compare with, only a fresh run on the data.
                out["analysis"] = {"same": None, "stale_at_export": True,
                                   "exported_at": source.get("created_at")}
            else:
                diff = {k: {"exported": theirs.get(k), "here": mine.get(k)}
                        for k in sorted(set(theirs) | set(mine))
                        if theirs.get(k) != mine.get(k)}
                out["analysis"] = {"same": not diff, "differences": diff,
                                   "exported_at": source.get("created_at")}
        except Exception as exc:                            # noqa: BLE001
            db.rollback()
            out["analysis"] = {"same": None, "error": str(exc)}
    say(1.0, "imported")
    return out


def _write_rows(db: Session, tables: dict, templates: list, staged: dict, *,
                user, name: str) -> dict:
    """Every row of the package, renumbered for this database. Flushed table by
    table; committed by the caller only when everything is in."""
    from . import services as S

    idmap: dict[str, dict[int, int]] = {}
    counts: dict[str, int] = {}
    skipped: dict[str, int] = {}

    # The project itself.
    src = tables["projects"][0]
    if not isinstance(src, dict):
        raise TransferError("the package's data is damaged. Nothing was imported.")
    cols = {c.name: c for c in Project.__table__.columns}
    p = Project(id=S.next_project_id(db), name=_unique_name(db, name),
                owner_id=user.id, visibility=Visibility.PRIVATE)
    for k, v in src.items():
        if k in cols and k not in PROJECT_SKIP:
            setattr(p, cols[k].key, _coerce(cols[k], v, f"projects.{k}"))
    db.add(p)
    db.flush()
    try:
        idmap["projects"] = {int(src.get("id")): p.id}
    except (TypeError, ValueError):
        raise TransferError("the package's data is damaged. Nothing was imported.") from None
    target_dir = settings.uploads_dir / f"project_{p.id}"

    merged_into: list[tuple[Any, int]] = []
    for tname, model, fks in TABLES:
        rows = tables.get(tname) or []
        if not isinstance(rows, list):
            raise TransferError(f"the package's data is damaged ({tname}). Nothing was imported.")
        cols = {c.name: c for c in model.__table__.columns}
        pairs: list[tuple[int, Any]] = []
        required = REQUIRED_POINTERS.get(tname)
        # Old id order is kept: the first book stays the first book, which is
        # what a row recorded without a book refers to.
        for i, r in enumerate(sorted((r for r in rows if isinstance(r, dict)),
                                     key=lambda r: r.get("id") if isinstance(r.get("id"), int) else 0)):
            old_id = r.get("id")
            if not isinstance(old_id, int):
                raise TransferError(f"the package's data is damaged ({tname}). Nothing was imported.")
            values: dict[str, Any] = {}
            drop = False
            for k, v in r.items():
                if k == "id" or k not in cols:
                    continue
                v = _coerce(cols[k], v, f"{tname}[{i}].{k}")
                if k in fks and v is not None:
                    v = idmap.get(fks[k], {}).get(v)
                    if v is None and (k == required or not cols[k].nullable):
                        drop = True
                        break
                values[cols[k].key] = v
            if tname == "elements" and r.get("scenario_id") is not None:
                drop = True
            if drop:
                skipped[tname] = skipped.get(tname, 0) + 1
                continue
            values.pop("scenario_id", None)
            if tname == "ner_assets":
                mi = values.pop("merged_into_id", None)
            if tname == "audit_log":
                table = AUDIT_ENTITY_TABLE.get(values.get("entity") or "")
                eid = values.get("entity_id")
                values["entity_id"] = idmap.get(table, {}).get(eid) if table and eid is not None else None
            if tname == "ner_consolidations":
                values["undo_snapshot"] = _renumber_snapshot(values.get("undo_snapshot"), idmap)
            if tname in ("drawings", "teap_files"):
                kind = "drawings" if tname == "drawings" else "teap"
                got = staged.get((kind, old_id))
                if got is None and tname == "drawings":
                    raise TransferError(f"the book '{values.get('filename')}' is not in the "
                                        f"package. Nothing was imported.")
                if got is not None:
                    dest = target_dir / got[1]
                    n = 1
                    while dest.exists():
                        dest = target_dir / f"{Path(got[1]).stem}_{n}{Path(got[1]).suffix}"
                        n += 1
                    target_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(got[0]), dest)
                    values["stored_path"] = str(dest)
                else:
                    values["stored_path"] = ""
            obj = model(**values)
            db.add(obj)
            pairs.append((old_id, obj))
            if tname == "ner_assets" and mi is not None:
                merged_into.append((obj, mi))
        db.flush()
        idmap[tname] = {old: obj.id for old, obj in pairs}
        counts[tname] = len(pairs)
    for obj, old in merged_into:
        obj.merged_into_id = idmap["ner_assets"].get(old)
    # The column-mapping templates travel too; a name already here is kept as it is.
    have = {n.lower() for n in db.execute(select(MappingTemplate.name)).scalars()}
    tcols = {c.name: c for c in MappingTemplate.__table__.columns}
    for t in templates if isinstance(templates, list) else []:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            continue
        if t["name"].lower() in have:
            continue
        db.add(MappingTemplate(**{tcols[k].key: _coerce(tcols[k], v, f"mapping_templates.{k}")
                                  for k, v in t.items() if k in tcols and k != "id"}))
        have.add(t["name"].lower())
    db.flush()
    return {"project_id": p.id, "rows": counts, "skipped": skipped}


def _renumber_snapshot(snap: Any, idmap: dict) -> Any:
    """The undo record of a consolidation names the markers and the room it
    moved; renumbered so Undo still works on the receiving computer."""
    if not isinstance(snap, dict):
        return snap
    out = dict(snap)
    if isinstance(out.get("occurrence_ids"), list):
        out["occurrence_ids"] = [idmap.get("elements", {}).get(i) for i in out["occurrence_ids"]
                                 if idmap.get("elements", {}).get(i) is not None]
    if out.get("previous_asset_id") is not None:
        out["previous_asset_id"] = idmap.get("ner_assets", {}).get(out["previous_asset_id"])
    return out
