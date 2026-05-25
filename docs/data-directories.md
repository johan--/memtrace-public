# Data directories

Every directory Memtrace creates, where it lives, what's inside, and
when (if ever) to delete it.

## TL;DR map

```
   YOUR WORKSPACE  (anchored by .memtrace-workspace marker, or git root, or CWD)
   ├── .memtrace-workspace  ← optional anchor — multiple repos here share one .memdb
   ├── .memdb/              ← graph + vectors for every repo under this anchor
   ├── .memtrace/           ← indexer job state (transient, small)
   ├── repo-a/
   ├── repo-b/
   └── repo-c/

   YOUR HOME
   ~/.memtrace/
   ├── embed-cache/         ← per-symbol embedding cache (cross-workspace)
   ├── fastembed_cache/     ← downloaded embedding models
   ├── rerank-models/       ← downloaded reranker model
   ├── auth/                ← session tokens (one file)
   ├── config.toml          ← persistent embedder choice — see embedding-providers.md
   ├── last_health.json     ← last `memtrace embed test` probe result
   ├── logs/                ← daemon.log + rotated history (v0.3.89)
   ├── session-ledger.jsonl ← user-global MCP tool-call ledger (v0.3.89)
   ├── watches.json         ← persistent watch_directory registrations (v0.3.89)
   └── telemetry/           ← buffered events (only if telemetry is ON)
```

Two important rules:
- **Workspace state lives in the workspace, not the per-repo.** Sibling
  repos under one `.memtrace-workspace` marker (or one git root, if no
  marker) share a single `.memdb/`. That makes cross-repo edges work —
  your TS frontend's `fetch("/api/users")` can link to your Rust
  backend's `Router::route(...)` even though they're in separate repo
  directories. `memtrace reset <repo_id>` removes only one repo's
  records; `rm -rf .memdb/` wipes them all.
- **Cross-workspace state lives in `~/.memtrace/`.** Models, embedding
  cache, and your session token aren't tied to a workspace.

## Where `.memdb/` actually lives — workspace anchor

The MemDB graph engine's on-disk store. Created the first time you run
`memtrace start` or `memtrace index <path>` somewhere under a workspace.

**Discovery order** when Memtrace boots:

1. **`.memtrace-workspace` marker** (explicit anchor — empty file is fine).
   Memtrace walks UP from the current working directory looking for it.
   First match wins. All sibling directories under the marker share one
   `.memdb/`. *Recommended for monorepos and multi-repo workspaces.*
2. **`.git/` root** (per-repo fallback). If no `.memtrace-workspace`
   marker is found, Memtrace uses the nearest git repo root.
3. **Current working directory** if neither marker nor git root is found.

Quick way to confirm where YOUR `.memdb` is on a running system:

```
memtrace status
```

The startup banner also prints:

```
◆  MemDB embedded — in-process (data dir: /your/path/.memdb)
```

### Multi-repo workspace example

```
$ pwd
/home/me/work/

$ tree -L 1 -a
.
├── .memtrace-workspace      ← marker, you `touch`-ed this
├── .memdb/                  ← ONE store for all 3 repos
├── frontend/                ← repo A (git)
├── backend/                 ← repo B (git)
└── infra/                   ← repo C (terraform-only, no git)

$ cd frontend && memtrace index .
# → registers frontend's symbols in /home/me/work/.memdb under repo_id=frontend

$ cd ../backend && memtrace index .
# → registers backend's symbols in the SAME .memdb under repo_id=backend
# Cross-language edges between frontend & backend symbols work out of the box.
```

Without the marker, each repo gets its own `<repo>/.memdb/` and they
can't see each other.

Layout (high-level — the inner files are MemDB's business; don't
touch them):

```
.memdb/
├── daemon.pid                     # workspace-owner lock
├── daemon-state.json              # owner endpoint + heartbeat
└── memtrace/                     # database name
    ├── wal/                      # write-ahead log
    ├── episodes/                 # commit + working-tree snapshots
    ├── paged-records/            # Nodes / Edges / Episodes / VectorBlobs
    ├── indexes/                  # property indexes + HNSW vectors
    ├── tantivy/                  # BM25 full-text segments
    └── manifest.toml             # MemDB metadata
```

`daemon.pid` and `daemon-state.json` are runtime coordination files,
not graph data. They let `memtrace start`, `memtrace mcp`, and the
headless daemon agree on a single owner for this `.memdb`. If another
process already owns the lock, later `memtrace mcp` processes attach
to that owner's loopback endpoint instead of opening a duplicate
embedded MemDB.

Size grows roughly linearly with your codebase. Some rough numbers:

| Project | Files | Symbols | `.memdb/` size |
|---|---|---|---|
| Small (mempalace) | ~250 | ~1.8k | ~30 MB |
| Medium (Express, Bun-style) | ~800 | ~12k | ~120 MB |
| Large (Django) | ~3,300 | ~50k | ~700 MB–1 GB |
| Huge (Linux kernel-class) | 30k+ | 500k+ | 5–10 GB |

**Override location** with `MEMTRACE_MEMDB_DATA_DIR=<absolute path>`
if you want it outside the repo (e.g. on a faster disk).

**When to delete:** `memtrace reset` does this safely. Manual
`rm -rf .memdb/` works too if the daemon isn't running. The next
`memtrace start` will re-index from scratch.

## Per-project: `<project>/.memtrace/`

Job state for the indexing pipeline — progress, watchers, recovery
metadata. Tiny (usually < 1 MB). Created the first time the daemon
runs in your project.

If the daemon crashes mid-index, this is what lets it resume rather
than starting over. Safe to delete when the daemon isn't running; you
just lose the resume point and the next `memtrace start` re-indexes
from scratch.

**Override location** with `MEMTRACE_DATA_DIR=<path>`.

## `<project>/.memtraceignore`

Optional file. Glob patterns of paths the indexer should skip,
on top of the built-in exclude list (`.git`, `node_modules`,
`target`, `dist`, `build`, `.venv`, `vendor`, `.claude/`, etc.).

```
# .memtraceignore — same syntax as .gitignore
docs/generated/
**/*_pb2.py
fixtures/
```

You usually don't need this — the built-in excludes cover most cases.
Reach for it when a generated/vendored directory is bloating your
graph.

## `~/.memtrace/embed-cache/`

A redb-backed key-value store mapping `(model_id, symbol_ast_hash)`
→ embedding vector. **Cross-project** — re-indexing a different repo
that has the same symbol body doesn't recompute the embedding.

Layout:
```
~/.memtrace/embed-cache/
└── memtrace_embed_v2.redb       # single file, ACID, mmap
```

Typical size: 200 MB–2 GB depending on how many distinct symbols
you've indexed across all your projects.

**When to delete:** Only when you change embedding models. The cache
is keyed by model ID, so switching from `jina-embeddings-v2-base-code`
to `bge-small` makes the existing entries cache-misses anyway — but
they still take disk. Manual cleanup:

```bash
rm -rf ~/.memtrace/embed-cache/
```

## `~/.memtrace/fastembed_cache/`

HuggingFace-style cache for the downloaded embedding model. Default
is `jina-embeddings-v2-base-code` (~340 MB f32 ONNX, ~85 MB int8).

Layout:
```
~/.memtrace/fastembed_cache/
├── models--jinaai--jina-embeddings-v2-base-code/
│   ├── snapshots/<sha>/
│   │   ├── model.onnx           OR model_int8.onnx
│   │   ├── tokenizer.json
│   │   └── tokenizer_config.json
│   ├── blobs/                   # Hugging Face content-addressed blobs
│   └── refs/main
└── models--Xenova--bge-small-en-v1.5/    # only if you've used bge-small
```

Size: 340–500 MB for the default model. Adding alternative models
(bge-small, bge-base) costs 100–500 MB each.

**Override location** with `FASTEMBED_CACHE_DIR=<path>` — useful if
your home directory is on a small SSD and you want models on a
different disk.

**When to delete:** When you want to redownload a model (rare). The
cache is content-addressed, so a partial download self-heals on next
use.

## `~/.memtrace/rerank-models/`

Cross-encoder reranker models. Default is `BAAI/bge-reranker-base`
(int8 quantized, ~75 MB).

Layout:
```
~/.memtrace/rerank-models/
└── bge-reranker-base/
    ├── model_int8.onnx
    ├── tokenizer.json
    └── config.json
```

The reranker is loaded into memory only when `MEMTRACE_RERANK=on`
(the default). Disable it with `MEMTRACE_RERANK=off` if you want a
pure BM25 + vector pipeline (faster, ~3–4 pp lower acc@1 on typical
agent queries).

## `~/.memtrace/auth/`

Your Memtrace session token, refreshed automatically. One file:

```
~/.memtrace/auth/
└── session.json     # { device_id, token, expires_at }
```

Don't share this file. If you suspect it's leaked,
`memtrace auth logout` deletes it; the next `memtrace start` walks
you through device-flow login again.

## `~/.memtrace/telemetry/`

Created on first run because product telemetry is on by default.
Stores a small batch of pending events (sanitised crashes, errors,
and lightweight usage signals) until the flusher ships them every
60 seconds. See [`privacy-and-telemetry.md`](privacy-and-telemetry.md)
for the full field-level breakdown of what's in there.

Set `MEMTRACE_TELEMETRY=off` to disable telemetry — the panic hook
still leaves a local breadcrumb in this directory if the binary
crashes (useful for your own debugging), but the flusher never
ships it. If you've never run `memtrace start`, the directory
doesn't exist yet.

## `~/.memtrace/logs/daemon.log` (v0.3.89)

Daemon startup + error log. Rolling file appender:

```
~/.memtrace/logs/
├── daemon.log         # current
├── daemon.2026-05-10.log
├── daemon.2026-05-09.log
└── …                  # up to 5 files retained, rotated at 10 MB each
```

Populated from the first daemon-startup tick, so even an
"exits-immediately" failure leaves a breadcrumb. Created on first
`memtrace daemon start` after upgrading to v0.3.89.

Override the location with `MEMTRACE_LOGS_DIR=<absolute path>` if
you want logs somewhere else. Safe to delete the directory at any
time — it'll be recreated on the next daemon start.

## `~/.memtrace/session-ledger.jsonl` (v0.3.89)

User-global JSONL append-log of MCP tool calls. One line per call:

```jsonc
{ "event_id": "…", "tool_name": "find_symbol", "task_label": "…",
  "timestamp": "2026-05-11T11:42:13Z", "bytes_avoided": 1843,
  "elapsed_ms": 38, "files_referenced": 2, "repo_id": "myrepo", … }
```

Moved here from `<workspace>/.memtrace/session-ledger.jsonl` in
v0.3.89 to fix the bug @Badmrpotatohead reported where the
dashboard's `/api/value/aggregate` view said "0 queries / $0.00"
while the session log showed 140 historical calls — root cause
was `memtrace mcp` (agent-launched) and `memtrace start` (run from
your repo) writing to / reading from different ledger files because
each was anchored to its own cwd.

Override with `MEMTRACE_SESSION_LEDGER=<absolute path>` to put it
somewhere else (e.g. per-workspace isolation if you really want it).

Safe to delete — you lose historical receipts but the live counters
keep working from in-memory state, and the file rebuilds itself on
the next MCP call.

## `~/.memtrace/watches.json` (v0.3.89)

Persistent registry of `watch_directory` registrations, atomic
write, BOM-tolerant read:

```jsonc
[
  { "path": "D:\\Repos\\my-project", "repo_id": "my-project",
    "registered_at": "2026-05-11T01:42:00Z", "origin": "manual" },
  { "path": "/home/me/other-repo",   "repo_id": "other-repo",
    "registered_at": "2026-05-10T22:14:55Z", "origin": "manual" }
]
```

`origin` is `"manual"` for entries you registered via the
`watch_directory` MCP tool, and `"restored"` for entries the MCP
server re-armed from this file on boot.

Restore-on-boot is on by default. Escape hatch:
`MEMTRACE_NO_WATCH_RESTORE=1` makes the MCP server ignore this file.

To forget all watches: delete the file.

## Things Memtrace creates outside its own directories

A few files end up in your repo or home folder beyond the four
directories above:

- **Skills** are installed at the global path your AI tool expects
  (e.g. `~/.claude/skills/memtrace-skills/...` for Claude Code,
  `.cursor/...` for Cursor). Generated by `memtrace install` /
  `npm install -g memtrace` postinstall.
- **MCP config entries** are appended to your tool's config:
  `~/.config/claude-code/mcp.json`, `~/.cursor/mcp.json`, etc. The
  installer is idempotent — running it twice doesn't duplicate
  entries.
- The Memtrace npm shim itself lives wherever your global npm puts
  things (`~/.npm-global/lib/node_modules/memtrace/` on most setups).

## Cleaning up everything

Full reset to factory:

```bash
memtrace stop                         # stop the daemon
rm -rf <project>/.memdb               # this project's graph
rm -rf <project>/.memtrace            # this project's job state
rm -rf ~/.memtrace                    # ALL machine-level state
npm uninstall -g memtrace             # the binary + skills
```

After this Memtrace leaves no trace on your system. Your source code
is never touched.

## What's safe to delete during normal use

| Path | Safe? | Effect |
|---|---|---|
| `<project>/.memdb/` | Yes (daemon stopped) | Re-index from scratch on next start |
| `<project>/.memtrace/` | Yes (daemon stopped) | Lose resume point; re-index full on next start |
| `~/.memtrace/embed-cache/` | Yes any time | Re-embed symbols on next index |
| `~/.memtrace/fastembed_cache/` | Yes any time | Re-download model on next start (~340 MB) |
| `~/.memtrace/rerank-models/` | Yes any time | Re-download reranker (~75 MB) |
| `~/.memtrace/auth/` | Yes | Forces re-login on next start |
| `~/.memtrace/telemetry/` | Yes | Drops any unsent events |
| `~/.memtrace/logs/` | Yes any time | Drops historical daemon logs; new ones will be created |
| `~/.memtrace/session-ledger.jsonl` | Yes any time | Loses historical MCP-call receipts; live counters keep working from in-memory state |
| `~/.memtrace/watches.json` | Yes (daemon / MCP stopped) | All `watch_directory` registrations forgotten; re-register manually after deleting |

Nothing here is precious. The graph rebuilds itself; the caches
warm themselves; the auth re-authenticates. Memtrace is designed so
you can `rm -rf` any of these at any time without consulting docs
first.
