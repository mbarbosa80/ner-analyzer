"""Network port demand per functional space.

The rule hierarchy is fixed and auditable. For every TEAP line exactly one rule
fires, which is what structurally prevents double counting:

    A. explicit port count on the line   -> use it verbatim
    B. quantity x catalogue ports/unit   -> compute
    C. quantity x category default       -> compute, flagged as an assumption
    D. nothing usable                    -> 0 ports, flagged for review

Validated against ``TEAP v2.0.xlsx``: the workbook's ``Network Ports`` column
equals ``FINAL QTY x catalogue ports-per-unit`` on 17,495 of 17,495 checkable
lines, so rule A is both authoritative and internally consistent there. That is a
property of this workbook, not a guarantee — the importer re-verifies it and
raises a reconciliation warning wherever the two disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .distance import DemandType
from .teap_import import TeapImport, TeapRow

#: What each rule letter means, in the words a reviewer needs.
#:
#: The letter alone is house shorthand. On a sheet that leaves this application
#: it says nothing — the same problem as an internal room key in a column headed
#: with a room name. The letter stays first so the column still sorts and filters
#: by rule; the phrase after it is what makes the row readable without the
#: explanation column beside it.
RULE_LABEL: dict[str, str] = {
    "A": "A — explicit in the TEAP",
    "B": "B — quantity x catalogue",
    "C": "C — assumed from category",
    "D": "D — no data, needs review",
}


def rule_label(rule: str) -> str:
    """The rule letter with its meaning, for anything a person reads."""
    return RULE_LABEL.get(rule, rule)


PHOTO_HINTS = re.compile(
    r"\bPHOTO(?:GRAPH(?:ER|Y))?S?\b|\bPHT\b|\bPHOTO\s*POSITION\b|\bPHOTO\s*WORKROOM\b",
    re.IGNORECASE,
)

WIRELESS_HINTS = re.compile(r"\bWIRELESS\b|\bWI-?FI\b|\bACCESS\s*POINT\b|\bAP\b", re.IGNORECASE)

#: Editable per project. Ports consumed by one unit of a product category when the
#: catalogue does not say. Deliberately conservative and visible in the UI.
DEFAULT_CATEGORY_PORTS: dict[str, float] = {
    "laptop": 1.0,
    "desktop": 1.0,
    "computer": 1.0,
    "printer": 1.0,
    "multifunction": 1.0,
    "network services / wireless access": 1.0,
    "access point": 1.0,
    "telephony": 1.0,
    "voip": 1.0,
    "display": 0.0,
    "monitor": 0.0,
    "accessories / peripherals": 0.0,
    "furniture": 0.0,
    "power": 0.0,
}

DEFAULT_FALLBACK_PORTS = 0.0


@dataclass
class DemandRuleSet:
    """Editable demand policy for a project."""

    category_ports: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CATEGORY_PORTS))
    fallback_ports_per_unit: float = DEFAULT_FALLBACK_PORTS
    trust_explicit_total: bool = True
    growth_margin_pct: float = 0.0

    def ports_for_category(self, category: Optional[str]) -> Optional[float]:
        if not category:
            return None
        key = str(category).strip().lower()
        if key in self.category_ports:
            return self.category_ports[key]
        for k, v in self.category_ports.items():
            if k in key:
                return v
        return None


@dataclass
class LineDemand:
    """One TEAP line, resolved to a port count with its provenance."""

    row_number: int
    space_key: str
    product_code: Optional[str]
    product_description: Optional[str]
    quantity: float
    ports: float
    rule: str                       # "A" | "B" | "C" | "D"
    explanation: str
    warnings: list[str] = field(default_factory=list)


#: Sentinel for a space the TEAP marks both ways. Not a value anyone should
#: act on — it exists so the contradiction survives as far as the warning.
CRITICALITY_CONFLICT = "__conflict__"


def _read_criticality(row) -> Optional[str]:
    """Criticality as the TEAP states it, in whichever shape it states it.

    Two shapes are supported:

    * a single column holding a word ("Critical", "High", "Tier 1");
    * a **pair** of columns ticked with an X — ``Critical NER`` and
      ``Non-Critical NER`` — which is the event's layout.

    The pair is read first because it is the more specific statement. When both
    are ticked the answer is a conflict, never a guess: a space cannot be both,
    and choosing one silently would put a fabricated value into a study that
    drives equipment decisions.
    """
    from .teap_import import is_ticked

    crit = is_ticked(row.get("critical_flag"))
    non_crit = is_ticked(row.get("non_critical_flag"))

    if crit and non_crit:
        return CRITICALITY_CONFLICT
    if crit:
        return "critical"
    if non_crit:
        return "non-critical"

    # Neither ticked. Fall back to a single-column TEAP.
    single = str(row.get("criticality", "") or "").strip()
    return single or None


@dataclass
class SpaceDemand:
    """Aggregated demand for one functional space."""

    space_key: str
    space_code: Optional[str]
    space_name: str
    venue_code: Optional[str]
    building: Optional[str]
    level: Optional[str]
    functional_area: Optional[str]
    criticality: Optional[str]
    demand_type: DemandType
    total_ports: float
    lines: list[LineDemand] = field(default_factory=list)
    wireless_required: bool = False
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    #: The NER the TEAP itself names for this space, when its sheet carries a
    #: column for it. Read verbatim; resolving it to a register row happens at
    #: analysis time, because names change and the TEAP does not.
    serving_ner: Optional[str] = None

    @property
    def ports_with_growth(self) -> float:
        return self.total_ports

    def breakdown(self) -> list[str]:
        """Human-readable calculation memo, e.g. '3 x Laptop = 3 ports (rule B)'."""
        out = []
        for ln in self.lines:
            if ln.ports == 0 and ln.rule == "A":
                continue
            label = ln.product_description or ln.product_code or "item"
            out.append(f"{ln.quantity:g} x {label} = {ln.ports:g} port(s) "
                       f"[{rule_label(ln.rule)}]")
        out.append(f"TOTAL = {self.total_ports:g} port(s)")
        return out


def _as_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _space_key(row: TeapRow) -> str:
    venue = str(row.get("venue_code", "") or row.get("venue_name", "") or "").strip()
    code = str(row.get("space_code", "") or "").strip()
    name = str(row.get("space_name", "") or "").strip()
    return "|".join((venue.upper(), (code or name).upper()))


def resolve_line(row: TeapRow, rules: DemandRuleSet,
                 product_ports: dict[str, float]) -> LineDemand:
    qty = _as_float(row.get("quantity")) or 0.0
    explicit = _as_float(row.get("network_ports"))
    pcode = row.get("product_code")
    pcode_s = str(pcode).strip() if pcode else None
    pdesc = row.get("product_description")
    pdesc_s = str(pdesc).strip() if pdesc else None
    warnings: list[str] = []

    per_unit = product_ports.get(pcode_s) if pcode_s else None

    if rules.trust_explicit_total and explicit is not None:
        ports = explicit
        rule = "A"
        explanation = f"explicit port count on the TEAP line ({explicit:g})"
        if per_unit is not None and qty:
            expected = qty * per_unit
            if abs(expected - explicit) > 0.001:
                warnings.append(
                    f"reconciliation: explicit {explicit:g} != quantity {qty:g} x "
                    f"catalogue {per_unit:g} = {expected:g}; the explicit value was used"
                )
    elif per_unit is not None:
        ports = qty * per_unit
        rule = "B"
        explanation = f"{qty:g} x {per_unit:g} port(s)/unit from the product catalogue"
    else:
        cat_ports = rules.ports_for_category(row.get("product_category"))
        if cat_ports is not None:
            ports = qty * cat_ports
            rule = "C"
            explanation = (f"{qty:g} x {cat_ports:g} port(s)/unit assumed for category "
                           f"{row.get('product_category')!r}")
            warnings.append("port count assumed from a category default, not from data")
        else:
            ports = qty * rules.fallback_ports_per_unit
            rule = "D"
            explanation = ("no explicit ports, no catalogue entry and no category default; "
                           f"fallback {rules.fallback_ports_per_unit:g} port(s)/unit applied")
            warnings.append("no reliable port information for this line — review required")

    return LineDemand(
        row_number=row.row_number, space_key=_space_key(row), product_code=pcode_s,
        product_description=pdesc_s, quantity=qty, ports=float(ports), rule=rule,
        explanation=explanation, warnings=warnings,
    )


def compute_demand(imp: TeapImport, rules: Optional[DemandRuleSet] = None,
                   product_ports: Optional[dict[str, float]] = None) -> list[SpaceDemand]:
    """Aggregate a TEAP import into one :class:`SpaceDemand` per functional space."""
    rules = rules or DemandRuleSet()
    product_ports = product_ports if product_ports is not None else imp.product_ports
    spaces: dict[str, SpaceDemand] = {}

    for row in imp.rows:
        key = _space_key(row)
        line = resolve_line(row, rules, product_ports)

        sd = spaces.get(key)
        if sd is None:
            name = str(row.get("space_name", "") or row.get("space_code", "") or "").strip()
            code = row.get("space_code")
            fa = row.get("functional_area") or row.get("fa_code")
            haystack = " ".join(str(x) for x in (name, code, fa) if x)
            sd = SpaceDemand(
                space_key=key,
                space_code=str(code).strip() if code else None,
                space_name=name or "(unnamed)",
                venue_code=str(row.get("venue_code", "") or "").strip() or None,
                building=str(row.get("building", "") or "").strip() or None,
                level=str(row.get("level", "") or "").strip() or None,
                functional_area=str(fa).strip() if fa else None,
                criticality=_read_criticality(row),
                demand_type=(DemandType.PHOTOGRAPHER if PHOTO_HINTS.search(haystack)
                             else DemandType.GENERAL),
                total_ports=0.0,
            )
            if sd.criticality == CRITICALITY_CONFLICT:
                sd.criticality = None
                sd.warnings.append(
                    "the TEAP marks this space as BOTH critical and non-critical. "
                    "That contradiction is in the source document and this tool "
                    "will not pick a side: resolve it in the TEAP and re-import"
                )
            elif sd.criticality is None:
                sd.warnings.append(
                    "criticality is not stated in the TEAP; it must be confirmed by a "
                    "human before a critical/non-critical NER is assigned"
                )
            if sd.level is None:
                sd.warnings.append(
                    "no level/floor column in the TEAP; the level must come from the "
                    "drawing match, and cross-floor service cannot be assumed"
                )
            spaces[key] = sd

        # The TEAP's own answer to "which NER". First non-empty value wins; a
        # second, different one is a contradiction in the source and is said
        # so, because picking a side silently is exactly what this tool must
        # not do with a document somebody else owns.
        named = str(row.get("serving_ner", "") or "").strip()
        if named:
            if sd.serving_ner is None:
                sd.serving_ner = named
            elif named.casefold() != sd.serving_ner.casefold():
                sd.warnings.append(
                    f"the TEAP names more than one NER for this space "
                    f"(“{sd.serving_ner}” and “{named}”); “{sd.serving_ner}” was used")

        sd.lines.append(line)
        sd.total_ports += line.ports
        sd.warnings.extend(line.warnings)
        if WIRELESS_HINTS.search(" ".join(str(x) for x in
                                          (line.product_description, row.get("product_category"))
                                          if x)):
            sd.wireless_required = True

    for sd in spaces.values():
        if rules.growth_margin_pct:
            extra = sd.total_ports * rules.growth_margin_pct / 100.0
            sd.assumptions.append(
                f"growth margin of {rules.growth_margin_pct:g}% added "
                f"({extra:.1f} port(s))"
            )
            sd.total_ports += extra
        sd.warnings = list(dict.fromkeys(sd.warnings))

    return sorted(spaces.values(), key=lambda s: (-s.total_ports, s.space_name))
