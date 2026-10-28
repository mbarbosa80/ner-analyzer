"""TEAP (Technology Equipment Allocation Plan) import.

The workbook is treated as untrusted input:

* macros are never executed — ``openpyxl`` is opened with ``keep_vba=False`` and
  formulas are read as cached values only;
* every sheet is inspected, because the header row is frequently not row 1;
* the column mapping is proposed automatically, shown to the user, and saved so
  the next import of the same template is one click.

Calibrated against ``TEAP v2.0.xlsx``: 15 sheets, main allocation sheet with
its header on row 2 and 17,496 data rows across 96 venues.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

import openpyxl

# ---------------------------------------------------------------------------
# Canonical fields
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: dict[str, list[str]] = {
    # field                     candidate header substrings (lower-case)
    "venue_code":              ["venue code", "venue cd", "venuecode"],
    "venue_name":              ["venue name", "venue", "project", "site"],
    "building":                ["building", "bldg", "block"],
    "level":                   ["level", "floor", "storey", "story", "andar", "nivel"],
    "zone":                    ["zone", "cluster", "precinct"],
    "fa_code":                 ["fa code", "fa/user code", "functional area code"],
    "functional_area":         ["fa name", "functional area", "user group"],
    "space_code":              ["space code", "room code", "location code", "space id"],
    "space_name":              ["space name", "location name", "room name", "location", "space"],
    "product_code":            ["product code", "equipment code", "item code", "sku"],
    "product_description":     ["product description", "product name", "equipment", "description"],
    "product_category":        ["primary product category", "product category", "service type"],
    # "updated qty" first, and on purpose. TEAP v2.3 (Sep 2026) carries three
    # quantity columns — ``TEAP v2.0``, ``NEW QTY`` and ``Updated QTY`` — and its
    # README says which one counts: "column O - Updated Quantity should be used
    # for estimated planning. Column M and N are feeding data for Column O and
    # should be ignored". The longest candidate wins, so without this entry the
    # bare "qty" matched ``NEW QTY`` (it comes first on the sheet) and every
    # line whose quantity had not changed since v2.0 was read as zero.
    "quantity":                ["updated quantity", "updated qty", "final qty", "qty total",
                                "quantity", "qty", "new req qty"],
    "network_ports":           ["network ports", "network port", "data ports", "ports", "rj45"],
    "wireless_required":       ["wireless", "wifi", "access point", "ap required"],
    # Criticality arrives in one of two shapes. Some TEAPs carry a single column
    # holding a word; the event's sheets instead carry a *pair* of columns, each
    # ticked with an X — see ``detect_criticality_columns`` for why that pair
    # cannot be resolved by substring matching alone.
    "criticality":             ["criticality", "priority", "tier"],
    "critical_flag":           [],   # resolved by detect_criticality_columns
    "non_critical_flag":       [],   # resolved by detect_criticality_columns
    "sport_code":              ["sport code", "sport", "discipline"],
    "comments":                ["comments", "comment", "notes", "remarks", "observ"],
    # Optional, and absent from every TEAP seen so far (the v2.0 sheet has
    # no such column). When a TEAP does name the room that serves a space, that
    # is the answer, and the engine treats it as a fixed choice — see
    # ``services.pin_map``. The candidates are deliberately specific: a bare
    # "ner" would claim the "Critical NER" / "Non-Critical NER" tick columns.
    "serving_ner":             ["serving ner", "ner name", "ner code", "served by",
                                "serving room", "assigned ner"],
}

REQUIRED_FIELDS = ["space_name"]

#: Cell values that mean "ticked" in a flag column. A TEAP marks these columns
#: with an X; the rest are accepted because different authors reach for
#: different marks and none of them are ambiguous.
TICKED = {"x", "xx", "yes", "y", "sim", "s", "true", "t", "1", "✓", "✔", "•"}

#: Values that explicitly mean "not ticked" rather than "unknown". Excel formula
#: residue (#N/A, #REF!) is *not* in here on purpose: it means the source could
#: not answer, which is different from answering no.
BLANK = {"", "-", "–", "—", "n/a", "na", "none", "no", "0", "false", "f", "não", "nao"}


def is_ticked(value: Any) -> Optional[bool]:
    """Is this flag cell ticked?

    ``None`` when the cell says nothing either way — blank is a real answer
    ("not this one"), but ``#N/A`` is the sheet failing to answer, and those two
    must not be collapsed. A space whose criticality could not be read has to
    reach the reviewer as unknown, not as non-critical.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("#"):          # #N/A, #REF!, #VALUE! — a failed lookup
        return None
    if text in TICKED:
        return True
    if text in BLANK:
        return False
    return None


def _fold(text: str) -> str:
    """Lower-case and strip accents, so a Portuguese header matches too.

    Without this, "NÃO CRÍTICA" fails: "crítica" does not contain "critica"
    once the accent is in the way, and the column is silently not found — which
    presents as criticality quietly not working, the exact failure this whole
    module exists to end.
    """
    decomposed = unicodedata.normalize("NFKD", str(text).strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def detect_criticality_columns(headers: Sequence[str]) -> dict[str, Optional[str]]:
    """Find the ``Critical NER`` / ``Non-Critical NER`` pair.

    This cannot be done with the substring matching the other fields use, and
    the reason is worth stating: **"critical ner" is a substring of
    "non-critical ner"**. A naive hint list maps both columns to the critical
    field, and every non-critical space silently becomes critical — which would
    be the worst possible direction for this particular error, because it
    inflates the critical count and drives NER upgrades that nobody needs.

    So the non-critical column is identified first, by its negation prefix, and
    the critical column is whatever else mentions criticality.
    """
    critical: Optional[str] = None
    non_critical: Optional[str] = None
    for h in headers:
        if not h:
            continue
        low = _fold(h)
        if "critical" not in low and "critica" not in low:
            continue
        negated = any(tok in low for tok in ("non-", "non ", "nao", "not "))
        if negated and non_critical is None:
            non_critical = h
        elif not negated and critical is None:
            critical = h
    return {"critical_flag": critical, "non_critical_flag": non_critical}



@dataclass
class SheetProfile:
    name: str
    header_row: int
    headers: list[str]
    data_rows: int
    score: float
    proposed_mapping: dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class TeapRow:
    row_number: int
    sheet: str
    values: dict[str, Any]

    def get(self, field_name: str, default: Any = None) -> Any:
        v = self.values.get(field_name, default)
        return default if v is None or (isinstance(v, str) and not v.strip()) else v


@dataclass
class TeapImport:
    source: str
    sheet: str
    mapping: dict[str, Optional[str]]
    rows: list[TeapRow]
    warnings: list[str] = field(default_factory=list)
    product_ports: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Header discovery
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _score_header_row(cells: list[Any]) -> tuple[float, dict[str, str]]:
    """How well a candidate header row maps onto the canonical fields."""
    labels = [_norm(c) for c in cells]
    mapping: dict[str, str] = {}
    used: set[int] = set()
    for field_name, candidates in CANONICAL_FIELDS.items():
        best_idx, best_len = None, -1
        for idx, lab in enumerate(labels):
            if not lab or idx in used:
                continue
            for cand in candidates:
                if lab == cand or (cand in lab and len(cand) > best_len):
                    if len(cand) > best_len:
                        best_idx, best_len = idx, len(cand)
        if best_idx is not None:
            used.add(best_idx)
            mapping[field_name] = cells[best_idx]
    # The criticality pair is resolved separately — substring matching cannot
    # separate "Critical NER" from "Non-Critical NER". See the function.
    pair = detect_criticality_columns([c if c is None else str(c) for c in cells])
    for field_name, header in pair.items():
        if header:
            mapping[field_name] = header

    filled = sum(1 for lab in labels if lab)
    return (len(mapping) + 0.01 * filled), mapping


def profile_workbook(path: str, *, probe_rows: int = 8,
                     max_sheets: int = 40) -> list[SheetProfile]:
    """Inspect every sheet and propose a header row plus a column mapping."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_vba=False)
    profiles: list[SheetProfile] = []
    try:
        for name in wb.sheetnames[:max_sheets]:
            ws = wb[name]
            best: Optional[SheetProfile] = None
            rows = list(ws.iter_rows(min_row=1, max_row=probe_rows, values_only=True))
            for r_idx, cells in enumerate(rows, start=1):
                cells = list(cells or [])
                if not any(c is not None and str(c).strip() for c in cells):
                    continue
                score, mapping = _score_header_row(cells)
                if best is None or score > best.score:
                    best = SheetProfile(
                        name=name, header_row=r_idx,
                        headers=[str(c).strip() if c is not None else "" for c in cells],
                        data_rows=max(0, (ws.max_row or 0) - r_idx),
                        score=score,
                        proposed_mapping={k: v for k, v in mapping.items()},
                    )
            if best:
                profiles.append(best)
    finally:
        wb.close()
    profiles.sort(key=lambda p: (p.score, p.data_rows), reverse=True)
    return profiles


def load_product_catalogue(path: str, *, sheet_hint: str = "Products") -> dict[str, float]:
    """Per-unit network port counts keyed by product code.

    Returns an empty dict when the workbook has no catalogue sheet.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_vba=False)
    try:
        target = next((s for s in wb.sheetnames if _norm(sheet_hint) in _norm(s)), None)
        if target is None:
            return {}
        ws = wb[target]
        rows = list(ws.iter_rows(min_row=1, max_row=6, values_only=True))
        header_row, code_idx, ports_idx = None, None, None
        for r_idx, cells in enumerate(rows, start=1):
            labels = [_norm(c) for c in (cells or [])]
            if "product code" in labels and any("network port" in l for l in labels):
                header_row = r_idx
                code_idx = labels.index("product code")
                ports_idx = next(i for i, l in enumerate(labels) if "network port" in l)
                break
        if header_row is None:
            return {}
        out: dict[str, float] = {}
        for cells in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if not cells or code_idx >= len(cells):
                continue
            code = cells[code_idx]
            ports = cells[ports_idx] if ports_idx < len(cells) else None
            if code and isinstance(ports, (int, float)):
                out[str(code).strip()] = float(ports)
        return out
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_sheet(path: str, sheet: str, header_row: int,
               mapping: dict[str, Optional[str]],
               *, venue_filter: Optional[str] = None,
               limit: Optional[int] = None) -> TeapImport:
    """Read one sheet using an explicit, user-confirmed column mapping."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_vba=False)
    warnings: list[str] = []
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(f"sheet {sheet!r} not present in the workbook")
        ws = wb[sheet]
        header_cells = next(ws.iter_rows(min_row=header_row, max_row=header_row,
                                         values_only=True))
        headers = [str(c).strip() if c is not None else "" for c in header_cells]
        index_of = {h: i for i, h in enumerate(headers) if h}

        col_index: dict[str, int] = {}
        for field_name, header in mapping.items():
            if header and header in index_of:
                col_index[field_name] = index_of[header]
            elif header:
                warnings.append(f"mapped column {header!r} for '{field_name}' not found in the sheet")

        missing = [f for f in REQUIRED_FIELDS if f not in col_index]
        if missing:
            raise ValueError(f"required field(s) not mapped: {', '.join(missing)}")

        rows: list[TeapRow] = []
        vf = _norm(venue_filter) if venue_filter else None
        for n, cells in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True),
                                  start=header_row + 1):
            if cells is None or not any(c is not None and str(c).strip() for c in cells):
                continue
            values = {f: (cells[i] if i < len(cells) else None) for f, i in col_index.items()}
            if vf and _norm(values.get("venue_code")) != vf and _norm(values.get("venue_name")) != vf:
                continue
            rows.append(TeapRow(row_number=n, sheet=sheet, values=values))
            if limit and len(rows) >= limit:
                warnings.append(f"import truncated at {limit} rows")
                break

        return TeapImport(source=path, sheet=sheet, mapping=dict(mapping),
                          rows=rows, warnings=warnings)
    finally:
        wb.close()


def read_csv(path: str, mapping: dict[str, Optional[str]],
             *, encoding: str = "utf-8-sig") -> TeapImport:
    with open(path, "r", encoding=encoding, newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        rows = [
            TeapRow(row_number=i, sheet="csv",
                    values={f: raw.get(h) for f, h in mapping.items() if h})
            for i, raw in enumerate(reader, start=2)
        ]
    return TeapImport(source=path, sheet="csv", mapping=dict(mapping), rows=rows)


def profile_csv(path: str, *, encoding: str = "utf-8-sig") -> SheetProfile:
    with open(path, "r", encoding=encoding, newline="") as fh:
        first = fh.readline()
    headers = next(csv.reader(io.StringIO(first)))
    score, mapping = _score_header_row(headers)
    return SheetProfile(name="csv", header_row=1, headers=headers, data_rows=-1,
                        score=score, proposed_mapping=mapping)


def list_venues(imp: TeapImport) -> list[tuple[str, str, int]]:
    """(venue_code, venue_name, row_count) present in an import."""
    counts: dict[tuple[str, str], int] = {}
    for r in imp.rows:
        key = (str(r.get("venue_code", "") or ""), str(r.get("venue_name", "") or ""))
        counts[key] = counts.get(key, 0) + 1
    return sorted(((c, n, k) for (c, n), k in counts.items()), key=lambda t: -t[2])


def preview_venues(path: str, sheet: str, header_row: int,
                   mapping: dict[str, Optional[str]],
                   *, max_venues: int = 400) -> list[dict]:
    """Stream just the venue columns and count rows per venue.

    A master allocation plan covers every venue in the programme — the reference
    workbook carries 96 of them across 17,496 rows. Importing all of it against
    one venue's drawings is never what anyone wants, so the UI shows this list and
    the importer refuses an unfiltered multi-venue import. Reading two columns is
    fast enough to run before the user commits to anything.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_vba=False)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(f"sheet {sheet!r} not present in the workbook")
        ws = wb[sheet]
        header_cells = next(ws.iter_rows(min_row=header_row, max_row=header_row,
                                         values_only=True))
        headers = [str(c).strip() if c is not None else "" for c in header_cells]
        index_of = {h: i for i, h in enumerate(headers) if h}

        code_i = index_of.get(mapping.get("venue_code") or "")
        name_i = index_of.get(mapping.get("venue_name") or "")
        if code_i is None and name_i is None:
            return []

        counts: dict[tuple[str, str], int] = {}
        for cells in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if not cells:
                continue
            code = str(cells[code_i]).strip() if code_i is not None and code_i < len(cells) \
                and cells[code_i] is not None else ""
            name = str(cells[name_i]).strip() if name_i is not None and name_i < len(cells) \
                and cells[name_i] is not None else ""
            if not code and not name:
                continue
            counts[(code, name)] = counts.get((code, name), 0) + 1

        out = [{"venue_code": c, "venue_name": n, "rows": k}
               for (c, n), k in counts.items()]
        out.sort(key=lambda d: -d["rows"])
        return out[:max_venues]
    finally:
        wb.close()
