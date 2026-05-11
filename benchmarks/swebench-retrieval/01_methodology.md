# Methodology — SWE-bench Verified retrieval, Vector vs Agentic vs Memtrace

**Round**: SWE-bench retrieval comparison
**Status**: Pre-registration (Phase 1). No run yet.
**Last touched**: see git log of this file.

---

## 1. What this measures

**Task**: given a SWE-bench Verified `problem_statement`, retrieve the set of source files the human PR modified. No code execution. No patch generation. Pure retrieval.

**Metric**: file-level recall of gold-patch files within the retrieved file set, evaluated by Princeton's `swebench.inference.make_datasets.eval_retrieval`. We additionally report **symbol-level recall** for the Memtrace row only (vector and agentic operate on chunks/files and cannot produce a symbol set without reduction).

**Why retrieval-only**: this is the comparison made in the slide we are answering. The SWE-bench leaderboard tracks resolve@1 only, so this round publishes **off-leaderboard** (blog/preprint).

---

## 2. Datasets pinned

| Dataset | Source | Pin |
|---|---|---|
| SWE-bench Verified (500 instances) | `SWE-bench/SWE-bench_Verified` on HuggingFace | parquet sha256 captured in `data/verified_500.parquet`; revision pin recorded in `02_sampling.py` |
| Headline sample (n=25) | derived from the above by `02_sampling.py` | `03_instances_25.csv` |
| Appendix sample (n=100) | derived from the above by `02_sampling.py` | `04_instances_100.csv` |

The pinned parquet is committed to this folder. Anyone re-running re-derives the CSVs bit-identically (verified by sha256 in the script output).

---

## 3. Sampling protocol

- **Population**: SWE-bench Verified (500 instances; 12 Python repos; 4 difficulty buckets, range 2013-01 → 2023-08).
- **Stratification**: proportional allocation by `difficulty` using the largest-remainder method. Repo distribution emerges naturally; we do **not** force per-repo quotas because Verified is repo-imbalanced (django/django = 46.2%, pallets/flask = 0.2%) and forcing uniformity would produce an unrepresentative sample.
- **Seed**: `42`, passed to `numpy.random.default_rng`. Deterministic across platforms with `numpy >= 2.0`.
- **Within each difficulty bucket**: instance_ids sorted ascending, then `rng.choice(replace=False)`.
- **Independence**: n=25 and n=100 are independent stratified draws from the same seed. Overlap is informational, not constrained.

### Resulting distribution

| Bucket | Verified-500 | n=25 | n=100 |
|---|---:|---:|---:|
| `<15 min fix` | 194 (38.8%) | 10 | 39 |
| `15 min - 1 hour` | 261 (52.2%) | 13 | 52 |
| `1-4 hours` | 42 (8.4%) | 2 | 8 |
| `>4 hours` | 3 (0.6%) | 0 | 1 |
| **Total** | **500** | **25** | **100** |

| Repo coverage | n=25 | n=100 |
|---|---:|---:|
| Repos with ≥1 instance | 6 / 12 | 9 / 12 |

Repos missing from n=100 (`mwaskom/seaborn`, `pallets/flask`, `psf/requests`) collectively account for 11 / 500 = 2.2% of Verified; their omission is a side-effect of small samples, disclosed but not corrected.

---

## 4. Retrieval metric — exact definition

**Gold set** for instance `i`: the set of files modified by `patch[i]` (the human PR's diff). Extracted from the `patch` field of the parquet by parsing unified-diff headers.

**Retrieved set** for instance `i`, row `r`: the set of files that retrieval row `r` surfaces for instance `i`, subject to the row's token budget.

**Per-instance score**: `|gold ∩ retrieved| / |gold|` (recall). A "hit" means recall = 1.0 (all gold files retrieved). A "miss" is recall < 1.0.

**Headline number per row**: mean per-instance recall, reported with **Wilson 95% CI**. Bare percentages are not acceptable at n=25.

**Symbol-level recall (Memtrace row only)**: for each instance, parse the gold patch's hunks to extract `(file, function_or_class_name)` pairs. Score = |gold_symbols ∩ retrieved_symbols| / |gold_symbols|. Vector and agentic do not produce symbol sets natively; we do not synthesize them from chunks/files to keep apples-to-apples honest.

---

## 5. The three rows — frozen specs

> **Amendment** (post-`7a5f49b`, pre-results): the Vector row is now an ablation of the Memtrace row, not a separate pipeline. Same indexer (Memtrace native Rust + ONNX), same embedder (Jina-code), same chunking — the only differences are (a) RRF weights at fusion, and (b) tool inventory available to the LM. This replaces the original sentence-transformers-based Vector variants A+B (and the CodeRankEmbed comparison), which proved both slow and methodologically noisy.

### Vector row
- **Indexer**: Memtrace ≥ 0.3.92, default tier, per-repo `.memdb` pinned to the instance's `base_commit`. **Same `.memdb` shared with the Memtrace row.**
- **Embedder**: Memtrace's default — `jinaai/jina-embeddings-v2-base-code` (161M, 768-dim).
- **Harness**: Claude Code `-p` (`--bare`), `claude-sonnet-4-6`, temperature 0, max_tokens 8192, no retries.
- **Tools allowed**: `mcp__memtrace__find_code` (only). **Disallowed**: every other Memtrace MCP tool, Bash, Grep, Glob, Read, Edit, Write.
- **RRF weights** (set per-invocation via env): `VECTOR=1.0, BM25=0.0, EXACT=0.0, GRAPH=0.0` — zeroes every leg except dense semantic at the fusion stage.
- **System prompt**: frozen — see `prompts/vector_query.md`.
- **Turn limit**: 30 turns.
- **File set**: union of `file_path` fields across all `find_code` results the agent cites in its final JSON.

### Agentic row
- **Harness**: Claude Code `-p` (`--bare`), `claude-sonnet-4-6`, temperature 0, max_tokens 8192, no retries.
- **Tools allowed**: Bash (read-only subset), Grep, Glob, Read. **Disallowed**: any Memtrace MCP tool, any vector store, Edit, Write.
- **System prompt**: frozen — see `prompts/agentic_system.md`.
- **Turn limit**: 30 turns.
- **File set**: the set of files the agent opened with `Read` plus any file paths it explicitly cited in its final JSON.

### Memtrace row
- **Indexer**: Memtrace ≥ 0.3.92, default tier, **same `.memdb` shared with the Vector row.**
- **Harness**: Claude Code `-p` (`--bare`), `claude-sonnet-4-6`, temperature 0, max_tokens 8192, no retries.
- **Tools allowed**: `find_code`, `find_symbol`, `get_symbol_context`, `get_impact`, `get_source_window`, `analyze_relationships`. **Disallowed**: Bash, Grep, Glob, Read, any vector store, Edit, Write.
- **RRF weights**: defaults (`EXACT=4.0, BM25=2.0, VECTOR=1.0, GRAPH=0.75`) — full hybrid + graph expansion.
- **System prompt**: frozen — see `prompts/memtrace_query.md`.
- **Turn limit**: 30 turns.
- **File set**: the set of files cited by Memtrace tool calls and in the final answer.
- **Symbol set**: the set of fully-qualified symbol names cited.

**Parity**: all three rows receive the **same `problem_statement` text** with **no `hints_text`** (hints can contain solution leakage). All are scored against the **same gold-file set** derived from `patch`. Vector and Memtrace share corpus, indexer, embedder, and chunking — they differ only in RRF weights and tool inventory. Agentic shares model/decoding params with the other two but operates on the raw filesystem instead of the indexed graph.

---

## 6. Disclosures (the 14-point block)

| # | Item | Where it lives |
|---|---|---|
| 1 | Retrieval task statement | §1 of this file |
| 2 | Dataset pins (HF revision + parquet sha256) | `02_sampling.py` header + script output |
| 3 | Sampling protocol + seed | §3 of this file + `02_sampling.py` |
| 4 | Pre-registration evidence | the git commit creating this folder, dated **before** any run; commit hash recorded in `README.md` |
| 5 | Model / version / params | §5 of this file + frozen in `prompts/*.md` |
| 6 | Cutoff defense | Verified `created_at` runs 2013–2023, well before any frontier model cutoff; no per-instance filtering applied |
| 7 | Harness pinning | swe-bench/SWE-bench commit SHA recorded in `repro.sh` and `results/*/run_meta.json` after each run |
| 8 | Token + cost accounting | per-row JSON in `results/<row>/cost.json` after each run |
| 9 | Statistical reporting | Wilson 95% CI on every percentage; per-instance recalls in appendix |
| 10 | Per-instance results | `results/<row>/per_instance.csv` |
| 11 | Negative-results disclosure | Memtrace losses explicitly listed in the writeup |
| 12 | Re-run command | `05_repro.sh` — single-command reproduction from fresh clone |
| 13 | Comparison parity | enforced by §5 above; deviations are bugs |
| 14 | Conflict-of-interest | the writeup discloses Memtrace authored both this benchmark and one of the rows being compared; instance IDs were locked at item #4 timestamp before any run |

---

## 7. Methodological attacks pre-empted

| Attack | Defense |
|---|---|
| Cherry-picked instances | §4 pre-registration commit predates any retrieval run |
| Heuristic-easy population (Lite) | We sampled from **Verified** (human-validated by 93 paid Python devs in collab with OpenAI) |
| Multi-attempt sampling | n=1, temp=0, no retries — declared in §5 |
| Train/test leakage | Verified `created_at` ≤ 2023-08; well before frontier model cutoffs. Disclose model cutoff in the writeup |
| Partial credit | Binary hit/miss per instance; mean recall reported separately; Wilson 95% CI on both |
| Embedder advantage | Vector row uses **the same embedder Memtrace uses** — no embedding-quality confound |
| Tool-set asymmetry | Agentic and Memtrace both capped at 30 turns, same model, same decode params |
| Hints leakage | All three rows see `problem_statement` only, no `hints_text` |
| Harness drift | swe-bench/SWE-bench commit SHA pinned at run time |
| Cost asymmetry | Per-row tokens + dollars logged; vendor list price on a named date |

---

## 8. Reporting template

After Phase 2 completes, the writeup includes:

1. **Headline table** (n=25): Vector / Agentic / Memtrace × {file-recall, avg tokens, avg cost}, each with Wilson 95% CI.
2. **Appendix table** (n=100): same shape.
3. **Per-instance table**: instance_id × {gold files, vector retrieved, agentic retrieved, Memtrace retrieved, hit/miss flags}.
4. **Symbol-recall row** for Memtrace (n=100 only; not comparable to baselines).
5. **Negative findings**: every instance where Memtrace loses, with a one-line root-cause attribution.
6. **Repro instructions**: copy of `05_repro.sh` + commit SHA.

---

## 9. Out of scope

- End-to-end resolve@1 (Track B; deferred until Track A produces a defensible delta).
- Ts-go retrieval (the source benchmark could not be publicly identified at pre-registration time — no matching dataset on HuggingFace, in `swe-bench/experiments`, or in any vendor/conference talk we located. If the source surfaces later, a sibling `benchmarks/tsgo-retrieval/` folder will be added with the same hygiene).
- Comparison to BM25 retrieval as a fourth row (could be added as appendix; not blocking).
- Statistical significance testing across rows (we report CIs, not p-values; reviewers can compute their own from per-instance data).

---

## 10. Phase 2 status (run deferred — explicit gates)

**Phase 2 has been intentionally deferred** pending the methodology gates below. The runnable harness is complete and committed; the run will fire once these are addressed. Listed here so the deferral is documented at pre-registration time, not retrofitted later.

| # | Gate | Reason | Action |
|---|---|---|---|
| G1 | Add an **independent commodity vector baseline** — ChromaDB or Qdrant + sentence-transformers, one-shot, no agent loop | The current `vector` row is Memtrace's own pipeline with non-vector RRF legs zeroed; that is a within-system ablation, not an independent baseline. The brutal critique "you compared Memtrace to Memtrace" is fair and lethal without a commodity reference | Build a 4th row (`vector-commodity`) on a server box; the M3 Max could not host it at scale during smoke testing |
| G2 | Bump sample size from n=25/100 to **n ≥ 300** | Wilson 95% CI at n=25 spans ±18pp. At n=100 still ±10pp. Below ~300 there is no statistically distinguishable claim available — only directional pilot data | Amendment commit extending the pre-registered instance list to n=300; same seed=42 stratified-random protocol |
| G3 | Report **hunk-level recall** in addition to file-level | File-level is the easiest metric. Fix-localization papers report hunk-level. Reporting only file-level is a known soft spot a reviewer will hit | Scorer already supports the parse; aggregator needs the additional column |
| G4 | Run a **train/test contamination probe** | Sonnet 4.6 was trained on GitHub through 2025; Verified `created_at` runs 2013–2023. The model has almost certainly seen these PRs. Without a probe, the result is partly "model recall," not retrieval quality | Sample N instances, prompt the model for the fix-file set with NO codebase access. If recall > random baseline, contamination is non-trivial |
| G5 | Hand the harness to an **independent runner**, or **co-author with an unaffiliated researcher** | Single-author benchmarks where the author owns one of the compared systems are heavily discounted regardless of pre-registration | First contact: UIUC live-SWE-agent group (currently leading Verified at 79.2% on resolve@1; open-source; natural co-author audience for a retrieval-only paper) |

Disclosing these at pre-registration time is part of the methodology, not an admission of failure. **Running the benchmark with a weak Vector baseline and n=25 would have produced numbers that a brutal reviewer (and the field) would have rightly discounted.** Better to defer and address than to ship and be picked apart.

The pre-registration commit (`7a5f49b`) and all subsequent runner / methodology commits remain in the public git history. When Phase 2 fires, results in `results/` will be timestamped after those commits — preserving the "instance IDs locked before any run" guarantee.
