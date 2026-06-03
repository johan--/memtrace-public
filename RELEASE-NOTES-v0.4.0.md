# Memtrace v0.4.0 — Persistent indexes, embedder flexibility, Windows field-report fixes

Three work streams roll up in this minor bump:

- **Boot-architecture rewrite** — every in-memory index Memtrace used to rebuild on each restart now persists to disk and recovers via manifest replay. Cold start goes from multi-second to sub-second.
- **Embedder flexibility** — new `memtrace embed` CLI for managing local presets and bringing your own remote (OpenAI / Voyage / Ollama / Infinity / TEI / vLLM / LM Studio / corporate gateways — anything speaking the OpenAI-compatible `/embeddings` spec).
- **Field-report fixes** — two bugs filed by **@Magalz** during Windows v0.3.93 validation close in this release.

This is the first 0.4.x. The bump signals the boot-architecture change, not a breaking API change.

## TL;DR

| Area | Was | Is |
|---|---|---|
| **Cold start** | full `iter_live` scan rebuilt 5 in-memory indexes on every boot — multi-second on real stores | manifest + append-log replay; sub-second on the same data |
| **Crash recovery time** | same multi-second rebuild after every restart | same fast path; only the data written since last manifest needs replay |
| **Embedding model** | one default, swapping required two env vars (model + dims) and a re-index dance | `memtrace embed set <preset>` for local presets; `memtrace embed set --remote …` for any OpenAI-compatible endpoint; dims derive env-fresh from the active model |
| **BYO remote provider** | not supported — local ONNX only | OpenAI, Voyage, Ollama, Infinity, TEI, vLLM, LM Studio, corporate gateways. Same code path; verified end-to-end against Voyage `voyage-code-3` and OpenAI `text-embedding-3-small` |
| **Matryoshka dim truncation** | not supported | `--dim 512` on remote providers — smaller HNSW, faster queries, configurable trade-off |
| **`find_symbol` on legacy Windows graphs** | duplicates from mixed-form path storage (`D:\…` vs `\\?\D:\…`) | read-time dedup heals legacy graphs without `--clear` or re-index |
| **`memtrace daemon start` on Windows when service missing** | printed "started"; 10 s later "did not bind within 20 attempts"; nothing in logs | real error surfaced immediately, with a clear "run `memtrace daemon install` from an elevated PowerShell first" pointer. Same hardening for macOS `launchctl` and Linux `systemctl` |
| **Page-cache append past ~7 MB** | silently dropped writes — the bench that drove the boot rewrite first surfaced this | `flush_all` walks all resident dirty pages, not a bounded queue; full round-trip integrity |

---

## Part 1 — Boot-architecture rewrite

MemDB used to rebuild every in-memory index on each restart by scanning the full primary record store via `iter_live`. On a real-size store that scan dominated startup time. Three back-to-back rounds replaced this with the pattern every real database has used forever — persistent indexes recovered via manifest replay.

### Indexes that now persist to disk

| Index | What it accelerates | Recovery shape |
|---|---|---|
| HNSW (vector search) | `ann_search`, semantic queries | append-only node log + atomic manifest (shipped earlier as R8-IDX-1, fully wired here) |
| `rid → uuid` map | record lookup by UUID across reopens | append-only log + manifest |
| Edge adjacency | `analyze_relationships`, `find_dependency_path`, `get_impact` | append-only log with insert + tombstone records |
| Property index (inverted) | `rids_by_property`, property-filtered searches | append-only log with torn-page tolerance inherited from R5/R7-A4 |
| Per-kind counts | repository stats, dashboard counts | fixed-size snapshot (~64 bytes), no log; WAL-high-water gate |

### Safety pattern (uniform across all 5)

- Schema version on every manifest. Mismatch → fall back to `iter_live` rebuild.
- Per-record CRC. Bad record → skip with warn log; tail of valid records still recovered.
- Atomic-rename manifest write. A crash between the write and the next WAL fsync only loses the recovery point (next boot rebuilds), never the underlying log records.
- WAL-high-water gate (count_store): snapshot is rejected if WAL has advanced past `last_wal_offset`.

In every failure mode the engine **falls back to the rebuild path**. A bad recovery point never corrupts state; the worst case is one boot at the old speed.

### The page-cache append bug that nearly hid this work

The R8-IDX-1 boot bench died with "corruption" at a fixed byte offset (~7 MB on the test machine). The original suspects — `&mut [u8]` after lock-drop, CLOCK eviction during append, multi-page non-atomicity — were all red herrings.

Real cause: `MmapPageManager::flush_all` walked only a bounded `ArrayQueue` of dirty page IDs. The write path pushed to that queue with `let _ = …push(id)` — silent on overflow. Past the queue capacity, dirty pages became invisible to `flush_all`; their mmap regions stayed as `allocate()`'s zero-fill, and the read path later saw zero bytes where records should have been.

Fix: `PageCache::snapshot_resident_for_db()` + rewrite `flush_all` to use `CachedPage::is_dirty()` as source of truth. +52/-3 LOC. The repro offset varies with record-size distribution (fixed 600-byte records diverge around 9.7 MB; HNSW-variable records around 7.1 MB) — same root cause, different fill rates.

### Validation

- **Storage/index/persistence layers**: rid_uuid 48 TDD + 12 proptest, edge_adj 41 + 7 + 12, property_idx 40 + 45 + 12, count_store 24 + 6. Combined: ~250 new tests / ~2,500 property cases on the boot-architecture work alone.
- **Dogfood bench** (copy of a live 220K `.memdb` to `/tmp`): first open 3.572 ms (rebuild path), second open 637 µs (all 5 fast-paths fire). 5.6× speedup; both sub-millisecond on this size. Scaling holds — recovery cost is bounded by manifest replay LSN, not store size.

### What does NOT change

- On-disk record format. Existing stores keep working.
- gRPC API. Same surface, same semantics.
- Query latency. Indexes recover into the same in-memory structures (HashMap, DashMap, HNSW graph) — post-boot lookups are bit-identical.
- RAM usage. A few KB per DB for write buffers and append cursors. No new in-memory caches.

The win is restart cost. CI runs that spawn a fresh `memtrace`, pre-commit hooks that touch the engine, container restarts behind a load balancer — all cheaper.

---

## Part 2 — Pick your embedder

`memtrace embed` is the new CLI for managing the embedding provider. Persistent TOML config at `~/.memtrace/config.toml` (workspace-scoped via `--workspace`).

### Local presets

```bash
memtrace embed set jina-code     # default, code-tuned, 768d
memtrace embed set bge-small     # lighter, 384d
```

### Bring your own remote

Anything speaking the OpenAI-compatible `/embeddings` spec:

```bash
memtrace embed set --remote openai-compat \
  --url https://api.voyageai.com/v1 \
  --model voyage-code-3 \
  --api-key-env VOYAGE_API_KEY
```

Verified end-to-end with **Voyage** (`voyage-code-3`) and **OpenAI** (`text-embedding-3-small`). Also works against **Ollama**, **Infinity**, **TEI**, **vLLM**, **LM Studio**, and self-hosted corporate gateways — same code path.

Add `--dim 512` (or any value ≤ the model's native dim) for Matryoshka truncation when you want a smaller HNSW.

### Circuit breaker — remote failure modes

Four new breaker reasons handle remote-specific failures:

- `RateLimited` — 429 with adaptive Retry-After backoff
- `AuthFailed` — 401/403, no retry, fail loudly
- `NetworkUnavailable` — connection refused, DNS failure, timeout
- `DimMismatch` — response vector wrong size; refuses to mix dims into a single HNSW (no silent corruption)

Pressure gate skips local-CPU-pressure checks for remote providers — your CPU is no longer the bottleneck when the model lives elsewhere.

### Switching with an existing index

A dim change (e.g. `jina-code` → `bge-small`, or remote `--dim` change) requires reset + reindex. The CLI prompts before touching anything; existing `.memdb` data is never silently corrupted. Same model + same dim swap is a no-op.

Full docs: [`docs/embedding-providers.md`](docs/embedding-providers.md).

---

## Part 3 — Magalz's Windows v0.3.93 validation — 2 bugs closed

### `find_symbol` returning duplicates on legacy Windows graphs

Older `.memdb` files written by previous Windows builds stored the same file under both `D:\Repos\proj\src\foo.ts` and `\\?\D:\Repos\proj\src\foo.ts`. Searches surfaced symbols 2-3× in `find_symbol`, `find_most_complex_functions`, `get_codebase_briefing`, and `find_dead_code`.

Fixed at read time — legacy graphs heal on next query, no `--clear` needed. New writes use a single canonical form (forward slashes, lowercased drive letter, no `\\?\` prefix).

### `memtrace daemon start` printing "did not bind within 20 attempts" 10 s after a silent failure

On Windows, `sc.exe` failures during daemon start were silently swallowed: no daemon process was ever spawned, but the CLI returned success and then sat polling a port nothing was binding to. After 20 attempts (~10 s) it gave up.

Fixed:

- `sc.exe` failures now surface the real error immediately, with a clear "run `memtrace daemon install` from an elevated PowerShell first" pointer.
- Same hardening for `launchctl` on macOS and `systemctl` on Linux — service-manager failures no longer hide behind a generic timeout.

22 new lock tests guard against Windows regressions specifically.

Thanks to [@Magalz](https://github.com/Magalz) for the detailed Windows validation report — that's the bug hunt that catches what test suites miss.

---

## Combined test gate

- Workspace `cargo build --release`: clean against new submodule pointer.
- Per-crate test suites: ~700 named tests + ~2,400 property cases across both the boot-architecture work and the embedder round.
- Dogfood bench on real `.memdb`: 5/5 fast-paths fire on second open after one clean restart.
- Magalz Windows regression: 22 new lock tests, all green.

## Upgrade notes

- **`npm install -g memtrace`** (or your usual update path) — `memtrace install` preserves all data under `~/.memtrace/` and `~/.memdb`.
- **Existing stores work as-is.** First boot after upgrade does one final `iter_live` rebuild and writes the 4 new manifests on close. From the second boot onwards you're on the fast path.
- **No config migration required.** `~/.memtrace/config.toml` is additive — old files stay valid; new fields fill in from sensible defaults.
- **No env-var changes.** All existing `MEMTRACE_*` env vars still work. `MEMTRACE_VECTOR_DIMS` keeps its precedence for reattaching to pre-existing `.memdb` whose dim was locked at first open.
