import { t } from "./i18n";

const BASE = "/api";

/**
 * Whether the server is reachable at all — as opposed to answering an error.
 *
 * A request that never reaches the server (the browser's "Failed to fetch")
 * means the server is down or restarting: on 22 Sep 2026 that read on screen
 * as a sign-in page that refused the password and a project that would not
 * open. Every such failure flips this to ``false``; the shell polls
 * ``/healthz`` until it answers and flips it back (2.6.1).
 */
export const SERVER_UNREACHABLE =
  "the server is not answering — it is restarted automatically within about two minutes, and this page reconnects by itself";
let reachable = true;
const listeners = new Set<(up: boolean) => void>();
export function onConnection(cb: (up: boolean) => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}
function setReachable(up: boolean) {
  if (up === reachable) return;
  reachable = up;
  listeners.forEach((cb) => cb(up));
}
export function isReachable(): boolean { return reachable; }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers:
        init?.body instanceof FormData
          ? undefined
          : { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    setReachable(false);
    throw new Error(t(SERVER_UNREACHABLE));
  }
  setReachable(true);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status line */
    }
    // Every server message the interface ever shows passes through here, so
    // this is the only place that needs to translate them. Anything without a
    // translation — the internal diagnostics — comes through in English on
    // purpose: those are the strings we quote to each other when something
    // breaks, and a translated one is a string nobody can search for.
    throw new Error(t(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  meta: () => req<any>("/meta"),
  /** True when the server answers ``/healthz``; never throws. */
  health: async (): Promise<boolean> => {
    try {
      const r = await fetch("/healthz", { cache: "no-store" });
      setReachable(r.ok);
      return r.ok;
    } catch {
      setReachable(false);
      return false;
    }
  },

  // --- access control ------------------------------------------------------
  authState: () => req<any>("/auth/state"),
  login: (body: { username: string; password: string }) =>
    req<any>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  bootstrap: (body: { username: string; password: string; display_name?: string }) =>
    req<any>("/auth/bootstrap", { method: "POST", body: JSON.stringify(body) }),
  logout: () => req<any>("/auth/logout", { method: "POST" }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    req<any>("/auth/password", { method: "POST", body: JSON.stringify(body) }),

  adminUsers: () => req<any>("/admin/users"),
  createAccount: (body: any) =>
    req<any>("/admin/users", { method: "POST", body: JSON.stringify(body) }),
  setAccountAdmin: (id: number, value: boolean) =>
    req<any>(`/admin/users/${id}/admin`, { method: "POST", body: JSON.stringify({ value }) }),
  setAccountActive: (id: number, value: boolean) =>
    req<any>(`/admin/users/${id}/active`, { method: "POST", body: JSON.stringify({ value }) }),
  resetAccountPassword: (id: number, new_password: string) =>
    req<any>(`/admin/users/${id}/password`, {
      method: "POST",
      body: JSON.stringify({ new_password }),
    }),
  deletionImpact: (id: number) => req<any>(`/admin/users/${id}/deletion-impact`),
  deleteAccount: (id: number, reason: string, confirm_username: string) =>
    req<any>(`/admin/users/${id}/delete`, {
      method: "POST",
      body: JSON.stringify({ reason, confirm_username }),
    }),

  setVisibility: (id: number, visibility: string) =>
    req<any>(`/projects/${id}/visibility`, {
      method: "POST",
      body: JSON.stringify({ visibility }),
    }),

  listProjects: () => req<any[]>("/projects"),
  createProject: (body: { name: string; venue_code?: string; description?: string }) =>
    req<{ id: number }>("/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: number) => req<any>(`/projects/${id}`),
  deleteProject: (id: number) => req<void>(`/projects/${id}`, { method: "DELETE" }),
  updateSettings: (id: number, body: any) =>
    req<any>(`/projects/${id}/settings`, { method: "PATCH", body: JSON.stringify(body) }),

  uploadDrawing: (id: number, file: File, background = true) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<any>(`/projects/${id}/drawings?background=${background}`, {
      method: "POST",
      body: fd,
    });
  },
  //: Take one book out of the project (4.6.0), and what that would take with it.
  deleteDrawing: (id: number, drawingId: number) =>
    req<any>(`/projects/${id}/drawings/${drawingId}`, { method: "DELETE" }),
  drawingImpact: (id: number, drawingId: number) =>
    req<any>(`/projects/${id}/drawings/${drawingId}/impact`),

  //: The project package (4.6.0): every row and document of a project, to
  //  hand the work to another computer.
  exportProject: (id: number) =>
    req<any>(`/projects/${id}/export?background=true`, { method: "POST" }),
  exportDownloadUrl: (id: number, filename: string) =>
    `${BASE}/projects/${id}/export/${encodeURIComponent(filename)}`,
  importProject: (file: File, name = "") => {
    const fd = new FormData();
    fd.append("file", file);
    return req<any>(`/projects/import?background=true&name=${encodeURIComponent(name)}`, {
      method: "POST",
      body: fd,
    });
  },
  drawingFileUrl: (id: number, drawingId: number) =>
    `${BASE}/projects/${id}/drawings/${drawingId}/file`,
  pageImageUrl: (id: number, page: number, dpi = 110) =>
    `${BASE}/projects/${id}/pages/${page}/image?dpi=${dpi}`,

  setScale: (id: number, page: number, body: any) =>
    req<any>(`/projects/${id}/pages/${page}/scale`, { method: "POST", body: JSON.stringify(body) }),
  //: Say whether a page is a key plan (2.13.0): only illustrative, out of every
  //  TEAP × drawing crossing. Ties to rooms there are released and the
  //  matching runs again.
  setKeyPlan: (id: number, page: number, keyPlan: boolean) =>
    req<{ page: number; key_plan: boolean; released_decisions: number; cleared_matches: number;
          matching?: any; matching_skipped?: string; counted_here: string[] }>(
      `/projects/${id}/pages/${page}/key-plan`,
      { method: "POST", body: JSON.stringify({ key_plan: keyPlan }) }),
  //: Confirm every page that holds a scale, in one act. Pages with none are
  //  skipped and named in the answer.
  confirmAllScales: (id: number) =>
    req<{ confirmed: number[]; already_confirmed: number[]; skipped_no_scale: number[] }>(
      `/projects/${id}/pages/scale/confirm-all`, { method: "POST" }),

  uploadTeap: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<any>(`/projects/${id}/teap`, { method: "POST", body: fd });
  },

  //: Register rooms with a position, so the viewer can draw the ones the
  //  drawing itself does not carry a marker for.
  nerAssetPositions: (id: number, page?: number) =>
    req<any>(`/projects/${id}/ner-assets/positions${page ? `?page=${page}` : ""}`),
  //: Move a register room on the drawing. The rooms the sheet does not carry
  //  have no marker to drag, so this is the only way to reposition them.
  moveNer: (id: number, nerId: number, body: { page: number; x: number; y: number; reason?: string }) =>
    req<any>(`/projects/${id}/ners/${nerId}/position`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  previewVenues: (id: number, teapId: number, body: any) =>
    req<any>(`/projects/${id}/teap/${teapId}/preview-venues`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  importTeap: (id: number, teapId: number, body: any, background = true) =>
    req<any>(`/projects/${id}/teap/${teapId}/import?background=${background}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  teapSpaces: (id: number) => req<any[]>(`/projects/${id}/teap-spaces`),
  patchTeapSpace: (id: number, spaceId: number, body: any) =>
    req<any>(`/projects/${id}/teap-spaces/${spaceId}`, { method: "PATCH", body: JSON.stringify(body) }),

  elements: (id: number, page?: number) =>
    req<any[]>(`/projects/${id}/elements${page ? `?page=${page}` : ""}`),
  createElement: (id: number, body: any) =>
    req<any>(`/projects/${id}/elements`, { method: "POST", body: JSON.stringify(body) }),
  patchElement: (id: number, elId: number, body: any) =>
    req<any>(`/projects/${id}/elements/${elId}`, { method: "PATCH", body: JSON.stringify(body) }),
  //: A NER marker's delete removes the NER — every page, the NERs list
  //  (2.18.1); ``scope: "marker"`` deletes this one drawing of it only.
  deleteElement: (id: number, elId: number, scope: "ner" | "marker" = "ner") =>
    req<void>(`/projects/${id}/elements/${elId}?scope=${scope}`, { method: "DELETE" }),
  wirelessTieOptions: (id: number) => req<any[]>(`/projects/${id}/wireless/tie-options`),

  drawingSpaces: (id: number, page?: number) =>
    req<any[]>(`/projects/${id}/drawing-spaces${page ? `?page=${page}` : ""}`),
  patchDrawingSpace: (id: number, spaceId: number, body: any) =>
    req<any>(`/projects/${id}/drawing-spaces/${spaceId}`, { method: "PATCH", body: JSON.stringify(body) }),

  runMatching: (id: number, background = true) =>
    req<any>(`/projects/${id}/matching/run?background=${background}`, { method: "POST" }),
  matches: (id: number, onlyReview = false, includeZero = false) =>
    req<any[]>(`/projects/${id}/matches?only_review=${onlyReview}&include_zero=${includeZero}`),
  bulkDecideMatches: (id: number, body: any) =>
    req<any>(`/projects/${id}/matches/bulk`, { method: "POST", body: JSON.stringify(body) }),
  decideMatch: (id: number, matchId: number, body: any) =>
    req<any>(`/projects/${id}/matches/${matchId}`, { method: "PATCH", body: JSON.stringify(body) }),
  undoMatch: (id: number, matchId: number, justification = "") =>
    req<any>(`/projects/${id}/matches/${matchId}/undo`,
             { method: "POST", body: JSON.stringify({ justification }) }),

  //: Named areas drawn by hand (kind "area", 2.8.0) — and the older zone
  //  kinds, which still load.
  zones: (id: number, page?: number) =>
    req<any[]>(`/projects/${id}/zones${page ? `?page=${page}` : ""}`),
  createZone: (id: number, body: any) =>
    req<any>(`/projects/${id}/zones`, { method: "POST", body: JSON.stringify(body) }),
  patchZone: (id: number, zoneId: number, body: any) =>
    req<any>(`/projects/${id}/zones/${zoneId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteZone: (id: number, zoneId: number) =>
    req<void>(`/projects/${id}/zones/${zoneId}`, { method: "DELETE" }),

  routes: (id: number) => req<any[]>(`/projects/${id}/routes`),
  /** ``whole``: every segment of the named route (R1, R2 …) it belongs to. */
  deleteRoute: (id: number, routeId: number, whole = false) =>
    req<void>(`/projects/${id}/routes/${routeId}${whole ? "?whole=true" : ""}`, { method: "DELETE" }),
  deleteVertical: (id: number, verticalId: number) =>
    req<void>(`/projects/${id}/verticals/${verticalId}`, { method: "DELETE" }),
  createRoute: (id: number, body: any) =>
    req<any>(`/projects/${id}/routes`, { method: "POST", body: JSON.stringify(body) }),
  /** A route traced corner by corner, saved as one named route (4.7.0). */
  createRoutePath: (id: number, body: { page: number; points: number[][]; kind?: string }) =>
    req<{ route: string; ids: number[] }>(`/projects/${id}/routes/path`,
      { method: "POST", body: JSON.stringify(body) }),
  /** The last analysis run on the project — the saved As-Is (4.7.0). */
  latestAnalysis: (id: number) => req<any>(`/projects/${id}/analysis`),
  verticals: (id: number) => req<any[]>(`/projects/${id}/verticals`),
  createVertical: (id: number, body: any) =>
    req<any>(`/projects/${id}/verticals`, { method: "POST", body: JSON.stringify(body) }),

  analyse: (id: number, scenario = "As-Is", background = true) =>
    req<any>(
      `/projects/${id}/analyse?scenario=${encodeURIComponent(scenario)}&background=${background}`,
      { method: "POST" },
    ),
  job: (jobId: string) => req<any>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => req<any>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  jobs: (id: number) => req<any[]>(`/projects/${id}/jobs`),

  aliases: (id: number) => req<any[]>(`/projects/${id}/aliases`),
  createAlias: (id: number, body: any) =>
    req<any>(`/projects/${id}/aliases`, { method: "POST", body: JSON.stringify(body) }),
  deleteAlias: (id: number, aliasId: number) =>
    req<void>(`/projects/${id}/aliases/${aliasId}`, { method: "DELETE" }),
  aliasSuggestions: (id: number) => req<any[]>(`/projects/${id}/aliases/suggestions`),
  exportAliases: (id: number) => req<any>(`/projects/${id}/aliases/export`),
  importAliases: (id: number, body: any) =>
    req<any>(`/projects/${id}/aliases/import`, { method: "POST", body: JSON.stringify(body) }),
  report: (id: number, fmt: "pdf" | "xlsx" | "csv",
           background = false, legend = true, lines = true) =>
    req<any>(`/projects/${id}/reports/${fmt}` +
             `?background=${background}&legend=${legend}&lines=${lines}`, { method: "POST" }),
  audit: (id: number) => req<any[]>(`/projects/${id}/audit`),
  accountAudit: () => req<any[]>(`/admin/audit`),
  templates: () => req<any[]>(`/mapping-templates`),

  // --- who serves what -----------------------------------------------------
  assignments: (id: number, includeZero = false) =>
    req<any>(`/projects/${id}/spaces/assignments?include_zero=${includeZero}`),
  /** "The same space on another page": confirmed, rejected, or handed back to the rule. */
  decideOccurrenceLink: (id: number, linkId: number, body: { verdict: string; justification?: string }) =>
    req<any>(`/projects/${id}/occurrence-links/${linkId}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** The NER that serves one wireless point (2.11.0); null releases the choice. */
  serveWireless: (id: number, elementId: number,
                  body: { ner_asset_id: number | null; justification?: string }) =>
    req<any>(`/projects/${id}/wireless/${elementId}/serve`, {
      method: "POST", body: JSON.stringify(body),
    }),
  assignSpace: (id: number, spaceKey: string,
                body: { ner_asset_id: number | null; justification?: string }) =>
    req<any>(`/projects/${id}/spaces/${encodeURIComponent(spaceKey)}/assign`, {
      method: "POST", body: JSON.stringify(body),
    }),
  //: The "other level" box: the room chosen for this space sits on another
  //  level. Ticked by the choice of a room on another page; this withdraws or
  //  restores it.
  declareCrossLevel: (id: number, spaceKey: string,
                      body: { cross_level: boolean; justification?: string }) =>
    req<any>(`/projects/${id}/spaces/${encodeURIComponent(spaceKey)}/cross-level`, {
      method: "POST", body: JSON.stringify(body),
    }),

  //: Sign a room off — criticality and every marker of it — or take it back.
  confirmNer: (id: number, nerId: number, body: { confirmed: boolean; reason?: string }) =>
    req<any>(`/projects/${id}/ners/${nerId}/confirm`, {
      method: "POST", body: JSON.stringify(body),
    }),
  //: lock | unlock | confirm | unconfirm, every live NER, one audit row each.
  bulkNers: (id: number, action: "lock" | "unlock" | "confirm" | "unconfirm") =>
    req<{ changed: number; names: string[]; skipped: { name: string; why: string }[] }>(
      `/projects/${id}/ners/bulk`, { method: "POST", body: JSON.stringify({ action }) }),

  // --- V2: the NER register ------------------------------------------------
  ners: (id: number, includeRemoved = false) =>
    req<any>(`/projects/${id}/ners?include_removed=${includeRemoved}`),
  /** The next free sequential NER name of each series (2.14.0). */
  nextNerName: (id: number) => req<{ name: string; critical: string; non_critical: string }>(
    `/projects/${id}/ner-next-name`),
  /** The NER placing step (2.14.0): annotations, TEC.010/020 (or TEC.003) rooms, NER labels, NER block symbols (2.15.0). */
  placeNers: (id: number, background = true) =>
    req<any>(`/projects/${id}/ners/place-from-drawing?background=${background}`, { method: "POST" }),
  /** The AP placing step (2.19.0): one wireless point per wireless port of every matched TEAP space, tied to it. */
  placeAccessPoints: (id: number) =>
    req<any>(`/projects/${id}/wireless/place-from-teap`, { method: "POST" }),
  /** Wi-Fi points on top of each other (4.8.0). */
  stackedWifi: (id: number) =>
    req<{ stacks: number; points: number; to_move: number }>(`/projects/${id}/wireless/stacked`),
  /** Spread them into a grid beside the oldest of each stack (4.8.0). */
  spreadWifi: (id: number) =>
    req<any>(`/projects/${id}/wireless/spread`, { method: "POST" }),
  /** The naming table of the side panel (4.3.0): bundled only for a team entitled to it. */
  namingReference: () => req<any>(`/reference/naming`),
  /** The key-plan ticks of the Scale screen, several pages at once (2.14.0). */
  setKeyPlans: (id: number, pages: Record<number, boolean>) =>
    req<any>(`/projects/${id}/pages/key-plans`, {
      method: "POST",
      body: JSON.stringify({ pages }),
    }),
  ner: (id: number, nerId: number) => req<any>(`/projects/${id}/ners/${nerId}`),
  renameNer: (id: number, nerId: number, body: { name: string; reason?: string }) =>
    req<any>(`/projects/${id}/ners/${nerId}/rename`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  classifyNer: (
    id: number,
    nerId: number,
    body: { classification: string; confirmed: boolean; reason?: string },
  ) =>
    req<any>(`/projects/${id}/ners/${nerId}/classify`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  nerStatus: (id: number, nerId: number, body: { status: string; reason?: string }) =>
    req<any>(`/projects/${id}/ners/${nerId}/status`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  keepNer: (id: number, nerId: number, body: { decision: string; reason?: string }) =>
    req<any>(`/projects/${id}/ners/${nerId}/keep`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  lockNer: (id: number, nerId: number, body: { locked: boolean; reason?: string }) =>
    req<any>(`/projects/${id}/ners/${nerId}/lock`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchNer: (id: number, nerId: number, values: Record<string, any>) =>
    req<any>(`/projects/${id}/ners/${nerId}`, {
      method: "PATCH",
      body: JSON.stringify({ values }),
    }),
  removeNer: (id: number, nerId: number, reason: string) =>
    req<any>(`/projects/${id}/ners/${nerId}/remove`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  restoreNer: (id: number, nerId: number) =>
    req<any>(`/projects/${id}/ners/${nerId}/restore`, { method: "POST" }),
  duplicateCandidates: (id: number) =>
    req<any>(`/projects/${id}/ners/duplicates/candidates`),
  consolidateNers: (
    id: number,
    body: { primary_id: number; duplicate_id: number; justification?: string; force?: boolean },
  ) =>
    req<any>(`/projects/${id}/ners/consolidate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  declareSeparate: (
    id: number,
    body: { a_id: number; b_id: number; justification?: string },
  ) =>
    req<any>(`/projects/${id}/ners/declare-separate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  consolidations: (id: number) => req<any>(`/projects/${id}/ner-consolidations`),
  undoConsolidation: (id: number, cid: number, reason = "") =>
    req<any>(
      `/projects/${id}/ner-consolidations/${cid}/undo?reason=${encodeURIComponent(reason)}`,
      { method: "POST" },
    ),
  detachOccurrence: (id: number, elementId: number, reason = "") =>
    req<any>(
      `/projects/${id}/occurrences/${elementId}/detach?reason=${encodeURIComponent(reason)}`,
      { method: "POST" },
    ),
  linkOccurrence: (
    id: number,
    elementId: number,
    body: { asset_id: number | null; status: string; reason?: string },
  ) =>
    req<any>(`/projects/${id}/occurrences/${elementId}/link`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  snapshots: (id: number) => req<any>(`/projects/${id}/register-snapshots`),
  createSnapshot: (
    id: number,
    body: { kind: string; name: string; reference?: string; issued_to?: string; note?: string },
  ) =>
    req<any>(`/projects/${id}/register-snapshots`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  snapshot: (id: number, sid: number) =>
    req<any>(`/projects/${id}/register-snapshots/${sid}`),
};
