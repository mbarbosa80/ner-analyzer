# Technical decisions

Short records of the choices that are not obvious from the code, and why.

---

### 1. The front-end is compiled into the backend

The brief asked for React + FastAPI. Shipping them as two processes would mean the
user needs Node installed and two terminals running. The Vite build writes
straight into `backend/app/static`, FastAPI serves it, and `run.py` bootstraps its
own virtual environment — so the machine needs **only Python 3.11+**. Node is
required solely to modify the interface.

*Trade-off:* the compiled bundle is committed as a build artefact rather than
built on the user's machine.

---

### 2. Everything is stored in metres; `units.py` is the only converter

PDF user units, drawing scales, feet, architectural notation and metres all meet
in one module. Every distance elsewhere in the system is already in metres. This
is what makes a distance auditable — there is a single code path to inspect when a
number looks wrong.

---

### 3. Straight-line results are never presented as compliant without qualification

`DistanceEvaluation` carries `geometric_distance_m` and `effective_distance_m`
separately, plus `method`, `scale_label`, `scale_confirmed`, `assumptions`,
`warnings` and `requires_human_validation`. A verdict without its assumptions is
not reviewable, so the object refuses to be reduced to a boolean.

`routing_slack_factor` defaults to `1.0` so the raw geometric study the brief
specifies is reproduced exactly and the mandated 89 m/91 m tests hold literally.
The default is documented as unsafe for design decisions in three places
(README, the module docstring, the UI) and there is a test proving that a 75 m
point flips to non-compliant at a realistic 1.3.

---

### 4. Blocking conditions are evaluated in priority order, before the verdict

Match not confirmed → scale not confirmed → distance verdict. A space whose match
is unconfirmed never reports "served", however short the distance. This is the
mechanism behind "definitive results stay blocked until the scale is confirmed".

---

### 5. A TER is not in `SERVING_KINDS`

The brief says a TER must be recorded and drawn but not auto-treated as a NER, and
that the tool must not invent TER↔NER rules. Excluding it from the serving set at
the type level makes that structural rather than a convention someone can forget.

---

### 6. Space code before name similarity

Reversed from the brief, on the strength of measurement — see
[FINDINGS.md](FINDINGS.md) §2. Exact-code matching is deterministic and
explainable; similarity matching is neither. Every `MatchCandidate` carries the
method, the score, the confidence and a human-readable reason.

---

### 7. Rule A–D hierarchy for port demand

Exactly one rule fires per TEAP line. That is what structurally prevents double
counting — not a de-duplication pass that could be got wrong. Each line records
which rule fired and why, and the space-level memo is reproduced in the UI and in
the export.

---

### 8. The optimiser's objective is strictly lexicographic

The first implementation weighted the goals `10000 / 1000 / 10 / 1` and a test
caught it opening an unnecessary new room to shave 45 m of distance — distance
dominated the new-room cost. The weights are now derived from the upper bound of
every lower-priority term, so *no amount of saved cable can ever justify one extra
room*. Whole metres (not centimetres) drive the objective so the derived weights
stay exact in int64.

Determinism is enforced with `num_search_workers = 1` and a fixed
`random_seed`; there are tests asserting identical output across repeated runs for
both the coverage engine and the solver.

---

### 9. Candidate positions are never arbitrary

Registered technical rooms and permitted zones come first. The coarse grid is a
labelled fallback: every position it produces is returned with the qualifier
*"Recommended geometric zone, subject to technical and operational validation."*

---

### 10. Redundancy is a classification, not a recommendation

`redundancy_candidates()` can only ever return
*"Spatial redundancy candidate — capacity and technical requirements still to be
validated."* with an explicit list of blockers (locked, not removable, capacity
unknown, critical-rated). Power, cooling, security, access and operational
continuity are not modelled from a drawing, so a removal recommendation is not
something this tool is in a position to make.

---

### 11. SQLite with SQLAlchemy 2.0, JSON columns for evidence payloads

Plain SQLAlchemy models mean PostgreSQL/PostGIS is a URL change plus a migration.
Evidence lists, alternatives and calculation memos are JSON because their shape is
per-record and they are read as a unit, never queried into.

---

### 12. Legend defined once, in `notation.ts` and `reports.py`

The viewer legend and the exported-PDF legend are generated from a single table on
each side. Two hand-maintained legends drift; a drifted legend on a drawing that
goes to a contractor is a real problem.

---

### 13. Documents are untrusted input

Extension and size validated, names flattened, workbooks opened read-only with
`keep_vba=False`, formulas read as cached values, per-project directories, no
network egress. Every mutation writes an audit row with actor, timestamp and
justification.

---

## V2 — the canonical NER register

### 14. `Element` is now an occurrence, `NerAsset` is the room

V1 stored one `Element` per marker found on a page. That conflated two different
things, and the conflation was silently wrong: a design book draws the same
equipment room on the level key plan, on a zone detail and on a services overlay,
so `Critical NER 3` became three rooms. Coverage then had three NERs where the
building has one, and every number downstream — port load, redundancy, "areas
without a NER" — inherited the error.

V2 splits them rather than replacing them:

* `NerAsset` owns the name, classification, keep/reject decision, capacity and
  canonical position. Its `id` and `code` never change.
* `Element` keeps every column it had and gains `ner_asset_id`, so it now
  describes *where this room appears in a document* — page, coordinate,
  confidence, detection method, symbol, colour.

Keeping `Element` rather than migrating markers into a new table means V1 data is
never rewritten. If the migration turns out to be wrong, the original rows are
still there to remigrate from.

### 15. Merge on proof, ask on suspicion, never assume

Two constraints in the spec pull against each other: do not create a NER per
occurrence (§9), and never consolidate an ambiguous pair silently (§9 again).
`domain/consolidation.py` resolves them with one rule:

* an identical normalised label is **necessary but not sufficient** — venues do
  reuse a numbering series across buildings;
* agreement on **level and building** is what turns a matching label into proof,
  and only that combination merges automatically (`AUTO_MERGE_THRESHOLD = 0.97`);
* a **conflict** on level or building is disqualifying however well the labels
  match, and consecutive indices in one series (`NER 4` / `NER 5`) are two rooms
  by definition;
* an **unknown** level is not an agreement. The score is capped just below the
  automatic threshold so the pair becomes a question rather than an assumption.

Every automatic link is written to `ner_consolidations` with its evidence and an
undo snapshot, so it is inspectable and reversible exactly like a manual one.
There is no silent path.

Measured on a real venue design book (`VEE`): 26 markers → 26 canonical NERs, 0
automatic merges, 3 duplicate questions raised (`NER 5` twice, `IDF` three
times). Zero automatic merges is the right answer for that document, because only
3 of its 34 pages carry a level — see LIMITATIONS.

### 16. The comparison returns the differences, not only the evidence

`Comparison` carries `evidence` *and* `differences`, and the review screen shows
both columns side by side. A reviewer who is only ever shown the reasons to merge
will merge. This is the same reasoning as the matching review queue: what matters
is what the row *asks the human*, not how few rows there are.

### 17. Coverage reads the register; the marker path stays as a fallback

`services.register_ners()` builds the coverage NERs from `NerAsset`, excluding
rejected, removed and consolidated rooms, and keys them `A<id>` instead of
`E<id>`. Two deliberate choices behind it:

* `critical` still follows the **marker kind**, not the confirmed classification.
  Reading criticality off the label is what V1 did; changing it here would move
  coverage numbers under a user who only asked for a register. What V2 adds is
  honesty about it — an unconfirmed classification is carried into the room's
  notes and reported as a pending validation everywhere it appears.
* A project whose migration has not run falls back to markers, so an old database
  still analyses.

Verified on the real database: V1 path and V2 path produce byte-identical
coverage — 2 873 spaces, 988 served, 1 885 uncovered, 21 434 ports, 23 serving
rooms, identical status histogram.

### 18. A suggested NER is a register row, not a position

The solver answers a geometric question. That is not the same question as "where
can a NER go", which needs a real room, power, cooling, access, a riser and
someone's signature. `ner_suggest.promote()` writes new sites into the register
with `status = suggested`, `position_source = suggested`, and a bundle answering
what §5 asks: why, which areas, total demand, longest serving distance, how many
areas were out of coverage before and after, constraints found, what still needs
validating, and whether it depends on the TVDB. Suggestions are excluded from the
As-Is analysis until a human confirms them, and re-running the solver updates a
suggestion it recognises instead of stacking duplicates — but never touches one
someone has already answered.

### 19. Removal is a status, deletion is not available

`soft_delete` requires a reason and sets `deleted_at`; the row and its whole
history stay. A consolidated room keeps its row too, pointing at the room it
became, and the survivor keeps the merged room's **code** in its aliases — two
rows can share a display name, and the code is the only thing that keeps the old
row's reports traceable afterwards.

Deleting the last marker of a room is the one path that can empty a register
entry. It marks the room removed with a stated cause rather than leaving a NER
nothing supports, and it still does not delete the row.

---

## 2026-09-02 — Cutting the application back

Marcelo walked the whole application screen by screen and asked for it to be
simplified. The single decision underneath most of what follows:

> **A new NER is drawn by hand, in the Drawing viewer, by somebody looking at
> the sheet.**

Three features were removed because they all did the opposite — they *proposed*
one:

* the CP-SAT **optimiser** and the As-Is vs Proposed screen;
* **Suggest NERs for uncovered areas** on the register;
* **Propose NERs from a VDB comments tracker**.

The optimiser did not work badly. What it optimised — distance on a plan — is a
fraction of what decides where an equipment room goes. Power, cooling, physical
space, security, access for the cabling, A/B independence and the continuity
plan are not in the model, so its answer was always a proposal somebody then had
to argue with using facts the tool cannot see. Presented as an *optimum*, it made
that argument harder rather than easier. The tool's job is to price a placement:
the distances, what falls outside the limits, what nothing reaches.

The tracker reader failed the same test from the other side. Five of the fourteen
VJJ proposals it read entered the register with **no position at all**, because
the space they named was not on the drawing yet. A room with no position never
reaches the coverage engine, which is the only thing this application can do with
it. The tracker is still where the requirement is written and argued with the VNI
team; when it is agreed, the room is drawn.

With no second scenario there is nothing to compare, so the scenario picker on
Reports went too. The `Scenario` table stays as the store of the last As-Is run —
it is what the reports and the new `Served by` column read back — and a scenario
written in the old optimiser shape now returns "nothing to draw" rather than
being silently redrawn as the live state.

### Thirteen columns, and where the evidence went

Columns were removed from five screens. The test applied to each was not "is this
true?" but **"does the answer change what the reader does?"**

On TEAP × drawing, `Method`, `Confidence` and `Reason` described how the matcher
arrived at its guess. The room is the right one or it is not, and that is read off
the drawing. Confidence in particular invited the wrong move: 90% looks like
agreement, and a base-code match at 90% is exactly the row that needs a human.

Nothing auditable was thrown away — it was moved to where it is audited:

| Removed from the screen | Still recorded in |
|---|---|
| method, score, confidence, reason | the **Matching** sheet of the workbook, and the audit log |
| the per-line port-demand rule | the `Rule` column on the workbook's first sheet |
| scale confirmed / match confirmed / needs validation | one `Needs validation` column, **on the row** |

That last one is deliberate. A row that reached a conclusion from an unconfirmed
scale or an unconfirmed match has to say so where the conclusion is, not in a
footnote at the end of the file.

### The workbook is now shaped like the TEAP

The old `Coverage` (one row per space) and `Demand detail` (one row per TEAP
line) sheets were two halves of one question, and reading them meant holding a
space key in your head while moving between them. They are one sheet: the TEAP as
it arrived — every space, every service, every port — with **Serving NER**,
**NER critical** and **Distance** added on the right. That is the whole thing the
application exists to answer, and it now reads across a single row.

### The legend has three rows

Eleven rows described states the plan in front of the reader does not contain — a
proposed NER on a sheet with no proposals, a redundancy candidate on a study that
never ran the optimiser. A legend that names shapes the reader cannot find is not
a key, and this box is 320 pt wide, so every unnecessary row was drawing it
covered. What is left is what a marker can be: TER, NER critical, NER
non-critical.

### The server is watched now, and the watchdog is also the witness

**2 September 2026.** The server disappeared mid-session. `data/server.log` ends
on a served request — no traceback, no `===== stopped =====` line, no Windows
Error Reporting entry for `pythonw.exe`, no SentinelOne or Defender event, no
reboot, no sleep. Nothing was watching it either: the logon scheduled task fires
once at logon, and its `RestartCount` covers a task that fails to *start*, not a
process that dies four hours later.

The signature — killed from outside, silent — is the **same** one as 28 August,
when the Windows memory manager killed it at 97% commit charge during a solver
run. A process killed for memory does not get to write anything, which is
precisely why the log cannot settle it. Commit charge measured 68% an hour after
the event, so the memory explanation is *consistent* with the evidence but not
proven by it, and it is not being written down as the cause.

Two things follow, and only the second is a diagnosis:

**`tools/watchdog.ps1`**, on a scheduled task every two minutes, probes
`/api/auth/state` and restarts the server if it does not answer. It probes twice
before acting — a timeout during a heavy export is not a dead server, and
restarting mid-export would lose the run — and never restarts a server that is
answering. Verified by killing the server twice on purpose: back up in under two
minutes both times.

**Before restarting, it writes the evidence** to `data/watchdog.log`: physical
memory free, commit charge used, the five largest processes, the last line of
`server.log`, and whether that line was a shutdown. The cause of this one stays
unknown; the next one will not, because the state at the moment of the fall is
recorded instead of reconstructed an hour later. That is the whole point of
logging it there rather than guessing here.

**`tools/server-stop.cmd` no longer kills every Python on the machine.** It was
`taskkill /IM pythonw.exe /F`, which is a blanket instruction aimed at whatever
happens to be running — there were two windowless Pythons on this box today. It
matches on the command line now and stops only this folder's `serve.py`.

`Register-ScheduledTask` answers *Access is denied* on this managed machine, so
the installer uses `schtasks.exe`, which the same user is allowed to run.

**The watchdog runs through a `.vbs`, and that is not decoration.** Marcelo saw
it within minutes: *"fica pulando aqui uma tela de comand"*. `powershell.exe
-WindowStyle Hidden` does **not** prevent a console window — Windows creates the
console and the switch only hides it afterwards — so the task fired a black box
onto his screen every two minutes. `wscript.exe //B` running
`tools/watchdog-hidden.vbs`, which shells PowerShell with window style 0, never
creates one. A background job that interrupts the work it is protecting is worse
than no background job.

It also writes `data/watchdog-heartbeat.txt` now: one line, overwritten each run,
with the time and the verdict. `watchdog.log` only records failures, so without
a heartbeat a watchdog that had quietly stopped running would look exactly like
one that had nothing to do.

## 2026-09-03 — The second screen-by-screen pass

Marcelo walked the application again, screen by screen, in writing this time.
Projects, Import, Exceptions and Reports were "ok". The rest changed.

### Scale — one button for the book, beside the row buttons

`Confirm all pages (n)` confirms every page that already holds a scale
(detected or typed) in one act. A 75-page book was 75 identical clicks. A page
with **no** scale is skipped and named in the notice — the honest thing to do
with it is to keep blocking its results until somebody types the ratio in the
row, so the per-page controls stay. `POST /pages/scale/confirm-all`.

### Drawing viewer — DIVA node in, calibrate and zones out

A **DIVA node** is the fourth visual-only kind, beside TER, IDF and COW: read
off the VDB on import (`DIVA Node`, `DIVA NODE`, `DIVA Node Rack` — the word
*Rack* had to be part of the kind, not a qualifier, or one venue's book would
have needed a dash it does not print), placed by hand with `+DIVA`, drawn in
purple (his choice; the proposal colour was free), never a register row, never
served from, no reach circle. `VISUAL_ONLY_KINDS` names the four in one place.

`calibrate` and the three zone tools are gone at his request ("não preciso
criar áreas"). The Scale screen takes a ratio or a scale text per page, which is
what the two-point calibration was being used for; the endpoints stay on the
server. The trade-off is written in the manual: a sheet with no printed scale
*and* no known ratio now has to be read off its title block.

The inspector gained `Name`, `Kind` and `Delete`, because the "On the drawing"
tab that used to carry them for every marker is gone (below). Changing a NER's
kind to a visual-only kind retires its register row with the reason on it;
changing a visual-only marker to a NER kind creates the row at once.

### The exporter now draws every marker kind, and the legend names them

Before today the marked-up PDF drew only the register — NERs — while its legend
listed TER. A TER read off the sheet was on the screen and missing from the
paper. `services.markers_to_draw` adds the visual-only markers to the export,
and both legends (`notation.ts`, `reports.py`) went from four rows to seven:
TER, NER critical, NER non critical, IDF / MDF, COW / temporary, DIVA node,
Match not confirmed. The 2 Sep rule holds — a legend names what the sheet
shows — it is the sheet that now shows more.

### NERs — two tabs became one list

"O que eu herdei ou desenhei segue o mesmo princípio." The "On the drawing" and
"Register" tabs are one table, one row per NER, with an `Origin` flag (from the
drawing / drawn by you) as the only remaining difference. Three consequences
that reach the data:

- **One name.** `ner_register.rename` relabels every marker of the room, and
  `PATCH /elements/{id}` with a `label` renames the room. The printed label
  survives as `suggested_name`, as an alias and in the name history.
- **Choosing the criticality confirms it, and repaints the marker.** The old
  Register select sent `confirmed: … && r.classification_confirmed`, i.e.
  never confirmed a row that was not already confirmed — so a criticality
  changed on an unconfirmed row never reached `asset.kind`, and the engine
  (which reads the kind) went on serving from the drawing's reading. Now
  `classify(confirmed=True)` sets the kind and the occurrences' kinds.
- **Confirm is one tick with one meaning:** criticality confirmed *and* every
  marker of the room confirmed (`is_confirmed`). `POST /ners/{id}/confirm`;
  `POST /ners/bulk` for lock / unlock / confirm / unconfirm all, one audit row
  per room, a pending criticality skipped and named rather than forced.

Delete is a soft delete with a reason; `list_elements` now hides the markers of
a removed room so the viewer stops drawing what the study no longer contains,
and `Removed (n) → Restore` brings everything back. The marker evidence is
behind `Details`, per marker. Change requests (register snapshots) are gone
from the screen; the endpoints stay.

### TEAP × drawing — verified, then corrected

He reported that every `Run matching` lost his edits. Verified on a copy of
his real database: three projects, 154 decisions, **zero** rows changed by a
re-run — `record_match_decision` writes the decision on the TEAP line and the
run reads it back, exactly as designed on 1 Sep. What *was* wrong was the
message: "30 need review" after a run on a project whose thirty rows had all
been confirmed, because `report.stats()` counts before the decisions are laid
back over the matcher's answer. The stats are now counted afterwards
(`matched`, `confirmed`, `needs_review`, `match_rate`; the raw figure kept as
`matcher_needs_review`), pinned by a test. A message that repeats the
pre-decision count after every run reads as data loss.

`Remember` (cross-venue alias rules) and `Confirm all {method}` are gone from
the screen at his request — "nem toda venue é igual", and "é arriscado assumir
que um nome próximo seja o local correto". Backend endpoints untouched.

### Demand per space — the serving-room rule, and one screen

Coverage analysis folded into Demand per space (8 steps now). The rule, in
his order: the TEAP's own column → his choice → nearest NER within the limit
with free ports → the next nearest if the nearest is full → **the nearest
anyway, flagged, if every room within reach is full** → nothing, if nothing is
within the limit, but the row names the nearest room and its distance.

The engine change is the capacity fallback: until today a space whose
in-reach rooms were all full got no room at all, which hid the demand from
the port load of the very room that will carry it. It now gets the nearest
in-reach room with status `insufficient_capacity`, the ports counted (the
utilisation goes past 100 %), and an exception row. Criticality is not relaxed
the same way. Out-of-limit stays unassigned — a cable that cannot reach
carries no ports — with `nearest_label` / `nearest_distance_m` on the
assignment so the screen can say so instead of printing a dash.

The TEAP column: `serving_ner` is an optional canonical field. The TEAP
v2.0 has no such column (checked); when one exists the name is resolved to a
live NER through `normalise_label` (so `NER 03` finds `NER 3`, and an earlier
name still finds a renamed room), becomes a pin with source "the TEAP", and a
person's choice still outranks it. Unresolved names are shown on the row, never
silently dropped.
