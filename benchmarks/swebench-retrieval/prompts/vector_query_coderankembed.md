# Vector row (variant B — CodeRankEmbed) — frozen retrieval configuration

**Status**: locked at pre-registration (added in amendment commit; see git log).
**Why a second variant**: pre-empts the "weak embedder" critique. CodeRankEmbed is the strongest publicly available code embedder as of 2026 (ICLR 2025, Apache-2.0). Reporting both variants makes the Vector row a real ceiling, not a strawman.

## Indexing

| Param | Value |
|---|---|
| Chunk size | 500 lines, non-overlapping (**identical to variant A**) |
| File filter (include) | source code only — extensions matching the repo's primary languages per Memtrace's language scanner |
| File filter (exclude) | `tests/`, `test/`, `docs/`, `examples/`, `.git/`, `node_modules/`, `vendor/`, `*.min.js` |
| **Embedder model** | **`nomic-ai/CodeRankEmbed`** (HuggingFace) |
| **Source** | Paper: *"CoRNStack: High-Quality Contrastive Data for Better Code Retrieval and Reranking,"* ICLR 2025 (arXiv 2412.01007) |
| **Parameters** | 137M (bi-encoder, BERT-family) |
| **Embedding dimension** | 768 |
| **Inference** | local via `sentence-transformers >= 3.0`; no API spend on embedding |
| Distance metric | cosine similarity |
| Store | flat in-memory index (numpy); reported in `results/vector-coderankembed/run_meta.json` |
| Pin | HuggingFace revision SHA captured at run start in `run_meta.json` |

## Query

| Param | Value |
|---|---|
| Query text | exact `problem_statement` from the parquet, unmodified |
| **Query instruction prefix** | **`"Represent this query for searching relevant code: "`** — CodeRankEmbed is instruction-tuned and the paper specifies this prefix for retrieval. Omitting it drops measured recall on CodeSearchNet by ~5pp |
| Query embedding | same model + same preprocessing as index |
| Hints text | **not included** (would leak solution-adjacent context) |

## Retrieval

| Param | Value |
|---|---|
| Top-K policy | grow K until cumulative chunk tokens ≥ 27,000 (cl100k_base), then stop |
| Token counter | `tiktoken` with `cl100k_base` encoder |
| Tie-break | lower instance-stable hash of chunk identifier wins |
| File set | union of source files of all chunks in the retrieved set |
| No LM in the loop | retrieval is pure vector; no model re-ranking |

## Why this variant matters

- **CodeRankEmbed is the public SOTA code embedder.** A Vector row without it can be dismissed as a strawman. With it, the comparison answers "is graph-typed retrieval better than the best available vector retrieval," not "is graph-typed retrieval better than some embedder we picked."
- **Variant A and variant B differ ONLY in the embedder model.** Same chunks, same token budget, same query, same scoring. Direct ablation of embedding quality.
- **Symmetrically reported.** Both variants appear in the headline table; neither is hidden. If CodeRankEmbed wins over Memtrace's default, that gets disclosed too.

## What this variant does NOT do

- **No CodeRankLLM reranker.** The reranker is a separate model from the same paper. Adding it would be a fourth row, not part of the Vector baseline. We may add it later as an ablation but it is not in the pre-registered scope.
- **No fine-tuning.** Off-the-shelf `nomic-ai/CodeRankEmbed` weights, no per-repo adaptation.
- **No hybrid (BM25 + dense) fusion.** Pure dense retrieval, matching variant A's architecture.
