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
    #: single-source shortest lengths and paths, by node (4.7.0): an analysis
    #: asks hundreds of questions of one network.
    _sssp: dict = field(default_factory=dict)

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
        self._sssp.clear()
        if prev is None or length_m < prev["weight"]:
            self.graph.add_edge(na, nb, weight=length_m, kind=seg.kind,
                                label=seg.label, vertical=False)

    def add_vertical(self, link: VerticalLink) -> None:
        """Add a shaft/riser. Its length is supplied in metres by the designer."""
        if link.length_m <= 0:
            raise ValueError("a vertical link must have a positive length in metres")
        na, nb = self._node(link.lower), self._node(link.upper)
        self._sssp.clear()
        self.graph.add_edge(na, nb, weight=link.length_m, kind=link.kind,
                            label=link.label or link.key, vertical=True)
        self._vertical_keys.add(link.key)

    # -- T-junctions (4.7.0) ------------------------------------------------
    def split_at_nodes(self, tolerance_units: float = 3.0) -> int:
        """Join a route that ends on the middle of another one.

        The viewer snaps a new route's first or last corner onto an existing
        route, which puts it on the *inside* of a traced segment; the graph
        only knew segment ends, so the two routes did not meet and nothing was
        measured along the pair. Every node lying on another horizontal
        segment of its page now splits that segment in two, the weights in
        proportion. Returns how many splits were made.
        """
        splits = 0
        for n in list(self.graph.nodes):
            changed = True
            while changed:
                changed = False
                for u, v, data in list(self.graph.edges(data=True)):
                    if data.get("vertical") or n in (u, v):
                        continue
                    if not (u[0] == v[0] == n[0]):
                        continue
                    t, d = _project(n[1], n[2], u[1], u[2], v[1], v[2])
                    if d > tolerance_units or t <= 1e-6 or t >= 1 - 1e-6:
                        continue
                    w = data["weight"]
                    self.graph.remove_edge(u, v)
                    attrs = {k: val for k, val in data.items() if k != "weight"}
                    self.graph.add_edge(u, n, weight=w * t, **attrs)
                    self.graph.add_edge(n, v, weight=w * (1 - t), **attrs)
                    splits += 1
                    changed = True
                    break
        self._sssp.clear()
        return splits

    # -- queries ------------------------------------------------------------
    def has_vertical_between(self, page_a: int, page_b: int) -> bool:
        for u, v, data in self.graph.edges(data=True):
            if data.get("vertical") and {u[0], v[0]} == {page_a, page_b}:
                return True
        return False

    def _attach(self, p: Point, max_units: float) -> Optional[dict]:
        """Where a space or a NER joins the traced network on its own page.

        Until 4.7.0 only a segment's *ends* were candidates, so a space beside
        the middle of a long corridor tray never joined it and was measured in
        a straight line as if nothing had been traced. Now the nearest point
        on any traced segment of the page (or a bare node — a shaft's foot)
        within ``max_units`` is the joint; the lead-in from the point to it is
        a straight line, measured and reported apart.
        """
        best: Optional[dict] = None
        for n in self.graph.nodes:
            if n[0] != p.page:
                continue
            d = ((n[1] - p.x) ** 2 + (n[2] - p.y) ** 2) ** 0.5
            if d <= max_units and (best is None or d < best["d"]):
                best = {"d": d, "x": n[1], "y": n[2], "via": [(n, 0.0)], "edge": None, "t": 0.0}
        for u, v, data in self.graph.edges(data=True):
            if data.get("vertical") or not (u[0] == v[0] == p.page):
                continue
            t, d = _project(p.x, p.y, u[1], u[2], v[1], v[2])
            if d > max_units or (best is not None and d >= best["d"]):
                continue
            w = data["weight"]
            best = {"d": d, "x": u[1] + t * (v[1] - u[1]), "y": u[2] + t * (v[2] - u[2]),
                    "via": [(u, w * t), (v, w * (1 - t))], "edge": (u, v), "t": t}
        return best

    def _from(self, node: tuple) -> tuple[dict, dict]:
        """Shortest lengths and paths from ``node``, computed once per node."""
        hit = self._sssp.get(node)
        if hit is None:
            hit = nx.single_source_dijkstra(self.graph, node, weight="weight")
            self._sssp[node] = hit
        return hit

    def route_length_m(self, origin: Point, destination: Point, scale: Scale,
                       *, connect_tolerance_units: float = 60.0,
                       connect_tolerance_m: float = 15.0) -> Optional[dict]:
        """Shortest real route length in metres, or ``None`` when unreachable.

        Each end joins the network at the nearest point of a traced segment
        (or a node) on its own page, within the larger of
        ``connect_tolerance_units`` and ``connect_tolerance_m`` (at ``scale``).
        The two lead-ins are straight lines, measured with ``scale``, included
        in the total and reported separately so a reviewer can see how much of
        the length is assumed rather than traced. Being straight, they keep
        the total at or above the straight-line distance on one sheet.
        """
        tol = max(connect_tolerance_units, scale.to_pdf_units(connect_tolerance_m))
        ja = self._attach(origin, tol)
        jb = self._attach(destination, tol)
        if ja is None or jb is None:
            return None
        best: Optional[tuple[float, list]] = None
        if ja["edge"] is not None and jb["edge"] is not None and \
                {ja["edge"][0], ja["edge"][1]} == {jb["edge"][0], jb["edge"][1]}:
            # Both join the same segment: along it, directly.
            u, v = ja["edge"]
            w = self.graph[u][v]["weight"]
            tb = jb["t"] if jb["edge"] == (u, v) else 1 - jb["t"]
            best = (abs(ja["t"] - tb) * w, [u])
        for a, da in ja["via"]:
            lengths, paths = self._from(a)
            for b, db in jb["via"]:
                if b not in lengths:
                    continue
                total = da + lengths[b] + db
                if best is None or total < best[0]:
                    best = (total, paths[b])
        if best is None:
            return None
        path_len, path = best
        stub_a = scale.to_metres(ja["d"])
        stub_b = scale.to_metres(jb["d"])
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


def _project(px: float, py: float, ax: float, ay: float, bx: float, by: float
             ) -> tuple[float, float]:
    """Where (px, py) falls on segment a–b: the fraction along it (0–1) and
    the distance from the point to that spot."""
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
    qx, qy = ax + t * dx, ay + t * dy
    return t, ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


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
    net.split_at_nodes()
    return net
