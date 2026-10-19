"""The two languages, and the one thing that can silently break them.

The interface is translated with a table keyed by the **English string itself**
(see ``frontend/src/lib/i18n.ts`` for why). That buys a great deal of
simplicity and costs exactly one thing: if the English text changes, its
translation is stranded — the key no longer matches anything, and the screen
quietly reverts to English with nobody the wiser.

For interface copy that is survivable; the string is right there in the same
file as the change. For **server messages** it is not, because the English
lives in Python and the Portuguese lives in TypeScript, and nothing in either
language's tooling connects them. So that link is asserted here.

This file also guards the other half of the decision: the exports are **not**
translated. One register workbook has one shape regardless of who exported it,
because the person opening it on the other end may not be the person who
exported it, and a column header that changes language is a column header that
breaks every downstream sheet and script that reads it.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app"
DICT = ROOT / "frontend" / "src" / "lib" / "strings.pt.ts"

# A message is "from the server" if it appears as a raised error. Anything else
# in the dictionary is interface copy and lives entirely in the frontend.
RAISE = re.compile(
    r"(?:HTTPException\(\s*\d+\s*,\s*|AuthError\(\s*|InsufficientMemory\(\s*"
    r"|ValidationError\(\s*)"
    r"((?:\"[^\"]*\"|'[^']*')(?:\s*(?:\"[^\"]*\"|'[^']*'))*)"
)
#: A message kept in a module-level constant so it can be raised from one place
#: and imported by a test — ``NO_SPACE_RECOGNISED = ("…" "…")`` in services.
CONSTANT = re.compile(
    r"^[A-Z][A-Z0-9_]+\s*=\s*\(\s*((?:\"[^\"]*\"\s*)+)\)", re.M)


def _server_messages() -> set[str]:
    out: set[str] = set()
    for path in sorted(BACKEND.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in list(RAISE.finditer(src)) + list(CONSTANT.finditer(src)):
            parts = re.findall(r"\"([^\"]*)\"|'([^']*)'", m.group(1))
            text = "".join(a or b for a, b in parts)
            if len(text) > 4:
                out.add(text)
    return out


def _dictionary_keys() -> set[str]:
    """Every key in the PT table, including the ones split across lines."""
    src = DICT.read_text(encoding="utf-8")
    # Keys are quoted string literals in the key position: `  "text":`
    return set(re.findall(r'^\s{2}"((?:[^"\\]|\\.)*)":', src, flags=re.M))


def test_the_dictionary_parses_at_all():
    keys = _dictionary_keys()
    assert len(keys) > 200, "the PT table looks truncated — did an edit break it?"


def test_every_translated_server_message_still_exists_on_the_server():
    """The one link no compiler checks.

    A translation whose English no longer appears in the backend is dead: the
    server will never produce that string again, so the entry can never match.
    Rather than leave it to be noticed on screen, fail here and name it.
    """
    server = _server_messages()
    keys = _dictionary_keys()

    # Lower-case first word is the house style for API messages and is what
    # separates them from interface copy ("Save rules", "Coverage").
    looks_like_a_server_message = {
        k for k in keys
        if k[:1].islower() and " " in k and not k.startswith(("e.g.", "or ", "runs "))
    }
    stranded = sorted(
        k for k in looks_like_a_server_message
        if k not in server and k not in _INTERFACE_LOWER_CASE
    )
    assert not stranded, (
        "these PT entries look like server messages but no longer match any "
        "message the backend raises — the English was edited on one side only:\n  "
        + "\n  ".join(stranded)
    )


# Interface copy that happens to start lower case. Listed explicitly so the
# test above stays strict about everything else.
_INTERFACE_LOWER_CASE = {
    # 4.2.0
    "change(s) after the last run", "changed since the last run",
    "is already the name of another NER", "the analysis was run again first:",
    # 4.0.0 — access points are positions, never ports; placing never duplicates
    "Wi-Fi point placed for",
    "Wi-Fi point placed — no matched room within the limit on this sheet, so it belongs to no TEAP space and counts no port. Tie it to a space in the Inspector if it belongs to one.",
    "Wi-Fi point(s) drawn by hand beyond one per space — kept, check them",
    "extra Wi-Fi point(s) taken back (one per space)",
    "cleared by you — not in the TEAP, no port",
    "no matched room within the limit on this sheet — not in the TEAP, no port",
    "space(s) already had their Wi-Fi point",
    "space(s) request wireless but have no room on the drawing — left pending",
    "the TEAP space this point was placed for — it stays tied wherever you drag it; change or clear it here if it serves another space",
    "room not confirmed", "served — room not confirmed",   # 3.0.0, Demand per space
    # 2.19.0 — access points from the TEAP
    "Wi-Fi point(s) placed in",
    "from the TEAP",
    "placed from the TEAP",
    "space(s) already had a tied point",
    "space(s) request wireless but have no room on the drawing yet",
    "space(s) sit on a key plan",
    "the TEAP space this point was placed for — it stands in for that space's wireless port wherever you drag it; change or clear it here if it serves another space",
    # 2.18.1 — deleting a NER deletes it everywhere
    "and in the NERs list.",
    "pages. Delete removes it from all of them.",
    "removed — it leaves every page, the NERs list and the analysis. Restore on the NERs screen brings it back.",
    "removed — it leaves every page, the analysis and the export; Restore brings it back",
    "row(s) of the same name",
    # 2.14.0 — key-plan ticks on Scale, the NER placing step
    "already had a NER beside them",
    "detail page(s) have no confirmed scale — a NER near an existing one is told apart at 12 m, which needs the scale",
    "detail page(s) with no confirmed scale", "from the team's annotations", "key plan(s)",
    "last placed", "page(s) changed", "space(s) read off the pages that are detail sheets again",
    "space(s) taken off the key plans", "you have key-plan ticks not applied yet",
    # 2.13.0 — key plans, NERs read off the room labels
    "from the room label",
    # 2.12.0 — three tiles, Exceptions from the Demand rows, viewer search, NER name check
    "all that need you",
    "created on page",
    "drawn on this page as the same NER — one room in the register, counted once.",
    "matched + no room found = TEAP spaces. Matched counts every line with a room, whether the matcher or you tied it; no room found counts every line without one, whether the matcher found none or you chose — none —. Each row says who decided.",
    "matched line(s) still await your Confirm.",
    "more — type more of the name",
    "named area",
    "near the limit (counted as served)",
    "no other NER on this page",
    "no page",
    "not measured",
    "nothing on the drawing has this name",
    "room on the drawing",
    "search a name…",
    "search code, name, room or NER",
    "wireless point",

    # 2.11.0 — the NER of a wireless point.
    "the NER of its TEAP space",
    "as its TEAP space",
    "assigned. Re-run the analysis to see the effect.",
    "released. Re-run the analysis to see the effect.",
    # 2.10.0 — "none" that sticks, the other-page line, the counter filter, the
    # NER naming card.
    "counted on that room from the other page: its ports count against it, and the distance is reported as not measured until a shaft or riser is registered. Re-run the analysis.",
    "counted on this NER, distance not measured",
    "filtered by a counter below",
    "other page",
    "the critical room nearest a TER marker",
    "you said this space is not on this drawing — kept when the matching re-runs; Undo takes it back",
    # 2.8.1 — the strings the test pass found untranslated (Import, Projects,
    # Account, the viewer's reference notice)
    "and everything in it?", "columns not in this sheet, left as they were",
    "deleted with", "earlier decision(s) carried across", "import every venue",
    "only the owner can delete this project", "page(s) need OCR", "project venue",
    "project(s)", "rows imported into",
    "rows will be imported. Only do this if the project really does cover every venue.",
    "sheet(s). Check the mapping, then load the venue list.",
    "reference placed on this sheet — drawn only, no reach circles; nothing is counted. Click again to place another, choose select to stop.",
    # 2.8.0 — named areas and the viewer's inspector
    "corner(s) — double-click or Enter to close, Esc to drop",
    "click the first corner of the area",
    "area drawn — illustrative only, nothing is counted from it. Click to start another, choose select to stop.",
    "the area", "ports assigned", "wireless point(s)",
    # 2.5.0 — the wireless tie, in the viewer's Inspector and its notices
    "cleared by you — counted as one extra port",
    "nearest matched room on this sheet — proposed; change it if the point serves another space",
    "no matched room within the limit on this sheet — counted as one extra port",
    "tied by you",
    "wireless point placed — no matched room within the limit on this sheet, so it counts as one extra port. Tie it to a space in the Inspector if it belongs to one.",
    "wireless point placed — stands in for the wireless port the TEAP requests for",
    # 2.3.0 — the viewer's eraser
    "this route segment", "the shaft between pages", "pages",
    "locked — unlock it before deleting it",
    # 2.2.0 — Demand per space, TEAP × drawing and the viewer: the TEAP rules,
    # the same space on several pages, wireless points. All interface copy.
    "from it there", "measured on", "is", "undo",
    "no ports requested in the TEAP — not part of the study",
    "none within the limit", "not the same space", "not the same space (your answer)",
    "same code", "same code, same level", "same level by the drawing number",
    "level not read", "same name, no code",
    "same space on another page? — to confirm", "same space, confirmed by you",
    "show TEAP spaces with no ports", "wireless points",
    "accounts on this machine", "all statuses", "change your password",
    # Added by the September simplification pass — all three are on the drawing
    # viewer or the demand list, none of them come off the wire.
    "in the register — not drawn on the sheet", "not on the sheet",
    "rooms chosen by you",
    "criticality unconfirmed", "general (90 m)", "internal identifier — never changes",
    "item(s) sit outside their page — re-import the drawing",
    "drawn from the saved snapshot",
    "no snapshot saved — the live analysis will be used",
    "ports still awaiting a decision", "remembered for every venue",
    "earlier decision(s) kept",
    "decision(s) released — the room is no longer on the drawing",
    "confirmed by you", "on the drawing", "read from the drawing",
    "removal proposed", "suggested here — not drawn in the VDB",
    "chosen by you", "space(s) assigned by you.", "nearest:",
    "your choice — saved, and kept when the matching re-runs",
    "you said this space is not on this drawing",
    # the tracker-proposal screen
    "left alone (already decided)", "no position — it will be listed, not drawn",
    "placed on the drawing", "proposal(s) read", "proposals read",
    "rows with text", "without a position",
    # the proposed-NER layer in the drawing viewer
    "proposed — not drawn on the sheet",
    "accepted — not drawn on the sheet", "accepted — not on the sheet",
    "with legend",
    "proposed NER(s) have no position yet — the space they name is not on this "
    "drawing set. They are listed on the NER register.",
    "rooms available on this drawing.", "row(s)",
    "what the VDB says", "what you decided", "with no room chosen yet",
    "not analysed", "not covered", "not set", "nothing outstanding", "only me",
    "page(s) awaiting scale", "photographer (70 m)", "photographer areas",
    "rooms opened", "scale not confirmed", "shared with you · read only",
    "space code", "space name", "still uncovered", "unknown — never read as zero",
    "what makes you sure", "within limits", "worst distance (m)", "limits",
    "slack", "scale", "page", "venue",
    "all pages", "also on", "no position", "of",
    # the 3 Sep 2026 screen pass — Scale, the one NERs screen, the merged
    # Demand screen and the viewer inspector
    "and reassigns", "awaiting confirmation", "capacity unknown",
    "chosen on the NERs screen", "consolidated — reversible from the history",
    "consolidation undone", "criticality not stated",
    "deleted from the drawing", "drawn by you", "from the drawing",
    "from the tracker", "marker separated into its own NER",
    "moved on the drawing", "named in the TEAP — no doubt", "needs judgement",
    "neither changes when the name does.",
    "no NER with that name on the NERs screen", "no room found",
    "not confirmed", "not in the design", "only rows not confirmed yet",
    "over capacity", "page(s) at once?", "page(s) confirmed",
    "page(s) have no scale to confirm",
    "page(s) with no scale — type one in the row",
    "recorded as different rooms", "removed on the NERs screen",
    "removed — it leaves the drawing and the analysis; Restore brings it back",
    "rooms named by the TEAP", "served area(s)",
    "still need review", "straight line", "strong evidence", "the TEAP names",
    "match not confirmed", "route not validated",
    # the 10 Sep 2026 Demand-screen pass — from → to, the "other level" box,
    # the readable notes and the lines switch on Reports
    "tied by hand", "matched, confirmed", "matched, not confirmed", "same room",
    "tied to another room", "other level", "is on", "this space is on",
    "unticked: the room is not counted", "other level — not measured",
    "via vertical route", "open all", "fold all", "with NER → space lines",
    "matched, not yet confirmed",
    # 2.6.0 — the tiles are the filter; Undo takes a decision back
    "no room found — choose one by hand", "with no room found — choose one by hand",
    "exact code, confirmed by the matcher", "your decisions — kept on every re-run",
    "show every row", "back to the matcher's answer",
    # 2.6.1 — the server down or restarting, seen from the browser
    "the server is not answering — it is restarted automatically within about two minutes, and this page reconnects by itself",
    "server not answering — reconnecting", "the server is back",
    "not on this drawing (rejected by you)",
    "recorded as served from another level ('other level' ticked): its ports "
    "count against that room, and the distance is reported as not measured "
    "until a shaft or riser is registered. Re-run the analysis.",
    # the version pill in the top bar (2.0.0)
    "the application was updated — press Ctrl+Shift+R to load the current interface",
    # 2.7.0 — the four piles and their reasons (interface copy, mirrored from
    # ``distance.STATUS_LABEL``), the unplaced rule, the NER references, the
    # suggested names
    "within the limit", "near the limit", "out of limit", "insufficient capacity",
    "no NER reaches it", "no room on the drawing", "not analysed yet",
    "no room on the drawing — NER chosen by you", "all spaces",
    "no room on the drawing — counted on this NER, distance not measured",
    "no number for", "add it to the convention", "no suggestion yet",
    "reference placed on this sheet — drawn only, with its reach circles; nothing is counted. Click again to place another, choose select to stop.",
}


def test_the_common_refusals_are_translated():
    """The messages a person actually meets, as opposed to the diagnostics.

    Not every server message is translated, on purpose — the internal ones stay
    in English because they are what we quote to each other when something
    breaks. But the ones an ordinary user runs into on a normal day have to be
    covered, or the Portuguese screen is a half-translated screen.
    """
    keys = _dictionary_keys()
    must_cover = [
        "sign in to continue",
        "username or password is not right",
        "this account is disabled — ask an administrator",
        "this needs an administrator account",
        "project not found",
        "the current password is not right",
        "you cannot disable your own account",
        "this installation already has accounts — ask an administrator to create yours",
    ]
    missing = [m for m in must_cover if m not in keys]
    assert not missing, f"untranslated messages an ordinary user meets: {missing}"


# ---------------------------------------------------------------------------
# The exports are not translated
# ---------------------------------------------------------------------------

def test_the_export_columns_are_not_language_dependent():
    """One workbook shape, whoever exported it.

    The register goes to the VNI team and to people who did not run the
    analysis. If the column headers followed whoever clicked the button, the
    same report would arrive in two shapes and every sheet reading it would
    break on the second one.
    """
    from app.ner_register import CHANGE_COLUMNS, REGISTER_COLUMNS

    for columns in (REGISTER_COLUMNS, CHANGE_COLUMNS):
        for col in columns:
            header = col[1] if isinstance(col, (tuple, list)) else str(col)
            assert header.isascii(), (
                f"export header {header!r} is not ASCII — the exports are "
                "English by design; a translated header changes the file's "
                "shape depending on who exported it"
            )


def test_no_translation_machinery_reaches_the_backend():
    """The server has no opinion about language, and should keep it that way.

    Every string it produces is English. If a language ever needs to reach the
    server it will be a deliberate decision with its own test, not something
    that arrived by accident through a request header.
    """
    for path in sorted(BACKEND.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "accept-language" not in src.lower(), (
            f"{path.name} reads a language header — the backend is "
            "language-agnostic on purpose"
        )
