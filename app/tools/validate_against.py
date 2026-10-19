#!/usr/bin/env python3
"""Run the extraction and matching engines against real documents and print a report.

This is the tool that surfaced the two extraction defects recorded in
``docs/FINDINGS.md``. Run it whenever you point the application at a new document
family, before trusting any coverage number from it.

    python tools/validate_against.py "HND_400_VVO.pdf" "TEAP v2.0.xlsx" --venue HND

Nothing is uploaded anywhere; everything runs locally against the files you name.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.domain.demand import compute_demand                      # noqa: E402
from app.domain.matching import MatchSettings, match_spaces       # noqa: E402
from app.domain.pdf_ingest import extract_drawing                 # noqa: E402
from app.domain.teap_import import (load_product_catalogue,       # noqa: E402
                                    profile_workbook, read_sheet)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("workbook")
    ap.add_argument("--venue", default=None, help="venue code to filter the TEAP by")
    ap.add_argument("--sheet", default=None, help="override the auto-detected sheet")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    report: dict = {}

    # -- drawing ------------------------------------------------------------
    t = time.time()
    ex = extract_drawing(args.pdf)
    report["drawing"] = {
        "seconds": round(time.time() - t, 1),
        "pages": ex.page_count,
        "vector_pages": sum(1 for p in ex.pages if p.is_vector),
        "pages_needing_ocr": ex.needs_ocr_pages,
        "pages_without_a_scale": [p.number for p in ex.pages if not p.scale_candidates],
        "spaces_detected": len(ex.spaces),
        "elements_detected": len(ex.elements),
        "element_kinds": {},
        "element_labels": sorted({e.label for e in ex.elements}),
        "scale_labels": {},
        "pdf_layers": ex.layer_names,
    }
    for e in ex.elements:
        report["drawing"]["element_kinds"][e.kind] = \
            report["drawing"]["element_kinds"].get(e.kind, 0) + 1
    for p in ex.pages:
        for s in p.scale_candidates:
            report["drawing"]["scale_labels"][s.label] = \
                report["drawing"]["scale_labels"].get(s.label, 0) + 1

    # -- workbook -----------------------------------------------------------
    t = time.time()
    profiles = profile_workbook(args.workbook)
    best = next((p for p in profiles if p.name == args.sheet), profiles[0])
    imp = read_sheet(args.workbook, best.name, best.header_row, best.proposed_mapping,
                     venue_filter=args.venue)
    imp.product_ports = load_product_catalogue(args.workbook)
    demands = compute_demand(imp)

    rules: dict[str, int] = {}
    for d in demands:
        for line in d.lines:
            rules[line.rule] = rules.get(line.rule, 0) + 1

    report["teap"] = {
        "seconds": round(time.time() - t, 1),
        "sheets_profiled": len(profiles),
        "sheet_used": best.name,
        "header_row": best.header_row,
        "mapped_columns": best.proposed_mapping,
        "rows_read": len(imp.rows),
        "spaces": len(demands),
        "total_ports": round(sum(d.total_ports for d in demands), 1),
        "demand_rules_fired": rules,
        "reconciliation_warnings": sum(
            1 for d in demands for w in d.warnings if "reconciliation" in w),
        "photographer_spaces": [d.space_code for d in demands
                                if d.demand_type.value == "photographer"],
        "criticality_stated": sum(1 for d in demands if d.criticality),
    }

    # -- matching -----------------------------------------------------------
    # Mirror what the application does: give the matcher the plot scale per page so
    # it can tell a detail sheet from a key plan. Without this the report
    # under-states the match quality the app actually achieves.
    st = MatchSettings(page_scale_denominator={
        pg.number: pg.scale_candidates[0].denominator
        for pg in ex.pages if pg.scale_candidates})
    rep = match_spaces(
        [(d.space_key, d.space_code, d.space_name, d.building, d.level) for d in demands],
        ex.spaces, st,
        demand_by_key={d.space_key: d.total_ports for d in demands})
    stats = rep.stats()
    real = stats["teap_spaces"] - stats["placeholders"]
    report["matching"] = {
        **stats,
        "real_spaces_excluding_placeholders": real,
        "match_rate_excluding_placeholders": round(stats["matched"] / real, 4) if real else 0.0,
        "methods": {},
        "placeholder_codes": [m.teap_code for m in rep.placeholders],
        "needs_review_sample": [(m.teap_code, m.teap_name, round(m.confidence, 2))
                                for m in rep.needs_review[:15]],
        "review_reasons": {},
    }
    for m in rep.matches:
        k = m.best.method.value
        report["matching"]["methods"][k] = report["matching"]["methods"].get(k, 0) + 1
    for m in rep.needs_review:
        notes = " ".join(m.notes)
        cause = ("ambiguous — no sheet is more detailed" if "ambiguous" in notes
                 else "placeholder code, name match only" if "placeholder" in notes
                 else f"method '{m.best.method.value}' below the threshold" if m.best
                 else "unmatched")
        report["matching"]["review_reasons"][cause] = \
            report["matching"]["review_reasons"].get(cause, 0) + 1

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    d, t_, mt = report["drawing"], report["teap"], report["matching"]
    print(f"\nDRAWING  {Path(args.pdf).name}")
    print(f"  {d['pages']} pages in {d['seconds']}s · {d['vector_pages']} vector · "
          f"{len(d['pages_needing_ocr'])} needing OCR")
    print(f"  scales found: {d['scale_labels']}")
    if d["pages_without_a_scale"]:
        print(f"  pages with NO scale (calibrate manually): {d['pages_without_a_scale']}")
    print(f"  {d['spaces_detected']} spaces · {d['elements_detected']} equipment rooms "
          f"{d['element_kinds']}")
    print(f"  labels: {', '.join(d['element_labels'])}")

    print(f"\nTEAP  {Path(args.workbook).name}"
          f"{f' (venue {args.venue})' if args.venue else ''}")
    print(f"  sheet '{t_['sheet_used']}' header row {t_['header_row']} · "
          f"{t_['rows_read']} rows -> {t_['spaces']} spaces · {t_['total_ports']} ports")
    print(f"  demand rules fired: {t_['demand_rules_fired']} "
          f"(A=explicit, B=catalogue, C=category default, D=unknown)")
    print(f"  reconciliation warnings: {t_['reconciliation_warnings']}")
    print(f"  criticality stated on {t_['criticality_stated']} of {t_['spaces']} spaces")
    print(f"  photographer areas (70 m rule): {t_['photographer_spaces']}")

    print("\nMATCHING")
    print(f"  {mt['matched']} of {mt['teap_spaces']} TEAP spaces matched "
          f"({mt['match_rate']:.0%})")
    print(f"  excluding {mt['placeholders']} placeholder rows: "
          f"{mt['matched']} of {mt['real_spaces_excluding_placeholders']} "
          f"({mt['match_rate_excluding_placeholders']:.0%})")
    print(f"  methods: {mt['methods']}")
    print(f"  awaiting human validation: {mt['needs_review']}")
    for cause, n in sorted(mt["review_reasons"].items(), key=lambda kv: -kv[1]):
        print(f"      {n:4d}  {cause}")
    if mt["needs_review_sample"]:
        print("  biggest unresolved, by ports:")
        for code, name, conf in mt["needs_review_sample"][:6]:
            print(f"      {str(code):<18} {str(name)[:38]:<38} conf={conf}")
    print(f"  drawing spaces with no TEAP allocation: {mt['unmatched_drawing']}")
    print("\nThis is an extraction report, not a coverage result. Confirm the scale on "
          "every page and review the match queue before running the analysis.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
