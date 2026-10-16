"""Random link-failure injection."""

from __future__ import annotations

import random

import networkx as nx

from .topology import FABRIC_LINK_KINDS

SCOPES = ("all", "fabric")
MODES = ("exact", "bernoulli")


def candidate_links(g: nx.Graph, scope: str) -> list[tuple[str, str]]:
    """Links eligible to fail, in a deterministic order (so a seed reproduces a run).

    scope="all"    -> every link, including host access links.
    scope="fabric" -> switch-to-switch links only (edge-aggregation, aggregation-core).
    """
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    links = [
        (u, v) for u, v, d in g.edges(data=True) if scope == "all" or d["kind"] in FABRIC_LINK_KINDS
    ]
    return sorted(links)


def inject_link_failures(
    g: nx.Graph,
    rate: float,
    *,
    scope: str = "all",
    mode: str = "exact",
    seed: int | None = None,
) -> tuple[nx.Graph, list[tuple[str, str, dict]]]:
    """Return (degraded copy of g, list of failed links with their attributes).

    mode="exact"     -> exactly round(rate * #candidate links) links fail, chosen uniformly.
    mode="bernoulli" -> each candidate link fails independently with probability `rate`.
    """
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"failure rate must be in [0, 1], got {rate}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    rng = random.Random(seed)
    links = candidate_links(g, scope)
    if mode == "exact":
        failed = rng.sample(links, round(rate * len(links)))
    else:
        failed = [link for link in links if rng.random() < rate]

    degraded = g.copy()
    failed_with_attrs = [(u, v, dict(g.edges[u, v])) for u, v in failed]
    degraded.remove_edges_from(failed)
    degraded.graph["failed_links"] = len(failed)
    return degraded, failed_with_attrs

