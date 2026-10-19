"""Deciding whether two things on the drawings are the same physical NER.

The problem this solves
-----------------------
A venue design book draws the same equipment room many times: once on the level
key plan, again on a zone detail, again on a services overlay. V1 recorded one
element per marker, so ``Critical NER 3`` on pages 5, 12 and 27 looked like three
rooms. Coverage then had three NERs where the building has one, and every number
downstream — port load, redundancy, "areas without a NER" — inherited the error.

The rule this module follows
----------------------------
Merge on proof, ask on suspicion, never assume. Concretely:

* An **identical normalised label** is necessary but not sufficient. Real venues
  do reuse a numbering series across buildings.
* Agreement on **level and building** is what turns a matching label into proof.
  Where the page metadata does not state a level, the score is capped below the
  automatic threshold — an unknown is not an agreement.
* A **conflict** on level or building is disqualifying no matter how well the
  labels match.
* Everything between "proof" and "no relation" becomes a question with its
  evidence attached, because a score with no sentences behind it is not something
  an engineer can review.

Every comparison returns the evidence *and* the differences. The screen shows
both. A reviewer who only ever sees the reasons to merge will merge.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .sheetnames import page_label

#: score at or above which the tool links without asking
AUTO_MERGE_THRESHOLD = 0.97
#: score below which two things are not even worth showing as a question
CANDIDATE_FLOOR = 0.55


def normalise_label(label: str) -> str:
    """``Critical NER 3`` / ``CRITICAL-NER-03`` / ``critical  ner 3`` → one form.

    Numeric tokens are stripped of leading zeros because real sheets tag the same
    room as both ``NER 03`` and ``NER 3``.
    """
    if not label:
        return ""
    s = unicodedata.normalize("NFKD", str(label))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    tokens: list[str] = []
    buf: list[str] = []
    for ch in s:
        if ch.isalnum():
            buf.append(ch)
        elif buf:
            tokens.append("".join(buf))
            buf = []
    if buf:
        tokens.append("".join(buf))
    return " ".join(str(int(t)) if t.isdigit() else t for t in tokens)


def label_series(label: str) -> tuple[str, Optional[int]]:
    """Split ``critical ner 3`` into its series (``critical ner``) and index (3)."""
    n = normalise_label(label)
    if not n:
        return "", None
    parts = n.split()
    if parts and parts[-1].isdigit():
        return " ".join(parts[:-1]), int(parts[-1])
    return n, None


@dataclass
class Candidate:
    """Everything the comparison is allowed to look at.

    Deliberately a flat value object rather than an ORM row so the same scoring
    runs over V1 elements during migration, over canonical assets in the review
    queue, and over TVDB detections later, without three copies of the rule.
    """

    ref: object
    label: str
    kind: str = ""
    page: Optional[int] = None
    level: Optional[str] = None
    building: Optional[str] = None
    document_id: Optional[int] = None
    space_code: Optional[str] = None
    space_name: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    nearby_text: str = ""
    confirmed_separate_from: frozenset = field(default_factory=frozenset)


@dataclass
class Comparison:
    score: float
    evidence: list[str]
    differences: list[str]
    blocking: Optional[str] = None

    @property
    def auto_mergeable(self) -> bool:
        return self.blocking is None and self.score >= AUTO_MERGE_THRESHOLD

    @property
    def is_candidate(self) -> bool:
        return self.blocking is None and self.score >= CANDIDATE_FLOOR

    def to_dict(self) -> dict:
        return {"score": round(self.score, 3), "evidence": self.evidence,
                "differences": self.differences, "blocking": self.blocking,
                "auto_mergeable": self.auto_mergeable}


def _norm(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s or None


def compare(a: Candidate, b: Candidate) -> Comparison:
    """Score whether ``a`` and ``b`` are the same physical room."""
    evidence: list[str] = []
    differences: list[str] = []

    if b.ref in a.confirmed_separate_from or a.ref in b.confirmed_separate_from:
        return Comparison(0.0, [], ["a reviewer has already declared these different NERs"],
                          blocking="declared_separate")

    la, lb = normalise_label(a.label), normalise_label(b.label)
    if not la or not lb:
        return Comparison(0.0, [], ["one of the markers carries no label"],
                          blocking="no_label")

    series_a, idx_a = label_series(a.label)
    series_b, idx_b = label_series(b.label)

    if la == lb:
        evidence.append(f"identical normalised label “{la}”")
        score = 0.90
    elif series_a and series_a == series_b and idx_a is not None and idx_b is not None:
        # Same series, different number: NER 4 and NER 5 are two rooms, not one.
        return Comparison(
            0.0, [f"same label series “{series_a}”"],
            [f"different index in the series: {idx_a} vs {idx_b}"],
            blocking="different_index")
    else:
        return Comparison(0.0, [], [f"labels differ: “{a.label}” vs “{b.label}”"],
                          blocking="different_label")

    # --- level and building: what turns a matching label into proof ----------
    lvl_a, lvl_b = _norm(a.level), _norm(b.level)
    bld_a, bld_b = _norm(a.building), _norm(b.building)

    if bld_a and bld_b and bld_a != bld_b:
        return Comparison(0.0, evidence,
                          [f"different buildings: {a.building} vs {b.building}"],
                          blocking="different_building")
    if lvl_a and lvl_b and lvl_a != lvl_b:
        return Comparison(0.0, evidence,
                          [f"different levels: {a.level} vs {b.level}"],
                          blocking="different_level")

    if lvl_a and lvl_b:
        evidence.append(f"both on level {a.level}")
        score += 0.05
    else:
        differences.append("level not stated on at least one page — agreement unproven")
    if bld_a and bld_b:
        evidence.append(f"both in building {a.building}")
        score += 0.02

    # --- supporting signals --------------------------------------------------
    ca, cb = _norm(a.space_code), _norm(b.space_code)
    if ca and cb:
        if ca == cb:
            evidence.append(f"same space code {a.space_code}")
            score += 0.04
        else:
            differences.append(f"space codes differ: {a.space_code} vs {b.space_code}")
            score -= 0.20

    if a.kind and b.kind:
        if a.kind == b.kind:
            evidence.append(f"same marker kind ({a.kind})")
            score += 0.02
        else:
            differences.append(f"marker kind differs: {a.kind} vs {b.kind}")
            score -= 0.15

    if a.page is not None and b.page is not None:
        if a.page == b.page:
            evidence.append(f"both tagged on {page_label(a.page)}")
            if None not in (a.x, a.y, b.x, b.y):
                d = math.hypot(a.x - b.x, a.y - b.y)
                if d < 1.0:
                    evidence.append("markers sit on top of each other (duplicate tag)")
                    score += 0.03
                else:
                    differences.append(
                        f"{d:.0f} drawing units apart on the same page — could be two rooms")
                    score -= 0.10
        else:
            evidence.append(f"appears on {page_label(a.page)} and {page_label(b.page)}")

    if a.document_id is not None and b.document_id is not None:
        if a.document_id == b.document_id:
            evidence.append("same source document")
        else:
            differences.append("different source documents")

    na, nb = _norm(a.space_name), _norm(b.space_name)
    if na and nb and na == nb:
        evidence.append(f"same room name “{a.space_name}”")
        score += 0.03

    if not (lvl_a and lvl_b):
        # An unknown is never an agreement. Hold below the automatic threshold so
        # the pair is asked about instead of assumed.
        score = min(score, AUTO_MERGE_THRESHOLD - 0.01)

    return Comparison(max(0.0, min(1.0, score)), evidence, differences)


def group_candidates(items: Sequence[Candidate]) -> list[tuple[Candidate, Candidate, Comparison]]:
    """Every pair worth showing a human, strongest first.

    Only pairs sharing a normalised label are compared, so this is linear in the
    number of NERs rather than quadratic — which matters on a venue with 26 rooms
    drawn across 34 pages, and much more on a games-wide project.
    """
    buckets: dict[str, list[Candidate]] = {}
    for c in items:
        key = normalise_label(c.label)
        if key:
            buckets.setdefault(key, []).append(c)

    out: list[tuple[Candidate, Candidate, Comparison]] = []
    for bucket in buckets.values():
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                cmp_ = compare(bucket[i], bucket[j])
                if cmp_.is_candidate:
                    out.append((bucket[i], bucket[j], cmp_))
    out.sort(key=lambda t: -t[2].score)
    return out
