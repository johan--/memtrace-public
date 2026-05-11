"""
Idempotent repo cloner.

For each unique (repo, base_commit) pair in the pre-registered CSVs, clones
the repo and checks out the base_commit into work/repos/<repo_safe>/<sha>/.

Idempotent: skips pairs already on disk. Total disk: ~5–10 GB for 100 instances.

Usage:
    .venv/bin/python -m runners.clone_repos --csv 03_instances_25.csv
    .venv/bin/python -m runners.clone_repos --csv 04_instances_100.csv
    .venv/bin/python -m runners.clone_repos --csv 04_instances_100.csv --jobs 4
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
WORK = HERE / "work" / "repos"


def repo_safe(repo: str) -> str:
    return repo.replace("/", "__")


def clone_one(repo: str, base_commit: str, *, work: Path = WORK, verbose: bool = True) -> Path:
    """Clone <repo> at <base_commit> into work/<repo_safe>/<sha>/. Idempotent."""
    dest = work / repo_safe(repo) / base_commit
    if (dest / ".git").exists():
        if verbose:
            print(f"  [skip] {repo}@{base_commit[:8]} -> {dest}")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"

    if verbose:
        print(f"  [get ] {repo}@{base_commit[:8]} -> {dest}")

    # Use a shallow fetch of the specific commit. Falls back to full clone if
    # the server doesn't support shallow fetches.
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    try:
        subprocess.run(["git", "init", "--quiet"], cwd=tmp, check=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=tmp, check=True)
        # Try fetching just the commit. Some hosts disallow this for old commits.
        r = subprocess.run(
            ["git", "fetch", "--quiet", "--depth", "1", "origin", base_commit],
            cwd=tmp, capture_output=True, text=True,
        )
        if r.returncode != 0:
            # Fallback: full clone + checkout.
            shutil.rmtree(tmp)
            subprocess.run(["git", "clone", "--quiet", url, str(tmp)], check=True)
        subprocess.run(["git", "checkout", "--quiet", base_commit], cwd=tmp, check=True)
        tmp.rename(dest)
    except subprocess.CalledProcessError as e:
        if tmp.exists():
            shutil.rmtree(tmp)
        raise RuntimeError(f"clone failed for {repo}@{base_commit}: {e}") from e

    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, required=True, help="instance CSV (03_ or 04_)")
    ap.add_argument("--jobs", type=int, default=2, help="concurrent clone jobs")
    args = ap.parse_args()

    csv_path = (HERE / args.csv) if not args.csv.is_absolute() else args.csv
    df = pd.read_csv(csv_path)
    pairs = df[["repo", "base_commit"]].drop_duplicates().reset_index(drop=True)
    print(f"=== cloning {len(pairs)} unique (repo, base_commit) pairs from {csv_path.name} ===")

    failures: list[tuple[str, str, Exception]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        fut_to_pair = {
            pool.submit(clone_one, row.repo, row.base_commit): (row.repo, row.base_commit)
            for row in pairs.itertuples(index=False)
        }
        for fut in as_completed(fut_to_pair):
            repo, sha = fut_to_pair[fut]
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  [FAIL] {repo}@{sha[:8]}: {e}")
                failures.append((repo, sha, e))

    print()
    if failures:
        print(f"FAIL — {len(failures)} clone(s) failed:")
        for repo, sha, e in failures:
            print(f"  - {repo}@{sha[:8]}: {e}")
        return 1

    total = sum(1 for _ in WORK.rglob(".git"))
    print(f"OK — {total} repos on disk at {WORK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
