"""
Agentic runner — Claude Code headless mode, grep/glob/read tool loop.

Frozen config (from prompts/agentic_system.md):
  - Model: claude-sonnet-4-6
  - Tools: Bash(git *) + Bash(rg *) + Bash(grep *) + Bash(find *) + Grep + Glob + Read
  - Turn limit: 30
  - Output: JSON {"files": [...]} on last line of response

Per instance:
  1. Render the user message from problem_statement
  2. Invoke `claude -p --bare ...` against the cloned repo
  3. Parse the final JSON from stdout
  4. Save full trajectory under results/agentic/trajectories/<id>.json
  5. Append per_instance.csv row

Resumable. Per-task budget cap via --max-budget-usd.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    .venv/bin/python -m runners.run_agentic --csv 03_instances_25.csv --max-budget-usd 2
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
You are a code-retrieval agent. You will be given a GitHub issue from an
open-source Python repository. Your task is to identify the files in the
repository that would need to be modified to resolve the issue.

You have access to: Bash (read-only commands), Grep, Glob, Read.

Rules:
1. Output your final answer as a JSON object on the LAST line of your
   response, formatted exactly as:
   {"files": ["path/to/file1.py", "path/to/file2.py"]}
   File paths must be repository-relative, forward-slash separated.
2. You have at most 30 turns. Budget your tool calls.
3. Do NOT modify any files. Do NOT run tests. Read-only investigation only.
4. Do NOT search outside the repository root.
5. The issue text is the only spec. Do not request clarification.

Work step by step. When you are confident in your answer, emit the JSON
object and stop.
"""

USER_TEMPLATE = """\
Repository: {repo}
Base commit: {base_commit}
Repository root: {repo_root}

Issue:
<<<
{problem_statement}
>>>

Identify the files that need to be modified to resolve this issue.
"""

# Read-only tool set. Bash is restricted via the pattern syntax so the agent
# can run search-style commands but cannot mutate state.
ALLOWED_TOOLS = [
    "Bash(rg *)", "Bash(grep *)", "Bash(find *)", "Bash(ls *)",
    "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(wc *)",
    "Bash(git log *)", "Bash(git show *)", "Bash(git ls-files *)",
    "Grep", "Glob", "Read",
]


def _parse_files_from_text(text: str) -> tuple[list[str], str]:
    """Find a JSON object {"files": [...]} on a recent line. Returns (files, status)."""
    if not text:
        return [], "parse_error"
    # Scan lines from the end backwards for the first parseable JSON object.
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and isinstance(obj.get("files"), list):
                files = [str(f) for f in obj["files"]]
                return files, "ok"
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
            retrieved_files=[], status="timeout",
            error=f"15m timeout: {e}",
            wall_clock_s=time.time() - t0,
        )

    wall = time.time() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # Claude Code --output-format=json emits a JSON object with shape:
    # {"role":"system",...,"result":"...","total_cost_usd":...,"num_turns":..., ...}
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        save_trajectory("agentic", instance_id, {"stdout": stdout, "stderr": stderr})
        return InstanceResult(
            instance_id=instance_id, repo=repo, base_commit=base_commit,
            retrieved_files=[], status="parse_error",
            error="Claude Code envelope not parseable",
            wall_clock_s=wall,
        )

    result_text = envelope.get("result") or envelope.get("response") or ""
    files, parse_status = _parse_files_from_text(result_text)

    usage = envelope.get("usage", {}) if isinstance(envelope.get("usage"), dict) else {}
    input_tok = int(usage.get("input_tokens", 0))
    output_tok = int(usage.get("output_tokens", 0))
    cache_read = int(usage.get("cache_read_input_tokens", 0))
    cost = float(envelope.get("total_cost_usd", 0.0)) or estimate_cost_usd(input_tok, output_tok, cache_read)
    turns = int(envelope.get("num_turns", 0))

    save_trajectory("agentic", instance_id, envelope)

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
    ap.add_argument("--max-budget-usd", type=float, default=2.0,
                    help="per-instance hard cap (Claude Code --max-budget-usd)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    env_required("ANTHROPIC_API_KEY")
    csv_path = (HERE / args.csv) if not args.csv.is_absolute() else args.csv
    df = pd.read_csv(csv_path)
    dataset = pd.read_parquet(HERE / "data" / "verified_500.parquet")
    df = df.merge(dataset[["instance_id", "problem_statement"]], on="instance_id", how="left")

    if args.limit:
        df = df.head(args.limit)

    done = load_completed_instances("agentic")
    remaining = df[~df["instance_id"].isin(done)].reset_index(drop=True)
    print(f"=== agentic runner csv={csv_path.name} ===")
    print(f"  {len(df)} total, {len(done)} done, {len(remaining)} to run")
    print(f"  model={MODEL}, turn_limit={TURN_LIMIT}, per_task_cap=${args.max_budget_usd}")

    if remaining.empty:
        return 0

    write_run_meta("agentic", {
        "row": "agentic",
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

    total_cost = 0.0
    for i, row in enumerate(remaining.itertuples(index=False), 1):
        iid = row.instance_id
        repo_root = repo_path(row.repo, row.base_commit)
        if not repo_root.exists():
            append_result("agentic", InstanceResult(
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
        append_result("agentic", res)
        total_cost += res.cost_usd
        print(f"    {len(res.retrieved_files):2d} files | "
              f"in={res.input_tokens:>7d} out={res.output_tokens:>5d} "
              f"${res.cost_usd:.3f} | total ${total_cost:.2f} | "
              f"{res.wall_clock_s:.1f}s | {res.status}")

    print(f"=== agentic complete: total ${total_cost:.2f} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
