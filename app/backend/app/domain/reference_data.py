"""Reference material that is not the author's (4.3.0).

A client's own documents — the space names of an accommodation matrix, a
naming structure for network rooms — are read from ``app/reference_private/``
when that folder holds them. The folder is ignored by git and left out of a
public package: the published source carries the application, not anybody's
event documents. Everything that reads from here works without it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PRIVATE_DIR = Path(__file__).resolve().parents[1] / "reference_private"


def private_file(name: str) -> Path:
    """Where a private reference file lives (it may not exist)."""
    return PRIVATE_DIR / name


def naming_reference() -> Optional[dict]:
    """The naming table for the side panel, or ``None`` when none is bundled.

    Shape: ``{"title", "intro", "principles": [...], "groups": [{"heading",
    "rows": [[name, where], ...]}], "source", "pt": {english: portuguese}}``.
    A file that cannot be read is treated as absent — a reference panel is
    never a reason for a screen to fail.
    """
    p = private_file("naming_reference.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
