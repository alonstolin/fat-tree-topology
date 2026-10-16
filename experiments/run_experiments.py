"""Reproduce every CSV and figure in results/ (reported in README.md).

    python experiments/run_experiments.py              # full run (about a minute)
    python experiments/run_experiments.py --quick      # smoke run (seconds)

Experiment: path metrics vs. link-failure rate for several k. Only switch-to-switch
("fabric") links fail; a failed host access link trivially cuts that host off and says
nothing about the fat-tree's redundancy. Also draws the k = 4 topology for the README.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fattree.failures import inject_link_failures  # noqa: E402
from fattree.metrics import host_path_metrics  # noqa: E402
from fattree.topology import build_fat_tree  # noqa: E402
from fattree.visualize import draw_fat_tree  # noqa: E402

SCOPE = "fabric"
COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
METRICS = ["avg_path_length", "interpod_path_diversity", "disconnected_pair_fraction"]


def mean_ci(values: list[float]) -> tuple[float, float]:
    """Mean and 95% confidence half-width (normal approximation)."""
    vals = [v for v in values if not math.isnan(v)]
    if not vals:
        return float("nan"), float("nan")
    m = statistics.fmean(vals)
    if len(vals) < 2:
        return m, 0.0
    return m, 1.96 * statistics.stdev(vals) / math.sqrt(len(vals))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _trial(args):
    k, rate, trial = args
    g = build_fat_tree(k)
    seed = zlib.crc32(f"{k}/{rate}/{trial}".encode())
    degraded, failed = inject_link_failures(g, rate, scope=SCOPE, mode="exact", seed=seed)
    return {"k": k, "rate": rate, "trial": trial, "failed_links": len(failed), **host_path_metrics(degraded).as_dict()}


def failure_sweep(out: Path, ks, rates, trials, jobs) -> list[dict]:
    tasks = [(k, r, t) for k in ks for r in rates for t in range(trials)]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        raw = list(pool.map(_trial, tasks, chunksize=8))
    write_csv(out / "failure_sweep_raw.csv", raw)

    summary = []
    for k in ks:
        for r in rates:
            group = [row for row in raw if row["k"] == k and row["rate"] == r]
            row = {"k": k, "rate": r, "trials": len(group)}
            for metric in METRICS:
                row[f"{metric}_mean"], row[f"{metric}_ci95"] = mean_ci([g[metric] for g in group])
            summary.append(row)
    write_csv(out / "failure_sweep_summary.csv", summary)
    return summary


def plot(out: Path, summary, ks, trials) -> None:
    figures = [
        ("avg_path_length", "avg_path_length_vs_failure.png",
         "avg. host-to-host shortest path (hops)", "Average path length", 1),
        ("interpod_path_diversity", "path_diversity_vs_failure.png",
         r"shortest paths left / $(k/2)^2$ (inter-pod pairs)", "Number of shortest paths (inter-pod)", 1),
        ("disconnected_pair_fraction", "disconnection_vs_failure.png",
         "host pairs disconnected (%)", "Disconnected host pairs", 100),
    ]
    for metric, filename, ylabel, title, scale in figures:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for color, k in zip(COLORS, ks):
            rows = sorted((r for r in summary if r["k"] == k), key=lambda r: r["rate"])
            x = [100 * r["rate"] for r in rows]
            y = [scale * r[f"{metric}_mean"] for r in rows]
            ci = [scale * r[f"{metric}_ci95"] for r in rows]
            ax.plot(x, y, marker="o", ms=3.5, color=color, label=f"k = {k}")
            ax.fill_between(x, [a - b for a, b in zip(y, ci)], [a + b for a, b in zip(y, ci)],
                            color=color, alpha=0.18, lw=0)
        ax.set_xlabel("switch-to-switch links failed (%)")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{title} vs. link failures\n(mean of {trials} trials, shaded band = 95% CI)")
        ax.grid(alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / filename, dpi=150)
        plt.close(fig)


def drawings(out: Path) -> None:
    g = build_fat_tree(4)
    draw_fat_tree(g, str(out / "topology_k4.png"), title="k = 4 fat-tree (Al-Fares et al., Fig. 3 addressing)")
    _, failed = inject_link_failures(g, 0.15, scope=SCOPE, seed=4)
    draw_fat_tree(g, str(out / "topology_k4_failures.png"), failed,
                  title=f"k = 4 fat-tree, 15% of switch-to-switch links failed ({len(failed)} links, dashed red)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--jobs", type=int, default=None, help="worker processes (default: all cores)")
    p.add_argument("--quick", action="store_true", help="tiny run for smoke-testing")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.quick:
        ks, rates, trials = [4, 8], [0.0, 0.1, 0.3], 3
    else:
        ks, rates, trials = [4, 8, 16, 24], [round(0.05 * i, 2) for i in range(11)], args.trials

    print(f"failure sweep: k={ks}, rates={rates[0]:.0%}..{rates[-1]:.0%}, {trials} trials each")
    plot(args.out, failure_sweep(args.out, ks, rates, trials, args.jobs), ks, trials)
    drawings(args.out)
    print(f"done -> {args.out}")


if __name__ == "__main__":
    main()
