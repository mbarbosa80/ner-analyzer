"""Persistence model.

The schema keeps four kinds of data strictly apart, because conflating them is how
a screening tool turns into a source of false confidence:

* ``extracted``  — what a document said
* ``confirmed``  — what a human signed off
* ``estimated``  — what the tool inferred to keep going
* ``proposed``   — what the optimiser recommends

Every element and match carries ``origin`` and ``confirmed_by`` so an export can
state which of the four it is.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list: JSON}


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    venue_code: Mapped[Optional[str]] = mapped_column(String(40), default=None)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)

    # editable policy
    general_limit_m: Mapped[float] = mapped_column(Float, default=90.0)
    photographer_limit_m: Mapped[float] = mapped_column(Float, default=70.0)
    near_limit_ratio: Mapped[float] = mapped_column(Float, default=0.90)
    routing_slack_factor: Mapped[float] = mapped_column(Float, default=1.0)
    display_units: Mapped[str] = mapped_column(String(8), default="m")
    demand_rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    match_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    synonyms: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The venue's NER naming convention (2.7.0): prefixes, and which functional
    #: areas carry which number — see ``domain/naming.py``. NULL means the
    #: default (the ALA sheet) until the project edits it.
    naming_convention: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=None)
    #: Fibre runs from the TER each NER needs (2.8.0): two for a critical room
    #: (A and B paths), one for a non-critical room, by default. A count the
    #: workbook multiplies out — never a length; nothing here measures a
    #: fibre route.
    fibre_runs_critical: Mapped[int] = mapped_column(Integer, default=2)
    fibre_runs_noncritical: Mapped[int] = mapped_column(Integer, default=1)

    #: Whether a stated criticality is allowed to *refuse* an assignment.
    #:
    #: Off by default, and that is a deliberate decision rather than caution.
    #: The engine has always been able to refuse a non-critical room for a
    #: critical space (:func:`coverage._criticality_ok`), and until the
    #: criticality matrix existed the rule simply never had data to act on.
    #: Turning it on the moment the data arrives would silently re-open every
    #: coverage result in every live study — spaces served today would become
    #: unserved, and decisions already sent to the drawing team would rest on
    #: numbers that had moved underneath them.
    #:
    #: What the criticality data is used for instead: the escalation report
    #: ("this NER serves a space the matrix marks critical, so it must be
    #: reclassified") and the redundancy rule (prefer keeping the critical room
    #: of an overlapping pair). Both *suggest*; neither changes an assignment.
    criticality_enforced: Mapped[bool] = mapped_column(Boolean, default=False)

    #: who created it. NULL only for projects that predate access control.
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None)
    #: "private" — only the owner and admins; "shared" — every signed-in user
    visibility: Mapped[str] = mapped_column(String(16), default="private")

    drawings: Mapped[list["Drawing"]] = relationship(back_populates="project",
                                                     cascade="all, delete-orphan")
    teap_files: Mapped[list["TeapFile"]] = relationship(back_populates="project",
                                                        cascade="all, delete-orphan")
    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="project",
                                                       cascade="all, delete-orphan")


class Drawing(Base):
    __tablename__ = "drawings"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(400))
    stored_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    extract_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="drawings")
    pages: Mapped[list["Page"]] = relationship(back_populates="drawing",
                                               cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("drawing_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    is_vector: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    sheet_title: Mapped[Optional[str]] = mapped_column(String(300), default=None)
    level: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    building: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    #: The drawing number printed in the title block (``OWC-401-CSL-O``), read
    #: from the ``DRAWING NUMBER`` label on import. NULL means never looked;
    #: an empty string means looked and found nothing — the distinction keeps
    #: the start-up backfill from re-reading a 45 MB book on every start.
    sheet_number: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    #: A key plan (2.13.0): an overview sheet — "KEY ENLARGED PLAN - LEVEL 01"
    #: in the title block — that only illustrates. Its rooms take part in no
    #: TEAP × drawing crossing and no NER is created from it. NULL = not
    #: decided yet (the start-up pass reads it off ``sheet_title``).
    key_plan: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    #: How it was decided: "title" (the title block) or "manual" (the person
    #: switched it in the Drawing viewer). A manual answer is never re-read.
    key_plan_source: Mapped[Optional[str]] = mapped_column(String(16), default=None)

    # scale
    metres_per_unit: Mapped[Optional[float]] = mapped_column(Float, default=None)
    scale_label: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    scale_source: Mapped[Optional[str]] = mapped_column(String(40), default=None)
    scale_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    scale_candidates: Mapped[list] = mapped_column(JSON, default=list)

    drawing: Mapped[Drawing] = relationship(back_populates="pages")


class Element(Base):
    """A TER / NER / IDF / COW / shaft marker, extracted or created by hand."""

    __tablename__ = "elements"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    drawing_id: Mapped[Optional[int]] = mapped_column(ForeignKey("drawings.id",
                                                                 ondelete="CASCADE"), index=True)
    scenario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenarios.id",
                                                                  ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(120))
    number: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)

    origin: Mapped[str] = mapped_column(String(16), default="extracted")   # extracted|manual|proposed
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    removable: Mapped[bool] = mapped_column(Boolean, default=True)
    movable: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)

    # capacity (all optional — absence must never imply a removal recommendation)
    total_ports: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    used_ports: Mapped[int] = mapped_column(Integer, default=0)
    reserved_ports: Mapped[int] = mapped_column(Integer, default=0)
    switch_capacity: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    patch_capacity: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    growth_margin_pct: Mapped[Optional[float]] = mapped_column(Float, default=None)
    power_available: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    cooling_available: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    space_available: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    security_constraints: Mapped[str] = mapped_column(Text, default="")
    access_constraints: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    #: A wireless point only (2.5.0): the TEAP space whose requested wireless
    #: port this access point stands in for, and how the tie was made —
    #: ``auto`` (the nearest matched room on the sheet, proposed when the point
    #: was placed or moved) or ``manual`` (chosen, or cleared, by a person; a
    #: cleared manual tie is ``space_key`` NULL with ``tie_source`` "manual",
    #: and is never re-proposed). NULL/NULL = never tied.
    space_key: Mapped[Optional[str]] = mapped_column(String(300), default=None)
    tie_source: Mapped[Optional[str]] = mapped_column(String(16), default=None)
    #: A wireless point only (2.11.0): the NER a person chose to serve it. NULL
    #: = not chosen — the point then follows the NER chosen for the TEAP space
    #: it stands in for, or, with none, the nearest-NER rule.
    assigned_ner_asset_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    #: A wireless point only (4.5.0): where the service is given — ``indoor``
    #: (a covered area) or ``outdoor`` (an open area); NULL = not said. Said by
    #: a person, never read off the drawing; it tells the LLD team the setting
    #: the access point is proposed for, as the same field does for a NER.
    environment: Mapped[Optional[str]] = mapped_column(String(16), default=None)

    # -- V2: this row is a *documental occurrence* of a canonical NER ---------
    #: the physical room this marker draws. NULL only for markers a human has
    #: not yet resolved, or for kinds that are not equipment rooms.
    ner_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ner_assets.id", ondelete="SET NULL"), default=None, index=True)
    #: state of the correspondence between this occurrence and the canonical NER
    link_status: Mapped[str] = mapped_column(String(20), default="unlinked")
    # unlinked | auto_linked | confirmed | disputed | rejected
    link_score: Mapped[float] = mapped_column(Float, default=0.0)
    detection_method: Mapped[str] = mapped_column(String(40), default="")
    symbol: Mapped[Optional[str]] = mapped_column(String(40), default=None)
    colour: Mapped[Optional[str]] = mapped_column(String(16), default=None)
    nearby_text: Mapped[str] = mapped_column(Text, default="")
    #: which document family this occurrence came from
    document_kind: Mapped[str] = mapped_column(String(8), default="VDB")   # VDB | TVDB
    viewport: Mapped[Optional[str]] = mapped_column(String(80), default=None)

    ner_asset: Mapped[Optional["NerAsset"]] = relationship(
        back_populates="occurrences", foreign_keys=[ner_asset_id])


class DrawingSpace(Base):
    """A functional space read off a drawing."""

    __tablename__ = "drawing_spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    space_code: Mapped[Optional[str]] = mapped_column(String(60), default=None)
    name: Mapped[str] = mapped_column(String(300))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    polygon: Mapped[list] = mapped_column(JSON, default=list)
    area_label: Mapped[Optional[str]] = mapped_column(String(40), default=None)
    origin: Mapped[str] = mapped_column(String(16), default="extracted")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class TeapFile(Base):
    __tablename__ = "teap_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(400))
    stored_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    uploaded_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    sheet: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    header_row: Mapped[int] = mapped_column(Integer, default=1)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    venue_filter: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    profiles: Mapped[list] = mapped_column(JSON, default=list)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="teap_files")


class MappingTemplate(Base):
    """A saved, reusable column mapping."""

    __tablename__ = "mapping_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    sheet_hint: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    header_row: Mapped[int] = mapped_column(Integer, default=1)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)


class TeapSpace(Base):
    """One functional space aggregated from the TEAP, with its port demand."""

    __tablename__ = "teap_spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    teap_file_id: Mapped[int] = mapped_column(ForeignKey("teap_files.id", ondelete="CASCADE"), index=True)
    space_key: Mapped[str] = mapped_column(String(300))
    space_code: Mapped[Optional[str]] = mapped_column(String(60), default=None)
    space_name: Mapped[str] = mapped_column(String(300))
    venue_code: Mapped[Optional[str]] = mapped_column(String(40), default=None)
    building: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    level: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    functional_area: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    criticality: Mapped[Optional[str]] = mapped_column(String(60), default=None)
    #: Where that criticality came from: "matrix" (the matrix names this exact
    #: space code), "inherited:<CODE>" (it names an ancestor), "teap" (a column
    #: in the venue TEAP itself), or NULL when nothing states it. Kept because
    #: "critical because the programme said so" and "critical because I walked
    #: up the code tree" are different claims, and a reviewer needs to be able
    #: to disagree with the second without rejecting the first.
    criticality_source: Mapped[Optional[str]] = mapped_column(String(60), default=None)
    criticality_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    demand_type: Mapped[str] = mapped_column(String(20), default="general")
    total_ports: Mapped[float] = mapped_column(Float, default=0.0)
    wireless_required: Mapped[bool] = mapped_column(Boolean, default=False)
    lines: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    #: The equipment room a *person* decided should serve this space.
    #:
    #: The engine's own answer is the nearest compatible room, which is right
    #: until it is not. Creating a second NER beside an existing one is a
    #: statement that geometry alone is now wrong here: the existing room is
    #: full, or critical and non-critical services must not share it. Distance
    #: cannot see either of those, so the choice has to be sayable.
    #:
    #: A pin decides *which* room, and nothing else. Distance, limit and
    #: capacity are still evaluated and still reported exactly as they are — a
    #: pinned assignment that is 200 m away comes back out of limit, and one
    #: that overruns the room comes back over capacity. Letting a manual choice
    #: silence those would turn the register into a way of laundering a
    #: violation, and would defeat the very case this exists for: you pin
    #: *because* the old room is overloaded, so the tool has to keep saying so.
    assigned_ner_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ner_assets.id", ondelete="SET NULL"), default=None, index=True)
    assignment_reason: Mapped[str] = mapped_column(Text, default="")

    #: The NER the *TEAP* names for this space, verbatim, when the imported
    #: sheet carries a "serving NER" column (mapped on the Import screen). It
    #: is the first of the three sources of a serving room — the TEAP, then a
    #: person's choice, then the nearest room with free ports — and it is
    #: resolved to a register row by name at analysis time, never stored as an
    #: id, because the TEAP is somebody else's document and does not follow
    #: renames in the register.
    teap_serving_ner: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    assignment_by: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    assignment_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)

    #: The person's statement that the room they chose sits on **another level**
    #: than this space — the ``other level`` box on the Demand row, asked for by
    #: Marcelo on 10 Sep 2026 ("uma check box informando que a mesma está em
    #: outro nível"). The engine never assumes a room reaches another floor;
    #: this is the one thing that lets it honour a pin to a room on another
    #: page when no vertical route is registered: the ports then count against
    #: that room, and the distance is reported as *not measured* rather than
    #: invented. Cleared whenever the assignment changes, so it can never
    #: outlive the room it was said about.
    assigned_cross_level: Mapped[bool] = mapped_column(Boolean, default=False)

    #: The room on the drawing that a *person* said this TEAP line means.
    #:
    #: This lives here, on the TEAP space, and not only on the match row,
    #: because the match row is rebuilt every time the matching runs and the
    #: decision is not. The earlier design kept the association only in
    #: ``space_matches`` and tried to carry it across a re-run by snapshotting
    #: the table immediately before deleting it. That works until anything
    #: disturbs the snapshot — a row the matcher no longer reports, a TEAP
    #: re-import, an exception between the delete and the re-insert — and when
    #: it fails it fails silently, because the rows come straight back wearing
    #: the automatic answer. A person then sees their morning's work undone
    #: with no error to point at.
    #:
    #: So the human answer is stored where nothing sweeps it up. ``run_matching``
    #: now *reads* these columns instead of trying to preserve its own table,
    #: which means the association survives a re-run, a wipe of ``space_matches``,
    #: and a re-import of the TEAP (the tie is to this row, and the row is found
    #: again by its stable ``space_key``, never by a database id that SQLite is
    #: free to recycle).
    #:
    #: ``locked_verdict`` is what the person actually said, and the three values
    #: are genuinely different: "this room" (assigned), "this space is not on
    #: this drawing at all" (rejected), and "I have not looked yet" (NULL — let
    #: the matcher answer). Rejection carries no room, which is why it cannot be
    #: inferred from ``locked_drawing_space_id`` being NULL.
    locked_drawing_space_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drawing_spaces.id", ondelete="SET NULL"), default=None)
    #: "assigned", "rejected", or NULL when no person has decided.
    locked_verdict: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    #: True once the person signed the row off, as opposed to merely picking a room.
    locked_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    locked_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)
    #: How the room was arrived at when it was locked ("manual", "base_code", …),
    #: so a confirmed automatic match is not relabelled as a hand-picked one.
    locked_method: Mapped[str] = mapped_column(String(30), default="manual")


class SpaceMatchRow(Base):
    __tablename__ = "space_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    teap_space_id: Mapped[int] = mapped_column(ForeignKey("teap_spaces.id", ondelete="CASCADE"), index=True)
    drawing_space_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drawing_spaces.id", ondelete="SET NULL"), default=None, index=True)
    method: Mapped[str] = mapped_column(String(30), default="none")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    exception: Mapped[Optional[str]] = mapped_column(Text, default=None)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    #: The matcher's own answer, kept beside whatever a person decided (2.6.0).
    #: A hand-picked room overwrites ``drawing_space_id``; these columns are
    #: what ``Undo`` puts back, so a wrong click is reversible without a re-run.
    #: ``auto_method`` is NULL on a row no run has refreshed since 2.6.0.
    auto_drawing_space_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drawing_spaces.id", ondelete="SET NULL"), default=None)
    auto_method: Mapped[Optional[str]] = mapped_column(String(30), default=None)
    auto_score: Mapped[float] = mapped_column(Float, default=0.0)
    auto_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    auto_reason: Mapped[str] = mapped_column(Text, default="")
    auto_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class SpaceOccurrenceLink(Base):
    """The same space, on another page.

    A design book cuts one level into many sheets, and a room on a match line
    is labelled on both of them. The matcher ties a TEAP line to **one** of
    those labels; when that one sits in the corner of a sheet with no NER, the
    space used to come back as "no NER on this level" while the NER serving it
    was a few metres away on the neighbouring sheet (Marcelo, 17 Sep 2026).

    A row here says: *this other label, on that other page, is the same space
    as the one this TEAP line is tied to.* Once it is ``confirmed`` the coverage
    engine may measure from it as well — a real distance, on the NER's own
    sheet, at that sheet's scale.

    Merge on proof, ask on suspicion — the rule the NER register already uses:

    * same full space code **and** both pages on the same known level →
      ``confirmed`` automatically (``auto`` is true, the evidence is recorded,
      and a person can still say "not the same");
    * same code but a level nobody could read, or the same *name* with no code
      → ``proposed``: a question on the Demand row, never an answer;
    * levels known and different → no row at all. That is another floor, and
      the ``other level`` box is how another floor is declared.

    A person's verdict (``decided_by`` set) is never overwritten by a matching
    run. The row is keyed on the TEAP space and the drawing space, and goes
    when either of them goes.
    """

    __tablename__ = "space_occurrence_links"
    __table_args__ = (UniqueConstraint("teap_space_id", "drawing_space_id",
                                       name="uq_occurrence_link"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    teap_space_id: Mapped[int] = mapped_column(
        ForeignKey("teap_spaces.id", ondelete="CASCADE"), index=True)
    drawing_space_id: Mapped[int] = mapped_column(
        ForeignKey("drawing_spaces.id", ondelete="CASCADE"), index=True)
    #: "proposed", "confirmed" or "rejected".
    verdict: Mapped[str] = mapped_column(String(12), default="proposed")
    #: True while the verdict is the rule's and not a person's.
    auto: Mapped[bool] = mapped_column(Boolean, default=True)
    #: "exact_code" or "name".
    method: Mapped[str] = mapped_column(String(20), default="exact_code")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    #: How the two pages' levels compare: "title_block" (same level, read off
    #: both sheets — the only basis that links without asking), "drawing_number"
    #: (same level, but at least one side only implied by the drawing number),
    #: or "unknown".
    level_basis: Mapped[str] = mapped_column(String(20), default="unknown")
    decided_by: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    decided_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)


class Zone(Base):
    """Permitted / forbidden zone, technical room, or a photographer area."""

    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    #: the book the zone is drawn on (4.1.0); NULL = the project's first
    drawing_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    page: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))     # permitted|forbidden|technical|photographer
    label: Mapped[str] = mapped_column(String(200), default="")
    polygon: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")


class RouteSegmentRow(Base):
    __tablename__ = "route_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    #: the book the segment is drawn on (4.1.0); NULL = the project's first
    drawing_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    page: Mapped[int] = mapped_column(Integer)
    x0: Mapped[float] = mapped_column(Float)
    y0: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(24), default="tray")
    label: Mapped[str] = mapped_column(String(200), default="")


class VerticalLinkRow(Base):
    __tablename__ = "vertical_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    #: the books of the two ends (4.1.0); NULL = the project's first
    lower_drawing_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    upper_drawing_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    lower_page: Mapped[int] = mapped_column(Integer)
    lower_x: Mapped[float] = mapped_column(Float)
    lower_y: Mapped[float] = mapped_column(Float)
    upper_page: Mapped[int] = mapped_column(Integer)
    upper_x: Mapped[float] = mapped_column(Float)
    upper_y: Mapped[float] = mapped_column(Float)
    length_m: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(24), default="shaft")
    label: Mapped[str] = mapped_column(String(200), default="")


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="as_is")   # as_is|proposed|custom
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    created_by: Mapped[str] = mapped_column(String(120), default="user")
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenarios.id"), default=None)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="scenarios")


class Alias(Base):
    """A curated TEAP -> drawing mapping the matcher cannot infer.

    The reference venue has spaces the TEAP calls ``OFFIC2``, ``OB VAN`` and
    ``BIOCA1b``; no similarity metric will ever connect those to the room names
    printed on the drawing. Only someone who knows the programme can. Because the
    space-code taxonomy is shared across every venue in the games, an alias
    recorded once is worth having again — so ``project_id`` may be NULL, meaning
    the alias applies everywhere.
    """

    __tablename__ = "aliases"
    __table_args__ = (UniqueConstraint("project_id", "kind", "teap_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True)
    kind: Mapped[str] = mapped_column(String(8))          # "code" | "name"
    teap_value: Mapped[str] = mapped_column(String(300))
    drawing_value: Mapped[str] = mapped_column(String(300))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="user")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    #: how many ports rode on the match that prompted this alias — used to show the
    #: curator where their next hour is best spent
    demand_hint: Mapped[float] = mapped_column(Float, default=0.0)


class Job(Base):
    """A long-running unit of work, so the HTTP handler never blocks on it.

    Ingesting a 34-page venue design book, matching thousands of spaces and
    solving the placement model all take far longer than a request should. Before
    this existed the only way to stop one was to kill the process.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | running | done | error | cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)     # 0..1
    stage: Mapped[str] = mapped_column(String(300), default="")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)
    finished_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id",
                                                                 ondelete="CASCADE"), index=True)
    at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    actor: Mapped[str] = mapped_column(String(120), default="user")
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    justification: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ===========================================================================
# V2 — canonical NER register
#
# V1 stored one ``Element`` per marker found on a drawing. That conflated two
# different things: the physical equipment room, and the fact that a document
# drew it on a page. A room printed on a key plan and again on a detail sheet
# produced two "NERs" that were really one.
#
# From V2 the two are separate:
#
#   ``NerAsset``  — the physical room. Owns the name, the classification, the
#                   keep/reject decision, the capacity and the canonical
#                   position. Its ``id`` never changes, not when it is renamed,
#                   not when a newer document version is imported.
#   ``Element``   — kept, but demoted to a *documental occurrence*: where this
#                   asset appears in one document, on one page, at one
#                   coordinate, with the confidence and evidence of that one
#                   detection. It now carries ``ner_asset_id``.
#
# Nothing is merged silently. Every link between an occurrence and an asset that
# the tool made on its own is written to ``NerConsolidation`` with its evidence,
# so it can be inspected, disputed and undone.
# ===========================================================================


class NerStatus(str):
    """Lifecycle of a canonical NER. Mirrors spec section 7."""

    IDENTIFIED = "identified"
    SUGGESTED = "suggested"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    CONFIRMED_WITH_CONSTRAINTS = "confirmed_with_constraints"
    REPOSITION_PROPOSED = "reposition_proposed"
    REJECTED = "rejected"
    CONSOLIDATED = "consolidated"

    ALL = ("identified", "suggested", "in_review", "confirmed",
           "confirmed_with_constraints", "reposition_proposed", "rejected",
           "consolidated")

    #: statuses that still describe a room the design intends to have
    LIVE = ("identified", "suggested", "in_review", "confirmed",
            "confirmed_with_constraints", "reposition_proposed")


class Criticality(str):
    CRITICAL = "critical"
    NON_CRITICAL = "non_critical"
    PENDING = "pending"

    ALL = ("critical", "non_critical", "pending")


class KeepDecision(str):
    KEEP = "keep"
    REJECT = "reject"
    UNDECIDED = "undecided"

    ALL = ("keep", "reject", "undecided")


class NerAsset(Base):
    """One physical equipment room, however many documents draw it."""

    __tablename__ = "ner_assets"
    __table_args__ = (UniqueConstraint("project_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    #: immutable, human-readable internal identifier (``NER-0007``). Assigned once
    #: and never rewritten — renaming touches ``display_name`` only.
    code: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(200))
    suggested_name: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    previous_name: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    #: other names the documents use for the same room
    aliases: Mapped[list] = mapped_column(JSON, default=list)

    kind: Mapped[str] = mapped_column(String(24), default="NER_NONCRITICAL")
    classification: Mapped[str] = mapped_column(String(20), default=Criticality.PENDING)
    suggested_classification: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    classification_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    #: what the drawing convention alone would say — recorded, never trusted on its own
    classification_evidence: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(32), default=NerStatus.IDENTIFIED)
    keep_decision: Mapped[str] = mapped_column(String(16), default=KeepDecision.UNDECIDED)
    in_as_is: Mapped[bool] = mapped_column(Boolean, default=True)
    in_proposed: Mapped[bool] = mapped_column(Boolean, default=True)

    origin: Mapped[str] = mapped_column(String(20), default="vdb_detection")
    # vdb_detection | manual | suggested | imported | tvdb

    building: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    sector: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    level: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    space_name: Mapped[Optional[str]] = mapped_column(String(300), default=None)
    space_code: Mapped[Optional[str]] = mapped_column(String(60), default=None)
    #: "indoor" / "outdoor" / NULL (2.14.0): where the rack stands. It decides
    #: the kind of rack the venue is sent, so it is a column of the NERs sheet
    #: of the workbook. Said by the person; the drawing is never read for it.
    environment: Mapped[Optional[str]] = mapped_column(String(16), default=None)

    #: canonical position — the one the coverage engine uses
    canonical_drawing_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drawings.id", ondelete="SET NULL"), default=None)
    canonical_page: Mapped[int] = mapped_column(Integer, default=1)
    canonical_x: Mapped[float] = mapped_column(Float, default=0.0)
    canonical_y: Mapped[float] = mapped_column(Float, default=0.0)
    position_source: Mapped[str] = mapped_column(String(24), default="occurrence")
    # occurrence | manual | suggested | tracker | unplaced

    #: False when this row has no position at all, as opposed to a position
    #: somebody is unsure about.
    #:
    #: A proposal read out of a VDB comments tracker can name a room that is not
    #: on the drawing set yet — five of the fourteen SPC proposals say exactly
    #: that: *"once those spaces are shown on the VDB"*. The requirement is real
    #: and must not be lost, but it has no coordinate, and the coordinate columns
    #: are not nullable. Zeroes would put the rack in the corner of page one.
    #:
    #: So this flag is the thing every reader consults. It is checked before the
    #: viewer draws a marker, before the exporter writes one, and before the
    #: coverage engine treats the room as a place a cable can reach.
    position_known: Mapped[bool] = mapped_column(Boolean, default=True)

    #: a proposed move, held next to the current position until a human accepts it
    proposed_page: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    proposed_x: Mapped[Optional[float]] = mapped_column(Float, default=None)
    proposed_y: Mapped[Optional[float]] = mapped_column(Float, default=None)
    reposition_reason: Mapped[str] = mapped_column(Text, default="")

    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    movable: Mapped[bool] = mapped_column(Boolean, default=True)

    # capacity — every field optional, because absence must never read as zero
    total_ports: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    used_ports: Mapped[int] = mapped_column(Integer, default=0)
    reserved_ports: Mapped[int] = mapped_column(Integer, default=0)
    switch_capacity: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    patch_capacity: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    growth_margin_pct: Mapped[Optional[float]] = mapped_column(Float, default=None)
    power_available: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    cooling_available: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    space_available: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    security_constraints: Mapped[str] = mapped_column(Text, default="")
    access_constraints: Mapped[str] = mapped_column(Text, default="")

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    #: the justification bundle for a suggested NER (spec section 5)
    suggestion: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending_validations: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

    #: set when this asset was folded into another; the row is kept, never deleted
    merged_into_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ner_assets.id", ondelete="SET NULL"), default=None, index=True)
    deleted_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)
    deleted_reason: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    updated_by: Mapped[str] = mapped_column(String(120), default="system")

    occurrences: Mapped[list["Element"]] = relationship(
        back_populates="ner_asset", foreign_keys="Element.ner_asset_id")

    @property
    def is_live(self) -> bool:
        return (self.deleted_at is None and self.merged_into_id is None
                and self.status in NerStatus.LIVE
                and self.keep_decision != KeepDecision.REJECT)

    @property
    def is_critical(self) -> bool:
        """Only a *confirmed* critical classification counts as critical.

        A red symbol on the drawing is a suggestion, never a decision — see
        spec section 4. Until a human confirms, the room is treated as
        non-critical for capacity purposes and flagged as pending.
        """
        return self.classification == Criticality.CRITICAL and self.classification_confirmed


class NerNameHistory(Base):
    """Every rename, so a report can be traced back to the name it was written under."""

    __tablename__ = "ner_name_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    ner_asset_id: Mapped[int] = mapped_column(ForeignKey("ner_assets.id",
                                                          ondelete="CASCADE"), index=True)
    old_name: Mapped[str] = mapped_column(String(200), default="")
    new_name: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    actor: Mapped[str] = mapped_column(String(120), default="user")


class NerConsolidation(Base):
    """A decision — by the tool or by a human — about whether two occurrences
    or two assets are the same physical room.

    ``decision`` is deliberately three-valued. "These are different rooms" is a
    finding worth keeping: it stops the duplicate detector from asking the same
    question at every run.
    """

    __tablename__ = "ner_consolidations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    primary_asset_id: Mapped[int] = mapped_column(ForeignKey("ner_assets.id",
                                                              ondelete="CASCADE"))
    merged_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ner_assets.id", ondelete="SET NULL"), default=None)

    decision: Mapped[str] = mapped_column(String(16), default="pending")
    # merged | separate | pending
    method: Mapped[str] = mapped_column(String(16), default="manual")   # auto | manual
    score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    differences: Mapped[list] = mapped_column(JSON, default=list)
    #: everything needed to put the two assets back the way they were
    undo_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    justification: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="user")
    at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    undone_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)
    undone_by: Mapped[Optional[str]] = mapped_column(String(120), default=None)


class SnapshotKind(str):
    """Why a register was frozen."""

    CHANGE_REQUEST = "change_request"
    FREEZE = "freeze"
    BASELINE = "baseline"

    ALL = ("change_request", "freeze", "baseline")


class RegisterSnapshot(Base):
    """The NER register, frozen at a named moment. Immutable once written.

    Two things in this workflow need the same object, so it is built once.

    **The change request.** Decisions go to the drawing team, they redraw, a new
    document version comes back, and the only question that matters is whether
    they did what was asked. That comparison is worthless without a baseline
    fixed at the moment of asking: if the request goes out, the reviewer changes
    their mind a week later and the revision then arrives, nothing can separate
    *the drawing diverging from the request* from *the reviewer diverging from
    their own request*. A snapshot taken later cannot reconstruct that — which is
    why this is the one piece of the versioning design that had to exist first.

    **The design freeze.** Near delivery, names and positions stop being
    editable, and what is frozen has to be recorded as the definitive register.
    That is the same act with a different name.

    Rows carry the internal code, the current name **and** the previous name, on
    purpose: the immutable code protects the database, but it does not protect
    the conversation with the drawing team. Renumbering — dropping NER 007 and
    renaming the last room to NER 007 — is normal here, and a request that names
    only "NER 007" lets both sides mean different rooms while believing they
    agree.

    There is deliberately no update path. Correcting a snapshot means issuing the
    next one.
    """

    __tablename__ = "register_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))

    kind: Mapped[str] = mapped_column(String(20), default=SnapshotKind.CHANGE_REQUEST)
    name: Mapped[str] = mapped_column(String(200))
    #: free external reference — a revision number, a ticket, an email subject
    reference: Mapped[str] = mapped_column(String(200), default="")
    #: who it went to; empty for a freeze
    issued_to: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")

    #: the whole register as it stood, plus the actionable subset
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    created_by: Mapped[str] = mapped_column(String(120), default="user")


# ===========================================================================
# Access control
#
# This is a single-machine tool. The server binds to 127.0.0.1 and opens no
# port on the network, and that — not the password — is its strongest security
# property. Accounts exist so that the venue design data on a shared or
# unattended laptop is not readable by whoever sits down at it, and so that
# every decision in the audit log names a real person rather than "user".
#
# What this deliberately is not: a multi-tenant system. Moving the app off
# loopback so colleagues can reach it is a different deployment with different
# obligations — TLS, an owner for the machine, backups, patching, access review.
# ===========================================================================


class Visibility(str):
    PRIVATE = "private"
    SHARED = "shared"

    ALL = ("private", "shared")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    #: scrypt, stored as ``scrypt$n$r$p$salt$hash`` — see ``app.auth``
    password_hash: Mapped[str] = mapped_column(String(400))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    last_login_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime, default=None)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)


class UserSession(Base):
    """A logged-in session.

    Server-side on purpose: the cookie carries nothing but an opaque random
    token, so there is no signed payload to get wrong and revoking a session is
    a delete rather than a token blacklist.
    """

    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime)
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class AppCounter(Base):
    """A number that only goes up (4.2.0): the highest project id ever handed
    out. SQLite gives a deleted project's id to the next one created (the
    table has no AUTOINCREMENT), so the new project inherited the old one's
    upload folder, export folder and per-project browser settings."""

    __tablename__ = "app_counters"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)

