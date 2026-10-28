/**
 * NERs — one screen, one list.
 *
 * Until 3 Sep 2026 this was two tabs: *On the drawing* (every marker the
 * extractor found, with its evidence) and *Register* (one row per physical
 * room, with the decisions about it). The split had a reason — "the drawing
 * says NER 12" and "we renamed it" are different statements — but from the
 * desk it was one job done in two places: rename here, set the criticality
 * there, confirm in both, and find the same room twice under two names.
 *
 * Marcelo's own summary: *"o que eu herdei ou desenhei segue o mesmo
 * princípio. Afinal, se eu passei pela tela de Drawing e ajustei as posições
 * e desenhei mais algumas NERs, tudo passa a ser uma coisa só."*
 *
 * So: one row per NER, inherited from the drawing or drawn by hand, and the
 * row says which. One name — renaming the room relabels its marker on the
 * sheet, and the printed label is kept as history. Criticality is always
 * editable and choosing it is confirming it. Lock, Confirm and Delete on the
 * row; Lock all and Confirm all above it. The marker evidence — the text the
 * extractor read, the colour, the confidence — is behind *Details*, per
 * occurrence, because it is the audit trail and not the working view.
 *
 * What is *not* here: a TER, an IDF, a COW or a DIVA node. Those are drawn,
 * moved, renamed and deleted in the Drawing viewer and take part in nothing
 * else; the tally under the heading says how many there are and where.
 * Change requests (the frozen snapshots) are gone at his request.
 */

import { useEffect, useMemo, useState } from "react";
import type { Ctx } from "../App";
import { api } from "../lib/api";
import { NamingReference } from "../components/NamingReference";
import { DISCLAIMER, KIND_COLOUR, KIND_LABEL, REFERENCE_KINDS, VISUAL_ONLY_KINDS } from "../lib/notation";
import { t } from "../lib/i18n";
import { useSort } from "../components/useSort";
import { PageButton, pageName, sheetNo } from "./panels";
import { nerNameKey } from "./Viewer";

function Pill({ text, colour }: { text: string; colour?: string }) {
  return (
    <span className="pill" style={{ color: colour || "var(--muted)" }}>
      {text}
    </span>
  );
}

function useAsync<T>(fn: () => Promise<T>, deps: any[], initial: T) {
  const [data, setData] = useState<T>(initial);
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

// ---------------------------------------------------------------------------

export function NerRegisterPanel({ ctx }: { ctx: Ctx }) {
  const p = ctx.project;
  const [expanded, setExpanded] = useState<number | null>(null);
  const [onlyUnconfirmed, setOnlyUnconfirmed] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);
  // The naming reference as a side panel (2.14.0): a reference table,
  // folded or open, remembered per browser. It decides nothing.
  const [namingOpen, setNamingOpen] = useState<boolean>(() => {
    try { return localStorage.getItem("ner.naming-side") === "open"; }
    catch { return false; }
  });
  const toggleNaming = () => setNamingOpen((open) => {
    const next = !open;
    try { localStorage.setItem("ner.naming-side", next ? "open" : "closed"); }
    catch { /* private window */ }
    return next;
  });
  const [busy, setBusy] = useState(false);
  const srm = useSort<any>();

  // Removed rows come along too (include_removed) so Restore has something
  // to work on; the table itself shows the live ones.
  const reg = useAsync(() => (p ? api.ners(p.id, true) : Promise.resolve(null)), [p?.id], null as any);
  const dups = useAsync(
    () => (p ? api.duplicateCandidates(p.id) : Promise.resolve(null)),
    [p?.id],
    null as any,
  );
  const hist = useAsync(
    () => (p ? api.consolidations(p.id) : Promise.resolve(null)),
    [p?.id],
    null as any,
  );
  // The visual-only markers — not rows here, but worth a line: "where are
  // the TERs" is the question people arrive with.
  const els = useAsync(() => (p ? api.elements(p.id) : Promise.resolve([])), [p?.id], [] as any[]);
  const reloadAll = async () => {
    await Promise.all([reg.reload(), dups.reload(), hist.reload(), els.reload()]);
  };

  const act = async (fn: () => Promise<any>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      await reloadAll();
      if (ok) ctx.notify(ok);
    } catch (e: any) {
      ctx.notify(e.message, "err");
    } finally {
      setBusy(false);
    }
  };

  const all: any[] = reg.data?.ners || [];
  const rows = useMemo(() => all.filter((r) => r.is_live), [all]);
  const removed = useMemo(() => all.filter((r) => r.deleted_at && !r.merged_into_id), [all]);

  /** The "criticality not stated" tile is a filter (2.13.0): the NERs read
   *  off a room label that does not say critical or non-critical. */
  const [onlyPendingCrit, setOnlyPendingCrit] = useState(false);
  const visible = useMemo(
    () => rows.filter((r) => (!onlyUnconfirmed || !r.confirmed)
                           && (!onlyPendingCrit || r.classification === "pending")),
    [rows, onlyUnconfirmed, onlyPendingCrit]);

  const unconfirmed = rows.filter((r) => !r.confirmed).length;
  const pendingCrit = rows.filter((r) => r.classification === "pending").length;
  const noCapacity = rows.filter((r) => r.capacity?.total_ports == null).length;
  const locked = rows.filter((r) => r.locked).length;

  const tally = useMemo(() => {
    const acc: Record<string, { count: number; pages: Set<number> }> = {};
    for (const e of els.data) {
      if (!VISUAL_ONLY_KINDS.has(e.kind) && !REFERENCE_KINDS.has(e.kind)) continue;
      const row = acc[e.kind] || (acc[e.kind] = { count: 0, pages: new Set() });
      row.count += 1;
      row.pages.add(e.page);
    }
    return acc;
  }, [els.data]);

  if (!p) return null;

  const bulk = async (action: "lock" | "unlock" | "confirm" | "unconfirm") => {
    const n = action === "lock" ? rows.length - locked
      : action === "unlock" ? locked
      : action === "confirm" ? unconfirmed : rows.length - unconfirmed;
    const question = {
      lock: t("Lock every NER against being moved?"),
      unlock: t("Unlock every NER?"),
      confirm: t("Confirm every NER — its criticality and every marker of it on the drawing?"),
      unconfirm: t("Take the confirmation back on every NER?"),
    }[action];
    if (!confirm(`${question} (${n})`)) return;
    await act(async () => {
      const r = await api.bulkNers(p.id, action);
      const skipped = r.skipped.length
        ? ` · ${r.skipped.length} ${t("skipped")}: ${r.skipped.map((s) => `${s.name} — ${s.why}`).join("; ")}`
        : "";
      ctx.notify(`${r.changed} ${t("NER(s)")} ${t({
        lock: "locked", unlock: "unlocked", confirm: "confirmed", unconfirm: "unconfirmed",
      }[action])}${skipped}`, r.skipped.length ? "err" : "ok");
    });
  };

  return (
    <div className="with-side">
    <div className="main">
      <div className="card">
        <h2>{t("NERs")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("One row per NER, whether it came from the drawing or you drew it — the Origin column says which. Every NER the app creates is named in sequence (NERc_01.1, NERc_02.1 … / NER_20.1, NER_21.1 …); rename it here as you like — one name: renaming a room relabels its marker on the sheet, and the label the drawing printed is kept as \"printed as\". Choosing the criticality confirms it. Indoor / outdoor says where the rack stands and goes to the NERs sheet of the workbook. A TER, an IDF, a COW or a DIVA node is not a row here: it is drawn, moved and renamed in the Drawing viewer and takes part in nothing else.")}
        </p>

        <div className="grid c4" style={{ marginBottom: 12 }}>
          <div className="stat">
            <div className="n">{rows.length}</div>
            <div className="k">{t("NERs")}</div>
          </div>
          <div className="stat">
            <div className="n" style={{ color: unconfirmed ? "var(--warn)" : "var(--ok)" }}>{unconfirmed}</div>
            <div className="k">{t("not confirmed")}</div>
          </div>
          <div className={`stat ${onlyPendingCrit ? "active" : ""}`} role="button" tabIndex={0}
               style={{ cursor: "pointer", outline: onlyPendingCrit ? "2px solid var(--warn)" : undefined }}
               title={t("Show only these rows — click again to show all")}
               onClick={() => setOnlyPendingCrit((v) => !v)}
               onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOnlyPendingCrit((v) => !v); }}>
            <div className="n" style={{ color: pendingCrit ? "var(--warn)" : "var(--ok)" }}>{pendingCrit}</div>
            <div className="k">{t("criticality not stated")}</div>
          </div>
          <div className="stat">
            <div className="n" style={{ color: noCapacity ? "var(--warn)" : undefined }}>{noCapacity}</div>
            <div className="k">{t("capacity unknown")}</div>
          </div>
        </div>

        <div className="row" style={{ alignItems: "center" }}>
          <button className="primary" disabled={busy || unconfirmed === 0} onClick={() => bulk("confirm")}
                  title={t("Confirms the criticality and every marker of every NER that is not confirmed yet")}>
            {t("Confirm all")}{unconfirmed ? ` (${unconfirmed})` : ""}
          </button>
          {unconfirmed < rows.length && (
            <button className="small" disabled={busy} onClick={() => bulk("unconfirm")}>{t("Unconfirm all")}</button>
          )}
          <button disabled={busy || locked === rows.length} onClick={() => bulk("lock")}
                  title={t("Locks every NER against being moved on the drawing")}>
            {t("Lock all")}{rows.length - locked ? ` (${rows.length - locked})` : ""}
          </button>
          {locked > 0 && (
            <button className="small" disabled={busy} onClick={() => bulk("unlock")}>{t("Unlock all")} ({locked})</button>
          )}
          <label style={{ display: "flex", gap: 6, alignItems: "center", margin: 0 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={onlyUnconfirmed}
                   onChange={(e) => setOnlyUnconfirmed(e.target.checked)} />
            <span>{t("only rows not confirmed yet")}</span>
          </label>
          <span style={{ flex: 1 }} />
          <button className={showDuplicates ? "small active" : "small"}
                  onClick={() => setShowDuplicates((v) => !v)}>
            {t("Possible duplicates")} ({dups.data?.summary?.pairs ?? 0})
          </button>
          <button className={showHistory ? "small active" : "small"}
                  onClick={() => setShowHistory((v) => !v)}>
            {t("Consolidation history")}
          </button>
          <button className={namingOpen ? "small active" : "small"}
                  title={t("The naming reference, for reference only — it decides nothing")}
                  onClick={toggleNaming}>
            {t("Naming reference")}
          </button>
          {removed.length > 0 && (
            <button className={showRemoved ? "small active" : "small"}
                    onClick={() => setShowRemoved((v) => !v)}>
              {t("Removed")} ({removed.length})
            </button>
          )}
        </div>

        {Object.keys(tally).length > 0 && (
          <p className="small muted" style={{ marginBottom: 0 }}>
            {t("Also on the drawing, managed in the Drawing viewer")}:{" "}
            {Object.keys(KIND_LABEL).filter((k) => tally[k]).map((k, i) => {
              const pages = Array.from(tally[k].pages).sort((a, b) => a - b);
              return (
                <span key={k} title={`${t("page")} ${pages.join(", ")}`}>
                  {i > 0 ? " · " : ""}
                  <span style={{ color: KIND_COLOUR[k], fontWeight: 600 }}>{tally[k].count}</span>{" "}
                  {t(KIND_LABEL[k])} ({t("p.")} {pages.slice(0, 6).join(", ")}{pages.length > 6 ? ` +${pages.length - 6}` : ""})
                </span>
              );
            })}
          </p>
        )}
      </div>

      <RegisterTable
        ctx={ctx}
        rows={visible}
        all={rows}
        expanded={expanded}
        setExpanded={setExpanded}
        busy={busy}
        act={act}
      />

      {showRemoved && removed.length > 0 && (
        <div className="card">
          <h2>{t("Removed NERs")}</h2>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("Nothing is deleted: a removed NER keeps its row, its markers and the reason, and can be restored.")}
          </p>
          <table>
            <thead><tr><srm.Th k="display_name">{t("Name")}</srm.Th><srm.Th k="deleted_reason">{t("Reason")}</srm.Th>
                       <srm.Th k="deleted_at">{t("When")}</srm.Th><th /></tr></thead>
            <tbody>
              {srm.apply(removed).map((r) => (
                <tr key={r.id} style={{ opacity: 0.75 }}>
                  <td>{r.display_name} <span className="mono small muted">{r.code}</span></td>
                  <td className="small muted">{r.deleted_reason || "—"}</td>
                  <td className="small muted">{r.deleted_at ? new Date(r.deleted_at).toLocaleString() : "—"}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="small" disabled={busy}
                            onClick={() => act(() => api.restoreNer(p.id, r.id), `${r.display_name} ${t("restored")}`)}>
                      {t("Restore")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showDuplicates && (
        <DuplicateQueue ctx={ctx} body={dups.data} loading={dups.loading} busy={busy} act={act} />
      )}

      {showHistory && <ConsolidationHistory ctx={ctx} body={hist.data} busy={busy} act={act} />}

      <div className="card">
        <p className="small" style={{ margin: 0, color: "var(--warn)" }}>
          {t(DISCLAIMER)}
        </p>
      </div>
    </div>
    {!namingOpen && (
      <button className="naming-reopen small" onClick={toggleNaming} title={t("Show the naming reference")}>‹ {t("Naming")}</button>
    )}
    <aside className={namingOpen ? "naming-side" : "naming-side collapsed"}>
      <button className="inspector-toggle" onClick={toggleNaming} title={t("Hide the naming reference")}>›</button>
      <NamingReference />
    </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------

function RegisterTable({ ctx, rows, all, expanded, setExpanded, busy, act }: any) {
  const s = useSort<any>();

  return (
    <div className="card">
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <s.Th k="page" get={(r) => r.canonical?.page}>{t("Page")}</s.Th>
              <s.Th k="display_name">{t("Name")}</s.Th>
              <s.Th k="space_code" get={(r) => r.space_code || "~"}
                    title={t("The room's space code as the AAM or the VDB writes it (TEC.010-001). Filled from the code printed on the drawing; type to correct it. Column C of the NERs sheet in the workbook.")}>
                {t("Space code")}
              </s.Th>
              <s.Th k="origin">{t("Origin")}</s.Th>
              <s.Th k="classification">{t("Criticality")}</s.Th>
              <s.Th k="environment" get={(r) => r.environment || "~"}
                    title={t("Where the rack stands — it decides the kind of rack the venue is sent. A column of the NERs sheet in the workbook.")}>
                {t("Indoor / outdoor")}
              </s.Th>
              <s.Th k="cap" get={(r) => r.capacity?.total_ports}>{t("Capacity (ports)")}</s.Th>
              <s.Th k="locked">{t("Lock")}</s.Th>
              <s.Th k="confirmed">{t("Confirm")}</s.Th>
              <th>{t("Details")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {s.apply(rows).map((r: any) => (
              <NerRow
                key={r.id}
                ctx={ctx}
                r={r}
                sameName={rows.filter((o: any) => o.id !== r.id && nerNameKey(o.display_name) === nerNameKey(r.display_name))}
                allRows={rows}
                busy={busy}
                act={act}
                expanded={expanded === r.id}
                toggle={() => setExpanded(expanded === r.id ? null : r.id)}
              />
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={11} className="muted">
                  {all.length === 0
                    ? t("No NER yet. Import a drawing, or place one by hand in the Drawing viewer with the +NER tools.")
                    : t("No row matches this filter.")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const ORIGIN_LABEL: Record<string, string> = {
  vdb_detection: "from the drawing",
  // 2.13.0: read off the NER room the drawing prints — a TEC.003 code or a
  // "Network Equipment Rack (NER)" label — never confirmed until checked.
  drawing_room: "from the room label",
  manual: "drawn by you",
  suggested: "suggested",
  tracker: "from the tracker",
};

function NerRow({ ctx, r, sameName = [], allRows = [], busy, act, expanded, toggle }: any) {
  const p = ctx.project;
  const [name, setName] = useState(r.display_name);
  // 3.0.0: the room's space code as the AAM / VDB writes it (TEC.010-001).
  // Filled from the code printed on the drawing; the person corrects it.
  // Column C of "NERs and ports".
  const [code, setCode] = useState<string>(r.space_code || "");
  const [ports, setPorts] = useState<string>(
    r.capacity.total_ports == null ? "" : String(r.capacity.total_ports),
  );
  useEffect(() => setName(r.display_name), [r.display_name]);
  useEffect(() => setCode(r.space_code || ""), [r.space_code]);
  useEffect(
    () => setPorts(r.capacity.total_ports == null ? "" : String(r.capacity.total_ports)),
    [r.capacity.total_ports],
  );

  const pendingCount = (r.pending_validations || []).length;
  const editable = r.editable !== false;
  const origin = ORIGIN_LABEL[r.origin] || r.origin.replace("_", " ");

  const remove = async () => {
    const why = prompt(`${t("Remove")} ${r.display_name}? ${t("Why — recorded in the audit log")}`,
                       t("not in the design"));
    if (why == null) return;
    // Other live rows with the same name are *separate* register rows (two
    // answers of "no, not the same NER", or two rows renamed alike): removing
    // this one leaves them on their pages, which reads as "the NER came back"
    // (2.18.1). Said plainly, and the choice to take them too is his.
    const twins: any[] = sameName;
    let also: any[] = [];
    if (twins.length) {
      const where = twins.map((o) => `${o.code} (${(o.pages || []).map((n: number) => pageName(p, n)).join(", ") || t("no page")})`).join("; ");
      also = confirm(`${t("Other NER rows carry the same name")} “${r.display_name}”: ${where}.\n\n`
        + `${t("They are separate register rows and stay on their pages unless removed too.")}\n\n`
        + `${t("OK: remove them as well. Cancel: remove only this row.")}`) ? twins : [];
    }
    await act(async () => {
      await api.removeNer(p.id, r.id, why || t("removed on the NERs screen"));
      for (const o of also) await api.removeNer(p.id, o.id, why || t("removed on the NERs screen"));
    }, `${r.display_name}${also.length ? ` ${t("and")} ${also.length} ${t("row(s) of the same name")}` : ""} `
       + t("removed — it leaves every page, the analysis and the export; Restore brings it back"));
  };

  return (
    <>
      <tr className={editable ? "" : "row-closed"}>
        <td style={{ whiteSpace: "nowrap" }}>
          {/* The page is the way to the sheet (4.4.0): one click opens the
              Drawing viewer on it, centred on this NER and ringed. */}
          {r.canonical?.page != null ? (
            <PageButton ctx={ctx} page={r.canonical.page} x={r.canonical.x} y={r.canonical.y} pill />
          ) : (
            <span className="muted small">{t("no position")}</span>
          )}
          {r.pages && r.pages.length > 1 && (
            <div className="small muted">
              {t("also on")}{" "}
              {r.pages.filter((x: number) => x !== r.canonical?.page).map((x: number, i: number) => {
                const o = (r.occurrences || []).find((q: any) => q.page === x);
                return (
                  <span key={x}>
                    {i > 0 && ", "}
                    <PageButton ctx={ctx} page={x} x={o?.x} y={o?.y} />
                  </span>
                );
              })}
            </div>
          )}
        </td>
        <td style={{ minWidth: 190 }}>
          <input
            value={name}
            className="mono"
            disabled={!editable || r.locked}
            title={r.locked ? t("Locked — unlock it to rename") : t("Rename — the marker on the sheet follows; recorded in the audit log")}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              const nn = name.trim();
              if (!nn || nn === r.display_name) { setName(r.display_name); return; }
              // A name another NER already carries (4.2.0): two NERs with one
              // name are counted twice and cannot be told apart in the
              // workbook. Same room → one NER; another room → another name.
              const twin = (allRows || []).find((o: any) => o.id !== r.id && !o.deleted_at
                && !o.merged_into_id && nerNameKey(o.display_name) === nerNameKey(nn));
              if (twin) {
                const same = confirm(
                  `${nn} ${t("is already the name of another NER")}: ${twin.display_name} (${twin.code}`
                  + `${twin.pages?.length ? ` · p. ${twin.pages.map((n: number) => sheetNo(p, n)).join(", ")}` : ""}).\n\n`
                  + t("Is it the same NER? OK makes the two one NER, with every marker of both. Cancel keeps the current name — choose another one."));
                if (same) {
                  act(() => api.consolidateNers(p.id, {
                    primary_id: twin.id, duplicate_id: r.id, force: true,
                    justification: `the same name (${nn}) given on the NERs screen — the same NER`,
                  }), t("consolidated — reversible from the history"));
                } else setName(r.display_name);
                return;
              }
              act(() => api.renameNer(p.id, r.id, { name: nn, reason: "renamed on the NERs screen" }));
            }}
          />
          {r.previous_name && (
            <div className="small muted">
              {t("was")} <span className="mono">{r.previous_name}</span>
            </div>
          )}
        </td>
        <td style={{ minWidth: 130 }}>
          <input
            value={code}
            className="mono"
            placeholder="TEC.010-…"
            disabled={!editable}
            title={t("Space code (AAM / VDB) — goes to the workbook")}
            onChange={(e) => setCode(e.target.value)}
            onBlur={() => {
              if (code.trim() !== (r.space_code || ""))
                act(() => api.patchNer(p.id, r.id, { space_code: code.trim() || null }));
            }}
          />
        </td>
        <td>
          <Pill text={t(origin)} colour={r.origin === "manual" ? "var(--accent, #4c8dff)"
                                     : r.origin === "drawing_room" ? "var(--warn)" : "var(--muted)"} />
        </td>
        {/* Critical or non-critical — the two states a room can be in.
            "Not stated on the drawing" is offered only while the marker's
            label said nothing, and it disappears the moment a value is
            chosen. Choosing IS confirming: the value goes to the engine, and
            the marker on the sheet is repainted in that colour. */}
        <td style={{ minWidth: 150 }}>
          <select
            value={r.classification}
            disabled={busy || !editable}
            style={{ color: r.classification === "critical" ? "var(--bad)" : undefined }}
            onChange={(e) =>
              act(() =>
                api.classifyNer(p.id, r.id, {
                  classification: e.target.value,
                  confirmed: e.target.value !== "pending",
                  reason: "chosen on the NERs screen",
                }),
              )
            }
          >
            <option value="critical">{t("Critical")}</option>
            <option value="non_critical">{t("Non-critical")}</option>
            {r.classification === "pending" && (
              <option value="pending">{t("Not stated on the drawing")}</option>
            )}
          </select>
        </td>
        {/* Indoor / outdoor (2.14.0): said by the person, never read off the
            drawing; the kind of rack the venue is sent depends on it. */}
        <td style={{ minWidth: 120 }}>
          <select value={r.environment || ""} disabled={busy || !editable}
                  onChange={(e) => act(() => api.patchNer(p.id, r.id, { environment: e.target.value || null }))}>
            <option value="">{t("— not said —")}</option>
            <option value="indoor">{t("Indoor")}</option>
            <option value="outdoor">{t("Outdoor")}</option>
          </select>
        </td>
        <td style={{ width: 110 }}>
          <input
            type="number"
            value={ports}
            placeholder={t("unknown")}
            disabled={!editable}
            onChange={(e) => setPorts(e.target.value)}
            onBlur={() => {
              const current = r.capacity.total_ports ?? "";
              if (String(ports) === String(current)) return;
              act(() =>
                api.patchNer(p.id, r.id, {
                  total_ports: ports === "" ? null : Number(ports),
                }),
              );
            }}
          />
        </td>
        <td style={{ textAlign: "center" }}>
          <input type="checkbox" checked={!!r.locked} style={{ width: "auto" }} disabled={busy || !editable}
                 title={t("Locked against being moved on the drawing")}
                 onChange={(e) => act(() => api.lockNer(p.id, r.id, {
                   locked: e.target.checked, reason: "NERs screen",
                 }))} />
        </td>
        <td style={{ textAlign: "center" }}>
          <input type="checkbox" checked={!!r.confirmed} style={{ width: "auto" }} disabled={busy || !editable}
                 title={t("Confirmed: the criticality is right and every marker of this room on the drawing is real")}
                 onChange={(e) => act(() => api.confirmNer(p.id, r.id, {
                   confirmed: e.target.checked, reason: "NERs screen",
                 }))} />
        </td>
        <td>
          <button className="small" onClick={toggle}
                  title={t("Evidence per marker, outstanding validations, history and notes")}>
            {expanded ? t("Close") : `${t("Details")}${pendingCount ? ` (${pendingCount})` : ""}`}
          </button>
        </td>
        <td style={{ textAlign: "right" }}>
          <button className="small danger" disabled={busy || r.locked || !editable} onClick={remove}
                  title={r.locked ? t("Locked — unlock it to remove") : t("Remove from the drawing and the analysis (restorable)")}>
            {t("Delete")}
          </button>
        </td>
      </tr>

      {expanded && (
        <tr>
          <td colSpan={11} style={{ background: "var(--panel-2)" }}>
            <NerDetail ctx={ctx} r={r} busy={busy} act={act} />
          </td>
        </tr>
      )}
    </>
  );
}

function NerDetail({ ctx, r, busy, act }: any) {
  const sdoc = useSort<any>();
  const p = ctx.project;

  return (
    <div style={{ padding: "10px 4px" }}>
      <div className="grid c2">
        <div>
          <h3>{t("Outstanding validations")}</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {(r.pending_validations || []).map((v: string, i: number) => (
              <li key={i} style={{ color: "var(--warn)" }}>
                {v}
              </li>
            ))}
            {(r.pending_validations || []).length === 0 && (
              <li className="muted">{t("nothing outstanding")}</li>
            )}
          </ul>

          <h3>{t("Identity and history")}</h3>
          <div className="small">
            <div>
              {t("Internal id")} <span className="mono">{r.id}</span> · {t("code")}{" "}
              <span className="mono">{r.code}</span> — {t("neither changes when the name does.")}
            </div>
            {r.suggested_name && r.suggested_name !== r.display_name && (
              <div className="muted">{t("Label printed on the drawing")}: <span className="mono">{r.suggested_name}</span></div>
            )}
            {(r.aliases || []).length > 0 && (
              <div className="muted">{t("Also known as")}: {r.aliases.join(", ")}</div>
            )}
            {(r.name_history || []).map((h: any, i: number) => (
              <div key={i} className="muted">
                {new Date(h.at).toLocaleString()} — “{h.old}” → “{h.new}”
                {h.reason ? ` (${h.reason})` : ""} {t("by")} {h.actor}
              </div>
            ))}
            {(r.classification_evidence || []).length > 0 && (
              <div className="muted" style={{ marginTop: 4 }}>
                {t("Criticality read from")}: {r.classification_evidence.slice(0, 3).join("; ")}
              </div>
            )}
          </div>

          <h3>{t("Notes")}</h3>
          <textarea
            rows={2}
            defaultValue={r.notes}
            onBlur={(e) => {
              if ((e.target.value || "") !== (r.notes || ""))
                act(() => api.patchNer(p.id, r.id, { notes: e.target.value }));
            }}
          />
        </div>

        <div>
          {/* The evidence column of the old "On the drawing" tab lives here,
              per marker: what the extractor read, in what colour, on which
              layer, and how sure it was. */}
          <h3>{t("Markers on the drawing")}</h3>
          <table>
            <thead>
              <tr>
                <sdoc.Th k="page">{t("Page")}</sdoc.Th>
                <sdoc.Th k="label">{t("Label")}</sdoc.Th>
                <sdoc.Th k="kind">{t("Kind")}</sdoc.Th>
                <th>{t("Conf.")}</th>
                <th>{t("Evidence")}</th>
                <th>{t("Confirmed")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sdoc.apply(r.occurrences || []).map((o: any) => (
                <tr key={o.id}>
                  <td><PageButton ctx={ctx} page={o.page} x={o.x} y={o.y} /></td>
                  <td className="mono small">{o.label}</td>
                  <td>
                    <span style={{ color: KIND_COLOUR[o.kind] }}>
                      {t(KIND_LABEL[o.kind] || o.kind)}
                    </span>
                    <div className="small muted">{o.origin === "manual" ? t("drawn by you") : t("from the drawing")}</div>
                  </td>
                  <td className="small">{(o.confidence * 100).toFixed(0)}%</td>
                  <td className="small muted" style={{ maxWidth: 320 }}>
                    {(o.evidence || []).join("; ") || "—"}
                  </td>
                  <td className="small">
                    <span style={{ color: o.confirmed ? "var(--ok)" : "var(--warn)" }}>
                      {o.confirmed ? t("yes") : t("no")}
                    </span>
                  </td>
                  <td>
                    {r.occurrence_count > 1 && (
                      <button
                        className="small danger"
                        disabled={busy}
                        title={t("This marker is a different room: give it a row of its own")}
                        onClick={() =>
                          act(
                            () => api.detachOccurrence(p.id, o.id, "separated on the NERs screen"),
                            t("marker separated into its own NER"),
                          )
                        }
                      >
                        {t("Separate")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(r.occurrences || []).length === 0 && (
                <tr><td colSpan={7} className="muted small">
                  {t("No marker on the sheet — the room is drawn from its register position.")}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function DuplicateQueue({ ctx, body, loading, busy, act }: any) {
  const p = ctx.project;
  const [why, setWhy] = useState<Record<string, string>>({});
  if (loading) return <div className="card muted">{t("Comparing the register…")}</div>;
  const rows: any[] = body?.candidates || [];

  return (
    <div className="card">
      <h2>{t("Possible duplicates")}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {body?.note}
      </p>
      {rows.length === 0 && (
        <p className="muted">
          {t("No pair in the list looks like the same room twice. A pair you have already answered — merged, or declared different — stops appearing here.")}
        </p>
      )}
      {rows.map((c: any) => {
        const key = `${c.primary.id}-${c.duplicate.id}`;
        return (
          <div
            key={key}
            style={{
              border: "1px solid var(--line)",
              borderRadius: 8,
              padding: 12,
              marginBottom: 12,
            }}
          >
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <strong className="mono">{c.primary.code}</strong> “{c.primary.display_name}”
                {" ↔ "}
                <strong className="mono">{c.duplicate.code}</strong> “{c.duplicate.display_name}”
              </div>
              <Pill
                text={`${(c.comparison.score * 100).toFixed(0)}% — ${
                  c.comparison.auto_mergeable ? t("strong evidence") : t("needs judgement")
                }`}
                colour={c.comparison.auto_mergeable ? "var(--ok)" : "var(--warn)"}
              />
            </div>

            <div className="grid c2" style={{ marginTop: 8 }}>
              <div>
                <div className="small muted">{t("Evidence they are the same room")}</div>
                <ul className="small" style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {c.comparison.evidence.map((e: string, j: number) => (
                    <li key={j}>{e}</li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="small muted">{t("Differences found")}</div>
                <ul className="small" style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {c.comparison.differences.length === 0 && <li className="muted">{t("none")}</li>}
                  {c.comparison.differences.map((d: string, j: number) => (
                    <li key={j} style={{ color: "var(--warn)" }}>
                      {d}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="small muted">
              {t("Consolidating moves")} {c.impact.occurrences_moved} {t("marker(s)")}
              {c.impact.areas_affected != null &&
                ` ${t("and reassigns")} ${c.impact.areas_affected} ${t("served area(s)")}`}
              . {t("Pages")} {c.primary.pages.map((n: number) => sheetNo(p, n)).join(", ")} {t("and")} {c.duplicate.pages.map((n: number) => sheetNo(p, n)).join(", ")}.
            </div>

            <div className="row" style={{ marginTop: 8 }}>
              <div style={{ flex: 2 }}>
                <label>{t("Justification")}</label>
                <input
                  value={why[key] || ""}
                  onChange={(e) => setWhy({ ...why, [key]: e.target.value })}
                  placeholder={t("what makes you sure")}
                />
              </div>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  act(
                    () =>
                      api.consolidateNers(p.id, {
                        primary_id: c.primary.id,
                        duplicate_id: c.duplicate.id,
                        justification: why[key] || "",
                      }),
                    t("consolidated — reversible from the history"),
                  )
                }
              >
                {t("Same NER — consolidate")}
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  act(
                    () =>
                      api.declareSeparate(p.id, {
                        a_id: c.primary.id,
                        b_id: c.duplicate.id,
                        justification: why[key] || "",
                      }),
                    t("recorded as different rooms"),
                  )
                }
              >
                {t("Different NERs")}
              </button>
              <span className="small muted">{t("or leave it for later — nothing changes")}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------

export function ConsolidationHistory({ ctx, body, busy, act }: any) {
  const shist = useSort<any>();
  const p = ctx.project;
  const rows: any[] = body?.consolidations || [];
  return (
    <div className="card">
      <h2>{t("Consolidation history")}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {t("Every link the tool made on its own is here with its evidence, alongside every decision a person made. A merge can be undone; the list goes back exactly as it was.")}
      </p>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <shist.Th k="at">{t("When")}</shist.Th>
              <shist.Th k="decision">{t("Decision")}</shist.Th>
              <shist.Th k="created_by" get={(h: any) => h.actor}>{t("By")}</shist.Th>
              <shist.Th k="rooms" get={(h: any) => h.primary?.code}>{t("Rooms")}</shist.Th>
              <th>{t("Score")}</th>
              <shist.Th k="evidence" get={(h: any) => (h.evidence || []).join("; ")}>{t("Evidence")}</shist.Th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shist.apply(rows).map((h: any) => (
              <tr key={h.id} style={{ opacity: h.undone_at ? 0.5 : 1 }}>
                <td className="small">{new Date(h.at).toLocaleString()}</td>
                <td>
                  <Pill
                    text={h.undone_at ? t("undone") : h.decision}
                    colour={
                      h.undone_at
                        ? "var(--muted)"
                        : h.decision === "merged"
                        ? "var(--ok)"
                        : h.decision === "separate"
                        ? "var(--accent)"
                        : "var(--warn)"
                    }
                  />
                </td>
                <td className="small">
                  {h.actor}
                  <div className="muted">{h.method}</div>
                </td>
                <td className="small mono">
                  {h.primary?.code}
                  {h.duplicate ? ` ← ${h.duplicate.code}` : ""}
                </td>
                <td className="small">{(h.score * 100).toFixed(0)}%</td>
                <td className="small muted" style={{ maxWidth: 320 }}>
                  {(h.evidence || []).join("; ")}
                  {h.justification && <div style={{ color: "var(--text)" }}>“{h.justification}”</div>}
                </td>
                <td>
                  {h.decision === "merged" && !h.undone_at && (
                    <button
                      className="small"
                      disabled={busy}
                      onClick={() =>
                        act(
                          () => api.undoConsolidation(p.id, h.id, "undone from the history"),
                          t("consolidation undone"),
                        )
                      }
                    >
                      {t("Undo")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  {t("Nothing consolidated yet.")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
