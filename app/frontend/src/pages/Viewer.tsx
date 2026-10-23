import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Arc, Circle, Group, Image as KImage, Label, Layer, Line, Rect, Stage, Tag, Text } from "react-konva";
import * as pdfjsLib from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { Ctx } from "../App";
import { api } from "../lib/api";
import {
  AREA_COLOUR, AREA_FILL_OPACITY, DEMAND_KINDS, DISCLAIMER, KIND_COLOUR, KIND_LABEL,
  KIND_LABEL_COLOUR, LABEL_TAG_FILL, LABEL_TAG_OPACITY, LEGEND_ROWS, MARKER_RING,
  NER_REFERENCE_KINDS, REFERENCE_KINDS, STATUS_COLOUR, canServe, drawsReach, fmtLen,
} from "../lib/notation";
import { HANDOFF, SPACE_COLLATOR } from "./panels";
import { NamingReference } from "../components/NamingReference";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * The tools. The calibrate tool and the three zone tools went on 3 Sep 2026:
 * the Scale screen takes a ratio or a scale text per page, which is what the
 * two-point calibration was being used for, and nobody was drawing
 * permitted / forbidden / technical areas — the study does not need areas,
 * it needs rooms. (The zone and calibration endpoints still exist on the
 * server; only the tools are gone.)
 */
type Tool =
  | "select" | "add-ner-critical" | "add-ner" | "add-ter" | "add-idf" | "add-cow"
  | "add-diva" | "add-ner-ref-critical" | "add-ner-ref"
  | "add-ter-ref" | "add-cow-ref" | "add-diva-ref" | "area"
  | "add-wireless" | "route" | "vertical" | "delete";

/** The toolbox (2.14.0: a column down the left of the sheet, not a strip
 *  across the top), in groups: what the study counts, what the plan shows,
 *  the demand drawn by hand, the *illustrative* tools (references on a key
 *  plan and named areas — drawn, never counted; styled apart so nobody
 *  mistakes ``*NER`` for ``+NER``), routing, and the eraser. */
const TOOL_GROUPS: Tool[][] = [
  ["select"],
  ["add-ner-critical", "add-ner"],
  ["add-ter", "add-idf", "add-cow", "add-diva"],
  ["add-wireless"],
  ["add-ner-ref-critical", "add-ner-ref", "add-ter-ref", "add-cow-ref", "add-diva-ref", "area"],
  ["route", "vertical"],
  ["delete"],
];
const ILLUSTRATIVE_TOOLS = new Set<Tool>(TOOL_GROUPS[4]);
/** What a key plan does not take (2.13.0): a key plan only illustrates, so a
 *  NER or an access point is placed on the detail sheet and pointed at here
 *  with a *NER reference. The server refuses them too. */
const KEY_PLAN_BLOCKED = new Set<Tool>(["add-ner-critical", "add-ner", "add-wireless"]);

/** What each ``add-`` tool places. A NER is the room the study is about; the
 *  rest — TER, IDF, COW and, since 3 Sep 2026, the DIVA node — are drawn so
 *  the plan shows what is in the building, and are never offered as
 *  somewhere a space could be served from. */
const ADD_KIND: Record<string, string> = {
  "add-ner-critical": "NER_CRITICAL",
  "add-ner": "NER_NONCRITICAL",
  "add-ter": "TER",
  "add-idf": "IDF",
  "add-cow": "COW",
  "add-diva": "DIVA",
  // A *reference* to a NER on a key plan (2.7.0): named after a NER of the
  // register, drawn with its reach circles to this sheet's scale, and
  // counted nowhere — a picture of a room that exists on another sheet.
  "add-ner-ref-critical": "NER_CRITICAL_REF",
  "add-ner-ref": "NER_NONCRITICAL_REF",
  // The same for a TER, a COW and a DIVA node (2.8.0): pointed at on a key
  // plan, dashed ring, no circles, nothing counted.
  "add-ter-ref": "TER_REF",
  "add-cow-ref": "COW_REF",
  "add-diva-ref": "DIVA_REF",
  // Not a room: an access point. Since 4.0.0 it takes no port — the DWISA
  // line of its TEAP space is the port — and is measured to its NER so the
  // 90 m rule is checked where it is drawn. One kind since 2.14.0 — "AP".
  "add-wireless": "WIRELESS",
};

const TOOL_LABEL: Record<string, string> = {
  "select": "select",
  "add-ner-critical": "+NER★",
  "add-ner": "+NER",
  "add-ter": "+TER",
  "add-idf": "+IDF",
  "add-cow": "+COW",
  "add-diva": "+DIVA",
  "add-ner-ref-critical": "*NER★",
  "add-ner-ref": "*NER",
  "add-ter-ref": "*TER",
  "add-cow-ref": "*COW",
  "add-diva-ref": "*DIVA",
  // A named area: click the corners, double-click (or Enter) to close it,
  // name it. Illustrative — "BTOC", "TER", a compound — never counted.
  "area": "+area",
  "add-wireless": "+Wi-Fi",
  "route": "route",
  "vertical": "vertical",
  // The eraser: click anything that was drawn — a marker, a wireless point, a
  // route segment, a shaft — and it goes. Stays armed, like +Wireless.
  "delete": "delete",
};

/** The kinds the inspector offers when re-classifying a marker: the two NER
 *  kinds and the four visual-only kinds. Order carries meaning, so it is not
 *  alphabetical. */
const KIND_CHOICES = ["NER_CRITICAL", "NER_NONCRITICAL", "TER", "IDF", "COW", "DIVA"];
/** A reference stays a reference — of a NER, a TER, a COW or a DIVA node —
 *  never a room. */
const REF_CHOICES = ["NER_CRITICAL_REF", "NER_NONCRITICAL_REF", "TER_REF", "COW_REF", "DIVA_REF"];
/** What a reference of a non-NER kind is named by default when placed. */
const REF_DEFAULT_LABEL: Record<string, string> = { TER_REF: "TER", COW_REF: "COW", DIVA_REF: "DIVA Node" };
import { t } from "../lib/i18n";
import { useJob } from "../lib/useJob";
import { bookSeries, pageName, sheetFromText, sheetNo } from "./panels";

const RENDER_SCALE = 2.2;
/** The longest side of the page bitmap, in pixels (2.17.0). A 36×24 in sheet
 *  at 2.2 is 5,700 px wide and 87 MB of bitmap; a 48×36 in one would be 7,600
 *  px, which some browsers refuse outright. Above this the scale comes down. */
const MAX_CANVAS_PX = 6000;

/** How two NER names are compared for "is this the same room?": case, spaces,
 *  dots and dashes ignored — "NER 21", "ner21" and "NER-21" are one name,
 *  "NERc 01" and "NER 01" are two. */
export function nerNameKey(name: string): string {
  return String(name || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function Viewer({ ctx }: { ctx: Ctx }) {
  // The inspector takes 316px of a drawing that needs every pixel. Remembered
  // per browser: someone who works collapsed wants it collapsed tomorrow too.
  const [inspectorOpen, setInspectorOpen] = useState<boolean>(() => {
    try { return localStorage.getItem("ner.inspector") !== "closed"; }
    catch { return true; }
  });
  const toggleInspector = () => setInspectorOpen((open) => {
    const next = !open;
    try { localStorage.setItem("ner.inspector", next ? "open" : "closed"); }
    catch { /* private window — the session still remembers */ }
    return next;
  });
  // The toolbox folds too (2.14.0), remembered the same way.
  const [toolboxOpen, setToolboxOpen] = useState<boolean>(() => {
    try { return localStorage.getItem("ner.toolbox") !== "closed"; }
    catch { return true; }
  });
  const toggleToolbox = () => setToolboxOpen((open) => {
    const next = !open;
    try { localStorage.setItem("ner.toolbox", next ? "open" : "closed"); }
    catch { /* private window */ }
    return next;
  });
  const [legendOpen, setLegendOpen] = useState<boolean>(() => {
    try { return localStorage.getItem("ner.legend") !== "closed"; }
    catch { return true; }
  });
  const toggleLegend = () => setLegendOpen((open) => {
    const next = !open;
    try { localStorage.setItem("ner.legend", next ? "open" : "closed"); }
    catch { /* private window */ }
    return next;
  });
  const p = ctx.project;
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 900, h: 640 });
  // The page comes back to where it was (2.14.0): leaving the viewer to check
  // something on another screen used to land on page 1 every time, and the
  // trip was usually about the page just left. Per project, per browser.
  const [page, setPageState] = useState<number>(() => {
    // The page left last time, when this project still has it; otherwise its
    // first sheet (4.2.0). "1" is no sheet at all in a project with several
    // books, and three requests for it failed on every first visit.
    let saved = 0;
    try { saved = Number(localStorage.getItem(`ner.viewer.page.${p?.id}`)) || 0; }
    catch { saved = 0; }
    const pages = p?.pages || [];
    // Sent here by a page button (4.4.0): that sheet wins over the last one.
    const sent = HANDOFF.viewerAt?.page;
    if (sent != null && pages.some((x: any) => x.number === sent)) {
      try { localStorage.setItem(`ner.viewer.page.${p?.id}`, String(sent)); } catch { /* */ }
      return sent;
    }
    if (pages.some((x: any) => x.number === saved)) return saved;
    return pages.length ? pages[0].number : 1;
  });
  const setPage = (n: number) => {
    setPageState(n);
    try { localStorage.setItem(`ner.viewer.page.${p?.id}`, String(n)); }
    catch { /* private window — the session still remembers */ }
  };
  /** Which panel the aside shows: the inspector, or the naming reference
   *  — a reference table (2.14.0), nothing more. */
  const [asideTab, setAsideTab] = useState<"inspector" | "naming">("inspector");
  const [bg, setBg] = useState<HTMLCanvasElement | null>(null);
  const [pdfSize, setPdfSize] = useState({ w: 1000, h: 700 });
  const [zoom, setZoom] = useState(0.6);
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const [tool, setTool] = useState<Tool>("select");
  const [elements, setElements] = useState<any[]>([]);
  const [spaces, setSpaces] = useState<any[]>([]);
  const [routes, setRoutes] = useState<any[]>([]);
  //: Shafts / risers registered on this page (either end). They used to be
  //  invisible once created, which also made them impossible to take back.
  const [verticals, setVerticals] = useState<any[]>([]);
  const [coverage, setCoverage] = useState<any | null>(null);
  const coverageJob = useJob();
  const [selected, setSelected] = useState<any | null>(null);
  const [draft, setDraft] = useState<number[][]>([]);
  /** The named areas drawn on this page (2.8.0), and the one being drawn. */
  const [areas, setAreas] = useState<any[]>([]);
  const [areaDraft, setAreaDraft] = useState<number[][]>([]);
  const [showRadii, setShowRadii] = useState(true);
  const [showSpaces, setShowSpaces] = useState(true);
  //: Register rooms that the drawing does not carry a marker for — a room you
  //  placed here yourself, or one whose marker was deleted from the sheet. The
  //  viewer used to draw only the markers the extractor found on the PDF, which
  //  meant such a room was invisible on the one screen where position is the
  //  whole point.
  //
  //  They are drawn exactly like any other NER — filled in the colour of their
  //  criticality, ringed in black. There is no "proposed" state any more: a NER
  //  you draw is a NER.
  const [proposed, setProposed] = useState<any[]>([]);
  const [unplaced, setUnplaced] = useState<any[]>([]);
  /** The TEAP spaces a wireless point can stand in for (matched rooms). */
  const [tieOptions, setTieOptions] = useState<any[]>([]);
  const [showProposed, setShowProposed] = useState(true);
  const [busy, setBusy] = useState("");
  /** The register's NERs, by name — what a *NER reference is named after. */
  const [registerNers, setRegisterNers] = useState<any[]>([]);
  /** The NER a reference placed next will be named after ("" = ask). */
  const [refName, setRefName] = useState("");

  // -- search (2.12.0) ------------------------------------------------------
  // Every named thing on every page — the rooms the extractor read (and the
  // TEAP lines tied to them), the markers, the named areas — so a name can be
  // found without paging through the book. Marcelo, 25 Sep 2026: "no drawing
  // viewer se tivesse uma busca pra achar os nomes atribuídos às áreas
  // ajudaria bastante."
  const [searchQ, setSearchQ] = useState<string>(() => HANDOFF.viewer || "");
  const [searchOpen, setSearchOpen] = useState<boolean>(() => !!HANDOFF.viewer);
  const autoJump = useRef<boolean>(!!HANDOFF.viewer);
  useEffect(() => { HANDOFF.viewer = ""; }, []);
  const [searchIndex, setSearchIndex] = useState<any[]>([]);
  const [indexTick, setIndexTick] = useState(0);
  /** Where the last search landed: ringed on the sheet for a few seconds. */
  const [focus, setFocus] = useState<{ page: number; x: number; y: number } | null>(null);

  useEffect(() => {
    if (p?.pages?.length && !p.pages.some((x: any) => x.number === page)) setPage(p.pages[0].number);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p?.id, p?.pages?.length]);
  const pageInfo = p?.pages?.find((x: any) => x.number === page);
  const pageIdx = p?.pages ? p.pages.findIndex((x: any) => x.number === page) : -1;
  const mpu = pageInfo?.metres_per_unit ?? null;
  /** A key plan (2.13.0): read off the title block, or switched here. */
  const isKey = !!pageInfo?.key_plan;
  useEffect(() => {
    if (isKey && KEY_PLAN_BLOCKED.has(tool)) setTool("select");
  }, [isKey, tool]);

  // -- resize -------------------------------------------------------------
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // -- the open book (2.17.0) ---------------------------------------------
  // One PDF.js document per drawing, opened once and kept while the viewer
  // shows that drawing. It used to be opened again on every page turn and
  // never closed: each open book — 70 MB for a real venue design book —
  // stayed in the PDF.js worker until the tab was closed, so the tab grew
  // with every project opened and every page turned. Marcelo, 8 Oct 2026:
  // "a renderização dos mapas fica mais lenta a cada novo projeto carregado".
  const docRef = useRef<{ key: string; doc: pdfjsLib.PDFDocumentProxy } | null>(null);
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);
  const closeDoc = useCallback(() => {
    const open = docRef.current;
    docRef.current = null;
    if (open) void open.doc.destroy().catch(() => { /* already gone */ });
  }, []);
  // Leaving the viewer closes the book and stops a render still running.
  useEffect(() => () => {
    renderTaskRef.current?.cancel();
    renderTaskRef.current = null;
    closeDoc();
  }, [closeDoc]);
  // The bitmap of the page just left is released as soon as the next one is
  // on the stage — a zero-sized canvas holds no pixels, whatever still
  // points at it.
  useEffect(() => () => { if (bg) { bg.width = 0; bg.height = 0; } }, [bg]);

  // -- render the PDF page -------------------------------------------------
  useEffect(() => {
    if (!p?.drawings?.length) { closeDoc(); return; }
    let cancelled = false;
    (async () => {
      setBusy("Rendering the page…");
      try {
        // The sheet names its book and its page in that book (4.1.0): with
        // several books every one starts at page 1, and the viewer used to
        // open the first book whatever sheet was chosen.
        const sheet = p.pages?.find((x: any) => x.number === page);
        const drawing = p.drawings.find((d: any) => d.id === sheet?.drawing_id) ?? p.drawings[0];
        const pageInBook = sheet?.page ?? page;
        const key = `${p.id}:${drawing.id}`;
        if (docRef.current && docRef.current.key !== key) closeDoc();
        if (!docRef.current) {
          const url = api.drawingFileUrl(p.id, drawing.id);
          const doc = await pdfjsLib.getDocument({ url }).promise;
          if (docRef.current) {
            // Two opens raced (a quick page turn while the book was loading):
            // keep the one already recorded, close this one.
            void doc.destroy().catch(() => { /* already gone */ });
          } else {
            docRef.current = { key, doc };
          }
        }
        const doc = docRef.current.doc;
        const pg = await doc.getPage(Math.min(pageInBook, doc.numPages));
        if (cancelled) return;
        const base = pg.getViewport({ scale: 1 });
        const scale = Math.min(RENDER_SCALE, MAX_CANVAS_PX / Math.max(base.width, base.height));
        const vp = pg.getViewport({ scale });
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(vp.width);
        canvas.height = Math.ceil(vp.height);
        const c2d = canvas.getContext("2d")!;
        c2d.fillStyle = "#ffffff";
        c2d.fillRect(0, 0, canvas.width, canvas.height);
        // A render still running for the page just left is stopped first:
        // its pixels are not wanted, and PDF.js renders one page at a time.
        renderTaskRef.current?.cancel();
        const task = pg.render({ canvas, canvasContext: c2d, viewport: vp } as any);
        renderTaskRef.current = task;
        await task.promise;
        if (renderTaskRef.current === task) renderTaskRef.current = null;
        if (cancelled) { canvas.width = 0; canvas.height = 0; return; }
        setPdfSize({ w: base.width, h: base.height });
        setBg(canvas);
      } catch (e: any) {
        if (cancelled || e?.name === "RenderingCancelledException") return;
        ctx.notify(`Could not render the page with PDF.js (${e.message}). ` +
                   `Check the drawing upload.`, "err");
      } finally {
        if (!cancelled) setBusy("");
      }
    })();
    return () => { cancelled = true; };
  }, [p?.id, p?.drawings?.length, p?.pages, page, closeDoc]);

  // -- overlay data --------------------------------------------------------
  const reloadOverlays = useCallback(async () => {
    if (!p) return;
    // Only a sheet the project has (4.2.0) — the page effect above moves an
    // unknown one to the first sheet, and this runs again then.
    if (p.pages?.length && !p.pages.some((x: any) => x.number === page)) return;
    const [els, sps, rts, reg, vts, ties, names, zones] = await Promise.all([
      api.elements(p.id, page), api.drawingSpaces(p.id, page),
      api.routes(p.id), api.nerAssetPositions(p.id, page), api.verticals(p.id),
      api.wirelessTieOptions(p.id).catch(() => []),
      api.ners(p.id).catch(() => ({ ners: [] })),
      api.zones(p.id, page).catch(() => []),
    ]);
    setAreas((zones as any[]).filter((z: any) => z.kind === "area"));
    setVerticals(vts.filter((v: any) => v.lower_page === page || v.upper_page === page));
    setTieOptions(ties);
    setRegisterNers(((names as any).ners || [])
      .filter((n: any) => n.is_live !== false && canServe(n.kind))
      .sort((a: any, b: any) => SPACE_COLLATOR.compare(a.display_name, b.display_name)));
    setElements(els);
    // Only the rows the drawing does not already show: a room with a marker
    // arrives as an element and drawing it twice would double-count it by eye.
    setProposed((reg.positions || []).filter((a: any) => !a.on_drawing));
    setUnplaced(reg.unplaced || []);
    setSpaces(sps);
    setRoutes(rts.filter((r: any) => r.page === page));
  }, [p?.id, page]);
  //: Something was drawn, renamed or erased: the search index follows.
  const reloadAll = useCallback(async () => {
    await reloadOverlays();
    setIndexTick((n) => n + 1);
  }, [reloadOverlays]);

  useEffect(() => { void reloadOverlays(); }, [reloadOverlays]);

  // The search index: every page at once, rebuilt when something is drawn.
  useEffect(() => {
    if (!p) return;
    let cancelled = false;
    Promise.all([
      api.drawingSpaces(p.id), api.elements(p.id), api.zones(p.id).catch(() => []),
    ]).then(([sps, els, zs]) => {
      if (cancelled) return;
      const items: any[] = [];
      for (const s of sps as any[]) {
        const tied = (s.tied_to || []).join(" ");
        items.push({ type: "space", data: s, page: s.page, x: s.x, y: s.y,
                     name: [s.space_code, s.name].filter(Boolean).join(" · ") || "?",
                     what: t("room on the drawing"), extra: tied,
                     hay: [s.space_code, s.name, s.area_label, tied].join(" | ") });
      }
      for (const e of els as any[]) {
        if (!e.label) continue;
        items.push({ type: "element", data: e, page: e.page, x: e.x, y: e.y, name: e.label,
                     what: t(KIND_LABEL[e.kind] || e.kind), hay: `${e.label} | ${e.kind}` });
      }
      for (const z of zs as any[]) {
        const pts: number[][] = z.polygon || [];
        if (!z.label || pts.length < 3) continue;
        const cx = pts.reduce((a, q) => a + q[0], 0) / pts.length;
        const cy = pts.reduce((a, q) => a + q[1], 0) / pts.length;
        items.push({ type: "area", data: z, page: z.page, x: cx, y: cy, name: z.label,
                     what: t("named area"), hay: z.label });
      }
      setSearchIndex(items);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [p?.id, indexTick]);

  const searchHits = useMemo(() => {
    const fold = (v: any) => String(v ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const q = fold(searchQ).trim();
    if (!q) return [];
    const words = q.split(/\s+/);
    const scored: [number, any][] = [];
    for (const it of searchIndex) {
      const hay = fold(it.hay);
      if (!words.every((w) => hay.includes(w))) continue;
      const n = fold(it.name);
      // Exact name first, then names that start with the text, then the rest.
      const rank = n === q || fold(it.data?.space_code) === q ? 0 : n.startsWith(q) ? 1 : 2;
      scored.push([rank, it]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].page - b[1].page || SPACE_COLLATOR.compare(a[1].name, b[1].name));
    return scored.map((x) => x[1]);
  }, [searchQ, searchIndex]);

  /** Go to a search hit: its page, centred, zoomed in, selected, ringed. */
  const goTo = (hit: any) => {
    const z = Math.max(zoom, 1.4);
    if (hit.page !== page) setPage(hit.page);
    setZoom(z);
    setPan({ x: size.w / 2 - hit.x * z, y: size.h / 2 - hit.y * z });
    setFocus({ page: hit.page, x: hit.x, y: hit.y });
    setSelected(hit.type === "space" ? { type: "space", data: hit.data, assignment: assignmentFor(hit.data) }
                                     : { type: hit.type, data: hit.data });
    setSearchOpen(false);
  };
  useEffect(() => {
    if (!focus) return;
    const id = setTimeout(() => setFocus(null), 6000);
    return () => clearTimeout(id);
  }, [focus]);
  // Sent here by a page button (4.4.0): centre the point it named and ring
  // it, once the canvas has its size. The page itself was chosen above.
  const pendingAt = useRef(HANDOFF.viewerAt);
  useEffect(() => { HANDOFF.viewerAt = null; }, []);
  useEffect(() => {
    const at = pendingAt.current;
    const w = wrapRef.current?.clientWidth || 0, h = wrapRef.current?.clientHeight || 0;
    if (!at || w < 50 || h < 50) return;
    pendingAt.current = null;
    if (at.x == null || at.y == null) return;
    const z = Math.max(zoom, 1.4);
    setZoom(z);
    setPan({ x: w / 2 - at.x * z, y: h / 2 - at.y * z });
    setFocus({ page: at.page, x: at.x, y: at.y });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size.w, size.h]);
  // Sent here from another screen: go straight to the best hit.
  useEffect(() => {
    if (!autoJump.current || !searchIndex.length) return;
    autoJump.current = false;
    if (searchHits.length) goTo(searchHits[0]);
    else ctx.notify(`${t("Nothing on the drawing is named")} “${searchQ}”.`, "err");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchIndex]);

  const assignmentsByKey = useMemo(() => {
    const m: Record<string, any> = {};
    for (const a of coverage?.assignments || []) m[a.space_key] = a;
    return m;
  }, [coverage]);

  // The verdict for each room on the sheet, by the room's own id (2.8.0).
  // The overlay used to find a room's row by matching the TEAP key's tail
  // against the room code, which holds only when the two are spelled the
  // same — the matcher exists because they often are not — so on most rows
  // "Coverage" painted nothing and looked broken. The tail match stays as
  // the fallback for a run saved before the id travelled with the row.
  const assignmentsBySpaceId = useMemo(() => {
    const m: Record<number, any> = {};
    for (const a of coverage?.assignments || []) {
      if (a.drawing_space_id != null && a.kind !== "wireless_point") m[a.drawing_space_id] = a;
    }
    return m;
  }, [coverage]);
  const assignmentFor = (s: any) =>
    assignmentsBySpaceId[s.id]
    ?? assignmentsByKey[Object.keys(assignmentsByKey).find(
      (k) => k.endsWith(`|${(s.space_code || s.name).toUpperCase()}`)) || ""];

  const nerById = useMemo(() => {
    const m: Record<string, any> = {};
    for (const e of elements) {
      m[`E${e.id}`] = e;
      // Since the register, an analysis names a room by its canonical id.
      if (e.ner_asset_id != null) m[`A${e.ner_asset_id}`] = e;
    }
    return m;
  }, [elements]);

  // -- interaction ---------------------------------------------------------
  const toPdf = (stage: any) => {
    const pos = stage.getPointerPosition();
    return { x: (pos.x - pan.x) / zoom, y: (pos.y - pan.y) / zoom };
  };

  const onWheel = (e: any) => {
    e.evt.preventDefault();
    const stage = e.target.getStage();
    const pointer = stage.getPointerPosition();
    const factor = e.evt.deltaY > 0 ? 1 / 1.12 : 1.12;
    const next = Math.min(8, Math.max(0.05, zoom * factor));
    setPan({
      x: pointer.x - ((pointer.x - pan.x) / zoom) * next,
      y: pointer.y - ((pointer.y - pan.y) / zoom) * next,
    });
    setZoom(next);
  };

  const onStageClick = async (e: any) => {
    if (!p) return;
    const stage = e.target.getStage();
    const pt = toPdf(stage);

    if (tool === "select" || tool === "delete") { setSelected(null); return; }

    if (tool === "area") {
      // One corner per click; a double-click (or Enter) closes the outline.
      // The second click of a double-click lands within a pixel of the first
      // and is dropped, so the corner is not recorded twice.
      setAreaDraft((d) => {
        const last = d[d.length - 1];
        if (last && Math.hypot(last[0] - pt.x, last[1] - pt.y) < 3 / zoom) return d;
        return [...d, [pt.x, pt.y]];
      });
      return;
    }

    if (tool.startsWith("add-")) {
      const kind = ADD_KIND[tool] || "NER_NONCRITICAL";
      if (DEMAND_KINDS.has(kind)) {
        // No name asked: the server numbers them AP-1, AP-2 … (one kind) and
        // proposes the TEAP space the point stands in for; the tool stays
        // armed, because nobody places one access point.
        const made = await api.createElement(p.id, { page, kind, label: "", x: pt.x, y: pt.y });
        await reloadAll();
        ctx.notify(made?.space_name
          ? `${made.label}: ${t("Wi-Fi point placed for")} ${made.space_name}. ${t("Check it in the Inspector; click again to place another, choose select to stop.")}`
          : `${made?.label || ""}: ${t("Wi-Fi point placed — no matched room within the limit on this sheet, so it belongs to no TEAP space and counts no port. Tie it to a space in the Inspector if it belongs to one.")}`);
        return;
      }
      if (REFERENCE_KINDS.has(kind)) {
        // Named after a NER of the register — chosen in the toolbar while
        // the tool is armed — or typed, when the register has nothing yet.
        // A TER, COW or DIVA reference is simply named. The tool stays
        // armed: a key plan gets every room pointed at in one go.
        const label = NER_REFERENCE_KINDS.has(kind)
          ? (refName || prompt(t("Name of the NER this reference points at"), "NER") || "")
          : (prompt(t("Name of the room this reference points at"), REF_DEFAULT_LABEL[kind] || kind) || "");
        if (!label.trim()) return;
        const made = await api.createElement(p.id, { page, kind, label: label.trim(), x: pt.x, y: pt.y });
        await reloadAll();
        ctx.notify(`${label.trim()}: ${NER_REFERENCE_KINDS.has(kind)
          ? t("reference placed on this sheet — drawn only, with its reach circles; nothing is counted. Click again to place another, choose select to stop.")
          : t("reference placed on this sheet — drawn only, no reach circles; nothing is counted. Click again to place another, choose select to stop.")}`);
        const fresh = (await api.elements(p.id, page)).find((x: any) => x.id === made?.id);
        if (fresh) setSelected({ type: "element", data: fresh });
        return;
      }
      // A NER is offered the next name of its series (2.14.0) — NERc03,
      // NER07 — computed from the register; anything typed over it stands.
      let proposed = kind === "DIVA" ? "DIVA Node" : kind;
      if (kind === "NER_CRITICAL" || kind === "NER_NONCRITICAL") {
        try {
          const nx = await api.nextNerName(p.id);
          proposed = kind === "NER_CRITICAL" ? nx.critical : nx.non_critical;
        } catch { proposed = kind === "NER_CRITICAL" ? "NERc" : "NER"; }
      }
      let label = prompt(t("Label for the new element"), proposed);
      if (!label) return;
      // A NER named like one that exists (2.12.0): the same room drawn on
      // another sheet, or a slip? Asked, never guessed. Marcelo, 25 Sep 2026:
      // "se eu usar o mesmo nome de uma NER existente me pergunte se é a
      // mesma NER também em outra página ou se devo escolher outro nome."
      let sameAs: any = null;
      if (kind === "NER_CRITICAL" || kind === "NER_NONCRITICAL") {
        for (;;) {
          const key = nerNameKey(label);
          const twin = registerNers.find((n: any) => nerNameKey(n.display_name) === key);
          if (!twin) break;
          const where = (twin.pages || []).map((n: number) => pageName(p, n)).join(", ") || t("no page");
          const here = (twin.pages || []).includes(page);
          const same = confirm(
            `${t("A NER with this name already exists")}: “${twin.display_name}” (${where}).\n\n`
            + (here ? `${t("It is already drawn on this page.")}\n\n` : "")
            + `${t("OK — it is the same NER, drawn on this page too (one room, counted once).")}\n`
            + `${t("Cancel — it is a different room: choose another name.")}`);
          if (same) { sameAs = twin; break; }
          const other = prompt(t("Another name for the new NER"), label);
          if (!other) return;
          label = other;
        }
      }
      try {
        await api.createElement(p.id, { page, kind, label, x: pt.x, y: pt.y,
                                         same_as_asset_id: sameAs ? sameAs.id : undefined });
      } catch (e: any) { ctx.notify(e.message, "err"); return; }
      await reloadAll();
      ctx.notify(sameAs
        ? `${sameAs.display_name}: ${t("drawn on this page as the same NER — one room in the register, counted once.")}`
        : `${label} ${t("created on page")} ${sheetNo(p, page)}.`);
      setTool("select");
      return;
    }

    if (tool === "route") {
      const next = [...draft, [pt.x, pt.y]];
      if (next.length < 2) { setDraft(next); return; }
      await api.createRoute(p.id, {
        page, x0: next[0][0], y0: next[0][1], x1: next[1][0], y1: next[1][1], kind: "tray",
      });
      setDraft([]);
      await reloadAll();
      return;
    }

    if (tool === "vertical") {
      // With several books a page number alone names no sheet (4.2.0): the
      // shaft was refused with "sheet 12 is not a sheet of this project".
      const other = prompt(p.multi_book
        ? t("Sheet this shaft connects to — the series and the page as the page selector shows them (600 12), or the drawing number")
        : t("Page number this shaft connects to"));
      if (!other) return;
      const target = sheetFromText(p, other);
      if (target == null) {
        ctx.notify(`${t("No sheet answers to")} "${other}". ${p.multi_book
          ? t("Type the series and the page, e.g. 600 12, or the drawing number.")
          : t("Type a page number of this drawing.")}`, "err");
        return;
      }
      const len = prompt(t("Vertical length in metres"));
      if (!len) return;
      try {
        await api.createVertical(p.id, {
          key: `SHAFT-${page}-${Math.round(pt.x)}`,
          lower_page: page, lower_x: pt.x, lower_y: pt.y,
          upper_page: target, upper_x: pt.x, upper_y: pt.y,
          length_m: Number(len), kind: "shaft",
        });
      } catch (err: any) { ctx.notify(err.message, "err"); return; }
      // Drawn at once (2.12.1): it used to appear only after a page change.
      await reloadAll();
      ctx.notify(`${t("Shaft registered between")} ${pageName(p, page)} ${t("and")} ${pageName(p, target)}.`);
      setTool("select");
      return;
    }
  };

  /** Rename, re-classify or delete the selected marker from the inspector.
   *  These used to live on the "On the drawing" tab of the NERs screen; that
   *  tab is gone, and a TER, an IDF, a COW or a DIVA node is managed here,
   *  on the sheet, where it is a visual thing. */
  const patchSelected = async (body: any) => {
    if (!p || !selected || selected.type !== "element") return;
    try {
      await api.patchElement(p.id, selected.data.id, body);
      await reloadAll();
      // Keep the Inspector open on the same marker with the fresh row, so the
      // person sees what they just changed — the tie, the name, the kind.
      const fresh = (await api.elements(p.id, page)).find((x: any) => x.id === selected.data.id);
      setSelected(fresh ? { type: "element", data: fresh } : null);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /** Close the outline being drawn, ask for its name, and save it. */
  const finishArea = async () => {
    if (!p) return;
    const pts = areaDraft;
    if (pts.length < 3) {
      ctx.notify(t("An area needs at least three corners — keep clicking, then double-click or press Enter to close it."), "err");
      return;
    }
    const label = (prompt(t("Name of the area (for example BTOC, TER, broadcast compound)"), "") || "").trim();
    if (!label) { return; }
    try {
      const made = await api.createZone(p.id, { page, kind: "area", label, polygon: pts });
      setAreaDraft([]);
      await reloadAll();
      setSelected({ type: "area", data: made });
      ctx.notify(`${label}: ${t("area drawn — illustrative only, nothing is counted from it. Click to start another, choose select to stop.")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const patchArea = async (body: any) => {
    if (!p || !selected || selected.type !== "area") return;
    try {
      const fresh = await api.patchZone(p.id, selected.data.id, body);
      await reloadAll();
      setSelected({ type: "area", data: fresh });
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /**
   * Take something off the drawing: a marker of any kind, a wireless point, a
   * route segment, a shaft, a named area. One function, because "anything I
   * drew I can erase right here" (Marcelo, 17 Sep 2026) is one rule, not five.
   *
   * ``ask`` is off only for the eraser tool on the things that cost nothing to
   * redraw — a wireless point, a route segment. A marker always asks: a TER or
   * a NER read off the drawing does not come back by clicking again.
   */
  const removeItem = async (type: string, d: any, ask = true, scope: "ner" | "marker" = "ner") => {
    if (!p) return;
    const name = type === "element" ? d.label
      : type === "area" ? `${t("the area")} ${d.label}`
      : type === "route" ? t("this route segment")
      : `${t("the shaft between pages")} ${sheetNo(p, d.lower_page)} ${t("and")} ${sheetNo(p, d.upper_page)}`;
    if (type === "element" && d.locked) {
      ctx.notify(`${d.label}: ${t("locked — unlock it before deleting it")}`, "err");
      return;
    }
    // A NER marker is one drawing of a room the register holds (2.18.1):
    // deleting it deletes the NER — every page, the NERs list, the analysis,
    // the export — and the dialog says so, naming the other sheets. "Delete
    // only this marker" (the inspector) keeps the old, narrower act.
    const isNer = type === "element" && d.ner_asset_id != null && canServe(d.kind);
    const otherPages: number[] = isNer
      ? (registerNers.find((n: any) => n.id === d.ner_asset_id)?.pages || []).filter((n: number) => n !== page)
      : [];
    const wholeNer = isNer && scope === "ner";
    if (ask) {
      const msg = wholeNer
        ? `${t("Delete the NER")} ${name}?\n\n`
          + (otherPages.length
            ? `${t("It is also drawn on")} ${otherPages.map((n) => pageName(p, n)).join(", ")}. `
            : "")
          + t("It leaves every page, the NERs list, the analysis and the export. Restore on the NERs screen (Removed (n)) brings it back.")
        : isNer
          ? `${t("Delete only this marker of")} ${name} (${pageName(p, page)})?\n\n`
            + (otherPages.length
              ? `${t("The NER stays on")} ${otherPages.map((n) => pageName(p, n)).join(", ")} ${t("and in the NERs list.")}`
              : t("It is the NER's last marker, so the NER leaves the register too."))
          : `${t("Delete")} ${name}?`;
      if (!confirm(msg)) return;
    }
    try {
      if (type === "element") await api.deleteElement(p.id, d.id, scope);
      else if (type === "area") await api.deleteZone(p.id, d.id);
      else if (type === "route") await api.deleteRoute(p.id, d.id);
      else await api.deleteVertical(p.id, d.id);
      await reloadAll();
      setSelected(null);
      ctx.notify(wholeNer
        ? `${name} ${t("removed — it leaves every page, the NERs list and the analysis. Restore on the NERs screen brings it back.")}`
        : `${name} ${t("deleted from the drawing")}.`
          + (type === "element" && !DEMAND_KINDS.has(d.kind) ? "" : ` ${t("Re-run the analysis to see the effect.")}`));
    } catch (err: any) { ctx.notify(err.message, "err"); }
  };

  const deleteSelected = async () => {
    if (!selected || !["element", "route", "vertical", "area"].includes(selected.type)) return;
    await removeItem(selected.type, selected.data);
  };

  /** The narrower act: this one drawing of the NER goes, the room stays on
   *  its other sheets (for a duplicate marker on one sheet). */
  const deleteSelectedMarkerOnly = async () => {
    if (!selected || selected.type !== "element") return;
    await removeItem("element", selected.data, true, "marker");
  };

  /** What a click on a drawn thing does: erase it when the eraser is armed,
   *  select it otherwise. */
  const pick = (type: string, d: any) => {
    if (tool === "delete") {
      const cheap = type === "route" || (type === "element" && DEMAND_KINDS.has(d.kind));
      void removeItem(type, d, !cheap);
    } else {
      setSelected({ type, data: d });
    }
  };

  // Delete / Backspace removes what is selected — unless the keys are being
  // typed into a box (the inspector's Name field is one click away).
  const deleteRef = useRef<() => void>(() => {});
  deleteRef.current = () => { void deleteSelected(); };
  // Enter closes the area being drawn; Escape drops it (and the route draft).
  const areaKeyRef = useRef<(key: string) => boolean>(() => false);
  areaKeyRef.current = (key: string) => {
    if (key === "Enter" && tool === "area" && areaDraft.length) { void finishArea(); return true; }
    if (key === "Escape" && (areaDraft.length || draft.length)) { setAreaDraft([]); setDraft([]); return true; }
    return false;
  };
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT"
                 || el.isContentEditable)) return;
      if (ev.key === "Enter" || ev.key === "Escape") {
        if (areaKeyRef.current(ev.key)) ev.preventDefault();
        return;
      }
      if (ev.key !== "Delete" && ev.key !== "Backspace") return;
      ev.preventDefault();
      deleteRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /** The person's answer to "is this page a key plan?" — for a title block
   *  read wrong. Ties to rooms on it are released and the matching runs
   *  again, so switching it off brings the page's rooms back too. */
  const toggleKeyPlan = async (on: boolean) => {
    if (!p) return;
    const question = on
      ? t("Mark this page as a key plan? A key plan only illustrates: its rooms leave every TEAP × drawing crossing, a TEAP line tied to one of them is released, and the matching runs again.")
      : t("Take this page off the key plans? Its rooms go back into the TEAP × drawing crossing and the matching runs again.");
    if (!confirm(question)) return;
    try {
      const r = await api.setKeyPlan(p.id, page, on);
      await ctx.reload();
      await reloadAll();
      const parts = [on ? t("Page marked as a key plan.") : t("Page taken off the key plans.")];
      if (r.released_decisions) parts.push(`${r.released_decisions} ${t("TEAP tie(s) to a room on this page released.")}`);
      if (r.matching) parts.push(t("Matching run again."));
      if (on && r.counted_here?.length) {
        parts.push(`${t("Still counted on this page — delete them or replace them with *NER references:")} ${r.counted_here.join(", ")}`);
      }
      ctx.notify(parts.join(" "));
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  if (!p) return <div style={{ padding: 18 }} className="muted">{t("Select a project first.")}</div>;
  if (!p.drawings?.length) {
    return <div style={{ padding: 18 }} className="muted">{t("Import a drawing first.")}</div>;
  }

  const radiusUnits = (metres: number) =>
    mpu ? metres / mpu / (p.settings.routing_slack_factor || 1) : 0;

  return (
    <div className="viewer">
      <div className="canvas-wrap" ref={wrapRef}>
        {/* The top strip (2.14.0): only what is about *where you are* — the
            page, whether it is a key plan, and the search. Every tool went
            into the toolbox down the left. Marcelo, 29 Sep 2026: "ficou com
            muitas funções e muito grande". */}
        <div className="toolbar">
          <span className="pager">
            <button className="small" disabled={pageIdx <= 0} title={t("Previous page")}
                    onClick={() => { setPage(p.pages[pageIdx - 1].number); setSelected(null); }}>◀</button>
            {/* "Page 13 - OWC-410B8-CSL-O · LEVEL 01": the page number the tool
                uses, the drawing number the design team uses, the level when the
                title block states one. */}
            <select value={page} onChange={(e) => { setPage(Number(e.target.value)); setSelected(null); }}
                    style={{ width: 230 }} title={t("Page number - drawing number from the title block")}>
              {p.pages.map((pg: any) => (
                <option key={pg.number} value={pg.number}>
                  {p.multi_book ? `${bookSeries(p, pg.drawing_id)} · ${t("Page")} ${pg.page}` : `${t("Page")} ${pg.number}`}{pg.sheet_number ? ` - ${pg.sheet_number}` : ""}{pg.level ? ` · ${pg.level}` : ""}{pg.key_plan ? " · KEY" : ""}
                </option>
              ))}
            </select>
            <button className="small" disabled={pageIdx < 0 || pageIdx >= p.pages.length - 1} title={t("Next page")}
                    onClick={() => { setPage(p.pages[pageIdx + 1].number); setSelected(null); }}>▶</button>
            <span className="small muted" style={{ marginBottom: 0 }}>{pageIdx + 1}/{p.pages.length}</span>
          </span>
          {/* Key plan (2.13.0): read off the DRAWING TITLE of the title block,
              ticked per page on the Scale screen; the box is here too. */}
          <label className={`small key-plan-toggle ${isKey ? "on" : ""}`}
                 title={t("A key plan only illustrates: its rooms are not drawn or listed and take part in no TEAP × drawing crossing, and no NER is created from it. Read off the drawing title in the title block; untick it if the title block was read wrong.")}>
            <input type="checkbox" style={{ width: "auto" }} checked={isKey}
                   onChange={(e) => void toggleKeyPlan(e.target.checked)} />
            {t("Key plan")}
          </label>
          {/* Search (2.12.0): any name on any page — a room, a TEAP line
              tied to it, a marker, a named area. Enter goes to the first. */}
          <span className="viewer-search">
            <input type="search" value={searchQ} placeholder={t("search a name…")}
                   title={t("Find a room, a TEAP code tied to it, a NER or any marker, or a named area, on any page")}
                   onChange={(e) => { setSearchQ(e.target.value); setSearchOpen(true); }}
                   onFocus={() => setSearchOpen(true)}
                   onBlur={() => setTimeout(() => setSearchOpen(false), 180)}
                   onKeyDown={(e) => {
                     if (e.key === "Enter" && searchHits.length) { e.preventDefault(); goTo(searchHits[0]); }
                     if (e.key === "Escape") setSearchOpen(false);
                   }} />
            {searchOpen && searchQ.trim() && (
              <div className="search-hits">
                {searchHits.length === 0 && <div className="muted small hit">{t("nothing on the drawing has this name")}</div>}
                {searchHits.slice(0, 15).map((h, k) => (
                  <button type="button" key={`${h.type}${h.data.id}`} className={`hit ${k === 0 ? "first" : ""}`}
                          onMouseDown={(e) => { e.preventDefault(); goTo(h); }}>
                    <span className="nm">{h.name}</span>
                    <span className="muted small"> {h.what} · {pageName(p, h.page)}</span>
                    {h.extra && <div className="muted small">TEAP: {h.extra}</div>}
                  </button>
                ))}
                {searchHits.length > 15 && (
                  <div className="muted small hit">+{searchHits.length - 15} {t("more — type more of the name")}</div>
                )}
              </div>
            )}
          </span>
          {busy && <span className="small muted" style={{ marginBottom: 0 }}>{busy}</span>}
          {!pageInfo?.scale_confirmed && (
            <span className="pill" style={{ color: "var(--warn)" }}>{t("scale not confirmed")}</span>
          )}
          {unplaced.length > 0 && (
            <span className="small" style={{ color: "var(--warn)", marginBottom: 0 }}
                  title={unplaced.map((u) => `${u.name}: ${u.why}`).join("\n")}>
              {unplaced.length}{" "}
              {t("NER(s) in the register have no position on this drawing set. Place them with the +NER tools.")}
            </span>
          )}
        </div>

        {/* The toolbox (2.14.0): the tools in a column down the left of the
            sheet, the view switches under them. Folds to a tab. */}
        {!toolboxOpen && (
          <button className="toolbox-reopen" onClick={toggleToolbox} title={t("Show the tools")}>{t("Tools")} ›</button>
        )}
        <div className={`toolbox ${toolboxOpen ? "" : "collapsed"}`}>
          <div className="tb-head">
            <span>{t("Tools")}</span>
            <button className="toolbox-toggle" onClick={toggleToolbox} title={t("Hide the tools")}>‹</button>
          </div>
          {TOOL_GROUPS.map((group, gi) => (
            <div key={gi} className={`tool-group ${gi === 4 ? "illustrative" : ""}`}
                 title={gi === 4 ? t("Illustrative tools: drawn on the sheet and in the marked-up PDF, counted nowhere") : undefined}>
              {group.map((tl) => (
              <button key={tl} className={`small ${tool === tl ? "active" : ""} ${ILLUSTRATIVE_TOOLS.has(tl) ? "illus" : ""}`}
                      disabled={isKey && KEY_PLAN_BLOCKED.has(tl)}
                      style={tl === "delete" && tool === "delete"
                        ? { background: "var(--bad)", borderColor: "var(--bad)", color: "#fff" } : undefined}
                      title={isKey && KEY_PLAN_BLOCKED.has(tl)
                        ? t("This page is a key plan — it only illustrates. Place the NER or the Wi-Fi point on the detail sheet, and point at it here with *NER.")
                        : tl === "delete"
                        ? t("Eraser: click a marker, a wireless point, a named area, a route segment or a shaft to delete it. Stays on until you choose select.")
                        : tl === "add-ner-ref-critical" || tl === "add-ner-ref"
                        ? t("A reference to a NER on a key plan: named after a NER of the register, drawn with its 90 m / 70 m circles to this sheet's scale, and counted nowhere — no register row, no TEAP link, no port")
                        : tl === "add-ter-ref" || tl === "add-cow-ref" || tl === "add-diva-ref"
                        ? t("A reference to a TER, a COW or a DIVA node on a key plan: named after the real one, drawn with a dashed ring, counted nowhere")
                        : tl === "area"
                        ? t("A named area, to point something out (BTOC, TER, a compound): click each corner, double-click or press Enter to close it, then name it. Illustrative only — nothing is counted from it")
                        : tl === "add-wireless"
                        ? t("A Wi-Fi point: it marks a space that has wireless, not an access point count; measured to the NER of its TEAP space; it takes no port — the space's DWISA line is the port")
                        : tl === "add-ner-critical" || tl === "add-ner"
                        ? t("A NER: named in sequence (NERc_01.1 …, NER_20.1 …) — rename it as you like")
                        : tl.startsWith("add-") && !ADD_KIND[tl].startsWith("NER")
                        ? t("Drawn on the plan only — never serves a space")
                        : undefined}
                      onClick={() => { setTool(tl); setDraft([]); setAreaDraft([]); }}>
                {TOOL_LABEL[tl]}
              </button>
              ))}
            </div>
          ))}
          {tool === "area" && (
            <div className="small tb-note">
              {areaDraft.length
                ? `${areaDraft.length} ${t("corner(s) — double-click or Enter to close, Esc to drop")}`
                : t("click the first corner of the area")}
            </div>
          )}
          {(tool === "add-ner-ref-critical" || tool === "add-ner-ref") && (
            <select value={refName} onChange={(e) => setRefName(e.target.value)}
                    title={t("The NER this reference is named after. Click the sheet to place it.")}>
              <option value="">{t("— name it after: ask each time —")}</option>
              {registerNers.map((n: any) => (
                <option key={n.id} value={n.display_name}>
                  {n.display_name}{n.classification === "critical" ? " ★" : ""}
                </option>
              ))}
            </select>
          )}
          <div className="tool-group view">
            <button className="small" onClick={() => { setZoom(0.6); setPan({ x: 40, y: 40 }); }}>{t("Fit")}</button>
            <button className={`small ${showRadii ? "active" : ""}`} onClick={() => setShowRadii(!showRadii)}>{t("Radii")}</button>
            {/* On a key plan the spaces are never drawn (2.14.0): the switch
                is off and stays off there. */}
            <button className={`small ${showSpaces && !isKey ? "active" : ""}`} disabled={isKey}
                    title={isKey ? t("A key plan has no spaces") : undefined}
                    onClick={() => setShowSpaces(!showSpaces)}>{t("Spaces")}</button>
            {/* Shown only when there is something to toggle. Since a NER you
                draw is a NER (its marker IS the register row), a register room
                with a position and no marker on the sheet is a rare leftover —
                and a button that never changes anything reads as broken. */}
            {proposed.length > 0 && (
              <button className={`small ${showProposed ? "active" : ""}`}
                      title={t("Rooms in the register that carry no marker on this sheet")}
                      onClick={() => setShowProposed(!showProposed)}>
                {t("Register NERs")} ({proposed.length})
              </button>
            )}
            {/* The analysis runs as a job. Taking ``await api.analyse(...)`` as
                the result stored ``{job_id}`` as the coverage, and the overlay
                then painted nothing while the toolbar said it had been updated —
                a silent lie rather than a visible error. */}
            <button className="small primary" disabled={coverageJob.busy} onClick={async () => {
              try {
                await coverageJob.start(() => api.analyse(p.id, "As-Is", true), async (j) => {
                  setBusy(j.state === "running" ? (j.stage || t("Computing coverage…")) : "");
                  if (j.state === "error") { ctx.notify(j.error, "err"); return; }
                  if (j.state !== "done") return;
                  setCoverage(j.result || null);
                  ctx.notify(t("Coverage overlay updated."));
                });
              } catch (e: any) { ctx.notify(e.message, "err"); setBusy(""); }
            }}>{t("Coverage")}</button>
          </div>
        </div>

        <Stage width={size.w} height={size.h} onWheel={onWheel} onClick={onStageClick}
               // A double-click closes the outline — when it lands on the last
               // corner. Konva calls any two clicks inside 400 ms a double-click
               // wherever they land, and a quick hand placing two corners must
               // not have its outline closed between them.
               onDblClick={(e) => {
                 if (tool !== "area") return;
                 const pt = toPdf(e.target.getStage());
                 const last = areaDraft[areaDraft.length - 1];
                 if (last && Math.hypot(last[0] - pt.x, last[1] - pt.y) < 8 / zoom) void finishArea();
               }}
               draggable={tool === "select"}
               // Konva bubbles drag events, so a marker's own drag ended here
               // too — and its position in PDF units was taken as the pan, which
               // threw the sheet off screen every time a NER was moved ("o PDF
               // vai pra longe e eu tenho que dar Fit", Marcelo, 22 Sep 2026).
               // Only the stage's own drag moves the sheet.
               onDragEnd={(e) => {
                 if (e.target === e.target.getStage()) setPan({ x: e.target.x(), y: e.target.y() });
               }}
               x={pan.x} y={pan.y} scaleX={zoom} scaleY={zoom}
               style={{ cursor: tool === "select" ? "grab" : "crosshair" }}>
          <Layer>
            {bg && <KImage image={bg as any} width={pdfSize.w} height={pdfSize.h} listening={false} />}

            {/* named areas (2.8.0): faint fill, outline, the name on a tag at
                the centre. Under everything else — they are notes on the
                sheet, not results. */}
            {areas.map((z) => {
              const pts: number[] = (z.polygon || []).flat();
              if (pts.length < 6) return null;
              const n = pts.length / 2;
              const cx = pts.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b, 0) / n;
              const cy = pts.filter((_, i) => i % 2 === 1).reduce((a, b) => a + b, 0) / n;
              const on = selected?.type === "area" && selected.data.id === z.id;
              return (
                <Group key={`z${z.id}`} onClick={(ev) => { ev.cancelBubble = true; pick("area", z); }}>
                  {/* Konva has no separate fill opacity, so the fill colour
                      carries it as alpha (AREA_COLOUR #3d5980 = 61, 89, 128). */}
                  <Line points={pts} closed fill={`rgba(61, 89, 128, ${AREA_FILL_OPACITY})`}
                        stroke={on ? "#ff7a00" : AREA_COLOUR}
                        strokeWidth={(on ? 2.4 : 1.4) / zoom} />
                  <Label x={cx} y={cy} listening={false}>
                    <Tag fill={LABEL_TAG_FILL} opacity={LABEL_TAG_OPACITY} cornerRadius={3 / zoom}
                         stroke={AREA_COLOUR} strokeWidth={0.6 / zoom} />
                    <Text text={z.label} fontSize={12 / zoom} fontStyle="bold" fill={AREA_COLOUR}
                          padding={3 / zoom} />
                  </Label>
                </Group>
              );
            })}

            {/* the area being drawn */}
            {areaDraft.length > 0 && (
              <Line points={areaDraft.flat()} stroke="#c9bff2" strokeWidth={1.6 / zoom}
                    dash={[4 / zoom, 3 / zoom]} closed={areaDraft.length > 2}
                    fill={areaDraft.length > 2 ? `rgba(61, 89, 128, ${AREA_FILL_OPACITY})` : undefined}
                    listening={false} />
            )}
            {areaDraft.map((d, i) => (
              <Circle key={`ad${i}`} x={d[0]} y={d[1]} radius={3 / zoom} fill="#c9bff2" listening={false} />
            ))}

            {/* traced routes */}
            {routes.map((r) => {
              const on = selected?.type === "route" && selected.data.id === r.id;
              return (
                <Line key={`r${r.id}`} points={[r.x0, r.y0, r.x1, r.y1]}
                      stroke={on ? "#ff7a00" : "#00b3a4"} strokeWidth={(on ? 3.2 : 2) / zoom}
                      hitStrokeWidth={14 / zoom}
                      onClick={(ev) => { ev.cancelBubble = true; pick("route", r); }} />
              );
            })}

            {/* shafts / risers registered on this page: a teal square, the
                page it leads to beside it. */}
            {verticals.map((v) => {
              const lower = v.lower_page === page;
              const x = lower ? v.lower_x : v.upper_x, y = lower ? v.lower_y : v.upper_y;
              const on = selected?.type === "vertical" && selected.data.id === v.id;
              return (
                <Group key={`v${v.id}`} x={x} y={y}
                       onClick={(ev) => { ev.cancelBubble = true; pick("vertical", v); }}>
                  <Rect x={-6 / zoom} y={-6 / zoom} width={12 / zoom} height={12 / zoom}
                        fill={KIND_COLOUR.SHAFT} stroke={on ? "#ff7a00" : MARKER_RING}
                        strokeWidth={(on ? 2.2 : 1) / zoom} />
                  <Text x={9 / zoom} y={-5 / zoom} fontSize={9 / zoom} fill={KIND_COLOUR.SHAFT}
                        text={`${v.kind} ${lower ? "↑" : "↓"} p.${sheetNo(p, lower ? v.upper_page : v.lower_page)} · ${v.length_m} m`}
                        listening={false} />
                </Group>
              );
            })}

            {/* coverage radii */}
            {/* Reach circles are a NER thing. A TER, an IDF and a COW never
                serve a space, so drawing a 90 m ring around one would promise
                a coverage it can never provide. */}
            {showRadii && mpu && showProposed && proposed.filter((a) => canServe(a.kind)).map((a) => (
              <Group key={`prad${a.id}`}>
                <Circle x={a.x} y={a.y} radius={radiusUnits(p.settings.general_limit_m)}
                        stroke="#4a8cff"
                        strokeWidth={0.8 / zoom} dash={[6 / zoom, 4 / zoom]}
                        opacity={0.7} listening={false} />
              </Group>
            ))}

            {/* …and around a NER reference on a key plan: the circles are
                what the reference is drawn for (2.7.0). */}
            {showRadii && mpu && elements.filter((e) => drawsReach(e.kind)).map((e) => (
              <Group key={`rad${e.id}`}>
                <Circle x={e.x} y={e.y} radius={radiusUnits(p.settings.general_limit_m)}
                        stroke="#4a8cff" strokeWidth={0.8 / zoom} dash={[6 / zoom, 4 / zoom]} listening={false} />
                <Circle x={e.x} y={e.y} radius={radiusUnits(p.settings.photographer_limit_m)}
                        stroke="#9a4ccf" strokeWidth={0.8 / zoom} dash={[3 / zoom, 4 / zoom]} listening={false} />
              </Group>
            ))}

            {/* spaces */}
            {showSpaces && !isKey && spaces.map((s) => {
              const a = assignmentFor(s);
              const colour = a ? STATUS_COLOUR[a.status] || "#888" : "#6f7788";
              return (
                <Group key={`s${s.id}`} onClick={(e) => { e.cancelBubble = true; setSelected({ type: "space", data: s, assignment: a }); }}>
                  <Circle x={s.x} y={s.y} radius={4 / zoom + 2} fill={colour} opacity={a ? 0.85 : 0.45} />
                  {zoom > 0.5 && (
                    <Text x={s.x + 7 / zoom} y={s.y - 5 / zoom} text={s.space_code || s.name}
                          fontSize={9 / zoom} fill={colour} listening={false} />
                  )}
                </Group>
              );
            })}

            {/* connection lines */}
            {coverage && (coverage.assignments || [])
              .filter((a: any) => a.page === page && a.ner_key && nerById[a.ner_key])
              .map((a: any) => {
                const s = (a.drawing_space_id != null && spaces.find((x) => x.id === a.drawing_space_id))
                  || spaces.find((x) => (x.space_code || x.name).toUpperCase() ===
                    a.space_key.split("|").pop());
                const n = nerById[a.ner_key];
                if (!s || !n) return null;
                return (
                  <Line key={`l${a.space_key}`} points={[s.x, s.y, n.x, n.y]}
                        stroke={STATUS_COLOUR[a.status] || "#888"} strokeWidth={0.9 / zoom}
                        dash={[2 / zoom, 3 / zoom]} listening={false} opacity={0.8} />
                );
              })}

            {/* wireless point → the NER that carries its port */}
            {coverage && (coverage.assignments || [])
              .filter((a: any) => a.kind === "wireless_point" && a.page === page
                && a.ner_key && nerById[a.ner_key])
              .map((a: any) => {
                const w = elements.find((x) => `WP${x.id}` === a.space_key);
                const n = nerById[a.ner_key];
                if (!w || !n) return null;
                return (
                  <Line key={`lw${a.space_key}`} points={[w.x, w.y, n.x, n.y]}
                        stroke={STATUS_COLOUR[a.status] || "#888"} strokeWidth={0.9 / zoom}
                        dash={[2 / zoom, 3 / zoom]} listening={false} opacity={0.8} />
                );
              })}

            {/* elements */}
            {elements.map((e) => {
              const colour = KIND_COLOUR[e.kind] || "#888";
              // The dot keeps the notation colour; the name is written in a
              // shade that survives white paper. Yellow is a good fill and bad
              // ink, and the name is the half that carries the information.
              const ink = KIND_LABEL_COLOUR[e.kind] || colour;
              return (
                <Group key={`e${e.id}`} x={e.x} y={e.y} draggable={!e.locked && tool === "select"}
                       onClick={(ev) => { ev.cancelBubble = true; pick("element", e); }}
                       onDragEnd={async (ev) => {
                         await api.patchElement(p.id, e.id, { x: ev.target.x(), y: ev.target.y() });
                         await reloadAll();
                       }}>
                  {/* Filled in its kind colour, ringed in black. The ring is
                      what separates the marker from the linework underneath —
                      a yellow dot on a dense CAD sheet otherwise reads as part
                      of the drawing rather than as something laid over it. */}
                  {DEMAND_KINDS.has(e.kind) ? (
                    <>
                      {/* The wireless sign: a dot where the point is, two arcs
                          fanning out above it; an outdoor point stands on a
                          short mast. An invisible disc underneath keeps it
                          easy to click and drag. */}
                      <Circle radius={12 / zoom} fill="#ffffff" opacity={0.01} />
                      {[6.5, 11].map((r) => (
                        <Arc key={r} innerRadius={(r - 1.1) / zoom} outerRadius={(r + 1.1) / zoom}
                             angle={100} rotation={-140} fill={colour} listening={false} />
                      ))}
                      <Circle radius={2.6 / zoom} fill={colour}
                              stroke={MARKER_RING} strokeWidth={0.8 / zoom} />
                    </>
                  ) : REFERENCE_KINDS.has(e.kind) ? (
                    // A reference: the NER's colour, a dashed ring — a pointer
                    // to a room drawn elsewhere, not the room.
                    <Circle radius={7 / zoom} fill={colour}
                            stroke={MARKER_RING} strokeWidth={1.1 / zoom}
                            dash={[2.2 / zoom, 2.2 / zoom]} />
                  ) : (
                    <Circle radius={7 / zoom} fill={colour}
                            stroke={MARKER_RING} strokeWidth={1.1 / zoom} />
                  )}
                  {!e.confirmed && (
                    <Circle radius={11 / zoom} stroke="#f28c1a" strokeWidth={1.2 / zoom}
                            dash={[2 / zoom, 2 / zoom]} listening={false} />
                  )}
                  {/* The name on a white tag (2.8.0), a point larger and bold:
                      written straight onto CAD linework it read as part of
                      the drawing. */}
                  <Label x={(DEMAND_KINDS.has(e.kind) ? 13 : 10) / zoom}
                         y={(DEMAND_KINDS.has(e.kind) ? -8 : -9) / zoom} listening={false}>
                    <Tag fill={LABEL_TAG_FILL} opacity={LABEL_TAG_OPACITY} cornerRadius={2.5 / zoom} />
                    {/* A reference (*NER, *TER, *COW, *DIVA) is drawn to be read
                        from across a key plan, so its name is two points
                        larger than a room's (Marcelo, 14 Oct 2026). */}
                    <Text text={e.label} fontSize={(DEMAND_KINDS.has(e.kind) ? 10 : REFERENCE_KINDS.has(e.kind) ? 14 : 12) / zoom}
                          fontStyle="bold" fill={ink} padding={2 / zoom} />
                  </Label>
                </Group>
              );
            })}

            {/* Register rooms the sheet carries no marker for. They are part
                of the design, so they are drawn like it — solid, in the colour
                of their criticality, the same as every other NER. The label
                underneath says the sheet does not show it yet; that is a fact
                about the drawing, not a different kind of room, and it does not
                earn a colour of its own. */}
            {showProposed && proposed.map((a) => {
              const kind = KIND_COLOUR[a.kind] || "#888";
              const ring = kind;
              const ink = KIND_LABEL_COLOUR[a.kind] || kind;
              return (
                <Group key={`a${a.id}`} x={a.x} y={a.y}
                       draggable={!a.locked && tool === "select"}
                       onClick={(ev) => { ev.cancelBubble = true; setSelected({ type: "proposed", data: a }); }}
                       onDragEnd={async (ev) => {
                         try {
                           await api.moveNer(p.id, a.id, {
                             page, x: ev.target.x(), y: ev.target.y(),
                             reason: "moved on the drawing",
                           });
                           await reloadAll();
                         } catch (err: any) {
                           ctx.notify(err.message, "err");
                           await reloadAll();   // snap it back
                         }
                       }}>
                  <Circle radius={7 / zoom} stroke={MARKER_RING} strokeWidth={1.1 / zoom}
                          fill={ring} />
                  <Label x={10 / zoom} y={-14 / zoom} listening={false}>
                    <Tag fill={LABEL_TAG_FILL} opacity={LABEL_TAG_OPACITY} cornerRadius={2.5 / zoom} />
                    <Text text={a.name} fontSize={12 / zoom} fontStyle="bold" fill={ink} padding={2 / zoom} />
                  </Label>
                  {zoom > 0.4 && (
                    <Text x={10 / zoom} y={1 / zoom}
                          text={`${t("not on the sheet")} · ${a.space_code || a.space_name || ""}`}
                          fontSize={9 / zoom} fill={ink} opacity={0.85} listening={false} />
                  )}
                </Group>
              );
            })}

            {/* where the search landed: a ring that fades after a few seconds */}
            {focus && focus.page === page && (
              <Group listening={false}>
                <Circle x={focus.x} y={focus.y} radius={22 / zoom} stroke="#ff7a00" strokeWidth={3 / zoom} />
                <Circle x={focus.x} y={focus.y} radius={34 / zoom} stroke="#ff7a00" strokeWidth={1.5 / zoom}
                        dash={[5 / zoom, 4 / zoom]} />
              </Group>
            )}

            {/* in-progress route */}
            {draft.length > 0 && (
              <Line points={draft.flat()} stroke="#4a8cff" strokeWidth={1.6 / zoom}
                    dash={[4 / zoom, 3 / zoom]} />
            )}
            {draft.map((d, i) => (
              <Circle key={i} x={d[0]} y={d[1]} radius={3 / zoom} fill="#4a8cff" />
            ))}
          </Layer>
        </Stage>

        {/* The legend folds to a small tab (4.4.0), remembered per browser:
            on a laptop screen it sat over the corner of the sheet. Marcelo,
            22 Oct 2026: "a legenda que fica do lado direito abaixo poderia
            ser retrátil". */}
        {!legendOpen ? (
          <button type="button" className="legend-reopen" onClick={toggleLegend}
                  title={t("Show the legend")}>{t("LEGEND")} ▴</button>
        ) : (
        <div className="legend">
          <div style={{ display: "flex", alignItems: "center" }}>
            <strong style={{ fontSize: 11, flex: 1 }}>{t("LEGEND")}</strong>
            <button type="button" className="linkish legend-fold" onClick={toggleLegend}
                    title={t("Hide the legend")}>{t("hide")} ▾</button>
          </div>
          {LEGEND_ROWS.map((r) => (
            <div className="lg-row" key={r.label}>
              {/* The swatch is drawn the way the plan draws the thing: a dot
                  is filled and ringed in black, exactly like the marker, and an
                  outline row is a hollow box in its own colour. The dot used to
                  be a hollow ring in the kind colour, which is not what the
                  plan has ever shown. */}
              {r.style === "wifi" ? (
                <svg className="sw" viewBox="0 0 14 14" style={{ border: "none", background: "transparent" }}>
                  <path d="M2 6a7 7 0 0 1 10 0" fill="none" stroke={r.colour} strokeWidth="1.6" strokeLinecap="round" />
                  <path d="M4.3 8.1a3.8 3.8 0 0 1 5.4 0" fill="none" stroke={r.colour} strokeWidth="1.6" strokeLinecap="round" />
                  <circle cx="7" cy="10.2" r="1.5" fill={r.colour} />
                </svg>
              ) : (
              <div className="sw" style={{
                background: r.style === "dot" || r.style === "fill" || r.style === "reference" ? r.colour
                  : r.style === "area" ? `rgba(61, 89, 128, ${AREA_FILL_OPACITY + 0.2})` : "transparent",
                border: r.style === "dot"
                  ? `1px solid ${MARKER_RING}`
                  : r.style === "reference"
                  ? `1.5px dashed ${MARKER_RING}`
                  : r.style === "area"
                  ? `1.5px solid ${r.colour}`
                  : `2px ${r.style === "dashed" ? "dashed" : "solid"} ${r.colour}`,
                borderRadius: r.style === "dot" || r.style === "dashed" || r.style === "reference" ? "50%" : 3,
                opacity: r.style === "fill" ? 0.55 : 1,
              }} />
              )}
              <span>{t(r.label)}</span>
            </div>
          ))}
          <div className="lg-row" style={{ marginTop: 4 }}>
            <span className="muted">
              {p.settings.general_limit_m} m / {p.settings.photographer_limit_m} m
              {" · "}{t("slack")} {p.settings.routing_slack_factor}×
              {" · "}{t("scale")} {pageInfo?.scale_label || t("not set")}
            </span>
          </div>
          <div className="foot">{t(DISCLAIMER)}</div>
        </div>
        )}
      </div>

      {!inspectorOpen && (
        <button className="inspector-reopen" onClick={toggleInspector}
                title={t("Show the inspector")}>‹ {t("Inspector")}</button>
      )}
      <aside className={inspectorOpen ? "inspector" : "inspector collapsed"}>
        <button className="inspector-toggle" onClick={toggleInspector}
                title={t("Hide the inspector")}>›</button>
        <div className="aside-tabs">
          <button className={`small ${asideTab === "inspector" ? "active" : ""}`}
                  onClick={() => setAsideTab("inspector")}>{t("Inspector")}</button>
          <button className={`small ${asideTab === "naming" ? "active" : ""}`}
                  title={t("The naming reference, for reference only — it decides nothing")}
                  onClick={() => setAsideTab("naming")}>{t("Naming")}</button>
        </div>
        {asideTab === "naming" && <NamingReference />}
        {asideTab === "inspector" && (<>
        {!selected && isKey && (
          <p className="small key-plan-note">
            {t("This page is a key plan: it only illustrates. Its rooms are not drawn or listed and take part in no TEAP × drawing crossing, and no NER is created from it. Point at the NERs of the detail sheets with *NER★ and *NER.")}
          </p>
        )}
        {!selected && (
          <p className="muted small">
            {t("Click a marker, a space or a named area. Drag an unlocked marker to move it; the change is written to the audit log. The +NER tools place a room the study is about; +TER, +IDF, +COW and +DIVA draw what is in the building and never serve a space. +Wi-Fi places a Wi-Fi point: it marks a space that has wireless, not an access point count; measured to its NER; it takes no port — the DWISA line of its TEAP space is the port. The illustrative tools (violet) are drawn and counted nowhere: *NER★ and *NER place a reference to a NER on a key plan, named after a NER of the register and drawn with its reach circles to this sheet's scale; *TER, *COW and *DIVA do the same for those rooms, without circles; +area draws a named area (BTOC, TER, a compound) — click each corner, double-click or Enter to close it. To take anything back: select it and press Delete (or the Delete button here), or arm the delete tool and click what should go.")}
          </p>
        )}

        {selected?.type === "element" && (
          <>
            <h3>{selected.data.label}</h3>
            <p className="small muted">
              {t(KIND_LABEL[selected.data.kind])} · {t("page")} {sheetNo(p, selected.data.page)}
              {selected.data.origin === "manual" ? ` · ${t("drawn by you")}`
                : selected.data.detection_method === "teap_wireless" ? ` · ${t("placed from the TEAP")}`
                : selected.data.detection_method === "drawing_room" ? ` · ${t("from the room label")}`
                : ` · ${t("from the drawing")}`}
            </p>
            {selected.data.printed_as && (
              <p className="small muted" style={{ marginTop: -4 }}>
                {t("Printed on the drawing as")}: <span className="mono">{selected.data.printed_as}</span>
              </p>
            )}
            {(selected.data.pending || []).filter((v: string) => v.startsWith("criticality:") || v.startsWith("position:")).map((v: string, i: number) => (
              <p key={i} className="small" style={{ color: "var(--warn)", marginTop: -4 }}>{v}</p>
            ))}
            {/* Rename, re-classify, delete: what the "On the drawing" tab of
                the NERs screen used to do for every marker. For a NER the
                same edits are on the NERs screen too, and they agree — one
                name, one kind, wherever it is changed. */}
            {REFERENCE_KINDS.has(selected.data.kind) && !NER_REFERENCE_KINDS.has(selected.data.kind) && (
              <p className="small" style={{ color: "var(--accent, #4c8dff)" }}>
                {t("A reference on a key plan: it points at a room drawn on another sheet. Drawn only — no register row, no TEAP link, nothing counted, no reach circles.")}
              </p>
            )}
            {NER_REFERENCE_KINDS.has(selected.data.kind) && (
              <>
                <p className="small" style={{ color: "var(--accent, #4c8dff)" }}>
                  {t("A reference on a key plan: it points at a NER drawn on another sheet. Drawn only, with its reach circles to this sheet's scale — no register row, no TEAP link, no port, nothing counted.")}
                </p>
                <label>{t("Points at (NER of the register)")}</label>
                <select value={registerNers.some((n: any) => n.display_name === selected.data.label) ? selected.data.label : ""}
                        disabled={selected.data.locked}
                        onChange={(ev) => { if (ev.target.value) void patchSelected({ label: ev.target.value }); }}>
                  <option value="">{t("— a name of its own (type it below) —")}</option>
                  {registerNers.map((n: any) => (
                    <option key={n.id} value={n.display_name}>
                      {n.display_name}{n.classification === "critical" ? " ★" : ""}
                    </option>
                  ))}
                </select>
              </>
            )}
            <label>{t("Name")}</label>
            <input className="mono" defaultValue={selected.data.label} disabled={selected.data.locked}
                   key={`n${selected.data.id}`}
                   title={t("Rename — recorded in the audit log")}
                   onBlur={(ev) => {
                     const v = ev.target.value.trim();
                     if (!v || v === selected.data.label) return;
                     // The same check as on the NERs screen (4.2.0).
                     const twin = selected.data.ner_asset_id
                       ? registerNers.find((n: any) => n.id !== selected.data.ner_asset_id
                           && nerNameKey(n.display_name) === nerNameKey(v))
                       : null;
                     if (twin && p) {
                       const same = confirm(
                         `${v} ${t("is already the name of another NER")}: ${twin.display_name}`
                         + `${twin.pages?.length ? ` (p. ${twin.pages.map((n: number) => pageName(p, n)).join(", ")})` : ""}.\n\n`
                         + t("Is it the same NER? OK makes the two one NER, with every marker of both. Cancel keeps the current name — choose another one."));
                       const el = ev.target;
                       if (same) {
                         void (async () => {
                           try {
                             await api.consolidateNers(p.id, {
                               primary_id: twin.id, duplicate_id: selected.data.ner_asset_id, force: true,
                               justification: `the same name (${v}) given in the Drawing viewer — the same NER`,
                             });
                             await reloadAll();
                             setSelected(null);
                             ctx.notify(t("consolidated — reversible from the history"));
                           } catch (err: any) { ctx.notify(err.message, "err"); el.value = selected.data.label; }
                         })();
                       } else el.value = selected.data.label;
                       return;
                     }
                     void patchSelected({ label: v });
                   }} />
            {DEMAND_KINDS.has(selected.data.kind) && (() => {
              const a = (coverage?.assignments || []).find(
                (x: any) => x.space_key === `WP${selected.data.id}`);
              const samePage = tieOptions.filter((o) => o.page === page);
              const otherPages = tieOptions.filter((o) => o.page !== page);
              return (
                <>
                <label>{t("TEAP space")}</label>
                <select value={selected.data.space_key || ""}
                        title={t("The TEAP space this Wi-Fi point belongs to. Its wireless port is that space's DWISA line, counted on the space whatever is drawn; the point adds no port.")}
                        onChange={(ev) => void patchSelected({ space_key: ev.target.value })}>
                  <option value="">{t("— none (not in the TEAP, no port) —")}</option>
                  {samePage.length > 0 && (
                    <optgroup label={t("On this page")}>
                      {samePage.map((o) => (
                        <option key={o.space_key} value={o.space_key}>
                          {o.space_code ? `${o.space_code} · ` : ""}{o.space_name}{o.wireless_ports ? ` (${t("TEAP wireless")} ${o.wireless_ports})` : ""}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {otherPages.length > 0 && (
                    <optgroup label={t("Other pages")}>
                      {otherPages.map((o) => (
                        <option key={o.space_key} value={o.space_key}>
                          {o.space_code ? `${o.space_code} · ` : ""}{o.space_name} (p{sheetNo(p, o.page)})
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {selected.data.space_key && !tieOptions.some((o) => o.space_key === selected.data.space_key) && (
                    <option value={selected.data.space_key}>{selected.data.space_name || selected.data.space_key}</option>
                  )}
                </select>
                <p className="small muted">
                  {selected.data.space_key
                    ? (selected.data.tie_source === "manual" ? t("tied by you")
                       : selected.data.tie_source === "teap" ? t("the TEAP space this point was placed for — it stays tied wherever you drag it; change or clear it here if it serves another space")
                       : t("nearest matched room on this sheet — proposed; change it if the point serves another space"))
                    : (selected.data.tie_source === "manual" ? t("cleared by you — not in the TEAP, no port") : t("no matched room within the limit on this sheet — not in the TEAP, no port"))}
                </p>
                {/* 4.5.0: indoor (a covered area) or outdoor (an open area),
                    said by the person — the same field a NER has. */}
                <label>{t("Indoor / outdoor")}</label>
                <select value={selected.data.environment || ""}
                        title={t("Where the service is given: indoor (a covered area) or outdoor (an open area). A column of the Wireless points sheet in the workbook.")}
                        onChange={(ev) => void patchSelected({ environment: ev.target.value })}>
                  <option value="">{t("— not said —")}</option>
                  <option value="indoor">{t("Indoor")}</option>
                  <option value="outdoor">{t("Outdoor")}</option>
                </select>
                <p className="small">
                  {t("A Wi-Fi point takes no port and is not an access point count: the DWISA line of its TEAP space is the port. It is measured to the NER of its space, or the nearest within the limit.")}<br />
                  {a ? (
                    <>
                      {t("Serving NER")}: <strong>{a.ner_label || t("none within the limit")}</strong>
                      {a.evaluation?.effective_distance_m != null &&
                        ` · ${fmtLen(a.evaluation.effective_distance_m, ctx.units)} / ${a.evaluation.limit_m} m`}
                      {" "}<span className="pill" style={{ color: STATUS_COLOUR[a.status] }}>{t(a.status)}</span>
                    </>
                  ) : t("Not analysed yet — press Coverage on this screen to measure it.")}
                </p>
                </>
              );
            })()}
            <label>{t("Kind")}</label>
            <select value={selected.data.kind} disabled={selected.data.locked}
                    onChange={(ev) => void patchSelected({ kind: ev.target.value })}>
              {(DEMAND_KINDS.has(selected.data.kind) ? ["WIRELESS"]
                : REFERENCE_KINDS.has(selected.data.kind) ? REF_CHOICES : KIND_CHOICES).map((k) => (
                <option key={k} value={k}>{t(KIND_LABEL[k])}</option>
              ))}
              {!KIND_CHOICES.includes(selected.data.kind) && !DEMAND_KINDS.has(selected.data.kind)
                && !REFERENCE_KINDS.has(selected.data.kind) && (
                <option value={selected.data.kind}>{t(KIND_LABEL[selected.data.kind] || selected.data.kind)}</option>
              )}
            </select>
            {canServe(selected.data.kind) && selected.data.ner_asset_id != null && (
              <>
                <label>{t("Indoor / outdoor")}</label>
                <select value={selected.data.environment || ""} disabled={selected.data.locked}
                        title={t("Where the rack stands — it decides the kind of rack the venue is sent. A column of the NERs sheet in the workbook.")}
                        onChange={async (ev) => {
                          try {
                            await api.patchNer(p.id, selected.data.ner_asset_id, { environment: ev.target.value || null });
                            await reloadAll();
                            const fresh = (await api.elements(p.id, page)).find((x: any) => x.id === selected.data.id);
                            if (fresh) setSelected({ type: "element", data: fresh });
                          } catch (e: any) { ctx.notify(e.message, "err"); }
                        }}>
                  <option value="">{t("— not said —")}</option>
                  <option value="indoor">{t("Indoor")}</option>
                  <option value="outdoor">{t("Outdoor")}</option>
                </select>
              </>
            )}
            <p className="small">
              {t("Confidence")} {(selected.data.confidence * 100).toFixed(0)}% ·{" "}
              {selected.data.confirmed ? t("confirmed") : t("awaiting confirmation")}
            </p>
            <ul className="small muted">
              {(selected.data.evidence || []).map((x: string, i: number) => <li key={i}>{x}</li>)}
            </ul>
            {canServe(selected.data.kind) && (
              <p className="small">
                {t("Capacity")}: {selected.data.total_ports ?? t("unknown")}
                {selected.data.total_ports != null && ` (${selected.data.used_ports} ${t("used")}, ${selected.data.reserved_ports} ${t("reserved")})`}
              </p>
            )}
            <div className="row">
              <button className="small" onClick={() => void patchSelected({ confirmed: !selected.data.confirmed })}>
                {selected.data.confirmed ? t("Unconfirm") : t("Confirm")}
              </button>
              <button className="small" onClick={() => void patchSelected({ locked: !selected.data.locked })}>
                {selected.data.locked ? t("Unlock") : t("Lock")}
              </button>
              <button className="small danger" disabled={selected.data.locked} onClick={deleteSelected}
                      title={canServe(selected.data.kind) && selected.data.ner_asset_id != null
                        ? t("Deletes the NER: every page, the NERs list, the analysis and the export. Restore on the NERs screen brings it back.")
                        : undefined}>
                {t("Delete")}
              </button>
            </div>
            <p className="small muted">{t("Or press Delete on the keyboard.")}</p>
            {canServe(selected.data.kind) && selected.data.ner_asset_id != null && (selected.data.occurrence_count || 1) > 1 && (
              <p className="small muted">
                {t("This NER is drawn on")} {selected.data.occurrence_count} {t("pages. Delete removes it from all of them.")}{" "}
                <button className="small" disabled={selected.data.locked} onClick={() => void deleteSelectedMarkerOnly()}
                        title={t("For a duplicate drawing of the room on this sheet: this marker goes, the NER stays on its other pages.")}>
                  {t("Delete only this marker")}
                </button>
              </p>
            )}
            {coverage && canServe(selected.data.kind) && (() => {
              // The run keys a room by its register id (A<id>); the marker
              // key (E<id>) is the fallback for a project that predates the
              // register. Reading E<id> alone showed every NER as serving
              // nothing (2.8.0).
              const load = coverage.ner_load?.[`A${selected.data.ner_asset_id}`]
                ?? coverage.ner_load?.[`E${selected.data.id}`];
              return (
                <>
                  <h3>{t("Served spaces")}</h3>
                  <ul className="small">
                    {(load?.spaces || []).map((k: string) => (
                      <li key={k}>{k.split("|").pop()}</li>
                    ))}
                  </ul>
                  <p className="small muted">
                    {load?.assigned_ports ?? 0} {t("ports assigned")} ·{" "}
                    {load?.utilisation_pct != null
                      ? `${load.utilisation_pct}% ${t("utilisation")}`
                      : t("capacity unknown")}
                    {load?.wireless_points ? ` · ${load.wireless_points} ${t("wireless point(s)")}` : ""}
                  </p>
                </>
              );
            })()}
          </>
        )}

        {selected?.type === "area" && (
          <>
            <h3>{selected.data.label}</h3>
            <p className="small muted">{t("Named area")} · {t("page")} {sheetNo(p, selected.data.page)} · {t("drawn by you")}</p>
            <p className="small" style={{ color: "var(--accent, #4c8dff)" }}>
              {t("Illustrative only: drawn on the sheet and in the marked-up PDF to point something out. Nothing is measured or counted from it.")}
            </p>
            <label>{t("Name")}</label>
            <input className="mono" defaultValue={selected.data.label} key={`z${selected.data.id}`}
                   title={t("Rename — recorded in the audit log")}
                   onBlur={(ev) => {
                     const v = ev.target.value.trim();
                     if (v && v !== selected.data.label) void patchArea({ label: v });
                   }} />
            <label>{t("Notes")}</label>
            <input defaultValue={selected.data.notes || ""} key={`zn${selected.data.id}`}
                   onBlur={(ev) => {
                     const v = ev.target.value.trim();
                     if (v !== (selected.data.notes || "")) void patchArea({ notes: v });
                   }} />
            <p className="small muted">{(selected.data.polygon || []).length} {t("corners")}</p>
            <div className="row">
              <button className="small danger" onClick={deleteSelected}>{t("Delete")}</button>
            </div>
            <p className="small muted">{t("Or press Delete on the keyboard.")}</p>
          </>
        )}

        {(selected?.type === "route" || selected?.type === "vertical") && (
          <>
            <h3>{selected.type === "route" ? t("Route segment") : t("Shaft / riser")}</h3>
            <p className="small muted">
              {selected.type === "route"
                ? `${t("page")} ${sheetNo(p, selected.data.page)} · ${selected.data.kind}`
                : `${selected.data.kind} · ${t("pages")} ${sheetNo(p, selected.data.lower_page)} ↔ ${sheetNo(p, selected.data.upper_page)} · ${selected.data.length_m} m`}
            </p>
            <p className="small">
              {selected.type === "route"
                ? t("Distances are measured along traced routes instead of the straight line. Deleting this segment changes them at the next analysis.")
                : t("A shaft is what lets a NER on one page be measured to a space on another. Deleting it puts those spaces back to 'other level — not measured'.")}
            </p>
            <div className="row">
              <button className="small danger" onClick={deleteSelected}>{t("Delete")}</button>
            </div>
            <p className="small muted">{t("Or press Delete on the keyboard.")}</p>
          </>
        )}

        {selected?.type === "space" && (
          <>
            <h3>{selected.data.name}</h3>
            <p className="small mono muted">{selected.data.space_code || "no code"} · {pageName(p, selected.data.page)}</p>
            {selected.assignment ? (
              <>
                <p className="small">
                  {t("Serving NER")}: <strong>{selected.assignment.ner_label || t("none")}</strong><br />
                  {t("Distance")}: {fmtLen(selected.assignment.evaluation?.effective_distance_m, ctx.units)}{" "}
                  {t("of")} {selected.assignment.evaluation?.limit_m} m<br />
                  {t("Method")}: {selected.assignment.evaluation?.method}<br />
                  {t("Ports")}: {selected.assignment.ports_required}
                </p>
                <span className="pill" style={{ color: STATUS_COLOUR[selected.assignment.status] }}>
                  {selected.assignment.status}
                </span>
                <h3>{t("Assumptions")}</h3>
                <ul className="small muted">
                  {[...(selected.assignment.evaluation?.assumptions || []),
                    ...(selected.assignment.evaluation?.warnings || []),
                    ...(selected.assignment.reasons || [])].map((x: string, i: number) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="small muted">{t("Run “Coverage” to see this space's assignment.")}</p>
            )}
          </>
        )}

        {selected?.type === "proposed" && (
          <>
            <h3>{selected.data.name}</h3>
            <p className="small mono muted">
              {selected.data.code} · {t("page")} {sheetNo(p, selected.data.page)}
            </p>
            <span className="pill" style={{ color: "var(--ok)" }}>
              {t("in the register — not drawn on the sheet")}
            </span>{" "}
            <span className="pill" style={{
              color: selected.data.critical ? "var(--bad)" : "var(--muted)",
            }}>{selected.data.critical ? t("Critical") : t("Non-critical")}</span>
            {selected.data.space_name && (
              <p className="small">
                {t("Sits inside")}: <strong>{selected.data.space_name}</strong>
                {selected.data.space_code ? ` (${selected.data.space_code})` : ""}
              </p>
            )}
            {selected.data.why && (
              <>
                <h3>{t("Why it is here")}</h3>
                <p className="small muted">{selected.data.why}</p>
              </>
            )}
            {(selected.data.pending_validations || []).length > 0 && (
              <>
                <h3>{t("Outstanding validations")}</h3>
                <ul className="small muted">
                  {selected.data.pending_validations.map((v: string, i: number) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </>
            )}
            <p className="small muted">
              {selected.data.locked
                ? t("Locked. Unlock it on the register to move it.")
                : t("Drag it to move it. The move is recorded.")}
            </p>
          </>
        )}
        </>)}
      </aside>
    </div>
  );
}
