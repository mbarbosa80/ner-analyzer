/**
 * Two languages for the interface, and nothing else.
 *
 * The design decision worth writing down: **the key is the English string
 * itself**, not an invented identifier like `register.rename.button`.
 *
 * Invented keys are the textbook approach and they are the right one for a
 * product with translators, a string-freeze and a release train. This app has
 * none of those. Here they would buy one thing — the ability to change the
 * English without touching the key — and cost three:
 *
 *   1. Every string in every screen would have to be *named*, and the names
 *      would have to be kept accurate as screens are rearranged. A key that
 *      still says `matching.` after the control moved to the register is worse
 *      than no key.
 *   2. A missing key renders as `matching.confirm.button` in front of a
 *      stakeholder. A missing English-keyed string renders as correct English.
 *      The failure mode of the cheap approach is strictly better.
 *   3. Constants that already exist in English — STATUS_LABEL, KIND_LABEL,
 *      LEGEND_ROWS, the TABS table — can be translated at the point of display
 *      with `t(STATUS_LABEL[x])`, with no restructuring at all. With invented
 *      keys each of those tables would have to be rewritten to carry keys.
 *
 * The cost is real and should be stated: **editing the English text of a
 * string silently drops its translation back to English.** That is why
 * `missingKeys()` exists and why the test suite reports coverage — the drift
 * is made visible rather than left to be discovered on screen.
 *
 * What is *not* translated, deliberately:
 *   - anything that came out of the database (space names, NER display names,
 *     venue codes, page labels, aliases, audit entries),
 *   - the codes (NER-0007), which are identifiers and must read identically to
 *     everyone,
 *   - the XLSX/CSV exports, which have one shape regardless of who exported
 *     them — see `docs/` and the export code,
 *   - file names and the server log.
 */

import { PT } from "./strings.pt";

export type Lang = "en" | "pt";

const STORE_KEY = "ner.lang";

function read(): Lang {
  try {
    return localStorage.getItem(STORE_KEY) === "pt" ? "pt" : "en";
  } catch {
    // Private mode, blocked site data — English is the default anyway.
    return "en";
  }
}

let current: Lang = read();
const listeners = new Set<() => void>();

export function getLang(): Lang {
  return current;
}

export function setLang(next: Lang): void {
  if (next === current) return;
  current = next;
  try {
    localStorage.setItem(STORE_KEY, next);
  } catch {
    /* the choice just will not survive a reload; the session still switches */
  }
  document.documentElement.lang = next === "pt" ? "pt-BR" : "en";
  listeners.forEach((fn) => fn());
}

/** Subscribe to language changes. Returns the unsubscribe function. */
export function onLangChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Translate one piece of interface copy.
 *
 * Falls back to the English it was given, so an untranslated string is a
 * cosmetic gap and never a broken screen.
 */
export function t(english: string): string {
  if (current === "en") return english;
  return PT[english] ?? english;
}

/**
 * Which strings the caller asked for that PT has no translation for.
 * Used by the build-time coverage report, not at runtime.
 */
export function missingKeys(used: string[]): string[] {
  return used.filter((s) => !(s in PT));
}

document.documentElement.lang = current === "pt" ? "pt-BR" : "en";
