import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, isReachable, onConnection } from "./lib/api";
import { DISCLAIMER } from "./lib/notation";
import {
  DemandPanel,
  ExceptionsPanel,
  MatchingPanel,
  ProjectsPanel,
  ReportsPanel,
  ScalePanel,
  SetupPanel,
} from "./pages/panels";
import { AccountPanel, LoginGate } from "./pages/Access";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { NersPanel } from "./pages/Ners";
import { Viewer } from "./pages/Viewer";
import { getLang, onLangChange, setLang, t } from "./lib/i18n";

export type Tab =
  | "projects" | "setup" | "scale" | "viewer" | "ners"
  | "matching" | "demand" | "exceptions"
  | "reports" | "account";

const TABS: {
  key: Tab;
  label: string;
  step?: string;
  needsProject: boolean;
  /** Not a step in the study — rendered under its own heading so it does not
   *  read as "step 11" and get skipped by anyone following the numbers. */
  aside?: boolean;
}[] = [
  { key: "projects", label: "Projects", needsProject: false },
  { key: "setup", label: "Import", step: "1", needsProject: true },
  { key: "scale", label: "Scale", step: "2", needsProject: true },
  { key: "viewer", label: "Drawing viewer", step: "3", needsProject: true },
  { key: "ners", label: "NERs", step: "4", needsProject: true },
  { key: "matching", label: "TEAP × drawing", step: "5", needsProject: true },
  // "Coverage analysis" was step 7 until 3 Sep 2026. It is part of Demand
  // per space now: the analysis runs there, beside the rows it decides.
  { key: "demand", label: "Demand per space", step: "6", needsProject: true },
  { key: "exceptions", label: "Exceptions", step: "7", needsProject: true },
  { key: "reports", label: "Reports", step: "8", needsProject: true },
  { key: "account", label: "Account & security", needsProject: false, aside: true },
];

export interface Ctx {
  projectId: number | null;
  project: any | null;
  reload: () => Promise<void>;
  setProjectId: (id: number | null) => void;
  go: (t: Tab) => void;
  notify: (msg: string, kind?: "ok" | "err") => void;
  units: string;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("projects");
  // One subscription at the root. Every t() call happens during render, so a
  // single state bump here re-renders the whole tree in the new language —
  // no context to thread through 4,000 lines, and no page reload that would
  // throw away the project you had open.
  const [, bumpLang] = useState(0);
  useEffect(() => onLangChange(() => bumpLang((n) => n + 1)), []);
  const [auth, setAuth] = useState<any>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [project, setProject] = useState<any | null>(null);
  //: The project reopens itself after a reload (2.8.1). Ctrl+Shift+R is what
  //  the manual tells people to press after an update, and until now it also
  //  sent them back to the Projects list.
  const [restoredProject, setRestoredProject] = useState(false);
  //: The menu folds to a narrow rail of step numbers (4.4.0), remembered per
  //  browser — the drawing gets the width back on a laptop screen. Marcelo,
  //  22 Oct 2026: "o menu da esquerda também poderia ser retrátil, para
  //  aumentar a tela de trabalho no mapa".
  const [navOpen, setNavOpen] = useState<boolean>(() => {
    try { return localStorage.getItem("ner.sidebar") !== "closed"; }
    catch { return true; }
  });
  const toggleNav = () => setNavOpen((open) => {
    const next = !open;
    try { localStorage.setItem("ner.sidebar", next ? "open" : "closed"); }
    catch { /* private window */ }
    return next;
  });
  const [msg, setMsg] = useState<{ text: string; kind: "ok" | "err" } | null>(null);

  const reload = useCallback(async () => {
    if (projectId == null) {
      setProject(null);
      return;
    }
    try {
      setProject(await api.getProject(projectId));
    } catch (e: any) {
      setMsg({ text: e.message, kind: "err" });
    }
  }, [projectId]);

  const loadAuth = useCallback(async () => {
    try {
      setAuth(await api.authState());
    } catch {
      // A server that is down is not a session that ended. Keep whatever
      // session the screen had; the reconnect below reloads it when the
      // server answers again. Only a first load with no answer at all shows
      // the sign-in gate, which then says the server is not answering.
      setAuth((a: any) => (a && isReachable() ? a : (a ?? { authenticated: false })));
    } finally {
      setAuthLoaded(true);
    }
  }, []);

  useEffect(() => {
    void loadAuth();
  }, [loadAuth]);

  // The server down — usually the watchdog restarting it. Poll /healthz every
  // five seconds until it answers, then reload the session and the project
  // rather than leaving the person at a sign-in page that refuses them.
  const [serverDown, setServerDown] = useState(false);
  useEffect(() => onConnection((up) => setServerDown(!up)), []);
  useEffect(() => {
    if (!serverDown) return;
    const id = setInterval(async () => {
      if (await api.health()) {
        setServerDown(false);
        await loadAuth();
        await reload();
        setMsg({ text: t("the server is back"), kind: "ok" });
      }
    }, 5000);
    return () => clearInterval(id);
  }, [serverDown, loadAuth, reload]);

  useEffect(() => {
    if (auth?.authenticated) void reload();
  }, [reload, auth?.authenticated]);

  // Reopen the project this browser had open, once, if it still exists and
  // this account can still see it. Silent when it cannot.
  const restoreDone = useRef(false);
  useEffect(() => {
    if (!auth?.authenticated || restoredProject) return;
    setRestoredProject(true);
    let saved: number | null = null;
    try { saved = Number(localStorage.getItem("ner.project")) || null; } catch { saved = null; }
    if (!saved || projectId != null) { restoreDone.current = true; return; }
    api.listProjects().then((list: any[]) => {
      if ((list || []).some((p: any) => p.id === saved)) setProjectId(saved);
    }).catch(() => {}).finally(() => { restoreDone.current = true; });
  }, [auth?.authenticated, restoredProject, projectId]);

  useEffect(() => {
    try {
      // Nothing is forgotten before the saved project had its chance to come
      // back (4.2.0): this ran on the first render, with no project open yet,
      // and erased the key the restore above was about to read — so the
      // project never reopened after a reload.
      if (projectId == null) {
        if (restoreDone.current) localStorage.removeItem("ner.project");
      } else localStorage.setItem("ner.project", String(projectId));
    } catch { /* private window */ }
  }, [projectId]);

  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 6000);
    return () => clearTimeout(t);
  }, [msg]);

  const ctx: Ctx = useMemo(
    () => ({
      projectId,
      project,
      reload,
      setProjectId: (id) => {
        setProjectId(id);
        if (id != null) setTab("setup");
      },
      go: setTab,
      notify: (text, kind = "ok") => setMsg({ text, kind }),
      units: project?.settings?.display_units || "m",
    }),
    [projectId, project, reload],
  );

  if (!authLoaded) return null;
  if (!auth?.authenticated) {
    return (
      <LoginGate
        state={auth}
        onSignedIn={async () => {
          await loadAuth();
          setTab("projects");
        }}
      />
    );
  }

  const scaleReady = !!project?.scale_ready;
  const pendingScale = (project?.pages || []).filter((p: any) => !p.scale_confirmed).length;
  // The server's version is the installation's; this bundle's is what the
  // browser is holding. They differ exactly when the browser cached an older
  // interface after an update — the one case Ctrl+Shift+R exists for.
  const serverVersion: string = auth.version || "";
  const stale = !!serverVersion && serverVersion !== __APP_VERSION__;

  return (
    <div className="app">
      {!navOpen ? (
      <aside className="sidebar rail">
        <button className="rail-toggle" onClick={toggleNav} title={t("Show the menu")}
                aria-label={t("Show the menu")}>»</button>
        <nav className="nav">
          {TABS.map((x) => (
            <button
              key={x.key}
              className={tab === x.key ? "active" : ""}
              disabled={x.needsProject && projectId == null}
              title={t(x.label)}
              onClick={() => setTab(x.key)}
            >
              {x.step ?? (x.aside ? "⚙" : "▤")}
            </button>
          ))}
        </nav>
      </aside>
      ) : (
      <aside className="sidebar">
        <button className="rail-toggle open" onClick={toggleNav} title={t("Hide the menu")}
                aria-label={t("Hide the menu")}>«</button>
        <h1>{t("NER Spatial Coverage Analyzer")}</h1>
        <div className="sub">{t("TER / NER placement and coverage study")}</div>
        <div className="sub version" title={`${t("interface")} ${__APP_VERSION__}`}>
          {t("version")} {serverVersion || __APP_VERSION__}
        </div>
        <nav className="nav">
          {TABS.filter((x) => !x.aside).map((x) => (
            <button
              key={x.key}
              className={tab === x.key ? "active" : ""}
              disabled={x.needsProject && projectId == null}
              onClick={() => setTab(x.key)}
            >
              <span>{t(x.label)}</span>
              {x.step && <span className="step">{x.step}</span>}
            </button>
          ))}

          <div className="navsep">
            {t(auth.user.is_admin ? "Administration" : "Your account")}
          </div>
          {TABS.filter((x) => x.aside).map((x) => (
            <button
              key={x.key}
              className={tab === x.key ? "active" : ""}
              onClick={() => setTab(x.key)}
            >
              <span>{t(auth.user.is_admin ? "Accounts & security" : x.label)}</span>
              {auth.user.is_admin && <span className="step">admin</span>}
            </button>
          ))}
        </nav>
        {auth.copyright && <div className="copyright">{auth.copyright}</div>}
      </aside>
      )}

      <main className="main">
        <div className="topbar">
          <strong>{project ? project.name : t("No project selected")}</strong>
          {project?.venue_code && <span className="muted">{t("venue")} {project.venue_code}</span>}
          {project && (
            <span className="pill" style={{ color: scaleReady ? "var(--ok)" : "var(--warn)" }}>
              {scaleReady ? t("Scale confirmed") : `${pendingScale} ${t("page(s) awaiting scale")}`}
            </span>
          )}
          {project && (
            <span className="muted small">
              {t("limits")} {project.settings.general_limit_m} m / {project.settings.photographer_limit_m} m
              · {t("slack")} {project.settings.routing_slack_factor}×
            </span>
          )}
          <span style={{ flex: 1 }} />
          {serverDown && (
            <span className="pill" style={{ color: "var(--bad)" }}>
              {t("server not answering — reconnecting")}
            </span>
          )}
          {stale && (
            <span className="pill" style={{ color: "var(--warn)" }}
                  title={`${t("interface")} ${__APP_VERSION__} · ${t("server")} ${serverVersion}`}>
              {t("the application was updated — press Ctrl+Shift+R to load the current interface")}
            </span>
          )}
          <button
            className="small"
            title={t("Your account, password and — for administrators — the other accounts")}
            onClick={() => setTab("account")}
          >
            {auth.user.display_name || auth.user.username}
            {auth.user.is_admin ? " · admin" : ""}
            {auth.user.must_change_password ? " ·" : ""}
            {auth.user.must_change_password && (
              <span style={{ color: "var(--warn)" }}> {t("change your password")}</span>
            )}
          </button>
          <button
            className="small"
            title={t("Interface language. Project data, names and exports are never translated.")}
            onClick={() => setLang(getLang() === "en" ? "pt" : "en")}
          >
            {getLang() === "en" ? "PT-BR" : "EN"}
          </button>
          <button
            className="small"
            onClick={async () => {
              await api.logout();
              setProjectId(null);
              await loadAuth();
            }}
          >
            {t("Sign out")}
          </button>
        </div>

        <div className={tab === "viewer" ? "content no-pad" : "content"}>
          {msg && <div className={`banner ${msg.kind === "err" ? "err" : "ok"}`}>{msg.text}</div>}
          {/* One panel failing must not blank the application. Keyed on the tab
              so moving to another step clears the failure. */}
          <ErrorBoundary resetKey={tab}>
          {tab === "projects" && <ProjectsPanel ctx={ctx} />}
          {tab === "setup" && <SetupPanel ctx={ctx} />}
          {tab === "scale" && <ScalePanel ctx={ctx} />}
          {tab === "viewer" && <Viewer ctx={ctx} />}
          {tab === "ners" && <NersPanel ctx={ctx} />}
          {tab === "matching" && <MatchingPanel ctx={ctx} />}
          {tab === "demand" && <DemandPanel ctx={ctx} />}
          {tab === "exceptions" && <ExceptionsPanel ctx={ctx} />}
          {tab === "reports" && <ReportsPanel ctx={ctx} />}
          {tab === "account" && (
            <AccountPanel
              user={auth.user}
              notice={auth.notice}
              onChanged={loadAuth}
              notify={ctx.notify}
              projectId={projectId}
            />
          )}
          </ErrorBoundary>
        </div>

        <div className="disclaimer">{t(DISCLAIMER)}</div>
      </main>
    </div>
  );
}
