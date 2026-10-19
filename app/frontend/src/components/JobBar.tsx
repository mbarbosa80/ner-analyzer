import type { JobState } from "../lib/useJob";
import { t } from "../lib/i18n";

/**
 * Progress for a long operation, with the stage in words and a cancel button.
 *
 * The stage text matters as much as the bar: "reading page 12 of 34" tells the
 * user the tool is working and roughly how long is left, which a spinner never
 * does. When a job fails the error stays on screen instead of vanishing.
 */
export function JobBar({ job, onCancel, onDismiss }: {
  job: JobState | null;
  onCancel?: () => void;
  onDismiss?: () => void;
}) {
  if (!job) return null;

  const pct = Math.round((job.progress || 0) * 100);
  const tone =
    job.state === "error" ? "err" : job.state === "done" ? "ok" : "";

  return (
    <div className={`banner ${tone}`} style={{ display: "grid", gap: 7 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <strong style={{ flex: "0 0 auto" }}>
          {job.state === "error" ? t("Failed")
            : job.state === "cancelled" ? t("Cancelled")
            : job.state === "done" ? t("Finished")
            : t("Working")}
        </strong>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
          {/* The server's last stage word is "finished" once it is done —
              beside "Finished" it read as a stutter. */}
          {job.error || (job.stage && job.stage.toLowerCase() !== job.state ? job.stage : "") || "…"}
        </span>
        {job.running && <span className="mono">{pct}%</span>}
        {job.running && onCancel && (
          <button className="small danger" onClick={onCancel}>{t("Cancel")}</button>
        )}
        {!job.running && onDismiss && (
          <button className="small" onClick={onDismiss}>{t("Dismiss")}</button>
        )}
      </div>
      {job.running && (
        <div style={{ height: 6, background: "#0d1017", borderRadius: 4, overflow: "hidden" }}>
          <div
            style={{
              width: `${Math.max(3, pct)}%`,
              height: "100%",
              background: "var(--accent)",
              transition: "width 0.35s ease",
            }}
          />
        </div>
      )}
    </div>
  );
}
