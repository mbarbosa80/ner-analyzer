"""Overlapping rooms: which of a pair could actually be given up.

The rule this implements was stated as "two NERs crossing within 90 m and
serving the same area — the non-critical one can be suggested for removal".
Implemented literally that would have been a **loosening** of what the
application already did, and the difference is worth recording.

``coverage.redundancy_candidates`` only ever flags a room carrying **zero**
load, and there is a test — ``test_overlapping_ners_do_not_by_themselves_
justify_removal`` — pinning that down. Two rooms serving the same area both
carry load, so neither was ever flagged. Suggesting removal on overlap alone
would mean proposing to remove rooms that are actively serving spaces, with no
idea whether anything else can take them.

Two further problems with the rule as stated:

* **Proximity is not overlap.** 90 m is the limit from a room to the spaces it
  serves, not a spacing rule between rooms. Two NERs 89 m apart are not
  redundant by that fact; what matters is whether the sets of spaces they serve
  intersect, and whether one set is contained in what the other could reach.
* **The "more than 100 UTP cables" exception is capacity.** Writing 100 into
  the code makes a constant somebody has to maintain and that is wrong at every
  venue with a different cable plan. Simulating the removal makes the same
  exception appear on its own, expressed in ports the application already
  tracks, with the number in the report.

So: this module answers "if this room were gone, could every space it serves
still be reached, by a room with the capacity to take it?" A suggestion is only
produced when the answer is yes, and every refusal carries its reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .coverage import NER, CoverageResult
from .distance import DistanceRules
from .geometry import Point


@dataclass
class Reassignment:
    space_key: str
    ports: float
    to_ner: str
    distance_m: float


@dataclass
class OverlapVerdict:
    """One candidate room, and what would happen if it went."""

    ner_key: str
    label: str
    page: int
    critical: bool
    partner_key: Optional[str]
    partner_label: Optional[str]
    spaces_served: int
    ports_served: float
    can_be_removed: bool
    blockers: list[str]
    reassignments: list[Reassignment]

    def as_dict(self) -> dict:
        return {
            "ner_key": self.ner_key, "label": self.label, "page": self.page,
            "critical": self.critical,
            "overlaps_with": self.partner_key,
            "overlaps_with_label": self.partner_label,
            "spaces_served": self.spaces_served,
            "ports_served": round(self.ports_served, 1),
            "can_be_removed": self.can_be_removed,
            "blockers": self.blockers,
            "reassignments": [
                {"space_key": r.space_key, "ports": round(r.ports, 1),
                 "to": r.to_ner, "distance_m": round(r.distance_m, 1)}
                for r in self.reassignments],
            "classification": (
                "Removal candidate — every space it serves can be reached by "
                "another room with the capacity to take it."
                if self.can_be_removed else
                "Overlapping, but not removable — see the blockers."),
        }


def _distance_m(a: Point, b: Point, scale_for_page: dict, rules: DistanceRules
                ) -> Optional[float]:
    if a.page != b.page:
        return None
    sc = scale_for_page.get(a.page)
    if sc is None:
        return None
    return sc.to_metres(a.distance_units(b)) * rules.routing_slack_factor


def overlapping_candidates(result: CoverageResult, ners: Sequence[NER],
                           rules: DistanceRules, scale_for_page: dict,
                           *, areas_by_key: Optional[dict] = None
                           ) -> list[dict]:
    """Rooms that overlap another and could be given up.

    ``areas_by_key`` maps a space key to its ``(Area, ports, demand_type,
    critical)`` so the simulation knows where each space is and what it needs.
    Without it the module can still find overlaps but cannot prove a space
    stays reachable, and it says so rather than guessing.
    """
    by_key = {n.key: n for n in ners}
    load = result.ner_load
    verdicts: list[OverlapVerdict] = []

    for key, info in load.items():
        ner = by_key.get(key)
        if ner is None or ner.proposed or not info["spaces"]:
            continue

        # A partner is another live room close enough that their coverage can
        # plausibly intersect: within the general limit, same page.
        partner = None
        for other_key, other in load.items():
            if other_key == key:
                continue
            o = by_key.get(other_key)
            if o is None or o.proposed:
                continue
            d = _distance_m(ner.point, o.point, scale_for_page, rules)
            if d is None or d > rules.general_limit_m:
                continue
            # Prefer a critical partner: given a pair, the critical room is the
            # one to keep, which is the whole point of the rule.
            if partner is None or (o.critical and not by_key[partner].critical):
                partner = other_key
        if partner is None:
            continue

        blockers: list[str] = []
        if ner.critical:
            blockers.append("this is the critical room of the pair — the "
                            "non-critical one is the candidate, not this")
        if ner.locked:
            blockers.append("locked by a user")
        if not ner.removable:
            blockers.append("flagged as not removable")

        reassignments: list[Reassignment] = []
        if areas_by_key is None:
            blockers.append("cannot simulate the removal: the space positions "
                            "were not supplied to this check")
        else:
            # Spare capacity of every other room, as things stand.
            spare: dict[str, Optional[float]] = {}
            for k, inf in load.items():
                if k == key:
                    continue
                if not inf["capacity_known"] or inf["total_ports"] is None:
                    spare[k] = None
                else:
                    spare[k] = float(inf["total_ports"]) - float(inf["assigned_ports"])

            for space_key in info["spaces"]:
                entry = areas_by_key.get(space_key)
                if entry is None:
                    blockers.append(f"space {space_key} could not be located")
                    continue
                area, ports, demand_type, is_critical = entry
                limit = rules.limit_for(demand_type)
                best: Optional[tuple[str, float]] = None
                for k, inf in load.items():
                    if k == key:
                        continue
                    o = by_key.get(k)
                    if o is None or o.proposed or not o.can_serve:
                        continue
                    if is_critical and not o.critical:
                        continue
                    d = _distance_m(area.representative_point(), o.point,
                                    scale_for_page, rules)
                    if d is None or d > limit:
                        continue
                    room = spare.get(k)
                    if room is not None and room < ports:
                        continue
                    if best is None or d < best[1]:
                        best = (k, d)
                if best is None:
                    blockers.append(
                        f"{space_key} would be left without a room that can "
                        f"reach it and still has ports free")
                    continue
                reassignments.append(Reassignment(space_key, float(ports),
                                                  best[0], best[1]))
                if spare.get(best[0]) is not None:
                    spare[best[0]] -= float(ports)

        verdicts.append(OverlapVerdict(
            ner_key=key, label=info["label"], page=info["page"],
            critical=bool(info["critical"]),
            partner_key=partner, partner_label=load[partner]["label"],
            spaces_served=len(info["spaces"]),
            ports_served=float(info["assigned_ports"]),
            can_be_removed=not blockers,
            blockers=blockers, reassignments=reassignments))

    # The removable ones first; within each group, the one that frees most.
    verdicts.sort(key=lambda v: (not v.can_be_removed, -v.ports_served))
    return [v.as_dict() for v in verdicts]
