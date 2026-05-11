# Vector row (variant A — Memtrace's default embedder) — frozen retrieval configuration

**Status**: locked at pre-registration. Any change requires bumping the round version.
**Variant identity**: this is variant A. Variant B is in `vector_query_coderankembed.md`. The two share every parameter except the embedder model.

## Indexing

| Param | Value |
|---|---|
| Chunk size | 500 lines, non-overlapping |
| File filter (include) | source code only — extensions matching the repo's primary languages per Memtrace's language scanner |
| File filter (exclude) | `tests/`, `test/`, `docs/`, `examples/`, `.git/`, `node_modules/`, `vendor/`, `*.min.js` |
| **Embedder model** | **`jinaai/jina-embeddings-v2-base-code`** — same model Memtrace uses internally for the semantic leg of its hybrid retrieval |
| **Source** | https://huggingface.co/jinaai/jina-embeddings-v2-base-code (Apache-2.0) |
| **Parameters** | 161M (BERT-base architecture, instruction-following) |
| **Embedding dimension** | 768 |
| **Inference** | local via `sentence-transformers >= 3.0`; no API spend on embedding |
| **Pin** | HuggingFace revision SHA captured at run start in `run_meta.json` |
| Distance metric | cosine similarity |
| Store | flat in-memory index (numpy or hnswlib, configurable; reported in `results/vector/run_meta.json`) |

## Query

| Param | Value |
|---|---|
| Query text | exact `problem_statement` from the parquet, unmodified |
| Query embedding | same embedder model + same preprocessing as index |
| Hints text | **not included** (would leak solution-adjacent context) |

## Retrieval

| Param | Value |
|---|---|
| Top-K policy | grow K until cumulative chunk tokens ≥ 27,000 (cl100k_base), then stop |
| Token counter | `tiktoken` with `cl100k_base` encoder |
| Tie-break | lower instance-stable hash of chunk identifier wins |
| File set | union of source files of all chunks in the retrieved set |
| No LM in the loop | retrieval is pure vector; no model re-ranking |

## Why these choices

- **500-line chunks, no overlap**: standard RAG default; reviewers cannot accuse us of an ablation choice.
- **27K token budget**: matches Princeton's BM25-27K setting in the SWE-bench paper. Direct comparability to published numbers.
- **No LM re-ranking**: keeps the vector row as a clean baseline. Adding a re-ranker would be a separate ablation row, not the vector baseline.
- **Excluding `tests/` etc.**: keeps the corpus to actual implementation code. The same exclusion is applied to the agentic row (via prompt) and the Memtrace row (via the indexer's default).
