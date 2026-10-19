/**
 * Keep one broken panel from taking the whole application with it.
 *
 * React unmounts the entire tree when a render throws, and with nothing to
 * catch it the result is a black screen: no message, no menu, no way back. It
 * reads as a freeze, which sends you looking for a hung server instead of the
 * one line that actually failed. That is what happened on the Exceptions
 * screen, where a button rendered a background job's ``{job_id}`` as though it
 * were an analysis result and mapped over an ``exceptions`` array that was not
 * there.
 *
 * The fix for that particular line is in the panel. This is the guard that
 * makes the *next* one survivable: the failing panel is replaced by what went
 * wrong and a way to carry on, and the shell around it — the project, the menu,
 * the other screens — stays up.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../lib/i18n";

interface Props {
  children: ReactNode;
  /** Changing this resets the boundary — used to clear the error on navigation. */
  resetKey?: unknown;
}

interface State {
  error: Error | null;
  stack: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, stack: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The browser console is where a developer will look; the panel below is
    // where the user is already looking.
    console.error("[NER] panel failed to render", error, info.componentStack);
    this.setState({ stack: info.componentStack || "" });
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null, stack: "" });
    }
  }

  render() {
    const { error, stack } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="card">
        <h2 style={{ color: "var(--bad)" }}>{t("This screen could not be drawn")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("The fault is in the screen, not in your data — nothing was changed. Switching to another step or reloading will bring the application back.")}
        </p>
        <pre className="small" style={{
          whiteSpace: "pre-wrap", background: "rgba(180,60,60,0.08)",
          border: "1px solid rgba(180,60,60,0.35)", borderRadius: 6, padding: 10,
        }}>{String(error?.message || error)}</pre>
        <div className="row">
          <button className="primary" onClick={() => this.setState({ error: null, stack: "" })}>
            {t("Try this screen again")}
          </button>
          <button onClick={() => window.location.reload()}>{t("Reload the application")}</button>
        </div>
        {stack && (
          <details style={{ marginTop: 10 }}>
            <summary className="small muted">{t("Technical detail")}</summary>
            <pre className="small muted" style={{ whiteSpace: "pre-wrap" }}>{stack}</pre>
          </details>
        )}
      </div>
    );
  }
}
