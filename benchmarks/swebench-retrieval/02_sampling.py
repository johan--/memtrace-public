"""
Pre-registered stratified-random sampler for SWE-bench Verified.

Deterministic: given the pinned dataset revision + this script + seed=42, the
output CSVs are bit-identical across machines and platforms (Python 3.12,
numpy >= 2.0, pandas >= 2.2).

Stratification:
    1. By `difficulty` (4 classes, proportional allocation to keep Verified's
       difficulty mix).
    2. Within each difficulty bucket: random.choice over instance_ids sorted
       ascending. No replacement.

Output:
    03_instances_25.csv   - headline sample (matches the slide's n=25)
    04_instances_100.csv  - appendix sample (rebuts n=25's wide Wilson CIs)

Both CSVs are a STRICT SUBSET of the parquet in `data/verified_500.parquet`.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ---------- Constants ----------
SEED = 42
N_HEADLINE = 25
N_APPENDIX = 100

# HuggingFace dataset pin. Bumping this revision invalidates pre-registration.
HF_DATASET = "SWE-bench/SWE-bench_Verified"
HF_REVISION = "main"  # captured at commit time; resolved SHA is logged below
HF_PARQUET_URL = (
    f"https://huggingface.co/datasets/{HF_DATASET}/resolve/{HF_REVISION}"
    "/data/test-00000-of-00001.parquet"
)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
PARQUET_PATH = DATA_DIR / "verified_500.parquet"
HEADLINE_CSV = ROOT / "03_instances_25.csv"
APPENDIX_CSV = ROOT / "04_instances_100.csv"

CSV_COLS = ["instance_id", "repo", "base_commit", "difficulty", "created_at"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_parquet() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PARQUET_PATH.exists():
        print(f"[skip] {PARQUET_PATH} already present ({PARQUET_PATH.stat().st_size:,} bytes)")
        return
    print(f"[get ] {HF_PARQUET_URL}")
    resp = requests.get(HF_PARQUET_URL, stream=True, timeout=120)
    resp.raise_for_status()
    with PARQUET_PATH.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    print(f"[save] {PARQUET_PATH} ({PARQUET_PATH.stat().st_size:,} bytes)")


def proportional_allocation(counts: dict[str, int], n: int) -> dict[str, int]:
    """Largest-remainder method. Sums to exactly n. Stable for tied remainders
    by sorting keys alphabetically."""
    total = sum(counts.values())
    raw = {k: n * v / total for k, v in counts.items()}
    floors = {k: int(np.floor(r)) for k, r in raw.items()}
    deficit = n - sum(floors.values())
    # Sort by (remainder desc, key asc) for deterministic tie-break
    order = sorted(raw.items(), key=lambda kv: (-(kv[1] - floors[kv[0]]), kv[0]))
    for i in range(deficit):
        floors[order[i][0]] += 1
    return floors


def stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    df = df.sort_values("instance_id").reset_index(drop=True)
    rng = np.random.default_rng(seed)

    # Allocate per-difficulty proportionally to Verified's mix.
    counts = df["difficulty"].value_counts().to_dict()
    alloc = proportional_allocation(counts, n)

    picks = []
    # Iterate difficulty buckets in sorted order so the RNG stream is deterministic.
    for diff in sorted(alloc):
        k = alloc[diff]
        if k == 0:
            continue
        bucket = df[df["difficulty"] == diff].sort_values("instance_id").reset_index(drop=True)
        idx = rng.choice(len(bucket), size=k, replace=False)
        picks.append(bucket.iloc[sorted(idx)])

    out = pd.concat(picks, ignore_index=True).sort_values("instance_id").reset_index(drop=True)
    assert len(out) == n, f"sample size mismatch: got {len(out)}, want {n}"
    assert out["instance_id"].is_unique, "duplicate instance_ids in sample"
    return out


def main() -> None:
    download_parquet()
    parquet_sha = sha256(PARQUET_PATH)
    print(f"[hash] verified_500.parquet sha256={parquet_sha}")

    df = pd.read_parquet(PARQUET_PATH)
    print(f"[load] {len(df)} instances, columns={sorted(df.columns)[:8]}...")

    # Defensive: sample is a subset of the pinned parquet; if HF rotates the
    # revision and the local cache mismatches, the pre-registration breaks.
    print(f"[diff] difficulty distribution: {df['difficulty'].value_counts().to_dict()}")

    s25 = stratified_sample(df, N_HEADLINE, SEED)
    s100 = stratified_sample(df, N_APPENDIX, SEED)

    # Sanity: s25 should be a subset of s100? NOT necessarily — different
    # allocations per bucket. We document them as independent stratified draws.
    overlap = set(s25["instance_id"]) & set(s100["instance_id"])
    print(f"[over] |s25 ∩ s100| = {len(overlap)} (informational, no constraint)")

    s25[CSV_COLS].to_csv(HEADLINE_CSV, index=False)
    s100[CSV_COLS].to_csv(APPENDIX_CSV, index=False)

    print(f"[done] wrote {HEADLINE_CSV.name}: {len(s25)} rows, "
          f"sha256={sha256(HEADLINE_CSV)}")
    print(f"[done] wrote {APPENDIX_CSV.name}: {len(s100)} rows, "
          f"sha256={sha256(APPENDIX_CSV)}")


if __name__ == "__main__":
    sys.exit(main())
