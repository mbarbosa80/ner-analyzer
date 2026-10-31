/**
 * The composite map (5.0.0): the detail sheets of one level of one book on one
 * plane, in a window of its own.
 *
 * Marcelo, 30 Oct 2026: "uma página nada mais é que a continuidade da outra, e
 * se a gente conseguir montar isso tudo num mapa só, sobrepondo essas páginas,
 * o trabalho de localização das NRs fica muito mais fácil". Built only when he
 * asks (Reports → Composite map), never in the Drawing viewer, carrying
 * everything already worked on the sheets. On it he can move a NER, delete it,
 * change its criticality and jump to its sheet in the main window.
 *
 * The picture comes in tiles the server cuts from the composed PDF, so the
 * browser never holds a whole level of a 60-sheet book at once; the NERs, the
 * reach circles and the Wi-Fi points are drawn on top as vectors.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { t } from "../lib/i18n";
import { KIND_COLOUR } from "../lib/notation";
import { useJob } from "../lib/useJob";
import { JobBar } from "../components/JobBar";
import type { Ctx } from "../App";

const STATE_COLOUR: Record<string, string> = {
  confirmed: "#3a6fd8",
  unconfirmed: "#f28c1a",
  contradicted: "#d81b1b",
  not_aligned: "#777777",
};

export const STATE_LABEL: Record<string, string> = {
  confirmed: "confirmed",
  unconfirmed: "not confirmed",
  contradicted: "contradicted",
  not_aligned: "not placed",
};

/** Where the main window is told to open a sheet (5.0.0): the map window
 *  writes it, the main window hears the storage event and opens the viewer. */
export const VIEWER_REQUEST_KEY = "ner.composite.viewerAt";

function openInMainWindow(projectId: number, page: number, x?: number, y?: number) {
  try {
    localStorage.setItem(VIEWER_REQUEST_KEY, JSON.stringify({
      projectId, page, x, y, at: Date.now(),
    }));
  } catch { /* private window */ }
  try { window.opener?.focus(); } catch { /* another origin, or closed */ }
}

export function compositeWindowUrl(projectId: number, mapId: number): string {
  return `/?composite=${projectId}&map=${mapId}`;
}

export function openCompositeWindow(projectId: number, mapId: number) {
  window.open(compositeWindowUrl(projectId, mapId), `ner-composite-${projectId}`);
}

// ---------------------------------------------------------------------------
// The window
// ---------------------------------------------------------------------------

export function CompositeWindow({ projectId, mapId }: { projectId: number; mapId: number }) {
  const [project, setProject] = useState<any>(null);
  const [books, setBooks] = useState<any[]>([]);
  const [current, setCurrent] = useState<number>(mapId);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string>("");
  const [msg, setMsg] = useState<{ text: string; kind: "ok" | "err" } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [lastMove, setLastMove] = useState<any>(null);
  const [focus, setFocus] = useState<{ X: number; Y: number; n: number } | null>(null);
  const [show, setShow] = useState({ reach: true, photo: true, wifi: true, spaces: false,
                                     sheets: true, others: true });
  const job = useJob();

  const load = useCallback(async () => {
    try {
      setErr("");
      const [p, plan, d] = await Promise.all([
        api.getProject(projectId), api.compositePlan(projectId),
        api.compositeMap(projectId, current)]);
      setProject(p);
      setBooks(plan.books || []);
      setData(d);
      document.title = `${t("Composite map")} — ${d.map.label} — ${p.name}`;
    } catch (e: any) {
      setErr(e.message);
    }
  }, [projectId, current]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!msg) return;
    const id = setTimeout(() => setMsg(null), 8000);
    return () => clearTimeout(id);
  }, [msg]);

  const maps = useMemo(() => books.flatMap((b: any) => (b.groups || [])
    .filter((g: any) => g.map?.has_picture)
    .map((g: any) => ({ id: g.map.id, label: `${b.filename} — ${g.label}` }))), [books]);

  const ners: any[] = data?.ners || [];
  const sel = ners.find((n) => n.asset_id === selected) || null;
  const pageName = (key: number) => {
    const pg = project?.pages?.find((x: any) => x.number === key);
    return pg?.sheet_number || `${t("page")} ${pg?.page ?? key}`;
  };

  const move = async (assetId: number, X: number, Y: number) => {
    const n = ners.find((x) => x.asset_id === assetId);
    if (!n) return;
    // 5.1.0 (D26): say how far it goes and which sheets it leaves or is drawn
    // on before the person confirms — the server works it out and changes
    // nothing. A NER whose sheets disagree is refused here (D29).
    let pv: any;
    try {
      pv = await api.moveNerOnMap(projectId, current, { asset_id: assetId, x: X, y: Y, preview: true });
    } catch (e: any) {
      setMsg({ text: e.message, kind: "err" });
      return;
    }
    // The sheet number the window knows (VLL-411A2-SAL-O), else the server's label.
    const lbl = (k: number) => {
      const pg = project?.pages?.find((x: any) => x.number === k);
      return pg?.sheet_number || pv.labels?.[String(k)] || pageName(k);
    };
    const lines = [`${t("Move")} ${n.name} ${pv.distance_m} m?`];
    if (pv.moved?.length) lines.push(`${t("Moves on")}: ${pv.moved.map(lbl).join(", ")}`);
    if (pv.removed?.length) lines.push(`${t("Taken off")}: ${pv.removed.map(lbl).join(", ")}`);
    if (pv.created?.length) lines.push(`${t("Drawn on")}: ${pv.created.map(lbl).join(", ")}`);
    lines.push(t("This changes the NER's position on the sheets: distances and statuses change - run the analysis again. You can undo it."));
    if (!window.confirm(lines.join("\n"))) {
      return;
    }
    try {
      const r = await api.moveNerOnMap(projectId, current, { asset_id: assetId, x: X, y: Y });
      setLastMove(r);
      const parts = [`${r.name} ${t("moved")}`];
      if (r.removed?.length) parts.push(`${t("left")} ${r.removed.map(pageName).join(", ")}`);
      if (r.created?.length) parts.push(`${t("drawn on")} ${r.created.map(pageName).join(", ")}`);
      if (r.other_books?.length) parts.push(`${t("not moved in book(s)")} ${r.other_books.join(", ")}`);
      setMsg({ text: parts.join(" · "), kind: "ok" });
      await load();
    } catch (e: any) {
      setMsg({ text: e.message, kind: "err" });
    }
  };

  const undo = async () => {
    if (!lastMove) return;
    try {
      const r = await api.undoMapMove(projectId, lastMove.undo_id);
      setMsg({ text: `${r.name} ${t("is back where it was")}`, kind: "ok" });
      setLastMove(null);
      await load();
    } catch (e: any) {
      setMsg({ text: e.message, kind: "err" });
    }
  };

  const setKind = async (n: any, critical: boolean) => {
    const el = n.points?.[0]?.element_id;
    if (!el) return;
    try {
      await api.patchElement(projectId, el, {
        kind: critical ? "NER_CRITICAL" : "NER_NONCRITICAL",
      });
      setMsg({ text: `${n.name} — ${critical ? t("NER critical") : t("NER non critical")}`, kind: "ok" });
      await load();
    } catch (e: any) { setMsg({ text: e.message, kind: "err" }); }
  };

  const remove = async (n: any) => {
    const el = n.points?.[0]?.element_id;
    if (!el) return;
    if (!window.confirm(`${t("Delete")} ${n.name}? ${t("The NER leaves the register — every sheet and every book it is drawn on, the NERs list and the analysis. Restore on the NERs screen brings it back.")}`)) {
      return;
    }
    try {
      await api.deleteElement(projectId, el, "ner");
      setSelected(null);
      setMsg({ text: `${n.name} ${t("deleted")}`, kind: "ok" });
      await load();
    } catch (e: any) { setMsg({ text: e.message, kind: "err" }); }
  };

  const exclude = async (page: number, excluded: boolean) => {
    try {
      await api.excludeCompositeSheet(projectId, current, page, excluded);
      await load();
    } catch (e: any) { setMsg({ text: e.message, kind: "err" }); }
  };

  const rebuild = async () => {
    if (!data) return;
    await job.start(() => api.buildComposite(projectId, data.map.drawing_id, [data.map.key]),
      async (j) => {
        if (j.state === "error") { setMsg({ text: j.error, kind: "err" }); return; }
        if (j.state === "done") { setLastMove(null); await load(); }
      });
  };

  const goTo = (X: number, Y: number) => setFocus({ X, Y, n: Date.now() });

  if (err && !data) {
    return (
      <div className="composite-window">
        <div className="banner err" style={{ margin: 20 }}>
          {err}
          <div className="small muted" style={{ marginTop: 8 }}>
            {t("Sign in in the main window, then reload this one.")}
          </div>
        </div>
      </div>
    );
  }
  if (!data) return <div className="composite-window"><div className="muted" style={{ margin: 20 }}>{t("Loading…")}</div></div>;

  const m = data.map;
  const findings: any[] = data.findings || [];
  return (
    <div className="composite-window">
      <div className="composite-top">
        <strong>{t("Composite map")}</strong>
        <span className="muted">{project?.name}</span>
        <select value={current} style={{ width: "auto", minWidth: 260 }}
                onChange={(e) => { setCurrent(Number(e.target.value)); setSelected(null); setLastMove(null); }}>
          {maps.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
        <span className="toggles">
          {([["reach", `${data.limits.general_m} m`], ["photo", `${data.limits.photographer_m} m`],
             ["wifi", t("Wi-Fi")], ["others", "TER / IDF / COW / DIVA"], ["spaces", t("Spaces")],
             ["sheets", t("Sheets")]] as [keyof typeof show, string][]).map(([k, label]) => (
            <label key={k}>
              <input type="checkbox" checked={show[k]} style={{ width: "auto" }}
                     onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
              {label}
            </label>
          ))}
        </span>
        <span style={{ flex: 1 }} />
        <button className="small" onClick={() => void load()}>{t("Reload")}</button>
      </div>
      {msg && (
        <div className={`banner toast ${msg.kind}`} role="status" onClick={() => setMsg(null)}>
          {msg.text}
          {lastMove && msg.kind === "ok" && (
            <button className="small" style={{ marginLeft: 10 }}
                    onClick={(e) => { e.stopPropagation(); void undo(); }}>{t("Undo")}</button>
          )}
        </div>
      )}
      <div className="composite-body">
        <MapView projectId={projectId} data={data} show={show} selected={selected}
                 onSelect={setSelected} onDrop={move} focus={focus} />
        <aside className="composite-side">
          <section>
            <h3>{m.filename} — {m.label}</h3>
            <div className="small muted">
              {m.sheets} {t("sheet(s)")}: {m.confirmed} {t("confirmed")}
              {m.unconfirmed ? ` · ${m.unconfirmed} ${t("not confirmed")}` : ""}
              {m.contradicted ? ` · ${m.contradicted} ${t("contradicted")}` : ""}
              {m.not_aligned ? ` · ${m.not_aligned} ${t("not placed")}` : ""}
              {m.excluded ? ` · ${m.excluded} ${t("left off")}` : ""}
            </div>
            <div className="small muted">
              {t("built")} {m.built_at ? new Date(m.built_at).toLocaleString() : "—"} · {m.built_by}
            </div>
            {m.outdated && (
              <div className="warn-box small" style={{ marginTop: 6 }}>
                {t("The book was replaced after this map was built — build it again.")}
              </div>
            )}
            <p className="small muted">
              {t("Moving a NER here changes where it is drawn on the sheets; the analysis still measures every distance on its own sheet. Drag a NER to move it; click it for the rest.")}
            </p>
            <div className="row">
              <button className="small" disabled={job.busy} onClick={() => void rebuild()}>
                {t("Build this map again")}
              </button>
              {lastMove && <button className="small" onClick={() => void undo()}>{t("Undo the last move")}</button>}
            </div>
            <JobBar job={job.job} onCancel={job.cancel} onDismiss={job.clear} />
          </section>

          {sel && (
            <section className="composite-sel">
              <h3>
                <span className="dot" style={{ background: sel.critical ? KIND_COLOUR.NER_CRITICAL : KIND_COLOUR.NER_NONCRITICAL }} />
                {sel.name}
              </h3>
              <div className="small muted">
                {sel.critical ? t("NER critical") : t("NER non critical")}
                {!sel.classification_confirmed ? ` · ${t("criticality not confirmed")}` : ""}
                {sel.locked ? ` · ${t("locked")}` : ""}
                {sel.spread_m != null ? ` · ${t("drawn on")} ${sel.points.length} ${t("sheet(s)")}` : ""}
              </div>
              {sel.spread_m > 1 && (
                <div className="warn-box small">
                  {t("Its drawings on different sheets are")} {sel.spread_m} m {t("apart on the map.")}
                </div>
              )}
              {sel.other_books?.length > 0 && (
                <div className="small muted">{t("Also drawn in book(s)")} {sel.other_books.join(", ")} — {t("not moved from here.")}</div>
              )}
              <div className="row" style={{ marginTop: 6 }}>
                <button className="small" disabled={sel.locked}
                        onClick={() => void setKind(sel, !sel.critical)}>
                  {sel.critical ? t("Make non critical") : t("Make critical")}
                </button>
                <button className="small danger" disabled={sel.locked}
                        onClick={() => void remove(sel)}>{t("Delete NER")}</button>
              </div>
              <div className="small" style={{ marginTop: 6 }}>
                {t("Open in the Drawing viewer")}:{" "}
                {[...(sel.points || []).map((p: any) => p.page_key), ...(sel.off_map_pages || [])]
                  .filter((k: number, i: number, a: number[]) => a.indexOf(k) === i)
                  .map((k: number) => {
                    const pt = sel.points.find((p: any) => p.page_key === k);
                    return (
                      <button key={k} className="linkish mono" style={{ marginRight: 8 }}
                              onClick={() => openInMainWindow(projectId, k, pt?.x, pt?.y)}>
                        {pageName(k)}
                      </button>
                    );
                  })}
              </div>
            </section>
          )}

          <section>
            <h3>{t("Findings")} ({findings.length})</h3>
            {findings.length === 0 && <div className="small muted">{t("Nothing found: every NER drawn on several sheets lands in one place, and no two NERs share a spot.")}</div>}
            <ul className="composite-list">
              {findings.map((f, i) => {
                const n = ners.find((x) => x.asset_id === f.asset_id);
                return (
                  <li key={i}>
                    <button className="linkish" onClick={() => {
                      setSelected(f.asset_id);
                      if (n?.X != null) goTo(n.X, n.Y);
                    }}>
                      {f.type === "spread" && <>{f.name}: {t("drawn")} {f.distance_m} m {t("apart on two sheets")}</>}
                      {f.type === "close" && <>{f.name} {t("and")} {f.other_name}: {f.distance_m} m {t("apart — the same NER under two names?")}</>}
                      {f.type === "off_map" && <>{f.name}: {t("drawn only on sheets left off the map")}</>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          <section>
            <h3>{t("Sheets")}</h3>
            <ul className="composite-list">
              {(data.sheets || []).map((s: any) => (
                <li key={s.page} title={s.why || ""}>
                  <span className="dot" style={{ background: STATE_COLOUR[s.state] || "#777" }} />
                  <button className="linkish mono" onClick={() => {
                    if (s.rect) goTo((s.rect[0] + s.rect[2]) / 2, (s.rect[1] + s.rect[3]) / 2);
                  }}>{s.sheet_number || pageName(s.key)}</button>{" "}
                  <span className="small muted">
                    {t(STATE_LABEL[s.state] || s.state)}
                    {s.excluded ? ` · ${t("left off")}` : ""}
                  </span>
                  <span style={{ float: "right" }}>
                    <button className="small" onClick={() => openInMainWindow(projectId, s.key)}>
                      {t("Open")}
                    </button>{" "}
                    {s.state !== "not_aligned" && (
                      <button className="small" onClick={() => void exclude(s.page, !s.excluded)}>
                        {s.excluded ? t("Put back") : t("Leave off")}
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
            <p className="small muted">
              {t("Blue: confirmed by two measurements or by a neighbouring sheet. Orange: placed, not confirmed — check it against its neighbours. Red: the spaces it shares with a neighbour do not line up. A sheet left off is not drawn and its NERs are not shown.")}
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The map itself
// ---------------------------------------------------------------------------

interface View { s: number; ox: number; oy: number }

function MapView({ projectId, data, show, selected, onSelect, onDrop, focus }: {
  projectId: number; data: any; show: Record<string, boolean>; selected: number | null;
  onSelect: (id: number | null) => void; onDrop: (assetId: number, X: number, Y: number) => void;
  focus: { X: number; Y: number; n: number } | null;
}) {
  const wrap = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [view, setView] = useState<View | null>(null);
  const drag = useRef<{ kind: "pan" | "ner"; x: number; y: number; v: View; asset?: number;
                        moved: boolean } | null>(null);
  const [ghost, setGhost] = useState<{ asset: number; X: number; Y: number } | null>(null);
  const m = data.map;

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Fit the level when a map is opened (not after every reload).
  const fitted = useRef<number | null>(null);
  useEffect(() => {
    if (!m.width || fitted.current === m.id || size.w < 50) return;
    const s = Math.min(size.w / m.width, size.h / m.height) * 0.95;
    setView({ s, ox: (size.w - m.width * s) / 2, oy: (size.h - m.height * s) / 2 });
    fitted.current = m.id;
  }, [m.id, m.width, m.height, size.w, size.h]);

  useEffect(() => {
    if (!focus || !view) return;
    const s = Math.max(view.s, 0.25);
    setView({ s, ox: size.w / 2 - focus.X * s, oy: size.h / 2 - focus.Y * s });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.n]);

  const toMap = (cx: number, cy: number, v: View) => {
    const r = wrap.current!.getBoundingClientRect();
    return { X: (cx - r.left - v.ox) / v.s, Y: (cy - r.top - v.oy) / v.s };
  };

  const onWheel = (e: React.WheelEvent) => {
    if (!view) return;
    const f = e.deltaY < 0 ? 1.2 : 1 / 1.2;
    const s = Math.min(8, Math.max(0.005, view.s * f));
    const r = wrap.current!.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    setView({ s, ox: px - (px - view.ox) * (s / view.s), oy: py - (py - view.oy) * (s / view.s) });
  };

  const down = (e: React.PointerEvent, asset?: number, locked?: boolean) => {
    if (!view || e.button !== 0) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { kind: asset != null && !locked ? "ner" : "pan", x: e.clientX, y: e.clientY,
                     v: view, asset, moved: false };
    if (asset != null) onSelect(asset);
  };
  const moveP = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
    if (d.kind === "pan") setView({ ...d.v, ox: d.v.ox + dx, oy: d.v.oy + dy });
    else if (d.moved && d.asset != null) {
      const p = toMap(e.clientX, e.clientY, d.v);
      setGhost({ asset: d.asset, X: p.X, Y: p.Y });
    }
  };
  const up = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.kind === "ner" && d.moved && d.asset != null) {
      const p = toMap(e.clientX, e.clientY, d.v);
      setGhost(null);
      onDrop(d.asset, p.X, p.Y);
    } else if (d.kind === "pan" && !d.moved && d.asset == null) {
      onSelect(null);
    }
  };

  const tiles = useMemo(() => {
    if (!view || !m.width) return [];
    const out: { key: string; url: string; x: number; y: number; w: number }[] = [];
    const layer = (z: number) => {
      const ts = 2 ** z / 64;
      const span = m.tile_px / ts;
      const x0 = Math.max(0, Math.floor(-view.ox / view.s / span));
      const y0 = Math.max(0, Math.floor(-view.oy / view.s / span));
      const x1 = Math.min(Math.floor(m.width / span), Math.floor((size.w - view.ox) / view.s / span));
      const y1 = Math.min(Math.floor(m.height / span), Math.floor((size.h - view.oy) / view.s / span));
      if ((x1 - x0 + 1) * (y1 - y0 + 1) > 120) return;
      for (let tx = x0; tx <= x1; tx++) {
        for (let ty = y0; ty <= y1; ty++) {
          out.push({
            key: `${z}/${tx}/${ty}`,
            url: api.compositeTileUrl(projectId, m.id, z, tx, ty, m.tile_version),
            x: tx * span * view.s + view.ox, y: ty * span * view.s + view.oy, w: span * view.s,
          });
        }
      }
    };
    // Crisp tiles at the zoom shown, over a coarse layer that fills in first.
    const z = Math.max(0, Math.min(m.zmax, Math.ceil(Math.log2(view.s * 64 * (window.devicePixelRatio || 1)))));
    if (z >= 3) layer(Math.max(0, z - 3));
    layer(z);
    return out;
  }, [view, m.id, m.width, m.height, m.tile_px, m.tile_version, m.zmax, size.w, size.h, projectId]);

  if (!view) return <div className="composite-map" ref={wrap} />;
  const s = view.s;
  const px = (n: number) => n / s;                        // n screen pixels in map points
  const rGen = data.limits.general_m / m.mpu;
  const rPho = data.limits.photographer_m / m.mpu;
  const labels = s > 0.04;

  return (
    <div className="composite-map" ref={wrap} onWheel={onWheel}
         onPointerDown={(e) => down(e)} onPointerMove={moveP} onPointerUp={up}>
      {/* The paper clips the tiles: the last row and column of tiles run
          past the edge of the map. */}
      <div className="composite-paper" style={{
        left: view.ox, top: view.oy, width: m.width * s, height: m.height * s }}>
        {tiles.map((tl) => (
          <img key={tl.key} src={tl.url} alt="" draggable={false} className="composite-tile"
               style={{ left: tl.x - view.ox, top: tl.y - view.oy, width: tl.w, height: tl.w }} />
        ))}
      </div>
      <svg className="composite-svg" width={size.w} height={size.h}>
        <g transform={`translate(${view.ox},${view.oy}) scale(${s})`}>
          {show.sheets && (data.sheets || []).filter((x: any) => x.rect && !x.excluded).map((x: any) => (
            <g key={x.page}>
              <rect x={x.rect[0]} y={x.rect[1]} width={x.rect[2] - x.rect[0]} height={x.rect[3] - x.rect[1]}
                    fill="none" stroke={STATE_COLOUR[x.state]} strokeWidth={1.5}
                    strokeDasharray="8 5" vectorEffect="non-scaling-stroke" />
              {labels && (
                <text x={x.rect[0] + px(6)} y={x.rect[1] + px(16)} fontSize={px(12)}
                      fill={STATE_COLOUR[x.state]} className="composite-text">{x.sheet_number}</text>
              )}
            </g>
          ))}
          {(show.reach || show.photo) && (data.ners || []).filter((n: any) => n.X != null).map((n: any) => {
            const col = n.critical ? KIND_COLOUR.NER_CRITICAL : KIND_COLOUR.NER_NONCRITICAL;
            const at = ghost?.asset === n.asset_id ? ghost : n;
            return (
              <g key={`r${n.asset_id}`} opacity={selected == null || selected === n.asset_id ? 0.85 : 0.35}>
                {show.reach && <circle cx={at.X} cy={at.Y} r={rGen} fill={col} fillOpacity={0.04}
                                       stroke={col} strokeWidth={1.5} strokeDasharray="10 7"
                                       vectorEffect="non-scaling-stroke" />}
                {show.photo && <circle cx={at.X} cy={at.Y} r={rPho} fill="none" stroke={col}
                                       strokeWidth={1} strokeDasharray="3 5"
                                       vectorEffect="non-scaling-stroke" />}
              </g>
            );
          })}
          {show.spaces && s > 0.15 && (data.spaces || []).map((sp: any, i: number) => (
            <text key={`s${i}`} x={sp.X} y={sp.Y} fontSize={px(10)} fill="#334"
                  className="composite-text">{sp.code || sp.name}</text>
          ))}
          {show.others && (data.others || []).map((o: any) => (
            <g key={`o${o.id}`}>
              <rect x={o.X - px(5)} y={o.Y - px(5)} width={px(10)} height={px(10)}
                    fill={KIND_COLOUR[o.kind] || "#777"} stroke="#000" strokeWidth={0.8}
                    vectorEffect="non-scaling-stroke" />
              {labels && <text x={o.X + px(8)} y={o.Y - px(6)} fontSize={px(11)} fill="#222"
                               className="composite-text">{o.label}</text>}
            </g>
          ))}
          {show.wifi && (data.wifi || []).map((w: any) => (
            <circle key={`w${w.id}`} cx={w.X} cy={w.Y} r={px(4)} fill={KIND_COLOUR.WIRELESS}
                    stroke="#003" strokeWidth={0.6} vectorEffect="non-scaling-stroke">
              <title>{w.label}</title>
            </circle>
          ))}
          {(data.ners || []).filter((n: any) => n.X != null).map((n: any) => {
            const col = n.critical ? KIND_COLOUR.NER_CRITICAL : KIND_COLOUR.NER_NONCRITICAL;
            const at = ghost?.asset === n.asset_id ? ghost : n;
            const spread = n.spread_m > 1 && ghost?.asset !== n.asset_id;
            return (
              <g key={`n${n.asset_id}`} style={{ cursor: n.locked ? "pointer" : "grab" }}
                 onPointerDown={(e) => down(e, n.asset_id, n.locked)}>
                {spread && n.points.map((p: any, i: number) => (
                  <g key={i}>
                    <line x1={n.X} y1={n.Y} x2={p.X} y2={p.Y} stroke={col} strokeWidth={1.5}
                          strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
                    <circle cx={p.X} cy={p.Y} r={px(5)} fill="#fff" stroke={col} strokeWidth={2}
                            vectorEffect="non-scaling-stroke" />
                  </g>
                ))}
                {selected === n.asset_id && (
                  <circle cx={at.X} cy={at.Y} r={px(14)} fill="none" stroke="#4a8cff"
                          strokeWidth={3} vectorEffect="non-scaling-stroke" />
                )}
                <circle cx={at.X} cy={at.Y} r={px(8)} fill={col} stroke="#000" strokeWidth={1.2}
                        vectorEffect="non-scaling-stroke" />
                {n.locked && <circle cx={at.X} cy={at.Y} r={px(3)} fill="#000" />}
                <text x={at.X + px(11)} y={at.Y - px(9)} fontSize={px(13)} fontWeight={700}
                      fill="#000" className="composite-text halo">{n.name}</text>
                <title>{n.name}</title>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="composite-scale small">
        {(() => {
          // A scale bar of a round length about 120 px long.
          const metres = (120 / s) * m.mpu;
          const nice = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((v) => v >= metres / 2) || 1000;
          return (<><div style={{ width: (nice / m.mpu) * s }} className="bar" /> {nice} m</>);
        })()}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The card on the Reports screen
// ---------------------------------------------------------------------------

export function CompositeCard({ ctx }: { ctx: Ctx }) {
  const p = ctx.project;
  const [books, setBooks] = useState<any[]>([]);
  const job = useJob();
  const load = useCallback(async () => {
    if (!p) return;
    try { setBooks((await api.compositePlan(p.id)).books || []); }
    catch (e: any) { ctx.notify(e.message, "err"); }
  }, [p?.id]);
  useEffect(() => { void load(); }, [load]);
  if (!p) return null;

  const build = async (drawingId: number, groups?: string[]) => {
    await job.start(() => api.buildComposite(p.id, drawingId, groups), async (j) => {
      if (j.state === "error") { ctx.notify(j.error, "err"); return; }
      if (j.state === "done") {
        ctx.notify(`${t("Composite map built")}: ${(j.result?.maps || []).length} ${t("map(s)")}`);
        await load();
      }
    });
  };
  const del = async (mapId: number) => {
    if (!window.confirm(t("Delete this composite map? Nothing on the sheets changes; build it again whenever you want."))) return;
    try { await api.deleteComposite(p.id, mapId); await load(); }
    catch (e: any) { ctx.notify(e.message, "err"); }
  };

  return (
    <div className="card">
      <h2>{t("Composite map")}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {t("The detail sheets of one level of one book laid on one map — never two series, never the key plan — with every NER, its reach and the Wi-Fi points already worked on the sheets. Built only when you ask for it, opened in a window of its own. On it you can move, delete and reclassify NERs; the analysis still measures every distance on its own sheet.")}
      </p>
      <JobBar job={job.job} onCancel={job.cancel} onDismiss={job.clear} />
      {books.map((b) => (
        <div key={b.drawing_id} style={{ marginTop: 10 }}>
          <div className="row" style={{ alignItems: "center" }}>
            <strong className="mono">{b.filename}</strong>
            <button className="small" disabled={job.busy || !b.groups.some((g: any) => g.sheet_count > 1)}
                    onClick={() => void build(b.drawing_id)}>
              {b.groups.some((g: any) => g.map) ? t("Build the maps of this book again") : t("Build the maps of this book")}
            </button>
          </div>
          <ul className="composite-list" style={{ marginTop: 6 }}>
            {b.groups.map((g: any) => (
              <li key={g.key}>
                <span className="mono">{g.label}</span>{" "}
                <span className="small muted">
                  {g.sheet_count} {t("sheet(s)")}
                  {g.no_scale?.length ? ` · ${g.no_scale.length} ${t("without a scale, left out")}` : ""}
                </span>
                {g.map ? (
                  <span style={{ float: "right" }}>
                    <span className="small muted" style={{ marginRight: 8 }}>
                      {g.map.confirmed}/{g.map.sheets} {t("confirmed")}
                      {g.map.outdated ? ` · ${t("book replaced — build again")}` : ""}
                    </span>
                    {g.map.has_picture && (
                      <button className="small primary" onClick={() => openCompositeWindow(p.id, g.map.id)}>
                        {t("Open")} ↗
                      </button>
                    )}{" "}
                    <button className="small" onClick={() => void del(g.map.id)}>{t("Delete")}</button>
                  </span>
                ) : g.sheet_count > 1 ? (
                  <span style={{ float: "right" }}>
                    <button className="small" disabled={job.busy}
                            onClick={() => void build(b.drawing_id, [g.key])}>{t("Build")}</button>
                  </span>
                ) : (
                  <span className="small muted" style={{ float: "right" }}>{t("one sheet — nothing to lay out")}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
