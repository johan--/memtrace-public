"""
Vector runner — handles both variants via --embedder flag.

variant A:  --embedder jinaai/jina-embeddings-v2-base-code  -> writes results/vector-default/
variant B:  --embedder nomic-ai/CodeRankEmbed                -> writes results/vector-coderankembed/

Per instance:
  1. Load problem_statement from the dataset
  2. Chunk every source file in the repo into 500-line non-overlapping chunks
  3. Embed all chunks (sentence-transformers, batched)
  4. Embed the query (with CodeRankEmbed's instruction prefix if applicable)
  5. Cosine top-K until cumulative chunk tokens >= 27,000 (cl100k_base)
  6. Emit the union of chunks' source files as retrieved_files

No API spend (everything is local inference on M3 Max).

Idempotent: skips instances already present in per_instance.csv.

Usage:
    .venv/bin/python -m runners.run_vector --csv 03_instances_25.csv \\
        --embedder jinaai/jina-embeddings-v2-base-code --row vector-default

    .venv/bin/python -m runners.run_vector --csv 04_instances_100.csv \\
        --embedder nomic-ai/CodeRankEmbed --row vector-coderankembed
"""
from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from runners.common import (
    HERE,
    InstanceResult,
    append_result,
    iter_source_files,
    load_completed_instances,
    repo_path,
    write_run_meta,
)

TOKEN_BUDGET = 27_000
CHUNK_LINES = 500
BATCH_SIZE = 32
QUERY_PREFIX_CODERANKEMBED = "Represent this query for searching relevant code: "


def _chunk_file(path: Path) -> list[tuple[str, str]]:
    """Return list of (chunk_text, source_file_relpath) tuples."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    lines = text.splitlines()
    chunks = []
    for i in range(0, len(lines), CHUNK_LINES):
        chunk = "\n".join(lines[i : i + CHUNK_LINES])
        if chunk.strip():
            chunks.append((chunk, str(path)))
    return chunks


def _build_index(repo_root: Path) -> tuple[list[str], list[str]]:
    """Walk the repo, chunk every source file, return (chunk_texts, chunk_source_paths)."""
    texts: list[str] = []
    sources: list[str] = []
    for p in iter_source_files(repo_root):
        rel = str(p.relative_to(repo_root))
        for chunk_text, _ in _chunk_file(p):
            texts.append(chunk_text)
            sources.append(rel)
    return texts, sources


def _retrieve(
    model,
    tokenizer,
    query: str,
    query_prefix: str,
    texts: list[str],
    sources: list[str],
    token_budget: int = TOKEN_BUDGET,
) -> list[str]:
    """Embed query + chunks, retrieve top-K until token budget hit, return file set."""
    if not texts:
        return []

    chunk_emb = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False,
                              convert_to_numpy=True, normalize_embeddings=True)
    query_text = query_prefix + query if query_prefix else query
    query_emb = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    scores = chunk_emb @ query_emb  # cosine since normalized
    # Sort indices by descending score. Stable tie-break by chunk index.
    order = np.argsort(-scores, kind="stable")

    retrieved_files: set[str] = set()
    cumulative_tokens = 0
    for idx in order:
        idx_i = int(idx)
        n_tok = len(tokenizer.encode(texts[idx_i]))
        if cumulative_tokens + n_tok > token_budget and retrieved_files:
            break
        cumulative_tokens += n_tok
        retrieved_files.add(sources[idx_i])
        if cumulative_tokens >= token_budget:
            break
    return sorted(retrieved_files)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--embedder", required=True, help="HuggingFace model id")
    ap.add_argument("--row", required=True, help="results row name (e.g. vector-default)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N instances (sanity)")
    args = ap.parse_args()

    csv_path = (HERE / args.csv) if not args.csv.is_absolute() else args.csv
    df = pd.read_csv(csv_path)
    dataset = pd.read_parquet(HERE / "data" / "verified_500.parquet")

    # Join on instance_id to pick up problem_statement.
    df = df.merge(dataset[["instance_id", "problem_statement"]], on="instance_id", how="left")
    assert df["problem_statement"].notna().all(), "missing problem_statement after merge"

    if args.limit:
        df = df.head(args.limit)

    # Skip already-done instances (idempotent resume).
    done = load_completed_instances(args.row)
    remaining = df[~df["instance_id"].isin(done)].reset_index(drop=True)
    print(f"=== vector runner row={args.row} csv={csv_path.name} ===")
    print(f"  {len(df)} total, {len(done)} already done, {len(remaining)} to run")
    print(f"  embedder={args.embedder}")

    if remaining.empty:
        print("  nothing to do.")
        return 0

    # Load model + tokenizer once.
    print(f"  loading {args.embedder} ...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    import tiktoken
    model = SentenceTransformer(args.embedder, trust_remote_code=True)
    tokenizer = tiktoken.get_encoding("cl100k_base")
    print(f"  loaded in {time.time()-t0:.1f}s")

    query_prefix = QUERY_PREFIX_CODERANKEMBED if "CodeRankEmbed" in args.embedder else ""

    write_run_meta(args.row, {
        "row": args.row,
        "embedder": args.embedder,
        "query_prefix": query_prefix,
        "chunk_lines": CHUNK_LINES,
        "token_budget": TOKEN_BUDGET,
        "csv": str(csv_path),
        "n_total": int(len(df)),
        "python": sys.version,
        "platform": platform.platform(),
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    for i, row in enumerate(remaining.itertuples(index=False), 1):
        iid = row.instance_id
        repo_root = repo_path(row.repo, row.base_commit)
        print(f"  [{i:3d}/{len(remaining)}] {iid}")

        if not repo_root.exists():
            print(f"    skip — repo not cloned at {repo_root}")
            append_result(args.row, InstanceResult(
                instance_id=iid, repo=row.repo, base_commit=row.base_commit,
                retrieved_files=[], status="runtime_error",
                error=f"repo not cloned: {repo_root}",
            ))
            continue

        t_start = time.time()
        try:
            texts, sources = _build_index(repo_root)
            files = _retrieve(model, tokenizer, row.problem_statement, query_prefix, texts, sources)
            append_result(args.row, InstanceResult(
                instance_id=iid, repo=row.repo, base_commit=row.base_commit,
                retrieved_files=files,
                wall_clock_s=time.time() - t_start,
            ))
            print(f"    {len(files)} files retrieved in {time.time()-t_start:.1f}s")
        except Exception as e:  # noqa: BLE001
            append_result(args.row, InstanceResult(
                instance_id=iid, repo=row.repo, base_commit=row.base_commit,
                retrieved_files=[], status="runtime_error",
                error=f"{type(e).__name__}: {e}",
                wall_clock_s=time.time() - t_start,
            ))
            print(f"    FAIL: {e}")

    print(f"=== {args.row} complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
