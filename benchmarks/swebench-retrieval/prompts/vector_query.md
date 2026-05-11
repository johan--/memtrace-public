# Vector row — frozen retrieval configuration

**Status**: locked at pre-registration. Any change requires bumping the round version.

## What this row is

Pure dense-vector (semantic) retrieval over the same indexed corpus the Memtrace row uses. **Same indexer, same embedder, same chunking** — the only difference vs the Memtrace row is that BM25, exact-symbol, and graph-expansion legs are zeroed at the RRF fusion stage, and the agent is restricted to `find_code` only.

This is **architecturally cleaner than running a separate sentence-transformers pipeline**: it directly ablates "what does the graph add over pure vector retrieval?" on the same corpus, with no embedder confound.

## Indexing

| Param | Value |
|---|---|
| Indexer | Memtrace ≥ 0.3.92 |
| Embedder | Memtrace's default: **`jinaai/jina-embeddings-v2-base-code`** (161M, 768-dim) |
| Backend | ONNX Runtime (Memtrace's native pipeline) |
| Chunking | per Memtrace's symbol-level scanner (AST-anchored, not 500-line slices) |
| Index state | shared with the Memtrace row — single `.memdb` per `(repo, base_commit)` |

## Retrieval

| Param | Value |
|---|---|
| Tool | `mcp__memtrace__find_code` (only) |
| RRF weights | **`VECTOR=1.0, BM25=0.0, EXACT=0.0, GRAPH=0.0`** — zeroes every leg except dense semantic |
| Env vars set per invocation | `MEMTRACE_RRF_BM25_WEIGHT=0.0`, `MEMTRACE_RRF_EXACT_WEIGHT=0.0`, `MEMTRACE_RRF_GRAPH_WEIGHT=0.0`, `MEMTRACE_RRF_VECTOR_WEIGHT=1.0` |
| Query | exact `problem_statement` from parquet, no `hints_text` |
| Result extraction | union of `file_path` fields across all `find_code` calls in the agent's session |

## LM-driver

| Param | Value |
|---|---|
| Harness | Claude Code `-p` (`--bare`) |
| Model | `claude-sonnet-4-6` |
| Temperature | 0, max_tokens 8192, no retries |
| Turn limit | 30 |
| Tools allowed | `mcp__memtrace__find_code` |
| Tools disallowed | every other Memtrace MCP tool, Bash, Grep, Glob, Read, Edit, Write |
| System prompt | frozen — see `runners/run_vector.py:SYSTEM_PROMPT` |

## Why this design

- **Same embedder as the Memtrace row.** A reviewer asking "did you use a SOTA code embedder?" gets the answer "We used Jina-code-v2-base-code, the same model Memtrace ships with. A separate embedder ablation is a follow-up round, not part of this comparison."
- **Direct ablation.** The only differences vs the Memtrace row are RRF weights and tool inventory. Same code path, same corpus, same parsing.
- **No Python embedding pipeline.** Earlier sentence-transformers approach used 40+ GB RAM on MPS and 30+ min/instance on CPU. Memtrace's native Rust+ONNX pipeline (which already runs on this machine) does the same work in minutes with <8 GB RAM.

## What this row does NOT do

- **No CodeRankEmbed comparison.** Pluggable embedders is a future feature; this round uses Memtrace's shipped Jina-code only.
- **No BM25-only baseline.** Could be added as a fourth row by flipping the weights (`BM25=1, others=0`); not in scope for this round.
- **No graph expansion.** That's the wedge the Memtrace row introduces.
