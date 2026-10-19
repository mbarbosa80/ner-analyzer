# Known limitations and recommended next steps

Written plainly, because a design-support tool whose limits are undocumented is
more dangerous than one that does less.

## What is not implemented yet

**OCR.** Scanned pages are detected and flagged (`needs_ocr`), never silently
skipped — but no OCR engine is wired in. Pages that need it produce no spaces and
no markers. The reference document is fully vector, so this was not on the
critical path. Adding it means one function behind the existing
`needs_ocr_pages` flag; keep the engine local and replaceable, as the brief asks.

**Computer vision for symbol shapes.** `pdf_ingest.py` scores label text, colour,
layer and context. It does not yet classify by *symbol geometry*. On the reference
drawing the text was decisive, so the marginal value was low — but a drawing that
marks rooms only with a symbol and no text will not be detected. OpenCV is listed
in the brief's stack and is the natural home for this.

**Room polygons.** Spaces are located by their label point. When a polygon is
present the engine already measures to its farthest vertex — and there are tests
proving that changes verdicts — but nothing currently *extracts* polygons from the
vector geometry. Until it does, most spaces are point estimates and are labelled
as such. This is the single highest-value improvement: it is the difference
between "the room label is 87 m away" and "the far corner of the room is 103 m
away".

**The sheets of one level are not stitched together (2.2.0).** Distance is
measured within one page. Since 2.2.0 a space that is *labelled* on a sheet
carrying a NER is measured there (`space_occurrence_links`), which settles the
room-on-a-match-line case. It does not settle the other one: a space that exists
**only** on a sheet with no NER, with the NER on the neighbouring sheet of the
same level. On the reference data that is 5 spaces on `HND` and 7 on a canoe-slalom
venue's book; they come back `not_analysable` unless a person chooses the serving NER
under `Served by` (a NER on another page is itself the cross-page statement). Fixing it means one coordinate frame per level. The overall
level plans (`-401-`, `-402-` …) cannot anchor it — they print no space codes —
so the control points would have to be the codes neighbouring detail sheets
share (112 of 448 codes on `HND` appear on more than one page). Feasible
and deterministic, not small.

**Wired connections the TEAP counts no port for (2.2.0).** TEAP v2.3 puts the
port on the device line, not on `Wired Connection`. Where users bring their own
device the port is counted by nobody: 253 wired connections on 27 zero-port
spaces on `HND`, 241 on 23 on the canoe-slalom venue. The application keeps those
spaces visible at zero ports and measures their distance, and **invents no
port** — so the NER loads are a floor, not a total, for press, photo and
commentary areas. A per-product override ("one DIPSA = one port") is the natural
next step and is a decision for the TEAP owner, not for this tool. The same
applies to Wi-Fi: the TEAP's wireless line counts as one port until access
points are drawn on the sheet; from then on the drawn wireless points take its
place in the load, one port each.

**Several books in one project — the series of one drawing set only.** Since
4.1.0 every sheet is addressed by book and page (`app/sheets.py`), so the 300,
400 and 600 series of a venue can share a project. Two *versions* of the same
series cannot: the application takes every book of a project as one drawing
set. Distances are measured within one sheet only; sheets of different series
are not registered to each other, so a NER drawn on the 400 is not placed on
the 600 automatically.

**Automatic placement of a NER.** Removed on 2026-09-02, deliberately and not
as a gap to be filled — see `docs/DECISIONS.md` and the manual's *As-Is vs
Proposed* section. The optimiser ranked positions by distance on a plan, which is
a fraction of what decides where an equipment room goes: power, cooling, physical
space, security, cabling access, A/B independence and the continuity plan are
outside the model. New rooms are placed by hand in the Drawing viewer. What the
application does is price a placement — the distances, what falls outside the
limits, what nothing reaches.

The reposition arrow the brief's notation specifies is still not drawn.

**Scenario branching and restore.** The As-Is run is saved with author,
timestamp, justification and full result payload, and is what the reports and the
demand list read back. There is one design now, so there is no second scenario
and no comparison. Restoring a previous version from the UI is not built; the
frozen register snapshot (change request / design freeze) is the mechanism that
exists for holding a state.

**Asynchronous processing.** Done — ingestion, matching and coverage
run as cancellable background jobs with per-stage progress. What
is *not* done: jobs do not survive a server restart (a job running when the
process dies is left in `running` forever), and there is no retry. Both are
acceptable for a single-user desktop tool and neither is hard to add.

**Authentication.** Built (accounts, sessions, admin, per-project visibility).
The application still binds to `127.0.0.1` and is intended as a single-user
desktop tool; the sign-in is not a substitute for that. Do not expose it on a
network as-is — that is a different deployment with different obligations.

**Two-point calibration has no tool any more (3 Sep 2026).** The Scale screen
takes a ratio or a scale text per page, and `Confirm all pages` confirms every
detected one at once. A sheet with no printed scale *and* no known ratio has
to be read off its own title block. The `pdf_distance_units` / `real_distance`
form of `POST /pages/{n}/scale` still exists on the server if the tool has to
come back.

**A TEAP that names the serving NER is supported, not seen.** `serving_ner` is
an optional mapping field; the TEAP v2.0 has no such column, so on every
project so far the rule falls straight through to the person's choice and the
nearest room with free ports. When a TEAP does carry one, the name is resolved
against the live NERs by normalised label; a name nobody answers to is shown
on the row and ignored by the engine — it does not become a wrong pin.

## What is deliberately *not* automated

**Removal recommendations.** The tool will not recommend removing a room, because
power, cooling, security, access and operational continuity are not derivable from
a drawing. The spatial-redundancy candidate list that stated this in the weakest
possible way — a true observation ("every area this room serves is reachable from
another one") sitting beside real results, where it read as a recommendation —
was removed from the screen and from the workbook on 2026-09-02. The removal
decision is made room by room, by a person, with the drawing open.

**Criticality.** Never inferred. The reference TEAP has no criticality column; the
tool proposes the nearest compatible NER and flags it for validation.

**Cross-floor service.** Never assumed. A shaft, riser or vertical route must be
registered with its real length.

**TER↔NER connection rules.** Not invented. If your programme has them, they
belong in project configuration and then in the coverage engine.

## The limitation that matters most

**Straight-line distance is not cable length.** Every straight-line result in this
tool is a screening number. The 90 m limit is the ANSI/TIA-568 permanent link —
installed cable along its real route, inside a 100 m channel that reserves 10 m
for patch cords. Raise `routing_slack_factor` to 1.25–1.40 for an arena bowl, or
trace the actual containment, before a green result is used to make a decision.

**Alias curation is manual and unbounded in principle.** The worklist is ranked by
port demand precisely so it can be stopped early, but nothing forces that. Do not
curate past the point where the remaining rows stop carrying meaningful demand.

## Uploading a second version of a drawing corrupts the analysis

This is the sharpest edge in the tool, because it does not fail — it produces
plausible wrong numbers.

Page number is scoped to the *project*, not to the document, so a second VDB in
the same project makes page 5 of the new drawing collide with page 5 of the old
one, and the coverage engine will measure from a marker on one to a space on the
other. `services.scale_map()` says as much in its own docstring.

**Until document versioning is built** (`docs/VERSIONING.md` has the full design):
when a revised VDB arrives, create a **new project** for it and carry the
previous NER register across as an exported XLSX. Reconcile by eye. One project
per venue is right; one project per *version* is the workaround.

## V2 — what the register does not yet do

**No TVDB.** Phase one reads no technology design book. Containment, pathways,
Route A / Route B, shafts, risers and shared-risk segments are therefore not
analysed — and the register says `not_analysed` for each of them rather than
implying a route exists. Every NER carries *"no TVDB route validated"* as a
pending validation, and every distance in the tool is still a straight-line
screening number.

**Automatic consolidation is only as good as the page metadata.** Level agreement
is what lets two occurrences merge without asking. On a real venue design
book (`HND`) only **3 of 34 pages** carry a level, and the one value extracted (`155`)
looks like a false read rather than a level name. The consequence is that the
tool merges nothing automatically on that document and sends every candidate to
the review queue — conservative and correct, but more work than it should be.

Improving level extraction from sheet titles and title blocks is the single change
that would most reduce that queue, and it should be done *before* loosening the
merge threshold. Lowering the threshold to shrink the queue would trade a slow,
correct register for a fast, wrong one.

**Sector is not extracted.** `NerAsset.sector` exists and is editable, but nothing
fills it in. The same is true of `space_name` / `space_code` on the NER itself —
matching a NER to the room it sits in is a separate job from matching TEAP spaces
to drawing spaces, and phase one does not do it.

**Cross-page geometry is not compared.** Two occurrences on different pages are
compared on label, level, building and kind, never on position, because the pages
are not registered against one another. Aligning viewports would let the tool say
"these two markers are the same point in the building", which is much stronger
evidence than a matching label.

**Capacity is still mostly unknown.** The register surfaces "capacity unknown" as
a pending validation on every room the drawing did not state one for, and never
treats it as zero. Filling it in is manual.

## Recommended order of work

1. Extract room polygons from the vector geometry (biggest accuracy gain).
2. ~~Key everything by `(drawing_id, page)` so multi-PDF projects work.~~ Done in 4.1.0.
3. Wire in a local OCR engine behind the existing `needs_ocr` flag.
4. Draw reposition arrows and constrain move distance.
5. Scenario branching and restore.
6. Symbol-shape classification with OpenCV.
7. Job durability across restarts.
8. PostgreSQL/PostGIS, if this ever becomes multi-user.

### V2 phase two, in the order the spec asks for it

1. Level and building extraction from sheet titles — unlocks automatic
   consolidation, and everything cross-floor after it.
2. TVDB upload and versioning, with VDB↔TVDB page correspondence.
3. Manual marking of containment, pathway, Route A and Route B.
4. Distance by real route, replacing the straight-line screening number.
5. Route A / B independence analysis and the redundancy exception for critical
   NERs.
6. Only then: automatic route detection, OCR, layer interpretation, automatic
   version comparison.
