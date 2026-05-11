"""
Scorer for SWE-bench retrieval rounds.

Two responsibilities:

1. `gold_files_from_patch(patch_str)` — parse a unified-diff `patch` string
   (from the SWE-bench parquet's `patch` field) into the set of files modified
   by the human PR. This is the gold set per Princeton's `eval_retrieval`.

2. `score_row(per_instance_df, dataset_df)` — given a row's retrieved file
   sets and the dataset's gold patches, compute:
     - per-instance recall = |gold ∩ retrieved| / |gold|
     - per-instance hit = (recall == 1.0)
     - aggregate hit-rate with Wilson 95% CI (binary metric)
     - aggregate mean-recall with bootstrap 95% CI (continuous metric)

No external API. Pure pandas + stdlib + numpy. Verified against pytest fixtures.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------- 1. Gold extraction ----------

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
_PLUS_PLUS_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$", re.MULTILINE)
_MINUS_MINUS_RE = re.compile(r"^--- (?:a/)?(.+?)(?:\t.*)?$", re.MULTILINE)


def gold_files_from_patch(patch_str: str) -> frozenset[str]:
    """Extract the set of repository-relative file paths modified by a unified
    diff. Handles renames (both src and dst captured), deletions (only `---`
    side), and creations (only `+++` side). `/dev/null` is filtered out.

    Returns a frozenset so callers can safely use the result as a dict key or
    set member.
    """
    if not patch_str:
        return frozenset()

    files: set[str] = set()

    # `diff --git a/X b/Y` captures both source and dest paths.
    for src, dst in _DIFF_GIT_RE.findall(patch_str):
        if src and src != "/dev/null":
            files.add(src)
        if dst and dst != "/dev/null":
            files.add(dst)

    # Fallback: capture `+++ b/path` and `--- a/path` lines for diffs that
    # may not have the `diff --git` header (edge case, but cheap to handle).
    for path in _PLUS_PLUS_RE.findall(patch_str):
        if path and path != "/dev/null":
            files.add(path)
    for path in _MINUS_MINUS_RE.findall(patch_str):
        if path and path != "/dev/null":
            files.add(path)

    return frozenset(files)


# ---------- 2. Recall computation ----------

def per_instance_recall(gold: frozenset[str], retrieved: frozenset[str]) -> float:
    """Recall = |gold ∩ retrieved| / |gold|. Returns 0.0 if gold is empty
    (defensive — should never happen on Verified, but documented behaviour).
    """
    if not gold:
        return 0.0
    return len(gold & retrieved) / len(gold)


def per_instance_hit(gold: frozenset[str], retrieved: frozenset[str]) -> bool:
    """True iff every gold file was retrieved (recall == 1.0).
    This is the binary metric used for Wilson CI."""
    if not gold:
        return False
    return gold.issubset(retrieved)


# ---------- 3. Confidence intervals ----------

@dataclass(frozen=True)
class CI:
    point: float
    low: float
    high: float
    n: int
    method: str

    def fmt(self, pct: bool = True, digits: int = 1) -> str:
        if pct:
            return f"{self.point*100:.{digits}f}% [{self.low*100:.{digits}f}, {self.high*100:.{digits}f}]"
        return f"{self.point:.{digits+2}f} [{self.low:.{digits+2}f}, {self.high:.{digits+2}f}]"


def wilson_ci(k: int, n: int, z: float = 1.96) -> CI:
    """Wilson 95% CI for a binomial proportion k/n.

    Reference: Wilson (1927); the standard reviewer-acceptable interval for
    small n. Wikipedia: Binomial_proportion_confidence_interval#Wilson_score_interval
    """
    if n == 0:
        return CI(point=0.0, low=0.0, high=0.0, n=0, method="wilson")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return CI(
        point=p,
        low=max(0.0, center - margin),
        high=min(1.0, center + margin),
        n=n,
        method="wilson",
    )


def bootstrap_ci(
    values: list[float], n_resamples: int = 10_000, seed: int = 42, alpha: float = 0.05
) -> CI:
    """Percentile bootstrap CI for the mean of `values`. Used for mean-recall
    (continuous metric in [0,1]). Wilson is wrong here because we're not
    estimating a binomial proportion."""
    n = len(values)
    if n == 0:
        return CI(point=0.0, low=0.0, high=0.0, n=0, method="bootstrap")
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        sample = rng.choice(arr, size=n, replace=True)
        means[i] = sample.mean()
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return CI(point=float(arr.mean()), low=lo, high=hi, n=n, method="bootstrap")


# ---------- 4. Row-level aggregation ----------

@dataclass(frozen=True)
class RowScore:
    row_name: str
    n: int
    hit_rate: CI         # binary: did the row retrieve every gold file?
    mean_recall: CI      # continuous: what fraction of gold files retrieved?

    def summary_line(self) -> str:
        return (
            f"{self.row_name:30s}  hit-rate {self.hit_rate.fmt()}   "
            f"mean-recall {self.mean_recall.fmt()}   n={self.n}"
        )


def score_row(
    row_name: str,
    per_instance_df: pd.DataFrame,  # columns: instance_id, retrieved_files (frozenset or list)
    dataset_df: pd.DataFrame,  # columns: instance_id, patch
) -> tuple[RowScore, pd.DataFrame]:
    """Compute the row's aggregate score AND return a per-instance dataframe
    suitable for results/<row>/per_instance.csv."""
    gold_by_id: dict[str, frozenset[str]] = {
        row["instance_id"]: gold_files_from_patch(row["patch"])
        for _, row in dataset_df.iterrows()
    }

    records = []
    for _, row in per_instance_df.iterrows():
        iid = row["instance_id"]
        retrieved = row["retrieved_files"]
        if isinstance(retrieved, str):
            # JSON-encoded list (typical when read from CSV)
            import json
            retrieved = json.loads(retrieved)
        retrieved_set = frozenset(retrieved)
        gold = gold_by_id.get(iid, frozenset())
        records.append({
            "instance_id": iid,
            "gold_files": sorted(gold),
            "retrieved_files": sorted(retrieved_set),
            "n_gold": len(gold),
            "n_retrieved": len(retrieved_set),
            "n_intersect": len(gold & retrieved_set),
            "recall": per_instance_recall(gold, retrieved_set),
            "hit": per_instance_hit(gold, retrieved_set),
        })
    out = pd.DataFrame(records)

    n = len(out)
    k = int(out["hit"].sum())
    hit = wilson_ci(k, n)
    mean = bootstrap_ci(out["recall"].tolist())

    return RowScore(row_name=row_name, n=n, hit_rate=hit, mean_recall=mean), out


# ---------- 5. CLI for ad-hoc scoring ----------

def main() -> None:
    """Usage: python -m scoring.scorer <per_instance.csv> <row_name>
    Requires data/verified_500.parquet alongside.
    """
    import sys
    from pathlib import Path

    if len(sys.argv) != 3:
        print(__doc__)
        print("usage: python -m scoring.scorer <per_instance.csv> <row_name>")
        sys.exit(1)

    per_instance_path = Path(sys.argv[1])
    row_name = sys.argv[2]

    here = Path(__file__).parent.parent
    dataset = pd.read_parquet(here / "data" / "verified_500.parquet")
    per_instance = pd.read_csv(per_instance_path)

    score, detail = score_row(row_name, per_instance, dataset)
    print(score.summary_line())

    out_csv = per_instance_path.with_name(per_instance_path.stem + "_scored.csv")
    detail.to_csv(out_csv, index=False)
    print(f"[wrote] {out_csv}")


if __name__ == "__main__":
    main()
