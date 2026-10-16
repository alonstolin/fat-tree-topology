import itertools
import json

import networkx as nx
import pytest

from fattree.cli import main
from fattree.failures import candidate_links, inject_link_failures
from fattree.metrics import healthy_path_metrics, host_path_metrics
from fattree.topology import (
    AGG_CORE,
    AGGREGATION,
    CORE,
    EDGE,
    HOST,
    FatTreeCounts,
    build_fat_tree,
    nodes_in_layer,
)


@pytest.mark.parametrize("k", [2, 4, 6, 8, 16])
def test_element_counts_match_paper(k):
    g = build_fat_tree(k)
    c = FatTreeCounts(k)
    assert len(nodes_in_layer(g, HOST)) == c.hosts == k**3 // 4
    assert len(nodes_in_layer(g, EDGE)) == c.edge_switches
    assert len(nodes_in_layer(g, AGGREGATION)) == c.aggregation_switches
    assert len(nodes_in_layer(g, CORE)) == c.core_switches == (k // 2) ** 2
    assert g.number_of_edges() == c.links


@pytest.mark.parametrize("k", [4, 6, 8])
def test_every_switch_uses_exactly_k_ports(k):
    g = build_fat_tree(k)
    for n, d in g.nodes(data=True):
        assert g.degree(n) == (1 if d["layer"] == HOST else k)


def test_core_switch_has_one_link_per_pod():
    k = 8
    g = build_fat_tree(k)
    for core in nodes_in_layer(g, CORE):
        pods = sorted(g.nodes[n]["pod"] for n in g.neighbors(core))
        assert pods == list(range(k))


def test_paper_addressing_k4():
    g = build_fat_tree(4)
    # Figure 3 of the paper.
    for name in ["10.4.1.1", "10.4.1.2", "10.4.2.1", "10.4.2.2", "10.0.1.1", "10.2.2.1", "10.0.1.2", "10.0.1.3"]:
        assert name in g
    assert g.nodes["10.0.1.1"]["layer"] == EDGE
    assert g.nodes["10.2.2.1"]["layer"] == AGGREGATION
    assert set(g.neighbors("10.0.1.2")) == {"10.0.1.1"}
    # Aggregation switch 10.pod.2.1 (first agg) reaches core row j=1; 10.pod.3.1 reaches row j=2.
    assert {n for n in g.neighbors("10.0.2.1") if g.nodes[n]["layer"] == CORE} == {"10.4.1.1", "10.4.1.2"}
    assert {n for n in g.neighbors("10.3.3.1") if g.nodes[n]["layer"] == CORE} == {"10.4.2.1", "10.4.2.2"}


@pytest.mark.parametrize("bad", [0, 3, -4, 256, 4.0])
def test_invalid_k_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        build_fat_tree(bad)


def test_exact_failures_count_scope_and_reproducibility():
    g = build_fat_tree(8)
    fabric = candidate_links(g, "fabric")
    degraded, failed = inject_link_failures(g, 0.1, scope="fabric", seed=7)
    assert len(failed) == round(0.1 * len(fabric))
    assert all(d["kind"] != "host-edge" for *_, d in failed)
    assert degraded.number_of_edges() == g.number_of_edges() - len(failed)
    assert g.number_of_edges() == FatTreeCounts(8).links  # original untouched
    _, again = inject_link_failures(g, 0.1, scope="fabric", seed=7)
    assert failed == again


def test_bernoulli_failures_rate_is_close():
    g = build_fat_tree(16)
    _, failed = inject_link_failures(g, 0.2, mode="bernoulli", seed=1)
    assert abs(len(failed) / g.number_of_edges() - 0.2) < 0.02


def test_failure_rate_bounds():
    g = build_fat_tree(4)
    with pytest.raises(ValueError):
        inject_link_failures(g, 1.5)
    _, failed = inject_link_failures(g, 1.0)
    assert len(failed) == g.number_of_edges()


@pytest.mark.parametrize("k", [2, 4, 6, 8])
def test_healthy_metrics_match_closed_form(k):
    m = host_path_metrics(build_fat_tree(k))
    expected = healthy_path_metrics(k)
    assert m.disconnected_pair_fraction == 0
    assert m.avg_path_length == pytest.approx(expected["avg_path_length"])
    assert m.avg_shortest_paths == pytest.approx(expected["avg_shortest_paths"])
    assert m.interpod_path_diversity == pytest.approx(1.0)
    assert m.max_path_length == 6


def _brute_force(g):
    hosts = nodes_in_layer(g, HOST)
    lengths, counts = [], []
    for a, b in itertools.combinations(hosts, 2):
        if not nx.has_path(g, a, b):
            continue
        paths = list(nx.all_shortest_paths(g, a, b))
        lengths.append(len(paths[0]) - 1)
        counts.append(len(paths))
    n_pairs = len(hosts) * (len(hosts) - 1) // 2
    return 1 - len(lengths) / n_pairs, sum(lengths) / len(lengths), sum(counts) / len(counts)


@pytest.mark.parametrize("rate,scope,seed", [(0.1, "all", 1), (0.25, "fabric", 2), (0.4, "all", 3), (0.5, "fabric", 4)])
def test_metrics_match_brute_force_under_failures(rate, scope, seed):
    g, _ = inject_link_failures(build_fat_tree(4), rate, scope=scope, seed=seed)
    m = host_path_metrics(g)
    disc, avg_len, avg_paths = _brute_force(g)
    assert m.disconnected_pair_fraction == pytest.approx(disc)
    assert m.avg_path_length == pytest.approx(avg_len)
    assert m.avg_shortest_paths == pytest.approx(avg_paths)


def test_agg_core_failures_can_force_longer_paths():
    # Cut every core uplink of pod 0 except one aggregation switch's -> still 6 hops.
    # Then cut the edge switch 10.0.0.1 from that aggregation switch -> detour through the pod.
    g = build_fat_tree(4)
    g.remove_edges_from([(u, v) for u, v, d in g.edges(data=True) if d["kind"] == AGG_CORE and "10.0.3.1" in (u, v)])
    g.remove_edge("10.0.0.1", "10.0.2.1")
    m = host_path_metrics(g)
    assert m.disconnected_pair_fraction == 0
    assert m.max_path_length == 8
    assert m.avg_path_length > healthy_path_metrics(4)["avg_path_length"]


def test_cli_with_config_and_overrides(tmp_path, capsys):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"k": 6, "failure_rate": 0.1, "seed": 3}))
    out = tmp_path / "topo.json"
    assert main(["--config", str(cfg), "-k", "4", "--metrics", "--export", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["config"]["k"] == 4
    assert report["failures"]["failed_links"] == round(0.1 * FatTreeCounts(4).links)
    assert "metrics" in report
    exported = json.loads(out.read_text())
    assert len(exported["failed_links"]) == report["failures"]["failed_links"]


def test_cli_rejects_bad_k(capsys):
    assert main(["-k", "5"]) == 2
    assert "even" in capsys.readouterr().err
