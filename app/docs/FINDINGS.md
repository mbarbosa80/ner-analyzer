# What the real documents actually contain

Before writing any code, two real documents were analysed on the author's machine:
a 34-page venue design book (`HND`, vector PDF, 38 MB) and the event's
`TEAP v2.0.xlsx` (15 sheets, 17,496 allocation rows, 96 venues).

Five findings changed the design. They are recorded here because the brief was
written from reasonable assumptions that the documents do not bear out, and
because anyone maintaining this tool needs to know which behaviours are grounded
in measurement rather than in specification.

---

## 1. Colour does not distinguish criticality

**Brief:** blue = TER, red = critical NER, yellow = non-critical NER.

**Measured:** every equipment-room label on the drawing — `Critical NER 1`,
`Critical NER 2`, `NER 5`, `NER 6`, … `Critical NER 20`, plus `COW #1` and
`COW #2` — is drawn in the *same* red, `#cc0000`. Criticality is carried by the
word **"Critical"** in the label text. There is no yellow.

**Consequence:** classifying on colour would have mislabelled every non-critical
NER on the sheet. `pdf_ingest.py` scores label text first and treats colour as
corroborating evidence only, reporting a per-element confidence. The application's
own output still uses the brief's colour notation, because that is a useful
normalised legend — it just is not what it reads *from*.

**Also useful:** the 20 equipment rooms are labelled as extractable text with
coordinates, so detection needs neither OCR nor computer vision on this document
class. Automatic detection is far more tractable than the brief assumed.

---

## 2. The drawings already carry the TEAP space codes

**Brief:** match TEAP location names to drawing room names through a
similarity cascade.

**Measured:** the venue design book prints the *same space-code taxonomy the TEAP
uses* next to every room label — `SPT.016.01`, `TEC.004-02`, `VVO.001`,
`FNB.010-01`, `SEC.101`. 448 code instances resolving to 142 distinct base codes
across 25 of 34 pages.

**Consequence:** matching on the code is exact, explainable and
language-independent, so it runs **first**; fuzzy name matching became the
fallback it should always have been. `matching.py` implements exact code → base
code → exact name → normalised name → synonyms → similarity → context.

Measured match rate for `HND`: **46 of 70** distinct TEAP base codes (66%) match a
drawing code exactly.

---

## 3. Roughly a third of the gap is data quality, not a matching failure

Of the 24 TEAP base codes with no drawing counterpart, a substantial share are
placeholder rows (`BRS.DUM`, `FNB.DUM`, `LNS.DUM`, `LOG.DUM`, `NRG.DUM`,
`PRS.DUM`, `PRT.DUM`, `SEC.DUM`, `SPT.DUM`, `TKT.DUM`) — allocations not tied to
any real room.

Conversely, ~96 drawing codes have no TEAP allocation at all. Some rooms
legitimately need no technology; others are gaps in the plan. The tool cannot
tell which, so it does not guess.

**Consequence:** `matching.py` detects placeholder codes and reports them as a
distinct exception class instead of forcing a match or counting them as failures.
Both unmatched directions get their own exception list.

---

## 4. `Network Ports` is already the authoritative per-line total

**Measured:** across **17,495 of 17,495** checkable rows,
`Network Ports = FINAL QTY × catalogue ports-per-unit`. Zero divergences. The
`Products` sheet carries a 131-item catalogue with a per-unit port count
(a laptop is 1, a webcam is 0, a shared-internet wireless connection is 1).

**Consequence:** rule A in `demand.py` — trust the explicit line total — is both
correct and internally consistent for this workbook, which is what structurally
prevents double counting. The importer nevertheless **re-verifies** the identity
on every import and raises a reconciliation warning per line wherever the two
disagree, because this is a property of one workbook, not a guarantee.

---

## 5. The TEAP has no building or floor column, and no criticality column

The allocation sheet carries `Venue Code`, `Venue Name`, `Venue Type`, `Zone`,
`FA Code`, `Space Code`, `Space Name`, product columns, `Network Ports` — and
nothing else locating a space vertically, and nothing stating criticality.

**Consequence:**

* Level must come from the drawing match. Since the brief (correctly) forbids
  assuming cross-floor service, a space whose level is unresolved cannot be
  analysed against a NER on another page until a shaft or riser is registered.
  The tool says so explicitly rather than defaulting.
* Criticality is never invented. `demand.py` attaches a warning to every space,
  the coverage engine proposes the nearest *compatible* NER, and the assignment is
  flagged for human validation. The UI exposes a criticality selector per space.

---

## 6. Scale is explicit and per-viewport

`SCALE 1 : 200` appears as plain text on the detailed sheets and `SCALE 1 : 1500`
on the key plan, so automatic detection works well. But note that a naive parser
reads the `1/8` in `1/8" = 1'-0"` as the ratio `1:8` — a 12× error. `units.py`
matches architectural notation first and excludes those character spans from the
ratio pass. There is a test for it.

---

---

## Measured result after the fixes

`tools/validate_against.py` runs the extraction and matching engines against a
real document pair and prints this report. Run it before trusting any coverage
number from a new document family:

```bash
python tools/validate_against.py "HND_400_VVO.pdf" "TEAP v2.0.xlsx" --venue HND
```

Against the reference pair:

| | Result |
|---|---|
| Drawing | 34 pages parsed in 33 s, all vector, **0 pages needing OCR** |
| Scales | `1:200` and `1:1500` found, from the keyword-anchored tier; every page has a candidate |
| Equipment rooms | **26 detected: 7 critical NER, 14 non-critical NER, 2 COW, 3 IDF** — matching a manual read of the sheets exactly |
| Spaces on drawings | 573 |
| TEAP (`HND`) | 317 rows → 115 spaces → 697 ports |
| Demand rules | **317 of 317 lines resolved by rule A** (explicit port count), **0 reconciliation warnings** |
| Photographer areas | 4 detected and switched to the 70 m limit, including a 110-port `Main Photo Position - FOP` |
| Matching | 74 of 115 (64%); excluding the **26 placeholder rows**, **74 of 89 real spaces = 83%** |
| Review queue | 41 matches held for human validation, never auto-confirmed |

**The two extraction defects this run caught** — both invisible against synthetic
data, both now pinned by tests in `tests/test_real_world_regressions.py`:

1. **Phantom scales.** A permissive ratio pattern read `03/31/2026` in the title
   block as `1:2026`, and detail bubbles such as `1 / 410` (naming sheet 410) as
   `1:410`, `1:430`, `1:440`, `1:470`. `units.py` now matches in two tiers —
   keyword-anchored (`SCALE 1 : 200`) first and trusted, then a bare `1:N` that
   requires a colon, forbids the `1` being the tail of a longer number, and
   restricts the denominator to values drawings actually use.
2. **Phantom equipment rooms.** A substring search picked up `Rack (NER)`,
   `Rack (NER) -`, `(TER)` and `(COW/Temporary` from an annotation block. The
   marker pattern is now anchored at both ends of the label.

**One thing to be aware of in real use:** 41 of 74 matches land in the review
queue, mostly because the same space code legitimately appears on more than one
sheet (a key plan and a detail plan), which the engine correctly treats as
ambiguous rather than guessing. Restricting matching to detail sheets, or
resolving level per page first, would cut that queue substantially. It is a
workflow improvement, not a bug.

---

## Engineering note that is not a document finding

The 90 m figure is the ANSI/TIA-568 **permanent link** — installed cable length
inside a 100 m channel that reserves 10 m for patch cords. A straight-line
measurement on a plan is not that number. The `routing_slack_factor` exists for
this reason, defaults to 1.0 so the raw geometric study the brief asks for is
reproduced exactly, and should be raised to 1.25–1.40 for an arena bowl before any
result is acted on. Every evaluation reports both the geometric and the effective
distance.


---

## Second round: four defects found in live use

The first release survived its own tests and then met a real working session. Four
things went wrong, all of them mine.

### 1. The TEAP was imported without a venue filter

The master allocation plan covers **96 venues**. Imported whole against one
venue's drawings it produced **5,543 spaces instead of 115**, matched rooms at
one venue against equipment rooms at another, and left the optimiser building a
model with hundreds of thousands of variables. The field existed; it was empty and
unremarkable, which is a design failure, not a user error.

Now: the sheet's venues are listed with row counts before import, the project's
venue code is pre-selected, and a multi-venue import is refused unless the user
ticks a box.

### 2. The optimiser had no size ceiling

`time_limit_s` bounds the CP-SAT *solve*. It does not bound the Python loop that
*builds* the model. With 5,543 demands against a fallback grid of up to 4,080
positions, that loop pegged a core for minutes with no progress and no way to stop
it. There is now a hard ceiling checked twice — before the distance matrix and
after it — that returns `MODEL_TOO_LARGE` with what to narrow.

### 3. Nothing heavy could be watched or cancelled

Every long operation ran inside an HTTP handler. The health endpoint went from
20 ms to 3 s while an oversized optimisation ran; the only way out was killing the
process. Ingestion, matching, coverage and optimisation are now cancellable
background jobs reporting a stage in words.

### 4. The review queue was mostly a tie-break bug

Measured on `HND`, **41 matches sat in the review queue and 36 of them were
the same space code appearing on more than one sheet**. Fixing that took three
attempts, and the honest arithmetic is worth recording:

| | queue | composition |
|---|---|---|
| before | 41 | 36 ambiguous · 4 base-code · 1 fuzzy |
| after the first tie-break | 29 | 19 ambiguous · 9 base-code · 1 fuzzy |
| after fixing the tie-break properly | **31** | 9 ambiguous · 21 base-code · 1 fuzzy |

The count went **up by two** while the work got materially easier, and that is the
point. Three separate bugs were in the way:

* the tie-break compared **full** space codes, so a sub-index difference
  (`PRS.006.02` against `PRS.006.01`) blocked it on 11 rooms;
* it never handled the case where the top two candidates are on the **same** page —
  a code tagged twice on one sheet is a repeated tag, not a question about which
  sheet, and that accounted for 8 more;
* it treated any page-rank difference as evidence, including a 4% gap across six
  `SEC.005-*` rooms, which is noise. A margin is now required, and those six
  correctly stay for a human.

What remains is no longer "which of four sheets is this room on?" at 0.70
confidence. It is "the base code matches and the sub-index differs" at 0.90 — a
two-second judgement. Because twenty-one identical two-second judgements is still
the friction that gets a review abandoned, the queue can now be confirmed in bulk
by method, with each row audited individually.

**The lesson worth keeping:** a smaller review queue is not automatically a better
one. Ask what each remaining item is asking the human, and whether the tool has
earned the right to stop asking.
