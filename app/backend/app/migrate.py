"""Schema and data migration from the V1 element-per-marker model to the V2
canonical-NER model.

Design constraints this file exists to satisfy
----------------------------------------------
1. **Nothing is lost.** V1 rows are never deleted or rewritten beyond gaining a
   foreign key. If the migration is wrong, the V1 data is still there to remigrate
   from.
2. **Nothing is invented.** The migration copies what the drawing said. It does
   not upgrade a red symbol into a confirmed critical room, and it does not fill
   in a capacity that was never recorded.
3. **Nothing is merged silently.** Two occurrences are folded into one asset only
   on *unambiguous* evidence — identical normalised label, same level, same
   building. Everything weaker becomes a duplicate candidate a human has to
   answer. Each automatic fold is written to ``ner_consolidations`` with its
   evidence and an undo snapshot, so it can be inspected and reversed like any
   manual one.

Idempotent: safe to run on every start. A second run finds every element already
carrying ``ner_asset_id`` and does nothing.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from . import sheets as SH

from .domain.consolidation import (AUTO_MERGE_THRESHOLD, Candidate, compare,
                                   normalise_label)
from .models import (Base, Criticality, Element, KeepDecision, NerAsset,
                     NerConsolidation, NerStatus, Page, Project, SpaceMatchRow,
                     TeapSpace)

log = logging.getLogger(__name__)

#: Element kinds that become canonical assets in the register.
#:
#: **NERs only, since 2 Sep 2026.** A TER, an IDF and a COW used to get a
#: register row each, which put them in the same list as the rooms the study is
#: actually about — and, worse, in the "Served by" dropdown, where the engine
#: would happily have handed one of them a functional area.
#:
#: They have not been taken off the drawing. They are still extracted, still
#: drawn, still renamed, moved, locked and deleted on the **On the drawing**
#: tab and in the viewer, and you can still place new ones by hand. What they no
#: longer are is a *register entry*: nothing to classify, nothing to consolidate,
#: nothing to serve a space with. They are on the plan because the plan should
#: show what is in the building.
ASSET_KINDS = ("NER_CRITICAL", "NER_NONCRITICAL")

#: the migration links two markers without asking only at the domain module's
#: automatic threshold. Kept as an alias so there is exactly one number.
AUTO_LINK_THRESHOLD = AUTO_MERGE_THRESHOLD


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

#: columns added to pre-existing tables, as (table, column, DDL type + default)
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("elements", "ner_asset_id", "INTEGER"),
    ("elements", "link_status", "VARCHAR(20) DEFAULT 'unlinked'"),
    ("elements", "link_score", "FLOAT DEFAULT 0.0"),
    ("elements", "detection_method", "VARCHAR(40) DEFAULT ''"),
    ("elements", "symbol", "VARCHAR(40)"),
    ("elements", "colour", "VARCHAR(16)"),
    ("elements", "nearby_text", "TEXT DEFAULT ''"),
    ("elements", "document_kind", "VARCHAR(8) DEFAULT 'VDB'"),
    ("elements", "viewport", "VARCHAR(80)"),
    ("projects", "owner_id", "INTEGER"),
    ("projects", "visibility", "VARCHAR(16) DEFAULT 'private'"),
    # Existing projects must keep the results they already have: criticality
    # arrives as data, and only starts constraining assignments when someone
    # turns it on deliberately. Defaulting this to 1 would rewrite live studies.
    ("projects", "criticality_enforced", "BOOLEAN DEFAULT 0"),
    # The NER naming convention a project edits (2.7.0). NULL = the default.
    ("projects", "naming_convention", "TEXT"),
    # Fibre runs to the TER per NER (2.8.0): 2 per critical, 1 per non-critical.
    ("projects", "fibre_runs_critical", "INTEGER DEFAULT 2"),
    ("projects", "fibre_runs_noncritical", "INTEGER DEFAULT 1"),
    ("teap_spaces", "criticality_source", "VARCHAR(60)"),
    # The room a person chose for a space, overriding the nearest-compatible
    # answer. Nullable and empty by default: an existing study keeps every
    # assignment the engine made for it.
    ("teap_spaces", "assigned_ner_asset_id", "INTEGER"),
    ("teap_spaces", "assignment_reason", "TEXT DEFAULT ''"),
    ("teap_spaces", "assignment_by", "VARCHAR(80)"),
    ("teap_spaces", "assignment_at", "DATETIME"),
    # The NER the TEAP itself names for the space, when its sheet has such a
    # column. NULL on every existing row: no TEAP imported so far carried one.
    ("teap_spaces", "teap_serving_ner", "VARCHAR(200)"),
    # The drawing room a person tied this TEAP line to. Held here, on the TEAP
    # space, because ``space_matches`` is rebuilt by every matching run and this
    # decision must outlive it. Backfilled from the existing match rows by
    # ``adopt_match_decisions`` below, so a project mid-review loses nothing.
    ("teap_spaces", "locked_drawing_space_id", "INTEGER"),
    ("teap_spaces", "locked_verdict", "VARCHAR(20)"),
    ("teap_spaces", "locked_confirmed", "BOOLEAN DEFAULT 0"),
    ("teap_spaces", "locked_by", "VARCHAR(120)"),
    ("teap_spaces", "locked_at", "DATETIME"),
    ("teap_spaces", "locked_method", "VARCHAR(30) DEFAULT 'manual'"),
    # A register row with no position at all — a proposal read from a comments
    # tracker whose room is not on this drawing set yet. Defaults to 1 so every
    # existing row keeps the position it has.
    ("ner_assets", "position_known", "BOOLEAN DEFAULT 1"),
    # 10 Sep 2026. The person's declaration that the room they chose is on
    # another level than the space (the "other level" box). Off on every
    # existing row: no assignment made before this shipped crossed a page.
    ("teap_spaces", "assigned_cross_level", "BOOLEAN DEFAULT 0"),
    # The drawing number from the title block. NULL = never read; filled by
    # ``backfill_sheet_numbers`` on the next start for every page whose book is
    # still on disk.
    ("pages", "sheet_number", "VARCHAR(80)"),
    # 21 Sep 2026 (2.5.0). A wireless point's tie to the TEAP space whose
    # wireless port it stands in for, and who tied it. Existing points are
    # tied by ``backfill_wireless_points`` on the next start.
    ("elements", "space_key", "VARCHAR(300)"),
    ("elements", "tie_source", "VARCHAR(16)"),
    # 24 Sep 2026 (2.11.0). The NER a person chose for one wireless point.
    ("elements", "assigned_ner_asset_id", "INTEGER"),
    # 21 Sep 2026 (2.6.0). The matcher's own answer kept beside the person's
    # decision on every worklist row, so ``Undo`` can put it back without a
    # re-run. NULL ``auto_method`` = no run since 2.6.0; filled by the next
    # ``Run matching``, and Undo says so until then.
    ("space_matches", "auto_drawing_space_id", "INTEGER"),
    ("space_matches", "auto_method", "VARCHAR(30)"),
    ("space_matches", "auto_score", "FLOAT DEFAULT 0.0"),
    ("space_matches", "auto_confidence", "FLOAT DEFAULT 0.0"),
    ("space_matches", "auto_reason", "TEXT DEFAULT ''"),
    ("space_matches", "auto_confirmed", "BOOLEAN DEFAULT 0"),
    # 29 Sep 2026 (2.13.0). Key plans are illustrative. NULL = not decided;
    # ``backfill_key_plans`` reads it off the sheet title on the next start.
    ("pages", "key_plan", "BOOLEAN"),
    ("pages", "key_plan_source", "VARCHAR(16)"),
    # 29 Sep 2026 (2.14.0). Indoor or outdoor NER — it decides the kind of
    # rack the venue is sent. NULL = not said yet.
    ("ner_assets", "environment", "VARCHAR(16)"),
    # 16 Oct 2026 (4.1.0). Which book a zone, a route segment or a vertical
    # link is drawn on — with several books a page number alone names no
    # sheet. NULL = drawn when the project had one book: read as its first.
    ("zones", "drawing_id", "INTEGER"),
    ("route_segments", "drawing_id", "INTEGER"),
    ("vertical_links", "lower_drawing_id", "INTEGER"),
    ("vertical_links", "upper_drawing_id", "INTEGER"),
]


def ensure_schema(engine: Engine) -> list[str]:
    """Create new tables and add new columns to old ones. Returns what changed."""
    changed: list[str] = []
    insp = inspect(engine)
    before = set(insp.get_table_names())
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    for t in sorted(set(insp.get_table_names()) - before):
        changed.append(f"created table {t}")

    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table not in tables:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            changed.append(f"added {table}.{column}")
        # The indexes the models declare (2.17.0: every ``project_id`` and
        # the other foreign keys a screen filters by). ``create_all`` only
        # makes them for a table it creates; a database that predates them
        # gets them here. SQLite does not index a foreign key on its own, so
        # until now every "rows of this project" query read the whole table.
        for table_obj in Base.metadata.sorted_tables:
            if table_obj.name not in tables:
                continue
            have = {ix["name"] for ix in insp.get_indexes(table_obj.name)}
            for ix in table_obj.indexes:
                if ix.name in have:
                    continue
                ix.create(conn, checkfirst=True)
                changed.append(f"indexed {table_obj.name}({', '.join(c.name for c in ix.columns)})")
    return changed


# ---------------------------------------------------------------------------
# Duplicate evidence
#
# The rule itself lives in ``domain.consolidation`` so that the migration, the
# review queue and any later TVDB import all decide the same way. This wrapper
# only adapts a V1 ``Element`` to the shape that module compares.
# ---------------------------------------------------------------------------

def _candidate(e: Element, page_meta) -> Candidate:
    # The sheet, not the page number (4.1.0): with several books, page 2 of
    # one and page 2 of another are not "the same page".
    level, building = SH.meta_of(page_meta, e, (None, None))
    return Candidate(ref=e.id, label=e.label or "", kind=e.kind, page=SH.key_of(page_meta, e),
                     level=level, building=building, document_id=e.drawing_id,
                     x=e.x, y=e.y)


def occurrence_evidence(a: Element, b: Element, page_meta
                        ) -> tuple[float, list[str], list[str]]:
    """``(score, evidence, differences)`` for two V1 markers."""
    c = compare(_candidate(a, page_meta), _candidate(b, page_meta))
    return c.score, c.evidence, c.differences


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def is_retired(a: NerAsset) -> bool:
    """A room the register has been told to drop.

    It keeps its name for readability and traceability, but it no longer
    competes for automatic re-linking — see the note in :func:`backfill_assets`.
    """
    return (a.keep_decision == KeepDecision.REJECT
            or a.status == NerStatus.REJECTED)


def _next_code(db: Session, project_id: int) -> str:
    existing = db.execute(select(NerAsset.code)
                          .where(NerAsset.project_id == project_id)).scalars().all()
    n = 0
    for c in existing:
        if c and c.startswith("NER-"):
            try:
                n = max(n, int(c.split("-", 1)[1]))
            except ValueError:
                continue
    return f"NER-{n + 1:04d}"


def _suggested_classification(kind: str) -> tuple[str, list[str]]:
    if kind == "NER_CRITICAL":
        return Criticality.CRITICAL, ["label text read as a critical NER on the drawing"]
    if kind in ("NER_NONCRITICAL", "IDF", "COW"):
        return Criticality.NON_CRITICAL, ["label text read as a non-critical room"]
    return Criticality.PENDING, []


#: The detection methods whose NERs are named in sequence (2.14.0): what the
#: extractor read off the drawing — a team annotation, a TEC.003 room, a room
#: label. A marker inserted any other way keeps its label.
SEQUENTIAL_NAMED_METHODS = ("pdf_extraction", "drawing_room")


def _asset_from_element(db: Session, e: Element, page_meta,
                        existing_names: Optional[list[str]] = None) -> NerAsset:
    level, building = SH.meta_of(page_meta, e, (None, None))
    sug_class, class_ev = _suggested_classification(e.kind)
    # The name (2.14.0). A NER *read off the drawing* — a team annotation, a
    # TEC.003 room, a room label — is named in sequence, NERc01 … / NER01 …,
    # and what the sheet printed is kept as ``suggested_name`` ("printed
    # as"); one name, so the marker takes it too. A NER a person drew keeps
    # the name they typed.
    printed = e.label or None
    name = e.label or "unnamed"
    if (e.origin != "manual" and e.kind in ("NER_CRITICAL", "NER_NONCRITICAL")
            and e.detection_method in SEQUENTIAL_NAMED_METHODS):
        from . import ner_register as R
        names = existing_names if existing_names is not None else R.live_names(db, e.project_id)
        name = R.next_sequential_name(names, e.kind == "NER_CRITICAL")
        if existing_names is not None:
            existing_names.append(name)
        if not e.nearby_text and printed:
            e.nearby_text = printed
        e.label = name
        if printed and printed != name:
            class_ev = class_ev + [f"printed on the drawing as '{printed}'"]
    asset = NerAsset(
        project_id=e.project_id,
        code=_next_code(db, e.project_id),
        display_name=name,
        suggested_name=printed,
        kind=e.kind,
        # The drawing's own answer is the starting value, not "pending".
        #
        # ``_suggested_classification`` already reads it: a marker labelled
        # "Critical NER 1" arrives as CRITICAL with the evidence line to prove
        # where that came from. Storing PENDING as well left the register asking
        # a question the drawing had already answered, twenty-one times over —
        # and asking it while the coverage engine was *already* treating the room
        # as critical (``_asset_to_ner`` reads the marker kind). The screen was
        # less truthful than the analysis.
        #
        # ``classification_confirmed`` stays False, which is the fact that
        # actually matters for the audit: a human has not signed this off yet.
        # PENDING survives only for a marker whose kind says nothing.
        classification=sug_class,
        suggested_classification=sug_class,
        classification_confirmed=False,
        classification_evidence=class_ev + list(e.evidence or []),
        status=NerStatus.SUGGESTED if e.origin == "proposed" else NerStatus.IDENTIFIED,
        # A room drawn in the VDB is *there*. "Keep or reject?" is not an open
        # question about it — keeping is the existing state, and rejecting it is
        # a change request to the drawing team, made deliberately. Only a room
        # the app proposed has a genuinely undecided future.
        keep_decision=(KeepDecision.UNDECIDED if e.origin == "proposed"
                       else KeepDecision.KEEP),
        origin={"extracted": "vdb_detection", "manual": "manual",
                "proposed": "suggested"}.get(e.origin, "vdb_detection"),
        building=building, level=level,
        canonical_drawing_id=e.drawing_id, canonical_page=e.page,
        canonical_x=e.x, canonical_y=e.y, position_source="occurrence",
        locked=e.locked, movable=e.movable,
        total_ports=e.total_ports, used_ports=e.used_ports,
        reserved_ports=e.reserved_ports, switch_capacity=e.switch_capacity,
        patch_capacity=e.patch_capacity, growth_margin_pct=e.growth_margin_pct,
        power_available=e.power_available, cooling_available=e.cooling_available,
        space_available=e.space_available,
        security_constraints=e.security_constraints or "",
        access_constraints=e.access_constraints or "",
        confidence=e.confidence, notes=e.notes or "",
        updated_by="migration",
        aliases=[printed] if printed and printed != name else [],
    )
    db.add(asset)
    db.flush()
    return asset


def adopt_drawing_answers(db: Session, project: Project) -> dict:
    """Stop asking rooms already answered by the drawing.

    Registers built before this change hold ``classification = pending`` and
    ``keep_decision = undecided`` on every row, including rooms whose marker the
    extractor read as "Critical NER 1" — the answer was sitting in
    ``suggested_classification`` and the screen showed "Pending" beside it. This
    brings those rows up to what a fresh import would now produce.

    Deliberately conservative, so nothing a person decided is overwritten:

    * a classification is adopted only where it is still ``pending`` and the
      drawing actually proposed one — never over a value someone set;
    * ``classification_confirmed`` is left alone. Adopting the drawing's reading
      is not a human sign-off and must not be recorded as one;
    * ``keep_decision`` moves to KEEP only for a room that is on the drawing and
      still ``undecided``. A proposal keeps its open question, and an existing
      REJECT is a decision that stands.
    """
    rows = db.execute(select(NerAsset)
                      .where(NerAsset.project_id == project.id)).scalars().all()
    classified = kept = 0
    for a in rows:
        if (a.classification == Criticality.PENDING and a.suggested_classification
                and a.suggested_classification != Criticality.PENDING):
            a.classification = a.suggested_classification
            classified += 1
        if (a.keep_decision == KeepDecision.UNDECIDED
                and a.status != NerStatus.SUGGESTED and a.origin != "suggested"
                and a.deleted_at is None):
            a.keep_decision = KeepDecision.KEEP
            kept += 1
    if classified or kept:
        from .services import audit
        audit(db, project.id, "register.adopted_drawing_answers",
              payload={"classification_from_drawing": classified,
                       "keep_set_from_presence": kept},
              justification="rooms the drawing had already answered for")
    db.commit()
    return {"classification_from_drawing": classified, "keep_set_from_presence": kept,
            "examined": len(rows)}


def adopt_match_decisions(db: Session, project: Project) -> dict:
    """Move every decision already made in the worklist onto the TEAP space.

    Until now the tie between a TEAP line and a room on the drawing existed only
    in ``space_matches``, a table the matching step deletes and rebuilds. It was
    carried across a re-run by a snapshot taken inside that same function, which
    is a preservation that only holds while nothing else goes wrong.

    Running this once moves the answers somewhere the matching step cannot reach.
    It reads, it does not decide: a row is adopted only where a person had
    confirmed it, rejected it, or picked the room by hand. An automatic match
    nobody has looked at is left exactly as it is — locking those would sign off
    forty rooms on the reviewer's behalf, which is the opposite of the point.

    Idempotent: a TEAP space that already carries a verdict is never rewritten,
    so this can run on every start-up without ever overruling a later decision.
    """
    adopted_room = adopted_reject = 0
    rows = db.execute(
        select(SpaceMatchRow).where(SpaceMatchRow.project_id == project.id)).scalars().all()
    for m in rows:
        t = db.get(TeapSpace, m.teap_space_id)
        if t is None or t.locked_verdict:
            continue
        if m.rejected:
            t.locked_verdict = "rejected"
            t.locked_drawing_space_id = None
            t.locked_confirmed = True
            t.locked_by = m.confirmed_by or "user"
            t.locked_at = _dt.datetime.utcnow()
            adopted_reject += 1
        # Only what a PERSON decided (4.2.0). ``confirmed`` alone is also the
        # matcher's own sign-off on an unambiguous exact code — ``confirmed_by``
        # empty — and adopting those made every restart turn the matcher's
        # answers into "your decision": the RIV project carried 22 rows
        # "confirmed by you" that nobody had looked at.
        elif m.drawing_space_id is not None and (
                (m.confirmed and m.confirmed_by) or m.method == "manual"):
            t.locked_verdict = "assigned"
            t.locked_drawing_space_id = m.drawing_space_id
            t.locked_confirmed = bool(m.confirmed)
            t.locked_method = m.method or "manual"
            t.locked_by = m.confirmed_by or "user"
            t.locked_at = _dt.datetime.utcnow()
            adopted_room += 1
    if adopted_room or adopted_reject:
        from .services import audit
        audit(db, project.id, "matching.decisions_made_durable",
              payload={"rooms_locked": adopted_room, "rejections_locked": adopted_reject},
              justification="moved onto the TEAP space so a re-run cannot clear them")
    db.commit()
    return {"rooms_locked": adopted_room, "rejections_locked": adopted_reject,
            "examined": len(rows)}


#: The audit actions that carry a person's decision on a worklist row.
_HUMAN_MATCH_ACTIONS = ("match.decided", "match.undone")


def release_matcher_locks(db: Session, project: Project) -> dict:
    """Give back to the matcher the rows a restart signed off in a person's name
    (4.2.0).

    Until 4.1.0 :func:`adopt_match_decisions` locked every *confirmed* row,
    the matcher's own confirmations included, as ``locked_by = "user"``. A
    lock that no audit entry backs — no ``match.decided`` / ``match.undone``
    for that row, that TEAP space or that space code — was never a decision:
    it is released and the row shows the matcher's answer again ("confirmed by
    the matcher" when it was). A room chosen by hand (``manual``) and every
    lock with an audit entry behind it are left alone. Idempotent.
    """
    from .models import AuditLog
    from . import services as S
    codes: set[str] = set()
    tids: set[int] = set()
    mids: set[int] = set()
    for a in db.execute(select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action.in_(_HUMAN_MATCH_ACTIONS))).scalars():
        p = a.payload or {}
        if p.get("teap_code"):
            codes.add(str(p["teap_code"]))
        if p.get("teap_space_id") is not None:
            tids.add(int(p["teap_space_id"]))
        if a.entity_id is not None:
            mids.add(int(a.entity_id))
    # When the old start-up pass ran: its locks carry that moment.
    adopted_at = [a.at for a in db.execute(select(AuditLog).where(
        AuditLog.project_id == project.id,
        AuditLog.action == "matching.decisions_made_durable")).scalars() if a.at]
    if not adopted_at:
        db.commit()
        return {"matcher_locks_released": 0}
    rows = {m.teap_space_id: m for m in db.execute(select(SpaceMatchRow).where(
        SpaceMatchRow.project_id == project.id)).scalars()}
    released: list[str] = []
    for t in db.execute(select(TeapSpace).where(
            TeapSpace.project_id == project.id,
            TeapSpace.locked_verdict == "assigned")).scalars().all():
        if (t.locked_by or "") != "user" or (t.locked_method or "manual") == "manual":
            continue
        if not t.locked_at or not any(abs((t.locked_at.replace(tzinfo=None) - at.replace(tzinfo=None)).total_seconds()) <= 120
                                      for at in adopted_at):
            continue
        m = rows.get(t.id)
        if (t.space_code and t.space_code in codes) or t.id in tids or (m is not None and m.id in mids):
            continue
        if m is not None:
            S.undo_match_decision(db, m, actor="system")
        else:
            t.locked_verdict = None
            t.locked_drawing_space_id = None
            t.locked_confirmed = False
            t.locked_by = None
        released.append(t.space_code or t.space_name)
    if released:
        from .services import audit
        audit(db, project.id, "matching.matcher_locks_released", actor="system",
              payload={"released": released},
              justification="4.2.0: rows the matcher had confirmed were signed off in your "
                            "name by an earlier start-up; they are the matcher's answer again")
    db.commit()
    return {"matcher_locks_released": len(released)}


#: The marker a book's ``extract_summary`` carries once its space codes were
#: read in full (4.2.0).
CODES_PASS = "codes-4.2.0"
_CODE_TAIL_RX = re.compile(r"^([.\-]\d{1,3}(?:[.\-]\d{1,3})?)(?:\s+(.*))?$", re.S)


def repair_truncated_codes(db: Session, project: Project) -> dict:
    """Put back the space codes the two-digit reader cut (4.2.0).

    ``PEM.003.000-003`` was stored as code ``PEM.003`` with the name
    ``.000-003 Toilets - Unisex``. The tail is still in the name, so the code
    is rebuilt from the row itself — no book is read again. A TEAP line a
    person confirmed on such a room by its "exact" code keeps its room but
    loses the confirmation: it was given on a code the drawing does not print,
    and goes back to the Confirm queue. Once per book.
    """
    from .domain.pdf_ingest import SPACE_CODE_RX
    from .models import Drawing, DrawingSpace
    repaired: dict[int, str] = {}
    for d in db.execute(select(Drawing).where(Drawing.project_id == project.id)).scalars().all():
        summary = dict(d.extract_summary or {})
        if summary.get("codes_pass") == CODES_PASS:
            continue
        for ds in db.execute(select(DrawingSpace).where(DrawingSpace.drawing_id == d.id)).scalars():
            m = _CODE_TAIL_RX.match((ds.name or "").strip())
            if not (m and ds.space_code):
                continue
            full = ds.space_code + m.group(1)
            if not SPACE_CODE_RX.fullmatch(full):
                continue
            old = ds.space_code
            ds.space_code = full
            ds.name = (m.group(2) or "").strip() or full
            ds.evidence = list(ds.evidence or []) + [
                f"4.2.0: code read in full as {full} (was cut to {old})"]
            repaired[ds.id] = full
        summary["codes_pass"] = CODES_PASS
        d.extract_summary = summary
    unconfirmed: list[str] = []
    if repaired:
        for t in db.execute(select(TeapSpace).where(
                TeapSpace.project_id == project.id,
                TeapSpace.locked_verdict == "assigned",
                TeapSpace.locked_drawing_space_id.in_(list(repaired)))).scalars():
            if (t.locked_method or "") == "exact_code" and t.locked_confirmed \
                    and (t.space_code or "") != repaired[t.locked_drawing_space_id]:
                t.locked_confirmed = False
                unconfirmed.append(f"{t.space_code} → {repaired[t.locked_drawing_space_id]}")
        from .services import audit
        audit(db, project.id, "drawing.codes_repaired", actor="system",
              payload={"spaces": len(repaired), "confirmations_released": unconfirmed},
              justification="4.2.0: space codes with a three-digit sub-index were cut to their "
                            "base code; read in full. A confirmation given on the cut code goes "
                            "back to the Confirm queue")
    db.commit()
    return {"codes_repaired": len(repaired), "confirmations_released": len(unconfirmed)}


def set_aside_orphan_files(db: Session) -> dict:
    """Clear what deleted projects and failed uploads left on disk (4.2.0).

    A folder ``project_N`` under ``data/uploads`` or ``data/exports`` with no
    project N belongs to a deleted project: the deletion never took its files.
    Inside a live project, an upload no drawing and no TEAP file points at is
    a cancelled or failed import (a 44 MB book cancelled half-way stayed for
    good). The highest id seen is recorded first, so it is never handed out
    again.

    Nothing is deleted here: what was found is **moved** to
    ``data/set-aside/<time>/``, with a note saying what it is, so that the
    person who owns the machine decides. A start-up that deletes files on its
    own is not a thing to be wrong about. Idempotent; every move is in the
    audit log.
    """
    import shutil
    from .config import settings
    from .models import AppCounter, Drawing, TeapFile
    live = {pid for (pid,) in db.execute(select(Project.id))}
    # By file name within the project's folder, not by full path: a record whose
    # path could not be re-pointed must never cost the file it names.
    kept: dict[int, set[str]] = {}
    for model in (Drawing, TeapFile):
        for pid, path in db.execute(select(model.project_id, model.stored_path)):
            kept.setdefault(pid, set()).add(Path(str(path).replace("\\", "/")).name.lower())
    high = 0
    folders: list[str] = []
    files: list[str] = []
    import datetime as _dtm
    aside = settings.data_dir / "set-aside" / _dtm.datetime.now().strftime("%Y%m%d-%H%M%S")

    def _set_aside(src: Path, base: Path) -> bool:
        dest = aside / base.name / src.relative_to(base)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            return True
        except OSError:
            return False

    for base in (settings.uploads_dir, settings.exports_dir):
        if not base.is_dir():
            continue
        for d in base.iterdir():
            m = re.fullmatch(r"project_(\d+)", d.name)
            if not (m and d.is_dir()):
                continue
            n = int(m.group(1))
            high = max(high, n)
            if n not in live:
                if _set_aside(d, base):
                    folders.append(str(d))
            elif base == settings.uploads_dir:
                for f in list(d.iterdir()):
                    if f.is_file() and f.name.lower() not in kept.get(n, set()):
                        if _set_aside(f, base):
                            files.append(str(f))
    row = db.get(AppCounter, "project_id")
    if row is None:
        db.add(AppCounter(name="project_id", value=max(high, max(live or {0}))))
    elif row.value < high:
        row.value = high
    if folders or files:
        try:
            (aside / "WHAT-IS-THIS.txt").write_text(
                "NER Analyzer 4.2.0 moved these here at start-up. Nothing in the database\n"
                "points at them: the files of projects that were deleted, and uploads that\n"
                "failed or were cancelled half-way. The application never reads them.\n"
                "Keep them, or delete this folder to free the space.\n\n"
                + "\n".join(folders + files) + "\n", encoding="utf-8")
        except OSError:
            pass
        from .services import audit
        audit(db, None, "uploads.orphans_set_aside", actor="system", entity="installation",
              payload={"to": str(aside), "folders": folders, "files": files},
              justification="4.2.0: files of deleted projects and of failed or cancelled "
                            "uploads, which nothing in the database points at, moved "
                            "aside (not deleted)")
    db.commit()
    return {"orphan_folders": len(folders), "orphan_files": len(files)}


_RESURRECTED_PREFIX = "position: a removed NER stood here"


def _naive(t: _dt.datetime) -> _dt.datetime:
    """UTC, without tzinfo: the database keeps both kinds."""
    return t.astimezone(_dt.timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def flag_resurrected_ners(db: Session, project: Project) -> dict:
    """A live NER created where a removed one stood (4.2.1).

    Until 4.2.1 *Place NERs from the drawing* re-created a room a person had
    removed before 2.18.1 when it had no TEC code: its marker was gone and
    nothing held the spot (a softball project, 16 Oct 2026 20:59: NER34, NER36,
    NER37 and NER40 came back as NER_35.1–38.1). Nothing is removed here —
    the row gets a validation naming the removed room, until it is removed
    again (the fix keeps it removed from then on) or kept on purpose."""
    import math
    from . import services as S
    from .sheets import for_project
    sh = for_project(db, project.id)
    first = sh.drawing_ids[0] if sh.drawing_ids else None
    scales = S.scale_map(db, project.id)
    removed = [a for a in db.execute(select(NerAsset).where(
        NerAsset.project_id == project.id, NerAsset.deleted_at.is_not(None),
        NerAsset.merged_into_id.is_(None))).scalars() if a.position_known is not False]
    flagged = 0
    for a in db.execute(select(NerAsset).where(
            NerAsset.project_id == project.id, NerAsset.deleted_at.is_(None),
            NerAsset.merged_into_id.is_(None))).scalars():
        keep = [v for v in (a.pending_validations or []) if not v.startswith(_RESURRECTED_PREFIX)]
        if a.origin == "drawing_room" and a.created_at is not None:
            sc = scales.get(sh.key(a.canonical_drawing_id or first, a.canonical_page))
            limit = S.DRAWN_ROOM_SAME_PLACE_M / sc.metres_per_unit if sc else S.DRAWN_ROOM_SAME_PLACE_PT
            for g in removed:
                if (g.canonical_drawing_id or first) != (a.canonical_drawing_id or first) \
                        or g.canonical_page != a.canonical_page or g.deleted_at is None \
                        or _naive(g.deleted_at) >= _naive(a.created_at):
                    continue
                if a.space_code and g.space_code and a.space_code != g.space_code:
                    continue
                d = math.dist((g.canonical_x, g.canonical_y), (a.canonical_x, a.canonical_y))
                if d <= limit:
                    keep.append(f"{_RESURRECTED_PREFIX} — {g.display_name} was removed at this "
                                f"spot on {g.deleted_at:%Y-%m-%d} and this NER was created there "
                                f"afterwards by Place NERs from the drawing; if it is the same "
                                f"room, remove this one (it then stays removed)")
                    flagged += 1
                    break
        if keep != list(a.pending_validations or []):
            a.pending_validations = keep
    db.commit()
    return {"resurrected_ners_flagged": flagged}


_SAME_NAME_PREFIX = "name: another NER has the same name"


def flag_same_name_ners(db: Session, project: Project) -> dict:
    """Two live NERs with one name (4.2.0) — the rename that made them is
    refused now, but the ones already made stay. Each gets a validation on its
    row naming the other, until one is renamed or the two are consolidated."""
    from .ner_register import name_key
    live = [a for a in db.execute(select(NerAsset).where(
        NerAsset.project_id == project.id, NerAsset.deleted_at.is_(None),
        NerAsset.merged_into_id.is_(None))).scalars() if not is_retired(a)]
    groups: dict[str, list[NerAsset]] = {}
    for a in live:
        groups.setdefault(name_key(a.display_name), []).append(a)
    flagged = 0
    for a in live:
        twins = [o for o in groups.get(name_key(a.display_name), []) if o.id != a.id]
        keep = [v for v in (a.pending_validations or []) if not v.startswith(_SAME_NAME_PREFIX)]
        if twins:
            keep.append(f"{_SAME_NAME_PREFIX} ({', '.join(o.code for o in twins)}) — the two "
                        f"are counted as two NERs and the workbook cannot tell them apart: "
                        f"consolidate them if it is one room, or rename one")
            flagged += 1
        if keep != list(a.pending_validations or []):
            a.pending_validations = keep
    db.commit()
    return {"same_name_ners": flagged}


def backfill_assets(db: Session, project: Project) -> dict:
    """See :func:`_backfill_assets`. The evidence it writes names sheets by
    their drawing number in a project with several books (4.1.0)."""
    with SH.naming(SH.for_project(db, project.id)):
        return _backfill_assets(db, project)


def _backfill_assets(db: Session, project: Project) -> dict:
    """Give every equipment-room element in a project a canonical NER.

    Runs after any import that can produce markers, so the index has to include
    the NERs that already exist — otherwise the second drawing of a room would
    only ever be compared against the markers imported in the same batch, and
    would create a duplicate every time.
    """
    elements = db.execute(
        select(Element)
        .where(Element.project_id == project.id,
               Element.scenario_id.is_(None),
               Element.kind.in_(ASSET_KINDS))
        .order_by(Element.page, Element.id)
    ).scalars().all()
    todo = [e for e in elements if e.ner_asset_id is None]
    if not todo:
        return {"project": project.name, "created": 0, "linked": 0,
                "auto_merged": 0, "candidates": 0}

    pages = db.execute(select(Page).join(Page.drawing)
                       .where(Page.drawing.has(project_id=project.id))).scalars().all()
    sh = SH.for_project(db, project.id)
    page_meta = SH.PageMeta(sh, {sh.key(p.drawing_id, p.number): (p.level, p.building)
                                 for p in pages})

    # Two indexes, and the split matters.
    #
    # A rejected room keeps its display name — the register would be unreadable
    # if it did not — but it must stop *competing* for automatic re-linking.
    # Renumbering is normal in this workflow: reject NER 007, then rename the
    # last room to NER 007. With one index both assets answer to that label, on
    # the same level and in the same building, so the scores tie and the
    # tie-break is arbitrary — and a new marker can be linked to the room that
    # was deleted, silently resurrecting it. That is the worst available answer.
    #
    # So a rejected asset retires its label: it is still compared, but only ever
    # to raise a question.
    index: dict[str, list[tuple[NerAsset, Candidate]]] = {}
    retired: dict[str, list[tuple[NerAsset, Candidate]]] = {}
    for a in db.execute(select(NerAsset)
                        .where(NerAsset.project_id == project.id)).scalars():
        if a.deleted_at is not None or a.merged_into_id is not None:
            continue
        cand = Candidate(ref=f"A{a.id}", label=a.display_name, kind=a.kind,
                         page=sh.of_asset(a), level=a.level, building=a.building,
                         document_id=a.canonical_drawing_id, x=a.canonical_x,
                         y=a.canonical_y)
        target = retired if is_retired(a) else index
        target.setdefault(normalise_label(a.display_name), []).append((a, cand))
        # The label the drawing printed (2.14.0): "NER 21" written on two
        # sheets is one room, whatever the register now calls it.
        if a.suggested_name and normalise_label(a.suggested_name) != normalise_label(a.display_name):
            printed_cand = Candidate(ref=cand.ref, label=a.suggested_name, kind=cand.kind,
                                     page=cand.page, level=cand.level, building=cand.building,
                                     document_id=cand.document_id, x=cand.x, y=cand.y)
            target.setdefault(normalise_label(a.suggested_name), []).append((a, printed_cand))

    created = linked = auto_merged = candidates = resurrections = 0
    from . import ner_register as R
    names = R.live_names(db, project.id)
    # Reading order — page, then top to bottom, then left to right — so the
    # sequence the names follow is the one a person reads the sheet in.
    todo.sort(key=lambda e: (sh.of(e), round(e.y / 20.0), e.x, e.id))

    for e in todo:
        cand = _candidate(e, page_meta)
        key = normalise_label(e.label)
        best = None
        for asset, other in index.get(key, []):
            cmp_ = compare(other, cand)
            if best is None or cmp_.score > best[1].score:
                best = (asset, cmp_)

        if best and best[1].auto_mergeable:
            asset, cmp_ = best
            e.ner_asset_id = asset.id
            e.link_status = "auto_linked"
            e.link_score = cmp_.score
            e.detection_method = e.detection_method or "v1_migration"
            asset.confidence = max(asset.confidence, e.confidence)
            if (e.origin != "manual" and e.label != asset.display_name
                    and e.detection_method in SEQUENTIAL_NAMED_METHODS):
                # One name: the second drawing of the room is labelled as
                # the register names it; what it printed stays on record.
                if not e.nearby_text:
                    e.nearby_text = e.label
                e.label = asset.display_name
            db.add(NerConsolidation(
                project_id=project.id, primary_asset_id=asset.id,
                merged_asset_id=None, decision="merged", method="auto",
                score=cmp_.score, evidence=cmp_.evidence, differences=cmp_.differences,
                undo_snapshot={"occurrence_ids": [e.id], "previous_asset_id": None},
                justification="occurrence linked to an existing NER on identical "
                              "label, level and building",
                actor="migration"))
            linked += 1
            auto_merged += 1
            continue

        asset = _asset_from_element(db, e, page_meta, names)
        e.ner_asset_id = asset.id
        e.link_status = "unlinked"
        e.link_score = 1.0
        e.detection_method = e.detection_method or "v1_migration"

        # Does this marker look like a room somebody rejected? Never link it —
        # say so instead. A drawing that still shows a room the design dropped is
        # exactly the thing a revision review exists to catch.
        ghost = None
        for other, other_cand in retired.get(key, []):
            cmp_ghost = compare(other_cand, cand)
            if ghost is None or cmp_ghost.score > ghost[1].score:
                ghost = (other, cmp_ghost)
        if ghost and ghost[1].is_candidate:
            other, cmp_ghost = ghost
            asset.pending_validations = list(asset.pending_validations or []) + [
                f"“{other.display_name}” ({other.code}) was rejected in this "
                f"project and the drawing still shows this label — confirm this "
                f"is a different room, not a removal that was not carried out"]
            db.add(NerConsolidation(
                project_id=project.id, primary_asset_id=other.id,
                merged_asset_id=asset.id, decision="pending", method="auto",
                score=cmp_ghost.score, evidence=cmp_ghost.evidence,
                differences=cmp_ghost.differences + ["the earlier room was rejected"],
                justification="a rejected NER shares this label — needs a human",
                actor="migration"))
            resurrections += 1
        new_cand = Candidate(ref=f"A{asset.id}", label=asset.display_name, kind=asset.kind,
                             page=sh.of_asset(asset), level=asset.level,
                             building=asset.building, document_id=asset.canonical_drawing_id,
                             x=asset.canonical_x, y=asset.canonical_y)
        if normalise_label(asset.display_name) != key:
            # Under the printed label, compared as the printed label.
            index.setdefault(key, []).append((asset, Candidate(
                ref=new_cand.ref, label=cand.label, kind=new_cand.kind, page=new_cand.page,
                level=new_cand.level, building=new_cand.building,
                document_id=new_cand.document_id, x=new_cand.x, y=new_cand.y)))
        index.setdefault(normalise_label(asset.display_name), []).append((asset, new_cand))
        created += 1
        linked += 1

        if best and best[1].is_candidate:
            # Similar enough to ask about, not similar enough to assume.
            other, cmp_ = best
            db.add(NerConsolidation(
                project_id=project.id, primary_asset_id=other.id,
                merged_asset_id=asset.id, decision="pending", method="auto",
                score=cmp_.score, evidence=cmp_.evidence, differences=cmp_.differences,
                justification="possible duplicate — needs a human decision",
                actor="migration"))
            candidates += 1

    db.commit()
    # Registers built before the drawing's answers were adopted still carry
    # "pending" and "undecided" on rows the drawing had already answered. Bring
    # them up to what a fresh import produces, here, so nobody has to know a
    # maintenance step exists.
    adopted = adopt_drawing_answers(db, project)
    return {"project": project.name, "created": created, "linked": linked,
            "auto_merged": auto_merged, "candidates": candidates,
            "rejected_label_reused": resurrections, **adopted}


def backfill_sheet_numbers(db: Session, project: Project) -> dict:
    """Read the drawing number off every page that was imported before it was
    read at all — once.

    The title block is opened by its labels (``DRAWING NUMBER``, ``DRAWING
    TITLE``), so where it is found the sheet title and the level are taken from
    it too: the earlier font-size guess had put a room label down as the title
    of one page and no level on any. A page with no block, or whose book is no
    longer on disk, is marked ``""`` — looked, found nothing — so a 45 MB book
    is not re-read on every start for a number it does not carry.
    """
    from pathlib import Path

    from .domain.pdf_ingest import read_title_blocks

    filled, blank, missing = 0, 0, 0
    for d in project.drawings:
        pages = [pg for pg in d.pages if pg.sheet_number is None]
        if not pages:
            continue
        if not Path(d.stored_path).exists():
            for pg in pages:
                pg.sheet_number = ""
            missing += len(pages)
            db.commit()
            continue
        try:
            blocks = read_title_blocks(d.stored_path, [pg.number for pg in pages])
        except Exception as exc:                      # a damaged file must not stop start-up
            for pg in pages:
                pg.sheet_number = ""
            missing += len(pages)
            db.commit()
            log.warning("sheet numbers: could not read %s: %s", d.filename, exc)
            continue
        for pg in pages:
            tb = blocks.get(pg.number)
            if tb is None or not tb.number:
                pg.sheet_number = ""
                blank += 1
                continue
            pg.sheet_number = tb.number
            if tb.title:
                pg.sheet_title = tb.title
                if pg.key_plan_source != "manual":
                    from .domain.drawn_rooms import is_illustrative_title
                    pg.key_plan = is_illustrative_title(tb.title)
                    pg.key_plan_source = "title"
            if tb.level:
                pg.level = tb.level
            filled += 1
        # One commit per book: a 45 MB book takes half a minute to read, and
        # the work done on it must survive the process being stopped before
        # the next one is opened.
        db.commit()
    return {"sheet_numbers_read": filled, "sheet_numbers_blank": blank,
            "sheet_numbers_file_missing": missing}


#: The extraction pass that reads room names off a sheet with no space code.
#: Stamped into ``Drawing.extract_summary`` so a book is read again for it
#: exactly once, whatever the outcome.
NAME_ONLY_PASS = "name-only-2.4.1"


def backfill_name_only_spaces(db: Session, project: Project) -> dict:
    """Read the spaces of a book that produced none, with the name-only pass — once.

    Before 2.4.1 a sheet with no space code yielded no space at all, and the
    matching step then refused to run on the book. Re-importing the book is
    not the answer: it would double every page and every NER marker, and the
    NER markers may already carry the person's confirmations and locks. So
    the spaces alone are read again here, for a book with **zero** spaces
    and no stamp, and inserted exactly as an import would have inserted them.
    A book that still yields nothing is stamped too, so it is not re-read on
    every start. The markers are not touched.
    """
    from pathlib import Path

    from .domain.pdf_ingest import extract_drawing
    from .models import AuditLog, DrawingSpace

    read, found, skipped = 0, 0, 0
    for d in project.drawings:
        summary = dict(d.extract_summary or {})
        if summary.get("name_only_pass") == NAME_ONLY_PASS:
            continue
        has_spaces = db.execute(select(DrawingSpace.id).where(
            DrawingSpace.drawing_id == d.id).limit(1)).first() is not None
        if has_spaces or not Path(d.stored_path).exists():
            summary["name_only_pass"] = NAME_ONLY_PASS
            d.extract_summary = summary
            skipped += 1
            db.commit()
            continue
        try:
            extract = extract_drawing(d.stored_path)
        except Exception as exc:                      # a damaged file must not stop start-up
            log.warning("name-only spaces: could not read %s: %s", d.filename, exc)
            summary["name_only_pass"] = NAME_ONLY_PASS
            d.extract_summary = summary
            skipped += 1
            db.commit()
            continue
        for s in extract.spaces:
            db.add(DrawingSpace(project_id=project.id, drawing_id=d.id, page=s.page,
                                space_code=s.space_code, name=s.name, x=s.x, y=s.y,
                                area_label=s.area_label, confidence=s.confidence,
                                origin="extracted", evidence=s.evidence))
        summary["spaces"] = len(extract.spaces)
        summary["name_only_pass"] = NAME_ONLY_PASS
        d.extract_summary = summary
        db.add(AuditLog(project_id=project.id, action="drawing.spaces_backfilled",
                        entity="drawing", entity_id=d.id, actor="system",
                        payload={"pass": NAME_ONLY_PASS, "spaces": len(extract.spaces)}))
        read += 1
        found += len(extract.spaces)
        db.commit()
    return {"name_only_books_read": read, "name_only_spaces_found": found,
            "name_only_books_skipped": skipped}


def backfill_all_name_only_spaces(session_factory) -> dict:
    """Every project, in its own session — for the same background thread as
    the sheet numbers, and for the same reason: a real book takes seconds to
    read and the watchdog must not see the server silent meanwhile."""
    db = session_factory()
    totals = {"name_only_books_read": 0, "name_only_spaces_found": 0,
              "name_only_books_skipped": 0}
    try:
        for project in db.execute(select(Project)).scalars().all():
            for k, v in backfill_name_only_spaces(db, project).items():
                totals[k] += v
    except Exception as exc:                          # noqa: BLE001 — never take the app down
        log.warning("name-only spaces: backfill stopped: %s", exc)
    finally:
        db.close()
    return totals


def backfill_all_sheet_numbers(session_factory) -> dict:
    """Every project, in its own session — meant for a background thread.

    Reading the title blocks of a real book takes about a second a page
    (measured: a 38-page canoe-slalom venue's book (OWC) in ~35 s), and the
    watchdog restarts a server that has not answered for a minute. So this is
    not on the start-up path: ``main.lifespan`` starts it after the schema is
    in place and the application is already answering. Each book commits on
    its own, so a restart mid-way loses nothing already read.
    """
    db = session_factory()
    totals = {"sheet_numbers_read": 0, "sheet_numbers_blank": 0,
              "sheet_numbers_file_missing": 0}
    try:
        for project in db.execute(select(Project)).scalars().all():
            for k, v in backfill_sheet_numbers(db, project).items():
                totals[k] += v
    except Exception as exc:                          # noqa: BLE001 — never take the app down
        log.warning("sheet numbers: backfill stopped: %s", exc)
    finally:
        db.close()
    return totals


def backfill_wireless_points(db: Session, project: Project) -> dict:
    """Bring the wireless points drawn before 2.5.0 up to the 2.5.0 shape — once.

    Two things, both idempotent. The label: ``WP-3`` becomes ``AP-3`` (every
    point placed before 2.5.0 was an indoor one — there was no other kind),
    keeping the number, so nothing anyone wrote down about ``WP-3`` is lost
    and the new numbering carries on from there. The tie: a point never tied
    to a TEAP space (NULL/NULL) gets the same proposal a newly placed point
    gets — the nearest matched room on its sheet — or stays untied, and
    either way is stamped so this is not asked again. A manual tie is never
    touched. Audited per point.
    """
    import re

    from . import services as S
    from .models import AuditLog

    renamed, tied, untied = 0, 0, 0
    rows = db.execute(select(Element).where(
        Element.project_id == project.id, Element.scenario_id.is_(None),
        Element.kind.in_(("WIRELESS", "WIRELESS_OUTDOOR")))).scalars().all()
    for e in rows:
        m = re.fullmatch(r"WP-(\d+)", e.label or "")
        if m and e.kind == "WIRELESS":
            old = e.label
            e.label = f"WIFI-{m.group(1)}"
            db.add(AuditLog(project_id=project.id, action="element.updated", entity="element",
                            entity_id=e.id, actor="system",
                            justification="2.5.0: wireless points are numbered per kind",
                            payload={"label": e.label, "was": old}))
            renamed += 1
        if e.space_key is None and e.tie_source is None:
            tie = S.propose_wireless_tie(db, project, SH.for_project(db, project.id).of(e), e.x, e.y)
            if tie:
                e.space_key = tie["space_key"]
                e.tie_source = "auto"
                e.evidence = list(e.evidence or []) + [
                    f"tied to {tie['space_name']} — nearest matched room on this sheet"
                    + (f", {tie['distance_m']} m from its label" if tie["distance_m"] is not None else "")]
                tied += 1
            else:
                e.tie_source = "auto"      # looked, found nothing; not asked again
                untied += 1
            db.add(AuditLog(project_id=project.id, action="element.updated", entity="element",
                            entity_id=e.id, actor="system",
                            justification="2.5.0: wireless point tied to the TEAP space it stands in for",
                            payload={"space_key": e.space_key, "tie_source": e.tie_source}))
    if renamed or tied or untied:
        db.commit()
    return {"wireless_renamed": renamed, "wireless_tied": tied, "wireless_untied": untied}


def backfill_key_plans(db: Session, project: Project) -> dict:
    """Decide, once, which pages of a book imported before 2.13.0 are key
    plans — from the sheet title already stored (the title block's DRAWING
    TITLE), so no PDF is opened. A page someone switched by hand is never
    touched. Cheap: runs on every start, and finds nothing to do after the
    first."""
    from .domain.drawn_rooms import is_illustrative_title
    from .models import AuditLog

    decided, keys = 0, 0
    for d in project.drawings:
        for pg in d.pages:
            if pg.key_plan is None:
                pg.key_plan = is_illustrative_title(pg.sheet_title)
                pg.key_plan_source = "title"
                decided += 1
                keys += int(pg.key_plan)
            elif (pg.key_plan_source != "manual" and not pg.key_plan
                  and is_illustrative_title(pg.sheet_title)):
                # 2.14.0 widened the default to the index, information,
                # abbreviations and typical-solutions sheets. A page the
                # person decided by hand keeps their answer.
                pg.key_plan = True
                decided += 1
                keys += 1
    if decided:
        db.add(AuditLog(project_id=project.id, action="page.key_plans_read", actor="system",
                        payload={"pages_decided": decided, "key_plans": keys},
                        justification="2.13.0: key plans are illustrative"))
        db.commit()
    return {"key_plan_pages_decided": decided, "key_plans": keys}


def cleanup_spaces_2140(db: Session, project: Project) -> dict:
    """Bring a book's spaces up to the 2.14.0 extraction — once per book.

    Two rules that the extraction now applies, applied here to what is
    already stored: a sheet that only illustrates (a key plan) has no
    spaces, and a name-only label is a space only when it reads as a known
    space name (the AAM list plus the project's TEAP). A space a TEAP line is
    tied to — by the matcher or by hand — is never touched, whatever it is
    called: the tie is the person's work. Everything removed is listed in the
    audit log, name by name.
    """
    from . import services as S
    from .domain.aam_vocab import SpaceVocabulary, strip_length_tag
    from .models import AuditLog, DrawingSpace, SpaceMatchRow, SpaceOccurrenceLink, TeapSpace

    removed_junk = removed_key = renamed = 0
    names_removed: list[str] = []
    for d in project.drawings:
        summary = dict(d.extract_summary or {})
        if summary.get("spaces_pass") == S.SPACES_PASS:
            continue
        key_pages = {pg.number for pg in d.pages if pg.key_plan}
        known = [n for n in db.execute(select(TeapSpace.space_name).where(
            TeapSpace.project_id == project.id)).scalars() if n]
        vocab = SpaceVocabulary(known)
        tied: set[int] = set()
        tied.update(db.execute(select(SpaceMatchRow.drawing_space_id).where(
            SpaceMatchRow.project_id == project.id,
            SpaceMatchRow.drawing_space_id.is_not(None))).scalars())
        tied.update(db.execute(select(TeapSpace.locked_drawing_space_id).where(
            TeapSpace.project_id == project.id,
            TeapSpace.locked_drawing_space_id.is_not(None))).scalars())
        tied.update(db.execute(select(SpaceOccurrenceLink.drawing_space_id).where(
            SpaceOccurrenceLink.project_id == project.id)).scalars())
        for sp in db.execute(select(DrawingSpace).where(
                DrawingSpace.drawing_id == d.id, DrawingSpace.origin == "extracted")).scalars():
            if sp.id in tied or sp.confirmed:
                continue
            if sp.page in key_pages:
                names_removed.append(f"p{sp.page} {sp.space_code or sp.name} (key plan)")
                db.delete(sp)
                removed_key += 1
                continue
            if sp.space_code:
                continue
            if not vocab.is_space_name(sp.name or ""):
                names_removed.append(f"p{sp.page} {sp.name}")
                db.delete(sp)
                removed_junk += 1
                continue
            clean = strip_length_tag(sp.name or "")
            if clean and clean != sp.name:
                sp.name = clean
                renamed += 1
        summary["spaces_pass"] = S.SPACES_PASS
        d.extract_summary = summary
        db.flush()
        if removed_junk or removed_key or renamed:
            db.add(AuditLog(project_id=project.id, action="drawing.spaces_cleaned",
                            entity="drawing", entity_id=d.id, actor="migration",
                            payload={"removed_not_a_space_name": removed_junk,
                                     "removed_on_key_plan": removed_key, "renamed": renamed,
                                     "names": names_removed[:500]},
                            justification="2.14.0: a name-only label is a space only when it "
                                          "reads as a known space name; a key plan has none"))
        db.commit()
    return {"spaces_removed_not_a_name": removed_junk, "spaces_removed_key_plan": removed_key,
            "spaces_renamed": renamed}


def fold_outdoor_wireless(db: Session, project: Project) -> dict:
    """One kind of access point (2.14.0): every ``WIRELESS_OUTDOOR`` point
    becomes ``WIRELESS`` and the points are numbered ``AP-1`` … in reading
    order, once, where any still carries an ``AP-I-n`` / ``AP-E-n`` label."""
    from .domain.pdf_ingest import LEGACY_WIRELESS_OUTDOOR
    from .models import AuditLog

    points = db.execute(select(Element).where(
        Element.project_id == project.id, Element.scenario_id.is_(None),
        Element.kind.in_(("WIRELESS", LEGACY_WIRELESS_OUTDOOR)))
        .order_by(Element.page, Element.id)).scalars().all()
    folded = sum(1 for e in points if e.kind == LEGACY_WIRELESS_OUTDOOR)
    old_style = [e for e in points if re.fullmatch(r"AP-[IE]-\d+", e.label or "")]
    if not folded and not old_style:
        return {"wireless_folded": 0, "wireless_renumbered": 0}
    renamed: list[dict] = []
    for e in points:
        if e.kind == LEGACY_WIRELESS_OUTDOOR:
            e.kind = "WIRELESS"
    if old_style:
        for n, e in enumerate(points, start=1):
            new = f"WIFI-{n}"
            if e.label != new:
                renamed.append({"id": e.id, "from": e.label, "to": new, "page": e.page})
                e.label = new
    db.add(AuditLog(project_id=project.id, action="wireless.one_kind", entity="project",
                    entity_id=project.id, actor="migration",
                    payload={"folded": folded, "renamed": renamed[:500]},
                    justification="2.14.0: one kind of access point — indoor and outdoor "
                                  "are not told apart any more"))
    db.commit()
    return {"wireless_folded": folded, "wireless_renumbered": len(renamed)}


def wifi_points_430(db: Session, project: Project) -> dict:
    """The access points become Wi-Fi points (4.3.0, every start, idempotent).

    Marcelo, 19 Oct 2026: *"não marque mais os AP como AP e sim como Wi-Fi
    somente. Pois não quero mais associar isso com qtde de AP"* — a reviewer had
    counted the AP markers on a marked-up PDF and read them as the number of
    access points requested. Two things:

    * the label ``AP-n`` becomes ``WIFI-n``, keeping the number;
    * a space that holds more than one point **placed from the TEAP** keeps
      one — the oldest, the one most likely already dragged into place — and
      loses the rest, because the placing step now draws one Wi-Fi point per
      space with wireless, not one per DWISA unit. A point a person drew or
      tied by hand is never removed.

    No port changes: since 4.0.0 a point carries none; the DWISA line of the
    space is its wireless port, before and after. Audited per project.
    """
    from .domain.pdf_ingest import LEGACY_WIRELESS_LABEL_RX
    from .models import AuditLog

    points = db.execute(select(Element).where(
        Element.project_id == project.id, Element.kind == "WIRELESS")
        .order_by(Element.id)).scalars().all()
    renamed: list[dict] = []
    for e in points:
        m = re.fullmatch(LEGACY_WIRELESS_LABEL_RX, e.label or "")
        if m:
            renamed.append({"id": e.id, "from": e.label, "to": f"WIFI-{m.group(1)}"})
            e.label = f"WIFI-{m.group(1)}"
    by_space: dict[tuple, list[Element]] = {}
    for e in points:
        if e.scenario_id is None and e.space_key:
            by_space.setdefault((e.space_key,), []).append(e)
    removed: list[dict] = []
    for (key,), group in by_space.items():
        if len(group) <= 1:
            continue
        # The placing step's own rule: one point per space; only points it
        # placed are taken back, newest first.
        extra = len(group) - 1
        for e in sorted((x for x in group if x.origin == "teap"),
                        key=lambda x: x.id, reverse=True)[:extra]:
            removed.append({"id": e.id, "label": e.label, "space_key": key, "page": e.page})
            db.delete(e)
    if not renamed and not removed:
        return {"wifi_renamed": 0, "wifi_extra_removed": 0}
    db.add(AuditLog(project_id=project.id, action="wireless.wifi_points", entity="project",
                    entity_id=project.id, actor="migration",
                    payload={"renamed": renamed[:500], "removed": removed[:500]},
                    justification="4.3.0: a wireless point marks a space with Wi-Fi, not an "
                                  "access point count — AP-n renamed WIFI-n, one point per "
                                  "space kept of those placed from the TEAP"))
    db.commit()
    return {"wifi_renamed": len(renamed), "wifi_extra_removed": len(removed)}


def repair_canonical_positions(db: Session, project: Project) -> dict:
    """Put each register room's canonical position back on its own marker
    (3.0.0, every start, idempotent).

    Before 3.0.0 dragging a room's marker on a sheet other than its canonical
    one copied that marker's x/y into the canonical position and left the
    canonical page alone — ALA's NERc_04.1 stood at page 6's coordinates
    on page 4. Here: a room whose canonical point is not on any of its markers
    takes the marker on its canonical page; with no marker there, the marker
    whose x/y the canonical copied (that page becomes canonical); otherwise
    its first marker. Rooms placed from the register (no marker) are left
    alone. Each repair is audited with the before and after."""
    from .models import AuditLog

    fixed: list[dict] = []
    for a in db.execute(select(NerAsset).where(NerAsset.project_id == project.id)).scalars():
        if a.position_source != "occurrence":
            continue
        markers = [e for e in a.occurrences
                   if e.scenario_id is None and e.kind in ("NER_CRITICAL", "NER_NONCRITICAL")]
        if not markers:
            continue

        def at(e) -> bool:
            return (SH.on_canonical_sheet(e, a) and abs(e.x - (a.canonical_x or 0)) < 0.5
                    and abs(e.y - (a.canonical_y or 0)) < 0.5)
        if any(at(e) for e in markers):
            continue
        here = [e for e in markers if SH.on_canonical_sheet(e, a)]
        copied = [e for e in markers if abs(e.x - (a.canonical_x or 0)) < 0.5
                  and abs(e.y - (a.canonical_y or 0)) < 0.5]
        if here:
            m = min(here, key=lambda e: (e.x - (a.canonical_x or 0)) ** 2
                    + (e.y - (a.canonical_y or 0)) ** 2)
        elif copied:
            m = copied[0]
        else:
            m = sorted(markers, key=lambda e: (e.page, e.id))[0]
        before = {"page": a.canonical_page, "x": a.canonical_x, "y": a.canonical_y}
        a.canonical_page, a.canonical_x, a.canonical_y = m.page, m.x, m.y
        if m.drawing_id:
            a.canonical_drawing_id = m.drawing_id
        after = {"page": m.page, "x": m.x, "y": m.y}
        fixed.append({"name": a.display_name, "from": before, "to": after})
        db.add(AuditLog(project_id=project.id, action="ner.canonical_repaired",
                        entity="ner_asset", entity_id=a.id, actor="migration",
                        payload={"from": before, "to": after, "marker_id": m.id},
                        justification="3.0.0: the canonical position is the room's own "
                                      "marker on its canonical page — a drag on another "
                                      "sheet had copied that sheet's coordinates"))
    if fixed:
        db.commit()
        log.info("canonical positions repaired in %s: %s", project.name,
                 ", ".join(f["name"] for f in fixed))
    return {"canonical_repaired": len(fixed)}


def clear_guessed_levels(db: Session, project: Project) -> dict:
    """Take back a level the importer guessed from a bare three-digit figure
    on a sheet whose title block was read (4.1.0, every start, idempotent).

    Such a sheet states its level in its drawing title or not at all; the
    guess was the seat count of a stand on the ALA 600 series ("142",
    "138") and became the level of the NERs created on those sheets, which
    then could never be found "on the same level" as anything. The page loses
    the guess (no level stated — the honest answer) and so does every register
    room whose level is that guess and whose canonical sheet is that page.
    Audited; a level a person typed on a room is not a page guess and is kept
    unless it is exactly the guessed figure of its own sheet."""
    from .domain.pdf_ingest import GUESSED_LEVEL_RX
    from .models import AuditLog

    cleared: list[dict] = []
    for pg in db.execute(select(Page).join(Page.drawing)
                         .where(Page.drawing.has(project_id=project.id))).scalars():
        lv = (pg.level or "").strip()
        if not (pg.sheet_number and lv and GUESSED_LEVEL_RX.fullmatch(lv)):
            continue
        rooms = []
        for a in db.execute(select(NerAsset).where(
                NerAsset.project_id == project.id, NerAsset.level == lv,
                NerAsset.canonical_page == pg.number)).scalars():
            if a.canonical_drawing_id not in (None, pg.drawing_id):
                continue
            a.level = None
            rooms.append(a.display_name)
        pg.level = None
        cleared.append({"page": pg.number, "drawing_id": pg.drawing_id,
                        "sheet": pg.sheet_number, "level": lv, "ners": rooms})
    if cleared:
        db.add(AuditLog(project_id=project.id, action="page.guessed_level_cleared",
                        actor="system", payload={"pages": cleared},
                        justification="4.1.0: a bare three-digit figure is not the level "
                                      "of a sheet whose title block was read"))
        db.commit()
    return {"guessed_levels_cleared": len(cleared)}


def backfill_all_spaces_2140(session_factory) -> dict:
    totals: dict[str, int] = {}
    try:
        with session_factory() as db:
            for project in db.execute(select(Project)).scalars().all():
                for k, v in cleanup_spaces_2140(db, project).items():
                    totals[k] = totals.get(k, 0) + v
    except Exception as exc:                          # noqa: BLE001
        log.warning("2.14.0 spaces pass: stopped: %s", exc)
    return totals


def _upload_tail(stored: str) -> Optional[tuple[str, ...]]:
    """The part of a stored path below its ``uploads`` folder, whichever
    machine and separator wrote it: ``C:\\…\\data\\uploads\\project_1\\a.pdf``
    and ``/srv/ner/data/uploads/project_1/a.pdf`` both give
    ``("project_1", "a.pdf")``. ``None`` when there is no such folder in it."""
    parts = [s for s in re.split(r"[\\/]+", stored or "") if s]
    at = [i for i, s in enumerate(parts) if s.lower() == "uploads"]
    if not at or at[-1] == len(parts) - 1:
        return None
    tail = tuple(parts[at[-1] + 1:])
    if any(s in (".", "..") for s in tail):
        return None
    return tail


def rebase_stored_paths(db: Session, uploads_dir=None) -> dict:
    """Point every uploaded file's record at THIS installation's uploads.

    ``Drawing.stored_path`` and ``TeapFile.stored_path`` are written as full
    paths when a file is uploaded. A database that is then restored into
    another folder — another computer, another Windows account, or the
    installed copy instead of a development checkout — kept naming the folder
    it came from. Where that folder no longer existed every drawing was
    "missing"; where it still existed (2 Oct 2026: a backup of the checkout
    restored into the installation on the same machine) the application went
    on reading the *other* folder's files and nobody could tell — until that
    folder was tidied away.

    The rule: a file uploaded to this application lives under
    ``settings.uploads_dir``. A record that names any other place is moved to
    the same relative path here when that file exists and — the record carries
    the upload's SHA-256 — is the same file. Nothing on disk is touched. A
    record whose file is not here is left exactly as it is: it still opens if
    the old place exists, and re-pointing it at nothing would only hide where
    the file was last seen.

    Runs on every start, before any pass that reads a book; when nothing
    moved it compares strings and returns.
    """
    import os
    from pathlib import Path

    from .config import settings
    from .models import AuditLog, Drawing, TeapFile
    from .services import sha256_file

    root = Path(uploads_dir) if uploads_dir is not None else settings.uploads_dir
    report = {"upload_paths_rebased": 0, "upload_paths_not_here": 0,
              "upload_paths_different_file": 0}

    def _same(a: str, b: Path) -> bool:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(str(b)))

    for model, entity in ((Drawing, "drawing"), (TeapFile, "teap_file")):
        for row in db.execute(select(model)).scalars().all():
            stored = row.stored_path or ""
            tail = _upload_tail(stored)
            if tail is None:
                name = re.split(r"[\\/]+", stored)[-1] if stored else ""
                if not name:
                    continue
                tail = (f"project_{row.project_id}", name)
            here = root.joinpath(*tail)
            if _same(stored, here):
                continue
            if not here.is_file():
                report["upload_paths_not_here"] += 1
                continue
            if row.sha256:
                try:
                    same_file = sha256_file(here) == row.sha256
                except OSError as exc:                # unreadable: leave the record alone
                    log.warning("upload paths: could not read %s: %s", here, exc)
                    same_file = False
                if not same_file:
                    report["upload_paths_different_file"] += 1
                    log.warning("upload paths: %s is not the file recorded for %s %s — "
                                "record left pointing at %s", here, entity, row.id, stored)
                    continue
            row.stored_path = str(here)
            db.add(AuditLog(project_id=row.project_id, action="upload.path_rebased",
                            entity=entity, entity_id=row.id, actor="system",
                            payload={"from": stored, "to": str(here)}))
            report["upload_paths_rebased"] += 1
    if report["upload_paths_rebased"]:
        db.commit()
        log.warning("upload paths: %d record(s) now point at %s",
                    report["upload_paths_rebased"], root)
    return report


def run(engine: Engine, session_factory) -> dict:
    """Full migration. Returns a report suitable for logging."""
    schema_changes = ensure_schema(engine)
    report = {"schema": schema_changes, "projects": []}
    db = session_factory()
    try:
        # First of all: the passes below, and the background ones that read
        # the books, trust ``stored_path`` (2.16.1).
        try:
            report["uploads"] = rebase_stored_paths(db)
        except Exception as exc:                      # noqa: BLE001 — never keep the app from starting
            db.rollback()
            log.warning("upload paths: pass stopped: %s", exc)
        try:
            report["orphans"] = set_aside_orphan_files(db)
        except Exception as exc:                      # noqa: BLE001 — never keep the app from starting
            db.rollback()
            log.warning("orphan files: pass stopped: %s", exc)
        for project in db.execute(select(Project)).scalars().all():
            row = backfill_assets(db, project)
            # Must run for every project on every start, not only after an
            # import: a study that was mid-review when this shipped holds its
            # only copy of the association in ``space_matches``.
            row.update(adopt_match_decisions(db, project))
            # 4.2.0: codes read in full, and the matcher's confirmations given
            # back to the matcher; then the matching once more, so the rows
            # read the corrected codes.
            try:
                fixed = repair_truncated_codes(db, project)
                fixed.update(release_matcher_locks(db, project))
                if (fixed["codes_repaired"] or fixed["matcher_locks_released"]) and db.execute(
                        select(TeapSpace.id).where(TeapSpace.project_id == project.id)).first():
                    from . import services as S
                    S.run_matching(db, project, actor="system")
                    fixed["matching_rerun"] = True
                row.update(fixed)
            except Exception as exc:                  # noqa: BLE001 — never keep the app from starting
                db.rollback()
                log.warning("4.2.0 repair pass stopped on project %s: %s", project.id, exc)
            row.update(backfill_wireless_points(db, project))
            row.update(backfill_key_plans(db, project))
            row.update(fold_outdoor_wireless(db, project))
            try:
                row.update(wifi_points_430(db, project))
            except Exception as exc:                  # noqa: BLE001 — never keep the app from starting
                db.rollback()
                log.warning("4.3.0 Wi-Fi pass stopped on project %s: %s", project.id, exc)
            row.update(repair_canonical_positions(db, project))
            row.update(clear_guessed_levels(db, project))
            row.update(flag_same_name_ners(db, project))
            try:
                row.update(flag_resurrected_ners(db, project))
            except Exception as exc:                  # noqa: BLE001 — never keep the app from starting
                db.rollback()
                log.warning("4.2.1 resurrected-NER pass stopped on project %s: %s", project.id, exc)
            report["projects"].append(row)
    finally:
        db.close()
    return report
