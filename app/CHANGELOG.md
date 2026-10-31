# Changelog — NER Spatial Coverage Analyzer

Every release of the application is numbered, and the number follows
**semantic versioning**: `MAJOR.MINOR.PATCH`, starting at **2.0.0**.

| Part | Bump it when | Example |
|---|---|---|
| **PATCH** | a correction that changes no screen and no file shape — a bug fix, a wording fix, a performance fix | 2.0.0 → 2.0.1 |
| **MINOR** | something new that keeps every existing project, export and workflow valid — a new column, a new switch, a new report | 2.0.1 → 2.1.0 |
| **MAJOR** | a change an existing installation cannot absorb silently — a database that must be re-imported, an export whose columns change shape, a screen removed | 2.1.0 → 3.0.0 |

The number lives in **one file**, `VERSION`, at the root of the project.
The API (`/healthz`, `/api/meta`, `/api/auth/state`), the interface, the
workbook's *Summary* sheet, the marked-up PDF's footnote and the package file
name all read it from there.

## Releasing a version

1. Edit `VERSION`.
2. Edit `"version"` in `frontend/package.json` to the same number.
3. Add an entry at the top of this file, newest first, dated.
4. Rebuild the interface: `cd frontend && npm run build`.
5. Put the same number in the mastheads of `docs/MANUAL.html`,
   `docs/INSTALL.html` and `docs/HISTORY.html`, record the change in
   `docs/HISTORY.html`, and re-render the PDFs (`tools/render_docs.py`).
   The three are in English only since 2.13.1.
6. Run the tests — `tests/test_version.py` refuses a mismatch between the
   places above, and refuses a manual that carries the wrong number or any
   change history; `tests/test_installer.py` holds the scripts and the
   packager to the bundled-runtime layout.
7. Build the packages: `build_package.bat` → `dist\ner-analyzer-<version>-windows.zip`;
   `python tools/make_package.py --platform mac` → `dist/ner-analyzer-<version>-macos-arm64.zip`.

The manual (`docs/MANUAL.html`) describes the application as it is and carries
no history; this file is where the history lives from 2.0.0 on. Everything
before that — 26 August to 10 September 2026: what came in, what went out
and why, the defects found and fixed, the decisions — is recorded in
`docs/HISTORY.html`. The previous manual with its dated revision notes is
archived under `docs/history/`, which is private and left out of a public
package.

---

## 5.1.1 — 2026-10-31

PATCH: what the complementary QA of 5.1.0 found (31 Oct 2026). No screen and no file
shape changes; the first start writes one more pass (below).

- **D34 (medium) - a drawing taken off a sheet came back by its code.** *Place NERs
  from the drawing* draws a NER whose TEC code it reads on another sheet there too.
  5.1.0 held only the spot a drawing was taken from (12 m), so the same code printed
  elsewhere on that sheet drew the NER back; and a drawing deleted with *Delete only
  this marker* before 5.1.0 had no spot at all - on an aquatics project the NER deleted
  by hand on two sheets of the 600 series on 20 Oct was drawn back on both. Now a NER
  is never drawn back by its code on a sheet its drawing was taken off. A start-up pass
  (`released_sheets_511`) reads the old *Delete only this marker* lines of the audit log
  and keeps those sheets whole on the NER - only where exactly one NER carries the name,
  it existed then and it is not drawn on that sheet now; running it again changes
  nothing. Held by `tests/test_qa_fixes_511.py`.
- **D32 (low) - the refusal to move a NER drawn twice on one sheet.** The notice said
  the sheets disagree and advised leaving a sheet off the map; it now says the NER is
  drawn twice on that sheet and to delete the extra marker with *Delete only this
  marker*. Nothing else changes: the move is still refused and nothing is written.
- **D33 (low, tests) - the 5.1.0 tests depended on their order.** Four D25 tests shared
  one project and the Undo test put the drawing back for the ones after it. Each test
  now has its own project; the file passes in any order.

## 5.1.0 — 2026-10-31

MINOR: the defects the QA pass of 5.0.0 found (31 Oct 2026, D25—D31), every one
reproduced on a copy of the work laptop's sixteen projects and held by a test in
`tests/test_qa_fixes_510.py` that fails on 5.0.0. Screens and the composite map PDF
change; the database gains one column (`ner_assets.released_spots`), added on the
first start.

- **D25 (high) - a drawing taken off a sheet came back as a new NER.** A move on the
  composite map that left a sheet, or *Delete only this marker*, deleted the marker
  and with it the only record that the room the sheet prints there is that NER. The
  next *Place NERs from the drawing* created a new NER on it (NER_38.1 and NER_43.1
  on a port project and an arena project, 0.0 m from where NER_21.1 and NER_35.1 had been drawn), or,
  for a room with a TEC code, drew the NER back on the sheet it was taken off
  (a stadium project). The NER now keeps those spots (`released_spots`, both where the
  marker was and where it was first put); *Place NERs* takes a room or a team
  annotation read there as that NER: nothing created, nothing drawn back; a removed
  NER's spots keep it removed. Undo forgets the spot it puts a drawing back on. On
  the first start, the spots of the moves still in force are read back from the audit
  log, and a NER *Place NERs* created on such a spot afterwards gets a validation
  naming the other NER - nothing is removed or consolidated. A marker deleted with
  *Delete only this marker* before 5.1.0 cannot be read back: its audit line has no
  position (13 such lines on the work laptop; no NER was created on any of them).
- **D26 (medium) - the confirm of a move said nothing of how far.** An 80-pixel drag
  at the zoom that fits the level moved a NER about 170 m onto another sheet. The
  window now asks the server first (`move-ner` with `preview: true`, nothing
  changed) and the question gives the distance in metres and the sheets the NER
  moves on, is taken off and is drawn on; the result of a move carries `distance_m`.
- **D27 (medium) - the PDF printed a contradicted sheet like a not-confirmed one.**
  Each state now has the window's colour, a line pattern of its own and, when not
  confirmed, its name beside the sheet number: confirmed blue dashed, not confirmed
  orange dotted + NOT CONFIRMED, contradicted thicker red dash-dot + CONTRADICTED;
  the heading counts the three.
- **D28 (low) - the PDF legend left out what the page draws.** It now lists TER,
  IDF, COW and DIVA and the three sheet states.
- **D29 (high) - a small drag collapsed a NER whose sheets disagree.** The window
  draws such a NER at the middle of its drawings; dropping it 0.5 m away moved one
  drawing 38.9 m on its own confirmed sheet and took the other off (NER_29.1,
  77 m apart), or took both off (NERc_10.1, 353 m apart), and the finding that
  showed the disagreement was gone (a golf project). A NER drawn more than 1 m apart on the map is
  now refused, with the sheets named.
- **D30 (low) - tiles asked at once composed the missing picture once each.** Six
  copies of one map's picture on the work laptop, five never referenced (about
  38 MB). The row is read again inside the lock. Copies already made are left where
  they are.
- **D31 (medium) - Undo could give a NER two drawings on one sheet** when it had been
  drawn there again after the move (NER_21.1 and NER_35.1 on a stadium project). A drawing
  is not put back where the NER is drawn again; the result names the sheet.
- **Manual (M1, M2, M3).** "The map changes no number" replaced by what a move
  changes; the released spot and the refusal described; the PDF states spelled out.

## 5.0.0 — 2026-10-30

MAJOR, by Marcelo's call: the composite map, a new way of working on a level.
Every project, export and workflow of 4.8.1 stays valid; the database gains
one table (`composite_maps`), created on the first start. Installed on his
computer only, for testing, before it goes anywhere else.

Marcelo, 30 Oct 2026: lay the detail sheets of one level of a book on one
map — never two series, never the key plan — as an option generated when he
decides, in a window of its own and not in the Drawing viewer, carrying
everything already worked on the sheets; on it, move, delete and reclassify
NERs; print it as one PDF beside the marked-up one. The feasibility test the
same day, on the sixteen 400 books of the work laptop, placed 28 of 34
multi-sheet levels automatically, at 0.05 to 0.3 m on the seams.

- **Placing the sheets** (`domain/composite.py`): one group per level by the
  drawing-number prefix (`412` in `VVV-412A1-XXX-OP`), else the title-block
  level; two independent measurements per sheet — the match lines against the
  key plan's grid, and the sheet's linework correlated with the key plan
  around its label — with the correlation kept when they disagree by more
  than 2 m; then a neighbour check that compares every overlapping pair within
  4 m of where it was put, corrects a few metres at most and never relocates a
  sheet. A wider search was tried first and dragged good sheets 7 to 11 m on
  the test book. Each sheet says how sure it is: confirmed, not confirmed,
  contradicted (two shared space codes that do not line up) or not placed.
- **Building** (`composite_service.py`, `POST /projects/{id}/composite/build`):
  a job, in the child interpreter like the book reader; one picture (vector
  PDF) per level under `data\composite\project_<id>\`; a sheet left off stays
  off when the map is built again. Not in a backup, not in a project package:
  it is derived from the book and built again on demand.
- **The map window** (`?composite=<project>&map=<id>`): tiles cut by the
  server and cached on disk; NERs with the general and photographer reach
  circles, Wi-Fi points, TER/IDF/COW/DIVA markers, sheet outlines by state,
  space codes on demand; findings (a NER whose drawings land more than 1 m
  apart, two NERs less than 2 m apart, a NER only on sheets left off); the
  sheet list with Leave off / Put back; a sheet or a NER opened in the Drawing
  viewer of the main window.
- **Deciding on the map**: dragging a NER moves its marker on every sheet of
  the level that shows the new spot, takes it off the sheets that no longer
  show it, draws it on the sheet that does when none of its sheets shows the
  spot, and keeps the register's position on the right sheet; audited as
  `ner.moved` / `element.deleted` / `element.created` under one
  `composite.ner_moved`, which **Undo** reverses while nothing else touched
  the NER. Delete and Make critical / non critical use the Drawing viewer's
  own requests.
- **Composite map PDF** on the Reports screen: one page per map, the legend
  on the first page only, scaled to 200 inches when larger.
- A level drawn on one sheet gets no map (nothing to lay out). Where sheets
  overlap, the surest are drawn on top, so a misplaced sheet never hides a
  placed one.
- Building, leaving a sheet off and deleting a map are neutral to the
  analysis; a move on the map is not.
- QA before installing, on a copy of the work laptop's projects (the sixteen
  400 books, 34 levels of more than one sheet, 422 sheets): 325 sheets
  confirmed, 62 not confirmed, 32 contradicted, 3 not placed; 20 levels with
  80 % or more confirmed and none contradicted, 9 with half or more, 5 to be
  checked sheet by sheet. The findings named 5 pairs of NERs under two names
  less than 0.15 m apart and 22 NERs whose drawings on two sheets land 1 to
  350 m apart. A book takes 20 s to 4 min to build.
- Tests: `tests/test_composite_map_500.py` (20) on an invented book whose true
  layout is known (`tests/composite_book.py`), flat and rotated, with and
  without match lines, with an irregular grid.

## 4.8.1 — 2026-10-28

PATCH: what the replay of the QA scripts on a copy of the work laptop's
fourteen projects found in 4.8.0, the same day, before 4.8.0 left the work
laptop.

- **Wi-Fi name tags no longer touch.** 4.8.0 placed the points of one room
  side by side but kept the 32 pt pitch chosen in 2.19.0 for the short `AP-n`
  tags; the `WIFI-n` tag at 9 pt bold is 37 pt wide with its frame (43 pt from
  `WIFI-100`), so on VBB 400 page 15 the tags `WIFI-37` to `WIFI-40` ran into
  each other on the marked-up PDF. The pitch is now 48 pt across and 28 pt
  down (`TEAP_AP_STEP`); `tests/test_wifi_tags_481.py` draws the tag boxes the
  way the PDF does and checks every neighbour pair up to `WIFI-999`.
- **Wi-Fi points deleted before 4.8.0.** 4.8.0 records the space of a Wi-Fi
  point when it is deleted, so *Place Wi-Fi from the TEAP* leaves it out; a
  point deleted with an earlier version left no space behind (its audit line
  holds the name and the sheet only), so the first run after the update puts
  it back. On the copy of the work laptop's projects a run placed 8 points on
  VKK (where 6 had been deleted by hand on 27 Oct) and 1 on VBB (deleted on
  28 Oct). The manual now says so: the names are in the notice, and deleting
  them once more is final.

## 4.8.0 — 2026-10-28

MINOR: the findings of the QA pass of 28 Oct 2026 on 4.7.0, the browser stall
after *Run matching*, and a rule Marcelo set the same day — a Wi-Fi point a
person deleted stays deleted. Every project, export and workflow stays valid.
The database gains three columns, added on the first start (`elements.origin_x`,
`elements.origin_y`, `projects.wifi_declined`).

- **Place NERs from the drawing no longer creates a room a second time after
  its NER was dragged away (A1, high).** Every marker now keeps where it was
  first put — the room the drawing prints, for a NER read off the book — and
  the "is there a NER here already?" test asks both that spot and where the
  marker is now. On the VKK project a NER dragged 16.5 m from a bare
  `TEC.010` came back as a new critical NER at the `TEC.010` on the next run,
  and nothing flagged it. The first start fills the spot of existing markers
  from the move history in the audit log (a marker never moved: where it is).
- **Wi-Fi points side by side, and a button for those already stacked (A2,
  high).** Several TEAP lines tied to one room each got their point at the
  same spot beside the label — 290 of 639 points on the work laptop sat on
  another one, unreadable on the marked-up PDF and out of reach in the viewer.
  *Place Wi-Fi from the TEAP* now puts them in rows of four, skipping any slot
  a Wi-Fi point holds. The Scale screen counts the points that sit on top of
  each other and **`Spread stacked Wi-Fi points`** (new
  `GET /projects/{id}/wireless/stacked`, `POST /projects/{id}/wireless/spread`)
  keeps the oldest of each stack in place and moves the others beside it,
  each keeping its space, its NER and indoor/outdoor; audited as
  `wireless.spread`.
- **A deleted Wi-Fi point stays deleted.** Deleting a point tied to a TEAP
  space puts the space on the project's list (`projects.wifi_declined`, by
  space key, so it survives a new TEAP); *Place Wi-Fi from the TEAP* leaves it
  without a point and counts it in the notice (`deleted_by_you`). Drawing a
  point for the space with `+Wi-Fi`, or tying one to it, takes it off the
  list. The deletion is audited with the space. Points deleted before 4.8.0
  carry no space in the log and are not on the list.
- **Exporting a package no longer makes the analysis "changed since the last
  run" (M1, medium).** `project.exported` and `project.imported` are neutral.
  The package now records when the analysis was last *run*, not when the
  scenario was first saved, so the import compares the two runs and quotes
  the right date.
- **Labels on sheets larger than 14,400 pt (M2, medium).** Such a sheet carries
  `/UserUnit` (the VBB 700 series, 17,144 × 11,092 pt). PyMuPDF places what it
  draws by that unit but not the text it inserts, so the marked-up PDF lost
  every label of the app there — empty Wi-Fi tags, no footnote. Text positions
  are now divided by the unit, as the drawing's are.
- **TEAP × drawing: no more stall after Run matching (R1).** Every row held a
  select with every room of the drawing — some 100,000 options on the larger
  venues, built at once each time the list came back. A row now holds only
  its own room until the pointer reaches the select (or the keyboard focuses
  it); choosing a room, Confirm and Undo reload the rows, not the rooms.
- **Notices float over the page (B1).** The notice no longer pushes the screen
  down: in the Drawing viewer it moved the sheet 45 px under the pointer, and
  a click made just then could land on another marker. A click closes it.
- **The next name offered skips former names (B2).** A live NER's earlier
  names (rename history) count as taken: VBB offered `NER_34.1` and
  `NERc_11.1`, both former names of `NERc_10.1`.
- **What the screens never send is refused by the API (B3):** an unknown
  marker kind, a position that is not a number or lies far off the sheet, a
  name longer than 120 characters, a NER with no name, a
  project name over 200 characters or a venue code over 40, a display unit
  other than m / ft / both, a photographer limit longer than the general one.
  Restoring a NER that does not exist answers 404.
- **Reads off the event loop (B4).** A book or a TEAP workbook sent without
  `background=true`, and a package imported the same way, were read inside
  the request and held every other request (58 s measured); they now run in
  a worker thread. The screens already used background jobs.
- **The test run cleans up after itself (B5).** `tests/conftest.py` removes the
  data folders the run made: each `run-tests.bat` left about 36 `ner-*`
  folders in `%TEMP%` (413, 195 MB, on the work laptop).
- **Audit (B6).** `route.deleted` names the sheet as `route.created` does; a
  deleted Wi-Fi point is logged with `scope: marker`, its kind and its space.
- **`NER_DATA_DIR` moves the database too (B7)**, unless `NER_DATABASE_URL`
  says otherwise; it used to move the uploads and leave the database behind.
- Tests: `tests/test_qa_fixes_480.py` (24).

## 4.7.0 — 2026-10-27

MINOR: a ruler in the Drawing viewer, the route tool made usable, and the
viewer's analysis made the project's analysis. Every project, export and
workflow stays valid; routes traced before 4.7.0 keep working.

- **`measure`** — a new tool in the viewer's toolbox. Click each point,
  double-click (or Enter) to end: the length is read on the sheet's scale and
  shown in the project's units, live while drawing. Nothing is saved, used by
  the analysis or exported; measures stay on their sheet while you work and go
  with the eraser or *Clear measures*. Refused on a page with no scale; says
  *scale not confirmed* beside the figure on one whose scale is not confirmed.
- **`route`**, which saved one straight segment per two clicks and showed no
  length, now traces a path corner by corner and ends on a double-click or
  Enter (Backspace takes back a corner, Esc drops it), with the running length
  under the pointer. The path is saved as one route named `R1`, `R2`… (new
  `POST /projects/{id}/routes/path`), drawn with its name and length, selected
  whole in the Inspector (name, segments, length, how the analysis uses it),
  and erased whole (`DELETE …/routes/{id}?whole=true`). A corner placed near
  another route snaps onto it — its corner or anywhere along it — so routes
  join.
- **How the analysis uses routes.** A space or a NER joined the traced
  network only through a segment's *end* within 60 PDF units (about 4 m at
  1:200), so a space beside the middle of a corridor tray was measured in a
  straight line as if nothing had been traced, and two routes met only if their
  ends coincided to within 2 units. Now each end joins at the nearest point
  *along* a traced segment of its sheet within the larger of 60 units and
  15 m on the sheet's scale; a route ending on the middle of another (or a
  shaft's foot on a tray) splits it into a junction; the straight lead-ins are
  added, so a route is never shorter than the straight line; and the space's
  assumptions say how much was traced and how much is lead-in. Shortest paths
  are computed once per node per analysis.
- **`Coverage` became `Run analysis`.** It already ran and saved the same
  As-Is analysis as *Demand per space*, but the viewer never read the saved one
  back, so the colours and lines were empty on every visit until it was pressed
  again. The viewer now shows the last saved analysis from the moment it opens
  (new `GET /projects/{id}/analysis`), says under the button when it was run,
  and turns amber with *changed since the last run (n)* when something changed
  after it.
- **"Last run" on *Demand per space* was the first run.** It read the
  scenario's creation time, set once; every later run overwrote the result in
  place. It now reads the time of the last run — and carries its UTC offset:
  SQLite hands the time back without a zone, and the browser read it as local
  time.
- While a route, a measure or an area is being drawn, markers and routes no
  longer catch the click: a corner on a NER is the point of the click.
- No notice after a route is saved: the notice bar pushes the drawing down and
  back up six seconds later, under the pointer of someone tracing the next one.
- New tests: `tests/test_routes_measure_470.py` (19). The interface test now
  draws a measure, two joined routes and a route beside a space, runs the
  analysis from the viewer and reads the method and the lead-in on the space.

---

## 4.6.1 — 2026-10-27

PATCH: two screens that could not be drawn. No screen, file or workflow changes.

- **Import** (step 1) showed *This screen could not be drawn* — "Minified React
  error #310" — when a project was chosen after the application had opened
  without one; reloading the page put it right. The upload queue added in
  4.6.0 was declared below the screen's "no project yet" return, so the screen
  called one React hook more once a project was open than before, and React
  refuses that. **Scale** (step 2) had carried the same fault since 4.0.0,
  with the double-click guards of *Place NERs from the drawing* and *Place APs
  from the TEAP*. Every hook now comes before the early return.
- New test `tests/test_hooks_order_461.py` reads every component of the
  interface and refuses a hook after an early return; it is proved on the
  4.6.0 shape. The interface tests now also open the application with no
  project chosen and choose one, which is how the fault shows; until now they
  always started with a project already selected.

---

## 4.6.0 — 2026-10-27

MINOR: a project can be handed to another computer, several books can be
imported in one go, the same book is refused the second time and a book can be
taken out, and the pages on *Demand per space* open the Drawing viewer. Every
project, export and workflow stays valid.

- **The project package.** `Export` on the *Projects* screen writes the whole
  project into one `.zip` (`NER-project_<name>_<date-time>.zip`): the design
  books and TEAP workbooks as imported, and every row of the project — pages,
  scales, key plans, rooms, the NER list (removed rows included), TEAP spaces
  with the person's ties, rejections and chosen NERs, matches and their undo,
  same-space links, Wi-Fi points, areas, references, routes, shafts, rules,
  aliases, consolidations, register snapshots and the project's audit log —
  plus the column-mapping templates. *Import a project package* on the same
  screen brings it in as a **new** project owned by whoever imports it,
  private, with new ids; nothing existing is touched. Accounts, passwords,
  jobs and the saved analysis do not travel: the analysis is run again on
  import and compared with the exported one (*came out the same*, or why
  not). The package is checked before anything is written — only the files
  the manifest lists, each against its SHA-256, the data against its own
  hash, known tables and columns only, every value coerced to its column's
  type — and a package from a newer version is refused. All or nothing: a
  refused package leaves no project, row or file. Anyone who can read a
  project may export it (a reader of a shared project takes their own copy).
  Only the newest package of a project is kept in `data\exports`.
- **Several books at once.** The *Drawings* file input takes several PDFs;
  they are read one after the other, each to its end, with a list saying of
  each *imported* or *refused* and why.
- **The same book once.** A book is refused when the same file (SHA-256) is
  already in the project, whatever its name, or when a book with the same
  file name and other content is (a new revision: remove the old one first).
  Checked when the file arrives and again before it is written, so two copies
  chosen together cannot both come in. A project that already holds the same
  file twice shows *same file as …* under the second copy.
- **Remove a book.** `Remove` on each row of the *Drawings* table, after a
  count of what goes with it. Its pages, rooms, markers, Wi-Fi points, areas,
  routes, shafts and the stored PDF go; a NER also drawn on another book stays
  and is placed there; a NER drawn only on that book leaves the list, removed
  with the reason; the person's ties to its rooms are released (counted in the
  answer and the audit log); the matching runs again. Refused while a task of
  the project is running.
- **Page buttons on Demand per space.** The page under each space, the pages
  of the same space on other sheets, the `Page` of each Wi-Fi point and of
  each NER under *NER load and capacity* open the Drawing viewer on that
  sheet, centred on the room, as on *TEAP × drawing*.
- A background task that fails with a message written for a person (a refused
  book, a refused package) shows the message as written, without the
  `ValidationError:` prefix.
- API: `POST /projects/{id}/export`, `GET /projects/{id}/export/{file}`,
  `POST /projects/import`, `DELETE /projects/{id}/drawings/{did}`,
  `GET /projects/{id}/drawings/{did}/impact`; `POST /projects/{id}/drawings`
  answers 409 for a book already in the project. New module `app/transfer.py`.
- Tests: `tests/test_project_transfer_460.py` (17) — the round trip of a
  worked project (same rows, same documents byte for byte, same analysis,
  owner and visibility), altered, newer, foreign and path-escaping packages,
  a reader's copy, duplicates, removing a book with NERs on two books.

## 4.5.0 — 2026-10-23

MINOR: each Wi-Fi point can be said to be **indoor** (a covered area) or
**outdoor** (an open area), the way a NER already can, so the LLD team knows
the setting each access point is proposed for. Every project stays valid: an
existing point starts as *not said*.

- **Indoor / outdoor on every Wi-Fi point.** A select in the *Wireless points*
  table of *Demand per space*, beside *Type* (sortable), and the same select in
  the viewer's Inspector under *TEAP space*: `Indoor`, `Outdoor` or
  `— not said —`. Said by a person, never read off the drawing; audited
  (`element.updated`). No re-run needed.
- **Workbook.** The *Wireless points* sheet has an `Indoor / outdoor` column
  beside `Type` (`indoor`, `outdoor`, blank = not said), read off the points
  when the file is exported, so a value set after the last analysis is in it.
  The columns after `Type` move one to the right — a filter or a formula
  someone keyed to a column letter on that sheet needs the new letter. The
  *Summary* gains three *Totals* lines: Wi-Fi points indoor / outdoor / not
  said.
- API: `PATCH /elements/{id}` takes `environment` (`indoor`, `outdoor`, `""`)
  for a wireless point and refuses it for any other marker (a NER's is the
  room's, on the NERs screen). Database: `elements.environment`, added on
  start.
- Tests: `tests/test_wifi_environment_450.py`; `test_wireless_tie_250.py` and
  `test_teap_ports_aps_400.py` follow the new column.

## 4.4.0 — 2026-10-22

MINOR: fewer clicks between screens, a worklist that puts the rows needing a
look first, and a Wi-Fi name that can be read on the exported PDF. No file
shape changes; every project, export and workflow stays valid.

- **The menu folds.** `«` at the top of the left-hand menu shrinks it to a
  rail of step numbers; `»` opens it again. Remembered per browser.
- **The viewer's legend folds** to a small `LEGEND ▴` tab (`hide ▾` on the
  legend). Remembered per browser.
- **Page numbers are buttons.** On *NERs* — the page pill, every *also on*
  sheet and every marker's page under *Details* — and in the *Page* column of
  *TEAP × drawing*: one click opens the *Drawing viewer* on that sheet, zoomed
  in on the NER or the room and ringed in orange.
- **`none` beside the room list** on *TEAP × drawing* sets `— none —` in one
  click (it sits at the top of a list of hundreds of rooms).
- **Confirm only where it is still a question.** A row already confirmed shows
  `✓ exact` (the matcher) or `✓ confirmed` (you) instead of the button, and the
  worklist lists the rows that still need a look first, the settled ones after
  (dimmed), each group largest demand first.
- **An identical name is an exact match** when the TEAP line carries no space
  code and only one room on the drawing answers to it: the matcher confirms it
  like an exact code (`EXACT_NAME_NO_CODE_CONFIDENCE` = 0.97). A line with a
  code the drawing does not print, and a name two rooms answer to, still wait
  for a person. Takes effect at the next *Run matching*; decisions are kept.
- **Wi-Fi name on the marked-up PDF**: 9 pt bold (the NERs' size, was 6.5 pt),
  dark blue on a white tag under a slightly larger sign (16, was 14). The team
  reported the old cyan name on the linework as small and unreadable.
- Tests: `tests/test_workflow_shortcuts_440.py` (12);
  `test_sheet_labels_423.py` follows the page buttons.

## 4.3.0 — 2026-10-19

MINOR: Wi-Fi points instead of access points, the legend on the first page
only, and the application becomes free software.

**Wi-Fi, not AP.** A reviewer counted the access-point symbols on a marked-up
PDF and read them as the number of access points requested. The symbols were
never that: they were drawn one per unit of the TEAP's wireless line, and only
in the spaces found on the drawings. They now say what they mean.
- *Place Wi-Fi from the TEAP* (was *Place APs from the TEAP*) draws **one**
  Wi-Fi point per TEAP space with a wireless (DWISA) line whose room is on a
  drawing, whatever the quantity. The quantity stays on the TEAP line, and in
  the workbook, as the space's wireless ports; the number of access points
  comes from the wireless design. Ports are unchanged: since 4.0.0 a drawn
  point carries none.
- Points are labelled `WIFI-n` (were `AP-n`); the viewer's tool is `+Wi-Fi`;
  the legend row reads *Wi-Fi - space with wireless*; the *Wireless points*
  sheet's `Type` reads `Wi-Fi`; the Summary line reads *Wi-Fi points drawn
  (one per space; not an AP count)*.
- On the first start a pass renames every `AP-n` to `WIFI-n` (same number)
  and, in a space holding several points placed from the TEAP, keeps the
  oldest and takes the rest back. A point drawn or tied by hand is never
  removed. Audited as `wireless.wifi_points`.

**The legend on the first page only.** The legend box sat over the plan on
every sheet. It is now drawn on the first page of the marked-up PDF (the
first book's first page when a project has several books); every other page
carries the short footnote — limits, scale, the disclaimer — and the line
*Legend: see the first page of this file.* Turning the legend off works as
before.

**Free software.** The application is now published under the GNU Affero
General Public License, version 3 (`LICENSE.txt`), with the author's credit
kept as an additional term of the licence (`NOTICE.txt`, section 7(b)). The
reason for the AGPL rather than a permissive licence: PyMuPDF, which reads
the drawings, is itself AGPL. `THIRD-PARTY-NOTICES.txt` lists every
component and its licence. The sign-in screen, the sidebar, the exports and
the manuals say so.
- A client's own reference material — the list of space names read from an
  accommodation matrix, a naming structure for network rooms — is no longer
  part of the source. It is read from `backend/app/reference_private/`, which
  git ignores and a public package leaves out; the application works without
  it (the project's TEAP names alone make the vocabulary, and the *Naming*
  panel shows the application's own naming rule). The panel now reads its
  table from `GET /api/reference/naming`.
- `tools/make_package.py --public` builds the edition that may be
  published, and refuses while any shipped text names an event, an
  organiser, a venue or an employer.
- Example text in the forms is generic: *Venue - VVV*, venue code *VVV*.

New tests: `tests/test_wifi_points_430.py`, `tests/test_public_edition_430.py`.

---

## 4.2.3 — 2026-10-17

PATCH: sheet numbers a person can read. In a project with several series the
NERs screen showed *also on 10012, 20004* — the internal sheet keys (book
number × 10000 + page) that the API returns by design and every screen is
meant to format as `400·12`. The *also on* line printed them raw, and so did
eight other places: the `Page` column of *TEAP × drawing*, the same-name
dialog on rename, the consolidation note, the viewer's notice after creating
a marker, the scale notice, and the three places that name a shaft's pages.
All nine now go through `sheetNo()`. The back end, the workbook and the CSV
were swept on a two-series project and carry no key in any text or cell.
One-book projects read exactly as before. New: `tests/test_sheet_labels_423.py`.

---

## 4.2.2 — 2026-10-17

PATCH: one test, nothing in the application. After installing 4.2.1 on the
work laptop, `run-tests.bat` failed on
`test_d17_a_ner_already_re_created_there_is_flagged_not_removed` — 3 runs in 8.
The cause was measured there: the laptop's clock moves in steps of about 1 ms,
and the test removed a NER and created the new one in the same millisecond, so
the removal was not "before" the creation and the flag did not fire. The
application's rule is right (on VCC the removal was on 8 Oct and the
re-creation on 16 Oct); the test now sets both dates, and also checks the
other side of the rule — a NER created before the removal is not flagged.
The manual's promise stands: every test passing means the installation is
sound.

---

## 4.2.1 — 2026-10-16

The QA pass on 4.2.0 (16 Oct 2026, night, on copies of the live data) found
eight defects (D17–D24), one of them high. PATCH: no screen gains anything, no
export changes shape. **Correction to 4.2.0's entry below:** "no removed room
comes back on any of the twelve projects" was not true — on VCC and
VGG five rooms removed on 8 Oct came back.

- **A NER removed before 2.18.1 stays removed (D17).** A room removed before
  its markers were kept, and with no TEC code, had nothing to hold its place:
  *Place NERs from the drawing* re-created it from its NER block symbol at the
  very spot (VCC: NER34, NER36, NER37, NER40 came back as NER_35.1–38.1; VGG:
  NER27 as NER_33.1). The position the NER list keeps for a removed room now
  holds it, within the 12 m same-place rule, for symbols, labels, codes (a
  different code is another room) and team annotations; a hidden marker is
  added so the next run finds it by marker and *Restore* brings it back there.
  At start, a live NER created by the drawing where a removed one stood is
  flagged *position: a removed NER stood here*, naming the room — nothing is
  removed for you.
- **A one-book project refuses a page its book does not have (D18).** 4.2.0
  refused it with several books only; a NER or a shaft could land on page 40
  of a 35-page book.
- **A PDF that opens with no page is refused (D19).** A truncated copy came in
  as a book of 0 pages and turned a one-book project into a multi-book one.
- **Restore keeps names unique (D20)**: refused while a live NER carries the
  name. **Two renames sent at once** can no longer both take one name (D22).
- **The start-up matching is audited as `system` (D21)**, not `user`.
- **Place NERs adds an evidence line once (D23)**, not again on every run.
- **Deleting a project is recorded (D24)** in the installation's log (account
  events): who, when, what it held. The project's own log still goes with it.
- Manual: a damaged or truncated PDF, the deletion record, Restore and names,
  removed rooms that had lost their markers.
- 990 tests (13 new in `test_qa_fixes_421.py`).

## 4.2.0 — 2026-10-16

The QA pass on 4.1.0 (16 Oct 2026, on the live installation) found sixteen
defects and ten places where the manual and the application disagreed. All
fixed. MINOR, not PATCH: two screens gain something (a pill on Demand per space
and Exceptions, a question when a NER is renamed to a name another NER has);
no export changes shape and no project has to be re-imported.

- **A removed NER stays removed (D1).** `Place NERs from the drawing` created a
  removed numbered room again when its code was printed on another sheet or
  another book (VBB: NERc_12.1, NERc_13.1, NER_35.1–37.1 came back). The
  new marker now joins the removed NER, hidden; `Restore` brings it back there
  too. And a NER block symbol inside a room the same run read by its code or
  label (within the 12 m same-place rule) is that room, not a second NER — the
  VBB symbols beside TEC.010-006 and TEC.010-021 were what came back as
  NER_35.1–37.1. Replayed on the 16 Oct backup: no removed room comes back on
  any of the twelve projects.
- **Codes with a three-digit sub-index are read whole (D2).**
  `PEM.003.000-003`, `PRS.007.001-004` were cut to `PEM.003` / `PRS.007`, and
  the cut code then matched the wrong TEAP line exactly (VBV.001 → Athlete
  Staging FOP; PRS.001 VMC, 68 ports → Photo Work Area). At start, once per
  book, every cut code stored is rebuilt from the name it was split from
  (audited `drawing.codes_repaired`); a match confirmed on the cut code goes
  back to the queue.
- **A restart no longer signs off the matcher's answers (D3).** Since 3.0 each
  start turned the matcher's own confirmations into decisions "by user" (22 on
  VBB on 14 Oct). Only a person's confirmation is adopted now, and the locks
  an earlier start made with no human decision in the audit log are released
  (audited `matching.matcher_locks_released`); the matching is run again.
- **Exports never come from a stale analysis (D4).** A NER deleted after the
  last run still came out on *NERs and ports* with its ports. Workbook, CSV and
  PDF run the analysis first when something changed after it (audited
  `report.analysis_refreshed`, and said in the notice); *Demand per space* and
  *Exceptions* show *changed since the last run (n)*.
- **The audit log names the person (D5).** The actor is taken from the
  session cookie on the server, never from the request body; start-up repairs
  are `system`.
- **Shafts between two books (D6).** The `vertical` tool asked for a page
  number, which a multi-book project refuses; it now takes `600 12`.
- **Deleting a project deletes its files, and ids are never reused (D7).**
  What 4.1.0 left behind (folders of deleted projects, uploads that failed or
  were cancelled) is moved at start to `data\set-aside\<time>\` with a note,
  never deleted: the owner of the machine decides (audited
  `uploads.orphans_set_aside`).
- **Two NERs cannot share a name (D8).** Renaming to another NER's name asks
  whether they are the same room and consolidates on OK; the API answers 409.
  Pairs already sharing a name carry a validation until resolved.
- **Smaller (D9–D15):** the open project reopens after F5; the viewer starts on
  a sheet the project has (no 404 on page 1 of a multi-book project); a file
  that is not a PDF gets a plain message and is not kept; blank and
  case-only-different project names are refused; a locked NER cannot be renamed
  through the API either; a page past the end of a book is refused; the import
  report's *decisions carried* counts decisions only.
- **An access point follows the NER of its space (D16).** It followed the NER
  nearest the point, so *Wireless points* and *of which wireless ports* on
  *NERs and ports* came out on different NERs (VBB: 57 vs 53). A point of a
  space with no NER waits with it.
- **Manual:** the ten divergences corrected (marked-up PDF holds every book;
  exports without an analysis; delete in one act; reload; audit; project
  delete; shaft sheet; second VDB version; `+NER` names; `Removed (n)`), and
  the `localhost` address for Edge in IE mode.
- 978 tests (23 new in `test_qa_fixes_420.py`).

## 4.1.0 — 2026-10-16

Several series of one venue design book in one project (300, 400, 600, 700 …).

- **A sheet is a book and a page.** New `app/sheets.py`: a *sheet key* names a
  sheet everywhere above the database — the page number itself in a one-book
  project (nothing changes there), `drawing_id × 10000 + page` with several.
  Every same-sheet comparison (coverage, distance, matching, the same-space
  links, the duplicate check, key plans, the APs placed from the TEAP, the
  canonical position of a NER) now compares sheets, not page numbers.
- **Drawing viewer**: pages through every book (`400 · Page 6 - VAA-411B3-VBV-O`)
  and opens the right PDF; a marker placed on a sheet is stored on that
  sheet's book (it went to the first book before).
- **Exports**: the marked-up PDF holds every book in upload order; the
  workbook and CSV name a sheet by its drawing number in a multi-book project.
- **Schema**: `zones.drawing_id`, `route_segments.drawing_id`,
  `vertical_links.lower_drawing_id` / `upper_drawing_id` (NULL = first book).
- **Level**: a bare three-digit figure is no longer read as the level of a
  sheet whose title block was read; one already stored is cleared at start,
  with the NERs that inherited it (audited `page.guessed_level_cleared`).
- Proved: every screen payload and workbook cell of the eleven one-book
  projects of the live database identical before and after; 955 tests.

## 4.0.0 — 2026-10-16

**MAJOR**, by the rule above: the workbook changes shape — the sheets come in
a new order, *Wireless points* loses its `Ports` column (and `Stands in for
(TEAP space)` is now `TEAP space`), and the port totals change meaning: an
access point no longer adds a port. Everything else keeps working: no
re-import, no database step by hand. An export drawn from a run saved by an
earlier version is counted the new way (the ports are read from the project,
the NER choices from the run); the Demand screen shows the new counts after
**Run analysis** on each project.

Marcelo, 16 Oct 2026, after another analysis found the VBB workbook
disagreeing with itself — 576 vs 519 ports on a NER, 842 vs 839 requested,
13/8/2 vs 14/9 indoor/outdoor: *"O NER tem que bater em todas as planilhas."*
And: *"AP não é um produto do TEAP. Mantenha somente a informação que já existe
que é o produto DWISA e o número de AP placed nos desenhos deveria seguir
rigorosamente esta qtde, e para os lugares não encontrados no VDB, não fazer
nada, mantendo-os como pending - no NER. Clicar duas vezes no botão place AP
ou Place NER não pode duplicar o que já foi feito."*

- **One set of numbers in every sheet.** *Coverage figures* was computed apart
  from the analysis (the raw TEAP total as requested, only spaces as "on a
  NER"), the *Summary* from the engine (TEAP − the DWISA lines with drawn
  access points + one port per point). Both now read the same run, and the
  *Summary* gains *Ports on no NER yet (pending)* and *of which wireless
  (DWISA)*: requested = on a NER + pending, on *Summary*, *Coverage figures*,
  *TEAP and coverage* (`Counted ports`), *TEAP by NER* (grand total and NER
  groups) and *NERs and ports* (`Ports assigned`).
- **The TEAP is the only source of ports.** The space's `DWISA` line counts on
  the space, on the NER that serves the space, whether or not its access
  points are drawn. A drawn access point takes no port: it is a position,
  measured to the NER of its space so the 90 m rule is checked where the AP
  is; one tied to no TEAP space counts nothing. *TEAP by NER* lists TEAP lines
  only — no `AP` rows; *NERs and ports* keeps `Wireless points` (APs the NER
  reaches, a count) and `of which wireless ports` (now the DWISA ports of the
  spaces it serves). This replaces the 2.5.0 rule ("five drawn + the TEAP's one
  = five"): a space that needs five APs says so in its DWISA quantity.
- **`Place APs from the TEAP` places exactly the DWISA quantity** of every
  matched space (`Qty`; the port count when there is none). Spaces with no room
  on the drawing get nothing and stay *Pending — no NER*. Running it again adds
  only what is missing and takes back extra points it placed itself (newest
  first) — a hand-drawn point is never removed, only reported.
- **A double click never places twice.** Both placing steps hold a lock per
  project on the server (a second press gets *already running for this
  project — wait for it to finish*, HTTP 409; a crashed job never blocks the
  button); the buttons also ignore a second click before the screen updates.
- **A saved run is counted the new way when exported.** A scenario keeps which
  NER serves which space; its ports are read from the project as it is now and
  each NER's load is summed again, so an export never mixes two countings.
- **Indoor / outdoor** counts the same rooms everywhere — the NERs of the last
  run, never a removed one; the `TOTAL` row of *NERs and ports* says
  *n indoor / m outdoor / k not said*, and *Coverage figures* carries the same
  three lines.
- **Sheet order and tabs** (his screenshot): *TEAP by NER* (red), *NERs and
  ports* (yellow), *Wireless points* (yellow), *Summary*, *TEAP and coverage*,
  *Matching*, *Match exceptions*, *Exceptions*, *TEAP spaces with no ports*,
  *Scales*, *Coverage figures* — no other tab coloured. The file opens on
  *TEAP by NER*, with only that tab selected (Excel would otherwise group two).
- **Forgot the password.** `Forgot your password?` on the sign-in screen says
  the two ways back in: an administrator's `Reset password`, or — with no
  administrator, or for the administrator — `reset-password.bat` (Windows) /
  `mac/reset-password.command` (macOS) in the installed folder: lists the
  accounts, asks for the new password twice, enables the account, signs out
  its sessions and writes `user.password_reset_on_this_computer` to the account
  events. Works with the app running. Both are in the packages (`REQUIRED`).
- Manual, installation guides and history updated; tests in
  `tests/test_teap_ports_aps_400.py`; older wireless and sheet-order tests
  rewritten for the new rule.

## 3.0.0 — 2026-10-14

**MAJOR**, by the rule above: the *NERs and ports* sheet changes shape —
columns move — so a formula or macro that reads it by column position must be
looked at. Everything else keeps working: no re-import, no database step by
hand; the start-up pass below runs by itself.

Marcelo, 14 Oct 2026, on the VAA export: a NER drawn on several sheets
came out in the wrong place on the marked-up PDF (*"A NERc_04.1 não aparece na
página 6 e na página 4 ela está errada"*); the notes written on the NERs screen
did not reach the workbook; a space whose room the tool had found, with a NER
measured on the same sheet, sat in Exceptions instead of being served; the
sheets in his order and colours; a Mac installer next to the Windows one.

- **A room drawn on several sheets is drawn where each sheet draws it.** The
  marked-up PDF drew every NER once, at its canonical point, and put that
  point's coordinates on the canonical page only. It now draws every marker of
  the room on its own sheet at its own position — circles, label and the lines
  to the spaces of that sheet included.
- **The cause of "the NER moved":** dragging a room's marker on *any* sheet
  copied that sheet's x/y into the room's canonical position while the
  canonical page stayed the same, so the room ended up at page 6's coordinates
  on page 4. Only the marker on the canonical sheet moves the canonical point
  now, and a **start-up pass** (`migrate.repair_canonical_positions`, every
  start, idempotent, audited `ner.canonical_repaired`) puts each room's stored
  point back on its own marker. On the VAA database: 3 rooms repaired
  (NERc_04.1, NERc_07.1, NERc_10.1).
- **Distances are measured from the marker on the space's own sheet.** The
  engine used the canonical point only; a space on page 8 served by a room
  drawn on pages 7 and 8 was measured from page 7 through the space's other
  label, or not at all. `NER.other_points` carries every marker; a room on the
  space's sheet is measured there (VAA SPP.002: NERc_10.1 at 3.8 m on its
  own sheet). Saved scenarios carry every marker; one saved before 3.0.0 is
  drawn where the markers are now.
- **A room the matcher found is served by the nearest NER before it is
  confirmed.** An unconfirmed match no longer blocks the verdict: the status
  is the distance's (served, near the limit, out of limit), the ports count on
  the NER, and the row leaves Exceptions. It is still marked — *room not
  confirmed* on the Demand row, a counter/filter *served — room not
  confirmed*, the orange box on the PDF, *Needs validation* in the workbook.
  `Status.MATCH_NOT_CONFIRMED` stays for runs stored earlier.
- **NERs and ports:** `NER`, **`Full name`** (B), **`Space code`** (C), then
  Page, Critical, Indoor / outdoor, Spaces served, Ports assigned, Total ports,
  Utilisation % (formula), Wireless points, of which wireless ports, Fibre runs
  to TER, and **`Notes`** last — the notes written on the NERs screen. The
  TOTAL row and the formulas follow the columns.
- **Space code on the NERs screen:** a new column, filled from the code the
  drawing prints beside the rack (`TEC.010-001`), editable; it is what goes to
  column C.
- **Sheet order and tab colours:** Summary, TEAP and coverage (yellow), TEAP
  by NER (red), NERs and ports (yellow), Wireless points (yellow), Exceptions
  (red), Matching, Match exceptions, TEAP spaces with no ports, Scales,
  Coverage figures.
- **macOS package** (`tools/make_package.py --platform mac` →
  `ner-analyzer-3.0.0-macos-arm64.zip`): Apple Silicon, macOS 11 or later, no
  administrator password. A standalone CPython 3.12.15 (python-build-standalone
  `20261009`, pinned by SHA-256) and the same pinned packages built for macOS
  (`requirements-lock-mac.txt` = the Windows pins), installed offline by
  `setup.command` into `~/Applications/ner-analyzer`; a per-user launch agent
  (`com.marcelobarbosa.ner-analyzer`) starts the server at sign-in and again if
  it stops; an update backs up, keeps `data/` and replaces the rest; the
  installation files are removed afterwards. `mac/` holds start, stop,
  backup, run-tests, autostart and uninstall. `run.py` finds the macOS runtime.

---

## 2.19.0 — 2026-10-14

**The access points the TEAP states, drawn where their rooms are** (Marcelo,
14 Oct 2026: *"desenhar nos VDB o AP (access point) nos espaços que já sabemos
que tem wifi, assim como fazemos com as NERs… só para facilitar os espaços que
já conhecemos"*). A new step; every existing project, export and workflow
stays valid.

- **`Place APs from the TEAP`** — a new card on the Scale screen, beside
  *NERs from the drawing* (`POST /projects/{id}/wireless/place-from-teap`).
  For every TEAP space that requests wireless (the `DWISA` line, or any line
  the importer reads as wireless) and whose room is on a drawing — matched by
  the matcher or tied by hand, not rejected — it places **one wireless point
  per wireless port**, beside the room's label (a little below and to the
  right, one step further right per extra point, in rows of four), numbered in the project's
  `AP-n` sequence and **tied to the space** (`tie_source` = `teap`,
  `origin` = `teap`, `detection_method` = `teap_wireless`). The tie is what
  keeps the count honest: a tied point stands in for the TEAP's wireless port
  (the 2.5.0 rule, *TEAP − 1 + points*), so the space's total does not change
  — the port only gets a position on the sheet, for the person to drag to
  where the access point really goes.
- Never on a key plan; a space that already has a tied wireless point —
  drawn by hand or by an earlier run — is left alone, so running it again only
  adds what is still missing. A space that requests wireless but has no room
  on the drawing is counted and named in the notice, not placed: tie its room
  on TEAP × drawing first. Audited as `wireless.placed_from_teap`.
- **A move never re-ties a TEAP-placed point** (an auto-tied point is
  re-proposed to the nearest room after a move; this one keeps the space it
  was placed for). The inspector says *placed from the TEAP* and explains the
  tie; `Stands in for (TEAP space)` still lets the person change or clear it
  (which makes it a manual tie, as before). The *Wireless points* table on
  Demand per space reads *from the TEAP* in the tie column.
- **Reference labels two points larger** (Marcelo, 14 Oct 2026). The name of a
  `*NER★`, `*NER`, `*TER`, `*COW` or `*DIVA` reference is drawn at 14 pt in
  the Drawing viewer (a room's stays at 12) and at 11 pt in the marked-up PDF
  (`REFERENCE_LABEL_SIZE`; a room's stays at 9): they are read from across a
  key plan.
- The `AP-n` label sequence is one function now (`services.next_wireless_label`),
  read by the viewer's `+AP` and by the new step alike.
- Ten new tests (`tests/test_wireless_from_teap_2190.py`).

---

## 2.18.1 — 2026-10-14

**Deleting a NER deletes it everywhere** (Marcelo, 13 Oct 2026: *"se eu uso a
opção delete de uma NR que aparece repetida em outras páginas, ela tem que ser
apagada de todas as páginas e ela tem que sumir da lista de NERs. Eu não posso
apagar do Drawing Viewer e ela continuar na lista"*; and a NER removed on the
NERs screen *"parece que ela volta"*). A correction; no screen moved.

- **The Drawing viewer's `Delete` on a NER marker removes the NER** — every
  marker of it on every page, the row in the NERs list, the analysis and the
  export — in one act, the way `Remove` on the NERs screen does. Until now
  `DELETE /elements/{id}` deleted that one marker and retired the NER only
  when it was the last one, so a room drawn on three sheets stayed on the
  other two and in the list. The dialog names the other pages; the reason
  recorded on the row names the page it was deleted from and the others.
  The markers stay in the database, hidden with their room, so `Restore`
  (NERs screen, *Show removed*) brings every page back without redrawing
  anything. Audited as `ner.removed`.
- **`Delete only this marker`** (inspector, shown when the NER is drawn on
  more than one page): the narrower act for a duplicate drawing of a room
  on one sheet — this marker goes, the NER stays on its other pages, and it
  is retired only when this was its last marker (`?scope=marker`; the
  previous behaviour).
- **A removed NER keeps its spot.** `_ner_marker_near` — the "is there a NER
  here already?" test of `Place NERs from the drawing` — skipped the markers
  of a removed room, so the pass read the team's annotation at the same
  point and created the room again under a new name. A removed room's
  marker now absorbs the annotation (`annotations_on_removed` in the
  pass's figures) and the drawn-rooms pass counts the same case
  (`on_removed_ner`); nothing is created there.
- **Same name, separate rows.** `Remove` on the NERs screen now says when
  other live rows carry the same name (two answers of "not the same NER",
  or two rows renamed alike), lists their codes and pages, and asks whether
  to remove them too — they are separate register rows and would otherwise
  stay on their pages. OK removes them; Cancel removes only the chosen row.
- **Installer: pip sees only the runtime.** On the work laptop a stray
  `%APPDATA%\Python\Python312\site-packages\pymupdf` (left by some
  `pip install --user`) made `install.bat`'s pip report pymupdf "already
  satisfied"; nothing was copied into `.python\`, and the server — which the
  `._pth` file does keep isolated — started with `ModuleNotFoundError:
  pymupdf`. pip now runs with `-s` and `--ignore-installed`, the component
  check with `-s`, `PYTHONNOUSERSITE=1` is set for the install, `run.py`
  passes it to uvicorn and `tools/serve.py` drops the user site-packages
  from `sys.path` before importing anything.
- Tests: 13 new in `tests/test_delete_everywhere_2181.py`;
  `test_tester_pass_281` (Restore redraws the marker) now exercises
  `scope=marker`, the act that erases the drawing.

---

## 2.18.0 — 2026-10-09

**The NER naming structure v2.0** (Marcelo, 9 Oct 2026, with *NER
Standardized Naming Structure - v2.0.xlsx*: *"veja se vale a pena uma
atualização. Cuidado para não deixar tudo mais lento de novo"*; then *"seguir
novo formato, mas não usar espaços e sim NERc_01.1, isso serve pra tudo"* and
*"leva o nome completo para o excel"*). Constants, a regular expression, one
workbook column and a static table — nothing in the extraction, the viewer or
the analysis changed.

- **Sequential names in the v2.0 form.** Every NER the app creates is
  `NERc_01.1`, `NERc_02.1` … (critical) / `NER_20.1`, `NER_21.1` …
  (non-critical): the sheet's `NERc 01.1` with an underscore in place of the
  space, the `.1` being the rack (a second rack beside it is `.2`, renamed by
  hand). **The non-critical series starts at 20** (`SEQUENCE_START`) — v2.0
  moved it from 21. `SEQUENTIAL_NAME_RX` reads the older forms the register
  holds (`NERc01`, `NERc 01`, `NER-21`) and the venue-prefixed ones
  (`VHH_NERc_01.1`) as the same series when it picks the next number. Nothing
  already named is renamed.
- **`Full name` on *NERs and ports*** (last column, L): the project's venue
  code in front of the NER name — `VHH_NERc_01.1` — as the sheet writes it
  (`VVV_NERc_02.1`; on a cluster each venue uses its own code). A name that
  already carries a code is not prefixed twice; a project with no venue code
  gets the name alone (`reports.ner_full_name`; `export_workbook(venue_code=)`).
  The other columns, the formulas and the TOTAL row are where they were.
- **The naming reference panel** (`NamingReference.tsx`) shows the v2.0 sheet:
  the fixed critical numbers 01.1–11.1 (09.1 Mixed Zones, 10.1 SPP Control,
  11.1 SPP Workroom are new), 12.1–19.1 for VTS to confirm, non-critical from
  20.1, the non-competition venues, and the sheet's principles (one name per
  rack, the venue prefix, clusters). Still read by nobody.
- Wording on the Scale card, the viewer's `+NER` tooltip and the NERs screen,
  the manual and the PT strings follow. Tests: 8 new in
  `tests/test_naming_v2_2180.py`; 2130 / 2140 / 2142 / 2150 updated.

---

## 2.17.0 — 2026-10-08

**The memory the books leave behind** (Marcelo, 8 Oct 2026, on the work
laptop with eight event projects: *"quando eu faço o uploading do PDF parece
estar demorando mais que o normal… quanto mais projetos eu tenho mais lento
fica. E a renderização dos mapas também fica mais lenta a cada novo projeto
carregado"*). The database had nothing to do with it — 2 MB, eight projects.
The machine had 700 MB of RAM free: the server process held 650 MB it would
never give back, and the browser tab held every book it had ever opened.

- **The book is read in a child interpreter.** Reading a venue design book —
  PyMuPDF over 20–90 MB of vector sheets, the stroke walk of every page for
  the NER block symbols — left the server a few hundred megabytes heavier
  each time, and Python never returns that to Windows. Over a day the server
  reached 650 MB, was paged out on a laptop with little free RAM, and the
  next upload ran at 8–17 s/page instead of 1.5 (a TEAP import that takes
  two seconds took two minutes beside it). `extract_drawing` (the import) and
  `read_drawn_rooms` (*Place NERs from the drawing*) now run in a child
  Python started for the job (`backend/app/isolate.py`): same code, same
  progress bar, same cancel button, and when the job ends the child exits
  and every byte goes back. It costs the child's start — a few seconds per
  job. `NER_INPROCESS=1` runs them in the server as before; if the child
  cannot be started at all the server falls back to that by itself and says
  so in the log.
- **The viewer keeps one open book and closes it.** The Drawing viewer
  opened the PDF again with PDF.js on every page turn and never closed any
  of them, so each open copy of a 70 MB book stayed in the browser's worker
  until the tab was closed — the tab grew with every page turned and every
  project opened, and the rendering slowed with it. It now opens the book
  once per drawing, turns its pages, closes it when the drawing or the
  project changes and when the viewer is left, stops a render still running
  for the page just left, and releases the bitmap of the previous page as
  soon as the next one is on the stage. The page bitmap is also capped at
  6,000 px on its long side (a 48×36 in sheet at the old fixed scale was
  7,600 px, which some browsers refuse).
- **Indexes.** SQLite does not index a foreign key on its own, so every "the
  rows of this project" query read the whole table. Every `project_id`, and
  the other keys the screens filter by (`drawing_id`, `ner_asset_id`,
  `teap_space_id`, `drawing_space_id`…), are indexed — 29 indexes, declared
  on the models and created at start on a database that predates them
  (`indexed elements(project_id)` lines in the migration report, once).
  Nothing to feel at today's sizes; it is what keeps the next hundred
  projects from feeling it.
- `GET /projects/{id}/elements` loaded each marker's register NER and that
  NER's other markers one query at a time; two queries for the list now.

No screen changed. Eight new tests (`test_isolate_2170.py`,
`test_indexes_2170.py`); 845 in all.

Not in this version: the marked-up PDF export still opens the book in the
server process (it reads the register through the database as it draws, so
it cannot move to the child as it is); the server's own baseline after a
start — about 350 MB with PyMuPDF loaded — is what it is.

## 2.16.1 — 2026-10-02

**Three defects found by moving to another computer** (Marcelo, 2 Oct 2026:
the development folders copied to a second laptop, the installation there
updated without administrator rights, the day's project carried into it with
`backup.bat` / `--restore`). No screen and no file shape changed.

- **The sign-in task needs no administrator any more.** `autostart.bat` made
  it with `schtasks /sc onlogon`, a trigger for every user of the computer,
  refused without elevation (`ERROR: Access is denied.`) — and stopped there,
  so the watchdog was not installed either: `setup-noadmin.bat` (2.16.0)
  installed an application nothing started. The task is now registered for
  the person signed in only, from XML (`tools/signin-task.ps1`: per-user
  logon trigger, the account by SID, `schtasks /Create /XML`, battery and
  72-hour settings off from the start). The watchdog is installed whatever
  the sign-in task did; if Windows refuses the sign-in task all the same,
  `autostart.bat` says so, ends with success, and the watchdog starts the
  server within two minutes of a sign-in. `signin-task.ps1` is shipped and,
  with `watchdog-install.ps1`, REQUIRED by the packager.
- **A restored database points at the installation it was restored into.**
  `Drawing.stored_path` and `TeapFile.stored_path` are full paths; a backup
  restored into another folder, another Windows account or another computer
  kept naming the folder it came from — and, where that folder still existed,
  kept reading it. `migrate.rebase_stored_paths` runs first at every start:
  a record that names any place but this installation's `data\uploads` is
  moved to the same relative path here when the file is here and has the
  recorded SHA-256, with an `upload.path_rebased` line in the audit log. A
  record whose file is not here, or is a different file, is left as it is
  and reported in `data\server.log`.
- **The backup carries `data\criticality-matrix.xlsx`**, the one file kept
  outside the database and the uploads; `BACKUP.txt` says whether it is in.
  A restore replaces the installation's matrix only with the backup's.
- A restore into a new installation no longer leaves an empty `replaced-…`
  folder; `backup.py` prints plain ASCII.
- Docs: INSTALL (starting by itself, where the data lives, backup, carrying
  projects, three new entries under common problems), the manual's backup
  paragraph, HISTORY.

Tests: `tests/test_carry_services_2161.py` (14) — 837 passed.

## 2.16.0 — 2026-10-01

**The installer without administrator rights** (Marcelo, 1 Oct 2026: the
team's managed computers do not let a non-administrator install software,
and nobody will be given the rights). Nothing in the installation ever needed
them — the folder is the person's own (`%LOCALAPPDATA%\Programs`), the
scheduled tasks are per-user (`schtasks /create … /rl limited`), the server
listens on `127.0.0.1` — only the 2.13.1 check asked for them.

- `setup.bat --no-admin`: skips the Windows prompt and installs for this
  account only, saying so. Everything else — backup and replacement of a
  previous installation, the tasks, the server, the shortcut, the clean-up —
  is unchanged.
- `setup-noadmin.bat`: a double-click file that runs `setup.bat --no-admin`,
  for whoever receives the zip. Shipped in the package (REQUIRED), excluded
  from the copy into the target like `setup.bat`, deleted with the package.
- When the Windows prompt is refused or cannot be answered, `setup.bat` no
  longer stops: it offers *Install without administrator rights, for this
  account only? [Y/N]* (with `NER_NOPAUSE=1` it fails as before, for scripts).
- The wrong-account guard still runs on the no-admin path (the window is the
  signed-in person's, so it passes).
- Docs: QUICK-INSTALL, INSTALL (prerequisites, options table, the log line,
  common problems), INSTALL.txt, the manual's installation paragraph.

Tests: `tests/test_installer_2160.py` (6) — 823 passed.

## 2.15.0 — 2026-10-01

**The NERs the 3.x design books state** (Marcelo, 1 Oct 2026, with the VCC
Softball book and the VDD / VEE / VBB AAM workbooks). The design team no
longer prints `TEC.003.xx.xxx` at every rack; the placing step now reads what
the new books do print, on top of everything it already read:

- **New codes.** `TEC.010-xxx` is a *Network Equipment Rack - Critical* and
  `TEC.020-xxx` a *Non-Critical* one (also the bare `TEC.010` / `TEC.020`), as
  the AAM workbooks file them. `TEC.003.01 / .02` still read for the 2.x
  books; `TEC.003-001` (the Mobile Equipment Room in the new taxonomy) is not
  a NER. Only a code with a room number identifies one room across sheets —
  a bare `TEC.010` printed on two sheets is two racks.
- **The label without "(NER)".** *Network Equipment / Rack - Non-Critical* (two
  lines, no bracket, no arrow — the label sits in the room) is a NER room; a
  lone *Rack - Critical* line with no *Network Equipment* over it is not.
- **The NER block symbol.** Most racks in the new books are a CAD block — a
  small orange square with the word NER plotted as strokes, no text layer
  at all. `domain/ner_symbol.py` recognises it by shape against a template
  taken from the VCC book (55 strokes; centred, turned onto the lettering's
  axis, scaled by its spread; symmetric Chamfer distance ≤ 0.10, the book's
  19 blocks score ≤ 0.05 and nothing else under 0.16). Colour decides
  nothing. Each symbol becomes a **non-critical NER with the criticality
  pending** ("coloca NER não crítica e depois eu mudo se precisar"); a
  symbol inside a room already read is that room's rack; a symbol at the
  same position as one on another sheet of the book (a level-01 rack repeated
  on the level-02 plan) is created and asked about. Never on a key plan;
  never within 12 m of a NER already there.
- **Non-critical names start at `NER21`** (`SEQUENCE_START`), as the event's
  naming sheet numbers them (01–08 COMP, 09–20 critical, 21+ non-critical);
  critical names keep starting at `NERc01`. An old lower number never pulls
  the series below 21.
- The placing step walks the strokes of every detail page (the symbols have
  no text to announce them), 1–3 s per sheet, and reports its progress page
  by page.
- Measured on `VCC_400_SBL_O.pdf` (83 pages): 4 coded rooms + 19 symbols =
  23 NERs, no false positive; the book has no "(NER)" and no `TEC.003` rack.

Tests: `tests/test_ner_sources_2150.py` (23 new) — 817 passed.

## 2.14.2 — 2026-09-30

**The manual audited against the code, a one-page installation guide, and
the two things the audit found in the code.** Every section of
`docs/MANUAL.html` was checked control by control against the interface and
the server and corrected in forty-odd places — the order of the NERs columns,
the `Applied` and `Source` columns of the Scale screen, the matching order as
the engine really runs it (no synonym step of its own; the building only
nudges the confidence), the wireless-port formula, the three cases that move a
tile before the next run, what `Insufficient capacity` overrides, the ten rows
of the legend, the `Summary` sheet's row order, `backup.bat --to`, and the
last bilingual labels (`caixa / box`, `seleção / select`) that the 2.13.1
conversion had left behind. The four documents are complete HTML pages again
(`<!DOCTYPE>`, `<head>`, `<body>` — lost in 2.13.1) and `docs/QUICK-INSTALL.html`
is new: one page, five steps, for the person who receives the zip; it ships in
the package and is what the e-mail to the team attaches. Three limitations
that were only in `LIMITATIONS.md` are now in the manual's table (no two-point
calibration, jobs do not survive a restart, no scenario restore).

In the code: the Import card read `2 · TEAP (XLSX / XLS / CSV)` while `.xls`
is refused — it now reads `XLSX / XLSM / CSV`; the next sequential NER name
(`NERc03`) skipped the numbers of *live* rows only, so a removed NER's number
could be handed out again and a restore would have made two `NERc02` — the
removed rows count now, as the function's own docstring always said; the
`with legend` tooltip promised three footer lines where two are written.
`README.md` still announced 2.1.0. `tests/test_docs_pass_2142.py` (9) holds
the documents to a complete English page and the naming rule to its docstring.
Found by running `run-tests.bat` inside the fresh installation: a 2.13.1 test
read `tools/render_docs.py`, a development tool the package does not ship, so
the suite failed on every installed copy — it now checks that file only where
it exists.

## 2.14.1 — 2026-09-30

**The marked-up PDF export failed with `NameError: name 'wcol' is not defined`**
on the first press after 2.14.0. Folding the two access-point kinds into one
removed the line that picked the label colour by kind and left the name behind
in the branch that draws an access point; no test exported a PDF with an access
point in the analysis. Fixed; `tests/test_marked_pdf_wireless_2141.py` exports
one, and scans every backend module for a name a function reads that nothing
defines (a stdlib `symtable` pass, so it needs no linter installed).

## 2.14.0 — 2026-09-30

**Key plans ticked on the Scale screen, cleaner space names, the NERs placed
as a step, sequential names, a toolbox in the viewer, one kind of AP,
indoor/outdoor, a clean export.** Marcelo, 29 Sep 2026: the space names had
become "muito poluído" (cable notes, length tags and legend words arriving
as rooms); the viewer had "muitas funções e muito grande"; the naming
convention was to go ("eu nomeio cada NER do jeito que eu quiser"); the NERs
should only be placed after the key plans and the scales are settled; and the
exported PDF should carry nothing "que não é de origem do arquivo".

- **Key plans on the Scale screen.** A *Key plan* tick per page, ticked by
  default from the title block — `KEY … PLAN`, and now also the drawing index,
  the venue information, the abbreviations and the typical-solutions sheets —
  applied in one act (`POST /projects/{id}/pages/key-plans`). A page ticked
  loses its spaces and any TEAP tie to them; a page unticked gets its spaces
  read off the book; the matching runs once. The viewer's tick stays. A key
  plan yields no space at all on import, and the *Spaces* switch is off there.
- **Space names read the accommodation-matrix (AAM) way.** The space code (`ACR.001`,
  `BRS.052.02-001`) first, as before; on a sheet with no codes, a room-name
  label is a space only when it reads as a known space name — the bundled
  AAM list (`backend/app/domain/aam_names.txt`, from the VHH and VBB AAM
  sheets; VNI and MPS left out) plus the project's TEAP names — at 80 %
  `token_sort_ratio` or a whole known name inside the label; the `L9m (31ft)`
  length tag is stripped. A start-up pass (`spaces-2.14.0`, once per book)
  removes the untied name-only labels that fail the test and every untied
  space on a key plan, and lists them in the audit log; a space a TEAP line
  is tied to is never touched.
- **NERs placed as a step, not at import.** An import reads what the book
  says about its NERs — the team's own annotations, the `TEC.003.01 / .02`
  rooms, the "Network Equipment Rack (NER)" labels — and places nothing.
  *Place NERs from the drawing* on the Scale screen
  (`POST /projects/{id}/ners/place-from-drawing`) creates them in that order,
  never on a key plan, never within 12 m of a NER already on the sheet;
  running it again adds only what is missing. The 2.13.0 start-up pass is
  gone; `POST /drawings?place_ners=true` does the placing at import.
- **Sequential names.** Every NER the app creates is `NERc01`, `NERc02` …
  (critical) or `NER01`, `NER02` … (non-critical), in reading order, with
  what the sheet printed kept as *printed as* and as an alias (so the same
  printed label on another sheet still links to the same room). The naming
  convention, the suggested names, *Adopt* and the convention editor of
  2.7.0–2.13.1 are removed (`/naming` endpoints gone; `domain/naming.py`
  deleted). The NER naming structure is a reference panel — a tab in the
  viewer's inspector, a side panel on the NERs screen — and decides nothing.
  A NER drawn by hand is offered the next name of its series
  (`GET /projects/{id}/ner-next-name`).
- **The Drawing viewer.** The top strip keeps only the page — a pager
  (◀ ▶, the list, `8/47`) — the key-plan tick and the search; every tool
  and the view switches (Fit, Radii, Spaces, Register NERs, Coverage) are
  in a toolbox down the left, folding to a tab. The viewer comes back to
  the last page viewed, per project.
- **One kind of access point.** `+AP` only; points are `AP-1`, `AP-2` …
  Existing `WIRELESS_OUTDOOR` points are folded into `WIRELESS` at start-up
  and the old `AP-I-n` / `AP-E-n` labels renumbered once (audited). The
  workbook's *Indoor APs* / *Outdoor APs* columns and summary lines are gone.
- **Indoor / outdoor per NER** (`ner_assets.environment`): a select on the
  NERs screen and in the viewer's inspector; the *Indoor / outdoor* column
  of the *NERs and ports* sheet, three *Totals* lines, and a column of the
  register export.
- **TEAP × drawing:** the *Drawing space* list is one alphabetical list —
  the "not tied yet" / "already tied" groups are gone.
- **The exported PDF is clean.** The reviewers' PDF annotations (free-text
  boxes, ink, notes — the red "COW #1" / "NER 14" of a comments round) are
  taken off the copy before the app's markers are drawn; the book on disk is
  untouched.
- Tests: `tests/test_spaces_vocab_sequence_2140.py` (26 new);
  `test_key_plans_drawn_rooms_2130.py` rewritten for the placing step.

## 2.13.1 — 2026-09-29

**A clean installer that needs administrator rights, and English-only
manuals.** Marcelo: the installer on other machines did not work well without
administrator rights; the team installs from an e-mail with simple steps; the
application has to work in Chrome, Edge and Firefox; the manuals no longer need
two languages.

- **`setup.bat` asks for administrator rights.** Without them (checked with
  `fltmc`) it asks Windows through the UAC prompt and carries on in the elevated
  window; refused, it installs nothing and says to use *Run as administrator*.
- **…and refuses the wrong account.** When the elevated window runs as another
  account than the one signed in (a standard user elevated with an
  administrator's credentials), the application would land in that account's
  profile with its tasks: setup stops and names both accounts. Remote Desktop
  sessions, where Windows reports no console user, are not compared.
- **An existing installation is replaced, not overlaid.** After the database
  backup and the stop, the old installation is moved whole to
  `<target>.previous` (an older `.previous` is removed first), its `data\`
  moves into the new empty folder, and the new version installs there: no file
  of the old version survives. A failure after the move puts everything back
  (data first, then the old folder, the tasks and the old server). Nothing of
  the data is ever deleted.
- **One way in.** `install.bat` opened in an unzipped package hands over to
  `setup.bat` (before delayed expansion is switched on); in the installed
  folder, in a development checkout, or called by `setup.bat`
  (`NER_FROM_SETUP`), it installs in place as before.
- The browser opens through `explorer.exe`, as the person signed in rather than
  with the setup window's rights; an **NER Analyzer** desktop shortcut
  (`.url` to `http://127.0.0.1:8000/`) is written with the services. The
  installed files lose the "downloaded from the internet" mark
  (`Unblock-File`).
- **Manuals in English only.** `docs/INSTALACAO.html` → `docs/INSTALL.html`,
  `docs/HISTORICO.html` → `docs/HISTORY.html`, one PDF each (no `.en.pdf`);
  `INSTALL.txt` in English. The installation manual describes the rights, the
  account check, the replacement with `.previous`, the rollback, the shortcut
  and the supported browsers (Chrome, Edge, Firefox; not Safari or Internet
  Explorer).
- Browsers: the interface uses no engine-specific API (the wheel zoom reads
  only the sign of the scroll, the session cookie is `SameSite=Lax` without
  `Secure`, the build targets the widely available baseline).

---

## 2.13.0 — 2026-09-29

**Key plans only illustrate, and the NERs the drawing already states become
NERs.** Marcelo: *"Eu só quero evitar criar todas as NER manualmente se a
informação já tá no desenho... prefiro conferir e validar do que criar tudo do
zero."*

- **Key plans.** A page whose title-block DRAWING TITLE reads `KEY … PLAN`
  (`KEY ENLARGED PLAN - LEVEL 01`, `KEY FLOOR PLAN`) is a key plan
  (`pages.key_plan`, `key_plan_source` = `title` | `manual`). Its spaces are
  read but listed nowhere (`/drawing-spaces`, the viewer, the search, the
  TEAP × drawing dropdown), never offered to the matcher, refused by hand
  (422), and ignored by *same space on other pages*. A tie to a room on a key
  plan is released (`matching.key_plan_released`, audited with room and page)
  and the matching looks again. A NER written on a key plan is imported as a
  reference (`NER_*_REF`); `+NER` and the access points are refused there
  (422) and disabled in the viewer. `POST /pages/{n}/key-plan` and the viewer's
  `Key plan` box correct a title block read wrong.
- **NERs from the drawing** (`domain/drawn_rooms.py`, `services.adopt_drawn_rooms`).
  On every page that is not a key plan: `TEC.003.01` (critical) /
  `TEC.003.02` (non-critical) in any spelling (`-05`, `.005`, bare), or the
  `Network Equipment Rack (NER) - Critical / Non-Critical` label with no code.
  The leader is walked segment by segment to its arrowhead and the NER goes at
  the tip (one path or several; on a stacked label the arrow leaving the NER's
  lines). Per place: a room within 12 m of a NER marker that was already on
  the sheet is that NER — none is created near one that exists, and one marker
  may answer for several racks labelled side by side; the code is recorded on
  it, a disagreeing criticality becomes a `criticality:` question. The same code
  on two sheets is one NER with two markers. Name: the code, or `NERc p9-1` /
  `NER p9-2`. Criticality not stated: non-critical, classification `pending`.
  Origin `drawing_room` ("from the room label"), never confirmed; answered
  `criticality:` / `position:` questions leave the row when a criticality is
  confirmed or the marker is moved.
- **Existing projects**: pages are classified from the stored sheet title on
  start; a one-time background pass per book (`drawn-rooms-2.13.0`) releases
  key-plan ties, re-runs the matching when something was released, and reads
  the NER rooms.
- NERs screen: the `criticality not stated` tile filters; origin
  `from the room label` in amber. Scale screen: `· KEY` on key plans. Workbook
  *Summary*: *of which read from the room label*, *criticality not stated*.
- Measured on the real books: VBB 27 NERs (no code; 25 arrows followed),
  VAA 9 rooms (9 arrows), VEE 17 rooms (15 arrows; 5 taken as
  the team's red NERs, 12 new), VFF 6 rooms (3 taken as the team's red NERs, 1 the same code on a second sheet, 2 new).
- New tests: `tests/test_key_plans_drawn_rooms_2130.py` (31).

## 2.12.2 — 2026-09-29

**A white page on other computers.** Installed on two more machines, the
app opened as a blank white page with no error. The interface is an ES module
(`<script type="module">`), and a browser refuses a module served as anything
but a JavaScript type. The server took each file's type from Python's
`mimetypes`, which on Windows reads the registry, and on many machines
`HKCR\.js` says `text/plain` (an editor or a runtime rewrites it). Marcelo's
machine had it right, so it never showed here. The server now fixes the types
of `.js`, `.mjs`, `.css`, `.svg`, `.wasm` and `.json` itself, whatever the
registry says. New tests: `tests/test_mime_types_2122.py` (2).

## 2.12.1 — 2026-09-26

**The manual reviewed against the code, section by section.** Marcelo:
*"Revise e reescreva todo o manual de acordo com a última versão."* Every
section of `docs/MANUAL.html` was checked against the code and corrected where
it had drifted: shared readers cannot build reports; the marked-up PDF covers
the first drawing set only and carries the legend *or* the footnote, never
both; `Needs validation` also covers rule B, unvalidated routes and spaces not
analysed yet; a pinned NER still takes a space whose match or scale is not
confirmed; a page with no scale gives *No NER reaches it*; *Route not
validated* practically never appears; the `Kind` list, `Register NERs`
circles, `Reset to default`, the automatic merge rule, the area-02 words
(*VENUE MEDIA CENTER*, *MEDIA CENTER*), the search box and the same-name
dialog are described as the code does them. The review also found defects,
fixed here rather than documented:

- **A TEAP with no venue column was filtered to nothing.** With no venue
  column mapped, the import fell back to the project's venue code, matched no
  row, "succeeded" empty and deleted the TEAP already in the project. The
  venue filter now applies only when a venue column is mapped.
- **An import that finds no row is refused** (*nothing to import … The TEAP
  already in the project was left as it was.*) and the TEAP in the project is
  kept.
- **An old `.xls` is refused at upload** with *save it as .xlsx*; it used to
  pass the filter and fail as a server error. The file picker offers
  `.xlsx`, `.xlsm` and `.csv`.
- **Choosing a different room drops the confirmation.** A row the matcher (or
  you) had confirmed kept the old confirmation after a new room was picked;
  it now waits for `Confirm` again.
- **`Save rules` failures are shown** (*Rules not saved: …*) instead of
  failing silently.
- **A new shaft or riser is drawn at once**, not after the page changes.
- **The ports-awaiting counter** on TEAP × drawing no longer counts rows set
  to `— none —`.
- **The wireless-point hint in the Inspector** points to the viewer's
  `Coverage` button, the one that fills it.

New tests: `tests/test_manual_pass_2121.py` (5). 711 passed, 1 skipped.

## 2.12.0 — 2026-09-25

**TEAP × drawing: three tiles.** Marcelo: *"acho que aqui só precisamos de 3
botões… qualquer outro botão aqui é desnecessário e tá poluindo e complicando
demais a análise."* The tiles are now `TEAP spaces`, `matched` and `no room
found`, and `matched` + `no room found` = `TEAP spaces`, always. `matched`
counts every line with a room, whoever tied it and whether or not it is
confirmed; `no room found` counts every line without one, including the
lines you set to `— none —` (the old *not on this drawing (rejected by you)*
tile — *"se eu mudei pra NONE é pq não tem room encontrada, o que dá no
mesmo"*). *confirmed by you*, *exact code, confirmed by the matcher*,
*matched, not yet confirmed*, *your decisions* and *TEAP spaces with no ports*
are gone as tiles; each row still says who decided, and the line under the
tiles says how many matched lines still await `Confirm`.

**Exceptions: every space that needs you, from the Demand rows.** *"Por que
o coverage exceptions parece não mostrar tudo que realmente ficou de fora?"*
The step ran an analysis of its own and listed the engine's exception rows,
which left out a TEAP space with no room and no NER (on VDD 43 of 88 spaces,
against 4 rows on the list — they were only in a second table), and a
near-limit space sat in Demand's *Served* pile where it was hard to find. The
step now reads the same rows as Demand per space (the stored run and the
choices made since) and lists, in five filter tiles: all, *Pending*, *Out of
limit / over capacity*, *near the limit*, *Served — not measured*. Each row
has the `Served by` select, the distance and margin, **Other NERs measured**
(the rooms the run measured from the space, nearest first, the serving one
left out, each a one-click `use`), and `Demand` / `Drawing` buttons that open
the row on Demand per space or find the room on the drawing. The API adds
`alternatives` to every row of `/spaces/assignments` and to wireless points;
the engine's alternatives now leave out the serving room.

**Demand per space: a search box and a near-limit counter.** Code, name, room
on the drawing, FA or NER; every word must match. The counter *near the limit
(counted as served)* filters those rows.

**Drawing viewer: search.** A box in the toolbar finds any name on any page —
a room the extractor read (and the TEAP codes tied to it), a NER or any other
marker, a named area. Enter or a click goes to the page, centres, zooms in,
selects it and rings it for a few seconds.

**Placing a NER under an existing name asks.** *"Se eu for criar uma NER e
usar o mesmo nome de uma NER existente, me pergunte se é a mesma NER também
em outra página ou se devo escolher outro nome."* OK draws the marker as the
same NER (one register row, counted once; `POST /elements` accepts
`same_as_asset_id`, the marker takes the room's name and classification, the
link is confirmed and audited); Cancel asks for another name. Names compare
without case, spaces, dots or dashes (`NER 21` = `ner21`, `NERc 01` ≠ `NER 01`).

706 tests (+7).

## 2.11.0 — 2026-09-24

**A wireless point follows the NER of its space, or the one you choose.**
Marcelo, on VAA page 6, whose rooms are served from page 7: *"os AP que
eu coloquei nas salas da página 6, eu preciso associar uma NER. Já que eu
associei NER para os espaços… pq ao colocar AP nas mesmas salas a mesma NER
não foi atribuída… se isso não for possível me deixa dizer qual NER vai
atender esse AP."* A point tied to a TEAP space whose room is fixed (chosen
by hand, or named by the TEAP) is now served by that same room: counted on
it, and *not measured* when the room is on another page. The `Served by`
column of the *Wireless points* table is a select, so a room can also be
chosen for one point; `✕ clear my choice` goes back. The count is unchanged
(TEAP − 1 + points): the choice moves the port, it never adds one. New
column `elements.assigned_ner_asset_id`, endpoint
`POST /projects/{id}/wireless/{element_id}/serve`, audited.

702 tests (+1).

## 2.10.0 — 2026-09-24

**TEAP × drawing: `— none —` now sticks.** Marcelo: *"qdo eu realmente não
encontro com o que cruzar… prefiro poder escolher none e isso valer."*
Picking `— none —` under `Drawing space` cleared the decision, and the next
`Run matching` proposed the matcher's room again. It now records on the TEAP
line that the space has **no room on this drawing** — the same lock the old
reject used — and every run keeps it. The option reads `— none (your
choice) —`, the row says *you said this space is not on this drawing — kept
when the matching re-runs; Undo takes it back*, and `Undo` gives the
matcher's answer back. The space counts in the tile *not on this drawing
(rejected by you)* and enters the analysis with no room: pending until a NER
is chosen for it on Demand per space, then *Served — not measured*.

**Demand per space: a NER chosen on another page counts.** *"Se eu escolhi,
deveria ser served."* The `other level` checkbox is gone. Choosing under
`Served by` a NER that sits on another page than the space is itself the
statement: the room serves the space, its ports count against it, and the
status is *Other level — not measured* (group *Served — not measured*) until
a shaft, riser or vertical route lets it be measured. The row shows a green
line: *other page — NER x is on page …; this space is on page … · counted on
this NER, distance not measured*. The cause of the stuck *pending*: when a
NER was chosen while the space had no room and the room was tied later — or
after an untick — the box stayed unticked and the engine refused the room.
A choice on the same page is still measured: far away it is *Out of limit* —
choosing picks the room, not the verdict.

**Demand per space: undo a choice.** *"Eu quero voltar ao no room on the
drawing."* With a NER chosen by hand, the first option of `Served by` is
`✕ clear my choice — back to: no room on the drawing` (space with no room),
`✕ clear my choice — back to the nearest NER rule` (space with a room) or
`✕ clear my choice — back to the TEAP's room: X` (the TEAP names one).
Picking it releases the choice, audited.

**Demand per space: every counter is a filter.** `photographer areas`,
`rooms chosen by you`, `tied to another room`, `same space on another page?
— to confirm` and `rooms named by the TEAP` are buttons now, like the four
group tiles: click to show only those rows, click again for all. The filter
select then reads `filtered by a counter below (n)`.

**Naming convention: the event's naming sheet.** *"O name convention está errado, a
planilha correta está em anexo"* (*NER Standardized Naming
Structure.xlsx*). It replaces the VAA device-sheet table (NERc.02 BTOC,
NERc.03 OVR…, a dot separator, a sequence from 08), which was wrong.

- Names are `NERc NN` (critical) and `NER NN` (non-critical) — prefix, a
  space, two digits; a second room for the same purpose gets `.1`
  (`NERc 07.1`). Adopted names are recognised in any spelling (`NERc.07`,
  `NERc07`, `NERc 07`).
- COMP: fixed critical numbers 01 TER, 02 Venue Media Centre / media work
  rooms, 03 media tribunes, 04 BTOC, 05 broadcast compound, 06 CCR, 07 OVR
  (07.1), 08 FOP / technical tables (08.1); other critical rooms 09–20 in
  sequence; every non-critical room from 21 in sequence.
- `Venue type` on the card loads the preset: COMP; IBC, MPC, OLV (01 TER,
  02 VMC, critical from 03); UAC, HQ, OFH (01 TER, critical from 02); OTHER
  (no critical numbers, `NER 21`+ only; a critical room there gets no
  suggestion and says why). Until saved, the type is inferred from the
  venue code (IBC/MPC/OLV/UAC/HQ/OFH, else COMP).
- `NERc 01` is the critical NER nearest a TER marker on its own sheet within
  `At the TER within (m)` (30 m). Other fixed numbers go to the area with the
  most ports among the spaces the room served in the last run, keywords
  matched whole against TEAP code, functional area and name (editable per
  row). A room serving nothing yet: nearest matched room on its sheet,
  marked weak. Most ports takes the plain number; a room already carrying a
  number keeps it; an adopted number is never handed out again.
- Sequences follow the drawings: page, then top to bottom, then left to
  right.
- Card fields: `Venue type`, `Critical prefix`, `Non-critical prefix`,
  `Critical sequence`, `Non-critical from`, `At the TER within (m)`,
  `TER prefix`, the table of numbers, `Add an area`, `Save convention`,
  `Reset to default`. "Sequence for the rest starts at" is gone.
- A convention saved on a project before this version (the VAA table) is not
  read any more; the project uses the event's preset until it is saved again.

Suggestions stay suggestions: `Adopt` is the ordinary audited rename.

701 tests (+1).

## 2.9.0 — 2026-09-24

**New sheet in the workbook: *TEAP by NER*.** Right after *TEAP and
coverage*, the same lines summed the way the LLD team reads them: NER →
space → product, with a total per space, per NER and a grand total. Marcelo
had built it by hand as a PivotTable on an VAA export and asked for it
in the file. It is a grouped sheet, not a PivotTable — openpyxl cannot write
one, and a hand-made pivot definition Excel dislikes opens with a repair
prompt and drops the table.

What it does that the hand-made pivot did not:

- **Each NER total equals *Ports assigned* on *NERs and ports*.** The wireless
  points drawn on the sheet are listed under the NER that reaches them
  (*Wireless points drawn*, `AP-I` / `AP-E`); the flat sheet cannot carry
  them, so a pivot on it was short by those ports (NER.10: 20 against 22) and
  a NER serving only access points did not appear at all. The grand total
  equals the Summary's *Total ports requested* (659 on VAA).
- **The lines with no NER are one named group, *Pending — no NER*, last** —
  the pivot's "(blank)", which on the first VAA pass held 564 of the 649
  TEAP ports.
- **Lines counting 0 ports are left out** (monitors, phones, TVs, and wireless
  lines whose access points are drawn); how many is stated under the total.
- **Rebuilt on every export**, so it cannot miss rows the way a pivot on a
  fixed range does (the hand-made one ended one row short).

Totals are `SUBTOTAL(9, …)` formulas: nested subtotals are never counted
twice, and a filter narrows the grand total with it. The rows carry outline
levels, so Excel's 1 / 2 / 3 buttons collapse the sheet to NER totals, space
totals, or every line. Labels repeat on every row, in grey after the first,
so a filter on a NER keeps its totals with it.

700 tests (+2).

## 2.8.1 — 2026-09-22

The test pass: 2.8.0 checked screen by screen against its own manual, on a
synthetic venue driven through the real screens (*"agora vc é um testador…
verifique toda a última documentação válida e teste tudo"*). Nothing here
changes a file shape or a screen's layout; every item is a correction the
pass found, or a sentence the manual had wrong.

**Fixed: saving a mapping template under an existing name was a 500** — and
it stopped the TEAP import behind it. Saving the same name now replaces that
template. **And the saved templates are offered back**: *Apply a saved
mapping template* on the Import screen puts a template's columns on the
sheet (only the columns the sheet has; the rest are named), plus its header
row. They had been written since 2.2 and never read.

**Fixed: a wired mouse was a wired connection.** The rule that keeps a
zero-port space in the study when the TEAP requests wired connections
matched the bare word *wired*, so a storage room with four *Accessories -
USB Wired Mouse* lines entered the study as "4 wired connection(s)". It now
takes *Wired Connection*, *Wired LAN/network/internet/data* and *RJ45*.

**Fixed: the workbook had no Matching sheets.** The manual described
*Matching* and *Match exceptions*; only the command-line tools wrote them.
The app's export now carries the matching as the project holds it — the
matcher's answer with every decision laid over it, with *Confirmed by* —
and the exceptions from the TEAP side (not found, rejected, a code on
several pages, awaiting validation).

**Fixed: a hand-set photographer type did not survive a re-import** unless
the row also carried a room or a NER. It is a decision on its own now.

**Fixed: Restore after erasing a NER on the drawing brought back a row with
no marker.** The viewer deletes the marker; Restore now redraws it from the
register position (origin *drawn by you*, audited as `marker_redrawn`).

**Fixed: a move was not audited as a move.** Dragging a marker wrote
`element.updated` with the destination only. It is `ner.moved` (a NER) or
`element.moved` (anything else) with *from* and *to*; the origin is left
as it was — a moved marker read off the drawing is still from the drawing.

**Account events can be read.** Accounts created, blocked, reset and
deleted — with the reason given — were written with no project and no
screen showed them. *Accounts & security* has an *Account events* card for
administrators (`GET /api/admin/audit`).

**Interface.** The open project is reopened after a reload (Ctrl+Shift+R
sent people back to the Projects list). *Ports* on Demand per space sorts
(its key named a field the row does not have); *Payload* in the audit log
sorts as text. The Demand type select is wide enough for *photographer
(70 m)* — it was cut to "pho". The notice after placing a `*TER`/`*COW`/
`*DIVA` reference no longer promises reach circles. The progress bar no
longer reads *Finished finished*. The legend's foot line has its spaces
back. Thirty-odd strings that stayed English on the Portuguese screens
(*Sign out*, the whole TEAP card of Import, *Change password*, *Reset
password*, *Delete permanently*, the first-account copy, the space
inspector's labels, the shaft prompts…) go through the dictionary.

**Manual.** Corrected where the pass found it wrong: a move keeps the
origin; dragging a locked marker pans the sheet; the Scale screen has no
unconfirm; the TEAP × drawing tiles read 0 before the first run; the
*show TEAP spaces with no ports* box is on Demand per space, not Projects;
a drawing cannot be removed from a project; each export replaces the
previous file of the same format; the *No coverage analysis* note is per
project, not per sheet; a shaft measures only when a traced route reaches
it; *Label printed on the drawing* shows once the name differs; the
*Wireless points* and *TEAP spaces with no ports* sheets appear only when
there are any; an administrator's tab reads *Accounts & security*.

**Tests.** 26 more (`test_tester_pass_281.py`): 698 in all.

## 2.8.0 — 2026-09-22

Marcelo's evening pass on the viewer and the workbook, plus the review of the
naming convention against the `NC.xlsx` sheet.

**Named areas (`+area`).** *"Me permitir desenhar áreas e nomear,
principalmente para eu destacar áreas de interesse como BTOC, TER, etc. …
só para fins ilustrativos."* Click each corner, double-click the last one
or press Enter to close, name it. A `Zone` of kind `area` — the zones table
had been in the schema since August with no tool since 3 Sep — drawn as a
faint slate-blue polygon with the name on a tag, on screen and on the
marked-up PDF (`services.areas_to_draw`, a legend row of its own). Rename,
annotate and delete from the Inspector, the `Delete` key or the eraser.
Counted nowhere. `GET/POST/PATCH/DELETE /projects/{id}/zones` (+`?page=`).

**References to a TER, a COW and a DIVA node (`*TER`, `*COW`, `*DIVA`).**
Three more reference kinds (`TER_REF`, `COW_REF`, `DIVA_REF`), drawn with
the dashed ring in the room's colour, **no reach circles** — the real ones
have none — and outside the `TER01…` numbering. `NER_REFERENCE_KINDS` is
the subset that gets circles; `REFERENCE_KINDS` is all five. The whole
illustrative group of the toolbar (references and `+area`) is styled in
violet, *"só pra não confundir"* `*NER` with `+NER`.

**Names on the sheet** are a point larger, bold, on a translucent white tag
(`Label`/`Tag`), for markers, register rooms and areas.

**Fixed: moving a marker threw the sheet off screen.** *"Toda vez que eu
mexo em uma NER, o PDF vai pra longe e eu tenho que dar Fit — por que?"*
Konva bubbles a marker's `dragend` up to the Stage, whose handler took the
marker's position — in PDF units, thousands — as the pan. Only the Stage's
own drag pans now.

**Fixed: the coverage overlay painted almost nothing.** The viewer found
each row's room by matching the tail of the TEAP key against the room's
code, which only holds when both are spelled the same — and the matcher
exists because they are not. Every assignment now carries
`drawing_space_id`, `x` and `y` (`_space_area` puts the id in `meta`), the
overlay keys on the id and falls back to the old tail match for runs saved
before. The Inspector read a NER's load by `E<id>` where the analysis
records `A<id>`, so every NER showed as serving nothing; fixed. The
`Register NERs` button is shown only when there is a room to toggle — since
a drawn NER *is* its register row, the layer is nearly always empty and a
button that never did anything read as broken.

**Fibre runs to the TER and the totals.** *"Uma coluna RUN fiber to TER,
contando 2 para cada NERc e uma para cada NER não crítica. Também preciso
de um resumão: quantas portas no total, quantas fibras, quantos AP interno
e AP externo."* Two project settings (`fibre_runs_critical` = 2,
`fibre_runs_noncritical` = 1; migration adds the columns; edited under
*Project rules*) feed a `Fibre runs to TER` column on *NERs and ports*, a
`TOTAL` row of live `SUM` formulas one blank row under the rooms and
outside the filter range, a *Totals:* block at the top of the *Summary*
sheet (total ports = TEAP spaces + wireless points, ports on a NER, NERs
critical/non-critical, fibre runs total and by criticality, APs indoor and
outdoor) and two rows on *Coverage figures*. A count of runs, never a
length.

**Naming convention, reviewed against the VAA sheet.** What was missing was
the rule for rooms whose area is not in the table: the sheet numbers
NERc.01–07 by area and then runs on in sequence (NERc.08, NERc.09) with no
area. The app only said *no number — add it to the convention*, which on
the event's TEAP (SPT, TEC, SPP, LOG…) was nearly every NER. `naming.suggest`
now hands such rooms the next free number from `fallback_start` (default
8, editable as *Sequence for the rest starts at*; 0 turns it off), critical
rooms first and then by ports, in one sequence for both prefixes so a
number is never used twice in a venue, and an adopted slot is kept. The
row still names the area it found. Area 07 was added as *IP6 / cellular
(T-Mobile CoW)* — the only reading of the sheet's row 07. Left out on
purpose: `NERc.OD1` (outdoor NER) and the full device name
(`VAA-L0-NERc.02-CEN9348-01`), which need facts the app does not have.

Tests: 672 (+1 skipped); 11 new in `tests/test_named_areas_refs_fibre_280.py`.
No installer built for this version, at Marcelo's request, until he has
tested it.

## 2.7.0 — 2026-09-22

Four requests from Marcelo in one day, all on the Demand / NER side of the
study.

**Demand per space scrolls sideways on a small monitor.** It did not: the
table was set to 100 % of its box, and a table at 100 % never overflows — it
shrinks, so every column was crushed and the Notes column came out three
words wide. The table now has a working width (`table.wide`, 1380 px) and the
box scrolls sideways, with the scrollbar **mirrored right under the headings**
(`WideScroll.tsx`), because the native one sits at the foot of a 62 vh box,
under the fold.

**Four groups instead of ten statuses.** *"Eu não consigo ver na prática por
que dividir o status do espaço em not analysable, match not confirmed, not
analysed … os que não foram cruzados caem todos no mesmo grupo."* The
engine's `Status` is unchanged and still precise; what the screens and the
workbook show is its **group** (`distance.Group`, mirrored in `notation.ts`):
`Served` (served, near the limit) · `Out of limit / over capacity` ·
`Served — not measured` (other level; no room on the drawing) · `Pending —
needs a room or a NER` (no room, not analysed yet, match / scale / route not
confirmed, no NER reaches it). The pill shows the group with the precise
reason under it; the Demand tiles are the four groups and are the filter
(click again for all); the filter select lists the groups and, under each,
the precise reasons with counts. Workbook: `Status` is the group and a new
`Status detail` column carries the reason, on *TEAP and coverage* and on
*Exceptions*. `/spaces/assignments` returns `group`, `group_label`,
`group_reason` per row and `by_group` counted from the rows as they stand.

**A TEAP space with no room on the drawing enters the analysis.** *"Todo
espaço que precisa de serviço de rede no TEAP vai ter que encontrar um lugar
no desenho ou … eu tenho que amarrar com uma NER existente ou criada."* Until
now such a space never reached the engine: on no room's load, absent from
the summary, "not analysed" in the workbook. `collect_areas` now adds every
in-scope TEAP space with no (non-rejected) room as an area with **page 0 and
no position** (`Area.meta["unplaced"]`). The engine leaves it pending
(`not_analysable`, reason "no room on the drawing", in `uncovered`, **not**
in the exceptions — the Exceptions step already lists those from the match
rows); when a person chooses its NER under `Served by` (or the TEAP names
one), the ports **count against that room** and the status is the new
`Status.ASSIGNED_NOT_PLACED` — no distance invented, `requires_human_validation`,
an exception row as a reminder to validate the route on site; a full room
still comes back `insufficient_capacity`. `assign_space` says so in its note
and returns `unplaced`; the Demand row says "no room on the drawing —
counted on this NER, distance not measured". `summary()` gained `by_group`,
`unplaced`, `unplaced_assigned`. `analyse` now refuses only with no TEAP
space in scope at all.

**Workbook sheet "Coverage figures".** Right after *Summary*: six columns
(`Section`, `Figure`, `Count`, `Of`, `Share`, `Note`) and one row per
figure — TEAP spaces in the file / requesting ports / left out; found on the
drawing (confirmed by you, by the matcher, not yet confirmed, **tied by
hand**) / not found (of which served by a NER you chose, of which rejected);
the last run's coverage by group and reason; ports requested / on a NER /
pending; NERs in the register (drawn by you, from the drawing, capacity
known, over capacity, serving nothing); wireless points. `Share` is a real
number formatted `0.0%` over the denominator in `Of`. Built by
`services.coverage_figures`.

**NER references on a key plan.** Two viewer tools, `*NER★` and `*NER`,
place a reference to a NER on the overview sheet (`ElementKind.NER_CRITICAL_REF`
/ `NER_NONCRITICAL_REF`, `REFERENCE_KINDS`): named after a NER of the
register (a select in the toolbar while the tool is armed, or typed; the
tool stays armed), drawn in the NER's colour with a **dashed ring**, ringed
with the 90 m / 70 m circles to that sheet's scale — on screen and on the
exported PDF, which gained a legend row *"NER reference (key plan) - drawn
only, not counted"*. Not in `ASSET_KINDS` (never a register row), not in
`SERVING_KINDS` (never serves), not in `VISUAL_ONLY_KINDS` (those get no
circle). The Inspector offers `Points at (NER of the register)` and the two
reference kinds; the NERs screen's "Also on the drawing" tally counts them.

**Suggested names from the naming convention.** From the VAA device naming
sheet (`NERc.02` the broadcast compound, `NERc.03` the OVR, `NERc.03.1` the
second OVR rack, `NERc.04` the FOP …): `domain/naming.py` suggests a name per
NER — the prefix by criticality (`NERc` / `NER`, editable), the number by the
**functional area the room serves most in the last run** (ports), `.1` /
`.2` for the second and third room of that area by ports served, an already
adopted name keeping its slot; deterministic. A room that serves nothing
falls back to the nearest matched room on its sheet and is marked *weak*;
an area the convention does not number yields no name and says which area
it found. The convention — prefixes, TER prefix, and the area → number table
with the words that identify each area (whole-word match against the TEAP
code, functional area and name) — is stored per project
(`projects.naming_convention`, NULL = the default), edited on the NERs
screen (`Naming convention`: add / edit / remove / save / reset) through
`GET /projects/{id}/naming` and `PUT /projects/{id}/naming/convention`
(two areas with one number → 422). The NERs list gained a sortable
`Suggested name` column with the evidence and an `Adopt` button — the
ordinary rename, reason "naming convention — …", so the marker, the PDF and
the workbook follow and the name history records it. TER markers get
`TER01`, `TER02` … per distinct label in page order, shown in the viewer's
Inspector with `Adopt`. Nothing is renamed by the tool on its own.

Also: `STATUS_LABEL` on screen says "No NER reaches it" for `not_analysable`
(it was "Not analysable"); the Exceptions sheet has a `Page` blank rather
than 0 for an unplaced space; `export_csv` likewise.

Tests: 660 passed, 2 skipped (15 new in `tests/test_groups_refs_naming_270.py`:
every status has a group and the screen mirrors it; unplaced pending /
assigned / over capacity / rejected; the figures sheet and the `Status detail`
column; the figures service on hand ties and rejections; a reference is
drawn only and counted nowhere, the exporter rings it; the suggester's
numbering and adopted slots, whole-word keywords, the per-project convention
end to end, TER numbering; the sideways-scrolling table).

---

## 2.6.1 — 2026-09-22

**The watchdog killed a server that was still starting.** Marcelo, 22 Sep:
*"está lento e toda vez que seleciono um projeto não tá indo de boa."* The
server had died at 10:14 (the laptop went in and out of Modern Standby three
times in the next ten minutes; 1 GB of 16 GB free, 75% CPU). What followed
was the watchdog's own doing: `watchdog.log` and `server.log` show a restart
at 10:24:15, a **second** watchdog run at 10:24:49 finding the port not
answering yet — the server was still importing its libraries on a starved
machine — killing it and starting another, whose bind failed with error
10048; "restart FAILED" three times in three minutes. From the chair, a
sign-in page that refused the password and a project that would not open.

* `watchdog-hidden.vbs` now **waits** for `watchdog.ps1` (bWaitOnReturn
  True). With False the task instance ended the moment it fired, so the
  task's IgnoreNew policy — do not start a new instance while one runs — had
  nothing to apply to, and runs overlapped every two minutes.
* `watchdog.ps1`: one run at a time (a lock file, stale after 5 min); "not
  answering" is split into **refused** (nothing listening — restart now) and
  **slow** (listening, no answer in 20 s twice — left alone; restarted only
  after three consecutive runs, six minutes); a server process **younger
  than three minutes is starting**, not dead; after a start the health check
  is polled for up to 150 s instead of asked once after 45; and the log
  records the **standby and power events of the last half hour** beside the
  memory figures (3 of the 8 deaths on record followed the laptop leaving
  Modern Standby; the other 5 have no power event and no known cause).
* `serve.py` takes a **named mutex** (`Local\ner-analyzer-<folder hash>`)
  before importing anything, so a second launcher of the same folder exits
  at once instead of racing the first to the port.
* Browser: a request that never reaches the server no longer reads as a dead
  session. The top bar shows `server not answering — reconnecting`, the page
  polls `/healthz` every five seconds, and when the server is back the
  session and the project are reloaded by themselves (`the server is back`).
  The sign-in screen appears only when the 12-hour session has actually
  expired.
* Manuals: the watchdog section and the "server vanishes" rows now say what
  the evidence says.
* Tests: 647 (11 new, `tests/test_watchdog_261.py`).

## 2.6.0 — 2026-09-21

**On TEAP × drawing the tiles are the filter, and every decision has an
Undo.** Marcelo: *"todas essas legendas poderiam ser botões que filtrassem …
assim eu poderia inclusive verificar coisas que eu mesmo já confirmei e
desconfirmar caso eu tenha feito algo errado."*

* **Tiles as buttons.** Every figure above the worklist is a button; the
  pressed one filters the list to exactly those rows, and a second click
  shows every row again. The figures are counted from the rows the table
  shows — so they are there before any run in this session and cannot
  disagree with the table — and they add up two ways: `matched` + `no room
  found` (+ `not on this drawing`) = `TEAP spaces`; `matched` = `confirmed
  by you` + `exact code, confirmed by the matcher` + `matched, not yet
  confirmed`. `your decisions — kept on every re-run` cuts across those.
  `TEAP spaces with no ports` is the one view of what is outside the study.
  The two check boxes (`show only what needs review`, `show TEAP spaces with
  no ports`) are gone: both are tiles now.
* **"Confirmed by you" counts people.** An unambiguous exact code is
  confirmed by the matcher itself (0.98 against the 0.95 threshold) with
  nobody named; those rows were counted under *confirmed by you*. They now
  have their own tile and say `exact code, confirmed by the matcher` on the
  row. Run stats gain `confirmed_by_you` / `confirmed_by_matcher`; the
  worklist gains `confirmed_by`, `undo_available`, `auto_ready`.
* **Undo.** On every row a person decided — a room chosen by hand, a
  confirmation, a rejection — `Undo` releases the decision and shows **the
  matcher's own answer** again: the same room, the same method, confirmed
  only where the matcher would have confirmed it, so the next run changes
  nothing. To make that possible the matcher's answer is kept beside the
  decision on every worklist row (`space_matches.auto_*`, six columns, added
  by the migration and filled by the next `Run matching`). A row last
  refreshed by an older version has no stored answer: Undo releases it with
  no room and says to run the matching. New endpoint `POST
  /projects/{id}/matches/{match_id}/undo`, audited as `match.undone` with
  what was taken back. `Confirm` is disabled on a row already confirmed by
  you (Undo is the action there) and enabled on the matcher's own
  confirmations, which makes them yours.
* The tile `no room found — choose one by hand or reject` drops the
  "or reject": there has been no Reject on this screen since 2 Sep 2026.
* Manual: *The tiles* and the worklist controls on TEAP × drawing.
* Tests: 636 (9 new, `tests/test_match_tiles_undo_260.py`).

## 2.5.0 — 2026-09-21

**A drawn access point stands in for the wireless port the TEAP requests.**
Seen on VAA: 88 of its 110 TEAP spaces carry a `DWISA` line (*Wireless
Connection - Shared Internet Access (SIA) Wireless LAN*) with one network
port — the access point's uplink — counted in the space total by rule A. A
wireless point drawn in the viewer took one port on the NER that reaches it,
and nothing tied the two: five drawn points plus the TEAP line put **six**
wireless ports on the switch for five access points. The result feeds the
LLD, so one port too many is an expensive mistake.

* **The tie.** A wireless point carries the TEAP space it stands in for
  (`Element.space_key`, `tie_source`). On placing — and on every drag while
  the tie is still the automatic one — the server proposes the nearest room
  on the same sheet that is matched to the TEAP, up to the project's general
  limit (a point farther than a cable could run serves no room). The
  Inspector shows it under `Stands in for (TEAP space)` and lets you choose
  another space or clear it; a manual choice, and a manual clear, survive a
  drag. New endpoint `GET /projects/{id}/wireless/tie-options`.
* **The rule.** A space with at least one tied point has the ports of its
  TEAP wireless lines taken off its total (`wireless_line_ports`, recognised
  by the same words the importer uses for `wireless_required`); the points
  carry the wireless on their own NER. The row says so under `Notes`. **With
  no point drawn the TEAP's port stays counted** — the TEAP rules — and the
  row says the wireless is not drawn yet. A point tied to no space counts as
  one extra port and says so.
* **Indoor and outdoor.** `+AP in` (kind `WIRELESS`, sign in light blue,
  `AP-I-n`) and `+AP out` (new kind `WIRELESS_OUTDOOR`, the sign on a mast in
  teal, `AP-E-n`): same port, same limit, same rule; they differ in symbol,
  numbering and the report. Both legends carry both. Points drawn before
  2.5.0 are renamed `WP-n` → `AP-I-n` once at start (audited, number kept) and
  tied by the same proposal (`migrate.backfill_wireless_points`).
* **Workbook.** A filter on the heading row of every sheet. `NERs and ports`:
  `Utilisation %` is now a live formula (`=IF(OR(F="",F=0),"",E/F)`, formatted
  as a percentage) so the network team can fill in `Total ports` and see it
  follow; new `Indoor APs` / `Outdoor APs` columns. `TEAP and coverage`: new
  last column `Counted ports` — what the analysis counted for the line, 0 on a
  superseded wireless line (`Ports` stays the TEAP as it arrived). `Wireless
  points`: `Type`, `Stands in for (TEAP space)` and `Tie` columns.
* Demand per space: the wireless table shows `Type` and `Stands in for`; the
  NER load table splits `Indoor APs` / `Outdoor APs`. Summary figures
  `wireless_indoor`, `wireless_outdoor`, `wireless_superseded_ports`,
  `wireless_pending_ports`.
* Manual: viewer tools, *The TEAP's wireless and the drawn wireless* (Demand
  per space), the workbook columns and the two notation rows.
* Tests: 627 (13 new, `tests/test_wireless_tie_250.py`).

## 2.4.4 — 2026-09-18

**The audit log was ordered by time alone.** Found by running `run-tests.bat`
inside an installation `setup.bat` had just made.

* A bulk decision writes every one of its rows with **one** timestamp, and the
  Windows clock ticks coarsely enough that the click before it can land on the
  same tick. Tied on time, SQLite returns those rows in whatever order it
  likes — so the screen whose purpose is to say who decided what, in which
  order, could show an order that never happened. `GET
  /projects/{id}/audit` now orders by time **and then by row number**. On Linux
  the clock is too fine to tie, which is why only a Windows run ever showed it.
* The `setup.bat` tests **skip** where `setup.bat` is not present — an
  installation it made, since it does not copy itself there. Eight of them, the
  same rule the bundled-wheels test already followed. The guarantee that the
  package *carries* `setup.bat` does not depend on the file: it is the
  packager's `REQUIRED` list, and that test still runs everywhere.
* The installation manual said "around 560 tests"; it is around 610.
* Tests: 615.

## 2.4.3 — 2026-09-18

**The clean-up deleted the root of the package and nothing inside it.** Found
by the clean-install test of 2.4.2: 22 of the 142 files went, the 120 in
subfolders stayed, and the empty folder therefore stayed too.

* `MANIFEST.txt` writes its paths with forward slashes — `backend/app/config.py`
  — and Windows' `del` refuses one: it reads the slash as the start of an
  option. Every line of the clean-up ends in `2>nul`, so nothing said so. The
  generated script now converts each path to backslashes (a `:kill`
  subroutine, one line at a time) before deleting it.
* It also tries `rd` on the folder that held the package once more, after the
  zip beside it has gone, so an "Extract All" folder does not stay behind empty.
* Tests: 614.

## 2.4.2 — 2026-09-18

**The installer's own clean-up, finished.** Found while testing `setup.bat` on a
fresh installation: the files of the unzipped package were deleted, but the
empty folder sometimes stayed behind.

* **The clean-up now retries the folder removal** for about 45 seconds. Windows
  refuses to remove a folder that any process still has as its working
  directory, and `setup.bat`'s own window is not the only candidate: run from
  another script, the caller gets its directory back the moment `setup.bat`
  exits, and an Explorer window open in that folder holds it too. The files go
  on the first pass either way; it is the empty folder that has to wait.
* `INSTALL.txt` said 2.4.0 on a 2.4.1 package. `tests/test_installer.py` now
  holds it to `VERSION`, like the manuals.
* Tests: 613.

## 2.4.1 — 2026-09-18

**A sheet that prints no space code is read by its room names.** Found on
the VDD project (a cricket venue, VDB 3.0): `Run matching` refused
with *"ingest at least one drawing before running the matching step"* on a
project whose drawing was imported, scale-confirmed and carrying ten NER
markers. The drawing-space table was empty because the extractor only ever
built a space from a printed code (`PRS.006.02`), and that book prints none —
every room is labelled by name alone, over two or three stacked lines of
12 pt text, on a raster plan.

* **Name-only spaces.** On a sheet with no space code anywhere, the room-name
  labels become the spaces: lines of one size, overlapping along the reading
  axis and within 2 pt of each other on the other one, joined in reading
  order. Excluded by explicit rule: the title-block column (anchored on the
  `DRAWING NUMBER` / `DRAWING TITLE` labels — not on `SCALE`, which the scale
  bar prints mid-sheet), the legend, the client-group key, the general notes,
  the revision table, the stamps (`CONFIDENTIAL`, `NOT FOR CONSTRUCTION`,
  `KEY PLAN`), the key plan's sheet references (`311A-CKT-O`) and the NER
  markers themselves. Each such space carries `space_code = null`, confidence
  0.45 and evidence saying it was read by name. A sheet with codes is read
  exactly as before. Measured on VDD: 58 spaces on the six floor plans, none
  on the three key plans, no debris; 23 of the 94 TEAP rows matched by name,
  all held for review.
* **The refusal tells the truth.** "ingest at least one drawing" is now only
  for a project with no drawing; a drawing that yielded no space gets its own
  message (translated), which says to re-ingest on this version or check that
  the sheets carry room labels.
* **Books imported before 2.4.1 are read again, once, at start** — only those
  with zero spaces, on the same background thread as the sheet numbers,
  stamped `name_only_pass` in the drawing's summary, audited as
  `drawing.spaces_backfilled`. Markers are not touched; no re-import (which
  would double pages and NERs).
* `centre` / `center` (and `theatre` / `theater`) normalise to one word in
  name matching: the TEAP writes *Venue Media Center*, the VDD book *Centre*.
* `tests/test_i18n.py` now also checks `ValidationError` messages and
  module-level message constants against the PT dictionary; the two matching
  refusals gained PT entries.
* Manual: *How a space is recognised* (Import), *A book with no space code*
  (TEAP × drawing) and a new row in *What the app does not do*.
* Tests: 611 (47 new, `tests/test_name_only_spaces_241.py`).

## 2.4.0 — 2026-09-18

**One file to run, and nothing left behind but the application.** Asked for
after the 2.1.0 package: *"o instalador deve destruir todos os arquivos da
instalação. Ele instala, levanta os serviços e depois limpa o próprio
instalador, deixando só o APP rodando na máquina instalada."*

* **`setup.bat`**, at the root of the package. Unzip anywhere (the Downloads
  folder is fine) and double-click it. It copies the package into a folder of
  its own — `%LOCALAPPDATA%\Programs\ner-analyzer` by default, or the folder
  given as its first argument — runs `install.bat` there (the bundled Python
  into `.python\`, the packages, the component check), runs `autostart.bat`
  (the sign-in task and the watchdog, both hardened for a laptop on battery),
  starts the server through the task, waits for `/healthz` and opens the
  browser. Then it removes `vendor\` from the installed folder (100 MB of
  wheels and the runtime zip the running application never reads) and, once
  its window closes, deletes every file of the unzipped package — by the
  package's own `MANIFEST.txt`, never a blind `rmdir` of a folder that might be
  Downloads itself — and the `ner-analyzer-2.4.0-windows.zip` beside it, one
  level up, or in Downloads. `data\setup.log` in the installed folder records
  what it did.
* **An existing installation in the target is updated**, not replaced:
  `backup.bat` first, the two tasks held while the runtime is rebuilt, the
  server stopped and started again on the new version, `data\` untouched.
* `setup.bat --no-services` installs and cleans up without registering a task
  or starting anything; `--keep-installer` leaves the package and the zip in
  place. It refuses to run from a development checkout (no `MANIFEST.txt`),
  from a package without the bundled Python, into itself, or into a folder
  above or below itself.
* `install.bat`, `start.bat` and `autostart.bat` are unchanged and still work
  on their own for whoever prefers to install in place.
* The packager requires `setup.bat`; `build_package.bat` and `INSTALL.txt`
  point at it; the installation manual has a new section, and its update and
  uninstall sections say what changes when the application was installed this
  way (no `vendor\` to rebuild from: the new package's `setup.bat` is the
  update).
* Tests: 564.

## 2.3.0 — 2026-09-17

**Anything drawn on the sheet can be taken off the sheet, from the sheet.**
Asked for after a wireless point went in the wrong place: *"qualquer coisa que
eu desenho poder apagar por ali"*.

* **`delete` tool in the Drawing viewer** — the eraser. Armed, a click on a
  marker (NER, TER, IDF, COW, DIVA node), a wireless point, a route segment or
  a shaft deletes it; it stays armed until `select` is chosen. A wireless point
  and a route segment go without a question (they cost one click to redraw); a
  marker and a shaft ask first. A locked marker refuses.
* **Delete / Backspace** removes whatever is selected (ignored while typing in
  a box). The Inspector says so under its `Delete` button.
* **Route segments are selectable** (they highlight, and the Inspector shows
  them with `Delete`), and **shafts are now drawn** — a teal square with the
  page it leads to and its length — on both pages they join. Until now a shaft
  was invisible once registered, and neither could be removed at all: new
  `DELETE /projects/{id}/routes/{route_id}` and `…/verticals/{vertical_id}`,
  both audited (`route.deleted`, `vertical.deleted`; drawing a route is now
  audited too).
* **Demand per space → Wireless points** has a `Delete` button per row. A
  deleted point leaves the list at once; its port leaves the NER's load at the
  next `Run analysis`, and the notice says so.
* Unchanged: a NER is still also removed from the *NERs* screen, where
  `Removed (n)` → `Restore` brings it back.
* Tests: 558.

## 2.2.1 — 2026-09-17

**The watchdog did not watch on battery, and a server started from a remote
session died with it.** Found the same afternoon 2.2.0 went in: the server
stopped at 14:31 with nothing in `data\server.log`, and
`data\watchdog-heartbeat.txt` had not been rewritten since 13:48.

* **The watchdog task carried the Task Scheduler defaults.** `schtasks /create`
  cannot set a task's conditions, so *NER Analyzer watchdog* had
  `DisallowStartIfOnBatteries` and `StopIfGoingOnBatteries` on: from the moment
  the laptop was unplugged (13:48) it never fired again — read off the task's
  XML with the machine at 73 % on battery. New `tools\task-harden.ps1` exports a
  task's XML, turns off both battery conditions and the 72-hour limit, keeps
  `IgnoreNew`, and registers it again through `schtasks /create /xml` (no admin;
  `Register-ScheduledTask` is refused on the managed machine). `autostart.bat`
  runs it on both tasks. If it cannot, the task is left as it was and the
  script says which boxes to untick. **Run `autostart.bat` once** on an
  existing installation.
* **`tools\server-start.cmd` starts the server through the sign-in task** when
  the task exists (`schtasks /run`), and only otherwise with `start`. A process
  started with `start` belongs to the session that ran the file; run from a
  remote tool session, the server ended when that session's helper process was
  recycled. Started by the Task Scheduler it belongs to nobody's session.
* Tests: 553.

## 2.2.0 — 2026-09-17

**The TEAP rules, and the study follows it.** Four things asked for in one
conversation, and two defects the real TEAP v2.3 exposed while they were
being built.

* **From the TEAP to the drawing, never back.** A room on the drawing that no
  TEAP line asks for is not a finding: it is no longer counted by the matching
  run, returned by it, or written to the workbook (`Drawing space not in TEAP`
  and `Duplicate name/code` are gone; `Same space on several pages` lists only
  codes a TEAP line is tied to). A TEAP line the matcher could not place is
  tied by hand as before; the `Drawing space` list on *TEAP × drawing* now
  offers **the rooms no TEAP line is tied to first**, then the rest — two lines
  can rightly share a room, so nothing is hidden.
* **No ports, no work.** A TEAP space whose lines add up to zero network ports
  is matched silently and left off the worklist, its tiles, *Demand per
  space*, *Exceptions*, the coverage run and the workbook's main sheet. It is
  filtered, not deleted: the scope is worked out from the imported lines every
  time (`domain/scope.py`), so a later TEAP that gives the space a port brings
  it back, `show TEAP spaces with no ports` shows them on request, and the
  workbook lists them on a new `TEAP spaces with no ports` sheet.
  **One exception:** a space with zero ports whose lines request *wired
  connections* stays on every list, at zero ports, with the reason on the row.
  TEAP v2.3 counts no port for a `Wired Connection` line; on VEE that
  is 253 wired connections on 27 spaces — 105 on *Press Tribune – Tabled
  Positions*, 58 on the five *Photo Position FOP* spaces the 70 m limit exists
  for. No port is invented for them.
* **The same space on more than one page.** A room on a match line is labelled
  on two sheets; tied to the one with no NER it came back as "no NER on this
  level" with the NER a few metres away on the next sheet. New table
  `space_occurrence_links`: same full space code **and** the same known level
  on both pages is proof (confirmed by the rule, evidence recorded, and you
  can still say `not the same space`); the same code with a level nobody could
  read, or the same *name* with no code, is a question on the *Demand per
  space* row — `Same space` / `Not the same`, one row at a time, no bulk
  action. When the title block gave no level the row states the level the
  *drawing number* implies (`VEE-440B5-VVO-O` → LEVEL 04; it agrees with the
  title block on 68 sheets of 68 on the reference books) — enough to rule
  another floor out and to make the question a two-second one, never enough
  to link without asking; levels known and different is another floor and is never inferred.
  Once confirmed, the engine measures from every label of the space and keeps
  the shortest real measurement; the row says `measured on page N`, the marked
  PDF draws the space and its leader line on that page too, and an unconfirmed
  label is only ever reported as a hint ("page 32 shows the same code, NER 20
  is 34 m from it there") — and only when the row is not already served.
* **Wireless points.** A new tool in the *Drawing viewer*, `+Wireless`, places
  a wireless point — its own sign, sky blue, numbered WP-1, WP-2 … — and the
  tool stays armed to place the next. Each point takes **one port on the
  nearest NER within the general limit** (the next one if that room is full;
  the nearest anyway, flagged, if every room in reach is full; no room, and an
  exception, if nothing is within the limit). It counts against the room's
  capacity, is never a room, never in the register, never in the space
  figures: *Demand per space* has a `Wireless points` table and a column on
  `NER load and capacity`, the workbook a `Wireless points` sheet and two
  columns on `NERs and ports`, and both legends a `Wireless point` row.
* **Fixed — TEAP v2.3 quantity column.** v2.3 carries `TEAP v2.0`, `NEW QTY`
  and `Updated QTY`; its README says to use *Updated QTY*. The proposed mapping
  took `NEW QTY` (first on the sheet), so every line unchanged since v2.0 read
  as quantity 0. Port totals were unaffected (they come from `Network Ports`),
  the quantities on every line were wrong. `Updated QTY` now wins. **Re-import
  the TEAP once** to correct projects imported before this version.
* **Fixed — a newer TEAP now replaces the older one.** Importing a second TEAP
  file used to add its spaces beside the first file's: the VFF
  project held v2.0 and v2.3 together — 102 + 105 spaces for one venue, ports
  counted twice, and the 45 decisions made on the v2.0 rows absent from the
  v2.3 ones. An import now replaces every TEAP space of the project and lays
  the decisions back by `space_key`: the room tied by hand, the confirmation,
  the rejection, the NER chosen, `other level`, a hand-set *photographer* type
  and every `Same space` / `Not the same` answer.
* Fixed — the viewer's space → NER lines resolve the register's room ids
  (`A<id>`), so they are drawn again after an analysis.
* Tests: 550 (was 498). `tests/test_teap_rules_220.py` (49) covers all of the
  above.

Not in this version: a space that is only on a sheet with no NER, with the NER
on a neighbouring sheet of the same level, still comes back "no NER on this
level" unless you choose the room and tick `other level`. Measuring across
sheets needs the sheets of one level stitched into one coordinate frame; the
overall plans cannot anchor that (they print no space codes). Recorded in
`docs/LIMITATIONS.md`.

## 2.1.0 — 2026-09-11

**The installation package now carries its own Python.** Until 2.0.0 the
package needed Python 3.12 installed on the target computer first — which
meant a download from python.org and an installer run, on a machine the
package otherwise promised to leave untouched and offline. From 2.1.0 the
zip includes the official python.org *embeddable package* (Python 3.12.10,
64-bit, about 11 MB) and `install.bat` unpacks it into `.python\` inside
the application folder, then installs the bundled packages into it. Nothing
is required on the target computer: no Python, no internet, no
administrator rights, no registry entry. Deleting the folder still
uninstalls everything.

* `install.bat` — unpacks the runtime, writes its search path
  (`python312._pth`: standard library, the packages, `backend\`), checks the
  publisher signature of `python.exe` (Python Software Foundation),
  bootstraps pip from the bundled wheel, installs
  `requirements-lock-win.txt` offline and loads every component once. A
  development checkout without `vendor\python\` still uses the machine's
  Python and a `.venv\`, as before.
* `start.bat`, `stop.bat`, `autostart.bat`, `backup.bat`, `run-tests.bat`,
  `build_package.bat`, `tools\server-start.cmd`, `tools\watchdog.ps1` and
  `run.py` — one rule everywhere: `.python\` when it exists, else `.venv\`.
  `run.py` passes `backend\` to uvicorn explicitly (`--app-dir`), because
  the bundled runtime ignores `PYTHONPATH` and the working directory by
  design.
* `tools\make_package.py` / `build_package.bat` — fetch the runtime once
  into `vendor\python\`, refuse to build unless it hashes to the pinned
  SHA-256, require the pip and numpy wheels, exclude `.python\` from the
  package. `--without-python` builds the old kind of package.
* **Visual C++ runtime** — the numeric packages need Microsoft's
  `msvcp140.dll`, which virtually every Windows already has. When it is
  absent, the installer places the copy that numpy ships next to
  `python.exe` (app-local deployment), so even that case needs no
  administrator. `install.bat` says which of the two happened.
* `tests/test_installer.py` — the scripts, the packager and the lock file
  are held to the layout above.
* Package size: about 97 MB (was 84 MB).

Not changed: the application itself, its screens, its exports and its
database. An existing 2.0.0 installation keeps working; upgrading it to
2.1.0 is unzip-over-and-`install.bat`, which builds `.python\` beside the
old `.venv\` and prefers it from then on.

---

## 2.0.0 — 2026-09-10

First numbered release. The version replaces the `0.1.0` placeholder the
application had carried since the prototype, and 2.0 marks the shape the
tool has settled into: the canonical NER register, the eight-step workflow,
and the human-decision model in which nothing low-confidence is confirmed
silently.

Included in this baseline:

* **Workflow of eight steps** — Import, Scale, Drawing viewer, NERs,
  TEAP × drawing, Demand per space, Exceptions, Reports — plus Projects and
  Account & security.
* **NER register** — one row per physical room however many sheets draw it;
  rename without changing the identifier; criticality, capacity, lock,
  confirm, remove and restore; duplicate queue with evidence and differences;
  consolidation history with undo.
* **Drawing viewer** — the real PDF with markers, spaces, routes and the
  coverage overlay; NER, TER, IDF, COW and DIVA node markers; route and
  vertical (shaft / riser) tools; page selector showing the drawing number
  read from the title block.
* **TEAP × drawing matching** — exact code → base code → exact name →
  normalised name → synonyms → text similarity → building / level context;
  decisions stored on the TEAP line itself, so re-running never erases them;
  worklist ordered by port demand.
* **Demand per space** — the serving-room rule (the TEAP names it → you chose
  it → the nearest NER within the limit with free ports → the nearest anyway,
  flagged); the *Matched to* (from → to) column; a NER on another level
  counted against its capacity with the status *Other level — not measured*;
  readable notes; NER load and capacity.
* **Exports** — marked-up PDF (legend and NER → space lines optional),
  analysis workbook (Summary, TEAP and coverage, NERs and ports, Exceptions,
  Matching, Match exceptions, Scales) and coverage CSV; every export stamped
  with the application version.
* **Accounts** — first-account bootstrap, administrators, blocking, password
  reset with mandatory change, project sharing (read only), audit log per
  project, data statement.
* **Interface in English and Brazilian Portuguese**; exports always in
  English.
* **Operation** — windowless server at logon, watchdog every two minutes,
  offline installation package with bundled Python packages, installer that
  writes nothing outside its own folder.
* **Documentation** — user manual and installation manual (HTML and PDF,
  PT-BR / EN), © 2026 Marcelo Barbosa.
