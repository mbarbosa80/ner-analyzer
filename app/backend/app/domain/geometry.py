"""Geometric primitives used by the coverage engine.

Everything in this module works in PDF user-space units unless a function name
says otherwise; conversion to metres is the caller's responsibility and is done
through :mod:`app.domain.units`. Keeping the two concerns apart is what makes the
distance results auditable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from shapely.geometry import LineString, Point as ShapelyPoint, Polygon as ShapelyPolygon
from shapely.ops import nearest_points

from .sheetnames import page_label


@dataclass(frozen=True)
class Point:
    """A point on a single PDF page. ``page`` is 1-based."""

    x: float
    y: float
    page: int = 1

    def distance_units(self, other: "Point") -> float:
        """Euclidean distance in PDF units. Raises when the pages differ."""
        if self.page != other.page:
            raise ValueError(
                f"cannot measure a straight line between {page_label(self.page)} and {page_label(other.page)}; "
                "a vertical route (shaft/riser) is required"
            )
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Area:
    """A functional space taken from a drawing.

    ``polygon`` is optional: many spaces are only known by their label position.
    When a polygon exists the engine also measures to its farthest vertex, which
    is what actually governs compliance for a room served from one room-entry
    point.
    """

    key: str
    name: str
    page: int
    label_point: Point
    polygon: Optional[Sequence[tuple[float, float]]] = None
    space_code: Optional[str] = None
    level: Optional[str] = None
    building: Optional[str] = None
    estimated: bool = True
    meta: dict = field(default_factory=dict)
    #: The **same physical space** as it appears on other pages — a room cut by
    #: a match line is labelled on both sheets. Only occurrences that were
    #: confirmed (by the same-code-same-level rule, or by a person) are here;
    #: the engine may measure from any of them, because each is a real position
    #: of this space on a real sheet. Unconfirmed ones travel in
    #: ``meta["proposed_occurrences"]`` and are only ever reported as a question.
    occurrences: list = field(default_factory=list)

    def shapely(self) -> Optional[ShapelyPolygon]:
        if not self.polygon or len(self.polygon) < 3:
            return None
        poly = ShapelyPolygon(self.polygon)
        return poly if poly.is_valid else poly.buffer(0)

    def representative_point(self) -> Point:
        """Centroid when a polygon exists, otherwise the label position."""
        poly = self.shapely()
        if poly is None or poly.is_empty:
            return self.label_point
        c = poly.representative_point()
        return Point(c.x, c.y, self.page)

    def farthest_vertex_from(self, origin: Point) -> Optional[tuple[Point, float]]:
        """The polygon vertex farthest from ``origin`` and its distance in units."""
        if not self.polygon or origin.page != self.page:
            return None
        best: Optional[tuple[Point, float]] = None
        for x, y in self.polygon:
            d = math.hypot(origin.x - x, origin.y - y)
            if best is None or d > best[1]:
                best = (Point(x, y, self.page), d)
        return best


def polygon_area_units(polygon: Sequence[tuple[float, float]]) -> float:
    if not polygon or len(polygon) < 3:
        return 0.0
    return abs(ShapelyPolygon(polygon).area)


def point_in_polygon(pt: Point, polygon: Sequence[tuple[float, float]]) -> bool:
    if not polygon or len(polygon) < 3:
        return False
    poly = ShapelyPolygon(polygon)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly.covers(ShapelyPoint(pt.x, pt.y))


def distance_point_to_polygon_boundary(pt: Point,
                                       polygon: Sequence[tuple[float, float]]) -> float:
    """Shortest distance from ``pt`` to a polygon (0 when inside)."""
    poly = ShapelyPolygon(polygon)
    if not poly.is_valid:
        poly = poly.buffer(0)
    p = ShapelyPoint(pt.x, pt.y)
    if poly.covers(p):
        return 0.0
    a, b = nearest_points(p, poly)
    return a.distance(b)


def segment_intersects_any(a: Point, b: Point,
                           polygons: Iterable[Sequence[tuple[float, float]]]) -> bool:
    """Whether the straight segment a→b crosses any of ``polygons``.

    Used to flag routes that pass through a forbidden zone.
    """
    seg = LineString([a.as_tuple(), b.as_tuple()])
    for poly_pts in polygons:
        if not poly_pts or len(poly_pts) < 3:
            continue
        poly = ShapelyPolygon(poly_pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if seg.intersects(poly):
            return True
    return False


def centroid(points: Sequence[Point]) -> Optional[Point]:
    """Unweighted centroid of same-page points; ``None`` for an empty sequence."""
    pts = list(points)
    if not pts:
        return None
    pages = {p.page for p in pts}
    if len(pages) != 1:
        raise ValueError("centroid requires all points on the same page")
    return Point(
        sum(p.x for p in pts) / len(pts),
        sum(p.y for p in pts) / len(pts),
        pts[0].page,
    )


def weighted_centroid(points: Sequence[Point], weights: Sequence[float]) -> Optional[Point]:
    """Demand-weighted centroid, used as a seed for new-NER suggestions."""
    pts, ws = list(points), list(weights)
    if not pts:
        return None
    if len(pts) != len(ws):
        raise ValueError("points and weights must have the same length")
    total = sum(ws)
    if total <= 0:
        return centroid(pts)
    pages = {p.page for p in pts}
    if len(pages) != 1:
        raise ValueError("weighted_centroid requires all points on the same page")
    return Point(
        sum(p.x * w for p, w in zip(pts, ws)) / total,
        sum(p.y * w for p, w in zip(pts, ws)) / total,
        pts[0].page,
    )
