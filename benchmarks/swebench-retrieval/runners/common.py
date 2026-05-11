"""
Shared utilities for all runners.

Path conventions:
    HERE                   = benchmarks/swebench-retrieval/
    HERE/work/repos/<r>/<c>  cloned repository at base_commit
    HERE/results/<row>/per_instance.csv   incremental per-instance results
    HERE/results/<row>/run_meta.json      single per-row metadata blob
    HERE/results/<row>/trajectories/<id>.json   full reasoning trace
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
WORK = HERE / "work"
REPOS = WORK / "repos"
RESULTS = HERE / "results"

SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".pyx",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".rb", ".go", ".rs", ".java", ".kt", ".scala",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cxx", ".hxx",
    ".cs", ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh",
    ".sql", ".pl", ".lua",
}

EXCLUDE_DIR_NAMES = {
    "tests", "test", "testing",
    "docs", "doc", "documentation",
    "examples", "example", "samples",
    ".git", "node_modules", "vendor", "third_party", "thirdparty",
    "__pycache__", ".tox", ".venv", "venv", ".env", "env",
    "build", "dist", ".cache", ".pytest_cache", ".mypy_cache",
}


def repo_safe(repo: str) -> str:
    return repo.replace("/", "__")


def repo_path(repo: str, base_commit: str) -> Path:
    return REPOS / repo_safe(repo) / base_commit


def is_source_file(p: Path) -> bool:
    if p.suffix not in SOURCE_EXTENSIONS:
        return False
    if any(part in EXCLUDE_DIR_NAMES for part in p.parts):
        return False
    return True


def iter_source_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and is_source_file(p):
            yield p


# ---------- per_instance.csv I/O ----------

def per_instance_path(row_name: str) -> Path:
    return RESULTS / row_name / "per_instance.csv"


def trajectory_path(row_name: str, instance_id: str) -> Path:
    return RESULTS / row_name / "trajectories" / f"{instance_id}.json"


def load_completed_instances(row_name: str) -> set[str]:
    p = per_instance_path(row_name)
    if not p.exists():
        return set()
    try:
        import pandas as pd
        df = pd.read_csv(p)
        return set(df["instance_id"].astype(str).tolist())
    except Exception:
        return set()


@dataclass
class InstanceResult:
    instance_id: str
    repo: str
    base_commit: str
    retrieved_files: list[str]
    retrieved_symbols: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    wall_clock_s: float = 0.0
    status: str = "ok"   # "ok" | "parse_error" | "runtime_error" | "timeout"
    error: str = ""
    turns_used: int = 0

    def to_csv_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["retrieved_files"] = json.dumps(d["retrieved_files"])
        d["retrieved_symbols"] = json.dumps(d["retrieved_symbols"])
        return d


def append_result(row_name: str, result: InstanceResult) -> None:
    """Append a single InstanceResult to results/<row_name>/per_instance.csv."""
    import pandas as pd
    p = per_instance_path(row_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([result.to_csv_row()])
    if p.exists():
        df.to_csv(p, mode="a", header=False, index=False)
    else:
        df.to_csv(p, index=False)


def save_trajectory(row_name: str, instance_id: str, trajectory: dict | list) -> None:
    p = trajectory_path(row_name, instance_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(trajectory, f, indent=2, default=str)


def write_run_meta(row_name: str, meta: dict) -> None:
    p = RESULTS / row_name / "run_meta.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    meta.setdefault("written_at_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with p.open("w") as f:
        json.dump(meta, f, indent=2, default=str)


# ---------- pricing ----------

# Sonnet 4.6 list price as of 2026-05. Update if Anthropic changes pricing.
SONNET_INPUT_PER_M = 3.00
SONNET_OUTPUT_PER_M = 15.00
SONNET_CACHE_READ_PER_M = 0.30   # 90% discount on cache hits


def estimate_cost_usd(input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> float:
    """Cost in USD given input/output token counts. Assumes Sonnet 4.6."""
    return (
        (input_tokens - cache_read_tokens) / 1_000_000 * SONNET_INPUT_PER_M
        + cache_read_tokens / 1_000_000 * SONNET_CACHE_READ_PER_M
        + output_tokens / 1_000_000 * SONNET_OUTPUT_PER_M
    )


def env_required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"required env var {name} is not set")
    return v
