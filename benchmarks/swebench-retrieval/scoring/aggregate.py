"""
Aggregate per-instance results across all rows into a single headline table.

Reads:
    results/vector-default/per_instance.csv
    results/vector-coderankembed/per_instance.csv
    results/agentic/per_instance.csv
    results/memtrace/per_instance.csv
    data/verified_500.parquet            (for gold patches)

Writes:
    results/HEADLINE.md         human-readable comparison table
    results/HEADLINE.json       structured copy for downstream tooling

Usage:
    .venv/bin/python -m scoring.aggregate
    .venv/bin/python -m scoring.aggregate --csv 03_instances_25.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from scoring.scorer import score_row

HERE = Path(__file__).resolve().parent.parent
ROWS = ["vector", "agentic", "memtrace"]


def _load_row(row: str, dataset: pd.DataFrame) -> dict | None:
    csv = HERE / "results" / row / "per_instance.csv"
    if not csv.exists():
        return None
    df = pd.read_csv(csv)
    if df.empty:
        return None
    # Restrict gold to instances present in the row's per_instance.csv
    ds_subset = dataset[dataset["instance_id"].isin(df["instance_id"])]
    score, detail = score_row(row, df, ds_subset)
    detail.to_csv(HERE / "results" / row / "per_instance_scored.csv", index=False)

    cost_total = float(df["cost_usd"].sum()) if "cost_usd" in df else 0.0
    in_tok = int(df["input_tokens"].sum()) if "input_tokens" in df else 0
    out_tok = int(df["output_tokens"].sum()) if "output_tokens" in df else 0
    parse_errors = int((df.get("status", pd.Series([])) == "parse_error").sum())
    runtime_errors = int((df.get("status", pd.Series([])) == "runtime_error").sum())
    timeouts = int((df.get("status", pd.Series([])) == "timeout").sum())

    return {
        "row": row,
        "n": score.n,
        "hit_rate": {"point": score.hit_rate.point, "low": score.hit_rate.low, "high": score.hit_rate.high},
        "mean_recall": {"point": score.mean_recall.point, "low": score.mean_recall.low, "high": score.mean_recall.high},
        "input_tokens_total": in_tok,
        "output_tokens_total": out_tok,
        "cost_usd_total": cost_total,
        "cost_usd_per_task": cost_total / max(1, score.n),
        "errors": {"parse": parse_errors, "runtime": runtime_errors, "timeout": timeouts},
    }


def _format_ci(ci: dict, digits: int = 1) -> str:
    return f"{ci['point']*100:.{digits}f}% [{ci['low']*100:.{digits}f}, {ci['high']*100:.{digits}f}]"


def _format_money(x: float) -> str:
    return f"${x:.2f}"


def write_headline(rows: list[dict]) -> None:
    md = HERE / "results" / "HEADLINE.md"
    js = HERE / "results" / "HEADLINE.json"

    lines = []
    lines.append("# SWE-bench Verified retrieval — headline\n")
    lines.append(f"Rows scored: {len(rows)} of {len(ROWS)} pre-registered. Mean over per-instance.\n")
    lines.append("| Row | n | Hit-rate (Wilson 95%) | Mean recall (bootstrap 95%) | Total in tok | Total out tok | Total $ | $/task | Errors |")
    lines.append("|---|---:|---|---|---:|---:|---:|---:|---|")
    for r in rows:
        err = r["errors"]
        err_str = f"parse={err['parse']} runtime={err['runtime']} timeout={err['timeout']}"
        lines.append(
            f"| {r['row']} | {r['n']} | {_format_ci(r['hit_rate'])} | {_format_ci(r['mean_recall'])} | "
            f"{r['input_tokens_total']:,} | {r['output_tokens_total']:,} | "
            f"{_format_money(r['cost_usd_total'])} | {_format_money(r['cost_usd_per_task'])} | "
            f"{err_str} |"
        )
    lines.append("")
    lines.append("**Hit-rate** = fraction of instances where the row retrieved EVERY gold file (Wilson 95% CI).")
    lines.append("**Mean recall** = mean per-instance |gold ∩ retrieved|/|gold| (bootstrap 95% CI, 10k resamples, seed=42).")
    lines.append("Per-instance details: see `results/<row>/per_instance_scored.csv` (one row per instance with gold + retrieved file lists).")
    md.write_text("\n".join(lines) + "\n")

    js.write_text(json.dumps({"rows": rows}, indent=2))
    print(f"[wrote] {md}")
    print(f"[wrote] {js}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=None,
                    help="restrict to instance_ids in this CSV (e.g. 03_instances_25.csv)")
    args = ap.parse_args()

    dataset = pd.read_parquet(HERE / "data" / "verified_500.parquet")
    if args.csv:
        csv_path = (HERE / args.csv) if not args.csv.is_absolute() else args.csv
        ids = set(pd.read_csv(csv_path)["instance_id"].astype(str).tolist())
        dataset = dataset[dataset["instance_id"].astype(str).isin(ids)]

    rows = []
    for row in ROWS:
        scored = _load_row(row, dataset)
        if scored is None:
            print(f"  [skip] {row}: no per_instance.csv yet")
            continue
        rows.append(scored)

    if not rows:
        print("ERR — no rows have per_instance.csv yet; nothing to aggregate.")
        return 1

    write_headline(rows)

    print()
    print("Summary:")
    for r in rows:
        print(f"  {r['row']:30s} hit-rate {_format_ci(r['hit_rate'])}  n={r['n']}  cost {_format_money(r['cost_usd_total'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
