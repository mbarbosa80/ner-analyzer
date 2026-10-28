"""Matching TEAP spaces to spaces found on the drawings.

Why the space code comes first
------------------------------
The specification describes a name-similarity cascade. Measured against the real
event documents that would have been the weaker strategy: the venue design book
prints the **same space code taxonomy the TEAP uses** next to every room label
(``SPT.016.01``, ``TEC.004-02``, ``VVO.001``). Matching on the code is exact,
explainable and language-independent, so it runs first; fuzzy name matching is
kept as the fallback it should be.

Measured on one venue (``VEE``): 448 code instances on the drawing resolve to
142 distinct base codes; the TEAP lists 70 distinct base codes for the venue; 46
of those (66%) match a drawing code exactly. Of the 24 unmatched TEAP codes, a
large share are ``*.DUM`` placeholder rows that point at no real room — which the
matcher reports as a data-quality exception rather than trying to force a match.

Nothing here is confirmed silently. Anything below ``auto_confirm_threshold``
lands in the review queue.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

from rapidfuzz import fuzz, process

from .pdf_ingest import DetectedSpace
from .sheetnames import page_label, pages_label


class MatchMethod(str, Enum):
    ALIAS = "alias"
    EXACT_CODE = "exact_code"
    BASE_CODE = "base_code"
    EXACT_NAME = "exact_name"
    NORMALISED_NAME = "normalised_name"
    SYNONYM = "synonym"
    FUZZY_NAME = "fuzzy_name"
    CONTEXT = "context"
    NONE = "none"


#: Confidence assigned by each method before context adjustments.
METHOD_BASE_CONFIDENCE: dict[MatchMethod, float] = {
    MatchMethod.ALIAS: 0.99,          # a human wrote this mapping down on purpose
    MatchMethod.EXACT_CODE: 0.98,
    MatchMethod.BASE_CODE: 0.90,
    MatchMethod.EXACT_NAME: 0.92,
    MatchMethod.NORMALISED_NAME: 0.86,
    MatchMethod.SYNONYM: 0.80,
    MatchMethod.FUZZY_NAME: 0.0,     # derived from the similarity score
    MatchMethod.CONTEXT: 0.55,
    MatchMethod.NONE: 0.0,
}

#: An identical name on a TEAP line that carries no space code (4.4.0) — the
#: best evidence such a line can have, so it clears ``auto_confirm_threshold``
#: like an exact code does. Ambiguity and placeholder caps still apply.
EXACT_NAME_NO_CODE_CONFIDENCE = 0.97

PLACEHOLDER_CODE_RX = re.compile(r"\.(DUM|DUMMY|TBC|TBD|XXX)\b", re.IGNORECASE)
SPACE_CODE_RX = re.compile(r"\b([A-Z]{2,4})\.(\d{2,3})(?:[.\-](\d{1,3}))?(?:[.\-](\d{1,3}))?\b")  # 1–3 digits (4.2.0), as pdf_ingest

DEFAULT_SYNONYMS: dict[str, str] = {
    "vao": "venue accreditation office",
    "fop": "field of play",
    "ito": "international technical official",
    "nto": "national technical official",
    "wc": "toilets",
    "av": "audio visual",
    "f&b": "food and beverage",
    "fnb": "food and beverage",
    "ops": "operations",
    "mgmt": "management",
    "rm": "room",
    "stor": "storage",
    "off": "office",
    "wkrm": "work room",
    "vip": "very important person",
    # The TEAP is written in American English and the design books are not
    # always: VDD prints "Venue Media Centre (VMC)" for the TEAP's "Venue Media
    # Center (VMC)". Applied to both sides, so it can only bring names
    # together, never apart.
    "centre": "center",
    "theatre": "theater",
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalise_name(text: str, synonyms: Optional[dict[str, str]] = None) -> str:
    """Case-, accent-, punctuation- and abbreviation-insensitive form."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = SPACE_CODE_RX.sub(" ", s.upper()).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    syn = {**DEFAULT_SYNONYMS, **(synonyms or {})}
    tokens = [syn.get(t, t) for t in s.split()]
    return " ".join(tokens).strip()


def normalise_code(code: Optional[str]) -> Optional[str]:
    """``TEC.004-02`` and ``TEC.004.02`` normalise to the same string."""
    if not code:
        return None
    c = str(code).strip().upper().replace("-", ".")
    c = re.sub(r"\.+", ".", c)
    return c or None


def base_code(code: Optional[str]) -> Optional[str]:
    """``SPT.016.01`` -> ``SPT.016``."""
    n = normalise_code(code)
    if not n:
        return None
    parts = n.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else n


#: ``VEE-440B5-VVO-O`` → level 04; ``VFF-401-CSL-O`` → level 01;
#: ``VEE-410MB2-VVO-O`` → level 01M. The event's drawing numbers carry the level
#: as the digit after the series digit (4), either as ``4L0<area>`` on a detail
#: sheet or ``40L`` on an overall plan, with an ``M`` for a mezzanine.
SHEET_LEVEL_RX = re.compile(r"-4(?:0(\d)|(\d)0)(M?)(?:[A-Z]\d+)?-")


def level_from_sheet_number(sheet_number: Optional[str]) -> Optional[str]:
    """The level a drawing number implies, as ``LEVEL 04`` — or ``None``.

    **Weaker evidence than the title block**, and used as such: measured on the
    reference books it agrees with the title block on 68 sheets of 68, but it
    is a numbering convention, not a statement on the sheet. It is enough to
    rule *out* a label on another floor and to make a question easy to answer;
    it is never enough, on its own, to merge two labels without asking.
    """
    m = SHEET_LEVEL_RX.search(str(sheet_number or "").upper())
    if not m:
        return None
    return f"LEVEL 0{m.group(1) or m.group(2)}{m.group(3)}"


def is_placeholder_code(code: Optional[str]) -> bool:
    return bool(code and PLACEHOLDER_CODE_RX.search(str(code)))


# ---------------------------------------------------------------------------
# Match records
# ---------------------------------------------------------------------------

@dataclass
class MatchCandidate:
    drawing_space: DetectedSpace
    method: MatchMethod
    score: float
    confidence: float
    reason: str


@dataclass
class SpaceMatch:
    teap_key: str
    teap_code: Optional[str]
    teap_name: str
    building: Optional[str] = None
    level: Optional[str] = None
    best: Optional[MatchCandidate] = None
    alternatives: list[MatchCandidate] = field(default_factory=list)
    confirmed: bool = False
    rejected: bool = False
    exception: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.best is not None and not self.rejected

    @property
    def confidence(self) -> float:
        return self.best.confidence if self.best else 0.0

    def to_dict(self) -> dict:
        def cand(c: Optional[MatchCandidate]) -> Optional[dict]:
            if c is None:
                return None
            return {
                "drawing_name": c.drawing_space.name,
                "drawing_code": c.drawing_space.space_code,
                "page": c.drawing_space.page,
                "x": c.drawing_space.x, "y": c.drawing_space.y,
                "method": c.method.value, "score": round(c.score, 1),
                "confidence": round(c.confidence, 3), "reason": c.reason,
            }
        return {
            "teap_key": self.teap_key, "teap_code": self.teap_code,
            "teap_name": self.teap_name, "building": self.building, "level": self.level,
            "best": cand(self.best),
            "alternatives": [cand(c) for c in self.alternatives],
            "confirmed": self.confirmed, "rejected": self.rejected,
            "exception": self.exception, "notes": self.notes,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class MatchReport:
    matches: list[SpaceMatch]
    unmatched_teap: list[SpaceMatch] = field(default_factory=list)
    unmatched_drawing: list[DetectedSpace] = field(default_factory=list)
    duplicate_names: dict[str, int] = field(default_factory=dict)
    multi_level: dict[str, list[int]] = field(default_factory=dict)
    needs_review: list[SpaceMatch] = field(default_factory=list)
    placeholders: list[SpaceMatch] = field(default_factory=list)

    def stats(self) -> dict:
        total = len(self.matches) + len(self.unmatched_teap)
        return {
            "teap_spaces": total,
            "matched": len(self.matches),
            "unmatched_teap": len(self.unmatched_teap),
            "unmatched_drawing": len(self.unmatched_drawing),
            "needs_review": len(self.needs_review),
            "placeholders": len(self.placeholders),
            "match_rate": round(len(self.matches) / total, 4) if total else 0.0,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass
class MatchSettings:
    fuzzy_threshold: float = 82.0
    auto_confirm_threshold: float = 0.95
    ambiguity_margin: float = 0.06
    synonyms: dict[str, str] = field(default_factory=dict)
    restrict_to_level: bool = True
    #: Break a same-code tie in favour of the sheet that actually details the room.
    #: A venue design book prints the same space code on a key plan and on the level
    #: plan; treating that as ambiguous sent 36 of 41 review items on the reference
    #: venue to a human for no reason. The detail sheet is the one that carries the
    #: room, so it wins.
    prefer_detail_pages: bool = True
    #: page number -> plot-scale denominator. A smaller denominator is a more
    #: detailed sheet (1:200 details what 1:1500 only locates).
    page_scale_denominator: dict[int, float] = field(default_factory=dict)
    #: How much more detailed the winning sheet must be before the tie is called.
    #: A 4% difference in page rank is noise, not evidence; measured on the
    #: reference venue, six SEC.005-* rooms sat at exactly that margin and are
    #: rightly left for a human.
    page_rank_margin: float = 0.85
    #: TEAP value -> drawing value, curated by the user. Applied before similarity.
    code_aliases: dict[str, str] = field(default_factory=dict)
    name_aliases: dict[str, str] = field(default_factory=dict)


def _page_detail_rank(drawing_spaces: Sequence[DetectedSpace],
                      settings: MatchSettings) -> dict[int, float]:
    """Score each page by how much detail it carries. Higher is more detailed.

    Two independent signals, both derived from the documents themselves:

    * how many distinct spaces the page labels — a key plan labels a handful, a
      level plan labels dozens;
    * the plot-scale denominator, when known.
    """
    per_page: dict[int, set[str]] = {}
    for ds in drawing_spaces:
        key = normalise_code(ds.space_code) or normalise_name(ds.name, settings.synonyms)
        if key:
            per_page.setdefault(ds.page, set()).add(key)
    counts = {p: len(v) for p, v in per_page.items()}
    top = max(counts.values()) if counts else 1

    rank: dict[int, float] = {}
    for page, n in counts.items():
        score = n / top                                   # 0..1 by label density
        denom = settings.page_scale_denominator.get(page)
        if denom:
            # 1:100 -> 1.0, 1:1500 -> ~0.07. Bounded so density still matters.
            score += min(1.0, 100.0 / denom)
        rank[page] = score
    return rank


def match_spaces(teap_spaces: Sequence[tuple[str, Optional[str], str, Optional[str], Optional[str]]],
                 drawing_spaces: Sequence[DetectedSpace],
                 settings: Optional[MatchSettings] = None,
                 demand_by_key: Optional[dict[str, float]] = None) -> MatchReport:
    """Match TEAP spaces against drawing spaces.

    ``teap_spaces`` items are ``(key, space_code, space_name, building, level)``.
    ``demand_by_key`` is optional and only used to rank the review and exception
    lists by port count, so the biggest unresolved demand is at the top.
    """
    st = settings or MatchSettings()
    demand_by_key = demand_by_key or {}
    page_rank = _page_detail_rank(drawing_spaces, st) if st.prefer_detail_pages else {}

    by_code: dict[str, list[DetectedSpace]] = {}
    by_base: dict[str, list[DetectedSpace]] = {}
    by_norm: dict[str, list[DetectedSpace]] = {}
    for ds in drawing_spaces:
        nc = normalise_code(ds.space_code)
        if nc:
            by_code.setdefault(nc, []).append(ds)
            bc = base_code(nc)
            if bc:
                by_base.setdefault(bc, []).append(ds)
        nn = normalise_name(ds.name, st.synonyms)
        if nn:
            by_norm.setdefault(nn, []).append(ds)

    norm_choices = list(by_norm.keys())
    used_drawing: set[int] = set()
    matches: list[SpaceMatch] = []
    unmatched: list[SpaceMatch] = []
    needs_review: list[SpaceMatch] = []
    placeholders: list[SpaceMatch] = []

    for key, code, name, building, level in teap_spaces:
        sm = SpaceMatch(teap_key=key, teap_code=code, teap_name=name,
                        building=building, level=level)

        placeholder = is_placeholder_code(code)
        if placeholder:
            # A placeholder code is not a reason to stop looking. On the reference
            # venue, PRS.DUM.099 "Main Photo Position - FOP" carries 110 ports under
            # the 70 m photographer limit — the largest single demand in the venue.
            # Dropping it into an exception bucket silently removed it from the
            # analysis. The code is unusable, the NAME is real, so the name cascade
            # still runs and the row stays available for manual assignment.
            sm.notes.append(
                "placeholder space code — matched on name only; confirm the room manually")
            placeholders.append(sm)

        cands: list[MatchCandidate] = []
        nc, bc = (None, None) if placeholder else (normalise_code(code), base_code(code))
        nn = normalise_name(name, st.synonyms)

        # 0) curated alias — a human recorded this mapping, so it outranks everything
        alias_target = None
        if nc and st.code_aliases:
            alias_target = st.code_aliases.get(nc) or st.code_aliases.get(str(code).strip().upper())
        if alias_target is None and st.name_aliases:
            alias_target = st.name_aliases.get(nn) or st.name_aliases.get(str(name).strip().lower())
        if alias_target:
            target_code = normalise_code(alias_target)
            target_name = normalise_name(alias_target, st.synonyms)
            for ds in by_code.get(target_code or "", []) + by_norm.get(target_name, []):
                cands.append(MatchCandidate(
                    ds, MatchMethod.ALIAS, 100.0,
                    METHOD_BASE_CONFIDENCE[MatchMethod.ALIAS],
                    f"curated alias: '{code or name}' maps to '{alias_target}'"))

        # 1) exact code
        for ds in (by_code.get(nc or "", []) if not cands else []):
            cands.append(MatchCandidate(ds, MatchMethod.EXACT_CODE, 100.0,
                                        METHOD_BASE_CONFIDENCE[MatchMethod.EXACT_CODE],
                                        f"space code {code} matches the drawing exactly"))
        # 2) base code
        if not cands and bc:
            for ds in by_base.get(bc, []):
                cands.append(MatchCandidate(
                    ds, MatchMethod.BASE_CODE, 95.0,
                    METHOD_BASE_CONFIDENCE[MatchMethod.BASE_CODE],
                    f"base space code {bc} matches (sub-index differs: {code} vs {ds.space_code})"))
        # 3) exact / normalised name
        if not cands and nn:
            for ds in by_norm.get(nn, []):
                same_raw = str(ds.name).strip().lower() == str(name).strip().lower()
                method = MatchMethod.EXACT_NAME if same_raw else MatchMethod.NORMALISED_NAME
                conf = METHOD_BASE_CONFIDENCE[method]
                # An identical name is an exact match when the TEAP line has no
                # space code to go by (4.4.0): it is signed like an exact code,
                # unless another room answers to it (the ambiguity cap below
                # lowers it again). A line WITH a code the drawing does not
                # carry stays for review — the name alone may be the room
                # next door.
                if same_raw and not nc and not placeholder:
                    conf = EXACT_NAME_NO_CODE_CONFIDENCE
                cands.append(MatchCandidate(
                    ds, method, 100.0, conf,
                    "identical name" if same_raw
                    else f"names match after normalisation ('{name}' ~ '{ds.name}')"))
        # 4) fuzzy
        if not cands and nn and norm_choices:
            for cand_name, score, _ in process.extract(nn, norm_choices,
                                                       scorer=fuzz.token_sort_ratio, limit=4):
                if score < st.fuzzy_threshold:
                    continue
                for ds in by_norm[cand_name]:
                    cands.append(MatchCandidate(
                        ds, MatchMethod.FUZZY_NAME, float(score),
                        min(0.90, float(score) / 100.0 * 0.88),
                        f"text similarity {score:.0f}% ('{name}' ~ '{ds.name}')"))

        # -- context adjustment ------------------------------------------------
        for c in cands:
            if level and c.drawing_space.page is not None:
                pass  # level is validated downstream against the confirmed page level
            if building and c.drawing_space.name and building.lower() in c.drawing_space.name.lower():
                c.confidence = min(0.99, c.confidence + 0.03)
                c.reason += "; building context agrees"

        # Rank by confidence, then by how detailed the candidate's sheet is. The
        # page rank is what resolves a code printed on both a key plan and a level
        # plan without asking a human.
        cands.sort(key=lambda c: (c.confidence,
                                  page_rank.get(c.drawing_space.page, 0.0),
                                  c.score), reverse=True)

        if not cands:
            sm.exception = (
                "placeholder space code and no drawing space matches the name — "
                "assign the room manually" if placeholder
                else "no space on the drawings matches this TEAP location")
            unmatched.append(sm)
            continue

        sm.best = cands[0]
        sm.alternatives = cands[1:4]
        used_drawing.add(id(sm.best.drawing_space))

        pages = sorted({c.drawing_space.page for c in cands})
        if len(cands) > 1 and (cands[0].confidence - cands[1].confidence) < st.ambiguity_margin:
            top, runner = cands[0].drawing_space, cands[1].drawing_space
            best_rank = page_rank.get(top.page, 0.0)
            runner_rank = page_rank.get(runner.page, 0.0)
            # Compare BASE codes, not full codes. A sub-index difference
            # (PRS.006.02 against PRS.006.01) still means the same room family, and
            # requiring an exact match here defeated the tie-break on 11 of the 19
            # unresolved rooms on the reference venue.
            same_room = (base_code(top.space_code) is not None
                         and base_code(top.space_code) == base_code(runner.space_code))

            if st.prefer_detail_pages and same_room and top.page == runner.page:
                # The same room labelled more than once on ONE sheet. That is not a
                # question about which sheet — it is a repeated tag. Prefer the
                # instance carrying an area figure, which is the real room label.
                same_page = [c for c in cands if c.drawing_space.page == top.page]
                labelled = next((c for c in same_page if c.drawing_space.area_label), None)
                if labelled is not None and labelled is not sm.best:
                    sm.best = labelled
                sm.notes.append(
                    f"the code is labelled {len(same_page)} times on {page_label(top.page)}; "
                    f"the instance carrying the room's area figure was used")
            elif (st.prefer_detail_pages and same_room
                  and runner_rank < best_rank * st.page_rank_margin):
                # Same room drawn on more than one sheet: this is not ambiguity,
                # it is how a design book is organised.
                sm.best.reason += (f"; the same code appears on {pages_label(pages)} and "
                                   f"{page_label(top.page)} is the more detailed sheet, so it was "
                                   f"selected")
                sm.notes.append(f"same code on {pages_label(pages)}; resolved to the detail sheet")
            else:
                why = (f" on {pages_label(pages)}, none clearly more detailed"
                       if len(pages) > 1 else "")
                sm.notes.append(
                    f"ambiguous: {len(cands)} candidates within "
                    f"{st.ambiguity_margin:.0%} confidence{why}")
                sm.best.confidence = min(sm.best.confidence, 0.70)
        elif len(pages) > 1:
            sm.notes.append(f"the same name/code appears on {pages_label(pages)}")

        if placeholder:
            sm.best.confidence = min(sm.best.confidence, 0.75)

        sm.confirmed = sm.best.confidence >= st.auto_confirm_threshold
        if not sm.confirmed:
            needs_review.append(sm)
        matches.append(sm)

    unmatched_drawing = [ds for ds in drawing_spaces if id(ds) not in used_drawing]

    dup: dict[str, int] = {}
    for ds in drawing_spaces:
        k = normalise_code(ds.space_code) or normalise_name(ds.name, st.synonyms)
        if k:
            dup[k] = dup.get(k, 0) + 1
    duplicate_names = {k: v for k, v in dup.items() if v > 1}

    multi_level: dict[str, list[int]] = {}
    seen_pages: dict[str, set[int]] = {}
    for ds in drawing_spaces:
        k = normalise_code(ds.space_code) or normalise_name(ds.name, st.synonyms)
        if k:
            seen_pages.setdefault(k, set()).add(ds.page)
    for k, pages in seen_pages.items():
        if len(pages) > 1:
            multi_level[k] = sorted(pages)

    # Rank what a human still has to look at by the demand riding on it, so the
    # 110-port photographer position is at the top and the 1-port store is not.
    def by_demand(items: list[SpaceMatch]) -> list[SpaceMatch]:
        return sorted(items, key=lambda m: -demand_by_key.get(m.teap_key, 0.0))

    return MatchReport(
        matches=matches, unmatched_teap=by_demand(unmatched),
        unmatched_drawing=unmatched_drawing,
        duplicate_names=duplicate_names, multi_level=multi_level,
        needs_review=by_demand(needs_review), placeholders=by_demand(placeholders),
    )
