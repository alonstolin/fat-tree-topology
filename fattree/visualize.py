"""Layered drawing of a fat-tree, with failed links highlighted."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from .topology import AGGREGATION, CORE, EDGE, HOST

LAYER_Y = {CORE: 3.0, AGGREGATION: 2.0, EDGE: 1.0, HOST: 0.0}
LAYER_STYLE = {
    CORE: dict(node_color="#4C72B0", node_shape="s", node_size=260),
    AGGREGATION: dict(node_color="#55A868", node_shape="s", node_size=220),
    EDGE: dict(node_color="#DD8452", node_shape="s", node_size=180),
    HOST: dict(node_color="#8C8C8C", node_shape="o", node_size=50),
}


def _positions(g: nx.Graph) -> dict[str, tuple[float, float]]:
    k = g.graph["k"]
    half = k // 2
    hosts_per_pod = half * half
    pod_width = hosts_per_pod + 1.0  # one empty slot between pods
    total_width = k * pod_width
    pos = {}
    for n, d in g.nodes(data=True):
        layer, pod, idx = d["layer"], d["pod"], d["index"]
        if layer == HOST:
            e, host_id = idx
            x = pod * pod_width + e * half + (host_id - 2)
        elif layer in (EDGE, AGGREGATION):
            # Spread the k/2 pod switches across the pod's host span.
            x = pod * pod_width + (idx + 0.5) * hosts_per_pod / half - 0.5
        else:
            j, i = idx
            slot = (j - 1) * half + (i - 1)
            x = (slot + 0.5) * total_width / (half * half) - 0.5
        pos[n] = (x, LAYER_Y[layer])
    return pos


def draw_fat_tree(
    g: nx.Graph,
    path: str,
    failed: list[tuple[str, str, dict]] | None = None,
    title: str | None = None,
    labels: bool | None = None,
) -> None:
    """Save a layered drawing of g (the full graph) to `path`; failed links are dashed red."""
    k = g.graph["k"]
    pos = _positions(g)
    failed_set = {frozenset((u, v)) for u, v, _ in failed or []}
    alive = [(u, v) for u, v in g.edges() if frozenset((u, v)) not in failed_set]

    width = max(10.0, 0.18 * len(pos) ** 0.9)
    fig, ax = plt.subplots(figsize=(min(width, 40.0), 6))
    nx.draw_networkx_edges(g, pos, edgelist=alive, ax=ax, edge_color="#B0B0B0", width=0.8)
    if failed_set:
        nx.draw_networkx_edges(
            g,
            pos,
            edgelist=[tuple(e) for e in failed_set],
            ax=ax,
            edge_color="#C44E52",
            style="dashed",
            width=1.8,
        )
    for layer, style in LAYER_STYLE.items():
        nodes = [n for n, d in g.nodes(data=True) if d["layer"] == layer]
        nx.draw_networkx_nodes(g, pos, nodelist=nodes, ax=ax, label=layer, **style)

    if labels if labels is not None else k <= 4:
        switch_labels = {n: n for n, d in g.nodes(data=True) if d["layer"] != HOST}
        for n, (x, y) in pos.items():
            if n in switch_labels:
                ax.annotate(n, (x, y), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=7)

    ax.set_title(title or f"k = {k} fat-tree" + (f" ({len(failed_set)} failed links)" if failed_set else ""))
    ax.legend(loc="upper left", fontsize=8, markerscale=0.7, frameon=False)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
