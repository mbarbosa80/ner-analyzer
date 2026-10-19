/**
 * A box for a table wider than the screen, with the sideways scrollbar where
 * it can be seen.
 *
 * The Demand per space table has a working width (the Notes column alone is
 * 260 px) and on a laptop screen it does not fit. Two things went wrong
 * before 2.7.0. The table was set to 100 % of its box, and a table at 100 %
 * never overflows — it *shrinks*, crushing every column to fit, so nothing
 * scrolled and the notes came out three words wide (Marcelo, 22 Sep 2026:
 * "não tá rolando na horizontal quando a resolução do monitor é menor").
 * And once the table is allowed its width, the browser draws the sideways
 * scrollbar at the *bottom* of the box — 62 vh down, under the fold, where
 * nobody looks for it.
 *
 * So: the table keeps its working width (``table.wide`` in styles.css), and
 * this box mirrors its sideways scrollbar at the **top**, right under the
 * headings, kept in step with the real one. Shift + wheel and the bottom
 * scrollbar still work; the top one is simply the one you can see.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

export function WideScroll({ children, className = "" }: { children: ReactNode; className?: string }) {
  const box = useRef<HTMLDivElement | null>(null);
  const top = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      setWidth(el.scrollWidth);
      setOverflows(el.scrollWidth > el.clientWidth + 1);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    const table = el.querySelector("table");
    if (table) ro.observe(table);
    return () => ro.disconnect();
  }, []);

  const follow = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (from && to && Math.abs(from.scrollLeft - to.scrollLeft) > 0.5) to.scrollLeft = from.scrollLeft;
  };

  return (
    <>
      {overflows && (
        <div ref={top} className="hscroll-top" onScroll={() => follow(top.current, box.current)}
             title="Scroll sideways — the table is wider than the screen">
          <div style={{ width, height: 1 }} />
        </div>
      )}
      <div ref={box} className={`scroll wide-scroll ${className}`}
           onScroll={() => follow(box.current, top.current)}>
        {children}
      </div>
    </>
  );
}
