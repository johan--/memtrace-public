"""
One-command orchestrator. Runs (or dry-runs) all four rows on a chosen CSV.

  Phase A — sanity   : --csv 03_instances_25.csv  (n=25, ~$45–120)
  Phase B — appendix : --csv 04_instances_100.csv (n=100, ~$180–600)

Always:
  1. Validates env (calls runners/check_env.py)
  2. Ensures unique (repo, base_commit) pairs are cloned
  3. Runs each row in order: vector-default, vector-coderankembed, agentic, memtrace
  4. Calls scoring/aggregate.py to produce results/HEADLINE.{md,json}

Flags:
  --dry-run       run only the first --dry-n instances (default 3) — gives a real cost projection
  --skip-row R    skip a row (e.g. --skip-row memtrace if MCP isn't up yet)
  --max-budget-usd  per-task hard cap passed to the agentic + memtrace runners

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    .venv/bin/python -m runners.orchestrate --csv 03_instances_25.csv --dry-run
    .venv/bin/python -m runners.orchestrate --csv 03_instances_25.csv
    .venv/bin/python -m runners.orchestrate --csv 04_instances_100.csv
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
VENV_PY = HERE / ".venv" / "bin" / "python"

VARIANTS = [
    ("vector-default", ["-m", "runners.run_vector", "--embedder", "jinaai/jina-embeddings-v2-base-code", "--row", "vector-default"]),
    ("vector-coderankembed", ["-m", "runners.run_vector", "--embedder", "nomic-ai/CodeRankEmbed", "--row", "vector-coderankembed"]),
    ("agentic", ["-m", "runners.run_agentic"]),
    ("memtrace", ["-m", "runners.run_memtrace"]),
]


def _run(cmd: list[str], *, cwd: Path = HERE, env: dict | None = None) -> int:
    print(f"\n$ {' '.join(str(c) for c in cmd)}\n", flush=True)
    return subprocess.call(cmd, cwd=cwd, env=env or os.environ.copy())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true", help="Only run first --dry-n instances per row")
    ap.add_argument("--dry-n", type=int, default=3)
    ap.add_argument("--skip-row", action="append", default=[],
                    choices=[v[0] for v in VARIANTS])
    ap.add_argument("--max-budget-usd", type=float, default=2.0,
                    help="per-instance hard cap (agentic + memtrace only)")
    args = ap.parse_args()

    csv_path = (HERE / args.csv) if not args.csv.is_absolute() else args.csv
    assert csv_path.exists(), f"CSV not found: {csv_path}"

    # 1. Env check
    rc = _run([str(VENV_PY), "-m", "runners.check_env"])
    if rc != 0:
        print("\nABORT — env precheck failed. Fix the items above and re-run.")
        return rc

    # 2. Clone
    rc = _run([str(VENV_PY), "-m", "runners.clone_repos", "--csv", str(args.csv)])
    if rc != 0:
        print("\nABORT — repo clone failed.")
        return rc

    # 3. Each row
    limit_args = ["--limit", str(args.dry_n)] if args.dry_run else []
    for row_name, base_cmd in VARIANTS:
        if row_name in args.skip_row:
            print(f"\n=== skipping row: {row_name} ===")
            continue
        cmd = [str(VENV_PY), *base_cmd, "--csv", str(args.csv), *limit_args]
        if row_name in ("agentic", "memtrace"):
            cmd += ["--max-budget-usd", str(args.max_budget_usd)]
        rc = _run(cmd)
        if rc != 0:
            print(f"\nWARN — row {row_name} exited rc={rc}; continuing to next row")

    # 4. Aggregate
    rc = _run([str(VENV_PY), "-m", "scoring.aggregate", "--csv", str(args.csv)])
    if rc != 0:
        print("\nWARN — aggregate failed; partial per_instance.csv files still on disk.")
        return rc

    print("\n=== orchestrator done ===")
    headline = HERE / "results" / "HEADLINE.md"
    if headline.exists():
        print(f"\nHeadline at: {headline}\n")
        print(headline.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
