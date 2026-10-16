"""k-ary fat-tree generator following Al-Fares et al., SIGCOMM 2008 (Section 2.2 / 3.2).

Structure for an even switch port count k:
  * k pods; each pod has k/2 edge switches and k/2 aggregation switches.
  * Every edge switch connects to k/2 hosts and to all k/2 aggregation switches of its pod.
  * (k/2)^2 core switches arranged in a (k/2) x (k/2) grid; core switch (j, i) has one
    port to every pod. Aggregation switch number j (0-based, inside its pod) connects to
    the k/2 core switches of grid row j+1 -- i.e. consecutive aggregation switches are
    wired to the core in strides of k/2, exactly as in the paper.

Node names are the paper's IP addresses:
  * pod switches  10.pod.switch.1   (switch in [0, k-1]; edge = [0, k/2-1], aggregation = [k/2, k-1])
  * core switches 10.k.j.i          (j, i in [1, k/2])
  * hosts         10.pod.switch.ID  (ID in [2, k/2+1], attached to edge switch `switch`)
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

HOST = "host"
EDGE = "edge"
AGGREGATION = "aggregation"
CORE = "core"
SWITCH_LAYERS = (EDGE, AGGREGATION, CORE)

HOST_EDGE = "host-edge"
EDGE_AGG = "edge-aggregation"
AGG_CORE = "aggregation-core"
FABRIC_LINK_KINDS = (EDGE_AGG, AGG_CORE)


@dataclass(frozen=True)
class FatTreeCounts:
    """Closed-form element counts of a k-ary fat-tree (paper Section 2.2)."""

    k: int

    @property
    def pods(self) -> int:
        return self.k

    @property
    def hosts(self) -> int:
        return self.k**3 // 4

    @property
    def edge_switches(self) -> int:
        return self.k * self.k // 2

    @property
    def aggregation_switches(self) -> int:
        return self.k * self.k // 2

    @property
    def core_switches(self) -> int:
        return (self.k // 2) ** 2

    @property
    def switches(self) -> int:
        return 5 * self.k * self.k // 4

    @property
    def links(self) -> int:
        # host-edge, edge-aggregation and aggregation-core each contribute k^3/4 links.
        return 3 * self.k**3 // 4


def validate_k(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool):
        raise TypeError(f"k must be an integer, got {type(k).__name__}")
    if k < 2 or k % 2:
        raise ValueError(f"k must be an even integer >= 2, got {k}")
    if k >= 256:
        # Addressing uses one octet per pod / switch / host id (paper assumes k < 256).
        raise ValueError(f"k must be < 256 for the 10.pod.switch.id addressing scheme, got {k}")


def edge_switch(pod: int, index: int) -> str:
    return f"10.{pod}.{index}.1"


def aggregation_switch(k: int, pod: int, index: int) -> str:
    return f"10.{pod}.{k // 2 + index}.1"


def core_switch(k: int, j: int, i: int) -> str:
    return f"10.{k}.{j}.{i}"


def host(pod: int, edge_index: int, host_id: int) -> str:
    return f"10.{pod}.{edge_index}.{host_id}"


def build_fat_tree(k: int) -> nx.Graph:
    """Return the k-ary fat-tree as an undirected networkx graph.

    Node attributes: ``layer`` (host/edge/aggregation/core), ``pod`` (None for core),
    ``index`` (position inside its layer/pod; (j, i) tuple for core switches).
    Edge attribute: ``kind`` (host-edge / edge-aggregation / aggregation-core).
    """
    validate_k(k)
    half = k // 2
    g = nx.Graph(k=k)

    for j in range(1, half + 1):
        for i in range(1, half + 1):
            g.add_node(core_switch(k, j, i), layer=CORE, pod=None, index=(j, i))

    for pod in range(k):
        for e in range(half):
            edge = edge_switch(pod, e)
            g.add_node(edge, layer=EDGE, pod=pod, index=e)
            for host_id in range(2, half + 2):
                h = host(pod, e, host_id)
                g.add_node(h, layer=HOST, pod=pod, index=(e, host_id))
                g.add_edge(h, edge, kind=HOST_EDGE)

        for a in range(half):
            agg = aggregation_switch(k, pod, a)
            g.add_node(agg, layer=AGGREGATION, pod=pod, index=a)
            for e in range(half):
                g.add_edge(edge_switch(pod, e), agg, kind=EDGE_AGG)
            # Aggregation switch a uses its k/2 upward ports for core row a+1.
            for i in range(1, half + 1):
                g.add_edge(agg, core_switch(k, a + 1, i), kind=AGG_CORE)

    return g


def nodes_in_layer(g: nx.Graph, layer: str) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d["layer"] == layer]


def summarize(g: nx.Graph) -> dict[str, int]:
    """Count nodes per layer and links per kind of a (possibly degraded) fat-tree."""
    summary: dict[str, int] = {"k": g.graph["k"]}
    for layer in (HOST, EDGE, AGGREGATION, CORE):
        summary[f"{layer}_nodes"] = len(nodes_in_layer(g, layer))
    for kind in (HOST_EDGE, EDGE_AGG, AGG_CORE):
        summary[f"{kind}_links"] = sum(1 for *_, d in g.edges(data=True) if d["kind"] == kind)
    summary["links"] = g.number_of_edges()
    return summary
