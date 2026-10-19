/**
 * The single source of truth for the visual notation, shared by the viewer and
 * the permanent legend so the two can never drift apart.
 */

export const KIND_COLOUR: Record<string, string> = {
  TER: "#0000cc",
  NER_CRITICAL: "#cc0000",
  NER_NONCRITICAL: "#e6b800",
  IDF: "#7a7a7a",
  COW: "#8c5a00",
  // Purple, as asked on 3 Sep 2026. The proposal colour used to be this
  // shade; there are no proposals any more, so nothing else claims it.
  DIVA: "#8000a0",
  // Sky blue, and its own shape (the fan of a Wi-Fi sign): a wireless point is
  // demand a person drew, not a room. Same value as ``COLOURS[WIRELESS]`` in
  // ``reports.py``.
  WIRELESS: "#0096c7",
  // A NER reference on a key plan (2.7.0): the colour of the NER it stands
  // for; the dashed ring is what tells it apart. Same values as
  // ``COLOURS[NER_*_REF]`` in ``reports.py``.
  NER_CRITICAL_REF: "#cc0000",
  NER_NONCRITICAL_REF: "#e6b800",
  // A TER, COW or DIVA reference on a key plan (2.8.0): the room's colour,
  // the dashed ring. Same values as ``COLOURS[*_REF]`` in ``reports.py``.
  TER_REF: "#0000cc",
  COW_REF: "#8c5a00",
  DIVA_REF: "#8000a0",
  SHAFT: "#00807a",
  UNKNOWN: "#555555",
};

export const KIND_LABEL: Record<string, string> = {
  TER: "TER",
  NER_CRITICAL: "NER — critical",
  NER_NONCRITICAL: "NER — non critical",
  IDF: "IDF / MDF",
  COW: "COW / temporary",
  DIVA: "DIVA node",
  WIRELESS: "Wi-Fi — space with wireless",
  NER_CRITICAL_REF: "NER reference — critical (key plan)",
  NER_NONCRITICAL_REF: "NER reference — non critical (key plan)",
  TER_REF: "TER reference (key plan)",
  COW_REF: "COW reference (key plan)",
  DIVA_REF: "DIVA node reference (key plan)",
  SHAFT: "Shaft / riser",
  UNKNOWN: "Unclassified",
};

/** The kinds a person can place with the toolbar, in toolbar order. */
export const PLACEABLE_KINDS = ["NER_CRITICAL", "NER_NONCRITICAL", "TER", "IDF", "COW", "DIVA"];

/** Drawn, moved, renamed and deleted by hand — and part of nothing else. No
 *  register row, no TEAP link, no reach circle. */
export const VISUAL_ONLY_KINDS = new Set(["TER", "IDF", "COW", "DIVA"]);

/** Demand drawn by hand: never a room, never in the register, never serving —
 *  and each one takes a port on the NER that reaches it. */
export const DEMAND_KINDS = new Set(["WIRELESS"]);

/** A NER *reference* drawn by hand on a key plan (2.7.0): a pointer to a room
 *  drawn on another sheet, named after it. Drawn only — no register row, no
 *  TEAP link, nothing counted — but ringed with the reach circles to the
 *  sheet's scale, because that is what it is drawn for. */
export const NER_REFERENCE_KINDS = new Set(["NER_CRITICAL_REF", "NER_NONCRITICAL_REF"]);

/** Every reference kind: the NER ones, and (2.8.0) a TER, a COW or a DIVA
 *  node pointed at on a key plan — dashed ring, no circles, nothing counted. */
export const REFERENCE_KINDS = new Set([...NER_REFERENCE_KINDS, "TER_REF", "COW_REF", "DIVA_REF"]);

/** The kind a reference stands for. */
export const REFERENCE_OF: Record<string, string> = {
  NER_CRITICAL_REF: "NER_CRITICAL",
  NER_NONCRITICAL_REF: "NER_NONCRITICAL",
  TER_REF: "TER",
  COW_REF: "COW",
  DIVA_REF: "DIVA",
};

/** Reach circles are drawn around a NER — and around a reference to one.
 *  Not around a TER, a COW or a DIVA reference: the real ones have none. */
export function drawsReach(kind: string | null | undefined): boolean {
  return canServe(kind) || (!!kind && NER_REFERENCE_KINDS.has(kind));
}

/** A named area drawn by hand (2.8.0) — "BTOC", "TER", a compound — to point
 *  something out on the sheet. Illustrative only: one colour for all of them,
 *  apart from every status fill and every marker, and part of no figure.
 *  Same value as ``AREA_COLOUR`` in ``reports.py``. */
export const AREA_COLOUR = "#3d5980";
export const AREA_FILL_OPACITY = 0.16;

export const PROPOSED_COLOUR = "#8000a0";
export const REMOVAL_COLOUR = "#737373";

/**
 * The ring every marker is drawn with, on screen and in the exported PDF.
 *
 * A venue design book is dense black linework on white, and a filled dot in
 * yellow or mid-blue sitting on top of it does not read as a separate object —
 * it reads as part of the drawing. A hairline black ring separates the marker
 * from whatever it lands on without changing what its colour means, which is
 * the only job the colour has.
 */
export const MARKER_RING = "#000000";

/**
 * The only rooms that may be offered as "this one serves that space".
 *
 * A NER, and nothing else. A TER, an IDF and a COW are recorded, drawn, moved
 * and deleted like any other marker — they are on the plan because the plan
 * should show what is in the building — but none of them is ever an option to
 * serve a functional area, and none of them gets a coverage radius.
 *
 * Filtering the dropdown with this is a courtesy; the server refuses the
 * assignment outright, which is what actually holds the line.
 */
export const SERVING_KINDS = new Set(["NER_CRITICAL", "NER_NONCRITICAL"]);

export function canServe(kind: string | null | undefined): boolean {
  return !!kind && SERVING_KINDS.has(kind);
}

/**
 * The colour a marker's *name* is written in, which is not always the colour of
 * its dot. Non-critical yellow is a good fill and a bad ink: `#e6b800` text on
 * the white of a drawing sheet is close to unreadable, and the label is the
 * half of the marker that carries the information. The dot keeps the notation
 * colour; the text gets a shade dark enough to read.
 */
export const KIND_LABEL_COLOUR: Record<string, string> = {
  ...KIND_COLOUR,
  NER_NONCRITICAL: "#7a5c00",
  NER_NONCRITICAL_REF: "#7a5c00",
};

/** The white tag every name on the sheet sits on (2.8.0). A name written
 *  straight onto dense CAD linework read as part of the drawing; on a tag it
 *  reads as a label. Marcelo, 22 Sep 2026: "um pouco mais visíveis". */
export const LABEL_TAG_FILL = "#ffffff";
export const LABEL_TAG_OPACITY = 0.82;

export const STATUS_COLOUR: Record<string, string> = {
  served: "#2ea44f",
  near_limit: "#f28c1a",
  out_of_limit: "#d81b1b",
  insufficient_capacity: "#d81b1b",
  match_not_confirmed: "#f28c1a",
  scale_not_confirmed: "#8c8c8c",
  route_not_validated: "#8c8c8c",
  not_analysable: "#5a5a5a",
  // Served from a room on another page/level, ports counted, distance not
  // measured (no vertical route registered yet). Neither green nor red would
  // be honest; the same grey as the other "not measured" states.
  cross_level_not_measured: "#8c8c8c",
  // No room on the drawing, NER chosen by hand: counted, not measured.
  assigned_not_placed: "#8c8c8c",
};

/**
 * The four piles a person reads the Demand list in (2.7.0) — the same
 * ``Group`` as ``distance.py``, and the same labels. The engine's status is
 * precise (match not confirmed, scale not confirmed, no NER reaches it…) and
 * every value is a real reason; but from the desk they are one situation:
 * the space is not resolved and needs a room on the drawing or a NER. So the
 * screen shows the group, with the precise status as the line under it.
 */
export const GROUP_OF: Record<string, string> = {
  served: "served",
  near_limit: "served",
  out_of_limit: "problem",
  insufficient_capacity: "problem",
  cross_level_not_measured: "not_measured",
  assigned_not_placed: "not_measured",
  match_not_confirmed: "pending",
  scale_not_confirmed: "pending",
  route_not_validated: "pending",
  not_analysable: "pending",
};

export const GROUP_LABEL: Record<string, string> = {
  served: "Served",
  problem: "Out of limit / over capacity",
  not_measured: "Served — not measured",
  pending: "Pending — needs a room or a NER",
};

export const GROUP_COLOUR: Record<string, string> = {
  served: "#2ea44f",
  problem: "#d81b1b",
  not_measured: "#8c8c8c",
  pending: "#f28c1a",
};

/** The order the groups are listed in: what is done first, what needs a hand last. */
export const GROUP_ORDER = ["served", "problem", "not_measured", "pending"];

export function groupOf(status: string | null | undefined): string {
  return (status && GROUP_OF[status]) || "pending";
}

export const STATUS_LABEL: Record<string, string> = {
  served: "Served",
  near_limit: "Near the limit",
  out_of_limit: "Out of limit",
  insufficient_capacity: "Insufficient capacity",
  match_not_confirmed: "Match not confirmed",
  scale_not_confirmed: "Scale not confirmed",
  route_not_validated: "Route not validated",
  not_analysable: "No NER reaches it",
  cross_level_not_measured: "Other level — not measured",
  assigned_not_placed: "No room on the drawing — NER chosen by you",
};

/**
 * Seven rows, and nothing else.
 *
 * The legend used to print eleven, most of them for states the plan in front of
 * you does not contain — a proposed NER on a sheet with no proposals, a
 * redundancy candidate on a study that never ran the optimiser. A legend that
 * describes shapes the reader cannot find is not a key, it is noise, and it was
 * wide enough (320 pt) to sit on top of the drawing while being it.
 *
 * What is left is what a reader can actually find on the sheet in front of
 * them: the six things a marker can be, plus the one annotation the plan
 * draws over a space. IDF, COW and the DIVA node were added on 3 Sep 2026 —
 * the viewer had been painting IDF grey and COW brown with no row to say so,
 * which is the other way a key can fail. The area fills still exist and are
 * still drawn; they are read from the status column of the coverage table,
 * which names them in words rather than in colour.
 */
export const LEGEND_ROWS: { label: string; colour: string; style: string }[] = [
  { label: "TER", colour: KIND_COLOUR.TER, style: "dot" },
  { label: "NER — critical", colour: KIND_COLOUR.NER_CRITICAL, style: "dot" },
  { label: "NER — non critical", colour: KIND_COLOUR.NER_NONCRITICAL, style: "dot" },
  { label: "IDF / MDF", colour: KIND_COLOUR.IDF, style: "dot" },
  { label: "COW / temporary", colour: KIND_COLOUR.COW, style: "dot" },
  { label: "DIVA node", colour: KIND_COLOUR.DIVA, style: "dot" },
  { label: "Wi-Fi — space with wireless", colour: KIND_COLOUR.WIRELESS, style: "wifi" },
  // A reference on a key plan (2.7.0; TER, COW and DIVA too since 2.8.0): a
  // dot in the room's colour with a dashed ring — a pointer to a room drawn
  // on another sheet, counted nowhere. A NER reference also gets the reach
  // circles to this sheet's scale.
  { label: "Reference (key plan) — drawn only, not counted", colour: KIND_COLOUR.NER_CRITICAL_REF, style: "reference" },
  // A named area drawn by hand (2.8.0): illustrative, nothing measured.
  { label: "Named area — illustrative only", colour: AREA_COLOUR, style: "area" },
  // The orange box the plan draws around a space whose TEAP × drawing match
  // nobody has validated. It went out with the other eight rows and came back
  // on its own: unlike a proposed NER or a redundancy candidate, this one is
  // drawn on a real sheet on a real run, and a mark on a construction document
  // that the key does not explain is worse than no key at all.
  { label: "Match not confirmed", colour: STATUS_COLOUR.match_not_confirmed, style: "outline" },
];

export const DISCLAIMER =
  "This tool supports the design process. It does not replace engineering approval, " +
  "a site survey, cable route validation or physical inspection.";

export function fmtLen(metres: number | null | undefined, units: string): string {
  if (metres == null) return "—";
  const ft = metres / 0.3048;
  if (units === "ft") return `${ft.toFixed(1)} ft`;
  if (units === "both") return `${metres.toFixed(1)} m (${ft.toFixed(1)} ft)`;
  return `${metres.toFixed(1)} m`;
}
