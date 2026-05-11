# SWE-bench retrieval — Vector vs Agentic vs Memtrace

**Status: Pre-registered (Phase 1 complete). Phase 2 run is intentionally deferred — see "Run status" below.**
**Date generated**: 2026-05-11
**Owner**: Memtrace / syncable-dev
**Question this round answers**: on SWE-bench Verified, how does Memtrace's graph-typed retrieval compare to vector search and Claude-Code-style agentic search on the same problem statements?

This folder is the **complete, self-contained pre-registration artefact** — public so anyone can audit, reproduce, and challenge the methodology before any results land. Every file required to re-derive the n=25 + n=100 instance sets, every frozen prompt, and the one-shot reproduction script. Phase 2 (the actual run) will populate `results/` once the gates below are cleared.

---

## Run status

**Phase 2 run is deferred. Not abandoned — paused on purpose until we can pass a brutal reviewer pass.**

What's gated:

| Gate | Why it matters | Status |
|---|---|---|
| **Independent commodity vector baseline** (ChromaDB / Qdrant + standard sentence-transformers, one-shot, no agent loop) running on a server box | The current `vector` row is Memtrace's own pipeline with non-vector RRF legs zeroed — it is an internal ablation, not an independent vector baseline. A brutal reviewer would (correctly) point out that "Memtrace beats Memtrace-with-graph-off" is not the same claim as "Memtrace beats vector retrieval" | Not yet built — the M3 Max can't host the commodity vector pipeline at scale; needs a beefier machine |
| **Sample size ≥ 300** | Wilson 95% CI at n=25 spans ±18pp. At n=100 still ±10pp. Below ~300, every "result" is statistical theater | Pre-registration covers n=25 + n=100; needs an amendment commit for n=300+ |
| **Hunk-level recall in addition to file-level** | File-level is the easiest metric. Fix-localization papers report hunk-level. Reporting only file-level is a known soft spot | Scorer supports it (`scoring/scorer.py`); needs aggregator wiring |
| **Train/test contamination probe** | Sonnet 4.6 was trained on GitHub through 2025; Verified `created_at` runs 2013–2023. The model has almost certainly seen these PRs. Need a probe that quantifies how much of the result is "model recall" vs "retrieval system quality" | Not built |
| **Independent runner or co-author** | Single-author benchmarks where the author owns one of the systems being compared are heavily discounted by the field, regardless of pre-registration. Path forward: hand the runnable harness to an unaffiliated party, or co-author with an academic (UIUC live-SWE-agent group is the natural target) | Not started |

When those clear, the rest of the harness is already wired: env check, repo cloner, three runners, scorer with Wilson + bootstrap CIs, aggregator, one-line entry point. `bash run_benchmark.sh --full` is one command away from producing results — we just won't run it until the gates above are honestly addressed.

The pre-registration commit (linked below) stays load-bearing. Instance IDs, sampling seed, prompts, methodology — all locked at commit time, before any retrieval has executed. That guarantee survives the deferral.

---

## How to cite this round

Public path:

```
https://github.com/syncable-dev/memtrace-public/tree/main/benchmarks/swebench-retrieval
```

When the writeup is published, link the **git commit hash** that first added this folder as the pre-registration timestamp. That commit's date must predate every entry in `results/`. Anyone can clone the repo, run `bash 05_repro.sh sample`, and verify the sha256s match — that's the public moat.

---

## Reading order

| File | What it is |
|---|---|
| `README.md` | this file — overview, status, cite-by path |
| `01_methodology.md` | the round contract — task, dataset pins, sampling, metric, four-row specs (2 Vector variants + Agentic + Memtrace), 14-point disclosure block, attacks pre-empted |
| `02_sampling.py` | reproducible stratified-random sampler (seed=42, numpy default_rng); deterministic across platforms |
| `03_instances_25.csv` | headline sample — matches the slide's n=25 |
| `04_instances_100.csv` | appendix sample — Wilson-CI defensible |
| `05_repro.sh` | one-shot re-runner; `bash 05_repro.sh sample` regenerates CSVs from the pinned parquet |
| `requirements.txt` | pinned Python deps (pandas, pyarrow, numpy, requests) |
| `data/verified_500.parquet` | HuggingFace snapshot, sha256 below; **bit-identical pre-registration evidence** |
| `prompts/vector_query.md` | Vector row spec — Memtrace + `find_code` only, RRF vector-only weights |
| `prompts/agentic_system.md` | frozen Claude Code system prompt, tool list, turn limit |
| `prompts/memtrace_query.md` | frozen Memtrace tool list + system prompt |
| `results/{vector,agentic,memtrace}/` | empty until Phase 2 — per-row outputs land here |

---

## Pre-registration evidence

| Artefact | sha256 |
|---|---|
| `data/verified_500.parquet` | `43ed5a3d1d98da36472c1ade65ddd2085d7b4ff694fcaf6a023a07c5c1f32f21` |
| `03_instances_25.csv` | `693286f2965c1e1adf4040d71df838ded26291e31e73cf5c20a60a655c880145` |
| `04_instances_100.csv` | `572798b64641754d99e03fcc21c5cb6a1996b23b3bcb9726af5dd8cdd4f710f9` |

Anyone re-running `bash 05_repro.sh sample` from a fresh clone reproduces these hashes byte-identically (Python 3.12, numpy ≥ 2.0, pandas 2.2.3, pyarrow 18.1.0).

---

## Sample composition (at a glance)

| Difficulty | Verified-500 | n=25 | n=100 |
|---|---:|---:|---:|
| `<15 min fix` | 194 | 10 | 39 |
| `15 min - 1 hour` | 261 | 13 | 52 |
| `1-4 hours` | 42 | 2 | 8 |
| `>4 hours` | 3 | 0 | 1 |

- n=25 covers 6 of 12 repos (django 11, sphinx 5, matplotlib 3, scikit-learn 3, sympy 2, pytest 1) — repo distribution emerges from difficulty stratification, no per-repo quota
- n=100 covers 9 of 12 repos; missing repos collectively account for 2.2% of Verified

See `01_methodology.md` §3 for the full protocol.

---

## Rows being compared (3 total)

| Row | Retrieval mechanism | Same `.memdb` as Memtrace? |
|---|---|---|
| `vector` | Memtrace's `find_code` with **RRF weights `VECTOR=1.0, BM25=EXACT=GRAPH=0`** (pure dense semantic) | yes |
| `agentic` | Claude Code grep/glob/read loop, 30 turns, no Memtrace | no — operates on raw filesystem |
| `memtrace` | Memtrace AST-graph tool calls + LeanCTX, full hybrid RRF, 30 turns | yes |

**Why "vector" is an ablation of "memtrace", not a separate pipeline**: same indexer, same embedder (Jina-code), same corpus. The only differences are the RRF weights at fusion and the tool inventory available to the LM. This makes the comparison "what does the graph add over pure vector retrieval, on the same indexed corpus?" — direct ablation, no embedder confound.

---

## What Phase 2 will produce (preview)

After running, each `results/<row>/` will contain:

- `run_meta.json` — model + version, harness SHAs, Memtrace version, hardware, wall-clock, run-start UTC
- `cost.json` — total input + output tokens, USD cost (vendor list price as of run date)
- `per_instance.csv` — instance_id × {retrieved_files, retrieved_symbols (memtrace only), recall, hit}
- `trajectories/<instance_id>.jsonl` — full tool-call traces (gitignored; published separately on demand)

The final writeup lives outside this folder; this folder produces its inputs.

---

## What this round does NOT do

- It does not generate patches and does not measure resolve@1. That is Track B, deferred.
- It does not include "Ts-go" — the slide's Ts-go benchmark could not be identified as a public artefact (no matching dataset on HuggingFace, in `swe-bench/experiments`, or in any vendor/conference talk we could find). If the source is identified later, a sibling folder `benchmarks/tsgo-retrieval/` will be added with the same hygiene.
- It does not submit to the SWE-bench leaderboard. The leaderboard accepts resolve@1 only; retrieval comparisons are published off-leaderboard.

---

## Running it

Drop your Anthropic API key in the shell and call the entry point:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
bash run_benchmark.sh --dry-run          # 3 instances per row, real cost projection
bash run_benchmark.sh                    # sanity: n=25, ~$45–120
bash run_benchmark.sh --full             # appendix: n=100, ~$180–600
```

Behind the scenes:

1. `runners/check_env.py` — verifies API key, Memtrace ≥ 0.3.87, Claude Code, MCP, disk, git
2. `runners/clone_repos.py` — clones each unique `(repo, base_commit)` into `work/repos/`
3. `runners/run_vector.py` — Claude Code `-p` + Memtrace `find_code` only, RRF weights pinned to vector-only (`VECTOR=1.0, BM25=EXACT=GRAPH=0`). Shares the `.memdb` with the Memtrace row
4. `runners/run_agentic.py` — Claude Code `-p` headless, Bash/Grep/Glob/Read, 30 turns
5. `runners/run_memtrace.py` — Claude Code `-p` headless, full Memtrace MCP tool set, default RRF weights
6. `scoring/aggregate.py` — Wilson + bootstrap 95% CIs, writes `results/HEADLINE.md`

Each runner is **idempotent + resumable**: re-running picks up where it stopped. Per-task results stream into `results/<row>/per_instance.csv` as they complete, so a crash mid-run loses at most one task. Trajectories under `results/<row>/trajectories/<instance_id>.json` for audit.

To skip a row (e.g. before MCP server is up):

```bash
bash run_benchmark.sh --skip-memtrace
```
