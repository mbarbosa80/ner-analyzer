"""Scale parsing and unit conversion.

Every measurement inside the application is stored in METRES. This module is the
only place allowed to convert between PDF user-space units, drawing units and
metres, so that a single audited code path produces every distance in the system.

A PDF "point" is 1/72 inch by definition. A drawing carries a *plot scale* which
relates paper distance to real-world distance:

    real_world_metres = paper_metres * scale_denominator

For an architectural scale such as 1/8" = 1'-0" the denominator is
(12 inches / 0.125 inches) = 96.

Nothing here depends on a language model. All results are deterministic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

# ---------------------------------------------------------------------------
# Primitive constants
# ---------------------------------------------------------------------------

POINTS_PER_INCH = 72.0
METRES_PER_INCH = 0.0254
METRES_PER_FOOT = 0.3048
POINTS_PER_METRE = POINTS_PER_INCH / METRES_PER_INCH  # 2834.6456...


class ScaleError(ValueError):
    """Raised when a scale string cannot be interpreted unambiguously."""


# ---------------------------------------------------------------------------
# Scale model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scale:
    """Relates PDF user-space units to real-world metres.

    Attributes
    ----------
    metres_per_unit:
        How many real-world metres one PDF user-space unit represents.
    source:
        How the scale was obtained: ``"ratio"``, ``"architectural"``,
        ``"engineering"``, ``"manual"``, ``"scale_bar"``.
    label:
        Human readable form as it appears (or would appear) on the drawing.
    confirmed:
        ``True`` only once a human has explicitly confirmed the scale. Definitive
        results must stay blocked while this is ``False``.
    """

    metres_per_unit: float
    source: str
    label: str
    confirmed: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.metres_per_unit) or self.metres_per_unit <= 0:
            raise ScaleError(f"metres_per_unit must be positive and finite, got {self.metres_per_unit!r}")

    # -- conversions --------------------------------------------------------
    def to_metres(self, pdf_units: float) -> float:
        """Convert a length expressed in PDF user-space units to metres."""
        return pdf_units * self.metres_per_unit

    def to_pdf_units(self, metres: float) -> float:
        """Convert a real-world length in metres to PDF user-space units."""
        return metres / self.metres_per_unit

    @property
    def denominator(self) -> float:
        """The plot-scale denominator (e.g. 200.0 for 1:200)."""
        return self.metres_per_unit * POINTS_PER_METRE

    def confirm(self) -> "Scale":
        return Scale(self.metres_per_unit, self.source, self.label, confirmed=True)


def scale_from_ratio(denominator: float, *, label: Optional[str] = None,
                     source: str = "ratio") -> Scale:
    """Build a :class:`Scale` from a plot-scale denominator such as 100 for 1:100."""
    if denominator <= 0:
        raise ScaleError("scale denominator must be positive")
    return Scale(
        metres_per_unit=denominator / POINTS_PER_METRE,
        source=source,
        label=label or f"1:{denominator:g}",
    )


def scale_from_two_points(pdf_distance_units: float, real_distance: float,
                          unit: str = "m") -> Scale:
    """Manual calibration: user picks two points and types the real distance."""
    if pdf_distance_units <= 0:
        raise ScaleError("the two calibration points must not coincide")
    real_m = length_to_metres(real_distance, unit)
    if real_m <= 0:
        raise ScaleError("the real distance must be positive")
    mpu = real_m / pdf_distance_units
    return Scale(
        metres_per_unit=mpu,
        source="manual",
        label=f"manual ({real_distance:g} {unit} over {pdf_distance_units:.2f} pt) ≈ 1:{mpu * POINTS_PER_METRE:.0f}",
    )


def length_to_metres(value: float, unit: str) -> float:
    """Convert ``value`` given in ``unit`` to metres."""
    u = unit.strip().lower()
    if u in ("m", "metre", "meter", "metres", "meters"):
        return value
    if u in ("mm", "millimetre", "millimeter"):
        return value / 1000.0
    if u in ("cm", "centimetre", "centimeter"):
        return value / 100.0
    if u in ("km",):
        return value * 1000.0
    if u in ("ft", "foot", "feet", "'"):
        return value * METRES_PER_FOOT
    if u in ("in", "inch", "inches", '"'):
        return value * METRES_PER_INCH
    raise ScaleError(f"unknown unit {unit!r}")


def metres_to(value_m: float, unit: str) -> float:
    """Convert metres to ``unit`` for display purposes only."""
    u = unit.strip().lower()
    if u in ("m", "metre", "meter"):
        return value_m
    if u in ("ft", "foot", "feet"):
        return value_m / METRES_PER_FOOT
    raise ScaleError(f"unsupported display unit {unit!r}")


def format_length(value_m: float, display: str = "m") -> str:
    """Format a metric length for the UI. ``display`` is ``m``, ``ft`` or ``both``."""
    if display == "m":
        return f"{value_m:.1f} m"
    if display == "ft":
        return f"{metres_to(value_m, 'ft'):.1f} ft"
    if display == "both":
        return f"{value_m:.1f} m ({metres_to(value_m, 'ft'):.1f} ft)"
    raise ScaleError(f"unsupported display mode {display!r}")


# ---------------------------------------------------------------------------
# Scale notation parsing
# ---------------------------------------------------------------------------

# Ratio notation is matched in two tiers, because a drawing sheet is full of text
# that *looks* like a ratio and is not. Measured on a real 34-page venue design
# book, a permissive pattern produced 1:2026 (from the date "03/31/2026"),
# 1:410 / 1:430 / 1:470 (from detail bubbles "1 / 410" naming a sheet) and other
# phantoms, alongside the two genuine scales.
#
# Tier 1 — anchored to an explicit SCALE / ESCALA keyword. Trusted.
_KEYWORD_RATIO_RX = re.compile(
    r"(?:scale|esc(?:ala)?\.?)\s*[:=]?\s*1\s*[:/]\s*(\d{1,5}(?:[.,]\d+)?)",
    re.IGNORECASE,
)

# Tier 2 — a bare ratio. Colon only (a slash without a keyword is almost always a
# detail bubble), the "1" must not be the tail of a longer number, and the
# denominator must be a value that actually appears on drawings.
_BARE_RATIO_RX = re.compile(
    r"(?<![\d.,/\-])1\s*:\s*(\d{1,5}(?:[.,]\d+)?)(?![\d.,])",
)

#: Denominators a real drawing plausibly uses. Anything else from an unanchored
#: match is a false positive rather than an unusual scale.
PLAUSIBLE_DENOMINATORS = {
    1, 2, 5, 10, 20, 25, 33, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300, 400,
    500, 600, 750, 1000, 1250, 1500, 2000, 2500, 5000, 10000,
}

# kept for backwards compatibility with callers that used the old single pattern
_RATIO_RX = _KEYWORD_RATIO_RX

# 1/8" = 1'-0"      3/16" = 1'-0"     1" = 20'      1/2 IN = 1 FT
_ARCH_RX = re.compile(
    r"""(?P<paper>\d+(?:\s+\d+/\d+|/\d+)?|\d+/\d+)\s*(?:"|''|in\b|inch(?:es)?\b)?
        \s*=\s*
        (?P<real>\d+(?:\.\d+)?)\s*(?:'|ft\b|feet|foot)
        (?:\s*[-–]?\s*(?P<realin>\d+(?:\.\d+)?)\s*(?:"|''|in\b))?""",
    re.IGNORECASE | re.VERBOSE,
)


def _parse_mixed_number(text: str) -> float:
    """Parse ``3``, ``3/16`` or ``1 1/2`` into a float."""
    text = text.strip()
    if " " in text:
        whole, frac = text.split(None, 1)
        return float(whole) + float(Fraction(frac))
    if "/" in text:
        return float(Fraction(text))
    return float(text)


def parse_scale_text(text: str) -> Optional[Scale]:
    """Best-effort parse of a scale annotation found on a drawing.

    Returns ``None`` when nothing recognisable is present. The returned scale is
    never ``confirmed`` — automatic detection always requires human sign-off.
    """
    if not text:
        return None
    cleaned = " ".join(text.split())

    m = _ARCH_RX.search(cleaned)
    if m:
        paper_in = _parse_mixed_number(m.group("paper"))
        real_ft = float(m.group("real"))
        real_in = float(m.group("realin") or 0.0)
        real_total_in = real_ft * 12.0 + real_in
        if paper_in > 0 and real_total_in > 0:
            denom = real_total_in / paper_in
            return scale_from_ratio(denom, label=m.group(0).strip(), source="architectural")

    m = _KEYWORD_RATIO_RX.search(cleaned)
    if m:
        denom = float(m.group(1).replace(",", "."))
        if denom > 0:
            return scale_from_ratio(denom, label=f"1:{denom:g}", source="ratio")

    m = _BARE_RATIO_RX.search(cleaned)
    if m:
        denom = float(m.group(1).replace(",", "."))
        if denom > 0 and (denom in PLAUSIBLE_DENOMINATORS or float(denom).is_integer()
                          and int(denom) in PLAUSIBLE_DENOMINATORS):
            return scale_from_ratio(denom, label=f"1:{denom:g}", source="ratio")

    return None


def parse_scale_candidates(text: str) -> list[Scale]:
    """Return every distinct scale annotation found in a block of text.

    A page may carry several viewports with different scales; the caller decides
    which one applies to which region.
    """
    out: list[Scale] = []
    seen: set[float] = set()
    cleaned = " ".join((text or "").split())

    # Architectural notations are matched first and their spans are then excluded
    # from the ratio pass, otherwise the "1/8" in `1/8" = 1'-0"` is misread as the
    # plot ratio 1:8.
    arch_spans: list[tuple[int, int]] = []
    for m in _ARCH_RX.finditer(cleaned):
        arch_spans.append(m.span())
        s = parse_scale_text(m.group(0))
        if s is None:
            continue
        key = round(s.metres_per_unit, 12)
        if key not in seen:
            seen.add(key)
            out.append(s)

    # Keyword-anchored ratios rank above bare ones, so the first candidate the UI
    # offers is the one the sheet actually declares.
    for rx in (_KEYWORD_RATIO_RX, _BARE_RATIO_RX):
        for m in rx.finditer(cleaned):
            a, b = m.span()
            if any(a < e and s < b for s, e in arch_spans):
                continue
            s = parse_scale_text(m.group(0))
            if s is None or s.denominator < 2:
                continue
            key = round(s.metres_per_unit, 12)
            if key not in seen:
                seen.add(key)
                out.append(s)
    return out
