# SWE-bench retrieval — Vector vs Agentic vs Memtrace

**Status**: Phase 1 (pre-registration) — bundle committed; no run yet.
**Date generated**: 2026-05-11
**Owner**: Memtrace / syncable-dev
**Question this round answers**: on SWE-bench Verified, how does Memtrace's graph-typed retrieval compare to vector search and Claude-Code-style agentic search on the same problem statements?

This folder is the **complete, self-contained pre-registration artefact** — public so anyone can audit, reproduce, and challenge the methodology before any results land. Every file required to re-derive the n=25 + n=100 instance sets, every frozen prompt, and the one-shot reproduction script. Phase 2 (the actual run) populates `results/`.

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
| `prompts/vector_query.md` | Vector variant A — Memtrace's default embedder (frozen) |
| `prompts/vector_query_coderankembed.md` | Vector variant B — `nomic-ai/CodeRankEmbed` SOTA code embedder (frozen) |
| `prompts/agentic_system.md` | frozen Claude Code system prompt, tool list, turn limit |
| `prompts/memtrace_query.md` | frozen Memtrace tool list + system prompt |
| `results/{vector-default,vector-coderankembed,agentic,memtrace}/` | empty until Phase 2 — per-row outputs land here |

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

## Rows being compared (4 total, after the CodeRankEmbed amendment)

| Row | Retrieval mechanism | Embedder |
|---|---|---|
| `vector-default` | chunked-file vector retrieval | Memtrace's default code embedder |
| `vector-coderankembed` | chunked-file vector retrieval | `nomic-ai/CodeRankEmbed` (SOTA public code embedder, ICLR 2025) |
| `agentic` | Claude Code grep/glob/read loop, 30 turns | n/a |
| `memtrace` | Memtrace AST-graph tool calls + LeanCTX, 30 turns | n/a |

The two Vector variants exist to pre-empt the "you picked a weak embedder" critique — CodeRankEmbed is currently the strongest publicly available code embedder, so reporting both variants makes the Vector row a real ceiling rather than a strawman.

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

1. `runners/check_env.py` — verifies API key, Memtrace ≥ 0.3.87, Claude Code, MCP, disk, deps
2. `runners/clone_repos.py` — clones each unique `(repo, base_commit)` into `work/repos/`
3. `runners/run_vector.py` — local inference (Jina-code variant A, CodeRankEmbed variant B). No API spend
4. `runners/run_agentic.py` — Claude Code `-p` headless, Bash/Grep/Glob/Read, 30 turns, `--max-budget-usd` per task
5. `runners/run_memtrace.py` — Claude Code `-p` headless, Memtrace MCP tools only, 30 turns
6. `scoring/aggregate.py` — Wilson + bootstrap 95% CIs, writes `results/HEADLINE.md`

Each runner is **idempotent + resumable**: re-running picks up where it stopped. Per-task results stream into `results/<row>/per_instance.csv` as they complete, so a crash mid-run loses at most one task. Trajectories under `results/<row>/trajectories/<instance_id>.json` for audit.

To skip a row (e.g. before MCP server is up):

```bash
bash run_benchmark.sh --skip-memtrace
```
