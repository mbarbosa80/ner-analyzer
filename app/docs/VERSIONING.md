# Document versioning — the design, and why it is not built yet

Status: **proposed, not implemented** (2026-08-27).
Decision: Marcelo asked for this to be documented rather than built for now.

---

## The workflow this has to serve

1. Analyse VDB v1. Decide: remove NER 12, reposition NER 7, accept suggested NER Z.
2. Send those decisions to the VNI team.
3. VNI redraws. VDB v2 arrives.
4. Upload v2 and answer one question: **did they do what I asked?**

Step 4 is not "re-run the analysis". It is a *reconciliation* between the decisions
recorded on v1 and what the new drawing actually shows. Nothing in the tool does
that today.

---

## What happens today, and why it is worse than "unsupported"

Uploading a second VDB into the same project does not fail. It **silently
corrupts the analysis**.

Page number is an integer scoped to the *project*, not to the document:
`Element.page`, `DrawingSpace.page`, `Zone.page`, `RouteSegmentRow.page`, and the
dictionary returned by `services.scale_map()` — all of them. That function's own
docstring already admits it:

> Pages share one numbering space across drawings in the MVP; a project with
> several PDFs should keep them in one file or use one project per document.

So with v1 and v2 in one project, page 5 of v2 overwrites the scale of page 5 of
v1 (dictionary insertion order decides which), and `compute_coverage` will
measure the distance from a marker on the *old* drawing to a space on the *new*
one as though they were the same plan. The numbers stay plausible. They are
wrong.

**Interim rule, agreed 2026-08-27:** when v2 arrives, create a **new project**
for it and carry the v1 NER register across as an exported XLSX for manual
reference. Reconciliation is done by eye. No number is wrong; the comparison is
just manual.

One project per *venue* remains correct. One project per *version of the same
venue* is the workaround, and its cost is precisely that the v2 project has no
knowledge of the decisions taken on v1.

---

## The half that is already solved

The canonical/occurrence split built for V2 is exactly the versioning primitive:

* **`NerAsset`** — the physical room. Survives any change of document. Its `id`
  and `code` are immutable. It carries the name, classification, keep/reject
  decision, capacity, notes and the whole audit trail.
* **`Element`** — one occurrence of that room in *one* document, on one page, at
  one coordinate, with the confidence of that one detection. It already carries
  `drawing_id` and `document_kind`.

Nothing a human decided lives on the document side. So a new version creates new
*occurrences*, re-links them to the assets that already exist, and the diff falls
out of the model rather than having to be computed against a stored snapshot of
the drawing:

| Occurrences | Reading |
|---|---|
| in v1 **and** v2 | the room is still there |
| in v1, none in v2 | **removed** from the new drawing |
| in v2, matching no asset | **new** in this version |
| in both, different coordinate | **moved**, and by how much |

The re-link rule is the existing one in `domain/consolidation.py`: identical
normalised label is necessary but not sufficient; level and building agreement is
what makes it automatic; a conflict disqualifies; an unknown level is a question,
not an agreement.

---

## What has to be built

### 1. Page namespace per document — the prerequisite

Key everything by `(drawing_id, page)` instead of `page`. This touches the
coverage engine, the viewer, zones, routes, vertical links, the scale map and a
data migration for existing projects.

Nothing else on this page works without it, and it is the same refactor already
listed as recommended step 2 in `LIMITATIONS.md`.

### 2. Version as a first-class entity

`Drawing` gains `version_label` (e.g. *"June 2026 rev C"*), `version_no`
(sequential per project per document family), `supersedes_id` and `is_current`.

Only the current version feeds the analysis. Superseded versions stay queryable,
so a report issued against v1 remains reproducible — which is the point of having
issued it.

### 3. The change request — a frozen baseline

**This is the piece that is easy to forget and impossible to add afterwards.**

There is no artefact today that says "here is what I want changed". It cannot be
reconstructed later either: if the request goes out, the reviewer changes their
mind the following week, and v2 then arrives, nothing can distinguish *the
drawing diverging from what was asked* from *the reviewer diverging from what
they asked*.

So the change request must be a **snapshot frozen at the moment it is issued** —
the decisions as they stood, with a revision number, a date and a recipient. It
is the baseline the new version is measured against. Without it the diff compares
the new drawing to a moving target and means nothing.

Its content comes from the register: assets with `keep_decision = reject`, assets
with `status = reposition_proposed` (current position, proposed position and the
recorded reason), and confirmed suggestions.

### 4. The reconciliation screen

For every item in the change request, the new version yields one of four
verdicts:

| Verdict | Meaning |
|---|---|
| **Applied** | asked to remove NER 12; v2 has no NER 12 |
| **Not applied** | asked to remove it; it is still there |
| **Applied differently** | asked to move it to X; it moved to Y |
| **Changed without being asked** | a room appeared, vanished or moved with no decision behind it |

The third and fourth are the ones that earn the screen. A naive comparison marks
"applied differently" as done, and never surfaces the fourth at all — yet the
fourth is what catches a drafting error.

---

## Two rules the implementation must hold

**A decision survives a new version, but not untouched when its evidence
changed.** If a room was confirmed critical against v1 and its label or position
changed in v2, the confirmation cannot silently continue to hold — it becomes
*"confirmed, but the basis moved: re-check"*, naming what changed. The opposite
(resetting every decision on each version) would throw away weeks of curation and
guarantees nobody upgrades.

**Scale is per page per document.** v2's pages need their own confirmation.
Inheriting it may be *proposed* when the sheet title and the detected scale both
match — proposed, never automatic.

---

## Sequencing note

Item 1 is the same refactor that level extraction needs, and item 4 depends on
level to re-link occurrences confidently. Building versioning *before* improving
level extraction from sheet titles means nearly every v2 re-link lands in the
manual review queue. It works, but it is a great deal of hand work — see
`LIMITATIONS.md`.

Recommended order: level extraction → page namespace → version entity → change
request → reconciliation.

---

## The same mechanism covers the TEAP

A TEAP v2.1 is another document version against the same register: new demand
rows, re-matched to the same spaces, with a diff of what the demand did. Not in
scope here, but the model above accommodates it without a second design.

---

# Part 2 — the refinement lifecycle

Added 2026-08-27 after Marcelo described the full loop: the app is not used once.
It is used to **refine** the TEC delivery across many VDB versions, driving toward
shorter distances and *fewer* NERs, until a design freeze near delivery.

Three things follow from that, and each breaks or extends something above.

---

## 5. Renumbering breaks label-based re-linking

The stated case: *delete NER007, then rename NER033 — the last one — to NER007.*

The internal identity holds. `NER-0033` keeps its immutable code, gains the
display name `NER 007`, and the rename is in `NerNameHistory`. Every report ever
issued stays traceable. That part works, and it is why the code is immutable.

**The re-link does not.** Two problems, both real today:

### 5a. A rejected asset still competes for its old label

`migrate.backfill_assets()` builds its index from every asset that is not
`deleted_at` and not `merged_into_id`. A **rejected** asset — `keep_decision =
reject`, `status = rejected` — is still indexed under its display name.

So after the renumber, two assets answer to `NER 007`: the rejected original and
the renamed survivor. They are on the same level and in the same building, so
label, level and building all agree for both. The score is identical and the
tie-break is arbitrary. The v2 marker can be linked to **the room that was
removed** — the worst possible answer, because it silently resurrects a deletion.

Minimum fix: a rejected or removed asset **retires its label**. It keeps it in
`aliases` and in the history, and stops competing for automatic re-link. If a v2
marker really does match only a retired asset, that is a question for a human
("this room was rejected but the new drawing still shows it"), never an automatic
link.

### 5b. Across versions, the label is the *weakest* signal

Consolidating duplicates *within* one document and re-linking occurrences *across*
two versions look similar and are not the same problem.

Within a version, two markers with the same label are probably one room drawn
twice — the label is the primary evidence, position is secondary because the same
room appears at different coordinates on a key plan and a detail sheet.

Across versions, after a renumber, that inverts:

| Signal | Within one version | Across versions |
|---|---|---|
| identical label | strong | **weak** — renumbering is expected |
| same coordinate (± tolerance), same level | weak (different viewports) | **strong** — a room that did not move |
| label changed, position identical | suspicious | **normal** — this is a renumber |
| label identical, position far apart | probably two rooms | **probably a renumber**, and the label is now on a different room |

So version re-linking needs its own rule, ordered position-first:

1. same level **and** coordinate within tolerance → same room, whatever the label
   says; if the label changed, record it as a **renumber** and surface it.
2. coordinate moved but the label and level match and no other asset claims that
   position → same room, **moved**; report the distance.
3. anything else → a question, with both readings shown.

Tolerance has to come from the page scale, not from raw PDF units — the same
number of units means different metres on a 1:100 and a 1:200 sheet.

Using the existing `domain/consolidation.py` rule for both jobs would be a
mistake. Share the `Candidate`/`Comparison` shapes; do not share the weights.

### 5c. An operational risk that costs nothing to avoid

The immutable code protects the database. It does **not** protect the conversation
with the VNI team. If a change request goes out saying *"move NER 007"* while
`NER 007` is being reassigned from one physical room to another, the two sides
will mean different rooms by the same name, and both will believe they agree.

Every change request must therefore carry, per row: the **internal code**, the
**current display name** and the **previous name**. Cheap, and it is the only
thing standing between a renumber and a wrong room being rebuilt.

---

## 6. Reducing the NER count — what the tool can and cannot prove

The goal is a significantly smaller set of NERs per venue. The tool can support
that honestly, but only up to a line it must not cross.

**What it can prove:** that a room is *spatially* redundant — every area it
serves is reachable, within the applicable limit, from another room that is being
kept. That is a complete, checkable statement, and it is the evidence needed to
argue for a removal.

The missing piece today is the direct question: **"if I remove this NER, what
happens?"** `redundancy_candidates()` only finds rooms carrying no load at all.
The useful analysis is one step further — for a room that *is* loaded, re-run the
assignment with it excluded and report, per area it currently serves: still
covered and by whom, or falls out. Nothing in the engine prevents this; it is a
second `compute_coverage()` run over the same inputs with one NER removed.

**What it cannot prove:** that the room is *removable*. Power, cooling, physical
space, security, maintenance access, A/B route independence and operational
continuity are not modelled from a drawing and never will be. Capacity is
routinely unknown.

So the honest framing, and the one to use internally: the app produces the
**shortlist and the evidence**; the engineering decision stays with a person, room
by room. "The app cut NERs from 26 to 18" is a claim that needs 8 defensible
evidence trails behind it, and the register plus the audit log is where they live.

**The artefact this loop actually wants** is a trend across versions: NER count,
worst serving distance, total cable length, areas out of coverage — one row per
analysed version. It is nothing more than the scenario summaries already stored,
lined up by document version. It is also the single most useful thing to put in
front of a stakeholder, and it is not built.

---

## 7. Freeze — and why it is the same object as the change request

Near delivery, names and positions stop being editable.

A freeze is not a per-room `locked` flag repeated 26 times. It is a project state
with three properties:

* **It refuses, out loud.** A rename, move, rejection or consolidation attempted
  on a frozen project is refused with a message naming the freeze — never
  silently ignored, never partially applied.
* **It is reversible only by an explicit, audited act.** Unfreezing takes a
  reason and is written to the audit log like any other decision. A toggle
  somebody can flip absent-mindedly is not a freeze.
* **It produces a baseline**: the definitive register, snapshotted. That snapshot
  *is* the deliverable.

Which makes the unification worth stating plainly: **the change-request snapshot
and the freeze baseline are the same primitive.** One `RegisterSnapshot` entity —
named, dated, immutable, holding the full register state — serves both
*"revision 3, issued to VNI on 12 October"* and *"design freeze, 15 November"*.
Build it once.

After a freeze, a newly arriving VDB can still be **checked** against the
baseline, and must not be able to change it. That check is the acceptance test:
*did the final drawing match the frozen design?* It is the same reconciliation
screen as section 4, pointed at the freeze snapshot instead of at a change
request.

---

## Revised build order

1. **Level extraction** from sheet titles — everything downstream re-links better.
2. **Page namespace** `(drawing_id, page)` — the prerequisite.
3. **`RegisterSnapshot`** — serves the change request now and the freeze later.
   Cheap, and it is the piece that cannot be added retroactively.
4. **Version entity** on `Drawing`.
5. **Version re-link rule** (position-first, section 5b) plus label retirement for
   rejected assets (5a).
6. **Reconciliation screen** with the four verdicts, plus renumbering as a
   reported event.
7. **Removal impact analysis** ("what happens if I delete this NER") and the
   **cross-version trend**.
8. **Project freeze** on top of `RegisterSnapshot`.

Items 3 and 5a are small and are the two whose absence causes silent, wrong
answers. Everything else is additive.
