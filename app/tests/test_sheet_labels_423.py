"""4.2.3 — a sheet key never reaches the person.

Marcelo, 17 Oct 2026, on the NERs screen of a project with the 400 and 600
books: *"Não entendi essa numeração de páginas 10012 20004"*. Since 4.1.0 a sheet
of a multi-book project is named internally by ``drawing_id * 10000 + page``;
the API hands those keys out on purpose and the screens are meant to turn them
into ``400·12``. The *also on* line of the NERs screen printed them raw, and so
did eight other places in the front end (matching table, shafts, scale and
creation notices, the same-name and consolidation dialogs).

Two guards:

* the back end — a two-book project driven through matching, analysis, the NER
  register, consolidation candidates, exceptions, the workbook and the CSV;
  no text a person reads (any string in any response, any workbook cell) may
  carry a sheet key. Numeric ``page`` fields stay keys: that is the contract.
* the front end — every place found on 17 Oct now formats the key, and no raw
  ``pages.join`` / ``.page`` rendering is left in the screens.
"""

from __future__ import annotations

import csv
import pathlib
import re

import openpyxl
import pytest

from tests.test_multi_book_410 import _key, _ner, _room, _teap, _two_books
from tests.test_wireless_tie_250 import client  # noqa: F401
from app.config import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"


def _strings(obj, path=""):
    """Every string in a JSON payload, with where it sits."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def _leaks(text: str, keys: set[int]) -> set[int]:
    return {int(t) for t in re.findall(r"(?<![\d.])\d{5,}(?![\d.])", text) if int(t) in keys}


@pytest.fixture(scope="module")
def two_books(client):
    pid, a, b = _two_books("two books labels 423")
    # One space on each book, the same code twice (one room seen on both),
    # a space nobody serves, and one NER drawn on both books.
    _room(pid, a, 1, "SPC.010", 100, 100)
    _room(pid, b, 2, "SPC.010", 300, 300)
    _room(pid, b, 1, "SPC.011", 900, 650)
    _room(pid, a, 2, "SPC.012", 500, 500)
    for code in ("SPC.010", "SPC.011", "SPC.012", "SPC.099"):
        _teap(pid, code)
    _ner(pid, a, 1, "NER 30", 120, 100)
    _ner(pid, b, 2, "NER 30", 320, 300)           # same name, another book
    _ner(pid, a, 2, "NER 31", 520, 500)
    assert client.post(f"/api/projects/{pid}/matching/run").status_code == 200
    keys = {_key(d, n) for d in (a, b) for n in (1, 2)}
    return pid, a, b, keys


GETS = [
    "", "/elements", "/drawing-spaces", "/teap-spaces", "/matches", "/zones", "/routes",
    "/verticals", "/spaces/assignments", "/occurrence-links", "/ners",
    "/ners/duplicates/candidates", "/ner-consolidations", "/ner-assets/positions",
    "/criticality/escalations", "/overlaps", "/audit",
]


def test_no_response_text_carries_a_sheet_key(client, two_books):
    pid, a, b, keys = two_books
    found = []
    analysed = client.post(f"/api/projects/{pid}/analyse")
    assert analysed.status_code == 200, analysed.text
    payloads = {"POST /analyse": analysed.json()}
    for g in GETS:
        r = client.get(f"/api/projects/{pid}{g}")
        if r.status_code == 200:
            payloads[f"GET {g or '/'}"] = r.json()
    for ner in client.get(f"/api/projects/{pid}/ners?include_removed=true").json()["ners"]:
        payloads[f"GET /ners/{ner['id']}"] = client.get(f"/api/projects/{pid}/ners/{ner['id']}").json()
    assert len(payloads) > 12
    for where, body in payloads.items():
        for path, s in _strings(body):
            if _leaks(s, keys):
                found.append(f"{where}{path}: {s!r}")
    assert not found, "sheet keys in text a person reads:\n" + "\n".join(found[:40])


def test_no_workbook_or_csv_cell_carries_a_sheet_key(client, two_books):
    pid, a, b, keys = two_books
    assert client.post(f"/api/projects/{pid}/analyse").status_code == 200
    found = []
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and _leaks(str(c.value), keys):
                    found.append(f"{ws.title}!{c.coordinate}: {c.value!r}")
    r = client.post(f"/api/projects/{pid}/reports/csv?background=false")
    assert r.status_code == 200, r.text
    with open(settings.exports_dir / f"project_{pid}" / r.json()["file"], encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.reader(fh)):
            for j, v in enumerate(row):
                if _leaks(v, keys):
                    found.append(f"csv r{i} c{j}: {v!r}")
    assert not found, "sheet keys in the exports:\n" + "\n".join(found[:40])


# ---------------------------------------------------------------------------
# Front end
# ---------------------------------------------------------------------------

def _src(name: str) -> str:
    return (SRC / "pages" / name).read_text(encoding="utf-8")


def test_the_ners_screen_formats_also_on():
    # 4.4.0: each "also on" sheet is a PageButton (a link to the sheet), and
    # the button writes its number with sheetNo — so the label stays formatted.
    src = _src("NerRegister.tsx")
    i = src.index('t("also on")')
    block = src[i:i + 900]
    assert "<PageButton ctx={ctx} page={x}" in block, block
    pb = _src("panels.tsx")
    j = pb.index("export function PageButton")
    assert "sheetNo(p, page)" in pb[j:j + 1200]


@pytest.mark.parametrize("name", ["NerRegister.tsx", "panels.tsx", "Viewer.tsx"])
def test_no_raw_sheet_number_is_rendered(name):
    s = _src(name)
    bad = []
    # A list of sheet keys joined as they are.
    bad += re.findall(r"\.pages\??\.join\(", s)
    bad += re.findall(r"\.pages\.filter\((?:(?!\.map\()[^\n])*\)\.join\(", s)
    # A key put straight into JSX or a message.
    bad += re.findall(r"<td>\{m\.page \?\?", s)
    bad += re.findall(r"(?<!SHAFT-)\$\{(?:page(?!\}\$\{sheet\})|d\.lower_page|d\.upper_page|v\.lower_page|v\.upper_page|"
                      r"selected\.data\.lower_page|selected\.data\.upper_page)\}", s)
    bad += re.findall(r"p\.\$\{lower \? v\.upper_page : v\.lower_page\}", s)
    assert not bad, f"{name}: sheet keys rendered raw: {bad}"


def test_the_sweep_sees_sheet_names(client, two_books):
    """The sweep above has teeth only if the payloads name sheets at all."""
    pid, a, b, keys = two_books
    texts = [s for g in ("/occurrence-links", "/spaces/assignments", "/matches")
             for _, s in _strings(client.get(f"/api/projects/{pid}{g}").json())]
    analysed = client.post(f"/api/projects/{pid}/analyse").json()
    texts += [s for _, s in _strings(analysed)]
    named = [s for s in texts if re.search(r"\((?:400|600) p\.\d\)", s)]
    assert named, "no response names a sheet; the sweep would pass for nothing"
    assert _leaks("seen on page 10002 and 20001", {10002, 20001}) == {10002, 20001}
