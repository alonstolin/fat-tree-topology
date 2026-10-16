"""Host-to-host path metrics, computed exactly over all host pairs.

Every host hangs off exactly one edge switch, so a host pair (a, b) on edge switches
(e_a, e_b) has
    distance(a, b)          = distance(e_a, e_b) + 2
    #shortest paths(a, b)   = #shortest paths(e_a, e_b)
(or distance 2 and a single path when e_a == e_b). We therefore run one BFS with
shortest-path counting per edge switch over the switch-only graph instead of one BFS
per host. That is k^2/2 BFS runs instead of k^3/4, and lets k = 24 (3456 hosts,
~6M host pairs) be evaluated in well under a second.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

import networkx as nx

from .topology import HOST, FatTreeCounts


@dataclass
class PathMetrics:
    host_pairs: int  # all unordered host pairs of the full (failure-free) network
    connected_pairs: int
    disconnected_pair_fraction: float
    avg_path_length: float  # hops, averaged over connected pairs
    max_path_length: int  # longest shortest path over connected pairs
    avg_shortest_paths: float  # number of equal-cost shortest paths, averaged over connected pairs
    interpod_path_diversity: float  # avg #shortest paths between connected hosts in different pods / (k/2)^2
    isolated_hosts: int  # hosts whose access link failed

    def as_dict(self) -> dict:
        return asdict(self)


def _bfs_with_counts(adj: dict[str, list[str]], src: str) -> tuple[dict[str, int], dict[str, int]]:
    """Unweighted BFS returning hop distance and number of shortest paths from src."""
    dist = {src: 0}
    sigma = {src: 1}
    frontier = [src]
    while frontier:
        nxt = []
        for u in frontier:
            du = dist[u] + 1
            su = sigma[u]
            for v in adj[u]:
                dv = dist.get(v)
                if dv is None:
                    dist[v] = du
                    sigma[v] = su
                    nxt.append(v)
                elif dv == du:
                    sigma[v] += su
        frontier = nxt
    return dist, sigma


def host_path_metrics(g: nx.Graph) -> PathMetrics:
    """Path metrics over all host pairs of a (possibly degraded) fat-tree."""
    total_hosts = FatTreeCounts(g.graph["k"]).hosts
    host_pairs = total_hosts * (total_hosts - 1) // 2

    hosts_on_edge: dict[str, int] = defaultdict(int)
    isolated = 0
    for n, d in g.nodes(data=True):
        if d["layer"] != HOST:
            continue
        nbrs = list(g.neighbors(n))
        if nbrs:
            hosts_on_edge[nbrs[0]] += 1
        else:
            isolated += 1

    adj = {
        n: [v for v in g.neighbors(n) if g.nodes[v]["layer"] != HOST]
        for n, d in g.nodes(data=True)
        if d["layer"] != HOST
    }

    edges = sorted(hosts_on_edge, key=lambda e: (g.nodes[e]["pod"], g.nodes[e]["index"]))
    connected = 0
    length_sum = 0
    paths_sum = 0
    max_len = 0
    interpod_pairs = 0
    interpod_paths_sum = 0

    for i, e1 in enumerate(edges):
        n1 = hosts_on_edge[e1]
        # Pairs behind the same edge switch: 2 hops, a single path.
        same = n1 * (n1 - 1) // 2
        if same:
            connected += same
            length_sum += 2 * same
            paths_sum += same
            max_len = max(max_len, 2)

        dist, sigma = _bfs_with_counts(adj, e1)
        for e2 in edges[i + 1 :]:
            d = dist.get(e2)
            if d is None:
                continue
            pairs = n1 * hosts_on_edge[e2]
            hops = d + 2
            connected += pairs
            length_sum += hops * pairs
            paths_sum += sigma[e2] * pairs
            max_len = max(max_len, hops)
            if g.nodes[e1]["pod"] != g.nodes[e2]["pod"]:
                interpod_pairs += pairs
                interpod_paths_sum += sigma[e2] * pairs

    return PathMetrics(
        host_pairs=host_pairs,
        connected_pairs=connected,
        disconnected_pair_fraction=1 - connected / host_pairs if host_pairs else 0.0,
        avg_path_length=length_sum / connected if connected else float("nan"),
        max_path_length=max_len,
        avg_shortest_paths=paths_sum / connected if connected else float("nan"),
        interpod_path_diversity=(
            interpod_paths_sum / interpod_pairs / (g.graph["k"] // 2) ** 2 if interpod_pairs else float("nan")
        ),
        isolated_hosts=isolated,
    )


def healthy_path_metrics(k: int) -> dict[str, float]:
    """Closed-form failure-free values, used to validate host_path_metrics.

    Per host: k/2 - 1 peers on the same edge switch (2 hops, 1 path),
    (k/2)(k/2 - 1) peers in the same pod (4 hops, k/2 paths) and
    (k - 1)(k/2)^2 peers in other pods (6 hops, (k/2)^2 paths).
    """
    h = k // 2
    same_edge, same_pod, other_pod = h - 1, h * (h - 1), (k - 1) * h * h
    peers = same_edge + same_pod + other_pod
    return {
        "avg_path_length": (2 * same_edge + 4 * same_pod + 6 * other_pod) / peers,
        "avg_shortest_paths": (1 * same_edge + h * same_pod + h * h * other_pod) / peers,
    }

