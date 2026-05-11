"""
Vector runner — Memtrace MCP, vector-only RRF weights.

Architecture: same indexer + same embedder (Jina-code) as the Memtrace row.
The only difference is that BM25, exact-symbol, and graph legs are zeroed at
the RRF fusion stage via env vars, and the agent is restricted to `find_code`
only. The result is "pure dense-vector retrieval over Memtrace's index."

Frozen config (prompts/vector_query.md):
  - Harness: Claude Code -p + Memtrace MCP
  - Tool allowlist: mcp__memtrace__find_code (nothing else)
  - RRF weights: BM25=0, EXACT=0, GRAPH=0, VECTOR=1.0
  - Model: claude-sonnet-4-6, temp 0, 30 turns

Per instance:
  1. Ensure the repo is indexed in Memtrace at base_commit
  2. Run `claude -p` with the vector-only env vars + find_code-only toolset
  3. Parse final JSON for files
  4. Save trajectory + append per_instance.csv row

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    .venv/bin/python -m runners.run_vector --csv 03_instances_25.csv --max-budget-usd 2
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from runners.common import (
    HERE,
    InstanceResult,
    append_result,
    env_required,
    estimate_cost_usd,
    load_completed_instances,
    repo_path,
    save_trajectory,
    write_run_meta,
)

MODEL = "claude-sonnet-4-6"
TURN_LIMIT = 30
ROW = "vector"

# Memtrace RRF weights: zero out every leg except vector. find_code still runs
# the full pipeline (BM25 sidecar, ANN, graph expansion) but only the vector
# leg's per-rank score reaches the fused output.
VECTOR_ONLY_ENV = {
    "MEMTRACE_RRF_BM25_WEIGHT": "0.0",
    "MEMTRACE_RRF_EXACT_WEIGHT": "0.0",
    "MEMTRACE_RRF_GRAPH_WEIGHT": "0.0",
    "MEMTRACE_RRF_VECTOR_WEIGHT": "1.0",
}

SYSTEM_PROMPT = """\
You are a code-retrieval agent with access to a single search tool that
performs pure dense-vector (semantic) retrieval over an indexed code graph.
You DO NOT have shell access. You DO NOT have file-read access. You can
ONLY call the `find_code` tool.

Your task: given a GitHub issue, identify the files that would need to be
modified to resolve it.

Available tools: mcp__memtrace__find_code

Rules:
1. Output your final answer as a JSON object on the LAST line, formatted
   exactly as:
   {"files": ["path/to/file1.py", "path/to/file2.py"]}
2. File paths repository-relative, forward-slash separated.
3. At most 30 turns. Budget tool calls. Each call returns up to `limit`
   ranked candidates; you can re-query with refined wording.
4. The issue text is the only spec. No clarification.

Strategy hint (not enforced): pull out the key noun phrases / symbol names
from the issue and run one or two `find_code` queries. The tool returns
file_path for each match — collect the distinct paths and emit the JSON.

Work step by step. When confident, emit the JSON and stop.
"""

USER_TEMPLATE = """\
Repository: {repo}
Base commit: {base_commit}
Memtrace repo handle: {memdb_repo_id}

Issue:
<<<
{problem_statement}
>>>

Identify the files that need to be modified.
"""

ALLOWED_TOOLS = ["mcp__memtrace__find_code"]


def _ensure_indexed(repo_root: Path, verbose: bool = True) -> None:
    memdb_marker = repo_root / ".memtrace-indexed"
    if memdb_marker.exists():
        return
    if verbose:
        print(f"    indexing {repo_root.name} ...")
    t0 = time.time()
    r = subprocess.run(
        ["memtrace", "index", "--path", str(repo_root)],
        capture_output=True, text=True, timeout=1800,
    )
    if r.returncode != 0:
        raise RuntimeError(f"memtrace index failed: rc={r.returncode}\n{r.stderr}")
    memdb_marker.touch()
    if verbose:
        print(f"    indexed in {time.time()-t0:.1f}s")


def _parse_files(text: str) -> tuple[list[str], str]:
    if not text:
        return [], "parse_error"
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and isinstance(obj.get("files"), list):
                return [str(f) for f in obj["files"]], "ok"
        except json.JSONDecodeError:
            continue
    return [], "parse_error"


def _run_one_instance(
    instance_id: str,
    repo: str,
    base_commit: str,
    problem_statement: str,
    repo_root: Path,
    max_budget_usd: float,
) -> InstanceResult:
    try:
        _ensure_indexed(repo_root)
    except Exception as e:  # noqa: BLE001
        return InstanceResult(
            instance_id=instance_id, repo=repo, base_commit=base_commit,
            retrieved_files=[], status="runtime_error",
            error=f"indexing failed: {e}",
        )

    user_msg = USER_TEMPLATE.format(
        repo=repo, base_commit=base_commit,
        memdb_repo_id=str(repo_root),
        problem_statement=problem_statement,
    )

    cmd = [
        "claude", "-p",
        "--bare",
        "--model", MODEL,
        "--add-dir", str(repo_root),
        "--tools", *ALLOWED_TOOLS,
        "--system-prompt", SYSTEM_PROMPT,
        "--output-format", "json",
        "--max-budget-usd", str(max_budget_usd),
        "--no-session-persistence",
        "--permission-mode", "acceptEdits",
        user_msg,
    ]

    env = {**os.environ, **VECTOR_ONLY_ENV}

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900, env=env,
        )
    except subprocess.TimeoutExpired as e:
        return InstanceResult(
            instance_id=instance_id, repo=repo, base_commit=base_commit,
            retrieved_files=[], status="timeout",
            error=f"15m timeout: {e}",
            wall_clock_s=time.time() - t0,
        )

    wall = time.time() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        save_trajectory(ROW, instance_id, {"stdout": stdout, "stderr": stderr})
        return InstanceResult(
            instance_id=instance_id, repo=repo, base_commit=base_commit,
            retrieved_files=[], status="parse_error",
            error="Claude Code envelope not parseable",
            wall_clock_s=wall,
        )

    result_text = envelope.get("result") or envelope.get("response") or ""
    files, parse_status = _parse_files(result_text)

    usage = envelope.get("usage", {}) if isinstance(envelope.get("usage"), dict) else {}
    input_tok = int(usage.get("input_tokens", 0))
    output_tok = int(usage.get("output_tokens", 0))
    cache_read = int(usage.get("cache_read_input_tokens", 0))
    cost = float(envelope.get("total_cost_usd", 0.0)) or estimate_cost_usd(input_tok, output_tok, cache_read)
    turns = int(envelope.get("num_turns", 0))

    save_trajectory(ROW, instance_id, envelope)

    return InstanceResult(
        instance_id=instance_id, repo=repo, base_commit=base_commit,
        retrieved_files=files,
        input_tokens=input_tok, output_tokens=output_tok,
        cost_usd=cost,
        wall_clock_s=wall,
        status=parse_status,
        turns_used=turns,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--max-budget-usd", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    env_required("ANTHROPIC_API_KEY")
    csv_path = (HERE / args.csv) if not args.csv.is_absolute() else args.csv
    df = pd.read_csv(csv_path)
    dataset = pd.read_parquet(HERE / "data" / "verified_500.parquet")
    df = df.merge(dataset[["instance_id", "problem_statement"]], on="instance_id", how="left")

    if args.limit:
        df = df.head(args.limit)

    done = load_completed_instances(ROW)
    remaining = df[~df["instance_id"].isin(done)].reset_index(drop=True)
    print(f"=== vector runner csv={csv_path.name} ===")
    print(f"  {len(df)} total, {len(done)} done, {len(remaining)} to run")
    print(f"  model={MODEL}, RRF weights: VECTOR=1.0, BM25/EXACT/GRAPH=0.0")

    if remaining.empty:
        return 0

    write_run_meta(ROW, {
        "row": ROW,
        "model": MODEL,
        "turn_limit": TURN_LIMIT,
        "max_budget_usd_per_task": args.max_budget_usd,
        "allowed_tools": ALLOWED_TOOLS,
        "rrf_weights": VECTOR_ONLY_ENV,
        "system_prompt": SYSTEM_PROMPT,
        "csv": str(csv_path),
        "n_total": int(len(df)),
        "python": sys.version,
        "platform": platform.platform(),
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    try:
        v = subprocess.check_output(["memtrace", "--version"], text=True).strip()
        with (HERE / "results" / ROW / "memtrace_version.txt").open("w") as f:
            f.write(v + "\n")
    except Exception:
        pass

    total_cost = 0.0
    for i, row in enumerate(remaining.itertuples(index=False), 1):
        iid = row.instance_id
        repo_root = repo_path(row.repo, row.base_commit)
        if not repo_root.exists():
            append_result(ROW, InstanceResult(
                instance_id=iid, repo=row.repo, base_commit=row.base_commit,
                retrieved_files=[], status="runtime_error",
                error=f"repo not cloned: {repo_root}",
            ))
            continue

        print(f"  [{i:3d}/{len(remaining)}] {iid}")
        res = _run_one_instance(
            iid, row.repo, row.base_commit, row.problem_statement, repo_root,
            args.max_budget_usd,
        )
        append_result(ROW, res)
        total_cost += res.cost_usd
        print(f"    {len(res.retrieved_files):2d} files | "
              f"in={res.input_tokens:>7d} out={res.output_tokens:>5d} "
              f"${res.cost_usd:.3f} | total ${total_cost:.2f} | "
              f"{res.wall_clock_s:.1f}s | {res.status}")

    print(f"=== vector complete: total ${total_cost:.2f} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
