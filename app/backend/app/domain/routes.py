"""Cable route graph, including vertical connections (shafts and risers).

Straight-line geometry is only a screening tool. Once a designer traces real
containment on the drawings, the graph built here becomes the authority for
compliance, and it is the only mechanism through which a NER on one level may
serve a space on another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import networkx as nx

from .geometry import Point
from .units import Scale


@dataclass
class RouteSegment:
    """A traced piece of horizontal containment on one page."""

    a: Point
    b: Point
    page: int
    kind: str = "tray"           # tray | conduit | j-hook | free-air
    label: str = ""


@dataclass
class VerticalLink:
    """A shaft or riser connecting two pages (levels) at a known location."""

    key: str
    lower: Point
    upper: Point
    length_m: float
    kind: str = "shaft"          # shaft | riser | sleeve
    label: str = ""


@dataclass
class RouteNetwork:
    """A per-project routing graph. Node ids are ``(page, x, y)`` tuples rounded
    to ``snap_units`` so that separately traced segments join up."""

    snap_units: float = 2.0
    graph: nx.Graph = field(default_factory=nx.Graph)
    _vertical_keys: set[str] = field(default_factory=set)

    # -- construction -------------------------------------------------------
    def _node(self, p: Point) -> tuple[int, float, float]:
        s = self.snap_units
        return (p.page, round(p.x / s) * s, round(p.y / s) * s)

    def add_segment(self, seg: RouteSegment, scale: Scale) -> None:
        """Add a horizontal segment; its weight is its real length in metres."""
        na, nb = self._node(seg.a), self._node(seg.b)
        if na == nb:
            return
        length_m = scale.to_metres(seg.a.distance_units(seg.b))
        prev = self.graph.get_edge_data(na, nb, default=None)
        if prev is None or length_m < prev["weight"]:
            self.graph.add_edge(na, nb, weight=length_m, kind=seg.kind,
                                label=seg.label, vertical=False)

    def add_vertical(self, link: VerticalLink) -> None:
        """Add a shaft/riser. Its length is supplied in metres by the designer."""
        if link.length_m <= 0:
            raise ValueError("a vertical link must have a positive length in metres")
        na, nb = self._node(link.lower), self._node(link.upper)
        self.graph.add_edge(na, nb, weight=link.length_m, kind=link.kind,
                            label=link.label or link.key, vertical=True)
        self._vertical_keys.add(link.key)

    # -- queries ------------------------------------------------------------
    def has_vertical_between(self, page_a: int, page_b: int) -> bool:
        for u, v, data in self.graph.edges(data=True):
            if data.get("vertical") and {u[0], v[0]} == {page_a, page_b}:
                return True
        return False

    def _nearest_node(self, p: Point, max_units: float) -> Optional[tuple]:
        best, best_d = None, float("inf")
        for n in self.graph.nodes:
            if n[0] != p.page:
                continue
            d = ((n[1] - p.x) ** 2 + (n[2] - p.y) ** 2) ** 0.5
            if d < best_d:
                best, best_d = n, d
        if best is None or best_d > max_units:
            return None
        return best

    def route_length_m(self, origin: Point, destination: Point, scale: Scale,
                       *, connect_tolerance_units: float = 60.0) -> Optional[dict]:
        """Shortest real route length in metres, or ``None`` when unreachable.

        The two end points are connected to the nearest traced node; those two
        lead-in stubs are measured with ``scale`` and included in the total, and
        reported separately so a reviewer can see how much of the length is
        assumed rather than traced.
        """
        na = self._nearest_node(origin, connect_tolerance_units)
        nb = self._nearest_node(destination, connect_tolerance_units)
        if na is None or nb is None:
            return None
        try:
            path_len = nx.shortest_path_length(self.graph, na, nb, weight="weight")
            path = nx.shortest_path(self.graph, na, nb, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

        stub_a = scale.to_metres(((na[1] - origin.x) ** 2 + (na[2] - origin.y) ** 2) ** 0.5)
        stub_b = scale.to_metres(((nb[1] - destination.x) ** 2 + (nb[2] - destination.y) ** 2) ** 0.5)
        verticals = [
            self.graph[u][v].get("label", "")
            for u, v in zip(path, path[1:]) if self.graph[u][v].get("vertical")
        ]
        return {
            "length_m": path_len + stub_a + stub_b,
            "traced_m": path_len,
            "lead_in_m": stub_a + stub_b,
            "node_count": len(path),
            "vertical_links": verticals,
            "crosses_levels": len({n[0] for n in path}) > 1,
        }


def build_network(segments: Iterable[RouteSegment],
                  verticals: Iterable[VerticalLink],
                  scale_for_page: dict[int, Scale],
                  snap_units: float = 2.0) -> RouteNetwork:
    net = RouteNetwork(snap_units=snap_units)
    for seg in segments:
        sc = scale_for_page.get(seg.page)
        if sc is None:
            continue
        net.add_segment(seg, sc)
    for link in verticals:
        net.add_vertical(link)
    return net
