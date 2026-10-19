"""One name for one sheet, across every book of a project (4.1.0).

The database stores where a thing is drawn as ``(drawing_id, page)`` — page
numbers restart at 1 in every PDF, so a project with the 300, 400 and 600
series of a venue design book has three page 1s. Everything above the
database — the coverage engine, the screens, the API, the exports — used to
carry the page number alone, so page 2 of the 300 book (1:800) and page 2 of
the 400 book (1:400) were taken for the same sheet: rooms of one were drawn on
the other and distances were measured between two different coordinate
systems (ALA, 16 Oct 2026).

A **sheet key** is the one integer that names a sheet everywhere above the
database:

* a project with **one** book keeps its page numbers as they are — the key of
  page 6 is 6 — so nothing a single-book project shows, measures or exports
  changes;
* a project with **several** books gives each page ``drawing_id * STRIDE +
  page`` — page 6 of drawing 15 is 150006 — so no two sheets share a key, and
  a key read anywhere says which book it is in.

``0`` (and ``None``) keep their meaning: "no sheet" — a TEAP space with no room
on the drawing.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain.sheetnames import naming as _naming
from .models import Drawing, Page

#: The multiplier of a multi-book key. A design book has tens of pages, never
#: ten thousand; ``split`` refuses a page number past it.
STRIDE = 10000


class SheetError(ValueError):
    """A sheet key that names no sheet of the project."""


@dataclass(frozen=True)
class SheetInfo:
    key: int
    drawing_id: int
    page: int
    filename: str
    sheet_number: str
    title: str
    level: Optional[str]
    key_plan: bool


def _series(filename: str) -> str:
    """``ALA_400_XXX_OP.pdf`` → ``400``: the book's series, when its name says
    it; the file name without extension otherwise."""
    stem = re.sub(r"\.pdf$", "", filename or "", flags=re.IGNORECASE)
    m = re.search(r"(?:^|[_\-\s])(\d{3})(?:[_\-\s]|$)", stem)
    return m.group(1) if m else stem


class Sheets:
    """The sheets of one project and the keys that name them."""

    def __init__(self, drawings: list[tuple[int, str]], pages: list[Page]):
        self.drawing_ids = sorted(d for d, _ in drawings)
        self.filenames = dict(drawings)
        self.multi = len(self.drawing_ids) > 1
        self.only = self.drawing_ids[0] if len(self.drawing_ids) == 1 else None
        self.info: dict[int, SheetInfo] = {}
        for pg in pages:
            k = self.key(pg.drawing_id, pg.number)
            self.info[k] = SheetInfo(
                key=k, drawing_id=pg.drawing_id, page=pg.number,
                filename=self.filenames.get(pg.drawing_id, ""),
                sheet_number=(pg.sheet_number or "").strip(),
                title=(pg.sheet_title or "").strip(), level=pg.level,
                key_plan=bool(pg.key_plan))

    # -- keys -------------------------------------------------------------

    def key(self, drawing_id: Optional[int], page: Optional[int]) -> Optional[int]:
        """The key of page ``page`` of book ``drawing_id``."""
        if page is None:
            return None
        page = int(page)
        if page == 0 or not self.multi:
            return page
        if drawing_id is None:
            # A row written before the book was known (an old proposal).
            # In a multi-book project its page alone names no sheet; it is
            # taken to be in the first book, the only one it could have been
            # drawn on when the project had one.
            drawing_id = self.drawing_ids[0]
        if not 0 < page < STRIDE:
            raise SheetError(f"page {page} is out of range")
        return int(drawing_id) * STRIDE + page

    def of(self, row) -> Optional[int]:
        """The key of a row that carries ``drawing_id`` and ``page``."""
        return self.key(getattr(row, "drawing_id", None), getattr(row, "page", None))

    def of_asset(self, a) -> Optional[int]:
        """The key of a register room's canonical sheet."""
        return self.key(getattr(a, "canonical_drawing_id", None),
                        getattr(a, "canonical_page", None))

    def split(self, key: Optional[int]) -> tuple[Optional[int], Optional[int]]:
        """``(drawing_id, page)`` of a key. Refuses a key that names no book of
        the project — in a multi-book project a bare page number is one."""
        if key is None:
            return None, None
        key = int(key)
        if key == 0:
            return None, 0
        if not self.multi:
            # A page past the end of the only book (4.2.1): 4.2.0 refused it in
            # a multi-book project only, so in a one-book project a marker, a
            # NER or a shaft landed on a sheet that is not there.
            if key < 0 or (self.info and key not in self.info):
                name = self.filenames.get(self.only, "the drawing")
                raise SheetError(f"{name} has no page {key}")
            return self.only, key
        d, p = divmod(key, STRIDE)
        if d not in self.filenames or p <= 0:
            raise SheetError(
                f"sheet {key} is not a sheet of this project — with several books "
                f"a page number alone does not say which book it is in")
        if self.info and key not in self.info:
            # A page past the end of an existing book (4.2.0): it used to be
            # accepted, and a marker or a shaft landed on a sheet that is not there.
            raise SheetError(f"{self.filenames.get(d, 'that book')} has no page {p}")
        return d, p

    def keys(self) -> list[int]:
        """Every sheet, in book order then page order."""
        return sorted(self.info)

    # -- names ------------------------------------------------------------

    def label(self, key: Optional[int]) -> str:
        """How a message names the sheet: ``page 6`` in a one-book project —
        exactly as before — and the drawing number in a multi-book one."""
        if key is None or key == 0:
            return "no sheet"
        if not self.multi:
            return f"page {key}"
        si = self.info.get(int(key))
        if si is None:
            try:
                d, p = self.split(key)
            except SheetError:
                return f"sheet {key}"
            return f"{_series(self.filenames.get(d, ''))} p.{p}"
        return short_label(si)

    def cell(self, key: Optional[int]):
        """What a spreadsheet cell holds for the sheet: the page number in a
        one-book project (unchanged), the sheet's name in a multi-book one."""
        if key is None or key == 0:
            return ""
        if not self.multi:
            return key
        return self.label(key)


def short_label(si: SheetInfo) -> str:
    """``ALA-411B3-VBV-O (400 p.6)`` — or ``400 p.6`` with no drawing number."""
    where = f"{_series(si.filename)} p.{si.page}"
    return f"{si.sheet_number} ({where})" if si.sheet_number else where


def for_project(db: Session, project_id: int) -> Sheets:
    drawings = [(d.id, d.filename) for d in db.execute(
        select(Drawing).where(Drawing.project_id == project_id)).scalars()]
    pages = list(db.execute(select(Page).join(Drawing)
                            .where(Drawing.project_id == project_id)).scalars())
    return Sheets(drawings, pages)


# -- naming sheets inside the coverage engine's messages ----------------------

@contextlib.contextmanager
def naming(sheets: Optional[Sheets]) -> Iterator[None]:
    """While active, the domain's "on page N" names the sheet by its drawing
    number — in a multi-book project only; a one-book project reads as before."""
    with _naming(sheets.label if sheets is not None and sheets.multi else None):
        yield


class PageMeta(dict):
    """Something known per sheet (level, building …), keyed by sheet key, that
    can be asked about a row carrying ``drawing_id`` and ``page`` (4.1.0)."""

    def __init__(self, sheets: Sheets, data: dict):
        super().__init__(data)
        self.sheets = sheets

    def for_row(self, row, default=None):
        return self.get(self.sheets.of(row), default)


def meta_of(page_meta, row, default=None):
    """``page_meta``'s entry for ``row`` — by sheet when it is a
    :class:`PageMeta`, by the row's page number for a plain dict."""
    if isinstance(page_meta, PageMeta):
        return page_meta.for_row(row, default)
    return page_meta.get(getattr(row, "page", None), default)


def key_of(page_meta, row) -> Optional[int]:
    """The sheet key of ``row`` when ``page_meta`` knows the sheets, its page
    number otherwise."""
    if isinstance(page_meta, PageMeta):
        return page_meta.sheets.of(row)
    return getattr(row, "page", None)


def same_book(a_drawing: Optional[int], b_drawing: Optional[int]) -> bool:
    """Two rows are in the same book unless both name one and they differ —
    a row with no book recorded was drawn when the project had one."""
    return a_drawing is None or b_drawing is None or a_drawing == b_drawing


def on_canonical_sheet(e, a) -> bool:
    """Whether marker ``e`` is on register room ``a``'s canonical sheet."""
    return e.page == a.canonical_page and same_book(e.drawing_id, a.canonical_drawing_id)
