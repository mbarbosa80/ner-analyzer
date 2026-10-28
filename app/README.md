# NER Spatial Coverage Analyzer

**Version 4.5.0** — the number lives in `VERSION`; see `CHANGELOG.md` for the
numbering rule and the release steps.

A working web application for studying **TER / NER placement and network coverage**
from venue design drawings and a TEAP allocation plan.

It reads real PDFs and real spreadsheets, computes real distances against real
rules, and exports marked-up drawings and auditable workbooks. It is a *screening
and review* tool: it does not approve a design.

> This tool supports the design process. It does not replace engineering approval,
> a site survey, cable route validation or physical inspection.

© 2026 Marcelo Barbosa. Created by Marcelo Barbosa. Free software under the
[GNU AGPL-3.0](LICENSE.txt): use it, study it, change it and share it, keeping
the credit to the author — an additional term of the licence, see
[`NOTICE.txt`](NOTICE.txt). The components it is built on keep their own
licences ([`THIRD-PARTY-NOTICES.txt`](THIRD-PARTY-NOTICES.txt)).

An independent project: not affiliated with, sponsored or endorsed by any
event organiser, rights holder, federation, venue or employer.

## Documentation

| File | What it is |
|---|---|
| `docs/MANUAL.html` (+ `.pdf`) | The user manual — how the application works, screen by screen (English) |
| `docs/INSTALL.html` (+ `.pdf`) | The installation manual — what a new Windows computer needs and how to install |
| `docs/HISTORY.html` (+ `.pdf`) | The project record — what came in, what went out and why |
| `CHANGELOG.md` | What changes in each version from 2.0.0 on |
| `docs/DECISIONS.md`, `docs/FINDINGS.md`, `docs/LIMITATIONS.md`, `docs/VERSIONING.md` | Technical notes |

## Quick start (Windows)

Nothing to install first: the installation package carries its own Python
(the python.org embeddable 3.12, unpacked by `install.bat` into `.python\`).
A development checkout without `vendor\python\` uses the machine's Python
3.11+ and a `.venv\` instead; every script looks for `.python\` first.

```
setup.bat          the installer of a built package (Run as administrator): installs into
                   %LOCALAPPDATA%\Programs\ner-analyzer, replaces an older version keeping
                   its data, starts it and deletes the package
setup-noadmin.bat  the same without asking for administrator rights (setup.bat --no-admin):
                   for a managed computer, installs for the account signed in only
install.bat        unpacks the bundled Python into .python\ and installs the packages offline
                   (development checkout: builds .venv\ from the machine's Python)
start.bat          starts the server in a console window and opens the browser
stop.bat           stops it
autostart.bat      starts it at sign-in with no window, and installs the watchdog
backup.bat         consistent backup of the database and the uploads (--restore to put one back)
run-tests.bat      the test suite (~750 tests)
build_package.bat  builds dist\ner-analyzer-<version>-windows.zip for another machine
```

On macOS / Linux, `python run.py` does what `start.bat` does.

## Editions

Two editions are built from the same source by `tools/make_package.py`. The
**team edition** (the default) carries the private reference material of
`backend/app/reference_private/` — a client's list of space names and naming
table, when the builder has them. The **public edition**
(`python tools/make_package.py --public`, written as
`ner-analyzer-<version>-public-windows.zip` / `...-public-macos-arm64.zip`)
leaves that folder out and refuses to build while any shipped text names an
event, an organiser, a venue or an employer. The application works the same
without the private material: the TEAP names alone filter name-only room
labels, and the Naming panel shows the application's own naming rule.

---

---

## The workflow

The left-hand navigation is the workflow, in order.

| # | Step | What happens |
|---|------|--------------|
| — | **Projects** | Create, open, share (read-only) and delete projects. One project is one venue. |
| 1 | **Import** | Upload the VDB PDF and the TEAP workbook. The PDF is parsed for the title block, scales, spaces and markers; the workbook is profiled (every sheet, header row, proposed column mapping) and its venues are listed so you import one venue, not the whole programme. Project rules (limits, near-limit band, slack factor, units). |
| 2 | **Scale** | Detected scales are proposals. Confirm each page (or all pages that have one) — definitive results stay blocked until you do. |
| 3 | **Drawing viewer** | Pan/zoom the real PDF; create, move, rename and delete NER, TER, IDF, COW and DIVA node markers; trace cable routes; register shafts; paint the coverage overlay. |
| 4 | **NERs** | One row per **physical** equipment room, however many sheets draw it: rename without changing the identifier, criticality, capacity, lock, confirm, remove/restore; duplicate queue with evidence; consolidation history with undo. |
| 5 | **TEAP × drawing** | Match TEAP locations to drawing spaces (exact code → base code → name → similarity → context), choose and confirm one by one; decisions live on the TEAP line and survive re-runs. |
| 6 | **Demand per space** | Run the analysis; port demand per space, the serving NER (TEAP → your choice → nearest with free ports → nearest anyway, flagged), distance, status, notes, NER load and capacity. |
| 7 | **Exceptions** | Spaces no NER covers or that could not be analysed, and TEAP lines with no room on the drawing. |
| 8 | **Reports** | Marked-up PDF (legend and NER → space lines optional), analysis workbook, coverage CSV — all stamped with the version. |
| — | **Account & security** | Accounts, administration, the audit log and the data statement. |

---

## The rules it applies

* A network port, connected device or access point must be within **90 m** of the
  NER that serves it.
* A photographer point or area must be within **70 m**.
* Both limits are editable per project.
* When a cable route is traced, the route length governs. When it is not, the
  straight-line distance is used and every result carries the warning
  *"Preliminary straight-line distance. The result must be validated against the
  real cable route."*
* A NER never serves another floor unless a shaft, riser or vertical route has
  been registered.
* A **TER is recorded and drawn but never auto-assigned** to serve a functional
  area. The TER↔NER relationship is a separate design rule the tool does not
  invent.
* Where a room polygon exists, compliance is evaluated against its **farthest
  vertex**, not only its centre.

### About the 90 m limit — read this before trusting a green result

ANSI/TIA-568 and ISO/IEC 11801 define 90 m as the **permanent link**: the fixed
horizontal cable, inside a 100 m channel that reserves 10 m for patch cords. It is
cable length along the real route, not a straight line on a plan. Cable rises into
a shaft, runs in tray around structure and drops back down, so a straight-line
measurement systematically under-reports the installed length.

The application models this with a per-project **routing slack factor**. It
defaults to `1.0`, which reproduces the raw geometric study the brief asks for and
which every result labels as such. **Raise it before treating any result as a
design decision** — 1.25–1.40 is typical for an arena or stadium bowl. Every
evaluation reports the raw geometric distance and the effective distance the
verdict used, so nothing is hidden.

---

## Long operations

Reading a 34-page venue design book, matching thousands of spaces and solving the
placement model all run as **background jobs**: a progress bar with the stage in
words ("reading page 12 of 34"), and a **Cancel** button. Nothing heavy blocks an
HTTP request any more.

Two guards exist because their absence caused real damage:

* **A multi-venue sheet cannot be imported without a venue filter.** A master
  allocation plan covers the whole programme — importing all of it against one
  venue's drawings compares rooms in one venue with equipment rooms in another.
  The project's venue code is offered as the default; importing everything
  requires ticking a box.
* **The placement model has a hard size ceiling.** The solver's time limit does
  not cover *building* the model, so an oversized input used to peg a core for
  minutes with no feedback. It now refuses immediately and says what to narrow.

## What is deterministic

Every distance, assignment, demand total and optimisation result is computed by
plain Python and Google OR-Tools. **No language model participates in any
calculation.** The CP-SAT solve is integer, single-threaded and seeded, so the
same inputs always produce byte-identical output. There are tests that assert
exactly this.

## Four kinds of data, never mixed

| Kind | Meaning |
|------|---------|
| **extracted** | what a document said |
| **confirmed** | what a human signed off |
| **estimated** | what the tool inferred to keep going |
| **proposed** | what the optimiser recommends |

Every element, match and result carries which one it is. Exports state it per row.

---

## Visual notation

| Symbol | Meaning |
|--------|---------|
| Blue dot | TER |
| Red dot | NER — critical |
| Yellow dot | NER — non critical |
| Purple dashed circle | NER — proposed |
| Grey crossed circle | NER — spatial redundancy candidate |
| Green translucent | Area served |
| Orange translucent | Area near the limit |
| Red translucent | Area out of coverage |
| Orange outline | Match not confirmed |

The legend is permanent in the viewer and on every exported PDF.

**Important:** real venue design books do not encode criticality in colour. On the
reference drawing this application was built against, *every* equipment-room
label — critical and non-critical — is the same red, and criticality is carried by
the word "Critical" in the label text. The extractor therefore scores several
signals (label text first, then colour, symbol, layer and context) and reports a
confidence per element rather than trusting colour alone. The notation above is
how the *application* draws its own normalised output.

---

## Running the tests

```bash
.venv/bin/python -m pytest          # Linux/macOS
.venv\Scripts\python -m pytest      # Windows
```

About 470 tests covering the mandatory cases: 89 m passes / 91 m fails, 69 m passes /
71 m fails, metric and imperial scales, pages at different scales, multi-sheet
workbooks, exact / similar / ambiguous names, double-counting prevention, a plan
with no NER, uncovered areas, overlapping NERs, insufficient capacity,
redundancy preservation, NERs on different floors, route length differing from the
straight line, scanned and vector PDFs, TER/critical/non-critical identification —
plus the real-document regressions and the four defects found in live use, all
described in docs/FINDINGS.md.

## Synthetic demonstration data

```bash
python run.py --sample
```

Generates `sample_data/synthetic_venue_plan.pdf`, `synthetic_venue_scanned.pdf`
and `synthetic_teap.xlsx`. They mirror the *structure* of real documents — the
same space-code taxonomy, the same "Critical NER n" labelling, a workbook whose
header is not on row 1 — with no real content, so the tests and demos never touch
confidential material.

---

## Project layout

```
run.py                     one-command launcher
requirements.txt
backend/app/
  main.py                  ASGI app; serves the compiled front-end
  config.py  db.py  models.py  services.py
  api/routes.py            HTTP API (thin: parse, persist, dispatch)
  api/ner_routes.py        HTTP API for the NER register (V2)
  migrate.py               V1 -> V2 schema and data migration, idempotent
  ner_register.py          the canonical NER register and its decisions (V2)
  ner_suggest.py           optimiser output -> suggested register rows (V2)
  domain/                  everything that decides a number
    units.py               scale parsing, metric/imperial, calibration
    geometry.py            points, polygons, farthest-vertex
    distance.py            the 90/70 rules, slack factor, statuses
    routes.py              cable-route graph incl. shafts and risers
    pdf_ingest.py          vector PDF extraction, multi-signal classification
    teap_import.py         workbook profiling and column mapping
    demand.py              port demand, rules A–D, no double counting
    matching.py            TEAP × drawing matching cascade
    consolidation.py       is this the same physical room? (V2)
    coverage.py            assignment, capacity, redundancy
    optimize.py            OR-Tools facility location / set covering
    reports.py             marked-up PDF and audit workbook
  sample_data.py           synthetic document generator
frontend/                  React + TypeScript + Vite + PDF.js + Konva
tests/                     pytest suite
docs/                      decisions, findings, limitations
```

## V2 — the NER register

V1 recorded one row per marker found on a page. A venue design book draws the
same equipment room on the level key plan, on a zone detail and again on a
services overlay, so `Critical NER 3` became three rooms — and every number that
followed inherited the error.

V2 separates **the room** from **the document that draws it**:

* a **canonical NER** (`ner_assets`) owns the name, the classification, the
  keep/reject decision, the capacity and the position. Its internal id and its
  register code never change — renaming writes a new display name and appends to
  the name history, so a report exported last month still resolves to the room it
  described;
* a **documental occurrence** (the old `elements` row, now carrying
  `ner_asset_id`) records where that room appears: document, page, coordinate,
  confidence, detection method.

### What merges by itself, and what does not

An identical label is not enough — venues reuse a numbering series across
buildings. Two occurrences are linked without asking only when the normalised
label, the level **and** the building all agree. A conflict on level or building
disqualifies the pair however well the labels match; `NER 4` and `NER 5` are two
rooms by definition; and an *unknown* level is treated as a question, not an
agreement, so the pair lands in the review queue instead of being assumed.

Every automatic link is written to the consolidation log with its evidence and an
undo snapshot. There is no silent path — a merge the tool made can be inspected
and reversed exactly like one a person made.

The duplicate queue shows **evidence and differences side by side**. A reviewer
shown only the reasons to merge will merge.

### Suggested NERs are questions

The solver answers a geometric question, which is not the same question as "where
can a NER go". A suggestion enters the register with status `suggested`, is
excluded from the As-Is analysis until someone confirms it, and carries the full
justification: why, which areas it would serve, total demand, longest serving
distance, how many areas were out of coverage before and after, the constraints
found, what still needs validating, and that it depends on the TVDB.

### Migrating an existing database

Nothing to run. Opening the database performs the migration, and it is idempotent
— a second start finds every marker already linked and does nothing. Verified
against a real venue design book (VEE): 26 markers → 26 canonical NERs, 3
duplicate questions raised for a human, and coverage **identical** to V1 down to
the status histogram (2 873 spaces, 988 served, 1 885 uncovered, 21 434 ports).

Back up `data/ner.sqlite3` first anyway. It costs nothing and the tool cannot put
back what it never had.

### One drawing version per project, for now

Do **not** upload a revised VDB into a project that already has one. Page numbers
are scoped to the project rather than to the document, so the two versions
collide and the coverage engine silently measures across them. Create a new
project for the revision and carry the NER register over as an XLSX export.

The full design for proper versioning — page namespacing, a frozen change
request, and a reconciliation screen answering *"did they draw what I asked?"* —
is written up in `docs/VERSIONING.md`. It is proposed, not built.

### Not in V2 phase one

No TVDB. Containment, pathways, Route A / Route B, shafts, risers and shared-risk
segments are **not analysed** — the register says `not_analysed` for each rather
than implying a route exists, and every NER carries *"no TVDB route validated"* as
a pending validation. Every distance in the tool is still a straight-line
screening number. See `docs/LIMITATIONS.md`.

---

## Starting automatically at logon (Windows)

A scheduled task named **NER Spatial Coverage Analyzer** starts the server when
you log in, so it survives a reboot without anyone opening a terminal.

```
Action   .python\pythonw.exe  tools\serve.py      (.venv\Scripts\pythonw.exe on a development checkout)
Trigger  at logon
Log      data\server.log
```

`tools/serve.py` exists rather than a shortcut to `run.py` because three things
make an auto-started server fragile on Windows, and it removes all three: the
working directory is not the project folder (every path is resolved from
`__file__`), the data folder must not drift (`NER_DATA_DIR` and
`NER_DATABASE_URL` are pinned to absolute paths and printed to the log), and
`pythonw.exe` has no console (output is redirected to the log before anything
else runs, so a startup failure leaves a trace instead of a process that
vanishes). It also exits quietly if the port is already serving, so launching it
twice is harmless.

**Cold start takes 20–40 seconds** — importing PyMuPDF and OR-Tools, then running
the migration. The page will not answer before that. `data\server.log` shows
`Application startup complete` at the moment it is actually ready.

Manage it by hand with `tools\server-start.cmd` and `tools\server-stop.cmd`, or
in Task Scheduler. To remove the task:

```powershell
Unregister-ScheduledTask -TaskName "NER Spatial Coverage Analyzer" -Confirm:$false
```

The trigger is *at logon*, not *at boot*: the app reads and writes a folder in
your user profile, so it runs as you and needs no stored password and no
administrator rights.

---

## Security

Uploaded documents are treated as untrusted: file type and size are validated,
names are flattened, workbooks are opened read-only with `keep_vba=False` so
**macros are never executed**, formulas are read as cached values, and each
project's files are isolated in their own directory. Every mutation is written to
an audit log with actor, timestamp and justification. Nothing is sent to any
external service.

Do not use real confidential venue documents in a public demo.

---

## Validating against your own documents

Before trusting any coverage number from a new document family, run the
extraction report:

```bash
python tools/validate_against.py "your_drawing.pdf" "your_teap.xlsx" --venue VEE
```

It prints what was extracted, which scales were found, which pages have none,
which demand rules fired, how many lines reconciled, and what the matching engine
resolved versus held for review. Everything runs locally; nothing is uploaded.

See [docs/FINDINGS.md](docs/FINDINGS.md) for the measured result against the
reference event documents and the two extraction defects that report caught,
[docs/DECISIONS.md](docs/DECISIONS.md) for why the code is shaped the way it is,
and [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for what it does not do yet.
