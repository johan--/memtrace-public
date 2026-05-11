"""
Pre-flight environment check for Phase 2 runs.

Run this BEFORE invoking any row runner. It validates that the laptop has
every prerequisite the four rows need, and prints a clear checklist of what's
green vs what's missing. Exit code 0 if all required checks pass; 1 otherwise.

Usage:
    .venv/bin/python -m runners.check_env
    .venv/bin/python -m runners.check_env --row agentic
    .venv/bin/python -m runners.check_env --row memtrace

Per-row checks: pass `--row <name>` to only validate the prerequisites that
row needs. Without `--row`, every check is run.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Check:
    name: str
    rows: frozenset[str]   # which rows need this — empty means all
    detail: str = ""
    status: str = "pending"  # "ok" | "warn" | "fail" | "pending"


def _set(c: Check, status: str, detail: str) -> Check:
    c.status = status
    c.detail = detail
    return c


def check_python_venv() -> Check:
    c = Check(name="Python venv (.venv) reproducible", rows=frozenset())
    venv = Path(__file__).resolve().parent.parent / ".venv"
    if not venv.exists():
        return _set(c, "fail", f"{venv} missing — run `bash 05_repro.sh sample` to create it")
    try:
        out = subprocess.check_output([str(venv / "bin" / "python"), "--version"], text=True).strip()
        return _set(c, "ok", out)
    except Exception as e:
        return _set(c, "fail", f"venv python broken: {e}")


def check_anthropic_key() -> Check:
    c = Check(name="ANTHROPIC_API_KEY in env", rows=frozenset({"agentic", "memtrace"}))
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return _set(c, "fail", "not set; export ANTHROPIC_API_KEY=sk-ant-...")
    if not key.startswith("sk-ant-"):
        return _set(c, "warn", f"present but doesn't look like an Anthropic key (prefix={key[:7]}...)")
    return _set(c, "ok", f"present, length={len(key)}, prefix=sk-ant-…{key[-4:]}")


def check_claude_cli() -> Check:
    c = Check(name="Claude Code CLI in PATH", rows=frozenset({"agentic"}))
    path = shutil.which("claude")
    if not path:
        return _set(c, "fail", "not on PATH; install per https://docs.claude.com/claude-code")
    try:
        out = subprocess.check_output(["claude", "--version"], text=True, timeout=5).strip()
        return _set(c, "ok", f"{path} — {out}")
    except Exception as e:
        return _set(c, "warn", f"{path} — version check failed: {e}")


def check_memtrace_cli() -> Check:
    c = Check(name="Memtrace CLI version >= 0.3.87", rows=frozenset({"memtrace"}))
    path = shutil.which("memtrace")
    if not path:
        return _set(c, "fail", "not on PATH; install per https://github.com/syncable-dev/memtrace-public")
    try:
        out = subprocess.check_output(["memtrace", "--version"], text=True, timeout=5).strip()
        # Parse a version like "memtrace 0.3.88" or "0.3.88"
        token = out.split()[-1]
        major, minor, patch = (int(x) for x in token.split(".")[:3])
        if (major, minor, patch) < (0, 3, 87):
            return _set(c, "fail", f"version {token} below 0.3.87 (Apple Silicon dylib fix); upgrade required")
        return _set(c, "ok", f"{path} — {out}")
    except subprocess.CalledProcessError as e:
        return _set(c, "fail", f"version check failed: {e}")
    except Exception as e:
        return _set(c, "warn", f"version output unparseable: {e}")


def check_memtrace_mcp() -> Check:
    c = Check(name="Memtrace MCP server reachable", rows=frozenset({"memtrace"}))
    # Heuristic: if claude config has memtrace registered. Best-effort check.
    try:
        out = subprocess.check_output(["claude", "mcp", "list"], text=True, timeout=10)
        if "memtrace" in out.lower():
            return _set(c, "ok", "registered with Claude Code")
        return _set(c, "warn", "not visible in `claude mcp list` — register before the memtrace row")
    except Exception:
        return _set(c, "warn", "`claude mcp list` unavailable — verify manually before the memtrace row")


def check_disk_free(min_gb: int = 20) -> Check:
    c = Check(name=f"Disk free >= {min_gb} GB at .memdb path", rows=frozenset({"memtrace", "agentic"}))
    here = Path(__file__).resolve().parent.parent
    stat = shutil.disk_usage(here)
    free_gb = stat.free / (1024**3)
    if free_gb < min_gb:
        return _set(c, "fail", f"{free_gb:.1f} GB free; need >= {min_gb} GB")
    return _set(c, "ok", f"{free_gb:.1f} GB free at {here}")


def check_sentence_transformers() -> Check:
    c = Check(name="sentence-transformers importable (CodeRankEmbed variant)", rows=frozenset({"vector-coderankembed"}))
    venv_python = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
    try:
        out = subprocess.check_output(
            [str(venv_python), "-c", "import sentence_transformers; print(sentence_transformers.__version__)"],
            stderr=subprocess.STDOUT, text=True, timeout=15,
        ).strip()
        return _set(c, "ok", f"sentence-transformers {out}")
    except subprocess.CalledProcessError:
        return _set(c, "fail", "not installed; run `.venv/bin/pip install sentence-transformers`")
    except Exception as e:
        return _set(c, "warn", f"check failed: {e}")


def check_git() -> Check:
    c = Check(name="git in PATH (repo cloner)", rows=frozenset())
    path = shutil.which("git")
    if not path:
        return _set(c, "fail", "git not on PATH")
    try:
        out = subprocess.check_output(["git", "--version"], text=True, timeout=5).strip()
        return _set(c, "ok", out)
    except Exception as e:
        return _set(c, "warn", str(e))


def check_pinned_data() -> Check:
    c = Check(name="data/verified_500.parquet present + CSVs reproducible", rows=frozenset())
    here = Path(__file__).resolve().parent.parent
    parquet = here / "data" / "verified_500.parquet"
    if not parquet.exists():
        return _set(c, "fail", "data/verified_500.parquet missing — run `bash 05_repro.sh sample`")
    csv25 = here / "03_instances_25.csv"
    csv100 = here / "04_instances_100.csv"
    missing = [p.name for p in [csv25, csv100] if not p.exists()]
    if missing:
        return _set(c, "fail", f"missing: {missing} — run `bash 05_repro.sh sample`")
    return _set(c, "ok", f"parquet + 25-CSV + 100-CSV all present")


ALL_CHECKS = [
    check_python_venv,
    check_pinned_data,
    check_anthropic_key,
    check_claude_cli,
    check_memtrace_cli,
    check_memtrace_mcp,
    check_disk_free,
    check_sentence_transformers,
    check_git,
]


def run(row_filter: str | None = None) -> int:
    print(f"=== env precheck (row_filter={row_filter or 'all'}) ===\n")
    failures: list[Check] = []
    warnings: list[Check] = []
    for fn in ALL_CHECKS:
        c = fn()
        if row_filter and c.rows and row_filter not in c.rows:
            print(f"  [skip] {c.name}  (only required for {sorted(c.rows)})")
            continue
        glyph = {"ok": "✓", "warn": "!", "fail": "✗", "pending": "?"}[c.status]
        print(f"  [{glyph}] {c.name}")
        print(f"         {c.detail}")
        if c.status == "fail":
            failures.append(c)
        elif c.status == "warn":
            warnings.append(c)

    print()
    if failures:
        print(f"FAIL — {len(failures)} required check(s) not green:")
        for c in failures:
            print(f"  - {c.name}: {c.detail}")
        return 1
    if warnings:
        print(f"OK with warnings — {len(warnings)} non-blocking issue(s); verify manually before running affected rows.")
        return 0
    print("OK — all checks green.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--row",
        choices=["vector-default", "vector-coderankembed", "agentic", "memtrace"],
        default=None,
        help="Only validate the prerequisites for this specific row.",
    )
    args = ap.parse_args()
    return run(row_filter=args.row)


if __name__ == "__main__":
    sys.exit(main())
