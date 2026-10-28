"""The NER register: one row per physical equipment room, and every decision
a human has made about it.

This is the service layer behind the *NER Register and Review* screen. It owns
five things V1 had nowhere to put:

* **Identity.** ``NerAsset.id`` and ``NerAsset.code`` never change. Renaming
  writes ``display_name`` and appends to ``NerNameHistory``, so a report printed
  last month can still be traced to the room it described.
* **Decisions.** Classification, keep/reject, lock, status — each recorded with
  who and when, none of them ever set by the tool on its own.
* **Consolidation.** Folding two occurrences into one room, and unfolding them
  again, with the evidence kept on both sides of the decision.
* **Controlled deletion.** Nothing is removed. ``deleted_at`` plus a reason, so
  a register that once listed a room can always show why it stopped.
* **Suggestions.** A NER the optimiser proposes enters the register as a row
  with status ``suggested`` and the full justification bundle attached — never
  as an approved position.
"""

from __future__ import annotations

import datetime as _dt
import re
import threading
import unicodedata
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import sheets as SH

from .domain.consolidation import (AUTO_MERGE_THRESHOLD, Candidate, compare,
                                   group_candidates, normalise_label)
from .models import (AuditLog, Criticality, Drawing, Element, KeepDecision, NerAsset,
                     NerConsolidation, NerNameHistory, NerStatus, Page, Project,
                     RegisterSnapshot, Scenario, SnapshotKind)


class RegisterError(ValueError):
    """A refused operation, with a sentence a user can act on."""


class AssetNotFound(RegisterError):
    """No NER with that id in this project (4.8.0: answered 404, not 422)."""


class NameInUse(RegisterError):
    """The name is another live NER's (4.2.0)."""

    def __init__(self, message: str, other: "NerAsset"):
        super().__init__(message)
        self.other = other


#: Held while a name is checked and written (4.2.1). Two renames to one name
#: sent at the same moment both passed the "is the name free?" check before
#: either was saved, and the project ended with two NERs of one name.
_NAME_LOCK = threading.Lock()


def _live_twin(db: Session, project: Project, asset: NerAsset, name: str) -> Optional[NerAsset]:
    """Another live NER whose name is ``name`` (as the screens compare names).

    Read twice (4.2.1): in the request's own session, and in a fresh one that
    sees what another request saved a moment ago — the request's session may
    hold a snapshot taken before it."""
    key = name_key(name)

    def _find(sess: Session) -> Optional[NerAsset]:
        return next((o for o in sess.execute(select(NerAsset).where(
            NerAsset.project_id == project.id, NerAsset.id != asset.id,
            NerAsset.deleted_at.is_(None), NerAsset.merged_into_id.is_(None))).scalars()
            if name_key(o.display_name) == key
            and o.keep_decision != KeepDecision.REJECT and o.status != NerStatus.REJECTED), None)

    hit = _find(db)
    if hit is not None:
        return hit
    fresh = Session(bind=db.get_bind())
    try:
        other = _find(fresh)
        return db.get(NerAsset, other.id) if other is not None else None
    finally:
        fresh.close()


def name_key(name: Optional[str]) -> str:
    """The comparison the interface makes (``nerNameKey``): case, accents,
    spaces and punctuation ignored — NER 21 = ner21 = NER-21, NERc 01 ≠ NER 01."""
    s = unicodedata.normalize("NFD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _audit(db: Session, project_id: int, action: str, *, entity_id: Optional[int],
           actor: str, justification: str = "", payload: Optional[dict] = None) -> None:
    if actor in ("user", "", None):            # the person signed in (4.2.0)
        from .services import current_actor
        actor = current_actor()
    db.add(AuditLog(project_id=project_id, actor=actor, action=action,
                    entity="ner_asset", entity_id=entity_id,
                    justification=justification, payload=payload or {}))


def get_asset(db: Session, project: Project, asset_id: int) -> NerAsset:
    a = db.get(NerAsset, asset_id)
    if a is None or a.project_id != project.id:
        raise AssetNotFound(f"NER {asset_id} does not belong to this project")
    return a


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _page_meta(db: Session, project_id: int) -> "SH.PageMeta":
    """Sheet key → ``(level, building, sheet title, file name)`` (4.1.0: by
    sheet — with several books each one's page 2 is its own sheet)."""
    sh = SH.for_project(db, project_id)
    rows = db.execute(
        select(Page.number, Page.level, Page.building, Page.sheet_title, Drawing.filename,
               Page.drawing_id)
        .join(Drawing, Drawing.id == Page.drawing_id)
        .where(Drawing.project_id == project_id)
    ).all()
    return SH.PageMeta(sh, {sh.key(r[5], r[0]): (r[1], r[2], r[3], r[4]) for r in rows})


def _asset_key(meta, a: NerAsset, page=None) -> Optional[int]:
    """The sheet key of a register room's canonical sheet (or of ``page`` in
    the same book) when ``meta`` knows the sheets; the page number otherwise."""
    p = a.canonical_page if page is None else page
    if isinstance(meta, SH.PageMeta):
        return meta.sheets.key(a.canonical_drawing_id, p)
    return p


def _latest_load(db: Session, project_id: int) -> dict[str, dict]:
    """Per-NER coverage figures from the most recent saved scenario.

    The register shows "areas served" and "longest served distance" next to each
    room. Those are results of an analysis, not properties of the room, so they
    are read from the last run rather than stored — and are absent, not zero,
    when no analysis has been run.
    """
    sc = db.execute(
        select(Scenario).where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
    ).scalars().first()
    if sc is None or not isinstance(sc.result, dict):
        return {}
    load = dict(sc.result.get("ner_load") or {})

    # ``ner_load`` records which spaces a room serves but not how far the
    # farthest one is; that lives on the individual assignments. The register
    # column asks for the longest serving distance, so it is derived here rather
    # than being left blank or, worse, filled with the wrong number.
    out: dict[str, dict] = {}
    for key, row in load.items():
        spaces = row.get("spaces")
        out[key] = {**row,
                    "spaces": len(spaces) if isinstance(spaces, list) else spaces,
                    "space_keys": spaces if isinstance(spaces, list) else [],
                    "max_distance_m": None}
    for a in sc.result.get("assignments") or []:
        key, ev = a.get("ner_key"), a.get("evaluation") or {}
        d = ev.get("effective_distance_m")
        if key in out and d is not None:
            current = out[key]["max_distance_m"]
            out[key]["max_distance_m"] = d if current is None else max(current, d)
    return out


def occurrence_dict(e: Element, meta: dict[int, tuple]) -> dict:
    level, building, sheet, filename = SH.meta_of(meta, e, (None, None, None, None))
    return {
        "id": e.id, "document": filename, "document_kind": e.document_kind,
        "drawing_id": e.drawing_id, "page": SH.key_of(meta, e), "sheet_title": sheet,
        "viewport": e.viewport, "level": level, "building": building,
        "x": e.x, "y": e.y, "label": e.label, "kind": e.kind,
        "symbol": e.symbol, "colour": e.colour, "nearby_text": e.nearby_text,
        "confidence": e.confidence, "detection_method": e.detection_method or e.origin,
        "link_status": e.link_status, "link_score": e.link_score,
        "evidence": e.evidence or [],
        "origin": e.origin, "confirmed": bool(e.confirmed),
    }


def is_confirmed(a: NerAsset, occs: list[Element]) -> bool:
    """Has a person signed this room off?

    One tick on the NERs screen, and one meaning: the criticality has been
    confirmed *and* every marker of this room on the drawing has been
    confirmed as a real marker at a real position. A room with no marker
    left (moved off the sheet, or drawn in the register alone) is confirmed
    by its criticality alone — there is no marker to vouch for.
    """
    return bool(a.classification_confirmed) and all(e.confirmed for e in occs)


def is_editable(a: NerAsset) -> bool:
    """Can this row still be changed?

    A room that has been removed, or rejected, is a record of a decision. Leaving
    its name, criticality and capacity editable invites someone to edit a room
    that is no longer part of the study and then wonder why nothing moved. The
    row stays visible and readable — the audit needs it — but it is closed until
    it is restored.
    """
    return (a.deleted_at is None and a.merged_into_id is None
            and a.status != NerStatus.REJECTED
            and a.keep_decision != KeepDecision.REJECT)


def keep_is_open_question(a: NerAsset) -> bool:
    """Is "keep or reject?" genuinely unanswered for this room?

    Only for a room the application proposed. One drawn in the VDB exists; the
    honest presentation is "on the drawing", with removal offered as a
    deliberate change request rather than as a blank to fill in.
    """
    return a.status == NerStatus.SUGGESTED or a.origin == "suggested"


def pending_validations(a: NerAsset, occs: list[Element]) -> list[str]:
    """What still has to be answered before this row is an engineering statement."""
    out = list(a.pending_validations or [])
    if not a.classification_confirmed:
        out.append("criticality not confirmed by a human")
    if a.keep_decision == KeepDecision.UNDECIDED and a.status == NerStatus.SUGGESTED:
        # Only a proposal has an open keep/reject question. A room drawn in the
        # VDB is already there; rejecting it is a change request, raised on
        # purpose, not an unanswered field on a form.
        out.append("keep / reject decision outstanding")
    if a.total_ports is None:
        out.append("capacity unknown")
    if a.status == NerStatus.SUGGESTED:
        out.append("suggested position — not validated technically or architecturally")
    if a.position_source == "suggested":
        out.append("geometric zone only — no technical room confirmed")
    if not a.level:
        out.append("level unknown — cross-floor service cannot be evaluated")
    unconfirmed = [e for e in occs if e.link_status in ("auto_linked", "unlinked")]
    if unconfirmed:
        out.append(f"{len(unconfirmed)} marker(s) on the drawing not confirmed by a human")
    # V2 phase 1 does not read the TVDB yet; say so rather than implying routes exist.
    out.append("no TVDB route validated (route A/B analysis pending)")
    return out


def asset_dict(db: Session, a: NerAsset, *, meta: dict[int, tuple],
               load: dict[str, dict], occs: Optional[list[Element]] = None) -> dict:
    if occs is None:
        occs = list(a.occurrences)
    occs = sorted(occs, key=lambda e: (SH.key_of(meta, e), e.id))
    stats = load.get(f"A{a.id}") or {}
    history = db.execute(
        select(NerNameHistory).where(NerNameHistory.ner_asset_id == a.id)
        .order_by(NerNameHistory.at.desc())
    ).scalars().all()
    return {
        "id": a.id, "code": a.code,
        "display_name": a.display_name, "suggested_name": a.suggested_name,
        "previous_name": a.previous_name, "aliases": a.aliases or [],
        "origin": a.origin, "kind": a.kind,
        "classification": a.classification,
        "suggested_classification": a.suggested_classification,
        "classification_confirmed": a.classification_confirmed,
        "classification_evidence": a.classification_evidence or [],
        "status": a.status, "keep_decision": a.keep_decision,
        "editable": is_editable(a),
        "keep_is_open_question": keep_is_open_question(a),
        "in_as_is": a.in_as_is, "in_proposed": a.in_proposed,
        "building": a.building, "sector": a.sector, "level": a.level,
        "space_name": a.space_name, "space_code": a.space_code,
        "environment": a.environment,
        "canonical": {"drawing_id": a.canonical_drawing_id, "page": _asset_key(meta, a),
                      "x": a.canonical_x, "y": a.canonical_y,
                      "source": a.position_source},
        "proposed_position": (
            {"page": _asset_key(meta, a, a.proposed_page), "x": a.proposed_x, "y": a.proposed_y,
             "reason": a.reposition_reason}
            if a.proposed_page is not None else None),
        "locked": a.locked, "movable": a.movable,
        "confirmed": is_confirmed(a, occs),
        "occurrence_count": len(occs),
        "documents": sorted({o["document"] for o in
                             (occurrence_dict(e, meta) for e in occs) if o["document"]}),
        "pages": sorted({SH.key_of(meta, e) for e in occs}),
        "occurrences": [occurrence_dict(e, meta) for e in occs],
        "marker_kinds": sorted({e.kind for e in occs}),
        "confidence": a.confidence,
        "capacity": {
            "total_ports": a.total_ports, "used_ports": a.used_ports,
            "reserved_ports": a.reserved_ports, "switch_capacity": a.switch_capacity,
            "patch_capacity": a.patch_capacity, "growth_margin_pct": a.growth_margin_pct,
            "power_available": a.power_available,
            "cooling_available": a.cooling_available,
            "space_available": a.space_available,
            "known": a.total_ports is not None,
        },
        "coverage": {
            "areas_served": stats.get("spaces"),
            "assigned_ports": stats.get("assigned_ports"),
            "max_distance_m": stats.get("max_distance_m"),
            "analysed": bool(stats),
        },
        "routes": {
            # Phase 1 imports no TVDB, so these are honestly unknown rather than false.
            "pathway": None, "containment": None,
            "route_a": None, "route_b": None, "redundancy_status": "not_analysed",
        },
        "suggestion": a.suggestion or None,
        "pending_validations": pending_validations(a, occs),
        "notes": a.notes,
        "name_history": [{"old": h.old_name, "new": h.new_name, "at": h.at.isoformat(),
                          "actor": h.actor, "reason": h.reason} for h in history],
        "merged_into_id": a.merged_into_id,
        "deleted_at": a.deleted_at.isoformat() if a.deleted_at else None,
        "deleted_reason": a.deleted_reason,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        "updated_by": a.updated_by,
        "is_live": a.is_live,
    }


def list_assets(db: Session, project: Project, *, include_removed: bool = False
                ) -> list[dict]:
    q = select(NerAsset).where(NerAsset.project_id == project.id)
    assets = db.execute(q.order_by(NerAsset.code)).scalars().all()
    if not include_removed:
        assets = [a for a in assets if a.deleted_at is None and a.merged_into_id is None]
    meta = _page_meta(db, project.id)
    load = _latest_load(db, project.id)
    by_asset: dict[int, list[Element]] = {}
    for e in db.execute(select(Element).where(Element.project_id == project.id,
                                              Element.ner_asset_id.is_not(None))
                        ).scalars():
        by_asset.setdefault(e.ner_asset_id, []).append(e)
    return [asset_dict(db, a, meta=meta, load=load, occs=by_asset.get(a.id, []))
            for a in assets]


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------

def rename(db: Session, project: Project, asset: NerAsset, new_name: str, *,
           actor: str = "user", reason: str = "", same_name_ok: bool = False) -> NerAsset:
    """Change the display name. The internal id and code are untouched.

    Refused (4.2.0) on a locked room — the lock disables the name on screen and
    now on the server too — and when another live NER already has the name:
    two rows with one name are two NERs counted twice that no workbook can tell
    apart (the VFF project: NER24 renamed NER23 beside NER23). The
    same room is consolidated, not renamed alike."""
    new_name = (new_name or "").strip()
    if not new_name:
        raise RegisterError("a NER name cannot be empty")
    if new_name == asset.display_name:
        return asset
    if asset.locked:
        raise RegisterError(f"{asset.display_name} is locked — unlock it first")
    with _NAME_LOCK:
        if not same_name_ok:
            other = _live_twin(db, project, asset, new_name)
            if other is not None:
                raise NameInUse(f"{other.display_name} is already the name of another NER "
                                f"({other.code}) — if it is the same room, consolidate the two; "
                                f"otherwise choose another name", other)
        return _rename_now(db, project, asset, new_name, actor=actor, reason=reason)


def _rename_now(db: Session, project: Project, asset: NerAsset, new_name: str, *,
                actor: str, reason: str) -> NerAsset:
    old = asset.display_name
    db.add(NerNameHistory(ner_asset_id=asset.id, old_name=old, new_name=new_name,
                          reason=reason, actor=actor))
    # Keep the old name reachable: reports printed under it must stay traceable.
    aliases = list(asset.aliases or [])
    if old and old not in aliases:
        aliases.append(old)
    asset.aliases = aliases
    asset.previous_name = old
    asset.display_name = new_name
    asset.updated_by = actor
    # One name. The marker on the sheet used to keep the label the drawing
    # printed while the register carried the new one, so the viewer and the
    # exported plan disagreed about what a room was called. The printed label
    # is still on record — as ``suggested_name`` on the row, as an alias, and
    # in the name history — but what is *drawn* is the current name.
    relabelled = 0
    for e in asset.occurrences:
        if e.label != new_name:
            e.label = new_name
            relabelled += 1
    _audit(db, project.id, "ner.renamed", entity_id=asset.id, actor=actor,
           justification=reason, payload={"from": old, "to": new_name,
                                          "code": asset.code, "id": asset.id,
                                          "markers_relabelled": relabelled})
    db.commit()
    return asset


# ---------------------------------------------------------------------------
# Sequential names (2.14.0)
# ---------------------------------------------------------------------------
#
# Every NER the app creates — read off a team annotation, a TEC.003 room, a
# "Network Equipment Rack (NER)" label — is named ``NERc01``, ``NERc02`` …
# (critical) or ``NER01``, ``NER02`` … (non-critical), in sequence, and the
# label the drawing printed is kept as *printed as*. The naming convention,
# the suggested names and *Adopt* of 2.7.0–2.13.x went at Marcelo's request
# (29 Sep 2026): *"mantenha tudo como NERcXX e NERxx e crie tudo em sequência,
# que eu vou renomear tudo na mão mesmo."* The event's naming structure is a
# reference table beside the register now, and decides nothing.

#: A sequential name and its number — in the form the app writes since 2.18.0
#: (``NERc_01.1``, ``NER_20.1``: the event's "NER Standardized Naming Structure"
#: v2.0, an underscore where the sheet prints a space), in the older forms the
#: register still holds (``NERc01``, ``NERc 01``, ``NER-21``, ``ner 3``) and
#: with the venue code the sheet puts in front (``VHH_NERc_01.1``). Group 1 is
#: the critical mark, group 2 the number; the rack suffix (``.1``, ``.2``) and
#: the venue code are not part of the number.
SEQUENTIAL_NAME_RX = re.compile(
    r"^\s*(?:[A-Z0-9]{2,5}_)?NER\s*(c)?\s*[-._ ]?\s*0*(\d{1,3})(?:\.(\d{1,2}))?\s*$",
    re.IGNORECASE)


def sequential_name(number: int, critical: bool) -> str:
    """``NERc_01.1`` / ``NER_20.1`` — the naming sheet's v2.0 form with an underscore in
    place of the sheet's space (Marcelo, 9 Oct 2026: "não usar espaços e sim
    NERc_01.1, isso serve pra tudo"). The ``.1`` is the rack: a second rack
    beside the first is ``.2``, renamed by hand."""
    return f"{'NERc' if critical else 'NER'}_{number:02d}.1"


#: Where each series starts. The naming sheet v2.0 (9 Oct 2026) fixes
#: ``NERc 01.1``–``11.1`` to the COMP racks, keeps ``12.1``–``19.1`` for the
#: other critical racks ("VTS to confirm") and numbers the non-critical racks
#: from ``NER 20.1`` — so the app's non-critical names start at ``NER_20.1``
#: (v1.1 said 21, and 2.15.0–2.17.0 started there). Critical names start at
#: ``NERc_01.1``.
SEQUENCE_START = {True: 1, False: 20}


def next_sequential_name(existing_names: Iterable[str], critical: bool) -> str:
    """The next free ``NERc_NN.1`` / ``NER_NN.1`` after every name in ``existing_names``.

    The number follows the highest one already used *in that series* (a
    critical name never reuses a non-critical number and vice versa), never
    below that series' ``SEQUENCE_START``; a name that collides with any
    existing name, spelling aside, is skipped.
    """
    taken = {normalise_label(n) for n in existing_names if n}
    highest = SEQUENCE_START[bool(critical)] - 1
    for n in existing_names:
        m = SEQUENTIAL_NAME_RX.match(n or "")
        if m and bool(m.group(1)) == critical:
            highest = max(highest, int(m.group(2)))
    n = highest
    while True:
        n += 1
        name = sequential_name(n, critical)
        if normalise_label(name) not in taken:
            return name


def live_names(db: Session, project_id: int) -> list[str]:
    """Every name the register holds — live rows *and* the removed or merged
    ones, so a deleted room's number is never handed out again while it can
    be restored (a restore would otherwise bring back a second ``NERc03``) —
    and, from 4.8.0, every name a NER **had** before a rename: the next name
    offered was a live NER's former name (VBB: ``NER_34.1`` and ``NERc_11.1``,
    both earlier names of ``NERc_10.1``), and a report or a message written
    under the old name then pointed at two rooms."""
    from .models import NerNameHistory

    assets = list(db.execute(select(NerAsset).where(NerAsset.project_id == project_id)).scalars())
    names = [a.display_name for a in assets if a.display_name]
    names += [a.previous_name for a in assets if a.previous_name]
    ids = [a.id for a in assets]
    if ids:
        names += [n for n in db.execute(select(NerNameHistory.old_name).where(
            NerNameHistory.ner_asset_id.in_(ids))).scalars() if n]
    return names


_CLASSIFICATION_TO_KIND = {
    Criticality.CRITICAL: "NER_CRITICAL",
    Criticality.NON_CRITICAL: "NER_NONCRITICAL",
}


def _drop_answered(asset: NerAsset, prefix: str) -> None:
    """Take off the row the questions a person has just answered — the
    "criticality:" questions a NER read off the drawing carries (2.13.0) go
    once somebody confirms a criticality."""
    asset.pending_validations = [v for v in (asset.pending_validations or [])
                                 if not v.startswith(prefix)]


def classify(db: Session, project: Project, asset: NerAsset, classification: str, *,
             confirmed: bool, actor: str = "user", reason: str = "") -> NerAsset:
    if classification not in Criticality.ALL:
        raise RegisterError(f"unknown classification “{classification}”")
    if classification == Criticality.PENDING and confirmed:
        raise RegisterError("“pending” cannot be a confirmed classification")
    before = (asset.classification, asset.classification_confirmed)
    asset.classification = classification
    asset.classification_confirmed = bool(confirmed)
    if confirmed:
        _drop_answered(asset, "criticality:")
    # A confirmed classification is also what the coverage engine serves from, so
    # the marker kind follows it — but only once a human has confirmed. The
    # markers on the sheet follow too: the viewer paints a marker in the
    # colour of *its* kind, and a room the register calls critical drawn in
    # non-critical yellow is the kind of disagreement nobody notices until
    # the exported plan is on someone else's desk.
    if confirmed and classification in _CLASSIFICATION_TO_KIND and asset.kind.startswith("NER"):
        asset.kind = _CLASSIFICATION_TO_KIND[classification]
        for e in asset.occurrences:
            if e.kind.startswith("NER"):
                e.kind = asset.kind
    asset.updated_by = actor
    _audit(db, project.id, "ner.classified", entity_id=asset.id, actor=actor,
           justification=reason,
           payload={"from": before[0], "from_confirmed": before[1],
                    "to": classification, "confirmed": bool(confirmed)})
    db.commit()
    return asset


def set_status(db: Session, project: Project, asset: NerAsset, status: str, *,
               actor: str = "user", reason: str = "") -> NerAsset:
    if status not in NerStatus.ALL:
        raise RegisterError(f"unknown status “{status}”")
    if status == NerStatus.CONSOLIDATED:
        raise RegisterError("use the consolidation action to fold one NER into another")
    before = asset.status
    asset.status = status
    if status == NerStatus.REJECTED:
        asset.keep_decision = KeepDecision.REJECT
        asset.in_proposed = False
    asset.updated_by = actor
    _audit(db, project.id, "ner.status", entity_id=asset.id, actor=actor,
           justification=reason, payload={"from": before, "to": status})
    db.commit()
    return asset


def set_keep(db: Session, project: Project, asset: NerAsset, decision: str, *,
             actor: str = "user", reason: str = "") -> NerAsset:
    if decision not in KeepDecision.ALL:
        raise RegisterError(f"unknown keep decision “{decision}”")
    if decision == KeepDecision.REJECT and asset.locked:
        raise RegisterError(f"{asset.display_name} is locked — unlock it before rejecting")
    before = asset.keep_decision
    asset.keep_decision = decision
    if decision == KeepDecision.KEEP and asset.status == NerStatus.SUGGESTED:
        asset.status = NerStatus.IN_REVIEW
    if decision == KeepDecision.REJECT:
        asset.status = NerStatus.REJECTED
        asset.in_proposed = False
    asset.updated_by = actor
    _audit(db, project.id, "ner.keep_decision", entity_id=asset.id, actor=actor,
           justification=reason, payload={"from": before, "to": decision})
    db.commit()
    return asset


_EDITABLE = ("sector", "level", "building", "space_name", "space_code", "environment",
             "total_ports", "used_ports", "reserved_ports", "switch_capacity",
             "patch_capacity", "growth_margin_pct", "power_available",
             "cooling_available", "space_available", "security_constraints",
             "access_constraints", "notes", "in_as_is", "in_proposed")


def update_fields(db: Session, project: Project, asset: NerAsset, values: dict, *,
                  actor: str = "user") -> NerAsset:
    changed: dict[str, Any] = {}
    for key, value in values.items():
        if key not in _EDITABLE:
            raise RegisterError(f"“{key}” is not editable from the register")
        if key == "environment":
            value = (value or "").strip().lower() or None
            if value not in (None, "indoor", "outdoor"):
                raise RegisterError("indoor / outdoor must be “indoor”, “outdoor” or empty")
        if getattr(asset, key) != value:
            changed[key] = {"from": getattr(asset, key), "to": value}
            setattr(asset, key, value)
    if not changed:
        return asset
    asset.updated_by = actor
    _audit(db, project.id, "ner.updated", entity_id=asset.id, actor=actor,
           payload=changed)
    db.commit()
    return asset


def set_lock(db: Session, project: Project, asset: NerAsset, *, locked: bool,
             actor: str = "user", reason: str = "") -> NerAsset:
    asset.locked = bool(locked)
    if locked:
        asset.movable = False
    asset.updated_by = actor
    _audit(db, project.id, "ner.locked" if locked else "ner.unlocked",
           entity_id=asset.id, actor=actor, justification=reason)
    db.commit()
    return asset


def set_confirmed(db: Session, project: Project, asset: NerAsset, *, confirmed: bool,
                  actor: str = "user", reason: str = "") -> NerAsset:
    """Sign the room off — or take the signature back.

    Confirming means: the criticality shown is right (it becomes
    ``classification_confirmed``), and every marker of this room on the drawing
    is a real marker at a real position. A row whose criticality is still
    *pending* cannot be confirmed — there is nothing to confirm yet, and the
    screen says so instead of quietly confirming "unknown".
    """
    if confirmed and asset.classification == Criticality.PENDING:
        raise RegisterError(f"{asset.display_name}: choose critical or non-critical "
                            f"before confirming it")
    asset.classification_confirmed = bool(confirmed)
    if confirmed:
        _drop_answered(asset, "criticality:")
    if confirmed and asset.classification in _CLASSIFICATION_TO_KIND \
            and asset.kind.startswith("NER"):
        asset.kind = _CLASSIFICATION_TO_KIND[asset.classification]
    for e in asset.occurrences:
        e.confirmed = bool(confirmed)
        if confirmed:
            e.confirmed_by = actor
            e.link_status = "confirmed"
            if e.kind.startswith("NER"):
                e.kind = asset.kind
        else:
            e.confirmed_by = None
            if e.link_status == "confirmed":
                e.link_status = "auto_linked"
    asset.updated_by = actor
    _audit(db, project.id, "ner.confirmed" if confirmed else "ner.unconfirmed",
           entity_id=asset.id, actor=actor, justification=reason,
           payload={"markers": len(asset.occurrences),
                    "classification": asset.classification})
    db.commit()
    return asset


BULK_ACTIONS = ("lock", "unlock", "confirm", "unconfirm")


def bulk(db: Session, project: Project, action: str, *, actor: str = "user") -> dict:
    """Lock, unlock, confirm or unconfirm every live NER at once.

    One audit entry per room, exactly as the single action writes — a bulk
    sign-off is still a decision about each room, and the log has to be able
    to show it that way. Rows that cannot take the action (a pending
    criticality under *confirm*) are skipped and named, never forced.
    """
    if action not in BULK_ACTIONS:
        raise RegisterError(f"unknown bulk action “{action}”")
    assets = [a for a in db.execute(
        select(NerAsset).where(NerAsset.project_id == project.id)
        .order_by(NerAsset.code)).scalars()
        if a.deleted_at is None and a.merged_into_id is None and is_editable(a)]
    done: list[str] = []
    skipped: list[dict] = []
    for a in assets:
        try:
            if action == "lock":
                if not a.locked:
                    set_lock(db, project, a, locked=True, actor=actor,
                             reason="lock all")
                    done.append(a.display_name)
            elif action == "unlock":
                if a.locked:
                    set_lock(db, project, a, locked=False, actor=actor,
                             reason="unlock all")
                    done.append(a.display_name)
            elif action == "confirm":
                if not is_confirmed(a, list(a.occurrences)):
                    set_confirmed(db, project, a, confirmed=True, actor=actor,
                                  reason="confirm all")
                    done.append(a.display_name)
            else:
                if is_confirmed(a, list(a.occurrences)):
                    set_confirmed(db, project, a, confirmed=False, actor=actor,
                                  reason="unconfirm all")
                    done.append(a.display_name)
        except RegisterError as exc:
            skipped.append({"name": a.display_name, "why": str(exc)})
    return {"action": action, "changed": len(done), "names": done,
            "skipped": skipped}


def move(db: Session, project: Project, asset: NerAsset, *, page: int, x: float,
         y: float, propose: bool, actor: str = "user", reason: str = "",
         drawing_id: Optional[int] = None) -> NerAsset:
    """Move the canonical position, or propose a move without committing to it.

    ``page`` is the page number in book ``drawing_id`` (4.1.0); left out, the
    book stays the one the room is on."""
    if asset.locked and not propose:
        raise RegisterError(f"{asset.display_name} is locked against movement")
    if propose:
        asset.proposed_page, asset.proposed_x, asset.proposed_y = page, x, y
        asset.reposition_reason = reason
        asset.status = NerStatus.REPOSITION_PROPOSED
        action = "ner.reposition_proposed"
    else:
        before = {"page": asset.canonical_page, "x": asset.canonical_x,
                  "y": asset.canonical_y}
        asset.canonical_page, asset.canonical_x, asset.canonical_y = page, x, y
        if drawing_id is not None:
            asset.canonical_drawing_id = drawing_id
        asset.position_source = "manual"
        asset.proposed_page = asset.proposed_x = asset.proposed_y = None
        asset.reposition_reason = ""
        if asset.status == NerStatus.REPOSITION_PROPOSED:
            asset.status = NerStatus.IN_REVIEW
        action = "ner.moved"
        _audit(db, project.id, action, entity_id=asset.id, actor=actor,
               justification=reason, payload={"from": before,
                                              "to": {"page": page, "x": x, "y": y}})
        asset.updated_by = actor
        db.commit()
        return asset
    asset.updated_by = actor
    _audit(db, project.id, action, entity_id=asset.id, actor=actor,
           justification=reason, payload={"page": page, "x": x, "y": y})
    db.commit()
    return asset


def soft_delete(db: Session, project: Project, asset: NerAsset, *, reason: str,
                actor: str = "user") -> NerAsset:
    """Controlled removal. The row stays, and says why it left the register."""
    if asset.locked:
        raise RegisterError(f"{asset.display_name} is locked — unlock it first")
    if not reason.strip():
        raise RegisterError("removing a NER from the register requires a reason")
    asset.deleted_at = _now()
    asset.deleted_reason = reason
    asset.status = NerStatus.REJECTED
    asset.keep_decision = KeepDecision.REJECT
    asset.updated_by = actor
    _audit(db, project.id, "ner.removed", entity_id=asset.id, actor=actor,
           justification=reason)
    db.commit()
    return asset


def restore(db: Session, project: Project, asset: NerAsset, *, actor: str = "user"
            ) -> NerAsset:
    with _NAME_LOCK:
        if asset.deleted_at is not None and asset.merged_into_id is None:
            # Two NERs cannot share a name (4.2.1): Restore used to bring a
            # removed row back beside a live one of the same name — on the
            # VBB project four names repeat among the removed rows.
            other = _live_twin(db, project, asset, asset.display_name)
            if other is not None:
                raise NameInUse(f"{other.display_name} is already the name of a live NER "
                                f"({other.code}) — rename that one first, or consolidate "
                                f"the two after restoring under another name", other)
        return _restore_now(db, project, asset, actor=actor)


def _restore_now(db: Session, project: Project, asset: NerAsset, *, actor: str) -> NerAsset:
    asset.deleted_at = None
    asset.deleted_reason = ""
    asset.status = NerStatus.IN_REVIEW
    asset.keep_decision = KeepDecision.UNDECIDED
    asset.updated_by = actor
    payload: dict = {}
    # A NER erased on the drawing lost its marker for good (the viewer deletes
    # the element), so Restore used to bring back a row with a position and
    # no dot on the sheet. The room's position is known, so the marker is
    # drawn again from it — "Restore brings everything back" (2.8.1).
    if not list(asset.occurrences) and asset.position_known:
        drawing_id = asset.canonical_drawing_id or (project.drawings[0].id if project.drawings else None)
        marker = Element(project_id=project.id, drawing_id=drawing_id,
                         page=asset.canonical_page or 1,
                         kind=asset.kind or ("NER_CRITICAL" if asset.classification == Criticality.CRITICAL
                                             else "NER_NONCRITICAL"),
                         label=asset.display_name, x=asset.canonical_x or 0.0, y=asset.canonical_y or 0.0,
                         origin="manual", confidence=1.0, confirmed=asset.classification_confirmed,
                         detection_method="manual", document_kind="VDB",
                         evidence=["marker redrawn from the register position on Restore"],
                         ner_asset_id=asset.id, link_status="confirmed")
        db.add(marker)
        db.flush()
        payload = {"marker_redrawn": marker.id, "page": marker.page}
    _audit(db, project.id, "ner.restored", entity_id=asset.id, actor=actor, payload=payload)
    db.commit()
    return asset


# ---------------------------------------------------------------------------
# Occurrences
# ---------------------------------------------------------------------------

def set_occurrence_link(db: Session, project: Project, element: Element, *,
                        asset_id: Optional[int], status: str, actor: str = "user",
                        reason: str = "") -> Element:
    """Confirm, dispute or re-point one documental occurrence."""
    if status not in ("unlinked", "auto_linked", "confirmed", "disputed", "rejected"):
        raise RegisterError(f"unknown occurrence link status “{status}”")
    before = {"asset_id": element.ner_asset_id, "status": element.link_status}
    if asset_id is not None:
        get_asset(db, project, asset_id)          # ownership check
    element.ner_asset_id = asset_id
    element.link_status = status
    _audit(db, project.id, "ner.occurrence_link", entity_id=asset_id, actor=actor,
           justification=reason,
           payload={"element_id": element.id, "from": before,
                    "to": {"asset_id": asset_id, "status": status}})
    db.commit()
    return element


def detach_occurrence(db: Session, project: Project, element: Element, *,
                      actor: str = "user", reason: str = "") -> NerAsset:
    """Pull one occurrence out into a NER of its own.

    This is the fine-grained undo: a consolidation that was right for two of three
    pages can be corrected without unpicking the whole thing.
    """
    from . import migrate  # local import: migrate imports models, not this module

    if element.ner_asset_id is None:
        raise RegisterError("this occurrence is not attached to a NER")
    old = get_asset(db, project, element.ner_asset_id)
    remaining = [e for e in old.occurrences if e.id != element.id]
    if not remaining:
        raise RegisterError(
            f"{old.display_name} has only this occurrence — detaching it would leave "
            "an empty NER. Remove the NER instead if that is what you mean.")
    full = _page_meta(db, project.id)
    meta = SH.PageMeta(full.sheets, {p: (m[0], m[1]) for p, m in full.items()})
    new_asset = migrate._asset_from_element(db, element, meta)
    new_asset.status = NerStatus.IN_REVIEW
    new_asset.updated_by = actor
    element.ner_asset_id = new_asset.id
    element.link_status = "confirmed"
    _audit(db, project.id, "ner.occurrence_detached", entity_id=new_asset.id,
           actor=actor, justification=reason,
           payload={"element_id": element.id, "from_asset": old.id,
                    "to_asset": new_asset.id})
    db.commit()
    return new_asset


# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------

def _candidate_for(a: NerAsset, separate: dict[int, set[int]],
                   sh: Optional["SH.Sheets"] = None) -> Candidate:
    return Candidate(ref=a.id, label=a.display_name, kind=a.kind,
                     page=(sh.of_asset(a) if sh is not None else a.canonical_page),
                     level=a.level, building=a.building,
                     document_id=a.canonical_drawing_id, space_code=a.space_code,
                     space_name=a.space_name, x=a.canonical_x, y=a.canonical_y,
                     confirmed_separate_from=frozenset(separate.get(a.id, ())))


def _separate_pairs(db: Session, project_id: int) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for c in db.execute(select(NerConsolidation).where(
            NerConsolidation.project_id == project_id,
            NerConsolidation.decision == "separate")).scalars():
        if c.merged_asset_id is None:
            continue
        out.setdefault(c.primary_asset_id, set()).add(c.merged_asset_id)
        out.setdefault(c.merged_asset_id, set()).add(c.primary_asset_id)
    return out


def duplicate_candidates(db: Session, project: Project) -> list[dict]:
    """Pairs of register rows that may be the same room, strongest evidence first.

    Recomputed on every call rather than cached: the answer changes as soon as
    someone edits a level, confirms a classification or renames a room, and a
    stale duplicate queue is worse than none.
    """
    assets = [a for a in db.execute(
        select(NerAsset).where(NerAsset.project_id == project.id)).scalars()
        if a.deleted_at is None and a.merged_into_id is None]
    by_id = {a.id: a for a in assets}
    separate = _separate_pairs(db, project.id)
    meta = _page_meta(db, project.id)
    load = _latest_load(db, project.id)

    with SH.naming(meta.sheets):
        pairs = group_candidates([_candidate_for(a, separate, meta.sheets) for a in assets])
    out: list[dict] = []
    for ca, cb, cmp_ in pairs:
        a, b = by_id[ca.ref], by_id[cb.ref]
        # Keep the better-evidenced row as the primary: more occurrences first,
        # then the earlier code, so the choice is stable between runs.
        if (len(b.occurrences), -b.id) > (len(a.occurrences), -a.id):
            a, b = b, a
        out.append({
            "primary": asset_dict(db, a, meta=meta, load=load),
            "duplicate": asset_dict(db, b, meta=meta, load=load),
            "comparison": cmp_.to_dict(),
            "impact": {
                "occurrences_moved": len(b.occurrences),
                "areas_affected": (load.get(f"A{b.id}") or {}).get("spaces"),
                "ports_affected": (load.get(f"A{b.id}") or {}).get("assigned_ports"),
            },
        })
    return out


def consolidate(db: Session, project: Project, primary_id: int, duplicate_id: int, *,
                actor: str = "user", justification: str = "",
                force: bool = False) -> dict:
    """Fold ``duplicate`` into ``primary``. Reversible.

    The duplicate's row is kept, marked ``consolidated`` and pointed at the
    primary, so every historic reference to it still resolves.
    """
    if primary_id == duplicate_id:
        raise RegisterError("a NER cannot be consolidated with itself")
    primary = get_asset(db, project, primary_id)
    dup = get_asset(db, project, duplicate_id)
    if dup.merged_into_id is not None:
        raise RegisterError(f"{dup.display_name} is already consolidated")
    if primary.merged_into_id is not None:
        raise RegisterError(f"{primary.display_name} is itself consolidated into another NER")
    if dup.locked:
        raise RegisterError(f"{dup.display_name} is locked — unlock it before consolidating")

    separate = _separate_pairs(db, project.id)
    sh = SH.for_project(db, project.id)
    with SH.naming(sh):
        cmp_ = compare(_candidate_for(primary, separate, sh), _candidate_for(dup, separate, sh))
    if cmp_.blocking and not force:
        raise RegisterError(
            f"these do not look like the same NER ({cmp_.differences[0] if cmp_.differences else cmp_.blocking})"
            " — confirm with force if you know otherwise")

    moved = [e.id for e in list(dup.occurrences)]
    snapshot = {
        "duplicate_id": dup.id,
        "occurrence_ids": moved,
        "duplicate_before": {
            "status": dup.status, "merged_into_id": dup.merged_into_id,
            "keep_decision": dup.keep_decision, "in_as_is": dup.in_as_is,
            "in_proposed": dup.in_proposed,
        },
        "primary_before": {"aliases": list(primary.aliases or []),
                           "confidence": primary.confidence,
                           "total_ports": primary.total_ports},
    }

    for e in list(dup.occurrences):
        e.ner_asset_id = primary.id
        e.link_status = "confirmed" if not force else "disputed"
        e.link_score = cmp_.score

    aliases = list(primary.aliases or [])
    # The merged room's internal code always goes in: two rows can carry the same
    # display name, and the code is the only thing that makes the old row's
    # reports traceable to this one afterwards.
    for name in [dup.code, dup.display_name, dup.suggested_name, *(dup.aliases or [])]:
        if name and name not in aliases and name != primary.display_name:
            aliases.append(name)
    primary.aliases = aliases
    primary.confidence = max(primary.confidence, dup.confidence)
    if primary.total_ports is None and dup.total_ports is not None:
        primary.total_ports = dup.total_ports
    if not primary.level and dup.level:
        primary.level = dup.level
    if not primary.building and dup.building:
        primary.building = dup.building
    primary.updated_by = actor

    dup.merged_into_id = primary.id
    dup.status = NerStatus.CONSOLIDATED
    dup.in_as_is = False
    dup.in_proposed = False
    dup.updated_by = actor

    record = NerConsolidation(
        project_id=project.id, primary_asset_id=primary.id, merged_asset_id=dup.id,
        decision="merged", method="manual" if not force else "manual_forced",
        score=cmp_.score, evidence=cmp_.evidence, differences=cmp_.differences,
        undo_snapshot=snapshot, justification=justification, actor=actor)
    db.add(record)
    _audit(db, project.id, "ner.consolidated", entity_id=primary.id, actor=actor,
           justification=justification,
           payload={"primary": primary.code, "duplicate": dup.code,
                    "occurrences_moved": len(moved), "score": round(cmp_.score, 3)})
    db.commit()
    return {"consolidation_id": record.id, "primary_id": primary.id,
            "duplicate_id": dup.id, "occurrences_moved": len(moved),
            "comparison": cmp_.to_dict()}


def undo_consolidation(db: Session, project: Project, consolidation_id: int, *,
                       actor: str = "user", reason: str = "") -> dict:
    rec = db.get(NerConsolidation, consolidation_id)
    if rec is None or rec.project_id != project.id:
        raise RegisterError("consolidation record not found in this project")
    if rec.decision != "merged":
        raise RegisterError("only a merge can be undone")
    if rec.undone_at is not None:
        raise RegisterError("this consolidation has already been undone")
    snap = rec.undo_snapshot or {}
    dup = db.get(NerAsset, rec.merged_asset_id) if rec.merged_asset_id else None
    if dup is None:
        raise RegisterError("the consolidated NER no longer exists")

    for eid in snap.get("occurrence_ids", []):
        e = db.get(Element, eid)
        if e is not None:
            e.ner_asset_id = dup.id
            e.link_status = "confirmed"
    before = snap.get("duplicate_before", {})
    dup.merged_into_id = None
    dup.status = before.get("status") or NerStatus.IN_REVIEW
    dup.keep_decision = before.get("keep_decision") or KeepDecision.UNDECIDED
    dup.in_as_is = before.get("in_as_is", True)
    dup.in_proposed = before.get("in_proposed", True)
    dup.updated_by = actor

    primary = db.get(NerAsset, rec.primary_asset_id)
    if primary is not None:
        pb = snap.get("primary_before", {})
        if "aliases" in pb:
            primary.aliases = pb["aliases"]
        if "confidence" in pb:
            primary.confidence = pb["confidence"]
        if "total_ports" in pb:
            primary.total_ports = pb["total_ports"]
        primary.updated_by = actor

    rec.undone_at = _now()
    rec.undone_by = actor
    _audit(db, project.id, "ner.consolidation_undone", entity_id=rec.primary_asset_id,
           actor=actor, justification=reason,
           payload={"consolidation_id": rec.id, "restored": dup.code})
    db.commit()
    return {"consolidation_id": rec.id, "restored_id": dup.id,
            "occurrences_restored": len(snap.get("occurrence_ids", []))}


def declare_separate(db: Session, project: Project, a_id: int, b_id: int, *,
                     actor: str = "user", justification: str = "") -> dict:
    """Record that two similar NERs are genuinely different rooms.

    Worth persisting: it is the only way the duplicate queue stops asking.
    """
    a, b = get_asset(db, project, a_id), get_asset(db, project, b_id)
    existing = db.execute(select(NerConsolidation).where(
        NerConsolidation.project_id == project.id,
        NerConsolidation.primary_asset_id.in_([a.id, b.id]),
        NerConsolidation.merged_asset_id.in_([a.id, b.id]),
        NerConsolidation.decision == "separate")).scalars().first()
    if existing:
        return {"consolidation_id": existing.id, "already": True}
    separate = _separate_pairs(db, project.id)
    sh = SH.for_project(db, project.id)
    with SH.naming(sh):
        cmp_ = compare(_candidate_for(a, separate, sh), _candidate_for(b, separate, sh))
    rec = NerConsolidation(project_id=project.id, primary_asset_id=a.id,
                           merged_asset_id=b.id, decision="separate", method="manual",
                           score=cmp_.score, evidence=cmp_.evidence,
                           differences=cmp_.differences, justification=justification,
                           actor=actor)
    db.add(rec)
    _audit(db, project.id, "ner.declared_separate", entity_id=a.id, actor=actor,
           justification=justification, payload={"a": a.code, "b": b.code})
    db.commit()
    return {"consolidation_id": rec.id, "already": False}


def consolidation_history(db: Session, project: Project) -> list[dict]:
    rows = db.execute(select(NerConsolidation)
                      .where(NerConsolidation.project_id == project.id)
                      .order_by(NerConsolidation.at.desc())).scalars().all()
    names = {a.id: (a.code, a.display_name) for a in db.execute(
        select(NerAsset).where(NerAsset.project_id == project.id)).scalars()}

    def name(i: Optional[int]) -> Optional[dict]:
        if i is None or i not in names:
            return None
        return {"id": i, "code": names[i][0], "name": names[i][1]}

    return [{"id": r.id, "decision": r.decision, "method": r.method,
             "score": round(r.score, 3), "evidence": r.evidence,
             "differences": r.differences, "justification": r.justification,
             "actor": r.actor, "at": r.at.isoformat(),
             "undone_at": r.undone_at.isoformat() if r.undone_at else None,
             "undone_by": r.undone_by,
             "primary": name(r.primary_asset_id), "duplicate": name(r.merged_asset_id)}
            for r in rows]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

#: the consolidated NER register, spec section 21. Column order is the reading
#: order of the screen so the two never disagree.
REGISTER_COLUMNS: list[tuple[str, str]] = [
    ("internal_id", "Internal id (never changes)"),
    ("code", "Register code"),
    ("current_name", "Current name"),
    ("suggested_name", "Name suggested by the tool"),
    ("previous_name", "Previous name"),
    ("aliases", "Other names / merged codes"),
    ("origin", "Origin"),
    ("building", "Building"),
    ("sector", "Sector"),
    ("level", "Level"),
    ("space_name", "Space"),
    ("space_code", "Space code"),
    ("environment", "Indoor / outdoor"),
    ("canonical_page", "Canonical page"),
    ("canonical_x", "Canonical x"),
    ("canonical_y", "Canonical y"),
    ("position_source", "Position source"),
    ("documents", "Documents"),
    ("pages", "Pages"),
    ("occurrence_count", "Occurrences"),
    ("marker_kinds", "Marker kind on the drawing"),
    ("detection_confidence", "Detection confidence"),
    ("classification", "Classification"),
    ("classification_confirmed", "Classification confirmed"),
    ("suggested_classification", "Classification suggested by the drawing"),
    ("status", "Status"),
    ("keep_decision", "Keep decision"),
    ("locked", "Locked"),
    ("total_ports", "Capacity (total ports)"),
    ("used_ports", "Used ports"),
    ("reserved_ports", "Reserved ports"),
    ("areas_served", "Areas served"),
    ("assigned_ports", "Demand assigned (ports)"),
    ("max_distance_m", "Longest serving distance (m)"),
    ("pathway", "Pathway"),
    ("containment", "Containment"),
    ("route_a", "Route A"),
    ("route_b", "Route B"),
    ("redundancy_status", "Redundancy status"),
    ("pending_validations", "Pending validations"),
    ("notes", "Comments"),
    ("updated_by", "Last changed by"),
    ("updated_at", "Last changed at"),
    ("merged_into", "Consolidated into"),
    ("removed_reason", "Removal reason"),
]


def _join(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    return str(v)


def register_rows(db: Session, project: Project) -> list[dict]:
    """Flat rows for CSV / XLSX export, including consolidated and removed NERs.

    Rows that left the register are *in* the export. A consolidated NER still
    resolves to the room it became, and a removed one still says why — which is
    the whole reason removal is not a delete.
    """
    codes = {a.id: a.code for a in db.execute(
        select(NerAsset).where(NerAsset.project_id == project.id)).scalars()}
    out: list[dict] = []
    for r in list_assets(db, project, include_removed=True):
        cap, cov, routes = r["capacity"], r["coverage"], r["routes"]
        out.append({
            "internal_id": r["id"], "code": r["code"],
            "current_name": r["display_name"],
            "suggested_name": r["suggested_name"] or "",
            "previous_name": r["previous_name"] or "",
            "aliases": _join(r["aliases"]),
            "origin": r["origin"],
            "building": r["building"] or "", "sector": r["sector"] or "",
            "level": r["level"] or "", "space_name": r["space_name"] or "",
            "space_code": r["space_code"] or "",
            "environment": r.get("environment") or "",
            "canonical_page": r["canonical"]["page"],
            "canonical_x": round(r["canonical"]["x"], 2),
            "canonical_y": round(r["canonical"]["y"], 2),
            "position_source": r["canonical"]["source"],
            "documents": _join(r["documents"]), "pages": _join(r["pages"]),
            "occurrence_count": r["occurrence_count"],
            "marker_kinds": _join(r["marker_kinds"]),
            "detection_confidence": round(r["confidence"], 3),
            "classification": r["classification"],
            "classification_confirmed": "yes" if r["classification_confirmed"] else "no",
            "suggested_classification": r["suggested_classification"] or "",
            "status": r["status"], "keep_decision": r["keep_decision"],
            "locked": "yes" if r["locked"] else "no",
            "total_ports": "unknown" if cap["total_ports"] is None else cap["total_ports"],
            "used_ports": cap["used_ports"], "reserved_ports": cap["reserved_ports"],
            "areas_served": "not analysed" if not cov["analysed"] else (cov["areas_served"] or 0),
            "assigned_ports": "not analysed" if not cov["analysed"] else (cov["assigned_ports"] or 0),
            "max_distance_m": "not analysed" if not cov["analysed"] else (cov["max_distance_m"] or ""),
            "pathway": "not analysed" if routes["pathway"] is None else routes["pathway"],
            "containment": "not analysed" if routes["containment"] is None else routes["containment"],
            "route_a": "not analysed" if routes["route_a"] is None else routes["route_a"],
            "route_b": "not analysed" if routes["route_b"] is None else routes["route_b"],
            "redundancy_status": routes["redundancy_status"],
            "pending_validations": _join(r["pending_validations"]),
            "notes": r["notes"],
            "updated_by": r["updated_by"], "updated_at": r["updated_at"] or "",
            "merged_into": codes.get(r["merged_into_id"], ""),
            "removed_reason": r["deleted_reason"],
        })
    return out


# ---------------------------------------------------------------------------
# Snapshots — the change request, and the design freeze
# ---------------------------------------------------------------------------

#: what a change request actually asks the drawing team to do
ACTIONABLE_STATUSES = (NerStatus.REJECTED, NerStatus.REPOSITION_PROPOSED,
                       NerStatus.SUGGESTED)


def _change_item(row: dict) -> Optional[dict]:
    """One row of the register expressed as a request, or ``None``.

    The three identity columns are not redundant. The internal code is what the
    database is sure about; the current name is what the drawing will be labelled
    with; the previous name is what the *last* request called it. Renumbering is
    routine here, so a request naming only the current label is how two teams end
    up meaning different rooms by the same word.
    """
    action = None
    detail = ""
    if row["keep_decision"] == KeepDecision.REJECT or row["status"] == NerStatus.REJECTED:
        action = "remove"
        detail = row["deleted_reason"] or "rejected in the register review"
    elif row["status"] == NerStatus.REPOSITION_PROPOSED and row["proposed_position"]:
        pp = row["proposed_position"]
        action = "reposition"
        detail = (f"from page {row['canonical']['page']} "
                  f"({row['canonical']['x']:.0f}, {row['canonical']['y']:.0f}) "
                  f"to page {pp['page']} ({pp['x']:.0f}, {pp['y']:.0f})"
                  + (f" — {pp['reason']}" if pp.get("reason") else ""))
    elif row["status"] == NerStatus.SUGGESTED and row["keep_decision"] == KeepDecision.KEEP:
        action = "add"
        s = row["suggestion"] or {}
        detail = s.get("reason", "suggested by the placement analysis")
    if action is None:
        return None
    return {
        "action": action,
        "internal_code": row["code"],
        "internal_id": row["id"],
        "current_name": row["display_name"],
        "previous_name": row["previous_name"] or "",
        "level": row["level"] or "",
        "building": row["building"] or "",
        "pages": row["pages"],
        "classification": row["classification"],
        "classification_confirmed": row["classification_confirmed"],
        "detail": detail,
        "outstanding": row["pending_validations"],
    }


def create_snapshot(db: Session, project: Project, *, kind: str, name: str,
                    reference: str = "", issued_to: str = "", note: str = "",
                    actor: str = "user") -> RegisterSnapshot:
    """Freeze the register under a name. There is no way to edit it afterwards."""
    if kind not in SnapshotKind.ALL:
        raise RegisterError(f"unknown snapshot kind “{kind}”")
    if not name.strip():
        raise RegisterError("a snapshot needs a name — it is what you will cite later")

    rows = list_assets(db, project, include_removed=True)
    items = [i for i in (_change_item(r) for r in rows) if i is not None]
    live = [r for r in rows if r["is_live"]]

    summary = {
        "ners_total": len(rows),
        "ners_live": len(live),
        "to_remove": sum(1 for i in items if i["action"] == "remove"),
        "to_reposition": sum(1 for i in items if i["action"] == "reposition"),
        "to_add": sum(1 for i in items if i["action"] == "add"),
        "criticality_unconfirmed": sum(1 for r in live
                                       if not r["classification_confirmed"]),
        "keep_undecided": sum(1 for r in live
                              if r["keep_decision"] == KeepDecision.UNDECIDED),
        "occurrences": sum(r["occurrence_count"] for r in rows),
    }

    snap = RegisterSnapshot(
        project_id=project.id, kind=kind, name=name.strip(),
        reference=reference.strip(), issued_to=issued_to.strip(), note=note,
        payload={"register": rows, "change_items": items,
                 "disclaimer": ("This tool supports the design process. It does "
                                "not replace engineering approval, a site "
                                "survey, cable route validation or physical "
                                "inspection.")},
        summary=summary, created_by=actor)
    db.add(snap)
    db.flush()
    _audit(db, project.id, f"register.snapshot.{kind}", entity_id=None, actor=actor,
           justification=note,
           payload={"snapshot_id": snap.id, "name": snap.name,
                    "reference": snap.reference, "issued_to": snap.issued_to,
                    **summary})
    db.commit()
    return snap


def snapshot_dict(s: RegisterSnapshot, *, with_payload: bool = False) -> dict:
    out = {
        "id": s.id, "kind": s.kind, "name": s.name, "reference": s.reference,
        "issued_to": s.issued_to, "note": s.note, "summary": s.summary,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "created_by": s.created_by,
    }
    if with_payload:
        out["change_items"] = (s.payload or {}).get("change_items", [])
        out["register"] = (s.payload or {}).get("register", [])
    return out


def list_snapshots(db: Session, project: Project) -> list[dict]:
    rows = db.execute(select(RegisterSnapshot)
                      .where(RegisterSnapshot.project_id == project.id)
                      .order_by(RegisterSnapshot.created_at.desc())).scalars().all()
    return [snapshot_dict(s) for s in rows]


def get_snapshot(db: Session, project: Project, snapshot_id: int) -> RegisterSnapshot:
    s = db.get(RegisterSnapshot, snapshot_id)
    if s is None or s.project_id != project.id:
        raise RegisterError("snapshot not found in this project")
    return s


#: columns of the change request, in the order the drawing team reads them
CHANGE_COLUMNS: list[tuple[str, str]] = [
    ("action", "Action"),
    ("internal_code", "Internal code (stable)"),
    ("current_name", "Name on the drawing"),
    ("previous_name", "Previously called"),
    ("building", "Building"),
    ("level", "Level"),
    ("pages", "Pages"),
    ("classification", "Classification"),
    ("classification_confirmed", "Classification confirmed"),
    ("detail", "What is being asked"),
    ("outstanding", "Still to validate"),
]
