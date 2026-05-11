"""
Memtrace runner — Claude Code headless + Memtrace MCP tool-call loop.

Frozen config (from prompts/memtrace_query.md):
  - Model: claude-sonnet-4-6
  - Tools: mcp__memtrace__{find_code, find_symbol, get_symbol_context,
                          get_impact, get_source_window, analyze_relationships}
  - Turn limit: 30
  - Output: JSON {"files": [...], "symbols": [...]} on last line

Per instance:
  1. Ensure the repo is indexed in Memtrace at `base_commit`
  2. Run `claude -p` with Memtrace MCP tools allowed and shell/grep DISALLOWED
  3. Parse final JSON for files + symbols
  4. Save trajectory + append per_instance.csv row

Requires:
  - ANTHROPIC_API_KEY
  - Memtrace CLI >= 0.3.87 + registered MCP server (verified via check_env)

Usage:
    .venv/bin/python -m runners.run_memtrace --csv 03_instances_25.csv --max-budget-usd 2
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

SYSTEM_PROMPT = """\
You are a code-retrieval agent with access to a graph database of the
repository. The graph knows every symbol, its file, its callers, its
callees, and its type relationships. You DO NOT have shell access. You
DO NOT have file-read access. You can only query the graph.

Your task: given a GitHub issue, identify the files AND the symbols that
need to be modified to resolve it.

Available tools: find_code, find_symbol, get_symbol_context, get_impact,
get_source_window, analyze_relationships.

Rules:
1. Output your final answer as a JSON object on the LAST line, formatted
   exactly as:
   {"files": ["path/to/file1.py", ...], "symbols": ["mod.Class.method", ...]}
2. File paths repository-relative, forward-slash separated.
3. Symbol names fully qualified as Memtrace returns them.
4. At most 30 turns. Budget tool calls.
5. The issue text is the only spec. No clarification.

Strategy hint (not enforced): start with find_code on key terms from the
issue, then use get_symbol_context or get_impact to expand the candidate
set. Use get_source_window only when you need to disambiguate.

Work step by step. When confident, emit the JSON and stop.
"""

USER_TEMPLATE = """\
Repository: {repo}
Base commit: {base_commit}
Repository root: {repo_root}

Issue:
<<<
{problem_statement}
>>>

Identify the files AND symbols that need to be modified.
"""

# Memtrace MCP tools — must be allowed; nothing else is.
ALLOWED_TOOLS = [
    "mcp__memtrace__find_code",
    "mcp__memtrace__find_symbol",
    "mcp__memtrace__get_symbol_context",
    "mcp__memtrace__get_impact",
    "mcp__memtrace__get_source_window",
    "mcp__memtrace__analyze_relationships",
]


def _ensure_indexed(repo_root: Path, verbose: bool = True) -> None:
    """Index the cloned repo with Memtrace. Idempotent (Memtrace handles).
    Skips silently if the .memdb is already present."""
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


def _parse_files_and_symbols(text: str) -> tuple[list[str], list[str], str]:
    if not text:
        return [], [], "parse_error"
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                continue
            files = obj.get("files")
            if not isinstance(files, list):
                continue
            symbols = obj.get("symbols") or []
            if not isinstance(symbols, list):
                symbols = []
            return [str(f) for f in files], [str(s) for s in symbols], "ok"
        except json.JSONDecodeError:
            continue
    return [], [], "parse_error"


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
            retrieved_files=[], retrieved_symbols=[],
            status="runtime_error", error=f"indexing failed: {e}",
        )

    user_msg = USER_TEMPLATE.format(
        repo=repo, base_commit=base_commit, repo_root=str(repo_root),
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

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired as e:
        return InstanceResult(
            instance_id=instance_id, repo=repo, base_commit=base_commit,
            retrieved_files=[], retrieved_symbols=[],
            status="timeout", error=f"15m timeout: {e}",
            wall_clock_s=time.time() - t0,
        )

    wall = time.time() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        save_trajectory("memtrace", instance_id, {"stdout": stdout, "stderr": stderr})
        return InstanceResult(
            instance_id=instance_id, repo=repo, base_commit=base_commit,
            retrieved_files=[], retrieved_symbols=[],
            status="parse_error",
            error="Claude Code envelope not parseable",
            wall_clock_s=wall,
        )

    result_text = envelope.get("result") or envelope.get("response") or ""
    files, symbols, parse_status = _parse_files_and_symbols(result_text)

    usage = envelope.get("usage", {}) if isinstance(envelope.get("usage"), dict) else {}
    input_tok = int(usage.get("input_tokens", 0))
    output_tok = int(usage.get("output_tokens", 0))
    cache_read = int(usage.get("cache_read_input_tokens", 0))
    cost = float(envelope.get("total_cost_usd", 0.0)) or estimate_cost_usd(input_tok, output_tok, cache_read)
    turns = int(envelope.get("num_turns", 0))

    save_trajectory("memtrace", instance_id, envelope)

    return InstanceResult(
        instance_id=instance_id, repo=repo, base_commit=base_commit,
        retrieved_files=files, retrieved_symbols=symbols,
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

    done = load_completed_instances("memtrace")
    remaining = df[~df["instance_id"].isin(done)].reset_index(drop=True)
    print(f"=== memtrace runner csv={csv_path.name} ===")
    print(f"  {len(df)} total, {len(done)} done, {len(remaining)} to run")
    print(f"  model={MODEL}, tools={ALLOWED_TOOLS}, per_task_cap=${args.max_budget_usd}")

    if remaining.empty:
        return 0

    write_run_meta("memtrace", {
        "row": "memtrace",
        "model": MODEL,
        "turn_limit": TURN_LIMIT,
        "max_budget_usd_per_task": args.max_budget_usd,
        "allowed_tools": ALLOWED_TOOLS,
        "system_prompt": SYSTEM_PROMPT,
        "csv": str(csv_path),
        "n_total": int(len(df)),
        "python": sys.version,
        "platform": platform.platform(),
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    # Capture Memtrace version once
    try:
        v = subprocess.check_output(["memtrace", "--version"], text=True).strip()
        with (HERE / "results" / "memtrace" / "memtrace_version.txt").open("w") as f:
            f.write(v + "\n")
    except Exception:
        pass

    total_cost = 0.0
    for i, row in enumerate(remaining.itertuples(index=False), 1):
        iid = row.instance_id
        repo_root = repo_path(row.repo, row.base_commit)
        if not repo_root.exists():
            append_result("memtrace", InstanceResult(
                instance_id=iid, repo=row.repo, base_commit=row.base_commit,
                retrieved_files=[], retrieved_symbols=[],
                status="runtime_error",
                error=f"repo not cloned: {repo_root}",
            ))
            continue

        print(f"  [{i:3d}/{len(remaining)}] {iid}")
        res = _run_one_instance(
            iid, row.repo, row.base_commit, row.problem_statement, repo_root,
            args.max_budget_usd,
        )
        append_result("memtrace", res)
        total_cost += res.cost_usd
        print(f"    {len(res.retrieved_files):2d} files {len(res.retrieved_symbols):2d} symbols | "
              f"in={res.input_tokens:>7d} out={res.output_tokens:>5d} "
              f"${res.cost_usd:.3f} | total ${total_cost:.2f} | "
              f"{res.wall_clock_s:.1f}s | {res.status}")

    print(f"=== memtrace complete: total ${total_cost:.2f} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
