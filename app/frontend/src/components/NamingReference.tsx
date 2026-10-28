import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { getLang, t } from "../lib/i18n";

/**
 * The *Naming* side panel — a reference table to read beside the register
 * while renaming (2.14.0). Nothing reads it back: the name a person gives a
 * NER is the name.
 *
 * Since 4.3.0 the table itself is not part of the application. It is a
 * client's document (a naming structure an organising committee hands its
 * venue teams), so it is read from the server's private reference folder,
 * which a public package leaves out. Without it the panel states the
 * application's own naming rule and nothing else.
 */

type Row = [string, string];
type Reference = {
  available: boolean;
  title?: string;
  intro?: string;
  principles?: string[];
  groups?: { heading: string; rows: Row[] }[];
  source?: string;
  pt?: Record<string, string>;
};

function Table({ rows }: { rows: Row[] }) {
  return (
    <table className="naming-ref">
      <thead><tr><th>{t("NER naming")}</th><th>{t("Location / space")}</th></tr></thead>
      <tbody>
        {rows.map(([name, where]) => (
          <tr key={name}><td className="mono">{name}</td><td>{where}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export function NamingReference() {
  const [ref, setRef] = useState<Reference | null>(null);
  useEffect(() => {
    api.namingReference().then(setRef).catch(() => setRef({ available: false }));
  }, []);
  // The reference file brings its own Portuguese; anything it does not
  // translate is shown as written.
  const tr = (s?: string) => (s && getLang() === "pt" && ref?.pt?.[s]) || s || "";

  const rule = (
    <p className="small muted">
      {t("The app names every NER it creates in sequence: NERc_01.1, NERc_02.1 … for critical rooms and NER_20.1, NER_21.1 … for non-critical ones. Rename each one as your project's naming document says; the name you give a NER is the name.")}
    </p>
  );
  if (ref === null) return <div className="naming-reference"><p className="small muted">{t("Loading…")}</p></div>;
  if (!ref.available) {
    return (
      <div className="naming-reference">
        <h2 style={{ fontSize: 14, marginTop: 0 }}>{t("NER naming")}</h2>
        {rule}
        <p className="small muted">
          {t("No naming reference is bundled with this copy. A team can add its own naming document to the package's private reference folder; it is shown here for reference only.")}
        </p>
      </div>
    );
  }
  return (
    <div className="naming-reference">
      <h2 style={{ fontSize: 14, marginTop: 0 }}>{tr(ref.title) || t("NER naming")}</h2>
      {ref.intro ? <p className="small muted">{tr(ref.intro)}</p> : rule}
      {!!ref.principles?.length && (
        <>
          <h3>{t("Principles")}</h3>
          <ul className="small">
            {ref.principles.map((p) => <li key={p}>{tr(p)}</li>)}
          </ul>
        </>
      )}
      {(ref.groups || []).map((g) => (
        <div key={g.heading}>
          <h3>{tr(g.heading)}</h3>
          <Table rows={g.rows} />
        </div>
      ))}
      {ref.source && <p className="small muted">{tr(ref.source)}</p>}
    </div>
  );
}
