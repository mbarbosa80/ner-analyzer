import { useEffect, useMemo, useRef, useState } from "react";
import type { Ctx } from "../App";
import { JobBar } from "../components/JobBar";
import { WideScroll } from "../components/WideScroll";
import { api } from "../lib/api";
import {
  GROUP_COLOUR, GROUP_LABEL, GROUP_ORDER, KIND_COLOUR, KIND_LABEL, STATUS_COLOUR, STATUS_LABEL,
  canServe, fmtLen, groupOf,
} from "../lib/notation";
import { useJob } from "../lib/useJob";
import { t } from "../lib/i18n";
import { useSort } from "../components/useSort";

const CANONICAL_FIELDS = [
  "venue_code", "venue_name", "building", "level", "zone", "fa_code",
  "functional_area", "space_code", "space_name", "product_code",
  "product_description", "product_category", "quantity", "network_ports",
  "wireless_required", "criticality", "sport_code", "comments",
  // Optional, and absent from every TEAP seen so far. When a sheet does name
  // the NER that serves a space, that is the answer — see Demand per space.
  "serving_ner",
];

function useAsync<T>(fn: () => Promise<T>, deps: any[], initial: T) {
  const [data, setData] = useState<T>(initial);
  // Starts true on purpose. With `false` there is a frame where the panel renders
  // the empty state before the first fetch runs, so a worklist with two unresolved
  // spaces briefly claims "0 unresolved" — false reassurance is the one thing this
  // tool must never give.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fn());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, setData, loading, error, reload: run };
}

/**
 * Ordering for the lists that offer drawing spaces to pick from.
 *
 * These lists used to come out in insertion order, which is page order — fine
 * for the tool, useless for a person. Someone resolving a match knows the code
 * or the room name, not which sheet it was extracted from, and a `select`
 * only supports type-ahead usefully when it is sorted.
 *
 * `numeric: true` is the part that matters: a plain string sort puts
 * `SPT.16` before `SPT.6`. `sensitivity: "base"` makes it ignore case and
 * accents, so `Sala Técnica` sits where a reader expects it.
 */
/** How many options the alias suggestion list renders. A datalist with several
 *  thousand entries makes the input sluggish; the box accepts free text anyway,
 *  so the cap costs nothing but has to be *stated* rather than silent. */
const DATALIST_LIMIT = 800;

export const SPACE_COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function spaceLabel(s: any, p?: any): string {
  return `${s.space_code ? `${s.space_code} · ` : ""}${s.name} (p${sheetNo(p, s.page)})`;
}

/** Drawing spaces sorted by the text actually shown, so the list reads in the
 *  same order it is scanned. */
function sortedSpaces(spaces: any[], p?: any): { key: number; label: string; s: any }[] {
  return spaces
    .map((s) => ({ key: s.id, label: spaceLabel(s, p), s }))
    .sort((a, b) => SPACE_COLLATOR.compare(a.label, b.label));
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className="pill" style={{ color: STATUS_COLOUR[status] || "var(--muted)" }}>
      {t(STATUS_LABEL[status] || status)}
    </span>
  );
}

/**
 * The pile a space is in — served, out of limit, served but not measured,
 * pending — and, under it, the precise reason (2.7.0). Marcelo, 22 Sep 2026:
 * the engine's ten statuses are one situation from the desk when the space
 * is not resolved, so the pill says the group and the small line says why.
 */
function GroupPill({ group, reason }: { group: string; reason?: string }) {
  return (
    <>
      <span className="pill" style={{ color: GROUP_COLOUR[group] || "var(--muted)" }}>
        {t(GROUP_LABEL[group] || group)}
      </span>
      {reason && <div className="small muted" style={{ marginTop: 2 }}>{t(reason)}</div>}
    </>
  );
}

// ---------------------------------------------------------------------------

export function ProjectsPanel({ ctx }: { ctx: Ctx }) {
  const sp = useSort<any>();
  const { data: projects, reload } = useAsync(() => api.listProjects(), [], [] as any[]);
  const [name, setName] = useState("");
  const [venue, setVenue] = useState("");
  //: The project package (4.6.0): one job for an export or an import.
  const xfer = useJob();
  const [importName, setImportName] = useState("");
  const [exporting, setExporting] = useState<number | null>(null);

  /** Write the whole project into one package and hand it to the browser. */
  const exportProject = async (pr: any) => {
    setExporting(pr.id);
    try {
      const j = await xfer.startAndWait(() => api.exportProject(pr.id));
      if (j.state === "done") {
        const r = j.result || {};
        const a = document.createElement("a");
        a.href = api.exportDownloadUrl(pr.id, r.filename);
        a.download = r.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        ctx.notify(`${t("Project package written")}: ${r.filename} (${Math.round((r.bytes || 0) / 1048576)} MB, ` +
                   `${r.documents} ${t("document(s)")}). ${t("It holds the venue's design books — share it only through your organisation's approved channels.")}`);
      } else if (j.state === "error") ctx.notify(j.error, "err");
    } catch (e: any) { ctx.notify(e.message, "err"); }
    finally { setExporting(null); }
  };

  /** A package from another computer becomes a new project of this account. */
  const importPackage = async (f: File) => {
    try {
      const j = await xfer.startAndWait(() => api.importProject(f, importName.trim()));
      if (j.state === "done") {
        const r = j.result || {};
        setImportName("");
        await reload();
        ctx.setProjectId(r.project_id);
        const an = r.analysis;
        const said = an == null ? ""
          : an.same === true ? ` ${t("The analysis was run again here and came out the same.")}`
          : an.stale_at_export ? ` ${t("The exported analysis was out of date; it was run again here on the current data.")}`
          : an.error ? ` ${t("The analysis could not be run again")}: ${an.error}`
          : ` ${t("The analysis was run again here and differs from the exported one — check Demand per space.")}`;
        ctx.notify(`${t("Project imported as")} “${r.name}” — ${t("exported by")} ${r.exported_by || "?"}` +
                   ` (${t("version")} ${r.from_app_version || "?"}). ${t("It is a copy: changes made here do not reach the original.")}${said}`,
                   an && an.same === false && !an.stale_at_export ? "err" : undefined);
      } else if (j.state === "error") ctx.notify(j.error, "err");
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const create = async () => {
    if (!name.trim()) return;
    try {
      const r = await api.createProject({ name: name.trim(), venue_code: venue.trim() || undefined });
      setName("");
      setVenue("");
      await reload();
      ctx.setProjectId(r.id);
      ctx.notify(t("Project created. Import the drawings and the TEAP next."));
    } catch (e: any) {
      ctx.notify(e.message, "err");
    }
  };

  return (
    <>
      <div className="card">
        <h2>{t("New project")}</h2>
        <div className="row">
          <div style={{ flex: 2 }}>
            <label>{t("Project name")}</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Venue - VVV" />
          </div>
          <div style={{ flex: 1 }}>
            <label>{t("Venue code (optional)")}</label>
            <input value={venue} onChange={(e) => setVenue(e.target.value)} placeholder="VVV" />
          </div>
          <button className="primary" onClick={create}>{t("Create")}</button>
        </div>
      </div>

      <div className="card">
        <h2>{t("Import a project package")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("A package is a .zip written by Export on another computer: the drawings, the TEAP and every decision of the project — scales, key plans, NERs, matches, ties, Wi-Fi points, areas. It comes in as a new project of yours, private until you share it; the analysis is run again here. The original is not touched and nothing is kept in step between the two copies.")}
        </p>
        <div className="row">
          <div style={{ flex: 2 }}>
            <label>{t("Name for the imported project (optional)")}</label>
            <input value={importName} onChange={(e) => setImportName(e.target.value)}
                   placeholder={t("the name it had — with “(imported …)” if taken here")} />
          </div>
          <div style={{ flex: 2 }}>
            <label>{t("Package (.zip)")}</label>
            <input type="file" accept=".zip,application/zip" disabled={xfer.busy}
                   onChange={(e) => {
                     const f = e.target.files?.[0];
                     e.target.value = "";
                     if (f) void importPackage(f);
                   }} />
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <JobBar job={xfer.job} onCancel={xfer.cancel} onDismiss={xfer.clear} />
        </div>
      </div>

      <div className="card">
        <h2>{t("Projects")}</h2>
        <table>
          <thead>
            <tr><sp.Th k="name">{t("Name")}</sp.Th><sp.Th k="venue_code">{t("Venue")}</sp.Th>
                <sp.Th k="owner">{t("Owner")}</sp.Th><sp.Th k="visibility">{t("Visible to")}</sp.Th>
                <sp.Th k="drawings">{t("Drawings")}</sp.Th><sp.Th k="teap_files">{t("TEAP files")}</sp.Th>
                <sp.Th k="scenarios">{t("Scenarios")}</sp.Th><th /></tr>
          </thead>
          <tbody>
            {sp.apply(projects).map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="mono">{p.venue_code || "—"}</td>
                <td className="small">
                  {p.mine ? <span style={{ color: "var(--ok)" }}>{t("you")}</span> : (p.owner || "—")}
                </td>
                <td style={{ minWidth: 150 }}>
                  {p.can_edit ? (
                    <select
                      value={p.visibility || "private"}
                      title={t("Shared means readable by the other accounts on this machine. Nothing is published anywhere.")}
                      onChange={async (e) => {
                        try {
                          await api.setVisibility(p.id, e.target.value);
                          await reload();
                          ctx.notify(
                            e.target.value === "shared"
                              ? t("Readable by the other accounts on this installation.")
                              : t("Private again — only you and administrators."),
                          );
                        } catch (err: any) { ctx.notify(err.message, "err"); }
                      }}
                    >
                      <option value="private">{t("only me")}</option>
                      <option value="shared">{t("accounts on this machine")}</option>
                    </select>
                  ) : (
                    <span className="small muted">{t("shared with you · read only")}</span>
                  )}
                </td>
                <td>{p.drawings}</td>
                <td>{p.teap_files}</td>
                <td>{p.scenarios}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="small" onClick={() => ctx.setProjectId(p.id)}>{t("Open")}</button>{" "}
                  <button className="small" disabled={xfer.busy}
                          title={t("Write the whole project — drawings, TEAP and every decision — into one package, to continue the work on another computer")}
                          onClick={() => void exportProject(p)}>
                    {exporting === p.id ? t("Exporting…") : t("Export")}
                  </button>{" "}
                  <button
                    className="small danger"
                    disabled={!p.can_edit}
                    title={p.can_edit ? "" : t("only the owner can delete this project")}
                    onClick={async () => {
                      if (!confirm(`${t("Delete")} “${p.name}” ${t("and everything in it?")}`)) return;
                      await api.deleteProject(p.id);
                      if (ctx.projectId === p.id) ctx.setProjectId(null);
                      await reload();
                    }}
                  >
                    {t("Delete")}
                  </button>
                </td>
              </tr>
            ))}
            {projects.length === 0 && (
              <tr><td colSpan={8} className="muted">{t("No projects yet.")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------

export function SetupPanel({ ctx }: { ctx: Ctx }) {
  const sf = useSort<any>();
  const p = ctx.project;
  const [teapId, setTeapId] = useState<number | null>(null);
  const [profiles, setProfiles] = useState<any[]>([]);
  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [venues, setVenues] = useState<any[] | null>(null);
  const [venueFilter, setVenueFilter] = useState("");
  const [allVenues, setAllVenues] = useState(false);
  const [templateName, setTemplateName] = useState("");
  //: The saved mappings (2.8.1). They were written since 2.2 and never offered
  //  back: "to reuse on another venue" was a promise the screen did not keep.
  const [templates, setTemplates] = useState<any[]>([]);
  const [settings, setSettings] = useState<any>(null);

  const drawJob = useJob();
  const teapJob = useJob();
  //: The books chosen together in the file dialog, and how each one went
  //  (4.6.0). Declared with every other hook, above the early return: placed
  //  below it in 4.6.0, the screen had one hook more once a project was open
  //  than before, and React refused to draw it (error #310) whenever a
  //  project was chosen after the application opened without one (4.6.1).
  const [queue, setQueue] = useState<{ name: string; state: string; note?: string }[]>([]);

  useEffect(() => { setSettings(p?.settings ? { ...p.settings } : null); }, [p?.id]);
  useEffect(() => {
    api.templates().then(setTemplates).catch(() => setTemplates([]));
  }, [p?.id, teapId]);

  if (!p) return <div className="muted">{t("Select a project first.")}</div>;

  const profile = profiles.find((x) => x.sheet === sheet);
  const totalRows = venues ? venues.reduce((a, v) => a + v.rows, 0) : 0;
  const selected = venues?.find((v) => v.venue_code === venueFilter);

  /**
   * Several books chosen together in the file dialog (4.6.0), read one after
   * the other — each to its end before the next, so the same book chosen
   * twice is refused by the server instead of racing in beside itself. A
   * file refused (the same book, a name already in the project, not a PDF)
   * is said and the rest carry on.
   */
  const uploadDrawings = async (files: File[]) => {
    // The same file picked twice in one selection is dropped here already.
    const seen = new Set<string>();
    const list = files.filter((f) => {
      const k = `${f.name.toLowerCase()}|${f.size}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
    const status = list.map((f) => ({ name: f.name, state: "waiting" as string, note: "" }));
    setQueue([...status]);
    const done: string[] = [];
    const refused: string[] = [];
    for (let i = 0; i < list.length; i++) {
      status[i].state = "reading";
      setQueue([...status]);
      try {
        const j = await drawJob.startAndWait(() => api.uploadDrawing(p.id, list[i]));
        if (j.state === "done") {
          const r = j.result || {};
          status[i].state = "imported";
          status[i].note = `${r.page_count} ${t("pages")}, ${r.summary?.spaces ?? 0} ${t("spaces")}`;
          done.push(list[i].name);
        } else {
          status[i].state = j.state === "cancelled" ? "cancelled" : "refused";
          status[i].note = j.error || j.stage;
          refused.push(list[i].name);
          if (j.state === "cancelled") break;
        }
      } catch (e: any) {
        status[i].state = "refused";
        status[i].note = e.message;
        refused.push(list[i].name);
      }
      setQueue([...status]);
      await ctx.reload();
    }
    if (done.length) {
      ctx.notify(
        `${done.length} ${t("book(s) imported")}` +
        (refused.length ? ` · ${refused.length} ${t("refused — see the list")}` : "") +
        ` — ${t("tick the key plans and confirm the scales, then place the NERs on the Scale screen")}`,
        refused.length ? "err" : undefined,
      );
    } else if (refused.length) {
      ctx.notify(`${t("Nothing imported")} — ${status.find((x) => x.note)?.note || ""}`, "err");
    }
  };

  /** Take one book out (4.6.0), after saying what goes with it. */
  const removeDrawing = async (d: any) => {
    try {
      const imp = await api.drawingImpact(p.id, d.id);
      const lines = [
        `${t("Remove")} ${d.filename} ${t("from this project?")}`,
        "",
        `${imp.pages} ${t("pages")}, ${imp.spaces} ${t("spaces")}, ${imp.markers} ${t("marker(s) drawn on it")}`,
      ];
      if (imp.duplicate_of?.length) lines.push(`${t("It is the same file as")} ${imp.duplicate_of.join(", ")}.`);
      if (imp.ners_only_here?.length) {
        lines.push(`${t("NERs drawn only on this book leave the register")}: ${imp.ners_only_here.join(", ")}`);
      }
      if (imp.ners_moved) lines.push(`${imp.ners_moved} ${t("NER(s) also drawn on another book stay, placed there")}`);
      if (imp.ties) lines.push(`${imp.ties} ${t("TEAP line(s) you tied to a room of this book will be untied")}`);
      lines.push("", t("The matching runs again on the books that remain. This cannot be undone."));
      if (!confirm(lines.join("\n"))) return;
      const r = await api.deleteDrawing(p.id, d.id);
      await ctx.reload();
      ctx.notify(`${d.filename} ${t("removed")}` +
                 (r.ners_removed?.length ? ` · ${r.ners_removed.length} ${t("NER(s) left the register")}` : "") +
                 (r.ties_released?.length ? ` · ${r.ties_released.length} ${t("tie(s) released")}` : ""));
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const uploadTeap = async (f: File) => {
    try {
      const r = await api.uploadTeap(p.id, f);
      setTeapId(r.id);
      setProfiles(r.profiles);
      setSheet(r.proposed.sheet);
      setHeaderRow(r.proposed.header_row);
      setMapping(r.proposed.mapping);
      setVenues(null);
      setVenueFilter("");
      setAllVenues(false);
      await ctx.reload();
      ctx.notify(`${t("Workbook read")}: ${r.profiles.length} ${t("sheet(s). Check the mapping, then load the venue list.")}`);
      void loadVenues(r.id, r.proposed.sheet, r.proposed.header_row, r.proposed.mapping);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const loadVenues = async (tid: number, sh: string, hr: number, map: any) => {
    try {
      const r = await api.previewVenues(p.id, tid, { sheet: sh, header_row: hr, mapping: map });
      setVenues(r.venues || []);
      if (r.suggested) setVenueFilter(r.suggested);
      else if ((r.venues || []).length === 1) setVenueFilter(r.venues[0].venue_code);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const doImport = async () => {
    if (teapId == null) return;
    try {
      await teapJob.start(
        () => api.importTeap(p.id, teapId, {
          sheet, header_row: headerRow, mapping,
          venue_filter: venueFilter || null,
          allow_all_venues: allVenues,
          save_as_template: templateName.trim() || null,
        }),
        async (j) => {
          await ctx.reload();
          if (j.state === "done") {
            const r = j.result || {};
            ctx.notify(`${r.rows} ${t("rows imported into")} ${r.spaces} ${t("spaces")}, ` +
                       `${r.total_ports} ${t("ports")}${r.venue_filter ? ` (${t("venue")} ${r.venue_filter})` : ""}` +
                       (r.decisions_carried ? ` · ${r.decisions_carried} ${t("earlier decision(s) carried across")}` : "") + ".");
            ctx.go("scale");
          } else if (j.state === "error") ctx.notify(j.error, "err");
        },
      );
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const multiVenue = (venues?.length || 0) > 1;
  const blocked = multiVenue && !venueFilter && !allVenues;

  return (
    <>
      <div className="card">
        <h2>{t("1 · Drawings (PDF)")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("Choose one book or several at once (Ctrl or Shift in the file dialog). They are read one after the other. The same file twice, or a book whose name is already in the project, is refused — remove the old one first if it is a new revision.")}
        </p>
        <input type="file" accept="application/pdf" multiple
               disabled={drawJob.busy}
               onChange={(e) => {
                 const files = Array.from(e.target.files || []);
                 e.target.value = "";
                 if (files.length) void uploadDrawings(files);
               }} />
        <div style={{ marginTop: 10 }}>
          <JobBar job={drawJob.job} onCancel={drawJob.cancel} onDismiss={drawJob.clear} />
        </div>
        {queue.length > 1 && (
          <ul className="small" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
            {queue.map((q, i) => (
              <li key={i} style={{ color: q.state === "refused" ? "var(--bad)" : q.state === "imported" ? "var(--ok)" : undefined }}>
                {q.name} — {t(q.state)}{q.note ? ` · ${q.note}` : ""}
              </li>
            ))}
          </ul>
        )}
        <table style={{ marginTop: 10 }}>
          <thead><tr><sf.Th k="filename">{t("File")}</sf.Th><sf.Th k="page_count">{t("Pages")}</sf.Th><sf.Th k="spaces" get={(d: any) => d.summary?.spaces}>{t("Spaces")}</sf.Th><sf.Th k="markers" get={(d: any) => d.summary?.elements}>{t("Markers")}</sf.Th><sf.Th k="needs_ocr" get={(d: any) => d.summary?.needs_ocr_pages?.length || 0}>{t("OCR needed")}</sf.Th><th /></tr></thead>
          <tbody>
            {sf.apply(p.drawings).map((d: any) => (
              <tr key={d.id}>
                <td>
                  {d.filename}
                  {/* A copy imported before 4.6.0 refused it. */}
                  {d.duplicate_of?.length > 0 && (
                    <div className="small" style={{ color: "var(--warn)" }}>
                      {t("same file as")} {d.duplicate_of.join(", ")} — {t("remove one of them")}
                    </div>
                  )}
                </td>
                <td>{d.page_count}</td>
                <td>{d.summary?.spaces ?? "—"}</td>
                <td>{d.summary?.elements ?? "—"}</td>
                <td>{d.summary?.needs_ocr_pages?.length ? d.summary.needs_ocr_pages.join(", ") : "none"}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="small danger" disabled={drawJob.busy}
                          title={t("Take this book out of the project, with its rooms and what is drawn on it")}
                          onClick={() => void removeDrawing(d)}>{t("Remove")}</button>
                </td>
              </tr>
            ))}
            {p.drawings.length === 0 && <tr><td colSpan={6} className="muted">{t("No drawing yet.")}</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>{t("2 · TEAP (XLSX / XLSM / CSV)")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("Macros are never executed. Formulas are read as their cached values.")}
        </p>
        <input type="file" accept=".xlsx,.xlsm,.csv"
               onChange={(e) => e.target.files?.[0] && uploadTeap(e.target.files[0])} />

        {profiles.length > 0 && (
          <>
            <h3>{t("Sheet and header row")}</h3>
            <div className="row">
              <div style={{ flex: 2 }}>
                <label>{t("Sheet")}</label>
                <select value={sheet} onChange={(e) => {
                  const sv = e.target.value;
                  setSheet(sv);
                  const pr = profiles.find((x) => x.sheet === sv);
                  if (pr) {
                    setHeaderRow(pr.header_row);
                    setMapping(pr.proposed_mapping);
                    if (teapId != null) void loadVenues(teapId, sv, pr.header_row, pr.proposed_mapping);
                  }
                }}>
                  {profiles.map((x) => (
                    <option key={x.sheet} value={x.sheet}>
                      {x.sheet} — {x.data_rows < 0 ? "?" : x.data_rows} rows (header row {x.header_row})
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label>{t("Header row")}</label>
                <input type="number" min={1} value={headerRow}
                       onChange={(e) => setHeaderRow(Number(e.target.value))} />
              </div>
              <button onClick={() => teapId != null && loadVenues(teapId, sheet, headerRow, mapping)}>
                {t("Reload venue list")}
              </button>
            </div>
            {templates.length > 0 && (
              <div className="row" style={{ marginTop: 6 }}>
                <div style={{ flex: 2 }}>
                  <label>{t("Apply a saved mapping template")}</label>
                  <select value="" onChange={(e) => {
                    const tpl = templates.find((x) => String(x.id) === e.target.value);
                    if (!tpl) return;
                    // The template carries the column names; only those the
                    // sheet actually has are applied, and the rest are said.
                    const headers = new Set<string>((profile?.headers || []).filter((h: string) => h));
                    const next: Record<string, string | null> = { ...mapping };
                    const missing: string[] = [];
                    for (const [field, col] of Object.entries(tpl.mapping || {})) {
                      if (!col) continue;
                      if (headers.has(col as string)) next[field] = col as string;
                      else missing.push(`${field} → ${col}`);
                    }
                    setMapping(next);
                    if (tpl.header_row) setHeaderRow(tpl.header_row);
                    ctx.notify(`${t("Template applied")}: ${tpl.name}` +
                      (missing.length ? ` — ${t("columns not in this sheet, left as they were")}: ${missing.join(", ")}` : ""));
                    if (teapId != null) void loadVenues(teapId, sheet, tpl.header_row || headerRow, next);
                  }}>
                    <option value="">{t("— choose a template —")}</option>
                    {templates.map((x) => (
                      <option key={x.id} value={x.id}>{x.name}{x.sheet_hint ? ` (${x.sheet_hint})` : ""}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            <h3>{t("Venue")}</h3>
            {venues === null && <p className="muted small">{t("Reading the venue column…")}</p>}
            {venues !== null && venues.length === 0 && (
              <p className="muted small">
                {t("No venue column is mapped, so the whole sheet will be imported.")}
              </p>
            )}
            {venues !== null && venues.length > 0 && (
              <>
                {multiVenue && (
                  <div className="banner" style={{ marginBottom: 10 }}>
                    {t("This sheet is a master allocation plan")}: <strong>{venues.length} {t("venues")}</strong>,
                    {" "}{totalRows.toLocaleString()} {t("rows")}. {t("Importing all of them against one venue's drawings compares rooms in one venue with equipment rooms in another, and makes the placement model enormous. Pick the venue this project covers.")}
                  </div>
                )}
                <div className="row">
                  <div style={{ flex: 2 }}>
                    <label>{t("Venue filter")}{p.venue_code ? ` (${t("project venue")}: ${p.venue_code})` : ""}</label>
                    <select value={venueFilter} disabled={allVenues}
                            onChange={(e) => setVenueFilter(e.target.value)}>
                      <option value="">{t("— none selected —")}</option>
                      {venues.map((v) => (
                        <option key={`${v.venue_code}|${v.venue_name}`} value={v.venue_code}>
                          {v.venue_code} · {v.venue_name} — {v.rows.toLocaleString()} rows
                        </option>
                      ))}
                    </select>
                  </div>
                  <label style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                    <input type="checkbox" checked={allVenues} style={{ width: "auto" }}
                           onChange={(e) => setAllVenues(e.target.checked)} />
                    {t("import every venue")}
                  </label>
                </div>
                {selected && (
                  <p className="small" style={{ color: "var(--ok)" }}>
                    {t("Will import")} {selected.rows.toLocaleString()} {t("of")} {totalRows.toLocaleString()} {t("rows")}.
                  </p>
                )}
                {allVenues && (
                  <p className="small" style={{ color: "var(--warn)" }}>
                    {t("All")} {totalRows.toLocaleString()} {t("rows will be imported. Only do this if the project really does cover every venue.")}
                  </p>
                )}
              </>
            )}

            <h3>{t("Column mapping")}</h3>
            <div className="grid c3">
              {CANONICAL_FIELDS.map((f) => (
                <div key={f}>
                  <label>{f.replace(/_/g, " ")}</label>
                  <select value={mapping[f] || ""}
                          onChange={(e) => setMapping({ ...mapping, [f]: e.target.value || null })}>
                    <option value="">{t("— not mapped —")}</option>
                    {(profile?.headers || []).filter((h: string) => h).map((h: string) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>

            <div className="row" style={{ marginTop: 12 }}>
              <div style={{ flex: 2 }}>
                <label>{t("Save this mapping as a reusable template (optional)")}</label>
                <input value={templateName} onChange={(e) => setTemplateName(e.target.value)}
                       placeholder="TEAP v1" />
              </div>
              <button className="primary" onClick={doImport}
                      disabled={!mapping.space_name || blocked || teapJob.busy}>
                {t("Import TEAP")}
              </button>
            </div>
            {!mapping.space_name && (
              <p className="small" style={{ color: "var(--warn)" }}>
                {t("“space name” must be mapped — it is the key the drawing match is built on.")}
              </p>
            )}
            {blocked && (
              <p className="small" style={{ color: "var(--warn)" }}>
                {t("Pick a venue, or tick “import every venue” to confirm you mean all of them.")}
              </p>
            )}
            <div style={{ marginTop: 10 }}>
              <JobBar job={teapJob.job} onCancel={teapJob.cancel} onDismiss={teapJob.clear} />
            </div>
          </>
        )}
      </div>

      {settings && (
        <div className="card">
          <h2>{t("3 · Project rules")}</h2>
          <div className="grid c4">
            <div>
              <label>{t("General limit (m)")}</label>
              <input type="number" value={settings.general_limit_m}
                     onChange={(e) => setSettings({ ...settings, general_limit_m: Number(e.target.value) })} />
            </div>
            <div>
              <label>{t("Photographer limit (m)")}</label>
              <input type="number" value={settings.photographer_limit_m}
                     onChange={(e) => setSettings({ ...settings, photographer_limit_m: Number(e.target.value) })} />
            </div>
            <div>
              <label>{t("Near-limit threshold (0–1)")}</label>
              <input type="number" step="0.05" min="0.1" max="1" value={settings.near_limit_ratio}
                     onChange={(e) => setSettings({ ...settings, near_limit_ratio: Number(e.target.value) })} />
            </div>
            <div>
              <label>{t("Routing slack factor (≥ 1)")}</label>
              <input type="number" step="0.05" min="1" value={settings.routing_slack_factor}
                     onChange={(e) => setSettings({ ...settings, routing_slack_factor: Number(e.target.value) })} />
            </div>
            <div>
              <label>{t("Display units")}</label>
              <select value={settings.display_units}
                      onChange={(e) => setSettings({ ...settings, display_units: e.target.value })}>
                <option value="m">{t("metres")}</option>
                <option value="ft">{t("feet")}</option>
                <option value="both">{t("both")}</option>
              </select>
            </div>
            {/* Fibre runs from the TER per NER (2.8.0): what the workbook
                multiplies out on the NERs sheet and totals on the Summary.
                A count of runs, never a length — nothing measures a fibre
                route here. */}
            <div>
              <label>{t("Fibre runs to the TER — per critical NER")}</label>
              <input type="number" min="0" max="16" value={settings.fibre_runs_critical ?? 2}
                     title={t("Counted on the NERs and ports sheet and totalled on the Summary sheet. A count of runs, not a length.")}
                     onChange={(e) => setSettings({ ...settings, fibre_runs_critical: Number(e.target.value) })} />
            </div>
            <div>
              <label>{t("Fibre runs to the TER — per non-critical NER")}</label>
              <input type="number" min="0" max="16" value={settings.fibre_runs_noncritical ?? 1}
                     title={t("Counted on the NERs and ports sheet and totalled on the Summary sheet. A count of runs, not a length.")}
                     onChange={(e) => setSettings({ ...settings, fibre_runs_noncritical: Number(e.target.value) })} />
            </div>
          </div>
          <p className="small muted" style={{ marginBottom: 8 }}>
            {t("The 90 m rule in ANSI/TIA-568 is the permanent link — real cable length, not a straight line on a plan. A slack factor of 1.0 reports the raw geometry; raise it (1.25–1.40 is typical for a bowl) before treating any result as a design decision.")}
          </p>
          <button className="primary" onClick={async () => {
            // A value the server refuses (a blank limit, slack below 1…) used
            // to fail with no message at all (2.12.1).
            try {
              await api.updateSettings(p.id, settings);
              await ctx.reload();
              ctx.notify(t("Project rules saved."));
            } catch (e: any) { ctx.notify(`${t("Rules not saved")}: ${e.message}`, "err"); }
          }}>{t("Save rules")}</button>
        </div>
      )}
    </>
  );
}


export function ScalePanel({ ctx }: { ctx: Ctx }) {
  const ss = useSort<any>();
  const p = ctx.project;
  const [denoms, setDenoms] = useState<Record<number, string>>({});
  //: The key-plan ticks (2.14.0): what the person ticked since the last
  //  Apply, page → answer. Ticked by default from the title block.
  const [ticks, setTicks] = useState<Record<number, boolean>>({});
  const [applying, setApplying] = useState(false);
  const placeJob = useJob();
  // The double-click guards of the two placing steps (4.0.0, 2.19.0) — refs
  // read synchronously, because a double click fires two clicks before React
  // re-renders the disabled button. Declared above the early return (4.6.1):
  // below it the screen called three hooks more once a project was open.
  const placingNersRef = useRef(false);
  const [placingAps, setPlacingAps] = useState(false);
  const placingApsRef = useRef(false);
  // Wi-Fi points that sit on top of each other (4.8.0), counted for the
  // Spread button. Above the early return, like the hooks before it.
  const { data: stacked, reload: reloadStacked } = useAsync(
    () => (p ? api.stackedWifi(p.id) : Promise.resolve(null)), [p?.id], null as any);
  const [spreading, setSpreading] = useState(false);
  useEffect(() => { setTicks({}); }, [p?.id]);
  if (!p) return null;

  const keyOf = (pg: any) => (pg.number in ticks ? ticks[pg.number] : !!pg.key_plan);
  const dirty = p.pages.filter((pg: any) => pg.number in ticks && ticks[pg.number] !== !!pg.key_plan);
  const applyKeyPlans = async () => {
    if (!dirty.length) return;
    setApplying(true);
    try {
      const body: Record<number, boolean> = {};
      for (const pg of dirty) body[pg.number] = ticks[pg.number];
      const r = await api.setKeyPlans(p.id, body);
      await ctx.reload();
      setTicks({});
      const parts = [`${r.changed.length} ${t("page(s) changed")}.`];
      if (r.spaces_removed) parts.push(`${r.spaces_removed} ${t("space(s) taken off the key plans")}.`);
      if (r.spaces_read) parts.push(`${r.spaces_read} ${t("space(s) read off the pages that are detail sheets again")}.`);
      if (r.released_decisions) parts.push(`${r.released_decisions} ${t("TEAP tie(s) to a room on a key plan released.")}`);
      if (r.matching) parts.push(t("Matching run again."));
      ctx.notify(parts.join(" "));
    } catch (e: any) { ctx.notify(e.message, "err"); }
    finally { setApplying(false); }
  };

  const keyCount = p.pages.filter((pg: any) => keyOf(pg)).length;
  const detailUnconfirmed = p.pages.filter((pg: any) => !keyOf(pg) && !pg.scale_confirmed).length;
  const nerPass = (p.drawings || []).map((d: any) => d.summary?.ner_pass).filter(Boolean);
  // A double click fires two clicks before React re-renders the disabled
  // button, so the guard is a ref read synchronously (4.0.0); the server
  // refuses a second run too.
  const placeNers = async () => {
    if (placingNersRef.current || placeJob.busy) return;
    placingNersRef.current = true;
    try { await placeNersOnce(); } finally { placingNersRef.current = false; }
  };
  const placeNersOnce = async () => {
    const warn = [];
    if (dirty.length) warn.push(t("you have key-plan ticks not applied yet"));
    if (detailUnconfirmed) warn.push(`${detailUnconfirmed} ${t("detail page(s) have no confirmed scale — a NER near an existing one is told apart at 12 m, which needs the scale")}`);
    const q = (warn.length ? `${t("Before placing")}: ${warn.join("; ")}.\n\n` : "")
      + t("Place the NERs the drawings state? The team's annotations first, then the TEC.010 / TEC.020 (or TEC.003.01 / .02) rooms, then the \"Network Equipment Rack\" labels, then the NER block symbols — never on a key plan, never where a NER already is. Every one is named in sequence (NERc_01.1 …, NER_20.1 …) for you to rename. Running it again only adds what is still missing.");
    if (!confirm(q)) return;
    try {
      await placeJob.start(() => api.placeNers(p.id), async (j) => {
        if (j.state === "error") { ctx.notify(j.error, "err"); return; }
        if (j.state !== "done") return;
        await ctx.reload();
        const r = j.result || {};
        ctx.notify(`${r.created ?? 0} ${t("NER(s) placed")} (${r.annotations ?? 0} ${t("from the team's annotations")}, ${r.rooms_found ?? 0} ${t("NER room(s) read")}, ${r.same_as_marker ?? 0} ${t("already had a NER beside them")}). ${t("Check them in the Drawing viewer and on the NERs screen; delete any duplicate there.")}`);
      });
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  // The AP placing step (2.19.0). Marcelo, 14 Oct 2026: "desenhar nos VDB o
  // AP nos espaços que já sabemos que tem wifi, assim como fazemos com as
  // NERs … só para facilitar os espaços que já conhecemos".
  const placeAps = async () => {
    if (placingApsRef.current) return;
    placingApsRef.current = true;
    try { await placeApsOnce(); } finally { placingApsRef.current = false; }
  };
  const placeApsOnce = async () => {
    const q = t("Mark the spaces the TEAP says have wireless? One Wi-Fi point for every TEAP space with a DWISA line whose room is on a drawing, beside the room's label and tied to that space. It marks the space, it is not an access point count, and it adds no port — the DWISA line stays the space's wireless port. Never on a key plan; spaces with no room on the drawing get nothing and stay pending. Running it again only adds what is missing and takes back extra points it placed.");
    if (!confirm(q)) return;
    setPlacingAps(true);
    try {
      const r = await api.placeAccessPoints(p.id);
      await ctx.reload();
      const parts = [`${r.placed ?? 0} ${t("Wi-Fi point(s) placed in")} ${r.spaces_placed ?? 0} ${t("space(s)")}`];
      if (r.already_had_points) parts.push(`${r.already_had_points} ${t("space(s) already had their Wi-Fi point")}`);
      if (r.removed_extra) parts.push(`${r.removed_extra} ${t("extra Wi-Fi point(s) taken back (one per space)")}`);
      if (r.extra_by_hand) parts.push(`${r.extra_by_hand} ${t("Wi-Fi point(s) drawn by hand beyond one per space — kept, check them")}`);
      if (r.no_room) parts.push(`${r.no_room} ${t("space(s) request wireless but have no room on the drawing — left pending")}${r.unplaced_spaces?.length ? ` (${r.unplaced_spaces.slice(0, 6).join(", ")}${r.unplaced_spaces.length > 6 ? ", …" : ""})` : ""}`);
      if (r.on_key_plan) parts.push(`${r.on_key_plan} ${t("space(s) sit on a key plan")}`);
      if (r.deleted_by_you) parts.push(`${r.deleted_by_you} ${t("space(s) whose Wi-Fi point you deleted — left without one")}`);
      ctx.notify(`${parts.join("; ")}. ${t("Check them in the Drawing viewer; drag a point if it sits on something you need to read.")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
    finally { setPlacingAps(false); reloadStacked(); }
  };

  // Spread the Wi-Fi points that sit on top of each other (4.8.0).
  const spreadWifi = async () => {
    if (spreading || !stacked?.to_move) return;
    if (!confirm(`${t("Spread the Wi-Fi points that sit on top of each other?")} ` +
                 `${stacked.points} ${t("point(s) in")} ${stacked.stacks} ${t("stack(s)")}: ` +
                 t("the oldest point of each stack stays where it is and the others move beside it, in rows of four. Ties, the NER chosen and indoor/outdoor go with each point; every move is in the audit log."))) return;
    setSpreading(true);
    try {
      const r = await api.spreadWifi(p.id);
      await ctx.reload();
      ctx.notify(`${r.moved ?? 0} ${t("Wi-Fi point(s) moved out of")} ${r.stacks ?? 0} ${t("stack(s)")}. ${t("Run analysis to measure them from where they are now.")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
    finally { setSpreading(false); reloadStacked(); }
  };

  const apply = async (page: number, confirm: boolean) => {
    const raw = denoms[page];
    try {
      const body: any = { confirm };
      if (raw && /^[\d.]+$/.test(raw.trim())) body.denominator = Number(raw);
      else if (raw) body.text = raw;
      else {
        const pg = p.pages.find((x: any) => x.number === page);
        if (!pg?.metres_per_unit) { ctx.notify(t("Nothing to confirm on this page yet."), "err"); return; }
        body.denominator = (pg.metres_per_unit * 72) / 0.0254;
      }
      await api.setScale(p.id, page, body);
      await ctx.reload();
      ctx.notify(`${t("Page")} ${sheetNo(p, page)}: scale ${confirm ? "confirmed" : "set"}.`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  // Every page that holds a scale — detected, or typed in earlier — and is
  // not confirmed yet. That is what the one button confirms; a page with no
  // scale at all is skipped and named, because the only honest thing to do
  // with it is to keep blocking its results until somebody types the ratio.
  const confirmable = p.pages.filter((pg: any) => pg.metres_per_unit && !pg.scale_confirmed);
  const noScale = p.pages.filter((pg: any) => !pg.metres_per_unit);

  const confirmAll = async () => {
    if (!confirm(`${t("Confirm the scale on")} ${confirmable.length} ${t("page(s) at once?")}\n\n` +
                 t("Each page keeps the value shown in its Applied column. Pages with no scale are left alone."))) return;
    try {
      const r = await api.confirmAllScales(p.id);
      await ctx.reload();
      ctx.notify(`${r.confirmed.length} ${t("page(s) confirmed")}` +
                 (r.skipped_no_scale.length
                   ? ` · ${r.skipped_no_scale.length} ${t("page(s) have no scale to confirm")}: ${r.skipped_no_scale.join(", ")}`
                   : ""));
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  return (
    <>
    <div className="card">
      <h2>{t("Scale per page")}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {t("Detected scales are proposals only. Definitive coverage results stay blocked until each page is confirmed. Type a ratio or a scale text in the row to override what was detected.")}
        {" "}
        {t("The Key plan tick marks a page that only illustrates — a key enlarged plan, the drawing index, the venue information, the abbreviations: no space is read off it, it takes part in no TEAP × drawing crossing and no NER is placed on it. Ticked by default from the title block; change it and press Apply.")}
      </p>
      {dirty.length > 0 && (
        <div className="row" style={{ marginBottom: 8, alignItems: "center" }}>
          <button className="primary" disabled={applying} onClick={applyKeyPlans}>
            {t("Apply key-plan ticks")} ({dirty.length})
          </button>
          <button className="small" disabled={applying} onClick={() => setTicks({})}>{t("Undo ticks")}</button>
          <span className="small muted" style={{ marginBottom: 0 }}>
            {t("A page ticked loses its spaces and any TEAP tie to them; a page unticked gets its spaces read. The matching runs again.")}
          </span>
        </div>
      )}
      {/* One button for the whole book, beside the row buttons — not instead
          of them. A 75-page book was 75 identical clicks. */}
      <div className="row" style={{ marginBottom: 10, alignItems: "center" }}>
        <button className="primary" disabled={confirmable.length === 0} onClick={confirmAll}
                title={t("Confirms the detected (or typed) scale on every page that has one")}>
          {t("Confirm all pages")}{confirmable.length ? ` (${confirmable.length})` : ""}
        </button>
        <span className="small muted" style={{ marginBottom: 0 }}>
          {p.pages.filter((pg: any) => pg.scale_confirmed).length} {t("of")} {p.pages.length} {t("confirmed")}
          {noScale.length > 0 && (
            <> · <span style={{ color: "var(--warn)" }}>
              {noScale.length} {t("page(s) with no scale — type one in the row")}
            </span></>
          )}
        </span>
      </div>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <ss.Th k="page" get={(pg: any) => pg.number}>{t("Page")}</ss.Th><ss.Th k="key_plan" get={(pg: any) => keyOf(pg)}>{t("Key plan")}</ss.Th><ss.Th k="sheet_title" get={(pg: any) => `${pg.sheet_number || ""} ${pg.sheet_title || ""}`.trim()}>{t("Sheet / level")}</ss.Th><ss.Th k="scale_label" get={(pg: any) => (pg.candidates || []).map((c: any) => c.label).join(", ")}>{t("Detected")}</ss.Th><ss.Th k="metres_per_unit">{t("Applied")}</ss.Th>
              <ss.Th k="source" get={(pg: any) => pg.scale_source}>{t("Source")}</ss.Th><ss.Th k="status" get={(pg: any) => pg.scale_confirmed}>{t("Status")}</ss.Th><th>{t("Set (ratio or text)")}</th><th />
            </tr>
          </thead>
          <tbody>
            {ss.apply(p.pages).map((pg: any) => (
              <tr key={pg.number} className={keyOf(pg) ? "row-key" : ""}>
                <td>{sheetNo(p, pg.number)}{pg.needs_ocr && <div className="pill" style={{ color: "var(--warn)" }}>{t("OCR needed")}</div>}</td>
                <td>
                  <label className={`small key-plan-toggle ${keyOf(pg) ? "on" : ""}`}
                         title={t("A key plan only illustrates: its rooms are not drawn or listed and take part in no TEAP × drawing crossing, and no NER is created from it. Read off the drawing title in the title block; untick it if the title block was read wrong.")}>
                    <input type="checkbox" style={{ width: "auto" }} checked={keyOf(pg)}
                           onChange={(e) => setTicks({ ...ticks, [pg.number]: e.target.checked })} />
                    {keyOf(pg) ? "KEY" : ""}{pg.number in ticks && ticks[pg.number] !== !!pg.key_plan ? " *" : ""}
                  </label>
                </td>
                <td className="small">{pg.sheet_number ? <span className="mono">{pg.sheet_number}</span> : null}{pg.sheet_number && pg.sheet_title ? " · " : ""}{pg.sheet_title || (pg.sheet_number ? "" : "—")}{pg.level ? ` · ${pg.level}` : ""}</td>
                <td className="small mono">
                  {(pg.candidates || []).map((c: any) => c.label).join(", ") || "—"}
                </td>
                <td className="mono">{pg.scale_label || "—"}</td>
                <td className="small muted">{pg.scale_source || "—"}</td>
                <td>
                  <span className="pill" style={{ color: pg.scale_confirmed ? "var(--ok)" : "var(--warn)" }}>
                    {pg.scale_confirmed ? "confirmed" : "not confirmed"}
                  </span>
                </td>
                <td style={{ width: 170 }}>
                  <input placeholder={`200  or  1/8" = 1'-0"`} value={denoms[pg.number] || ""}
                         onChange={(e) => setDenoms({ ...denoms, [pg.number]: e.target.value })} />
                </td>
                {/* One button, not two.
                    "Set" wrote the scale without confirming it and "Confirm"
                    wrote the same value and confirmed it, so the only thing
                    "Set" could produce was a page that had been given a scale
                    and still blocked the coverage results — a state nobody
                    chooses on purpose. Confirm applies whatever is in the field
                    (or the detected value, when the field is empty) and marks
                    the page confirmed, which is what both buttons were being
                    used for. */}
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="small primary" onClick={() => apply(pg.number, true)}>{t("Confirm")}</button>
                </td>
              </tr>
            ))}
            {p.pages.length === 0 && <tr><td colSpan={9} className="muted">{t("Import a drawing first.")}</td></tr>}
          </tbody>
        </table>
      </div>
    </div>

    {/* The NER placing step (2.14.0). Marcelo, 29 Sep 2026: "seria melhor a
        ferramenta só posicionar NER depois de eu marcar e desmarcar páginas
        key e confirmar scale". */}
    <div className="card">
      <h2>{t("NERs from the drawing")}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {t("After the key plans are ticked and the scales confirmed, place the NERs the drawings state: the team's own annotations first, then the coded rooms — TEC.010 (critical) / TEC.020 (non-critical), or TEC.003.01 / .02 on older books — then the \"Network Equipment Rack\" labels (with or without the \"(NER)\", with their arrows when there are any), then the NER block symbols (the small square with NER inside, read by its shape; non-critical, criticality to confirm). Never on a key plan; a candidate within 12 m of a NER already on the sheet is taken as that NER. Every NER is named in sequence — NERc_01.1, NERc_02.1 … / NER_20.1, NER_21.1 … — with what the sheet printed kept as \"printed as\"; rename them on the NERs screen. Running it again only adds what is still missing; a duplicate is yours to delete in the Drawing viewer.")}
      </p>
      <div className="row" style={{ alignItems: "center" }}>
        <button className="primary" disabled={placeJob.busy || !(p.drawings || []).length} onClick={placeNers}>
          {t("Place NERs from the drawing")}
        </button>
        <span className="small muted" style={{ marginBottom: 0 }}>
          {keyCount} {t("key plan(s)")} · {detailUnconfirmed} {t("detail page(s) with no confirmed scale")}
          {nerPass.length > 0 && (
            <> · {t("last placed")} {nerPass.map((x: any) => `${x.at?.replace("T", " ") || "?"} (${x.created} ${t("created")})`).join("; ")}</>
          )}
        </span>
      </div>
      <div style={{ marginTop: 10 }}>
        <JobBar job={placeJob.job} onCancel={placeJob.cancel} onDismiss={placeJob.clear} />
      </div>
    </div>

    {/* The AP placing step (2.19.0). */}
    <div className="card">
      <h2>{t("Wi-Fi from the TEAP")}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {t("The spaces the TEAP says have wireless (a DWISA line), marked with one Wi-Fi point each where their rooms are, beside the room's label, tied to that space. A Wi-Fi point says the space has wireless; it is not an access point count — the quantity stays on the DWISA line and the number of APs comes from the wireless design. It adds no port: the DWISA line stays the space's wireless port, counted on the NER that serves the space. The distance to the NER is checked from where the point is drawn. Never on a key plan; a space with no room on the drawing gets nothing and stays pending — tie its room first on TEAP × drawing. Running it again never duplicates: it adds only what is missing and takes back extra points it placed itself; points you drew are never removed.")}
      </p>
      <div className="row" style={{ alignItems: "center" }}>
        <button className="primary" disabled={placingAps || !(p.drawings || []).length} onClick={placeAps}>
          {placingAps ? t("Placing…") : t("Place Wi-Fi from the TEAP")}
        </button>
        {/* Points placed before 4.8.0 for several TEAP lines of one room
            sit on top of each other; this puts them side by side. */}
        <button disabled={spreading || !stacked?.to_move} onClick={spreadWifi}
                title={t("Move the Wi-Fi points that sit on top of each other into a grid beside the oldest one")}>
          {spreading ? t("Spreading…") : `${t("Spread stacked Wi-Fi points")}${stacked?.to_move ? ` (${stacked.to_move})` : ""}`}
        </button>
        <span className="small muted" style={{ marginBottom: 0 }}>
          {stacked?.to_move
            ? `${stacked.points} ${t("point(s) sit on top of another one, in")} ${stacked.stacks} ${t("stack(s)")}`
            : t("no Wi-Fi point sits on top of another one")}
        </span>
      </div>
      <p className="muted small" style={{ marginBottom: 0 }}>
        {t("A Wi-Fi point you delete stays deleted: running this step again leaves its space without one. Draw a point with +Wi-Fi for the space, or tie one to it, to bring it back.")}
      </p>
    </div>
    </>
  );
}

// ---------------------------------------------------------------------------

/* ``ElementsPanel`` — the "On the drawing" tab of the NERs screen — stood
   here until 3 Sep 2026. Its list is now the NERs screen itself
   (``NerRegister.tsx``); its per-marker rename / kind / confirm / lock /
   delete controls moved to the Drawing viewer's inspector, where a TER, an
   IDF, a COW or a DIVA node is managed. */

// ---------------------------------------------------------------------------

/**
 * TEAP × drawing — one screen for the whole crossing.
 *
 * One act, from the desk: *this TEAP line means that room on the sheet*.
 * Choose the room, confirm it, and the decision is written on the TEAP line
 * itself — which is why re-running the matching never undoes it.
 *
 * Two things went on 3 Sep 2026, both at Marcelo's request.
 *
 * **Remember for every venue.** A tick that turned the choice into a rule
 * applying to every project on this installation. *"Prefiro fazer projeto por
 * projeto individualmente. Nem toda venue é igual."* A pairing that is right
 * at one venue is a guess at the next venue, and a rule reaching projects
 * you are not looking at is exactly the kind of quiet error this tool exists
 * to avoid. (The alias table and its endpoints still exist on the server;
 * nothing on this screen writes to them any more.)
 *
 * **Confirm all base_code / Confirm all fuzzy_name.** One click signing off
 * twenty rooms because the matcher used the same method for them. *"Melhor
 * fazer isso manual olhando um por um, pois é arriscado assumir que um nome
 * próximo seja o local correto."* A base-code match is precisely the row that
 * needs a person: `PRS.006.02` against `PRS.006` may be the same room or the
 * one next door.
 *
 * The worklist is ordered by the port demand riding on each row, because a
 * space carrying 110 ports deserves an hour of attention and one carrying a
 * single port does not — and listing them in arbitrary order pretends
 * otherwise.
 */
/**
 * The tiles are the filter — three of them (2.12.0).
 *
 * Every figure on the TEAP × drawing screen is a button: click one and the
 * worklist shows exactly those rows; click it again and the list is whole.
 *
 * There were up to nine until 2.11.0 (matched, confirmed by you, confirmed by
 * the matcher, not yet confirmed, no room found, not on this drawing, your
 * decisions, no ports…). Marcelo, 25 Sep 2026: *"acho que aqui só precisamos
 * de 3 botões … qualquer outro botão aqui é desnecessário e tá poluindo e
 * complicando demais a análise."* What matters is the TEAP line and whether
 * it has a room:
 *
 * * ``TEAP spaces`` — every line of the study;
 * * ``matched`` — a room is tied to it, whoever tied it (the matcher or you),
 *   confirmed or not — who confirmed is said on the row itself;
 * * ``no room found`` — no room tied: the matcher found none, or you chose
 *   "— none —". The same answer either way, so one pile.
 *
 * ``matched`` + ``no room found`` = ``TEAP spaces``, always. TEAP spaces with
 * no ports are outside the study and outside the sum, as before.
 */
type TileKey = "all" | "matched" | "no_room";

const inStudy = (m: any) => m.in_scope !== false;
const hasRoom = (m: any) => !!m.drawing_space_id && !m.rejected;

/** A row nobody needs to look at again: confirmed (by the matcher or by you)
 *  with its room, or set to — none — by you. */
const isSettled = (m: any) => (!!m.confirmed && hasRoom(m)) || m.locked === "rejected";

const TILE_ROWS: [TileKey, string, (m: any) => boolean][] = [
  ["all", "TEAP spaces", inStudy],
  ["matched", "matched", (m) => inStudy(m) && hasRoom(m)],
  ["no_room", "no room found", (m) => inStudy(m) && !hasRoom(m)],
];

/**
 * The *Drawing space* select of one TEAP × drawing row (4.8.0).
 *
 * Every row used to hold every room of the drawing — about a hundred rows
 * times nine hundred rooms on the larger venues, some 100,000 ``<option>``s
 * built and laid out at once each time the list came back, and the browser
 * froze for a moment after *Run matching* (Marcelo, 27 Oct 2026: "o navegador
 * dá uma travada e depois volta"). Closed, a row now holds only the room it
 * shows; the whole list is built when the pointer reaches the select or the
 * keyboard focuses it, and let go again when it leaves.
 */
function SpaceSelect({ value, current, currentLabel, noneLabel, options, project, onChoose }: {
  value: number | null; current?: any; currentLabel?: string; noneLabel: string;
  options: { key: number; label: string }[]; project: any;
  onChoose: (id: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSelectElement>(null);
  const shown = current ? spaceLabel(current, project) : (currentLabel || "");
  return (
    <select ref={ref} value={value ?? ""} style={{ flex: 1, minWidth: 0 }}
            onMouseEnter={() => setOpen(true)} onFocus={() => setOpen(true)}
            onMouseDown={() => setOpen(true)} onTouchStart={() => setOpen(true)}
            onMouseLeave={() => { if (document.activeElement !== ref.current) setOpen(false); }}
            onBlur={() => setOpen(false)}
            onChange={(e) => { onChoose(e.target.value ? Number(e.target.value) : null); }}>
      <option value="">{noneLabel}</option>
      {open
        ? options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)
        : (value ? <option value={value}>{shown}</option> : null)}
    </select>
  );
}

export function MatchingPanel({ ctx }: { ctx: Ctx }) {
  const sw = useSort<any>();
  const p = ctx.project;
  //: Which tile is pressed. ``all`` is the whole study; ``zero`` is the one
  //  view that shows what is outside it.
  const [tile, setTile] = useState<TileKey>("all");
  const matchJob = useJob();
  // Every row, every time: the tiles are counted from this list and the
  // filter is applied here, so the figures and the table cannot disagree.
  const { data: matches, reload: reloadMatches } = useAsync(
    () => (p ? api.matches(p.id, false, true) : Promise.resolve([])),
    [p?.id], [] as any[]);
  const { data: spaces, reload: reloadSpaces } = useAsync(
    () => (p ? api.drawingSpaces(p.id) : Promise.resolve([])), [p?.id], [] as any[]);
  //: What a choice, a Confirm or an Undo changes is the rows (4.8.0): the
  //  drawing spaces do not change with them, and fetching and sorting the
  //  whole list again after every click was half of the stall Marcelo felt.
  //  Run matching reloads both.
  const reload = async () => { await reloadMatches(); };
  const reloadAll = async () => { await Promise.all([reloadMatches(), reloadSpaces()]); };
  //: One select per row, every drawing space in each — so the ordering is
  //  computed once for the table, not once per row. One list, alphabetical
  //  (2.14.0): it was split into "not tied yet" and "already tied", and that
  //  made a room hard to find when two TEAP lines rightly share it.
  //  Marcelo, 29 Sep 2026: "already tied ou não isso não importa, deixa
  //  tudo em ordem alfabética".
  const spaceOptions = useMemo(() => sortedSpaces(spaces, p), [spaces, p]);
  const spaceById = useMemo(() => new Map((spaces || []).map((x: any) => [x.id, x])), [spaces]);

  // One figure per tile, from the rows themselves.
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const [k, , pred] of TILE_ROWS) c[k] = matches.filter(pred).length;
    return c;
  }, [matches]);
  // Largest demand first. This is the ordering the old alias worklist used and
  // the reason it existed; the queue inherits it rather than repeating it.
  //: Rows that still need a look come first (4.4.0) — a room not chosen, or
  //  chosen and not confirmed — and then the rows already settled: confirmed
  //  by the matcher (an exact match), by you, or set to — none — by you.
  //  Marcelo, 22 Oct 2026: "eu deveria gastar meu tempo só olhando para
  //  aqueles que realmente precisam de atenção".
  const rows = useMemo(() => {
    const pred = TILE_ROWS.find(([k]) => k === tile)![2];
    return matches.filter(pred).sort((a, b) =>
      Number(isSettled(a)) - Number(isSettled(b)) || (b.ports || 0) - (a.ports || 0));
  }, [matches, tile]);
  const unresolved = rows.filter((m) => !m.drawing_space_id);
  // A row set to "— none —" is a decision already taken: it is not waiting.
  const pendingPorts = rows
    .filter((m) => !m.confirmed && !m.rejected && m.locked !== "rejected")
    .reduce((a, m) => a + (m.ports || 0), 0);

  if (!p) return null;

  /**
   * Record the choice.
   *
   * The room is saved the moment it is picked — on the TEAP space, not only on
   * this worklist row — so it survives every later matching run without the
   * user having to confirm anything first.
   */
  const choose = async (m: any, drawingSpaceId: number | null) => {
    try {
      // "— none —" is an answer, not an erase (2.10.0): it records that this
      // TEAP space has no room on this drawing, and the answer is kept on the
      // TEAP line like any other, so a later run does not propose a room
      // again. Undo takes it back.
      if (!drawingSpaceId && m.locked === "rejected") return;
      await api.decideMatch(p.id, m.id, drawingSpaceId
        ? { drawing_space_id: drawingSpaceId, justification: "room chosen" }
        : { rejected: true, justification: "no room on this drawing — chosen by you" });
      await reload();
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /**
   * Confirm the row, re-stating the room it is confirming.
   *
   * Sending the room matters: Confirm used to send only ``{confirmed: true}``,
   * so it could sign off a row without ever recording *what* was signed off.
   * The server treats a room it already holds as a re-affirmation, not a new
   * hand pick, so an automatic match keeps the method that found it.
   */
  const confirmRow = async (m: any) => {
    try {
      await api.decideMatch(p.id, m.id, {
        confirmed: true,
        drawing_space_id: m.drawing_space_id || undefined,
        justification: "reviewed",
      });
      await reload();
      ctx.notify(`${m.teap_code || m.teap_name} ${t("confirmed")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /**
   * Take the decision back. The row returns to the matcher's own answer —
   * the room it proposed, unconfirmed unless it was an unambiguous exact
   * code — so a wrong confirmation or a wrong room is one click to reverse.
   */
  const undoRow = async (m: any) => {
    try {
      const r = await api.undoMatch(p.id, m.id, "undone from the worklist");
      await reload();
      const name = m.teap_code || m.teap_name;
      if (r.note) ctx.notify(`${name}: ${t(r.note)}`);
      else if (r.drawing_space_id) {
        ctx.notify(`${name} ${t("back to the matcher's answer")}: ${r.drawing_name}` +
                   (r.confirmed ? ` (${t("exact code, confirmed by the matcher")})` : ` (${t("not confirmed")})`));
      } else ctx.notify(`${name} ${t("back to the matcher's answer")}: ${t("no room found")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const tiles = TILE_ROWS;
  //: Matched rows nobody has signed off yet — said in a line, not a fourth
  //  button: the row's own Confirm is where it is settled.
  const awaitingConfirm = matches.filter((m) => inStudy(m) && hasRoom(m) && !m.confirmed).length;
  const zeroCount = matches.filter((m) => !inStudy(m)).length;
  const tileLabel = TILE_ROWS.find(([k]) => k === tile)![1];

  return (
    <>
      <div className="card">
        <h2>{t("TEAP × drawing matching")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("Order: exact space code → base code → exact name → normalised name → synonyms → text similarity → building/level context. Low-confidence and ambiguous results are never confirmed silently — each one is yours to check against the sheet.")}
        </p>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("The TEAP rules. The check runs from the TEAP to the drawing, never the other way round: a room on the drawing that no TEAP line asks for is not listed and not a finding. A TEAP line the matcher could not place is yours to tie by hand to any room on the drawing.")}
        </p>
        <div className="row">
          <button className="primary" disabled={matchJob.busy} onClick={async () => {
            try {
              await matchJob.start(() => api.runMatching(p.id), async (j) => {
                if (j.state === "error") { ctx.notify(j.error, "err"); return; }
                if (j.state !== "done") return;
                const r = j.result;
                await reloadAll();
                const kept = r.stats.decisions_kept || 0;
                const lost = r.stats.decisions_released_room_gone || 0;
                ctx.notify(
                  `${t("Matched")} ${r.stats.matched} ${t("of")} ${r.stats.teap_spaces} ${t("TEAP spaces")} ` +
                  `(${(r.stats.match_rate * 100).toFixed(0)}%); ${r.stats.needs_review} ${t("matched, not yet confirmed")}; ` +
                  `${r.stats.unmatched_teap} ${t("with no room found — choose one by hand")}.` +
                  (kept ? ` ${kept} ${t("earlier decision(s) kept")}.` : "") +
                  (lost ? ` ${lost} ${t("decision(s) released — the room is no longer on the drawing")}.` : ""));
              });
            } catch (e: any) { ctx.notify(e.message, "err"); }
          }}>{t("Run matching")}</button>
          <span className="muted small" style={{ marginBottom: 0 }}>
            {t("Re-running never clears a room you chose or confirmed. Those are stored on the TEAP line itself, not on this list.")}
          </span>
        </div>
        <div style={{ marginTop: 10 }}>
          <JobBar job={matchJob.job} onCancel={matchJob.cancel} onDismiss={matchJob.clear} />
        </div>
        {/* Every tile is a button and the pressed one is the filter on the
            worklist below. Counted from the rows themselves, so they are here
            before any run and always agree with the table. */}
        <div className="grid c3" style={{ marginTop: 12 }}>
          {tiles.map(([k, label]) => (
            <button type="button" className={`stat tile${tile === k ? " on" : ""}`} key={k}
                    aria-pressed={tile === k}
                    title={tile === k ? t("Click again to show every row") : t("Click to show only these rows")}
                    onClick={() => setTile(tile === k ? "all" : k)}>
              <div className="n">{String(counts[k] ?? 0)}</div>
              <div className="k">{t(label)}</div>
            </button>
          ))}
        </div>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {t("matched + no room found = TEAP spaces. Matched counts every line with a room, whether the matcher or you tied it; no room found counts every line without one, whether the matcher found none or you chose — none —. Each row says who decided.")}
          {awaitingConfirm > 0 && <> {awaitingConfirm} {t("matched line(s) still await your Confirm.")}</>}
          {zeroCount > 0 && <> {zeroCount} {t("TEAP space(s) with no ports are outside the study and not counted.")}</>}
        </p>
      </div>

      <div className="card">
        <h2>{t("Worklist — largest demand first")}</h2>
        {tile !== "all" && (
          <p className="small" style={{ marginTop: 0, color: "var(--accent)" }}>
            {t("Showing only")}: <strong>{t(tileLabel)}</strong> ({rows.length}).{" "}
            <button type="button" className="linkish" onClick={() => setTile("all")}>{t("show every row")}</button>
          </p>
        )}
        <p className="muted small" style={{ marginTop: 0 }}>
          {rows.length} {t("row(s)")}, {unresolved.length} {t("with no room chosen yet")},
          {" "}{pendingPorts.toFixed(0)} {t("ports still awaiting a decision")}.{" "}
          {t("The list is not restricted by name similarity: pick whichever room on the sheet is the right one, however differently it is named. A line with no room chosen stays on the list and is reported as an exception.")}
        </p>
        <div className="scroll">
          <table>
            <thead>
              {/* Six columns, and every one of them is part of the question
                  being asked: this TEAP line, that room on the sheet. Method,
                  Confidence and Reason went on 2 Sep; Remember on 3 Sep. The
                  matcher's evidence is still on every row of the Matching
                  sheet in the workbook and in the audit log. */}
              <tr><sw.Th k="ports">{t("Ports")}</sw.Th><sw.Th k="teap_code">{t("TEAP code")}</sw.Th>
                  <sw.Th k="teap_name">{t("TEAP name")}</sw.Th>
                  <sw.Th k="drawing_name">{t("Drawing space")}</sw.Th><sw.Th k="page">{t("Page")}</sw.Th>
                  <th /></tr>
            </thead>
            <tbody>
              {sw.apply(rows).map((m: any) => (
                <tr key={m.id} className={m.drawing_space_id ? (isSettled(m) ? "row-decided" : "") : "row-unresolved"}>
                  <td><strong>{m.ports ?? "—"}</strong></td>
                  <td className="mono">{m.teap_code || "—"}</td>
                  <td>{m.teap_name}</td>
                  <td style={{ minWidth: 210 }}>
                    <div style={{ display: "flex", alignItems: "center" }}>
                    <SpaceSelect value={m.drawing_space_id || null}
                                 current={spaceById.get(m.drawing_space_id)}
                                 currentLabel={m.drawing_name}
                                 noneLabel={m.locked === "rejected" ? t("— none (your choice) —") : t("— none —")}
                                 options={spaceOptions} project={p}
                                 onChoose={(id) => choose(m, id)} />
                    {/* — none — in one click (4.4.0): it sits at the very top
                        of a list of hundreds of rooms, and getting back up
                        there was a long scroll every time. */}
                    <button type="button" className="small none-btn"
                            disabled={m.locked === "rejected"}
                            title={m.locked === "rejected"
                              ? t("Already set to — none —; Undo takes it back")
                              : t("This space is not on this drawing — set it to — none —")}
                            onClick={() => choose(m, null)}>{t("none")}</button>
                    </div>
                    {m.scope_note && (
                      <div className="small" style={{ color: "var(--warn)", marginTop: 2 }}>{m.scope_note}</div>
                    )}
                    {m.in_scope === false && (
                      <div className="small muted" style={{ marginTop: 2 }}>
                        {t("no ports requested in the TEAP — not part of the study")}
                      </div>
                    )}
                    {/* Says, on the row itself, that this is a decision and not
                        the matcher's guess — so it is visible that re-running
                        will leave it alone. */}
                    {m.locked === "assigned" && (
                      <div className="small" style={{ color: "var(--ok)", marginTop: 2 }}>
                        ✓ {t("your choice — saved, and kept when the matching re-runs")}
                      </div>
                    )}
                    {m.locked === "rejected" && (
                      <div className="small" style={{ color: "var(--warn)", marginTop: 2 }}>
                        {t("you said this space is not on this drawing — kept when the matching re-runs; Undo takes it back")}
                      </div>
                    )}
                    {/* The matcher signed this one itself: an exact code with
                        no rival. Said on the row, so "confirmed" is never read
                        as "confirmed by me". */}
                    {!m.locked && m.confirmed && m.drawing_space_id && (
                      <div className="small muted" style={{ marginTop: 2 }}>
                        {m.method === "exact_name" ? t("identical name, confirmed by the matcher")
                          : t("exact code, confirmed by the matcher")}
                      </div>
                    )}
                  </td>
                  <td>
                    {(() => {
                      // The page is the way to the sheet (4.4.0), centred on
                      // the room this row is tied to.
                      const ds: any = spaceById.get(m.drawing_space_id);
                      return <PageButton ctx={ctx} page={m.page} x={ds?.x} y={ds?.y} />;
                    })()}
                  </td>
                  {/* Confirm, and Undo beside it on a row you decided. Reject
                      went on 2 Sep 2026: choosing the room settles the row and
                      choosing a different one settles it again; a TEAP line
                      with no room chosen is already an exception. Undo (2.6.0)
                      takes back whatever you decided — room, confirmation or
                      rejection — and shows the matcher's own answer again. */}
                  <td style={{ whiteSpace: "nowrap" }}>
                    {/* Confirm only where it means something (4.4.0): a row
                        already confirmed — an exact match the matcher signed,
                        or one you signed — shows a tick, not a button to press
                        as a formality. */}
                    {m.confirmed && hasRoom(m) ? (
                      <span className="small" style={{ color: "var(--ok)" }}
                            title={m.confirmed_by ? t("Confirmed by you") : t("Confirmed by the matcher — an exact match")}>
                        ✓ {m.confirmed_by ? t("confirmed") : t("exact")}
                      </span>
                    ) : (
                    <button className="small primary" disabled={!m.drawing_space_id}
                            title={m.drawing_space_id ? "" : t("Choose the room first")}
                            onClick={() => confirmRow(m)}>{t("Confirm")}</button>
                    )}
                    {m.undo_available && (
                      <button className="small" style={{ marginLeft: 6 }}
                              title={m.auto_ready
                                ? t("Take back your decision on this row and show the matcher's answer again")
                                : t("Take back your decision on this row; run the matching to see the matcher's answer again")}
                              onClick={() => undoRow(m)}>{t("Undo")}</button>
                    )}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={6} className="muted">
                  {tile === "all"
                    ? t("Nothing pending. Run the matching step if you have not yet.")
                    : t("No row on this tile.")}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        {spaces.length > 0 && (
          <p className="muted small" style={{ marginTop: 8 }}>
            {spaces.length} {t("rooms available on this drawing.")}{" "}
            {t("Choosing one here is saved immediately and stays saved: re-running the matching never clears it. Every pairing belongs to this project alone — nothing here is carried to another venue.")}
          </p>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------

/**
 * Demand per space — and the room that serves it. One screen.
 *
 * Until 3 Sep 2026 this list answered "how many ports does this space need"
 * and read the serving room off the last run, and a second screen, *Coverage
 * analysis*, ran the analysis and showed the same rooms with the same
 * override beside a per-NER load table. Two screens for one question, and the
 * button that produced the answer was on the other one. They are one now:
 * run the analysis here, see the room here, change it here.
 *
 * The rule for the room, as Marcelo set it:
 *
 *   1. **The TEAP names it** — when the imported sheet carries a "serving
 *      NER" column and the name is a NER on this list. No doubt, and the row
 *      says "TEAP".
 *   2. **You chose it** — the select on the row. Outranks the TEAP, because
 *      you are looking at the drawing and the TEAP is not.
 *   3. **The nearest NER within the limit that still has free ports.** If the
 *      nearest is full, the next one; if every room within reach is full, the
 *      nearest anyway — flagged *insufficient capacity*, counted in that
 *      room's load, and listed on the Exceptions step, so the decision to draw
 *      a second NER there is made on the report rather than hidden by it.
 *   4. **Nothing within the limit** — no room serves it. The row says which
 *      room is closest and how far, so you can see what it would take.
 *
 * Distance, limit and capacity are evaluated and reported whichever leg
 * chose the room: a pinned room 200 m away comes back *out of limit*.
 *
 * Criticality is not a control here. Once the serving room is chosen the
 * area inherits that room's criticality, which comes from the NERs screen;
 * a second place to state it could only disagree with the first.
 */
/**
 * "page 13 · VFF-410B8-CSL-O" — the page number and, when the title block was
 * read, the drawing number beside it. The number is how the design team names
 * a sheet; the page is how this tool does. Both, so either reader finds it.
 */
export function pageName(p: any, page: number | null | undefined): string {
  if (page == null) return "";
  const pg = p?.pages?.find((x: any) => x.number === page);
  const sheet = pg?.sheet_number ? ` · ${pg.sheet_number}` : "";
  // Several books (4.1.0): ``page`` is a sheet key; the book's series and
  // its own page number say where it is ("400 page 6 · VAA-411B3-VBV-O").
  if (p?.multi_book && pg) return `${bookSeries(p, pg.drawing_id)} ${t("page")} ${pg.page}${sheet}`;
  return `${t("page")} ${page}${sheet}`;
}

/** A sheet key as a short number: the page number in a one-book project —
 *  unchanged — and ``400·6`` (series · page in that book) with several. */
export function sheetNo(p: any, key: number | null | undefined): string {
  if (key == null) return "";
  if (!p?.multi_book) return String(key);
  const pg = p?.pages?.find((x: any) => x.number === key);
  return pg ? `${bookSeries(p, pg.drawing_id)}·${pg.page}` : String(key);
}

/** A book's series — ``400`` for ``VAA_400_XXX_OP.pdf`` — or its file name
 *  when the name carries none (4.1.0). The same rule as ``app.sheets``. */
/** The sheet a person typed (4.2.0): a page number in a one-book project; with
 *  several books the series and the page as the pager shows them ("600 12",
 *  "600 · Page 12", "600 p12") or the drawing number ("VBB-612-GLF-O").
 *  ``null`` when no sheet answers to it. */
export function sheetFromText(p: any, text: string): number | null {
  const raw = String(text || "").trim();
  if (!raw || !p?.pages?.length) return null;
  const byNumber = p.pages.find((pg: any) =>
    pg.sheet_number && String(pg.sheet_number).toUpperCase() === raw.toUpperCase());
  if (byNumber) return byNumber.number;
  if (!p.multi_book) {
    const n = Number(raw);
    return p.pages.some((pg: any) => pg.number === n) ? n : null;
  }
  const m = raw.match(/^(\S+?)\s*(?:[·.\-]|\s)\s*(?:page|p\.?|pg)?\s*(\d+)$/i);
  if (!m) return null;
  const series = m[1].toUpperCase();
  const page = Number(m[2]);
  const hit = p.pages.find((pg: any) =>
    String(bookSeries(p, pg.drawing_id)).toUpperCase() === series && pg.page === page);
  return hit ? hit.number : null;
}

export function bookSeries(p: any, drawingId: number | null | undefined): string {
  const d = p?.drawings?.find((x: any) => x.id === drawingId);
  const stem = String(d?.filename || "").replace(/\.pdf$/i, "");
  const m = stem.match(/(?:^|[_\-\s])(\d{3})(?:[_\-\s]|$)/);
  return m ? m[1] : stem;
}

/** The Demand counters that are filters too (2.10.0): key → does the row belong. */
const EXTRA_FILTERS: Record<string, (s: any, i: any) => boolean> = {
  "x:photographer": (s) => s.demand_type === "photographer",
  "x:chosen": (_s, i) => !!i.assigned_ner_asset_id,
  "x:redirected": (_s, i) => !!i.redirected,
  "x:teap_named": (_s, i) => !!i.teap_ner,
  "x:same_space": (_s, i) => (i.occurrences || []).some((o: any) => o.verdict === "proposed"),
  // 3.0.0: a room the matcher found and nobody confirmed is served by the
  // nearest NER like any other; this counter is how the person reviews them.
  "x:unconfirmed": (_s, i) => i.match_confirmed === false && !!i.serving_ner,
};

/**
 * A hand-off between screens (2.12.0): the Exceptions step and the Drawing
 * viewer open *Demand per space* already searched for one space, and the
 * Exceptions step opens the viewer searched for one name. Module state, read
 * once by the screen that opens — there is one browser tab and one person.
 */
export const HANDOFF: {
  demand: string;
  viewer: string;
  /** A sheet to open the viewer on, and the point to centre and ring there
   *  (4.4.0) — what a page button on NERs and TEAP × drawing sends. */
  viewerAt: { page: number; x?: number | null; y?: number | null } | null;
} = { demand: "", viewer: "", viewerAt: null };

/** Open the Drawing viewer on this sheet, centred on this point when given. */
export function openViewerAt(ctx: Ctx, page: number, x?: number | null, y?: number | null) {
  HANDOFF.viewerAt = { page, x, y };
  ctx.go("viewer");
}

/**
 * A page number that is also the way to the sheet (4.4.0). Marcelo, 22 Oct
 * 2026: the page shown on NERs and on TEAP × drawing should take him straight
 * to the drawing, "assim a movimentação entre telas ficaria mais ágil".
 */
export function PageButton({ ctx, page, x, y, pill = false, long = false, title }: {
  ctx: Ctx; page: number | null | undefined; x?: number | null; y?: number | null;
  pill?: boolean; title?: string;
  /** The page's full name ("400 page 6 · VAA-411B3…") instead of the short
   *  number — where the name was shown before it became a button (4.6.0). */
  long?: boolean;
}) {
  if (page == null) return <>—</>;
  const p = ctx.project;
  return (
    <button type="button" className={`linkish${long ? "" : " mono"} page-link${pill ? " pill" : ""}`}
            title={title || `${t("Open")} ${pageName(p, page)} ${t("in the Drawing viewer")}`}
            onClick={() => openViewerAt(ctx, page, x, y)}>
      {pill ? "p. " : ""}{long ? pageName(p, page) : sheetNo(p, page)}
    </button>
  );
}

/** Open Demand per space with the search box set to this space. */
export function openInDemand(ctx: Ctx, query: string) {
  HANDOFF.demand = query;
  ctx.go("demand");
}

/** Open the Drawing viewer searched for this name. */
export function openInViewer(ctx: Ctx, query: string) {
  HANDOFF.viewer = query;
  ctx.go("viewer");
}

/**
 * Choose (or release) the NER that serves a TEAP space. Shared by Demand per
 * space and the Exceptions step, so the question asked and the message given
 * are the same on both.
 */
async function assignSpaceNer(ctx: Ctx, spaceKey: string, nerAssetId: number | null,
                              after: () => Promise<void>, why = ""): Promise<boolean> {
  const p = ctx.project;
  if (!p) return false;
  try {
    if (nerAssetId !== null && !why) {
      why = prompt(t("Why should this room serve this space? Recorded in the audit log.")) || "";
      if (!why) return false;
    }
    const r = await api.assignSpace(p.id, spaceKey, { ner_asset_id: nerAssetId, justification: why });
    await after();
    if (nerAssetId === null) {
      ctx.notify(t("Released — the rule chooses the room again. Re-run the analysis."));
    } else if (r.other_page) {
      ctx.notify(`${r.ner_name} ${t("is on")} ${pageName(p, r.ner_page)}; ${t("this space is on")} `
        + `${pageName(p, r.space_page)} — ${t("counted on that room from the other page: its ports count against it, and the distance is reported as not measured until a shaft or riser is registered. Re-run the analysis.")}`);
    } else {
      ctx.notify(t("Assigned. Re-run the analysis to see the effect — the distance and the capacity are still checked."));
    }
    return true;
  } catch (e: any) { ctx.notify(e.message, "err"); return false; }
}

/**
 * The rooms a space may be served from — NERs only, live, alphabetical. A
 * TER, an IDF, a COW and a DIVA node are on the drawing and stay there, but
 * none of them may serve a space, and the server refuses the assignment even
 * if a stale list somehow offers one. One definition for every list that
 * offers a room (Demand per space and Exceptions).
 */
function nerRoomOptions(ners: any): { id: number; label: string }[] {
  return ((ners as any)?.ners || [])
    .filter((n: any) => n.is_live !== false && canServe(n.kind))
    .map((n: any) => ({ id: n.id, label: `${n.display_name}${n.classification === "critical" ? " ★" : ""}` }))
    .sort((a: any, b: any) => SPACE_COLLATOR.compare(a.label, b.label));
}

/** Does a Demand row answer the search box? Code, name, the room it is tied
 *  to, its FA and the NER serving it — case and accents ignored. */
function fold(v: any): string {
  return String(v ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function rowMatches(q: string, s: any, i: any): boolean {
  if (!q.trim()) return true;
  const hay = fold([s.space_code, s.space_name, s.functional_area, i.matched_code, i.matched_name,
                    i.serving_ner, i.assigned_ner, i.teap_ner].join(" | "));
  return fold(q).split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

export function DemandPanel({ ctx }: { ctx: Ctx }) {
  const sd = useSort<any>();
  const sl = useSort<any>();
  const p = ctx.project;
  const [filter, setFilter] = useState("");
  //: The search box (2.12.0), filled when another screen sent us here.
  const [q, setQ] = useState(() => { const v = HANDOFF.demand; HANDOFF.demand = ""; return v; });
  const [showLoad, setShowLoad] = useState(false);
  //: Which rows have their notes opened out; and the switch that opens all of
  //  them at once. Closed, a cell shows two lines and the count.
  const [openNotes, setOpenNotes] = useState<Record<string, boolean>>({});
  const [allNotes, setAllNotes] = useState(false);
  //: TEAP spaces that request no port are left off this screen; this shows them.
  const [showZero, setShowZero] = useState(false);
  const [showWireless, setShowWireless] = useState(true);
  const sw2 = useSort<any>();
  const job = useJob();
  const { data: allSpaces, reload } = useAsync(
    () => (p ? api.teapSpaces(p.id) : Promise.resolve([])), [p?.id], [] as any[]);
  const { data: pins, reload: reloadPins } = useAsync(
    () => (p ? api.assignments(p.id, showZero) : Promise.resolve({ spaces: [] })),
    [p?.id, showZero], { spaces: [] } as any);
  // The TEAP says whether an area is served: no ports requested, not on the list.
  const spaces = useMemo(
    () => allSpaces.filter((x: any) => showZero || x.in_scope !== false),
    [allSpaces, showZero]);
  const zeroHidden = allSpaces.filter((x: any) => x.in_scope === false).length;
  const { data: ners } = useAsync(
    () => (p ? api.ners(p.id) : Promise.resolve({ ners: [] })), [p?.id], { ners: [] } as any);
  if (!p) return null;

  const total = spaces.reduce((s, x) => s + x.total_ports, 0);

  // NERs only. A TER, an IDF, a COW and a DIVA node are on the drawing and
  // stay there, but none of them may serve a space — and the server refuses
  // the assignment even if a stale list somehow offers one.
  const roomOptions = nerRoomOptions(ners);

  const info: Record<string, any> = {};
  for (const sp of (pins as any).spaces || []) info[sp.space_key] = sp;
  const analysed = (pins as any).analysed_at;
  const summary = (pins as any).summary;
  const nerLoad: any[] = (pins as any).ner_load || [];
  const wirelessPoints: any[] = (pins as any).wireless_points || [];

  /** A wireless point placed by mistake, removed from the list that counts it. */
  const deleteWireless = async (w: any) => {
    if (!confirm(`${t("Delete")} ${w.label} (${pageName(p!, w.page)})?`)) return;
    try {
      await api.deleteElement(p!.id, w.id);
      await reloadPins();
      ctx.notify(`${w.label} ${t("deleted from the drawing")}. ${t("Re-run the analysis to see the effect.")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /** Indoor (covered) or outdoor (open) for one Wi-Fi point (4.5.0) — a
   *  note for the LLD team, the same field a NER has. No re-run needed: the
   *  workbook reads it off the point when it is exported. */
  const setWirelessEnvironment = async (w: any, env: string) => {
    try {
      await api.patchElement(p!.id, w.id, { environment: env });
      await reloadPins();
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /** Choose (or release) the NER for one wireless point. */
  const serveWireless = async (w: any, nerAssetId: number | null) => {
    try {
      await api.serveWireless(p!.id, w.id, { ner_asset_id: nerAssetId,
        justification: nerAssetId ? "chosen for the wireless point" : "released" });
      await reloadPins();
      ctx.notify(nerAssetId
        ? `${w.label}: ${t("assigned. Re-run the analysis to see the effect.")}`
        : `${w.label}: ${t("released. Re-run the analysis to see the effect.")}`);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };
  /** The first option of a point's select: what it follows with no choice of its own. */
  const wirelessPlaceholder = (w: any) => {
    if (w.assigned_ner_asset_id) return w.space_ner
      ? `${t("✕ clear my choice — back to its TEAP space's NER")}: ${w.space_ner}`
      : t("✕ clear my choice — back to the nearest NER rule");
    if (w.space_ner) return `${t("as its TEAP space")}: ${w.space_ner}`;
    if (w.serving_ner) return `${t("nearest:")} ${w.serving_ner}`;
    if (!w.status) return t("— not analysed yet —");
    return w.nearest_ner
      ? `${t("— none within")} ${w.limit_m ?? p!.settings.general_limit_m} m · ${t("nearest")}: ${w.nearest_ner}`
      : t("— nothing reaches it: choose the NER —");
  };

  /** "Is the label on that other page the same space?" — one row at a time. */
  const decideOccurrence = async (linkId: number, verdict: string) => {
    try {
      const r = await api.decideOccurrenceLink(p!.id, linkId, { verdict });
      await reloadPins();
      ctx.notify(verdict === "confirmed"
        ? t("Recorded as the same space. Re-run the analysis: the distance is measured from the page the NER is on.")
        : verdict === "rejected"
          ? t("Recorded as a different space — that page is not used for this row. Re-run the analysis.")
          : r.note);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  /** Choose the room that serves this space, or hand it back to the rule. */
  const assign = (spaceKey: string, nerAssetId: number | null) =>
    assignSpaceNer(ctx, spaceKey, nerAssetId, reloadPins);

  const run = async () => {
    try {
      await job.start(() => api.analyse(p.id, "As-Is"), async (j) => {
        if (j.state === "error") { ctx.notify(j.error, "err"); return; }
        if (j.state !== "done") return;
        await Promise.all([reloadPins(), reload(), ctx.reload()]);
        ctx.notify(t("Coverage computed — the serving NER, the distance and the status on every row are from this run."));
      });
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  // The filter is a group ("pending") or a precise status ("status:match_not_confirmed").
  const rows = spaces.filter((s) => {
    const i = info[s.space_key] || {};
    if (!rowMatches(q, s, i)) return false;
    if (!filter) return true;
    // The counters under the tiles filter too (2.10.0).
    if (filter.startsWith("x:")) return EXTRA_FILTERS[filter]?.(s, i) ?? true;
    return filter.startsWith("status:") ? i.status === filter.slice(7) : i.group === filter;
  });
  /** A counter that is also the filter for its rows. */
  const counter = (key: string, n: any, label: string, colour?: string, title?: string) => (
    <button type="button" key={key} className={`stat tile ${filter === key ? "on" : ""}`}
            title={title || t("Click to show only these rows; click again for all")}
            onClick={() => setFilter(filter === key ? "" : key)}>
      <div className="n" style={{ color: colour }}>{n}</div>
      <div className="k">{t(label)}</div>
    </button>
  );
  const byStatus: Record<string, number> = summary?.by_status || {};
  const byGroup: Record<string, number> = (pins as any).by_group || {};

  /** What the select shows when nothing is chosen by hand: the rule's answer,
   *  or why there is none. A space whose match or page scale is not confirmed
   *  is not assigned at all — those results stay blocked on purpose — so the
   *  row says which, and names the closest room so the blank is not read as
   *  "nothing reaches it". */
  const placeholder = (i: any, placed: boolean) => {
    // With a room chosen by hand this option is the way back (2.10.0): it
    // clears the choice and says what the row returns to.
    if (i.assigned_ner_asset_id) {
      if (i.teap_ner_asset_id) return `${t("✕ clear my choice — back to the TEAP's room")}: ${i.teap_ner_name}`;
      return placed ? t("✕ clear my choice — back to the nearest NER rule")
                    : t("✕ clear my choice — back to: no room on the drawing");
    }
    if (i.teap_ner_asset_id) return `TEAP: ${i.teap_ner_name}`;
    if (i.serving_ner) return `${t("nearest:")} ${i.serving_ner}${i.serving_ner_critical ? " ★" : ""}`;
    if (i.group_reason === "no room on the drawing") return t("— no room on the drawing: choose the NER that serves it —");
    if (!analysed) return t("— not analysed yet —");
    if (!i.status) return t("— not analysed yet —");
    const nearest = i.nearest_ner
      ? ` · ${t("nearest")}: ${i.nearest_ner} ${t("at")} ${fmtLen(i.nearest_distance_m, ctx.units)}`
      : "";
    if (i.status === "match_not_confirmed") return `${t("match not confirmed")}${nearest}`;
    if (i.status === "scale_not_confirmed") return `${t("scale not confirmed")}${nearest}`;
    if (i.status === "route_not_validated") return `${t("route not validated")}${nearest}`;
    if (i.nearest_ner)
      return `${t("— none within")} ${i.limit_m ?? p.settings.general_limit_m} m${nearest}`;
    return t("— nothing reaches it —");
  };
  const tile = (g: string) => (
    <button type="button" key={g} className={`stat tile ${filter === g ? "on" : ""}`}
            title={t("Click to show only these rows; click again for all")}
            onClick={() => setFilter(filter === g ? "" : g)}>
      <div className="n" style={{ color: byGroup[g] ? GROUP_COLOUR[g] : undefined }}>{byGroup[g] || 0}</div>
      <div className="k">{t(GROUP_LABEL[g])}</div>
    </button>
  );

  return (
    <>
      <div className="card">
        <h2>{t("Demand per space and the NER that serves it")}</h2>
        <div className="row">
          <button className="primary" onClick={run} disabled={job.busy}>{t("Run analysis")}</button>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 300 }}
                  title={t("The four piles, and under each the precise reason from the last run")}>
            <option value="">{t("all spaces")} ({spaces.length})</option>
            {filter.startsWith("x:") && <option value={filter}>{t("filtered by a counter below")} ({rows.length})</option>}
            {GROUP_ORDER.map((g) => (
              <optgroup key={g} label={`${t(GROUP_LABEL[g])} (${byGroup[g] || 0})`}>
                <option value={g}>{t("all")} — {t(GROUP_LABEL[g])} ({byGroup[g] || 0})</option>
                {Object.keys(byStatus).filter((k) => (groupOf(k) === g)).map((k) => (
                  <option key={k} value={`status:${k}`}>· {t(STATUS_LABEL[k] || k)} ({byStatus[k]})</option>
                ))}
              </optgroup>
            ))}
          </select>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 240 }}
                 placeholder={t("search code, name, room or NER")}
                 title={t("Shows only the rows whose code, name, room on the drawing, FA or NER contain every word typed")} />
          {q && <span className="small" style={{ marginBottom: 0 }}>{rows.length} {t("row(s)")}</span>}
          <span className="muted small" style={{ marginBottom: 0 }}>
            {analysed
              ? `${t("Last run")}: ${new Date(analysed).toLocaleString()}`
              : t("No analysis yet — the rows show demand only.")}
          </span>
          {(pins as any).stale && (
            <span className="pill" style={{ color: "var(--warn)", marginBottom: 0 }}
                  title={t("Something changed after the last run. The exports run the analysis again by themselves; press Run analysis to see the new figures here.")}>
              {t("changed since the last run")} ({(pins as any).stale.changes})
            </span>
          )}
          <label style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 0 }}
                 title={t("The TEAP says whether an area is served. A TEAP space that requests no port is not matched by hand, not analysed and not listed here.")}>
            <input type="checkbox" checked={showZero} style={{ width: "auto" }}
                   onChange={(e) => setShowZero(e.target.checked)} />
            {t("show TEAP spaces with no ports")} ({zeroHidden})
          </label>
        </div>
        <div style={{ marginTop: 10 }}>
          <JobBar job={job.job} onCancel={job.cancel} onDismiss={job.clear} />
        </div>
        <div className="grid c4" style={{ marginTop: 12 }}>
          <div className="stat"><div className="n">{spaces.length}</div><div className="k">{t("spaces")}</div></div>
          <div className="stat"><div className="n">{total.toFixed(0)}</div><div className="k">{t("ports")}</div></div>
          {/* The four piles (2.7.0), counted from the rows as they stand —
              a room tied or a NER chosen after the last run already moves
              the row. Each tile is the filter for its rows. */}
          {GROUP_ORDER.map((g) => tile(g))}
          {(byStatus.near_limit || 0) > 0 && counter("status:near_limit", byStatus.near_limit,
            "near the limit (counted as served)", "var(--warn)",
            t("Served, within the limit but close to it. Counted in Served; click to see them"))}
          {counter("x:photographer", spaces.filter((s) => s.demand_type === "photographer").length, "photographer areas")}
          {counter("x:chosen", (pins as any).pinned || 0, "rooms chosen by you")}
          {wirelessPoints.length > 0 && (
            <div className="stat" title={t("Wireless points drawn in the Drawing viewer — one port each on the NER that reaches them")}>
              <div className="n" style={{ color: "#0096c7" }}>{wirelessPoints.length}</div>
              <div className="k">{t("wireless points")}</div>
            </div>
          )}
          {(() => {
            const n = spaces.filter((s) => EXTRA_FILTERS["x:unconfirmed"](s, info[s.space_key] || {})).length;
            return n > 0 && counter("x:unconfirmed", n, "served — room not confirmed", "var(--warn)",
              t("Counted on the nearest NER from the room the matcher found; confirm the room on TEAP × drawing when you have checked it"));
          })()}
          {(pins as any).same_space_questions > 0 && counter("x:same_space",
            (pins as any).same_space_questions, "same space on another page? — to confirm", "var(--warn)",
            t("The same code or name is on another page and nobody has said whether it is the same space — see the row"))}
          {(pins as any).redirected > 0 && counter("x:redirected", (pins as any).redirected,
            "tied to another room", "var(--accent, #4c8dff)",
            t("TEAP spaces tied to a drawing room with a different code — see the Matched to column"))}
          {(pins as any).teap_named > 0 && counter("x:teap_named",
            <>{(pins as any).teap_named - (pins as any).teap_unresolved}
              {(pins as any).teap_unresolved ? ` / ${(pins as any).teap_named}` : ""}</>,
            "rooms named by the TEAP", (pins as any).teap_unresolved ? "var(--warn)" : undefined)}
        </div>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {t("The room comes from the TEAP when its sheet names one, from you when you choose one on the row, and otherwise from the rule: the nearest NER within the limit that still has free ports — the next one if the nearest is full, and the nearest anyway, flagged, if every room within reach is full. Distance, limit and capacity are checked and reported whichever way the room was chosen.")}{" "}
          {t("A TEAP space with no room on the drawing is pending until you tie it to a room on TEAP × drawing or choose its NER here: then its ports count against that NER and the distance is reported as not measured.")}{" "}
          {t("A room the matcher found is served by the nearest NER before you confirm it; the row says the room is not confirmed until you do.")}
        </p>
      </div>

      <div className="card">
        {/* ``wide``: the table keeps its working width and the box scrolls
            sideways on a narrow screen — with the scrollbar mirrored at the
            top, where it can be seen — instead of the columns being crushed
            into unreadable slivers (Marcelo, 22 Sep 2026). */}
        <WideScroll>
          <table className="wide">
            <thead>
              <tr><sd.Th k="space_code">{t("Code")}</sd.Th><sd.Th k="space_name">{t("Space")}</sd.Th>
                  {/* From → to: the room on the drawing this TEAP line was
                      tied to on TEAP × drawing. Redirected rows sort first. */}
                  <sd.Th k="matched" title={t("The room on the drawing this TEAP line was tied to. An arrow means it was tied to a room with a different code — decided on TEAP × drawing.")}
                         get={(r) => `${info[r.space_key]?.redirected ? "0" : "1"}${info[r.space_key]?.matched_code || info[r.space_key]?.matched_name || "~"}`}>
                    {t("Matched to")}
                  </sd.Th>
                  <sd.Th k="functional_area">{t("FA")}</sd.Th><sd.Th k="ports" get={(r) => r.total_ports}>{t("Ports")}</sd.Th>
                  <th>{t("Demand type")}</th>
                  <sd.Th k="served" get={(r) => info[r.space_key]?.assigned_ner || info[r.space_key]?.serving_ner}>{t("Served by")}</sd.Th>
                  <sd.Th k="dist" get={(r) => info[r.space_key]?.distance_m}>{t("Distance")}</sd.Th>
                  <sd.Th k="status" get={(r) => info[r.space_key]?.status}>{t("Status")}</sd.Th>
                  <th style={{ minWidth: 260 }}>
                    {t("Notes")}{" "}
                    <button type="button" className="small linkish"
                            title={t("Open every row's notes in full, or fold them back")}
                            onClick={() => { setAllNotes((v) => !v); setOpenNotes({}); }}>
                      {allNotes ? t("fold all") : t("open all")}
                    </button>
                  </th></tr>
            </thead>
            <tbody>
              {sd.apply(rows).map((s) => {
                const i = info[s.space_key] || {};
                const notes = [...(i.notes || []), ...(s.warnings || [])];
                const spacePage = i.page ?? i.matched_page;
                const open = allNotes || !!openNotes[s.space_key];
                const toggleNotes = () => setOpenNotes((m) => ({ ...m, [s.space_key]: !open }));
                // The room chosen sits on another page than the space: the
                // declaration box is shown, ticked by the choice itself.
                const otherPage = i.assigned_ner_asset_id && i.assigned_ner_page != null
                  && spacePage != null && i.assigned_ner_page !== spacePage;
                const target = i.matched_code || i.matched_name;
                return (
                  <tr key={s.id}>
                    <td className="mono">{s.space_code || "—"}</td>
                    <td>
                      {s.space_name}{spacePage ? (
                        <div className="small muted">
                          {/* 4.6.0: the page is the way to the sheet, as on TEAP × drawing. */}
                          <PageButton ctx={ctx} page={spacePage} long
                                      x={spacePage === i.matched_page ? i.matched_x : null}
                                      y={spacePage === i.matched_page ? i.matched_y : null} />
                        </div>
                      ) : null}
                      {i.scope_note && <div className="small" style={{ color: "var(--warn)" }}>{i.scope_note}</div>}
                      {s.in_scope === false && (
                        <div className="small muted">{t("no ports requested in the TEAP — not part of the study")}</div>
                      )}
                      {/* The same space on other pages. Confirmed: the run may
                          measure from there. Proposed: a question, with the
                          answer it would give when that answer changes the row. */}
                      {(i.occurrences || []).map((o: any) => (
                        <div key={o.id} className="small" style={{ marginTop: 3,
                             color: o.verdict === "proposed" ? "var(--warn)" : undefined }}
                             title={(o.evidence || []).join(" · ")}>
                          {o.verdict === "confirmed" && (
                            <span className="muted">
                              ✓ {t("also on")} <PageButton ctx={ctx} page={o.page} x={o.x} y={o.y} long /> — {o.auto
                                ? t("same code, same level")
                                : t("same space, confirmed by you")}{" "}
                              <button type="button" className="small linkish"
                                      onClick={() => decideOccurrence(o.id, "rejected")}>{t("not the same space")}</button>
                            </span>
                          )}
                          {o.verdict === "proposed" && (
                            <span>
                              <strong>{t("also on")} <PageButton ctx={ctx} page={o.page} x={o.x} y={o.y} long /></strong>
                              <span className="muted">
                                {" "}— {o.method === "name" ? t("same name, no code") : t("same code")}
                                {" · "}{o.level_basis === "drawing_number"
                                  ? t("same level by the drawing number")
                                  : t("level not read")}
                              </span>
                              {i.occurrence_hint && i.occurrence_hint.link_id === o.id && (
                                <div>{i.occurrence_hint.ner_label} {t("is")} {fmtLen(i.occurrence_hint.distance_m, ctx.units)} {t("from it there")}</div>
                              )}
                              <div style={{ marginTop: 2 }}>
                                <button type="button" className="small"
                                        onClick={() => decideOccurrence(o.id, "confirmed")}>{t("Same space")}</button>{" "}
                                <button type="button" className="small"
                                        onClick={() => decideOccurrence(o.id, "rejected")}>{t("Not the same")}</button>
                              </div>
                            </span>
                          )}
                          {o.verdict === "rejected" && (
                            <span className="muted">
                              ✕ <PageButton ctx={ctx} page={o.page} x={o.x} y={o.y} long /> — {t("not the same space (your answer)")}{" "}
                              <button type="button" className="small linkish"
                                      onClick={() => decideOccurrence(o.id, "proposed")}>{t("undo")}</button>
                            </span>
                          )}
                        </div>
                      ))}
                    </td>
                    <td style={{ minWidth: 170 }}>
                      {!target ? (
                        <span className="small muted">{t("— not matched —")}</span>
                      ) : i.redirected ? (
                        <>
                          <div className="mono" style={{ color: "var(--accent, #4c8dff)", whiteSpace: "nowrap" }}>
                            {s.space_code || s.space_name} → {target}
                          </div>
                          <div className="small muted">
                            {i.matched_code && i.matched_name ? `${i.matched_name} · ` : ""}
                            {i.match_method === "manual" ? t("tied by hand")
                              : i.match_confirmed ? t("matched, confirmed") : t("matched, not confirmed")}
                          </div>
                        </>
                      ) : (
                        <div className="small muted">
                          {t("same room")}
                          {i.match_confirmed === false ? ` · ${t("room not confirmed")}` : ""}
                        </div>
                      )}
                    </td>
                    <td className="small muted">{s.functional_area || "—"}</td>
                    <td><strong>{s.total_ports}</strong></td>
                    <td>
                      {/* Wide enough for "photographer (70 m)": the column's
                          natural width cut it to "pho" (2.8.0 test pass). */}
                      <select value={s.demand_type} style={{ minWidth: 170 }} onChange={async (e) => {
                        await api.patchTeapSpace(p.id, s.id, { demand_type: e.target.value });
                        await reload();
                      }}>
                        <option value="general">{t("general")} ({p.settings.general_limit_m} m)</option>
                        <option value="photographer">{t("photographer")} ({p.settings.photographer_limit_m} m)</option>
                      </select>
                    </td>
                    {/* The room, and where it came from. The placeholder names
                        what the rule chose, so the select reads as an override
                        of a real answer rather than an empty field. */}
                    <td style={{ minWidth: 230 }}>
                      <select value={i.assigned_ner_asset_id || ""}
                              onChange={(e) => assign(s.space_key,
                                e.target.value ? Number(e.target.value) : null)}>
                        <option value="">{placeholder(i, !!target)}</option>
                        {roomOptions.map((o: any) => (
                          <option key={o.id} value={o.id}>{o.label}</option>
                        ))}
                      </select>
                      {i.assigned_ner_asset_id && (
                        <div className="small" style={{ color: "var(--accent, #4c8dff)" }}>
                          {t("chosen by you")}{i.reason ? ` — ${i.reason}` : ""}
                          {i.teap_ner_asset_id && i.teap_ner_asset_id !== i.assigned_ner_asset_id
                            ? ` · ${t("the TEAP names")} ${i.teap_ner_name}` : ""}
                        </div>
                      )}
                      {!target && (i.assigned_ner_asset_id || i.teap_ner_asset_id) && (
                        <div className="small muted"
                             title={t("This TEAP space is not on the drawing. The room you chose serves it: its ports count against that room and no distance is measured.")}>
                          {t("no room on the drawing — counted on this NER, distance not measured")}
                        </div>
                      )}
                      {/* "other level": the statement that the room chosen sits
                          on another level than this space. Ticked by the choice
                          of a room on another page; untick to withdraw it. */}
                      {/* The room chosen is on another page: counted from
                          there, distance not measured (2.10.0 — the choice is
                          the declaration; there is no box to tick). */}
                      {otherPage && (
                        <div className="small" style={{ color: "var(--ok)" }}
                             title={t("The room you chose is on another page. Its ports count against that room and the distance is reported as not measured until a shaft, riser or vertical route is registered.")}>
                          <strong>{t("other page")}</strong> — {i.assigned_ner} {t("is on")} {pageName(p, i.assigned_ner_page)};{" "}
                          {t("this space is on")} {pageName(p, spacePage)} · {t("counted on this NER, distance not measured")}
                        </div>
                      )}
                      {!i.assigned_ner_asset_id && i.teap_ner_asset_id && (
                        <div className="small" style={{ color: "var(--ok)" }}>
                          {t("named in the TEAP — no doubt")}
                        </div>
                      )}
                      {i.teap_ner && !i.teap_ner_asset_id && (
                        <div className="small" style={{ color: "var(--warn)" }}>
                          {t("the TEAP names")} “{i.teap_ner}” — {t("no NER with that name on the NERs screen")}
                        </div>
                      )}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {fmtLen(i.distance_m, ctx.units)}
                      {i.limit_m != null && i.distance_m != null && (
                        <span className="small muted"> / {i.limit_m} m</span>
                      )}
                      {i.method === "straight_line" && i.distance_m != null && (
                        <div className="small muted" title={t("Straight-line screening distance; validate against the cable route")}>
                          {t("straight line")}
                        </div>
                      )}
                      {i.measured_page && (
                        <div className="small muted"
                             title={t("The same space is labelled on more than one page; the distance was measured on the page the serving NER is on.")}>
                          {t("measured on")} {pageName(p, i.measured_page)}
                        </div>
                      )}
                      {i.cross_level && i.distance_m == null && (
                        <div className="small" style={{ color: "var(--warn)" }}
                             title={t("Served from another page/level with no vertical route registered: the distance was not measured.")}>
                          {t("other level — not measured")}
                        </div>
                      )}
                      {i.cross_level && i.distance_m != null && (
                        <div className="small muted">{t("via vertical route")} · {pageName(p, i.serving_ner_page)}</div>
                      )}
                    </td>
                    <td style={{ minWidth: 150 }}>
                      {i.group ? <GroupPill group={i.group} reason={i.group_reason} />
                        : <span className="muted small">—</span>}
                    </td>
                    {/* The notes, readable. Closed, two lines and the count;
                        open, one line per note, wrapped, nothing clipped. */}
                    <td className={`small notes ${open ? "open" : ""}`}>
                      {notes.length === 0 ? (
                        <span className="muted">—</span>
                      ) : open ? (
                        <ul className="notes-list">
                          {notes.map((n, k) => <li key={k}>{n}</li>)}
                        </ul>
                      ) : (
                        <div className="clamp notes-clamp muted" onClick={toggleNotes}
                             title={t("Click to read every note")}>
                          {notes.join(" · ")}
                        </div>
                      )}
                      {notes.length > 0 && (
                        <button type="button" className="small linkish" onClick={toggleNotes}>
                          {open ? t("fold") : `${t("read")} (${notes.length})`}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {spaces.length === 0 && <tr><td colSpan={10} className="muted">{t("Import a TEAP first.")}</td></tr>}
              {spaces.length > 0 && rows.length === 0 && (
                <tr><td colSpan={10} className="muted">
                  {q ? t("No space answers this search with this filter.") : t("No space has this status.")}
                </td></tr>
              )}
            </tbody>
          </table>
        </WideScroll>
      </div>

      {wirelessPoints.length > 0 && (
        <div className="card">
          <h2 style={{ cursor: "pointer" }} onClick={() => setShowWireless((v) => !v)}>
            {showWireless ? "▾" : "▸"} {t("Wireless points")} ({wirelessPoints.length})
          </h2>
          <p className="muted small" style={{ margin: 0 }}>
            {t("A point placed by mistake is deleted here or in the Drawing viewer.")}{" "}
            {t("Placed from the TEAP on the Scale screen (one per space with wireless), or drawn by hand in the Drawing viewer (+Wi-Fi). A Wi-Fi point marks a space that has wireless; it is not an access point count and takes no port. The wireless port is the DWISA line of its TEAP space, counted on that space's row and on the NER that serves the space. Each point is measured to the NER of its space (or the nearest within the general limit) so the 90 m rule is checked where the point is drawn; a point with no NER within reach is listed as an exception.")}
          </p>
          {showWireless && (
            <table style={{ marginTop: 8 }}>
              <thead>
                <tr><sw2.Th k="label">{t("Wireless point")}</sw2.Th><sw2.Th k="ap_kind">{t("Type")}</sw2.Th>
                    <sw2.Th k="environment" get={(w) => w.environment || "~"}
                            title={t("Where the service is given: indoor (a covered area) or outdoor (an open area). A column of the Wireless points sheet in the workbook.")}>
                      {t("Indoor / outdoor")}
                    </sw2.Th>
                    <sw2.Th k="page">{t("Page")}</sw2.Th>
                    <sw2.Th k="space_name">{t("TEAP space")}</sw2.Th>
                    <sw2.Th k="serving_ner">{t("Served by")}</sw2.Th>
                    <sw2.Th k="distance_m">{t("Distance")}</sw2.Th><sw2.Th k="status">{t("Status")}</sw2.Th>
                    <th /></tr>
              </thead>
              <tbody>
                {sw2.apply(wirelessPoints).map((w: any) => (
                  <tr key={w.id}>
                    <td className="mono">{w.label}</td>
                    <td>{w.ap_kind || "Wi-Fi"}</td>
                    <td>
                      {/* 4.5.0: said by the person, like a NER's. */}
                      <select className="env-select" value={w.environment || ""}
                              onChange={(e) => void setWirelessEnvironment(w, e.target.value)}>
                        <option value="">{t("— not said —")}</option>
                        <option value="indoor">{t("Indoor")}</option>
                        <option value="outdoor">{t("Outdoor")}</option>
                      </select>
                    </td>
                    <td><PageButton ctx={ctx} page={w.page} x={w.x} y={w.y} long /></td>
                    <td>{w.space_name
                      ? <>{w.space_name} <span className="muted small">· {w.tie_source === "manual" ? t("tied by you") : w.tie_source === "teap" ? t("from the TEAP") : t("proposed")}</span></>
                      : <span className="muted small">{t("— none: not in the TEAP, no port —")}</span>}</td>
                    <td style={{ minWidth: 220 }}>
                      {/* The room for this point (2.11.0): your choice; else the
                          room fixed for its TEAP space; else the rule. */}
                      <select value={w.assigned_ner_asset_id || ""}
                              onChange={(e) => serveWireless(w, e.target.value ? Number(e.target.value) : null)}>
                        <option value="">{wirelessPlaceholder(w)}</option>
                        {roomOptions.map((o: any) => (
                          <option key={o.id} value={o.id}>{o.label}</option>
                        ))}
                      </select>
                      {w.assigned_ner_asset_id
                        ? <div className="small" style={{ color: "var(--accent, #4c8dff)" }}>{t("chosen by you")}</div>
                        : w.space_ner
                          ? <div className="small" style={{ color: "var(--ok)" }}>{t("the NER of its TEAP space")}</div>
                          : null}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {fmtLen(w.distance_m, ctx.units)}
                      {w.limit_m != null && w.distance_m != null && <span className="small muted"> / {w.limit_m} m</span>}
                    </td>
                    <td>{w.status ? <StatusPill status={w.status} /> : <span className="muted small">—</span>}</td>
                    <td>
                      <button className="small danger" onClick={() => deleteWireless(w)}>{t("Delete")}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {nerLoad.length > 0 && (
        <div className="card">
          <h2 style={{ cursor: "pointer" }} onClick={() => setShowLoad((v) => !v)}>
            {showLoad ? "▾" : "▸"} {t("NER load and capacity")} ({nerLoad.length})
          </h2>
          {!showLoad && (
            <p className="muted small" style={{ margin: 0 }}>
              {t("Ports assigned to each NER by the last run against its capacity. Click to open.")}
            </p>
          )}
          {showLoad && (
            <table>
              <thead>
                <tr><sl.Th k="label">{t("NER")}</sl.Th><sl.Th k="page">{t("Page")}</sl.Th>
                    <sl.Th k="critical">{t("Critical")}</sl.Th><sl.Th k="spaces">{t("Spaces")}</sl.Th>
                    <sl.Th k="wireless_points">{t("Wi-Fi")}</sl.Th>
                    <sl.Th k="assigned_ports">{t("Ports assigned")}</sl.Th>
                    <sl.Th k="total_ports">{t("Total ports")}</sl.Th>
                    <sl.Th k="utilisation_pct">{t("Utilisation")}</sl.Th></tr>
              </thead>
              <tbody>
                {sl.apply(nerLoad).map((v: any) => (
                  <tr key={v.key}>
                    <td>{v.label}</td>
                    <td><PageButton ctx={ctx} page={v.page} x={v.x} y={v.y} /></td>
                    <td>{v.critical ? t("yes") : t("no")}</td>
                    <td>{v.spaces}</td>
                    <td>{v.wireless_points || 0}</td>
                    <td>{v.assigned_ports}</td>
                    <td>{v.total_ports ?? <span className="muted">{t("unknown")}</span>}</td>
                    <td style={{ color: (v.utilisation_pct ?? 0) > 100 ? "var(--bad)" : undefined }}>
                      {v.utilisation_pct != null ? `${v.utilisation_pct}%` : "—"}
                      {(v.utilisation_pct ?? 0) > 100 && ` · ${t("over capacity")}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}

/* ``CoveragePanel`` stood here until 3 Sep 2026. Its Run analysis button, its
   totals, its status filter and its NER load table are on Demand per space
   now, beside the rows they describe; the "Space → NER" table it carried was
   the same list with the same override. One question, one screen. */

// ---------------------------------------------------------------------------

/**
 * "As-Is vs Proposed" stood here and has been removed.
 *
 * It compared the current design against one the solver produced, and offered
 * targets — fewer NERs, more NERs, a shorter worst distance — for it to aim at.
 * The premise no longer holds: there is one proposal, and it is the drawing.
 * New rooms are placed by hand in the viewer, where the person placing them can
 * see the shafts, the risers, the power and everything else the solver could
 * not. A screen comparing the design against a machine-generated alternative
 * nobody intends to build is not a second opinion, it is a distraction with a
 * number on it.
 *
 * The Scenario table itself stays: the As-Is run is still saved under that name
 * and is what the reports and the demand list read back. What is gone is the
 * optimiser, the second scenario, and the comparison between them.
 */

// ---------------------------------------------------------------------------

/**
 * Exceptions — every TEAP space that still needs you, read from the same rows
 * as Demand per space (2.12.0).
 *
 * Until 2.11.0 this step ran an analysis of its own and listed the engine's
 * exception rows, and a second table listed the TEAP lines with no room. Two
 * gaps came out of that (Marcelo, 25 Sep 2026: *"por que o coverage
 * exceptions parece não mostrar tudo que realmente ficou de fora?"*):
 *
 * * a TEAP space with no room on the drawing and no NER chosen was **not** a
 *   coverage exception — on the VDD project 43 of the 88 spaces, against 4
 *   rows in the list — and only the second table carried it;
 * * the list was the answer of that one run, held on this screen, while
 *   Demand read the stored run with the choices made since. The two screens
 *   could disagree, and a near-limit space was in Demand's *Served* pile.
 *
 * Now one list, from the Demand rows as they stand: pending, out of limit or
 * over capacity, served but not measured, and near the limit — each with the
 * NER that serves it, the NERs the run measured next with their distance (one
 * click to use one), and a link to the row on Demand per space and to the
 * drawing.
 */
type ExKey = "all" | "pending" | "problem" | "near" | "not_measured";

const EX_TILES: [ExKey, string, string][] = [
  ["all", "all that need you", "var(--accent, #4c8dff)"],
  ["pending", "Pending — needs a room or a NER", GROUP_COLOUR.pending],
  ["problem", "Out of limit / over capacity", GROUP_COLOUR.problem],
  ["near", "near the limit", "var(--warn)"],
  ["not_measured", "Served — not measured", GROUP_COLOUR.not_measured],
];

/** Which pile of the Exceptions step a Demand row is in, or null when it is
 *  served within the limit and needs nothing. */
function exKind(r: any): ExKey | null {
  if (r.group === "pending") return "pending";
  if (r.group === "problem") return "problem";
  if (r.status === "near_limit") return "near";
  if (r.group === "not_measured") return "not_measured";
  return null;
}
const EX_ORDER: Record<string, number> = { pending: 0, problem: 1, near: 2, not_measured: 3 };

export function ExceptionsPanel({ ctx }: { ctx: Ctx }) {
  const sx = useSort<any>();
  const p = ctx.project;
  const [tile, setTile] = useState<ExKey>("all");
  const analysisJob = useJob();
  const { data: pins, reload } = useAsync(
    () => (p ? api.assignments(p.id) : Promise.resolve({ spaces: [] })), [p?.id], { spaces: [] } as any);
  const { data: ners } = useAsync(
    () => (p ? api.ners(p.id) : Promise.resolve({ ners: [] })), [p?.id], { ners: [] } as any);
  const roomOptions = useMemo(() => nerRoomOptions(ners), [ners]);

  // Spaces and the wireless points that failed, one list. A wireless point's
  // room is chosen through its own endpoint, so the row says which it is.
  const all = useMemo(() => {
    const out: any[] = [];
    for (const r of (pins as any).spaces || []) {
      if (r.in_scope === false) continue;
      const k = exKind(r);
      if (k) out.push({ ...r, ex: k, row_kind: "space", code: r.space_code, name: r.space_name,
                        where: r.page ?? r.matched_page, served: r.assigned_ner || r.serving_ner });
    }
    for (const w of (pins as any).wireless_points || []) {
      const k: ExKey | null = w.status === "near_limit" ? "near"
        : ["out_of_limit", "insufficient_capacity"].includes(w.status) ? "problem"
        : w.status && !["served", "cross_level_not_measured"].includes(w.status) ? "pending" : null;
      if (k) out.push({ ...w, ex: k, row_kind: "wireless", code: w.label,
                        name: w.space_name ? `${t("wireless point")} · ${w.space_name}` : t("wireless point"),
                        where: w.page, served: w.serving_ner,
                        group_reason: STATUS_LABEL[w.status] || w.status });
    }
    return out.sort((a, b) => (EX_ORDER[a.ex] - EX_ORDER[b.ex]) || ((b.ports || 0) - (a.ports || 0)));
  }, [pins]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: all.length };
    for (const r of all) c[r.ex] = (c[r.ex] || 0) + 1;
    return c;
  }, [all]);
  const rows = tile === "all" ? all : all.filter((r) => r.ex === tile);
  if (!p) return null;
  const analysed = (pins as any).analysed_at;

  const refresh = async () => {
    try {
      await analysisJob.start(() => api.analyse(p.id, "As-Is"), async (j) => {
        if (j.state === "error") { ctx.notify(j.error, "err"); return; }
        if (j.state !== "done") return;
        await Promise.all([reload(), ctx.reload()]);
        ctx.notify(t("Analysis re-run — the list is from this run."));
      });
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  const choose = async (r: any, nerId: number | null, why = "") => {
    if (r.row_kind === "wireless") {
      try {
        await api.serveWireless(p.id, r.id, { ner_asset_id: nerId,
          justification: why || (nerId ? "chosen for the wireless point" : "released") });
        await reload();
        ctx.notify(`${r.label}: ${nerId ? t("assigned. Re-run the analysis to see the effect.")
                                         : t("released. Re-run the analysis to see the effect.")}`);
      } catch (e: any) { ctx.notify(e.message, "err"); }
      return;
    }
    await assignSpaceNer(ctx, r.space_key, nerId, reload, why);
  };

  const pageLabel = (n: any) => (n == null ? "—" : pageName(p, n));

  return (
    <>
      <div className="card">
        <h2>{t("Coverage exceptions")}</h2>
        <div className="row">
          <button className="primary" disabled={analysisJob.busy} onClick={refresh}>
            {t("Re-run the analysis")}
          </button>
          <span className="muted small" style={{ marginBottom: 0 }}>
            {analysed
              ? `${t("Last run")}: ${new Date(analysed).toLocaleString()}`
              : t("No analysis yet — the rows show demand only.")}
          </span>
          {(pins as any).stale && (
            <span className="pill" style={{ color: "var(--warn)", marginBottom: 0 }}
                  title={t("Something changed after the last run. The exports run the analysis again by themselves; press Run analysis to see the new figures here.")}>
              {t("changed since the last run")} ({(pins as any).stale.changes})
            </span>
          )}
        </div>
        <div style={{ marginTop: 10 }}>
          <JobBar job={analysisJob.job} onCancel={analysisJob.cancel} onDismiss={analysisJob.clear} />
        </div>
        <div className="grid c5" style={{ marginTop: 12 }}>
          {EX_TILES.map(([k, label, colour]) => (
            <button type="button" key={k} className={`stat tile${tile === k ? " on" : ""}`}
                    aria-pressed={tile === k}
                    title={tile === k ? t("Click again to show every row") : t("Click to show only these rows")}
                    onClick={() => setTile(tile === k && k !== "all" ? "all" : k)}>
              <div className="n" style={{ color: counts[k] ? colour : undefined }}>{counts[k] || 0}</div>
              <div className="k">{t(label)}</div>
            </button>
          ))}
        </div>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {t("The same rows as Demand per space, read from the last run and the choices made since. Every TEAP space that still needs you is here: with no room and no NER, out of the limit or over capacity, near the limit, or served from another level without a measured distance. Change the NER on the row, or open the row on Demand per space or on the drawing.")}
        </p>
      </div>

      <div className="card">
        <WideScroll>
          <table className="wide">
            <thead>
              <tr><sx.Th k="code">{t("Code")}</sx.Th><sx.Th k="name">{t("Space")}</sx.Th>
                  <sx.Th k="ports">{t("Ports")}</sx.Th>
                  <sx.Th k="ex" get={(r) => EX_ORDER[r.ex]}>{t("Status")}</sx.Th>
                  <sx.Th k="served">{t("Served by")}</sx.Th>
                  <sx.Th k="distance_m" get={(r) => r.distance_m ?? r.nearest_distance_m}>{t("Distance")}</sx.Th>
                  <sx.Th k="alt" get={(r) => r.alternatives?.[0]?.distance_m}>{t("Other NERs measured")}</sx.Th>
                  <th /></tr>
            </thead>
            <tbody>
              {sx.apply(rows).map((r: any) => {
                const alts: any[] = r.alternatives || [];
                return (
                  <tr key={`${r.row_kind}${r.space_key || r.id}`}>
                    <td className="mono">{r.code || "—"}</td>
                    <td>{r.name}{r.where != null && <div className="small muted">{pageLabel(r.where)}</div>}</td>
                    <td><strong>{r.ports ?? "—"}</strong></td>
                    <td style={{ minWidth: 160 }}>
                      {r.row_kind === "space"
                        ? <GroupPill group={r.group} reason={r.group_reason} />
                        : <StatusPill status={r.status} />}
                    </td>
                    <td style={{ minWidth: 220 }}>
                      <select value={r.assigned_ner_asset_id || ""}
                              onChange={(e) => choose(r, e.target.value ? Number(e.target.value) : null)}>
                        <option value="">
                          {r.assigned_ner_asset_id ? t("✕ clear my choice — back to the rule")
                            : r.served ? `${t("nearest:")} ${r.served}`
                            : r.teap_ner_name ? `TEAP: ${r.teap_ner_name}`
                            : t("— no NER yet: choose one —")}
                        </option>
                        {roomOptions.map((o: any) => <option key={o.id} value={o.id}>{o.label}</option>)}
                      </select>
                      {r.assigned_ner_asset_id && (
                        <div className="small" style={{ color: "var(--accent, #4c8dff)" }}>{t("chosen by you")}: {r.assigned_ner}</div>
                      )}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {r.distance_m != null
                        ? <>{fmtLen(r.distance_m, ctx.units)}{r.limit_m != null && <span className="small muted"> / {r.limit_m} m</span>}
                            {r.margin_m != null && r.ex === "near" && (
                              <div className="small" style={{ color: "var(--warn)" }}>{fmtLen(r.margin_m, ctx.units)} {t("margin")}</div>)}</>
                        : r.nearest_ner
                          ? <span className="small">{t("nearest")}: {r.nearest_ner} {t("at")} {fmtLen(r.nearest_distance_m, ctx.units)}</span>
                          : <span className="muted small">{t("not measured")}</span>}
                    </td>
                    <td style={{ minWidth: 200 }}>
                      {alts.length === 0
                        ? <span className="muted small">
                            {r.row_kind === "space" && r.status && (r.matched_code || r.matched_name)
                              ? t("no other NER on this page") : "—"}
                          </span>
                        : alts.map((a: any) => {
                          const within = r.limit_m == null || a.distance_m == null || a.distance_m <= r.limit_m;
                          return (
                            <div key={a.ner_asset_id}>
                              <button type="button" className="small linkish"
                                      title={t("Serve this space from this NER")}
                                      onClick={() => {
                                        const why = prompt(t("Why should this room serve this space? Recorded in the audit log."),
                                                           `${a.label} — ${a.distance_m} m`);
                                        if (why) void choose(r, a.ner_asset_id, why);
                                      }}>
                                {t("use")} {a.label}
                              </button>{" "}
                              <span className="small" style={{ color: within ? "var(--ok)" : "var(--bad)" }}>
                                {fmtLen(a.distance_m, ctx.units)}{!within && ` · ${t("out of limit")}`}
                              </span>
                            </div>
                          );
                        })}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {r.row_kind === "space" && (
                        <button type="button" className="small" title={t("Open this row on Demand per space")}
                                onClick={() => openInDemand(ctx, r.space_code || r.space_name)}>{t("Demand")}</button>
                      )}{" "}
                      {(r.matched_code || r.matched_name || r.row_kind === "wireless") && (
                        <button type="button" className="small" title={t("Find it on the drawing")}
                                onClick={() => openInViewer(ctx, r.row_kind === "wireless" ? r.label : (r.matched_code || r.matched_name))}>
                          {t("Drawing")}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr><td colSpan={8} className="muted">
                  {analysed ? t("Nothing needs you here.") : t("Run the analysis to see what needs you.")}
                </td></tr>
              )}
            </tbody>
          </table>
        </WideScroll>
        <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
          {t("Other NERs measured: the rooms the last run measured from this space, nearest first, the serving one left out. Only rooms on the same page (or joined by a registered shaft) are measured; a NER on another page is chosen in the Served by list and counted as not measured. A near-limit space whose next NER is out of the limit has no closer room today: that is a case for a new NER on the drawing.")}
        </p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------

export function ReportsPanel({ ctx }: { ctx: Ctx }) {
  const srp = useSort<any>();
  const p = ctx.project;
  const [files, setFiles] = useState<{ name: string; url: string }[]>([]);
  const [stray, setStray] = useState<any[]>([]);
  //: The legend box is 320 pt wide, and on a dense CAD sheet it lands on top of
  //  the plan. Turning it off drops the box and the swatches — never the limits,
  //  the scale or the disclaimer, which move to a thin footnote instead.
  const [legend, setLegend] = useState(true);
  //: The space → NER leader lines with their distances. On a sheet with a
  //  hundred served rooms they are the picture; some readers want the markers
  //  and the verdict colours without them. Off, nothing else changes.
  const [lines, setLines] = useState(true);
  const reportJob = useJob();
  if (!p) return null;

  /**
   * Build a report.
   *
   * The marked-up PDF is minutes of work on a full venue book, so it runs as a
   * job with a progress bar naming the page it is on. It used to run inside the
   * request: the single-worker server could serve nothing else while it ran,
   * and the button gave no sign of life — which is indistinguishable, from the
   * outside, from a server that has died. The workbook and the CSV are quick,
   * so they stay synchronous.
   */
  const finish = async (r: any, fmt: string) => {
    setFiles((f) => [{ name: r.file, url: r.download }, ...f.filter((x) => x.name !== r.file)]);
    if (r.off_page_count) {
      setStray(r.off_page || []);
      ctx.notify(
        `${r.off_page_count} ${t("item(s) sit outside their page — re-import the drawing")}`,
        "err");
    } else {
      setStray([]);
      ctx.notify(`${fmt.toUpperCase()} — ${r.file} (${r.source})`
        + (r.analysis_refreshed
          ? ` · ${t("the analysis was run again first:")} ${r.analysis_refreshed.changes} ${t("change(s) after the last run")}`
          : ""));
    }
  };

  const make = async (fmt: "pdf" | "xlsx" | "csv") => {
    try {
      if (fmt === "pdf") {
        await reportJob.start(() => api.report(p.id, fmt, true, legend, lines), async (j) => {
          if (j.state === "error") { ctx.notify(j.error, "err"); return; }
          if (j.state !== "done") return;
          await finish(j.result, fmt);
        });
        return;
      }
      await finish(await api.report(p.id, fmt), fmt);
    } catch (e: any) { ctx.notify(e.message, "err"); }
  };

  return (
    <>
      <div className="card">
        <h2>{t("Exports")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("The workbook opens on a sheet shaped like the TEAP itself — every space, every service, every port — with the NER serving it, whether that NER is critical, and how far away it is. A second sheet lists the NERs and their ports. The scales, the matching evidence and the exceptions follow.")}
        </p>
        {/* The scenario picker is gone with the As-Is vs Proposed screen.
            There is one design — the drawing, with whatever you have placed on
            it — so every export is of that, and a control offering to export
            "the other one" had nothing to offer. */}
        <div className="row">
          <button className="primary" disabled={reportJob.busy}
                  onClick={() => make("pdf")}>{t("Marked-up PDF")}</button>
          <label style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 0 }}
                 title={t("The legend box is 320 pt wide and on a dense sheet it sits over the drawing. Turned off, the limits, the scale and the disclaimer stay as two small lines along the foot of the page (three with the no-coverage warning).")}>
            <input type="checkbox" checked={legend} style={{ width: "auto" }}
                   onChange={(e) => setLegend(e.target.checked)} />
            {t("with legend")}
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 0 }}
                 title={t("The dotted lines from each space to the NER that serves it, with the distance written on them. Turned off, the markers, the area colours and the legend stay exactly as they are.")}>
            <input type="checkbox" checked={lines} style={{ width: "auto" }}
                   onChange={(e) => setLines(e.target.checked)} />
            {t("with NER → space lines")}
          </label>
          <button disabled={reportJob.busy}
                  onClick={() => make("xlsx")}>{t("Analysis workbook (XLSX)")}</button>
          <button disabled={reportJob.busy}
                  onClick={() => make("csv")}>{t("Coverage CSV")}</button>
        </div>
        <div style={{ marginTop: 10 }}>
          <JobBar job={reportJob.job} onCancel={reportJob.cancel}
                  onDismiss={reportJob.clear} />
        </div>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {t("The marked-up PDF marks every page of the book, so on a large venue it takes a minute or two. It runs in the background — the progress bar names the page it is on, and the rest of the app stays usable.")}
        </p>
        {files.length > 0 && (
          <ul style={{ marginTop: 12 }}>
            {files.map((f) => (
              <li key={f.name}><a href={f.url} download>{f.name}</a></li>
            ))}
          </ul>
        )}
        {stray.length > 0 && (
          <div className="warn-box" style={{ marginTop: 12 }}>
            <strong>{t("Positions outside the page")}</strong>
            <p className="small" style={{ margin: "6px 0" }}>
              {t("These were marked where they are stored, not moved. A drawing imported before the page-rotation correction keeps the old coordinates — re-import it and they will fall into place.")}
            </p>
            <table className="small">
              <thead>
                <tr><srp.Th k="kind">{t("Kind")}</srp.Th><srp.Th k="label">{t("Label")}</srp.Th><srp.Th k="page">{t("Page")}</srp.Th>
                  <srp.Th k="x">X</srp.Th><srp.Th k="y">Y</srp.Th>
                  <srp.Th k="page_width">{t("Page size")}</srp.Th></tr>
              </thead>
              <tbody>
                {srp.apply(stray).slice(0, 20).map((s: any, i: number) => (
                  <tr key={i}>
                    <td>{s.kind}</td><td>{s.label}</td><td>{sheetNo(p, s.page)}</td>
                    <td>{s.x}</td><td>{s.y}</td>
                    <td>{s.page_width} × {s.page_height}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* The audit log used to be printed here, under the exports. It is the
          record of who changed what and why — an administration matter, not a
          report — and it now lives on the Account & security screen with the
          accounts and the sessions. */}
    </>
  );
}
