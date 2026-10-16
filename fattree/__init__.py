"""Fat-tree data center topology generator and analysis (Al-Fares et al., SIGCOMM 2008)."""

from .failures import inject_link_failures
from .metrics import PathMetrics, healthy_path_metrics, host_path_metrics
from .topology import FatTreeCounts, build_fat_tree, summarize

__all__ = [
    "FatTreeCounts",
    "PathMetrics",
    "build_fat_tree",
    "healthy_path_metrics",
    "host_path_metrics",
    "inject_link_failures",
    "summarize",
]
