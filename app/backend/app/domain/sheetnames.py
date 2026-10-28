"""How the coverage engine names a sheet in its messages (4.1.0).

``page 6`` by default — exactly the words of every release before 4.1.0 — and,
while :func:`naming` is active, whatever the caller says the sheet is called
(the drawing number, in a project with several books). Kept apart from
``app.sheets`` so the domain modules import nothing from the database layer.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Callable, Iterator, Optional

_LABEL: contextvars.ContextVar[Optional[Callable[[Optional[int]], str]]] = \
    contextvars.ContextVar("sheet_label", default=None)


def page_label(key: Optional[int]) -> str:
    fn = _LABEL.get()
    if fn is not None:
        return fn(key)
    return f"page {key}"


@contextlib.contextmanager
def naming(fn: Optional[Callable[[Optional[int]], str]]) -> Iterator[None]:
    token = _LABEL.set(fn)
    try:
        yield
    finally:
        _LABEL.reset(token)


def pages_label(pages) -> str:
    """``pages [3, 5]`` — exactly the old words — or the sheets' own names
    while :func:`naming` is active."""
    pages = list(pages)
    fn = _LABEL.get()
    if fn is None:
        return f"pages {pages}"
    return "sheets " + ", ".join(fn(p) for p in pages)
