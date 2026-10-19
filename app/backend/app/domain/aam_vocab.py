"""The accommodation-matrix (AAM) space vocabulary — what a room-name label may be called (2.14.0).

A venue design book names its rooms after the event's *Accommodation Area
Matrix* (AAM): a functional-area code, a full code and a space name —
``ACR / ACR.001 / Venue Accreditation Office (VAO)``, ``BRS / BRS.052.02-001
/ Broadcast Mixed Zone``. The extractor reads a room from its code first
(``pdf_ingest.SPACE_CODE_RX``); a sheet that prints no code is read from the
room-name labels instead, and that fallback used to take *every* short text
on the sheet as a room. On a containment book that meant "CABLE GOES UNDER
BRIDGE", "L145m (476ft)", "STRM SEWR" and a thousand other labels arriving as
spaces — Marcelo, 29 Sep 2026: *"está mostrando muito lixo nas páginas …
coisas que nada têm a ver com nomes de espaços."*

So a name-only label is a space only when it is *similar to a known space
name*: one of the AAM names bundled in ``aam_names.txt`` (read from the two
AAM sheets he supplied, CSQ and RIV), or one of the names the project's own
TEAP carries — the TEAP is the document that rules, and a name it prints is
a room by definition. Similarity is ``token_sort_ratio`` at 80 or better
after normalisation, or a whole known name contained in the label (the
label "L9m (31ft) Venue Media Centre (VMC)" carries a length tag before the
room's name). Measured on his OWC book: 1,111 name-only labels,
167 kept, all of them rooms; what went was the cable notes, the length tags,
the pathway legend, the drawing index and the survey abbreviations.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from rapidfuzz import fuzz

#: A label this similar (0–100, ``token_sort_ratio``) to a known space name
#: is a space.
SIMILARITY_THRESHOLD = 80
#: A known name at least this long, contained whole in the label, makes the
#: label a space whatever the rest of it says.
CONTAINED_MIN_LEN = 12

#: "L9m (31ft)", "L145m (476ft)" — the cable-length tag a containment sheet
#: prints before (or as) a label.
LENGTH_TAG_RX = re.compile(r"\bL\s*\d+(?:[.,]\d+)?\s*m\s*\(\s*\d+(?:[.,]\d+)?\s*ft\s*\)", re.IGNORECASE)

#: The list is a client's material, not the author's: it lives in
#: ``app/reference_private`` (4.3.0), which a public package leaves out.
#: Without it the project's TEAP names alone make the vocabulary.
from .reference_data import private_file

_NAMES_FILE = private_file("aam_names.txt")


def normalise(text: str) -> str:
    """Lower case, no length tag, no parenthesised part, letters and digits only."""
    t = LENGTH_TAG_RX.sub(" ", text or "")
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=1)
def aam_names() -> tuple[tuple[str, str], ...]:
    """``(functional area, space name)`` per line of the bundled list."""
    out: list[tuple[str, str]] = []
    if not _NAMES_FILE.exists():
        return ()
    for line in _NAMES_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or "\t" not in line:
            continue
        fa, name = line.split("\t", 1)
        out.append((fa.strip(), name.strip()))
    return tuple(out)


@lru_cache(maxsize=1)
def _aam_normalised() -> tuple[str, ...]:
    return tuple(sorted({normalise(n) for _fa, n in aam_names() if normalise(n)}))


class SpaceVocabulary:
    """The known space names of one extraction: the AAM list plus the names
    the project's TEAP carries."""

    def __init__(self, extra: Iterable[str] = ()):
        seen = set(_aam_normalised())
        self.names: list[str] = list(_aam_normalised())
        for n in extra:
            k = normalise(n)
            if k and len(k) >= 4 and k not in seen:
                seen.add(k)
                self.names.append(k)

    def match(self, label: str) -> Optional[tuple[int, str]]:
        """``(score, known name)`` when ``label`` reads as a space name, else None."""
        q = normalise(label)
        if len(q) < 4:
            return None
        best: Optional[tuple[int, str]] = None
        for v in self.names:
            s = int(fuzz.token_sort_ratio(q, v))
            if (len(v) >= CONTAINED_MIN_LEN and len(q) > len(v)
                    and fuzz.partial_ratio(v, q) == 100):
                s = 100
            if best is None or s > best[0]:
                best = (s, v)
                if s == 100:
                    break
        if best is None or best[0] < SIMILARITY_THRESHOLD:
            return None
        return best

    def is_space_name(self, label: str) -> bool:
        return self.match(label) is not None


def strip_length_tag(name: str) -> str:
    """The room's name without the cable-length tag a containment sheet
    prints in front of it: "L9m (31ft) Venue Media Centre (VMC)" → "Venue
    Media Centre (VMC)"."""
    return re.sub(r"\s+", " ", LENGTH_TAG_RX.sub(" ", name or "")).strip(" -–—·")
