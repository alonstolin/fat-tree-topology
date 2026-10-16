"""Command-line entry point: generate a fat-tree, optionally fail links, report metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx

from .failures import MODES, SCOPES, inject_link_failures
from .metrics import host_path_metrics
from .topology import FatTreeCounts, build_fat_tree, summarize

DEFAULTS = {
    "k": 4,
    "failure_rate": 0.0,
    "failure_scope": "all",
    "failure_mode": "exact",
    "seed": None,
    "metrics": False,
    "export": None,
    "draw": None,
}


def parse_args(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(
        prog="python -m fattree",
        description="Generate a k-ary fat-tree (Al-Fares et al., SIGCOMM'08), optionally inject link failures.",
    )
    p.add_argument("--config", type=Path, help="JSON config file; command-line flags override its values")
    p.add_argument("-k", "--k", type=int, help="switch port count (even, 2 <= k < 256). Default: 4")
    p.add_argument(
        "-f", "--failure-rate", type=float, help="fraction of links to fail, in [0, 1]. Default: 0"
    )
    p.add_argument(
        "--failure-scope",
        choices=SCOPES,
        help="'all' links may fail, or only switch-to-switch 'fabric' links. Default: all",
    )
    p.add_argument(
        "--failure-mode",
        choices=MODES,
        help="'exact': round(rate * links) links fail; 'bernoulli': each link fails w.p. rate. Default: exact",
    )
    p.add_argument("--seed", type=int, help="random seed for reproducible failures")
    p.add_argument("--metrics", action="store_true", default=None, help="compute host-pair path metrics")
    p.add_argument("--export", type=Path, help="write the (degraded) topology as node-link JSON")
    p.add_argument("--draw", type=Path, help="save a PNG drawing of the topology (best for k <= 8)")
    args = p.parse_args(argv)

    config = dict(DEFAULTS)
    if args.config:
        file_config = json.loads(args.config.read_text())
        unknown = set(file_config) - set(DEFAULTS)
        if unknown:
            p.error(f"unknown keys in {args.config}: {sorted(unknown)}")
        config.update(file_config)
    config.update({key: v for key, v in vars(args).items() if key != "config" and v is not None})
    return config


def run(config: dict) -> dict:
    k = config["k"]
    g = build_fat_tree(k)
    degraded, failed = inject_link_failures(
        g,
        config["failure_rate"],
        scope=config["failure_scope"],
        mode=config["failure_mode"],
        seed=config["seed"],
    )
    counts = FatTreeCounts(k)
    report = {
        "config": {key: str(v) if isinstance(v, Path) else v for key, v in config.items()},
        "expected": {
            "pods": counts.pods,
            "hosts": counts.hosts,
            "edge_switches": counts.edge_switches,
            "aggregation_switches": counts.aggregation_switches,
            "core_switches": counts.core_switches,
            "links": counts.links,
        },
        "topology": summarize(degraded),
        "failures": {"failed_links": len(failed)},
    }
    if config["metrics"]:
        report["metrics"] = host_path_metrics(degraded).as_dict()
    if config["export"]:
        data = nx.node_link_data(degraded, edges="links")
        data["failed_links"] = [[u, v] for u, v, _ in failed]
        Path(config["export"]).write_text(json.dumps(data, indent=1, default=list))
    if config["draw"]:
        from .visualize import draw_fat_tree

        draw_fat_tree(g, str(config["draw"]), failed)
    return report


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        report = run(config)
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0
