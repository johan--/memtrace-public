# Workspaces

A **workspace** lets several repositories share **one** Memtrace
knowledge graph, so the agent can answer questions *across* repo
boundaries — your TypeScript frontend's `fetch("/api/users")` links to
your Rust backend's `Router::route(...)` even though they live in
separate directories.

If you only ever work in a single repo, you can skip this page —
Memtrace already does the right thing (one `.memdb/` at your git root).
Workspaces matter the moment you have **two or more related repos**
(frontend + backend, a service mesh, a monorepo of packages) and you
want the graph to see them as one system.

## Why use one

Without a workspace, each repo gets its own isolated `.memdb/`. The
graphs can't see each other, so cross-repo questions come back empty:

- "What backend endpoint does this client call hit?"
- "If I rename this route, which frontends break?"
- "Show the call path from the UI button to the database write."

Put those repos under one workspace and all of that resolves through a
single graph. Concretely, a workspace gives you:

- **One `.memdb/` store** for every repo beneath it.
- **Cross-repo edges** — HTTP calls, shared types, imports across
  service boundaries — detected automatically at index time.
- **One owner/daemon** for the whole set instead of one per repo.

## Create a workspace

Pick whichever fits how you work. All three end up at the same place: a
`.memtrace-workspace` marker file at the folder that contains your
repos.

### Option A — drop a marker (most explicit)

```bash
cd /path/to/parent-folder    # the folder that holds your repos
touch .memtrace-workspace    # empty file is fine
```

### Option B — let the CLI write it

```bash
memtrace start --workspace .
# or
memtrace index --workspace .
```

`--workspace <path>` treats `path` as the workspace root and writes the
marker there for you.

### Option C — auto-detect

Run `memtrace start` from a folder that **isn't itself a git repo** but
contains **2+ child directories that each have their own `.git`**.
Memtrace recognises the multi-repo shape and writes the marker
automatically. Opt out with `memtrace start --no-workspace`.

## How Memtrace picks the workspace

When `memtrace start`, `memtrace index`, or `memtrace mcp` boots, it
walks **up** from the current directory and uses the first of these it
finds:

1. **`.memtrace-workspace` marker** — explicit anchor. First match
   wins; every sibling directory beneath it shares one `.memdb/`.
   *Recommended for monorepos and multi-repo setups.*
2. **`.git/` root** — per-repo fallback when no marker exists.
3. **Current working directory** — if neither marker nor git root is
   found.

Confirm where you actually landed:

```bash
memtrace status
```

The startup banner also prints the resolved path:

```
◆  MemDB embedded — in-process (data dir: /your/path/.memdb)
```

## Worked example

```
$ pwd
/home/me/work/

$ tree -L 1 -a
.
├── .memtrace-workspace      ← marker, you touch-ed this
├── .memdb/                  ← ONE store for all 3 repos
├── frontend/                ← repo A (git)
├── backend/                 ← repo B (git)
└── infra/                   ← repo C (terraform-only, no git)

$ cd frontend && memtrace index .
# → registers frontend's symbols in /home/me/work/.memdb under repo_id=frontend

$ cd ../backend && memtrace index .
# → registers backend's symbols in the SAME .memdb under repo_id=backend
# Cross-language edges between frontend & backend now resolve out of the box.
```

Without the marker, `frontend/` and `backend/` would each get their own
`<repo>/.memdb/` and could not see each other.

## What is scoped to a workspace (and what isn't)

| Lives in the workspace | Lives in `~/.memtrace/` (cross-workspace) |
|---|---|
| `.memdb/` — graph + vectors for every repo under the anchor | Downloaded embedding & reranker models |
| `.memtrace/` — indexer job state (transient, small) | `embed-cache/` — per-symbol embedding cache |
| Workspace-local embedding override (see below) | Session token, global config, logs, watches |

Rule of thumb: **graph data is per-workspace; models, caches, and your
login are machine-global.** Full directory-by-directory breakdown is in
[`data-directories.md`](data-directories.md).

## Workspace-local configuration

By default the embedding provider is read from `~/.memtrace/config.toml`
(machine-global). To pin a different embedder to one workspace only:

```bash
memtrace embed set jina-code --workspace
# writes <workspace>/.memtrace/embed.toml
```

Resolution precedence (highest first):

1. `<workspace>/.memtrace/embed.toml` — workspace-local override
2. `~/.memtrace/config.toml` — machine-global default
3. `MEMTRACE_EMBED_MODEL` / `MEMTRACE_VECTOR_DIMS` env vars
4. Built-in default (`jina-embeddings-v2-base-code`, 768 dims)

See [`embedding-providers.md`](embedding-providers.md) for the provider
catalogue.

## Switching, listing, and ownership

There is **no `switch` or `list-workspaces` command** — a workspace is
just a directory. To move between workspaces, run Memtrace from that
tree; resolution (above) does the rest.

```bash
memtrace status                          # the active workspace's .memdb path
find ~ -name .memdb -type d 2>/dev/null   # every store on this machine
```

Each workspace's `.memdb/` keeps an **owner lock** (`daemon.pid`), so
`memtrace start`, `memtrace mcp`, and the headless daemon agree on a
single owner. Extra `memtrace mcp` processes attach to the existing
owner's loopback endpoint instead of opening a duplicate store. See
[`mcp-and-transports.md`](mcp-and-transports.md) for the multi-agent
picture.

## Relevant flags and env vars

| Flag / var | Applies to | Effect |
|---|---|---|
| `--workspace <path>` | `start`, `index`, `mcp` | Anchor the workspace at `path`; write the `.memtrace-workspace` marker. |
| `--no-workspace` | `start` | Skip multi-repo auto-detection; use git root or CWD only. |
| `MEMTRACE_WORKSPACE_ROOT=<path>` | env | Force the workspace anchor — useful for MCP hosts that launch Memtrace from an unexpected CWD. |
| `MEMTRACE_MEMDB_DATA_DIR=<path>` | env | Override the `.memdb/` location directly (e.g. a faster disk). |

Full references: [`cli-reference.md`](cli-reference.md) and
[`environment-variables.md`](environment-variables.md).

## When *not* to use a workspace

- **A single repo** — the git-root fallback already gives you one clean
  `.memdb/`. No marker needed.
- **Unrelated projects** — keep them in separate workspaces so their
  graphs (and impact analysis) stay isolated.
- **A monorepo where you only want part of it indexed** — use a
  [`.memtraceignore`](indexing-and-ignore-rules.md) instead of widening
  the workspace.

## Deleting / resetting

A workspace is its directories — nothing precious lives there that the
graph can't rebuild.

```bash
memtrace reset <repo_id>     # remove just one repo's records from the shared graph
rm -rf .memdb/               # wipe the whole workspace graph (daemon stopped)
rm .memtrace-workspace       # demote back to per-repo stores
```

The next `memtrace start` / `memtrace index` re-indexes from scratch.
Your source code is never touched.
