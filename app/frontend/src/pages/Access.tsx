/**
 * Sign-in, the data-handling notice, and user administration.
 *
 * The notice is shown before anyone signs in, on purpose. It states what the
 * application does with the data — the bind address, the file it lives in, the
 * fact that nothing leaves the machine — and what it does *not* protect. A
 * notice that only lists reassurances manufactures confidence; the limits are
 * the half that makes the rest believable.
 */

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { getLang, onLangChange, setLang, t } from "../lib/i18n";
import { useSort } from "../components/useSort";

export interface Account {
  id: number;
  username: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
}

// ---------------------------------------------------------------------------

export function DataNotice({ notice, compact }: { notice: any; compact?: boolean }) {
  if (!notice) return null;
  return (
    <div className="card" style={{ borderColor: "var(--line)" }}>
      <h3 style={{ marginTop: 0 }}>{notice.headline}</h3>
      <ul className="small" style={{ margin: "6px 0", paddingLeft: 18 }}>
        {notice.statements.map((s: string, i: number) => (
          <li key={i} style={{ marginBottom: 3 }}>{s}</li>
        ))}
      </ul>
      <h4 className="small muted" style={{ margin: "12px 0 4px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {t("What this does not protect")}
      </h4>
      <ul className="small" style={{ margin: "6px 0", paddingLeft: 18, color: "var(--warn)" }}>
        {notice.limits.map((s: string, i: number) => (
          <li key={i} style={{ marginBottom: 3 }}>{s}</li>
        ))}
      </ul>
      {!compact && (
        <p className="small muted" style={{ marginBottom: 0 }}>{notice.release}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

export function LoginGate({ state, onSignedIn }: { state: any; onSignedIn: () => void }) {
  const bootstrapping = !!state?.needs_bootstrap;
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);
  // The gate renders before App mounts its own subscription, so it carries one.
  const [, bumpLang] = useState(0);
  useEffect(() => onLangChange(() => bumpLang((n) => n + 1)), []);

  const submit = async () => {
    setErr(null);
    if (bootstrapping && password !== confirm) {
      setErr(t("The two passwords do not match."));
      return;
    }
    setBusy(true);
    try {
      if (bootstrapping) {
        await api.bootstrap({ username, password, display_name: displayName });
      } else {
        await api.login({ username, password });
      }
      onSignedIn();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", overflowY: "auto" }}>
      <div style={{ maxWidth: 880, margin: "0 auto", padding: "56px 24px 64px" }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>{t("NER Spatial Coverage Analyzer")}</h1>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 26 }}>
          <div className="muted small">
            {t("TER / NER placement and coverage study")}
            {" · "}{t("version")} {state?.version || __APP_VERSION__}
          </div>
          <span style={{ flex: 1 }} />
          <button
            className="small"
            title={t("Interface language. Project data, names and exports are never translated.")}
            onClick={() => setLang(getLang() === "en" ? "pt" : "en")}
          >
            {getLang() === "en" ? "PT-BR" : "EN"}
          </button>
        </div>

        <div className="card">
          <h2>{t(bootstrapping ? "Create the first account" : "Sign in")}</h2>
          {bootstrapping && (
            <p className="muted small" style={{ marginTop: 0 }}>
              {t("This installation has no accounts yet. The first one is an administrator and can create the others. Any projects already on this machine will be transferred to it.")}
            </p>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <div className="grid c2">
              <div>
                <label>{t("Username")}</label>
                <input
                  value={username}
                  autoFocus
                  autoComplete="username"
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="jsmith"
                />
              </div>
              {bootstrapping && (
                <div>
                  <label>{t("Display name")}</label>
                  <input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="J. Smith"
                  />
                </div>
              )}
              <div>
                <label>{t("Password")}</label>
                <input
                  type="password"
                  value={password}
                  autoComplete={bootstrapping ? "new-password" : "current-password"}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {bootstrapping && (
                <div>
                  <label>{t("Password again")}</label>
                  <input
                    type="password"
                    value={confirm}
                    autoComplete="new-password"
                    onChange={(e) => setConfirm(e.target.value)}
                  />
                </div>
              )}
            </div>
            {bootstrapping && (
              <p className="small muted" style={{ marginBottom: 6 }}>
                {t("At least 10 characters. A phrase you can remember beats a short scramble — length is what resists guessing.")}
              </p>
            )}
            {err && <div className="banner err" style={{ marginTop: 10 }}>{err}</div>}
            <div className="row" style={{ marginTop: 12 }}>
              <button
                className="primary"
                type="submit"
                disabled={busy || !username.trim() || !password}
              >
                {t(bootstrapping ? "Create account and sign in" : "Sign in")}
              </button>
              {!bootstrapping && (
                <button type="button" className="small" onClick={() => setForgot((v) => !v)}>
                  {t("Forgot your password?")}
                </button>
              )}
            </div>
          </form>
          {/* The way back in (4.0.0). No e-mail and no network: the app runs
              on this computer only, so the reset is a program on it. */}
          {forgot && !bootstrapping && (
            <div className="banner" style={{ marginTop: 12 }}>
              <p className="small" style={{ margin: "0 0 6px" }}>
                {t("Ask an administrator of this installation: Account & security → Reset password. You choose a new password at the next sign-in.")}
              </p>
              <p className="small" style={{ margin: "0 0 6px" }}>
                {t("No administrator, or you are the administrator? On the computer where the app is installed, open the app's folder and run the reset tool. It lists the accounts, asks which one and the new password twice, and works with the app running:")}
              </p>
              <p className="small mono" style={{ margin: "0 0 4px" }}>
                Windows: %LOCALAPPDATA%\Programs\ner-analyzer\reset-password.bat
              </p>
              <p className="small mono" style={{ margin: 0 }}>
                macOS: ~/Applications/ner-analyzer/mac/reset-password.command
              </p>
            </div>
          )}
        </div>

        <DataNotice notice={state?.notice} />

        <p className="small muted" style={{ marginTop: 18 }}>{state?.disclaimer}</p>
        {state?.copyright && (
          <p className="small muted" style={{ marginTop: 6 }}>{state.copyright}</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function AccountPanel({ user, notice, onChanged, notify, projectId }: any) {
  const su = useSort<any>();
  const sup = useSort<any>();
  const sau = useSort<any>();
  const saa = useSort<any>();
  //: The audit log moved here from the Reports screen. It is not a report —
  //  nobody sends it to the drawing team — it is the record of who changed what
  //  and why, which is an administration question and belongs beside the
  //  accounts that answer "who". It is scoped to the open project; with no
  //  project open there is nothing to show.
  const [audit, setAudit] = useState<any[]>([]);
  const [accountAudit, setAccountAudit] = useState<any[]>([]);
  const [users, setUsers] = useState<Account[]>([]);
  const [busy, setBusy] = useState(false);
  const [impact, setImpact] = useState<any>(null);
  const [reason, setReason] = useState("");
  const [confirmName, setConfirmName] = useState("");

  const [nu, setNu] = useState({ username: "", display_name: "", password: "", is_admin: false });
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");

  const load = async () => {
    if (!user?.is_admin) return;
    try {
      setUsers((await api.adminUsers()).users);
    } catch (e: any) {
      notify(e.message, "err");
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  const act = async (fn: () => Promise<any>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      await load();
      await onChanged();
      if (ok) notify(ok);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card">
        <h2>{t("Your account")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("Signed in as")} <strong>{user.display_name || user.username}</strong> (
          <span className="mono">{user.username}</span>
          {user.is_admin ? ` · ${t("administrator")}` : ""}). {t("Every decision you record is written to the audit log under this name.")}
        </p>
        {user.must_change_password && (
          <div className="banner err">
            {t("This password was set by an administrator. Change it now.")}
          </div>
        )}
        <div className="row">
          <div>
            <label>{t("Current password")}</label>
            <input type="password" value={cur} autoComplete="current-password"
                   onChange={(e) => setCur(e.target.value)} />
          </div>
          <div>
            <label>{t("New password")}</label>
            <input type="password" value={next} autoComplete="new-password"
                   onChange={(e) => setNext(e.target.value)} />
          </div>
          <button
            disabled={busy || !cur || !next}
            onClick={() =>
              act(async () => {
                await api.changePassword({ current_password: cur, new_password: next });
                setCur(""); setNext("");
              }, t("Password changed."))
            }
          >
            {t("Change password")}
          </button>
        </div>
      </div>

      {user.is_admin && (
        <>
          <div className="card">
            <h2>{t("Add an account")}</h2>
            <div className="row">
              <div>
                <label>{t("Username")}</label>
                <input value={nu.username}
                       onChange={(e) => setNu({ ...nu, username: e.target.value })} />
              </div>
              <div>
                <label>{t("Display name")}</label>
                <input value={nu.display_name}
                       onChange={(e) => setNu({ ...nu, display_name: e.target.value })} />
              </div>
              <div>
                <label>{t("Initial password")}</label>
                <input value={nu.password}
                       onChange={(e) => setNu({ ...nu, password: e.target.value })} />
              </div>
              <label style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                <input type="checkbox" style={{ width: "auto" }} checked={nu.is_admin}
                       onChange={(e) => setNu({ ...nu, is_admin: e.target.checked })} />
                <span>{t("administrator")}</span>
              </label>
              <button
                className="primary"
                disabled={busy || !nu.username.trim() || !nu.password}
                onClick={() =>
                  act(async () => {
                    await api.createAccount({ ...nu, must_change_password: true });
                    setNu({ username: "", display_name: "", password: "", is_admin: false });
                  }, t("Account created — they must change the password on first use."))
                }
              >
                {t("Create")}
              </button>
            </div>
          </div>

          <div className="card">
            <h2>{t("Accounts")}</h2>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <su.Th k="username">{t("Username")}</su.Th><su.Th k="name" get={(u: any) => u.display_name}>{t("Name")}</su.Th><su.Th k="projects" get={(u: any) => (u.projects || []).join(", ")}>{t("Projects")}</su.Th><su.Th k="last_login" get={(u: any) => u.last_login_at}>{t("Last signed in")}</su.Th>
                    <su.Th k="sessions" get={(u: any) => u.active_sessions}>{t("Sessions")}</su.Th><su.Th k="is_admin">{t("Admin")}</su.Th><su.Th k="is_active">{t("Active")}</su.Th><th />
                  </tr>
                </thead>
                <tbody>
                  {su.apply(users).map((u: any) => (
                    <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.55 }}>
                      <td className="mono">{u.username}</td>
                      <td>{u.display_name}</td>
                      <td className="small muted">
                        {u.projects.length ? u.projects.join(", ") : "—"}
                      </td>
                      <td className="small">
                        {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}
                      </td>
                      <td>{u.active_sessions}</td>
                      <td>
                        <input type="checkbox" style={{ width: "auto" }} checked={u.is_admin}
                               disabled={busy || u.id === user.id}
                               onChange={(e) =>
                                 act(() => api.setAccountAdmin(u.id, e.target.checked))} />
                      </td>
                      <td>
                        <input type="checkbox" style={{ width: "auto" }} checked={u.is_active}
                               disabled={busy || u.id === user.id}
                               onChange={(e) =>
                                 act(() => api.setAccountActive(u.id, e.target.checked))} />
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="small" disabled={busy || u.id === user.id}
                                onClick={() =>
                                  act(async () => {
                                    const pw = prompt(`${t("New password for")} ${u.username}`);
                                    if (!pw) return;
                                    await api.resetAccountPassword(u.id, pw);
                                  }, t("Password reset."))}>
                          {t("Reset password")}
                        </button>{" "}
                        <button className="small danger" disabled={busy || u.id === user.id}
                                onClick={async () => {
                                  try {
                                    setImpact(await api.deletionImpact(u.id));
                                    setReason(""); setConfirmName("");
                                  } catch (e: any) { notify(e.message, "err"); }
                                }}>
                          {t("Delete")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {impact && (
            <div className="card" style={{ borderColor: "var(--bad)" }}>
              <h2 style={{ color: "var(--bad)" }}>{t("Delete")} {impact.username}</h2>
              <p className="small">{impact.note}</p>
              <table>
                <thead>
                  <tr><sup.Th k="name">{t("Project")}</sup.Th><sup.Th k="venue_code">{t("Venue")}</sup.Th><th>{t("Drawings")}</th><sup.Th k="teap_value" get={(p: any) => p.teap_files}>{t("TEAP")}</sup.Th><th>{t("Scenarios")}</th></tr>
                </thead>
                <tbody>
                  {sup.apply(impact.projects).map((p: any) => (
                    <tr key={p.id}>
                      <td>{p.name}</td><td className="mono">{p.venue_code || "—"}</td>
                      <td>{p.drawings}</td><td>{p.teap_files}</td><td>{p.scenarios}</td>
                    </tr>
                  ))}
                  {impact.projects.length === 0 && (
                    <tr><td colSpan={5} className="muted">{t("No projects.")}</td></tr>
                  )}
                </tbody>
              </table>
              <div className="row" style={{ marginTop: 10 }}>
                <div style={{ flex: 2 }}>
                  <label>{t("Reason — recorded in the audit log")}</label>
                  <input value={reason} onChange={(e) => setReason(e.target.value)} />
                </div>
                <div style={{ flex: 1 }}>
                  <label>{t("Type the username to confirm")}: “{impact.username}”</label>
                  <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
                </div>
                <button className="danger"
                        disabled={busy || !reason.trim() || confirmName !== impact.username}
                        onClick={() =>
                          act(async () => {
                            const uid = users.find((x) => x.username === impact.username)!.id;
                            const r = await api.deleteAccount(uid, reason, confirmName);
                            setImpact(null);
                            notify(`${r.username} ${t("deleted with")} ${r.projects_deleted.length} ${t("project(s)")}.`);
                          })}>
                  {t("Delete permanently")}
                </button>
                <button onClick={() => setImpact(null)}>{t("Cancel")}</button>
              </div>
            </div>
          )}
        </>
      )}

      {projectId != null && (
        <div className="card">
          <h2>{t("Audit log")}</h2>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("Every change to this project, with the person who made it and the reason they gave.")}
          </p>
          {audit.length === 0 && (
            <button className="small" onClick={async () => {
              try { setAudit(await api.audit(projectId)); }
              catch (e: any) { notify(e.message, "err"); }
            }}>{t("Load the audit log")}</button>
          )}
          {audit.length > 0 && (
            <div className="scroll" style={{ maxHeight: "50vh" }}>
              <table>
                <thead><tr><sau.Th k="at">{t("When")}</sau.Th><sau.Th k="actor">{t("Actor")}</sau.Th><sau.Th k="action">{t("Action")}</sau.Th><sau.Th k="entity">{t("Entity")}</sau.Th><sau.Th k="justification">{t("Justification")}</sau.Th><sau.Th k="payload" get={(a: any) => JSON.stringify(a.payload || {})}>{t("Payload")}</sau.Th></tr></thead>
                <tbody>
                  {sau.apply(audit).map((a: any, i: number) => (
                    <tr key={i}>
                      <td className="small">{new Date(a.at).toLocaleString()}</td>
                      <td className="small">{a.actor}</td>
                      <td className="mono small">{a.action}</td>
                      <td className="small">{a.entity}{a.entity_id ? ` #${a.entity_id}` : ""}</td>
                      <td className="small muted">{a.justification || "—"}</td>
                      <td className="small mono muted" style={{ maxWidth: 320 }}>
                        {JSON.stringify(a.payload).slice(0, 160)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {user.is_admin && (
        <div className="card">
          <h2>{t("Account events")}</h2>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("Sign-ins, accounts created, blocked, reset and deleted, with the reason given. These are not tied to a project, so they are not in a project's audit log.")}
          </p>
          {accountAudit.length === 0 && (
            <button className="small" onClick={async () => {
              try { setAccountAudit(await api.accountAudit()); }
              catch (e: any) { notify(e.message, "err"); }
            }}>{t("Load the account events")}</button>
          )}
          {accountAudit.length > 0 && (
            <div className="scroll" style={{ maxHeight: "40vh" }}>
              <table>
                <thead><tr><saa.Th k="at">{t("When")}</saa.Th><saa.Th k="actor">{t("Actor")}</saa.Th><saa.Th k="action">{t("Action")}</saa.Th><saa.Th k="entity_id">{t("Account")}</saa.Th><saa.Th k="justification">{t("Justification")}</saa.Th><saa.Th k="payload" get={(a: any) => JSON.stringify(a.payload || {})}>{t("Payload")}</saa.Th></tr></thead>
                <tbody>
                  {saa.apply(accountAudit).map((a: any, i: number) => (
                    <tr key={i}>
                      <td className="small">{new Date(a.at).toLocaleString()}</td>
                      <td className="small">{a.actor}</td>
                      <td className="mono small">{a.action}</td>
                      <td className="small">{a.entity_id ? `#${a.entity_id}` : "—"}</td>
                      <td className="small muted">{a.justification || "—"}</td>
                      <td className="small mono muted" style={{ maxWidth: 320 }}>
                        {JSON.stringify(a.payload).slice(0, 160)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <DataNotice notice={notice} />
    </>
  );
}
