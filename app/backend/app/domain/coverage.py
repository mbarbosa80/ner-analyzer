"""Coverage engine: which NER serves which space, and does it comply.

Assignment order is deterministic (spaces sorted by demand then by key, NERs by
effective distance then by key) so that two runs on the same inputs always give
byte-identical results — a hard requirement for an auditable design tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .distance import (DemandType, DistanceEvaluation, DistanceMethod, DistanceRules,
                       Status, evaluate_area, evaluate_cross_level, group_of)
from .geometry import Area, Point
from .sheetnames import page_label
from .pdf_ingest import ElementKind
from .routes import RouteNetwork
from .units import Scale

CRITICAL_KINDS = {ElementKind.NER_CRITICAL}

#: The only rooms that may be assigned to serve a functional area.
#:
#: **A NER, and nothing else.** COW was in this set until 2 Sep 2026 and should
#: not have been: a COW is a temporary cabin, and letting the engine hand it a
#: hundred permanent ports because it happened to be the nearest thing on the
#: sheet is a design decision the geometry has no business making. TER, IDF and
#: SHAFT were never here.
#:
#: Everything outside this set is recorded, drawn, moved and deleted exactly as
#: before — it simply never appears as an option to serve a space, never gets a
#: coverage radius, and never turns up in the port load. It is on the plan
#: because the plan should show what is in the building.
SERVING_KINDS = {ElementKind.NER_CRITICAL, ElementKind.NER_NONCRITICAL}


@dataclass
class NER:
    """An equipment room that can serve functional spaces.

    Only a NER is in :data:`SERVING_KINDS`. A TER, an IDF and a COW are recorded
    and drawn, but none of them is ever assigned as the serving room for a
    functional area — the TER↔NER relationship is a separate design rule that
    this tool does not invent, and a COW is a temporary cabin rather than a
    place a hundred permanent ports terminate.
    """

    key: str
    label: str
    kind: str
    point: Point
    critical: bool = False
    total_ports: Optional[int] = None
    used_ports: int = 0
    reserved_ports: int = 0
    locked: bool = False
    removable: bool = True
    movable: bool = True
    level: Optional[str] = None
    confidence: float = 1.0
    proposed: bool = False
    notes: list[str] = field(default_factory=list)
    #: "indoor" / "outdoor" / None (2.14.0): where the rack stands — it decides
    #: the kind of rack the venue is sent. Carried into the workbook, never
    #: used in a measurement.
    environment: Optional[str] = None
    #: The same room drawn on other sheets (3.0.0): one point per marker that
    #: is not the canonical one. A room drawn on four overlapping plans is one
    #: NER standing in one place; each sheet shows it where that sheet draws
    #: it. Distances are measured from the marker on the space's own sheet,
    #: and the marked-up PDF draws every marker where it is.
    other_points: list[Point] = field(default_factory=list)

    @property
    def points(self) -> list[Point]:
        """Every place this room is drawn — the canonical marker first."""
        return [self.point, *self.other_points]

    def point_on(self, page: int, near: Optional[Point] = None) -> Optional[Point]:
        """Where this room is drawn on ``page`` (the marker nearest ``near``
        when the sheet draws it twice), or ``None``."""
        here = [q for q in self.points if q.page == page]
        if not here:
            return None
        if near is None or len(here) == 1:
            return here[0]
        return min(here, key=lambda q: (q.x - near.x) ** 2 + (q.y - near.y) ** 2)

    @property
    def capacity_known(self) -> bool:
        return self.total_ports is not None

    @property
    def available_ports(self) -> Optional[float]:
        if self.total_ports is None:
            return None
        return max(0.0, self.total_ports - self.used_ports - self.reserved_ports)

    @property
    def can_serve(self) -> bool:
        return self.kind in SERVING_KINDS


@dataclass
class Assignment:
    space_key: str
    space_name: str
    area: Area
    demand_type: DemandType
    ports_required: float
    ner_key: Optional[str]
    ner_label: Optional[str]
    ner_critical: Optional[bool]
    evaluation: Optional[DistanceEvaluation]
    status: Status
    match_confirmed: bool
    reasons: list[str] = field(default_factory=list)
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    #: True when a person chose this room rather than the engine.
    pinned: bool = False
    #: When nothing serves the space, the closest NER and how far it is — so a
    #: row can say "nothing within 90 m; nearest is NER 5 at 120 m" instead of
    #: a blank. Empty when a room was assigned, or when nothing is measurable.
    nearest_label: Optional[str] = None
    nearest_distance_m: Optional[float] = None
    #: The page the serving room sits on. Usually the space's own page; when it
    #: is not, ``cross_level`` is true and the distance was either measured
    #: along a registered vertical route or not measured at all.
    ner_page: Optional[int] = None
    cross_level: bool = False
    #: The page the distance was measured on, when that is **not** the page the
    #: TEAP line was tied to: the same space is labelled on more than one sheet
    #: and the serving room is on one of the others. ``None`` otherwise.
    measured_page: Optional[int] = None
    #: A question, never an answer: the space is also labelled — unconfirmed —
    #: on another page, and from there a NER would reach it. Set only when the
    #: result as it stands is not "served", so it is asked only where the
    #: answer would change something.
    occurrence_hint: Optional[dict] = None
    #: "space" for a TEAP space, "wireless_point" for a point placed by hand.
    kind: str = "space"

    @property
    def unplaced(self) -> bool:
        """A TEAP space with no room on the drawing (page 0, no position)."""
        return bool(self.area.meta.get("unplaced"))

    def to_dict(self) -> dict:
        return {
            "space_key": self.space_key,
            "space_name": self.space_name,
            # An unplaced space has no page: ``None``, never 0, so a screen
            # does not print "page 0".
            "page": self.area.page or None,
            "unplaced": self.unplaced,
            "level": self.area.level,
            "building": self.area.building,
            "space_code": self.area.space_code,
            "demand_type": self.demand_type.value,
            "ports_required": self.ports_required,
            "ner_key": self.ner_key,
            "ner_label": self.ner_label,
            "ner_critical": self.ner_critical,
            "ner_page": self.ner_page,
            "cross_level": self.cross_level,
            "measured_page": self.measured_page,
            "occurrence_hint": self.occurrence_hint,
            "kind": self.kind,
            # Where the space sits on its sheet, and which drawing room it is
            # (2.8.0) — what the viewer paints the verdict on. None for an
            # unplaced space, which has nowhere to be painted.
            "x": None if self.unplaced else self.area.label_point.x,
            "y": None if self.unplaced else self.area.label_point.y,
            "drawing_space_id": self.area.meta.get("drawing_space_id"),
            "status": self.status.value,
            "match_confirmed": self.match_confirmed,
            "pinned": self.pinned,
            "nearest_label": self.nearest_label,
            "nearest_distance_m": (None if self.nearest_distance_m is None
                                   else round(self.nearest_distance_m, 2)),
            "reasons": self.reasons,
            "alternatives": [{"ner_key": k, "distance_m": round(d, 2)} for k, d in self.alternatives],
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
        }


def _wireless_notes(area: Area) -> list[str]:
    """What the row says about the wireless the TEAP asked for.

    Since 4.0.0 the TEAP is the only source of ports (Marcelo, 16 Oct 2026:
    *"AP não é um produto do TEAP. Mantenha somente a informação que já existe
    que é o produto DWISA"*). The space's ``DWISA`` line is counted on the
    space's own row, on the NER that serves the space, whether or not access
    points are drawn for it; a drawn access point is a position on the sheet,
    never a port of its own.
    """
    m = area.meta
    if m.get("kind") == "wireless_point":
        if m.get("space_key"):
            return [f"Wi-Fi point of {m.get('space_name') or m['space_key']} "
                    f"({'tied by you' if m.get('tie_source') == 'manual' else 'placed from the TEAP' if m.get('tie_source') == 'teap' else 'nearest matched room, proposed'})"
                    f" — its port is the space's DWISA line, counted on the space's row"]
        return ["tied to no TEAP space: not a TEAP product, no port counted"]
    w = m.get("teap_wireless_ports")
    if w:
        n = m.get("wireless_points_tied") or 0
        drawn = ("Wi-Fi point drawn for it" if n
                 else "no Wi-Fi point drawn for it yet")
        return [f"wireless requested in the TEAP (DWISA, {w:g} port(s)) counted on this "
                f"row — {drawn}"]
    return []


@dataclass
class CoverageResult:
    assignments: list[Assignment]
    ner_load: dict[str, dict]
    exceptions: list[dict]
    uncovered: list[str]

    def summary(self) -> dict:
        """The headline figures. **Spaces and wireless points are counted apart**:
        a wireless point is demand a person drew, not a TEAP space, and folding
        the two together would change what "spaces within limits" means."""
        ok = (Status.SERVED, Status.NEAR_LIMIT)
        spaces = [a for a in self.assignments if a.kind != "wireless_point"]
        points = [a for a in self.assignments if a.kind == "wireless_point"]
        point_keys = {a.space_key for a in points}
        by_status: dict[str, int] = {}
        by_group: dict[str, int] = {}
        for a in spaces:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            g = group_of(a.status.value).value
            by_group[g] = by_group.get(g, 0) + 1
        return {
            "spaces": len(spaces),
            "served": sum(1 for a in spaces if a.status in ok),
            "uncovered": sum(1 for k in self.uncovered if k not in point_keys),
            "exceptions": len(self.exceptions),
            "by_status": by_status,
            # The four piles a person reads the list in — see ``distance.Group``.
            "by_group": by_group,
            # TEAP spaces with no room on the drawing: served by a NER a person
            # chose, or still pending.
            "unplaced": sum(1 for a in spaces if a.unplaced),
            "unplaced_assigned": sum(1 for a in spaces if a.unplaced and a.ner_key),
            "ner_count": len(self.ner_load),
            # Every port of the study is a TEAP port (4.0.0): the spaces' lines,
            # the DWISA wireless line included. An access point drawn on a sheet
            # adds none.
            "total_ports": round(sum(a.ports_required for a in spaces), 1),
            "ports_on_ner": round(sum(a.ports_required for a in spaces if a.ner_key), 1),
            "ports_pending": round(sum(a.ports_required for a in spaces if not a.ner_key), 1),
            "wireless_ports": round(sum(
                float(a.area.meta.get("teap_wireless_ports") or 0) for a in spaces), 1),
            "wireless_points": len(points),
            "wireless_points_tied": sum(1 for a in points if a.area.meta.get("space_key")),
            "wireless_served": sum(1 for a in points if a.status in ok),
            "wireless_not_served": sum(1 for a in points if a.ner_key is None),
            "measured_from_another_page": sum(1 for a in spaces if a.measured_page),
        }


def _criticality_ok(space_critical: Optional[bool], ner: NER) -> bool:
    """A critical space must not be served by a non-critical room."""
    if space_critical is None:
        return True
    if space_critical and not ner.critical:
        return False
    return True


def _occurrence_hint(area: Area, demand_type: DemandType, serving: Sequence[NER],
                     scale_for_page: dict[int, Scale], rules: DistanceRules
                     ) -> Optional[dict]:
    """The best *unconfirmed* occurrence of this space, if one would be served.

    Never used to assign anything. It turns "no NER on this level" into the
    question it really is — "page 32 shows the same code 34 m from NER 20; is
    that this space?" — and only when the answer would change the result.
    """
    best: Optional[dict] = None
    for occ in area.meta.get("proposed_occurrences") or []:
        scale = scale_for_page.get(occ.page)
        for ner in serving:
            npt = ner.point_on(occ.page, occ.representative_point())
            if npt is None:
                continue
            ev = evaluate_area(area=occ, ner_point=npt, scale=scale, rules=rules,
                               demand_type=demand_type, route_length_m=None,
                               match_confirmed=True)
            if ev.effective_distance_m is None or not ev.compliant:
                continue
            if best is None or ev.effective_distance_m < best["distance_m"]:
                best = {"link_id": occ.meta.get("link_id"), "page": occ.page,
                        "method": occ.meta.get("link_method") or "exact_code",
                        "ner_label": ner.label, "ner_key": ner.key,
                        "distance_m": round(ev.effective_distance_m, 2)}
    return best


#: What the row says when a TEAP space has no room on the drawing and nobody
#: has chosen a NER for it. Quoted by the Demand screen and the workbook.
UNPLACED_PENDING_REASON = (
    "no room on the drawing for this TEAP space — tie it to a room on "
    "TEAP × drawing, or choose the NER that serves it here")


def _assign_unplaced(area: Area, ports: float, demand_type: DemandType,
                     pin_key: Optional[str], who: str, serving: Sequence[NER],
                     load: dict[str, dict], rules: DistanceRules,
                     assignments: list[Assignment], exceptions: list[dict],
                     uncovered: list[str]) -> None:
    """A TEAP space with no room on the drawing: served by decision, or pending.

    Marcelo, 22 Sep 2026: *"todo espaço que precisa de serviço de rede no TEAP
    vai ter que encontrar um lugar no desenho ou, mesmo que eu não ache um
    lugar, eu tenho que amarrar com uma NER existente ou criada, pq aí é o meu
    conhecimento pessoal da venue que me permite dizer qual NER vai atender
    aquele espaço."* Until 2.7.0 such a space simply never reached the engine:
    not counted on any room, absent from the summary, invisible in the
    workbook except as "not analysed".

    With a room chosen: the ports count against it, the status is
    :attr:`Status.ASSIGNED_NOT_PLACED`, no distance is invented, and the
    exception list carries the reminder — the same treatment as a room on
    another level with no vertical route. Without one: pending, on the list,
    with the sentence that says what would resolve it.
    """
    room = next((n for n in serving if n.key == pin_key), None) if pin_key else None
    if room is None:
        reasons = [UNPLACED_PENDING_REASON]
        if pin_key:
            reasons.insert(0, f"the room {'the TEAP names' if who == 'the TEAP' else 'you assigned'} "
                              f"({pin_key}) is no longer available to this space")
        assignments.append(Assignment(
            space_key=area.key, space_name=area.name, area=area,
            demand_type=demand_type, ports_required=ports,
            ner_key=None, ner_label=None, ner_critical=None,
            evaluation=None, status=Status.NOT_ANALYSABLE,
            match_confirmed=False, reasons=reasons))
        uncovered.append(area.key)
        # Not an exception row: the Exceptions step already lists every TEAP
        # space with no room on the drawing, from the match rows, and the
        # workbook's TEAP sheet says "pending — no room on the drawing" on
        # the line itself. A third copy of the same list would be noise.
        return
    by = "the TEAP names it" if who == "the TEAP" else "you assigned it"
    ev = DistanceEvaluation(
        status=Status.ASSIGNED_NOT_PLACED, demand_type=demand_type,
        method=DistanceMethod.STRAIGHT_LINE, limit_m=rules.limit_for(demand_type),
        geometric_distance_m=None, effective_distance_m=None, margin_m=None,
        scale_label=None, scale_confirmed=False,
        routing_slack_factor=rules.routing_slack_factor,
        assumptions=["The TEAP space is not on the drawing; its position is unknown "
                     f"and no distance was measured against the "
                     f"{rules.limit_for(demand_type):g} m limit."],
        warnings=["Served by the room a person chose, from their knowledge of the "
                  "venue. Validate the cable route on site."],
        requires_human_validation=True)
    reasons = [
        f"no room on the drawing for this TEAP space — served by {room.label} "
        f"because {by}; its {ports:.0f} port(s) count against {room.label}'s "
        f"capacity and no distance was measured"]
    if not room.capacity_known:
        reasons.append("capacity unknown for this NER")
    status = Status.ASSIGNED_NOT_PLACED
    if room.capacity_known:
        free = (room.total_ports - room.used_ports - room.reserved_ports
                - load[room.key]["assigned_ports"])
        if free < ports:
            status = Status.INSUFFICIENT_CAPACITY
            reasons.append(f"and it has {free:.0f} port(s) free against {ports:.0f} "
                           f"required — over capacity")
    load[room.key]["assigned_ports"] += ports
    load[room.key]["spaces"].append(area.key)
    load[room.key]["wireless_ports"] += float(area.meta.get("teap_wireless_ports") or 0)
    assignments.append(Assignment(
        space_key=area.key, space_name=area.name, area=area,
        demand_type=demand_type, ports_required=ports,
        ner_key=room.key, ner_label=room.label, ner_critical=room.critical,
        evaluation=ev, status=status, match_confirmed=True,
        reasons=reasons, pinned=True, ner_page=room.point.page))
    if status is Status.INSUFFICIENT_CAPACITY:
        uncovered.append(area.key)
        exceptions.append({
            "space_key": area.key, "space_name": area.name,
            "status": status.value, "page": None,
            "detail": f"assigned to {room.label} {'by the TEAP' if who == 'the TEAP' else 'by you'}; "
                      f"the room is out of ports",
        })
    else:
        exceptions.append({
            "space_key": area.key, "space_name": area.name,
            "status": status.value, "page": None,
            "detail": f"assigned to {room.label} {'by the TEAP' if who == 'the TEAP' else 'by you'} "
                      f"with no room on the drawing; distance not measured — "
                      f"validate the route on site, or tie the space to a room "
                      f"on TEAP × drawing when the sheet shows it",
        })


def compute_coverage(
    *,
    areas: Sequence[tuple[Area, float, DemandType, Optional[bool], bool]],
    ners: Sequence[NER],
    scale_for_page: dict[int, Scale],
    rules: DistanceRules,
    network: Optional[RouteNetwork] = None,
    respect_capacity: bool = True,
    pinned: Optional[dict[str, str]] = None,
    pin_sources: Optional[dict[str, str]] = None,
    cross_level: Optional[set[str]] = None,
) -> CoverageResult:
    """Assign every area to the most suitable NER.

    ``areas`` items are ``(area, ports_required, demand_type, is_critical,
    match_confirmed)``. ``is_critical`` may be ``None`` when the TEAP does not say,
    in which case the engine proposes the nearest compatible NER but flags the
    assignment for validation instead of inventing a classification.

    ``pinned`` maps a space key to the NER key a **person** chose for it, and
    that choice wins over the nearest-compatible answer. The reason it has to
    exist: putting a second NER beside an existing one is a statement that
    geometry is no longer the right criterion here — the old room is full, or
    critical and non-critical services must not share it. Distance can see
    neither, so the decision has to be sayable.

    A pin settles **which** room and nothing else. Distance, limit, criticality
    and capacity are still evaluated and still reported exactly as they come
    out: a pinned room 200 m away comes back out of limit; one whose ports are
    exhausted comes back over capacity. Letting the pin silence those would
    make it a way of laundering a violation — and would defeat the case it is
    for, since the whole point is that you pin *because* the other room is
    overloaded and you need the tool to keep saying so.

    ``cross_level`` is the set of space keys whose person has **declared** that
    the pinned room sits on another level — the ``other level`` box on the
    Demand row. The engine never assumes a room reaches another floor (that
    rule is older than this parameter and unchanged): a pinned room on another
    page with no vertical route registered is honoured only when this says
    so, and then with no distance and the status
    :attr:`Status.CROSS_LEVEL_NOT_MEASURED`. Without the declaration the space
    is left unassigned and the row asks for it — the load is not quietly moved
    to a room nobody chose. A room the TEAP names is a declaration in itself.
    """
    # Copies: the access points below are pinned to their space's NER as the
    # run goes (4.2.0), and the caller's maps must not change under it.
    pinned = dict(pinned or {})
    # Who fixed each pin — "you" unless told otherwise. A TEAP that names the
    # room is the other source, and the row has to say which it was.
    pin_sources = dict(pin_sources or {})
    cross_level = cross_level or set()
    serving = [n for n in ners if n.can_serve]
    load: dict[str, dict] = {
        n.key: {
            "label": n.label, "critical": n.critical, "page": n.point.page,
            "total_ports": n.total_ports, "assigned_ports": 0.0, "spaces": [],
            "capacity_known": n.capacity_known, "utilisation_pct": None,
            "proposed": n.proposed, "environment": n.environment,
            # Wireless points drawn by hand that this room carries, and the
            # ports they take — part of ``assigned_ports``, shown apart.
            # Access points drawn that this room reaches (a count of markers,
            # no ports), and the TEAP wireless ports (DWISA) of the spaces it
            # serves — part of ``assigned_ports``, shown apart (4.0.0).
            "wireless_points": 0, "wireless_ports": 0.0,
        } for n in serving
    }

    assignments: list[Assignment] = []
    exceptions: list[dict] = []
    uncovered: list[str] = []

    # The access points come after every TEAP space (4.2.0): a point follows
    # the NER that serves its space, whatever rule chose that NER, so the
    # spaces have to be answered first. Until 4.1.0 a point followed its
    # space only when a person or the TEAP had fixed the space's NER, and
    # otherwise went to the NER nearest to where it is drawn — its port (the
    # space's DWISA line) on one NER and the access point on another. On the
    # RIV workbook: SEC.005-01..07's seven ports on NER_23.1, their six
    # points on NER_25.1 and NER_27.1.
    def _is_point(t) -> bool:
        return t[0].meta.get("kind") == "wireless_point"

    ordered = sorted(areas, key=lambda t: (_is_point(t), -t[1], t[0].key))
    space_ner: Optional[dict[str, Optional[str]]] = None

    for area, ports, demand_type, is_critical, match_confirmed in ordered:
        if _is_point((area,)) and area.key not in pinned:
            if space_ner is None:
                space_ner = {a.space_key: a.ner_key for a in assignments
                             if a.area.meta.get("kind") != "wireless_point"}
            sk = area.meta.get("space_key")
            if sk and sk in space_ner:
                if space_ner[sk]:
                    pinned[area.key] = space_ner[sk]
                    pin_sources[area.key] = "the space"
                else:
                    # Its space has no NER yet: the point waits with it. It
                    # used to be counted on whichever NER was nearest, a room
                    # that carries none of the space's ports.
                    reason = (f"its TEAP space ({area.meta.get('space_name') or sk}) has no "
                              f"NER yet — a Wi-Fi point follows the NER that serves its "
                              f"space; choose that NER on Demand per space")
                    assignments.append(Assignment(
                        space_key=area.key, space_name=area.name, area=area,
                        demand_type=demand_type, ports_required=ports,
                        ner_key=None, ner_label=None, ner_critical=None,
                        evaluation=None, status=Status.NOT_ANALYSABLE,
                        match_confirmed=match_confirmed,
                        reasons=_wireless_notes(area) + [reason]))
                    uncovered.append(area.key)
                    exceptions.append({"space_key": area.key, "space_name": area.name,
                                       "status": Status.NOT_ANALYSABLE.value,
                                       "page": area.page, "detail": reason})
                    continue
        if area.meta.get("unplaced"):
            # A TEAP space the drawing does not show. Nothing can be measured,
            # so the only way it gets a room is a person choosing one — and
            # when they do, the ports count against that room exactly as they
            # would for a room on another level: counted, not measured, and
            # said so. Without a choice the space is pending, listed as such,
            # never quietly dropped from the study.
            _assign_unplaced(area, ports, demand_type, pinned.get(area.key),
                             pin_sources.get(area.key, "you"), serving, load,
                             rules, assignments, exceptions, uncovered)
            continue
        scale = scale_for_page.get(area.page)
        scored: list[tuple[float, NER, DistanceEvaluation]] = []
        #: NER key -> the occurrence of this space its distance was measured
        #: from. The tied occurrence first, so it wins a tie; then every other
        #: confirmed label of the same space, each on its own sheet and scale.
        via: dict[str, Area] = {}

        for ner in serving:
            best: Optional[tuple[float, DistanceEvaluation, Area]] = None
            for occ in (area, *area.occurrences):
                occ_scale = scale_for_page.get(occ.page)
                # The room's marker on this sheet when it has one (3.0.0):
                # a room drawn on two overlapping plans is measured where the
                # space's own sheet draws it, not from the other sheet's
                # coordinates.
                for npt in ner.points:
                    route_len = None
                    if network is not None:
                        r = network.route_length_m(occ.representative_point(), npt,
                                                   occ_scale) if occ_scale else None
                        if r:
                            route_len = r["length_m"]
                    if occ.page != npt.page and route_len is None:
                        continue
                    ev = evaluate_area(area=occ, ner_point=npt, scale=occ_scale,
                                       rules=rules, demand_type=demand_type,
                                       route_length_m=route_len,
                                       match_confirmed=match_confirmed)
                    if ev.effective_distance_m is None:
                        continue
                    if best is None or ev.effective_distance_m < best[0]:
                        best = (ev.effective_distance_m, ev, occ)
            if best is not None:
                scored.append((best[0], ner, best[1]))
                via[ner.key] = best[2]

        scored.sort(key=lambda t: (t[0], t[1].key))

        chosen: Optional[tuple[Optional[float], NER, DistanceEvaluation]] = None
        reasons: list[str] = _wireless_notes(area)
        rejected_for_capacity = False
        rejected_for_criticality = False
        # A pin to a room on another page that nobody has declared cross-level:
        # the space stays unassigned and the row says what it is waiting for.
        awaiting_declaration: Optional[NER] = None

        # A person's choice, honoured first and reported honestly.
        pin_key = pinned.get(area.key)
        if pin_key:
            pin = next((t for t in scored if t[1].key == pin_key), None)
            who = pin_sources.get(area.key, "you")
            by = ("the TEAP names it" if who == "the TEAP"
                  else "the TEAP space it stands in for is served by it" if who == "the space"
                  else "you assigned it")
            if pin is None:
                # Not measurable from here — but is it still a room? A pinned
                # NER on another page with no vertical route is exactly the
                # case Marcelo raised on 10 Sep 2026: the room one floor down,
                # in the same spot. It is honoured when he has said so.
                elsewhere = next((n for n in serving if n.key == pin_key
                                  and n.point_on(area.page) is None), None)
                # Since 2.10.0 the choice itself is the declaration (Marcelo,
                # 24 Sep 2026: "se eu escolhi, deveria ser served"): a room a
                # person picked on another page is counted from there, not
                # measured. ``cross_level`` is still accepted and still means
                # the same thing; it is no longer required.
                if elsewhere is not None:
                    ev = evaluate_cross_level(area=area, ner_point=elsewhere.point,
                                              scale=scale, rules=rules,
                                              demand_type=demand_type,
                                              match_confirmed=match_confirmed)
                    pin = (None, elsewhere, ev)
                elif elsewhere is not None:
                    awaiting_declaration = elsewhere
            if pin is not None:
                dist, ner, ev = pin
                if ev.status is Status.CROSS_LEVEL_NOT_MEASURED or (
                        dist is None and ner.point_on(area.page) is None):
                    reasons.append(
                        f"served by {ner.label} because {by}; it is on {page_label(ner.point.page)} "
                        f"and this space on {page_label(area.page)} — "
                        f"another level — with no shaft, riser or vertical route "
                        f"registered between them, so the distance was not "
                        f"measured. The {ports:.0f} port(s) count against "
                        f"{ner.label}'s capacity")
                else:
                    reasons.append(f"served by {ner.label} because {by}, "
                                   f"not because it is the nearest")
                if not ev.compliant and ev.effective_distance_m is not None:
                    reasons.append(
                        f"and it is {ev.effective_distance_m:.1f} m away against a "
                        f"{ev.limit_m:.0f} m limit — the assignment stands, the "
                        f"distance does not")
                if not _criticality_ok(is_critical, ner):
                    reasons.append("and it is not critical-rated for a space the "
                                   "matrix marks critical")
                if respect_capacity and ner.capacity_known:
                    remaining = (ner.total_ports - ner.used_ports - ner.reserved_ports
                                 - load[ner.key]["assigned_ports"])
                    if remaining < ports:
                        reasons.append(
                            f"and it has {remaining:.0f} port(s) free against "
                            f"{ports:.0f} required — over capacity")
                chosen = pin
            elif awaiting_declaration is not None:
                room = awaiting_declaration
                reasons.append(
                    f"you assigned {room.label}, which is on {page_label(room.point.page)} "
                    f"while this space is on {page_label(area.page)}, but 'other level' is "
                    f"unticked for this space and no vertical route is registered "
                    f"between the two pages — so {room.label} is not counted. Tick "
                    f"'other level' to count it from there, or choose a room on "
                    f"{page_label(area.page)}; until then its {ports:.0f} port(s) are not "
                    f"counted against any room")
            else:
                # The room is gone, rejected, or not measurable from here. Say
                # so rather than quietly falling back to the nearest one.
                reasons.append(f"the room {'the TEAP names' if who == 'the TEAP' else 'you assigned'} "
                               f"({pin_key}) is no longer available to this space — "
                               f"the nearest compatible room was used instead")

        if awaiting_declaration is not None:
            # Not the nearest room instead: he chose one, and the tool has no
            # business substituting another while the question is open.
            nearest = scored[0] if scored else None
            assignments.append(Assignment(
                space_key=area.key, space_name=area.name, area=area,
                demand_type=demand_type, ports_required=ports,
                ner_key=None, ner_label=None, ner_critical=None,
                evaluation=None, status=Status.NOT_ANALYSABLE,
                match_confirmed=match_confirmed, reasons=reasons,
                alternatives=[(n.key, d) for d, n, _ in scored[:3]],
                nearest_label=nearest[1].label if nearest else None,
                nearest_distance_m=nearest[2].effective_distance_m if nearest else None,
            ))
            uncovered.append(area.key)
            exceptions.append({
                "space_key": area.key, "space_name": area.name,
                "status": Status.NOT_ANALYSABLE.value, "page": area.page,
                "detail": reasons[-1],
            })
            continue

        for dist, ner, ev in scored:
            if chosen is not None:
                break
            if not _criticality_ok(is_critical, ner):
                rejected_for_criticality = True
                continue
            if respect_capacity and ner.capacity_known:
                remaining = (ner.total_ports - ner.used_ports - ner.reserved_ports
                             - load[ner.key]["assigned_ports"])
                if remaining < ports:
                    rejected_for_capacity = True
                    continue
            if not ev.compliant:
                continue
            chosen = (dist, ner, ev)
            break

        # Every room within the limit is out of ports. The rule Marcelo set on
        # 3 Sep 2026: take the nearest one anyway and say so. Leaving the
        # space with no room — what this did before — hid the demand from the
        # port load of the very room that will end up carrying it, and the
        # report is where he decides whether to draw a second NER there. The
        # overload is not softened: the status is *insufficient capacity*, the
        # row is an exception, and the utilisation goes past 100 %.
        #
        # Criticality is not relaxed the same way. When the project enforces
        # it, a critical space still never falls back onto a non-critical
        # room; that is a design rule, not a shortage.
        if chosen is None and scored and rejected_for_capacity:
            within = [t for t in scored
                      if t[2].compliant and _criticality_ok(is_critical, t[1])]
            if within:
                dist, ner, ev = within[0]
                reasons.append(
                    f"every NER within the distance limit is out of ports — "
                    f"assigned to the nearest one, {ner.label}, anyway; the "
                    f"overload is reported, not hidden")
                chosen = (dist, ner, ev)

        if chosen is None and scored:
            # nothing compliant: report the nearest option and why it fails
            dist, ner, ev = scored[0]
            status = ev.status
            if rejected_for_criticality:
                reasons.append("nearer NERs were skipped because they are not critical-rated")
            assignments.append(Assignment(
                space_key=area.key, space_name=area.name, area=area,
                demand_type=demand_type, ports_required=ports,
                ner_key=None, ner_label=None, ner_critical=None,
                evaluation=ev, status=status, match_confirmed=match_confirmed,
                reasons=reasons + [f"nearest NER is {ner.label} at "
                                   f"{ev.effective_distance_m:.1f} m "
                                   f"(limit {ev.limit_m:.0f} m)"],
                alternatives=[(n.key, d) for d, n, _ in scored[:3]],
                nearest_label=ner.label, nearest_distance_m=ev.effective_distance_m,
                measured_page=(via[ner.key].page if via.get(ner.key, area) is not area
                               else None),
            ))
            uncovered.append(area.key)
            exceptions.append({
                "space_key": area.key, "space_name": area.name,
                "status": status.value, "page": area.page,
                "detail": reasons[-1] if reasons else ev.summary(),
            })
            continue

        if chosen is None:
            assignments.append(Assignment(
                space_key=area.key, space_name=area.name, area=area,
                demand_type=demand_type, ports_required=ports,
                ner_key=None, ner_label=None, ner_critical=None,
                evaluation=None, status=Status.NOT_ANALYSABLE,
                match_confirmed=match_confirmed,
                reasons=_wireless_notes(area) + [
                    "no NER is measurable from this space "
                    "(no NER on this level and no vertical route registered)"],
            ))
            uncovered.append(area.key)
            exceptions.append({
                "space_key": area.key, "space_name": area.name,
                "status": Status.NOT_ANALYSABLE.value, "page": area.page,
                "detail": "no NER on this level and no registered shaft/riser",
            })
            continue

        dist, ner, ev = chosen
        was_pinned = bool(pin_key) and ner.key == pin_key

        # A room whose ports are exhausted must come back as exactly that,
        # whether a person pinned it or the capacity fallback above picked
        # it. ``ev.status`` only knows about distance, and the loop that
        # normally catches capacity was skipped for this space.
        status = ev.status
        if respect_capacity and ner.capacity_known:
            free = (ner.total_ports - ner.used_ports - ner.reserved_ports
                    - load[ner.key]["assigned_ports"])
            if free < ports and status is not Status.OUT_OF_LIMIT:
                status = Status.INSUFFICIENT_CAPACITY

        if is_critical is None:
            reasons.append("criticality not stated in the TEAP — nearest compatible NER "
                           "proposed, human validation required")
        if not ner.capacity_known:
            reasons.append("capacity unknown for this NER")
        if ev.method is DistanceMethod.STRAIGHT_LINE and ev.effective_distance_m is not None:
            reasons.append("straight-line screening distance; validate against the cable route")

        used = via.get(ner.key, area)
        if used is not area:
            reasons.append(
                f"measured from {page_label(used.page)}, where the same space is also "
                f"labelled ({used.meta.get('link_basis') or 'confirmed as the same space'}) "
                f"— {ner.label} is on that page; the TEAP line itself is tied to "
                f"{page_label(area.page)}")
            if used.estimated:
                reasons.append("the label on that page may sit at the edge of the sheet: "
                               "the distance is an estimate from the label position")

        load[ner.key]["assigned_ports"] += ports
        if area.meta.get("kind") == "wireless_point":
            load[ner.key]["wireless_points"] += 1
        else:
            load[ner.key]["spaces"].append(area.key)
            load[ner.key]["wireless_ports"] += float(area.meta.get("teap_wireless_ports") or 0)
        assignments.append(Assignment(
            space_key=area.key, space_name=area.name, area=area,
            demand_type=demand_type, ports_required=ports,
            ner_key=ner.key, ner_label=ner.label, ner_critical=ner.critical,
            evaluation=ev, status=status, match_confirmed=match_confirmed,
            reasons=reasons, pinned=was_pinned,
            # The next rooms by distance, the serving one left out — which is
            # not always ``scored[0]``: a pin or a full room moves it.
            alternatives=[(n.key, d) for d, n, _ in scored if n.key != ner.key][:3],
            ner_page=(ner.point_on(used.page) or ner.point).page,
            cross_level=(ner.point_on(used.page) is None),
            measured_page=(used.page if used is not area else None),
            kind=str(area.meta.get("kind") or "space"),
        ))
        # A room that does not comply is an exception like any other, whether
        # a person chose it or the capacity fallback did. Hiding it because
        # somebody chose it would be the one thing this feature must never do.
        if status in (Status.OUT_OF_LIMIT, Status.INSUFFICIENT_CAPACITY):
            who = ("by the TEAP" if was_pinned and pin_sources.get(area.key) == "the TEAP"
                   else "as its TEAP space" if was_pinned and pin_sources.get(area.key) == "the space"
                   else "by you" if was_pinned
                   else "as the nearest room, although it is full")
            exceptions.append({
                "space_key": area.key, "space_name": area.name,
                "status": status.value, "page": area.page,
                "detail": f"assigned to {ner.label} {who}; " + (
                    f"{ev.effective_distance_m:.1f} m of {ev.limit_m:.0f} m"
                    if status is Status.OUT_OF_LIMIT else "the room is out of ports"),
            })
            # Not served, whoever chose the room: "not covered" on the summary
            # has to count it, or a full room could be hidden behind a pin.
            uncovered.append(area.key)
        if status is Status.CROSS_LEVEL_NOT_MEASURED:
            # Served, counted, and still on the to-do list: the vertical route
            # is what turns "not measured" into a distance.
            who = ("by the TEAP" if pin_sources.get(area.key) == "the TEAP"
                   else "as its TEAP space" if pin_sources.get(area.key) == "the space"
                   else "by you")
            exceptions.append({
                "space_key": area.key, "space_name": area.name,
                "status": status.value, "page": area.page,
                "detail": f"assigned to {ner.label} {who} from {page_label(ner.point.page)} "
                          f"(another level); distance not measured — register the "
                          f"shaft, riser or vertical route to measure it",
            })
        if status is Status.NEAR_LIMIT:
            exceptions.append({
                "space_key": area.key, "space_name": area.name,
                "status": Status.NEAR_LIMIT.value, "page": area.page,
                "detail": f"{ev.effective_distance_m:.1f} m of {ev.limit_m:.0f} m "
                          f"({ev.margin_m:.1f} m margin)",
            })

    # Asked only where the answer would change the row: a space nothing
    # reaches. A row waiting on a match or a scale confirmation is waiting on
    # that, and a second question there is noise.
    ask_when = (Status.NOT_ANALYSABLE, Status.OUT_OF_LIMIT)
    for a in assignments:
        a.kind = str(a.area.meta.get("kind") or "space")
        if a.status not in ask_when or a.ner_key is not None:
            continue
        a.occurrence_hint = _occurrence_hint(a.area, a.demand_type, serving,
                                             scale_for_page, rules)
        if a.occurrence_hint:
            h = a.occurrence_hint
            a.reasons.append(
                f"the same {'code' if h['method'] == 'exact_code' else 'name'} is also "
                f"on {page_label(h['page'])}, where {h['ner_label']} is {h['distance_m']:.1f} m "
                f"away — confirm on this row that it is the same space and the next "
                f"run measures from there")

    for key, info in load.items():
        if info["total_ports"]:
            info["utilisation_pct"] = round(
                100.0 * info["assigned_ports"] / info["total_ports"], 1)
        else:
            info["capacity_note"] = "Capacity unknown."

    return CoverageResult(assignments=assignments, ner_load=load,
                          exceptions=exceptions, uncovered=uncovered)


def redundancy_candidates(result: CoverageResult, ners: Sequence[NER],
                          rules: DistanceRules) -> list[dict]:
    """NERs that carry no load, phrased strictly as spatial-redundancy candidates.

    Never a recommendation to remove: capacity, power, cooling, security and
    operational continuity are not modelled from the drawings.
    """
    out: list[dict] = []
    by_key = {n.key: n for n in ners}
    for key, info in result.ner_load.items():
        ner = by_key.get(key)
        if ner is None or ner.proposed:
            continue
        if info["spaces"] or info.get("wireless_points"):
            continue
        blockers: list[str] = []
        if ner.locked:
            blockers.append("element is locked by the user")
        if not ner.removable:
            blockers.append("flagged as not removable")
        if not ner.capacity_known:
            blockers.append("capacity unknown")
        if ner.critical:
            blockers.append("critical-rated room — redundancy must be preserved")
        out.append({
            "ner_key": key,
            "label": info["label"],
            "page": info["page"],
            "classification": "Spatial redundancy candidate — capacity and technical "
                              "requirements still to be validated.",
            "blockers": blockers,
            "eligible_for_removal_analysis": not blockers,
        })
    return out
