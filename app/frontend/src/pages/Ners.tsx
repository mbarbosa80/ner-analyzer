/**
 * NERs — one screen.
 *
 * This used to hold two tabs, "On the drawing" (what the VDB says) and
 * "Register" (what you decided). They were folded into one list on 3 Sep 2026
 * at Marcelo's request: *"não tem razão para duas telas, o que eu herdei ou
 * desenhei segue o mesmo princípio."* The distinction the split protected —
 * the drawing's evidence against a person's decisions — survives inside each
 * row: the marker evidence sits behind *Details*, per occurrence, and every
 * decision still lands in the audit log with who and why.
 *
 * The visual-only markers (TER, IDF, COW, DIVA node) are not rows here. They
 * are managed in the Drawing viewer; the heading counts them.
 */

import type { Ctx } from "../App";
import { NerRegisterPanel } from "./NerRegister";

export function NersPanel({ ctx }: { ctx: Ctx }) {
  return <NerRegisterPanel ctx={ctx} />;
}
