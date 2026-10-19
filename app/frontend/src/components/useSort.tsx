/**
 * Click a column heading to sort a table by it.
 *
 * One primitive for every table in the application, so the behaviour is the
 * same wherever you meet it and there is one place to fix when it is wrong.
 *
 * Three decisions worth stating, because each is easy to get subtly wrong and
 * each was chosen against a plausible alternative:
 *
 * **Three states, not two.** Click cycles ascending → descending → *back to the
 * original order*. Several of these lists are deliberately ordered: the TEAP
 * worklist runs by port demand so effort goes where the demand is, the register
 * runs by code, the audit log runs by time. A two-state toggle would let you
 * destroy that ordering with no way back short of reloading the screen.
 *
 * **Blanks sort last in both directions.** "unknown" is not a small value and
 * it is not a large one — it is the absence of one. Letting it compare as an
 * empty string sends every unknown to the top the moment you sort descending,
 * which buries exactly the rows you were looking for.
 *
 * **Numbers inside text compare as numbers.** `NER-0002` before `NER-0010`,
 * `p. 9` before `p. 74`. A plain string sort puts 10 before 9 and makes the
 * page column useless on a 75-page book.
 */

import { useMemo, useState, type ReactNode } from "react";

const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export type SortDir = "asc" | "desc";

/** Empty for sorting purposes: no value at all, or a blank string. */
function isBlank(v: unknown): boolean {
  return v == null || v === "" || (typeof v === "number" && Number.isNaN(v));
}

function compare(a: unknown, b: unknown): number {
  // Blanks are neither large nor small. They go last, and the caller flips
  // nothing for them — see the note above.
  const ab = isBlank(a), bb = isBlank(b);
  if (ab && bb) return 0;
  if (ab) return 1;
  if (bb) return -1;

  if (typeof a === "boolean" || typeof b === "boolean") {
    return (a ? 1 : 0) - (b ? 1 : 0);
  }
  if (typeof a === "number" && typeof b === "number") return a - b;
  return COLLATOR.compare(String(a), String(b));
}

export interface SortApi<T> {
  /** Sort a list by the column currently chosen. */
  apply: (rows: T[]) => T[];
  /** A clickable heading. Omit `get` when the field name is the key. */
  Th: (props: {
    k: string;
    get?: (row: T) => unknown;
    children: ReactNode;
    title?: string;
    style?: React.CSSProperties;
  }) => JSX.Element;
  /** Which column, and which way — null when the natural order is showing. */
  by: { key: string; dir: SortDir } | null;
}

export function useSort<T extends Record<string, any>>(): SortApi<T> {
  const [by, setBy] = useState<{ key: string; dir: SortDir } | null>(null);
  const [getters] = useState<Map<string, (row: T) => unknown>>(() => new Map());

  const api: SortApi<T> = {
    by,
    apply: (rows: T[]) => {
      if (!by || !Array.isArray(rows)) return rows;
      const get = getters.get(by.key) || ((r: T) => r[by.key]);
      const sign = by.dir === "asc" ? 1 : -1;
      // A copy, always: sorting the caller's array in place would reorder
      // state that other parts of the screen are still reading.
      return [...rows].sort((x, y) => {
        const a = get(x), b = get(y);
        // Blanks stay last whichever way the column is pointing, so the sign
        // is applied only when both sides have a value.
        if (isBlank(a) || isBlank(b)) return compare(a, b);
        return sign * compare(a, b);
      });
    },
    Th: ({ k, get, children, title, style }) => {
      if (get) getters.set(k, get);
      const active = by?.key === k;
      const next: SortDir | null = !active ? "asc" : by!.dir === "asc" ? "desc" : null;
      return (
        <th style={style} className={`sortable${active ? " sorted" : ""}`}>
          <button
            type="button"
            title={title || "Click to sort. A third click restores the original order."}
            onClick={() => setBy(next === null ? null : { key: k, dir: next })}
          >
            <span>{children}</span>
            <span className="arrow" aria-hidden="true">
              {active ? (by!.dir === "asc" ? "▲" : "▼") : "↕"}
            </span>
          </button>
        </th>
      );
    },
  };
  return useMemo(() => api, [by]);
}
