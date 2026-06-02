# Memtrace v0.3.89 — Lua + Swift + infra-language coverage, UI filters, leaner counts, field-report fixes

The biggest single-release expansion to date AND the largest community-driven bug-fix round. Two parallel work streams roll up here:

- **Indexing & UI surface** — five new programming-language families, eleven new framework scanners, default-ignore baseline, Visible Kinds filter panel, node-type colour parity, inspector source preview for config nodes.
- **Field-report fixes** — eight bugs filed by **@Magalz**, **@Badmrpotatohead**, and **@Corpo** between 2026-05-07 and 2026-05-10 ship as fixes or hardening in this release.

(0.3.88 was prepared but never published — this release rolls everything since 0.3.87 into one drop.)

## TL;DR

| Area | Was | Is |
|---|---|---|
| **Indexed languages** | 16 | **20+** — Lua and Swift land as first-class, plus YAML / HCL / JSON / TOML / SQL get full AST parsing |
| **Framework scanners** | Express / Encore / NestJS / RTK / TanStack / SWR / Rails routes / FastAPI / Flask / Django / Gin / Chi / Echo / Actix | **+ Vapor, Hummingbird, URLSession, AsyncHTTPClient, SwiftUI, Lapis, OpenResty, Kong, Wippy, GitHub Actions, Terraform variable refs, `package.json` deps, `Cargo.toml` deps, PostgreSQL RLS policies** |
| **Repository node/edge counts** | overcounted by ~4–5× (bi-temporal replay rows counted as separate edges) | live-only, deduped — matches the canvas exactly |
| **Generic config files (random YAML / JSON / TOML)** | every key in every file in `benchmarks/`, `datasets/`, `tests/fixtures/` became a graph node — flooded the canvas | default ignore baseline skips obvious noise paths; framework files (`Cargo.toml`, `package.json`, `.github/workflows/`) still fire normally |
| **Graph view default** | every node kind shown — dense and unreadable on real repos | code-only view by default; toggle config / IaC / DB families on individually via the **Visible Kinds** panel (top-left of the canvas) |
| **Node-kind colors** | 16 colored kinds, the new ones rendered as featureless grey circles | every kind has a distinct color in the **Node Types** legend |
| **Inspector source preview** for config nodes | "No source available" — config-key nodes had `start_line` but no `content` | source slice populated (up to 4 KB), shown in the inspector code tab |
| **`memtrace install` on upgrade** | overwrote `~/.memtrace/` — session ledger, embed cache, auth tokens, everything wiped | upgrade preserves all user data; only explicit `npm uninstall -g memtrace` removes anything, and even that requires `MEMTRACE_PURGE_DATA=1` to wipe `~/.memtrace/` |
| **Daemon on Windows** | `memtrace daemon start` printed "started", exited 2-3 s later, left no log file | startup health-check loop polls `/api/health` before declaring success; failures surface a real reason; `~/.memtrace/logs/daemon.log` always written; `--foreground` mode for in-shell debugging |
| **Windows path separators** | `D:\Repos\proj\src/foo.ts` (mixed `\` + `/`) failed `ERROR_PATH_NOT_FOUND` on incremental delta | every path normalised to a single canonical form (forward slashes, lowercased drive letter, no `\\?\` prefix) at three layers: walker, incremental delta, stored `file_path` properties |
| **Duplicated symbols on Windows** | the same file stored as `D:\Repos\proj\...` AND `\\?\D:\Repos\proj\...` — symbols showed up 2-3× in `find_most_complex_functions` / `get_codebase_briefing` / `find_dead_code` | one canonical form; existing graphs with both forms get read-time dedup so you don't need a full re-index |
| **`find_dead_code`** | returned tombstoned symbols (Shadcn components removed 3 days ago still listed) | HEAD-only by default — only currently-live tombstones surface; `include_historical: true` available for explicit history queries |
| **`delete_repository` / `memtrace reset`** | sometimes failed with `codec: bad kind N` on torn-page corruption — forced a full `.memdb` wipe | tolerant — corrupt records skipped with a warn log, the reset completes (both node and edge sides) |
| **Watch directory registrations** | vanished on MCP disconnect — `list_watched_paths` returned `count: 0` after restart | persist to `~/.memtrace/watches.json`; restored on every MCP boot; each entry tagged `origin: manual` or `origin: restored` |
| **Agent says "Memtrace index is empty (0 nodes, 0 edges)"** | MCP server with a dual-`.memdb` anchor mismatch returned silently empty — agent abandoned Memtrace and fell back to grep | empty-state responses now carry a `_meta` envelope explaining how the data dir was chosen, the resolved path, and a classified `empty_state_reason` the agent can branch on |
| **Value ledger ("140 calls / $0.00")** | ledger anchored to per-workspace `data_dir` — `memtrace mcp` (cwd = agent's dir) and `memtrace start` (cwd = repo) wrote to / read from different files | ledger lives at user-global `~/.memtrace/session-ledger.jsonl`; both processes see the same data regardless of cwd |
| **A legacy backend env var** | every install wired a dead `*_BOLT_URL` env var into `~/.claude/settings.json` — relic from an earlier backend | installer no longer writes it; on upgrade your config gets the new clean shape (`env: {}`) |

---

## Part 1 — New language coverage

Five new parsers, each with the same depth as the existing ones:

### Lua

Functions, table-as-module idiom, `require()` imports, method-call expressions, cyclomatic complexity. Framework scanners:

- **Lapis** — `app:get/post/put/delete/match("/path", handler)` → routes
- **OpenResty** — `ngx.location.capture(path)` (subrequest) + `content_by_lua_block`
- **Kong** — `kong.router.exec(path)`, plugin handler discovery
- **Wippy** — wippy.ai variant detected; routes live in YAML (handled by the YAML scanner)
- **Outbound HTTP** — `socket.http.request`, `lua-resty-http`'s `httpc:request_uri`

### Swift

Functions, classes (unified `class_declaration` for class/struct/enum/extension/actor in modern Swift grammars), protocols, init/deinit, return + parameter types, cyclomatic complexity including `guard let`. Framework scanners:

- **Vapor** — `app.get("path") { req in … }`, `routes.grouped("v1")`, `RouteCollection.boot(routes:)`
- **Hummingbird** — `app.router.get/post/put/delete`
- **URLSession** — `URLSession.shared.data(from:)`, `.dataTask(with:)`, `.upload(for:from:)`
- **AsyncHTTPClient** — `httpClient.execute(request:)`
- **SwiftUI tagging** — `View`/`App`/`Scene` conformances tagged for community detection

### YAML

Generic key extraction + GitHub Actions specific. Helm `Chart.yaml` and Kubernetes manifests continue to flow through their typed parsers (unchanged); other YAML routes through tree-sitter. **GitHub Actions scanner** emits `CIJob` per top-level job, `CIStep` per step, and `JobDependency` edges from `needs:` declarations — workflow graphs become first-class.

### HCL / Terraform

Resources, variables, modules, data sources. The existing regex-based Terraform parser still emits resource records; HCL adds the symbol graph — variable references (`var.region`), module composition (`module.vpc.public_subnets`), data references (`data.aws_ami.ubuntu.id`) become cross-symbol edges you can `get_impact` against.

### JSON / TOML

Generic key extraction + framework specifics:

- **`package.json` scanner** — `ScriptDefinition` per `scripts.*`, `Dependency` per `dependencies` / `devDependencies` / `peerDependencies` / `optionalDependencies` entry. Filename-gated (only fires on files literally named `package.json`).
- **`Cargo.toml` scanner** — same shape for Rust workspaces. `[dependencies]`, `[dev-dependencies]`, `[build-dependencies]`. Best-effort `pyproject.toml` reading for `[project.dependencies]`.
- TOML sections themselves become `TomlTable` nodes for navigation.

### SQL — including PostgreSQL RLS

`CREATE POLICY` / `CREATE TRIGGER` / `CREATE FUNCTION` indexed with table, verb (SELECT/INSERT/UPDATE/DELETE/ALL), role list, and the `USING (…)` + `WITH CHECK (…)` expression bodies. **Cross-language edges**: `SQLPolicy(table=public.users)` heuristically links to TS/Drizzle schema symbols matching the table name, so `get_impact` on an RLS policy surfaces the app-layer query sites that need to align with it.

This unlocks the bug class where an app-layer visibility filter and a DB-layer RLS policy quietly diverge — the policy and the schema are now in the same graph.

## Part 2 — UI changes

### Visible Kinds filter panel

New collapsible panel in the top-left of the graph canvas. Each node kind has a checkbox grouped by family (Programming / Config / IaC / DB). Defaults to **code-only**: programming kinds visible, the config / IaC / DB kinds hidden. One click on **Show all** reveals everything. **Reset defaults** returns to code-only.

State persists in your browser's localStorage — your choice survives reload.

**Important contract**: the filter affects the canvas only. Agent queries through MCP (`find_symbol`, `find_code`, `get_impact`, etc.) still see every kind regardless of what's toggled. This matches the panel's tooltip text — your agent doesn't get filtered out from under it.

### Node Types legend

Now shows all kinds with distinct colors. Config kinds (cyan family), IaC kinds (orange family), DB kinds (purple family). Hidden kinds (per the Visible Kinds panel) render at 40% opacity in the legend.

### Inspector content for non-function nodes

Click a config node and the inspector's code tab now shows the source slice (up to 4 KB, capped on huge files with a `<… N bytes elided …>` marker). Previously you'd see "No source available" because only function/class nodes populated the content field.

## Part 3 — Default ignore baseline

Memtrace now ships a built-in `.memtraceignore` baseline that auto-skips obvious noise paths before they get parsed:

- `benchmarks/**`, `**/datasets/**`, `**/test_data/**`, `**/tests/fixtures/**`, `**/__fixtures__/**`
- `**/*.gen.{json,ts,go,py,rs}`, `**/*.fixture.{json,yaml,toml,yml}`
- `**/node_modules/**`, `**/target/**`, `**/.next/**`, `**/dist/**`, `**/build/**`, `**/coverage/**`
- `**/package-lock.json`, `**/yarn.lock`, `**/pnpm-lock.yaml`
- `**/.vscode/**`, `**/.idea/**`, `**/.DS_Store`

Your existing `.memtraceignore` overlays on top — `!path` re-include syntax still works for the rare case you do want a benchmark fixture indexed. See [`docs/indexing-and-ignore-rules.md`](docs/indexing-and-ignore-rules.md) for the full layer order.

**Concrete impact**: on a large repo with benchmark fixtures, dataset dumps, and generated configs, node count drops 70–90% on re-index. Real code stays untouched. `Cargo.toml` and `package.json` etc. still get scanned even if they live under a noise path — framework scanners are filename-gated and run regardless.

### `memtrace status` — new skip counters

```
  Indexed:                       1,247 files
  Skipped by default ignore:        42 files
  Skipped by user .memtraceignore:   8 files
  Skipped by scanner gate:          18 files
```

JSON output (`--json`) exposes the same numbers under `.noise_filter`.

---

## Part 4 — Field-report fixes

This release is almost entirely community-driven on the bug side. Eight bugs filed by **@Magalz**, **@Badmrpotatohead**, and **@Corpo** between 2026-05-07 and 2026-05-10 — every one of them ships as a fix or hardening here. Thank you for the precise repros and the patience while I worked through them.

### @Badmrpotatohead — critical data loss on upgrade

> Running `memtrace install` to upgrade v0.3.85 → v0.3.86 wiped `C:\Users\csaru\.memtrace\` — including `session-ledger.jsonl` and the full graph index.

**Root cause**: npm fires the package's `preuninstall` lifecycle when it's replacing an existing global install. Nothing in our uninstall path distinguished "user asked to uninstall" from "npm is upgrading me." Result: every upgrade purged user data.

**Fix**: two new helpers —
- `isUpgradeLifecycle(env)` — `true` if `MEMTRACE_INSTALL_PARENT=1` is set (which `bin/memtrace.js` now sets when self-upgrading) OR npm's `npm_lifecycle_event=preuninstall` combined with `npm_command` in `(install|update|upgrade)`.
- `shouldPurgeMemtraceHomeDir(env)` — only true when the user *explicitly* opts in via `MEMTRACE_PURGE_DATA=1` (or its alias `MEMTRACE_UNINSTALL_PURGE_DATA=1`) AND the lifecycle is *not* an upgrade.

**Net behavior**: `npm install -g memtrace@latest` is now data-preserving. Even `npm uninstall -g memtrace` preserves user data by default — you have to set `MEMTRACE_PURGE_DATA=1` for a clean wipe.

**Action for you**: nothing. Upgrade safely.

### @Badmrpotatohead — value ledger 140 history / 0 queries

> The session view shows "140 historical calls counted" but "0 queries / $0.00 cost".

**Root cause**: ledger writes were anchored to `data_dir` (the workspace-local `.memtrace/`). When `memtrace mcp` was launched by an agent from a different cwd than `memtrace start`'s dashboard process, each anchored `data_dir` to its own location — the dashboard read from a file the MCP server never wrote to.

**Fix**: ledger now writes to **`~/.memtrace/session-ledger.jsonl`** — user-global, single source of truth across processes. Path is overridable via `MEMTRACE_SESSION_LEDGER`. `/api/value/aggregate` with no `repo_id` now reads this file first (falling back to the graph-backed ledger for repo-scoped queries).

**Action for you**: nothing if you just want the dashboard to show real numbers again. If you were relying on per-workspace ledger isolation, set `MEMTRACE_SESSION_LEDGER=<workspace>/.memtrace/session-ledger.jsonl` to preserve the old behavior.

### @Magalz — daemon dies silently on Windows + watchers don't survive

> `memtrace daemon start` reports "started" but the process exits in 2-3 seconds. Windows Service registered via `memtrace daemon install` is stuck Stopped. No log files in `~/.memtrace/logs/`. And the watchers I set up don't survive between sessions.

Three coupled problems:

1. **Optimistic "started" message** — the launcher didn't actually probe the daemon. Whatever crashed it stayed invisible.
2. **No daemon log** — the tracing subscriber wrote to stderr only. A daemon that exits before its first stderr flush leaves nothing.
3. **In-memory-only watches** — `watch_directory` registrations lived in the MCP server's heap; on disconnect they were gone.

**Fix**:

- `memtrace daemon start` now polls `http://localhost:<MEMTRACE_UI_PORT>/api/health` for up to 10 seconds (500 ms intervals). Success path: prints `memtrace daemon: running (pid N)`. Failure path: prints `memtrace daemon: did not bind within 10s — check ~/.memtrace/logs/daemon.log` with the actual reason in the log.
- New rolling file appender writes `~/.memtrace/logs/daemon.log` (max 5 files, rotated at 10 MB) — populated from the first startup tick, so even a "dies immediately" failure leaves a breadcrumb.
- New `memtrace daemon start --foreground` (alias `--verbose`) runs the daemon in your current shell — failures go straight to your stderr. Cleanest debugging path on Windows.
- Windows Service installer (`memtrace daemon install`) now starts the service and health-checks it before declaring success.
- **Watch persistence**: every `watch_directory` registration writes to `~/.memtrace/watches.json` atomically. On MCP boot, each entry is re-armed; `list_watched_paths` returns the restored set immediately, each entry tagged `origin: "manual"` or `origin: "restored"`. Escape hatch: `MEMTRACE_NO_WATCH_RESTORE=1` skips the restore step.

**Action for you**: if your watches got lost across upgrades, just re-run `watch_directory` once after upgrading — that registration will survive subsequent restarts.

### @Magalz — `find_dead_code` returns deleted symbols

> 17 Shadcn UI symbols (`CommandSeparator`, `DialogTrigger`, etc.) that I removed 3 days ago still show up as live dead-code candidates.

**Root cause**: same shape as the `/api/repos` overcount fix — the query walked every node `list_records` returned without consulting the indexer-stamped `invalid_at` property. Per-commit replay tombstones survived the read because the storage engine's bi-temporal predicate keys off the record header (which the deletion replay path leaves at `STILL_VALID`), not the property the indexer stamps when it sees a symbol disappear from the tree.

**Fix**: `find_dead_code` now applies a HEAD filter by default — only nodes whose `invalid_at` is `STILL_VALID` (or in the future) at `as_of_micros` (defaulting to now) are returned. Tombstoned nodes are dropped.

Two new optional parameters:

- `include_historical: bool` (default `false`) — when `true`, returns the prior behaviour (full history). Useful if you actively want to inspect what was dead in the past.
- `as_of_micros: i64` (default: now) — supply a timestamp to view dead-code at a specific moment.

**Property invariant**: historical mode result-set ≥ HEAD-only mode for the same query. Verified across 1,024+ random-graph property cases.

**Action for you**: nothing — default behaviour is now the one you want. If you specifically want the old behaviour, pass `include_historical: true`.

### @Magalz — Windows path separator mismatch + `\\?\` dedup

Two related bugs:

> #4: Incremental parse fails for `D:\Repos\agenda-clubber\scripts/migrate.mjs` with `error 3 (ERROR_PATH_NOT_FOUND)`. Looks like mixed `/` and `\` from string concat instead of `PathBuf::join`.

> #5: Symbols appear 2-3× in `find_most_complex_functions`, `get_codebase_briefing`, `find_dead_code`. Same file stored as `D:\Repos\…` AND `\\?\D:\Repos\…`. v0.3.85 fixed `repo_id` but not the per-symbol `file_path`.

**Root cause**: paths were entering Memtrace from multiple sources (watcher events, incremental delta, scanner output) and each was applying its own ad-hoc normalisation. Some kept `\\?\`, some kept native `\`, some mixed both.

**Fix**: a single canonical-form helper now sits at three layers:

1. **Walker / incremental delta** — every path is normalised before it's handed to OS filesystem APIs (fixes #4).
2. **All scanners that emit `CodeNode.file_path`** — paths canonicalised *before* storage (fixes #5 for new indexing).
3. **Query layer** (`find_most_complex_functions`, `get_codebase_briefing`, `find_dead_code`) — paths normalised at *read time* too, so existing graphs with mixed-form records still dedupe correctly without forcing a full re-index.

Canonical form on Windows: forward-slash separators, lowercased drive letter, no `\\?\` prefix, no trailing slash. UNC paths preserved (`\\server\share\…`).

**Action for you**: nothing if you re-index. If you don't re-index, the read-time normalisation pass handles the dedup transparently.

### @Magalz — `delete_repository` fails `codec: bad kind 164`

> `memtrace reset <repo>` and the MCP `delete_repository(repo_id)` both fail with: `embedded: delete_by_property(Edge, repo_id) failed: codec: bad kind 164`.

**Root cause**: the previous Node-side WAL torn-page tolerance (added during the dogfood round before this release) shipped via a submodule pointer bump. Binaries built before that pointer landed hit the bug. Edge-side coverage was already there at the codec layer — the field report surfaced the binary-vintage gap.

**Fix**: 55 new TDD + 14 property-test blocks (~1,000 effective cases) covering random discriminator bytes for Edge kind. Property invariant: iteration always terminates; no input panics the decoder. Together with the node-side wrapper this means `delete_repository` survives any combination of torn-page corruption.

**Action for you**: upgrade and your stuck `memtrace reset` will complete.

### @Corpo — agents abandon Memtrace at session start

> "Re-index on every session start" copy is confusing. — Plus a screenshot where the agent reports: "The Memtrace index is empty (0 nodes, 0 edges) — need to reindex before using graph tools. Let me do that while reading the current query router directly."

**Root cause**: the MCP server's first call (typically `list_indexed_repositories`) was returning a bare empty array when the workspace anchor resolved to a different `.memdb` than the daemon's. The agent had no way to tell "Memtrace's workspace is empty" apart from "Memtrace is broken / wrong anchor" — so the prudent assumption was "this is broken, fall back to grep." That's the worst possible UX: users have Memtrace installed but the agent stops using it.

The actual failure mode was **anchor mismatch**: `memtrace mcp` (launched by the agent) and `memtrace start` (launched by the user from the repo) anchored their `data_dir` from different cwds.

**Fix**: every empty-state MCP response now carries a `_meta` envelope describing the anchor decision. Non-empty responses pass through bit-for-bit identical to pre-fix, so legacy parsers keep working.

Example empty-state response now:

```jsonc
{
  "result": [],
  "_meta": {
    "anchor_source": "cwd_fallback",      // env_override | workspace_marker | git_root | cwd_fallback
    "data_dir": "/Users/you/some/agent-cwd/.memdb",
    "workspace_root": "/Users/you/some/agent-cwd",
    "cwd": "/Users/you/some/agent-cwd",
    "warming": false,
    "empty_state_reason": "no_workspace_marker_in_cwd_chain"
  }
}
```

Agents (or your custom MCP client) can read `_meta.empty_state_reason` and decide: re-index, retry, or surface the anchor mismatch to the user. The MCP tool description for `list_indexed_repositories` now tells the agent to check this envelope before deciding to re-index.

**Action for you**: drop an empty `.memtrace-workspace` file at your project's top-level directory. The anchor resolves there for both `memtrace mcp` and `memtrace start`, and this scenario stops being possible. See [`docs/data-directories.md`](docs/data-directories.md#where-memdb-actually-lives--workspace-anchor) for the full discovery order. If your agent has hardcoded "always reindex on empty result" logic, consider branching on `_meta.empty_state_reason` instead — `workspace_genuinely_empty` means re-index makes sense; `no_workspace_marker_in_cwd_chain` means the agent is looking at the wrong directory and re-indexing won't help.

---

## Part 5 — Behavior changes you should know about

### Value ledger location

`~/.memtrace/session-ledger.jsonl` is the new home (was `<workspace>/.memtrace/session-ledger.jsonl`). If you've scripted around the old path:
- Override with `MEMTRACE_SESSION_LEDGER=<absolute path>` to keep your old location.
- Or copy your existing per-workspace ledger to `~/.memtrace/session-ledger.jsonl` once.

The dashboard's `/api/value/aggregate` endpoint reads the user-global file by default; only `?repo_id=…` queries fall back to the graph-backed ledger.

### MCP empty-state response shape

Empty-state results from `list_indexed_repositories` (and other index-discovery tools) now wrap their payload in a `{ result, _meta }` envelope. Non-empty responses are unchanged. If you parse MCP responses defensively (`response.result ?? response`), nothing breaks. If you assume the result is always a bare array, check `_meta` for the loading / anchor signals.

### Watch persistence

Watches now survive across MCP disconnects via `~/.memtrace/watches.json`. The file is JSON-array-of-objects, atomic write, BOM-tolerant on read. To clear all watches: delete the file.

### Daemon log location

`~/.memtrace/logs/daemon.log` (rotated at 10 MB, max 5 files). The directory is created on first daemon start.

### Legacy backend env vars are ignored

A legacy storage backend was removed in an earlier version, but the env-var plumbing was missed in that cleanup — fresh installs were still wiring a dead `*_BOLT_URL` env var into `~/.claude/settings.json` (and Cursor's `mcp.json`, etc.). That's gone now. The binary still tolerates the env var being set (so existing configs don't break) but nothing reads it. On next install the installer overwrites the `memtrace` MCP entry's `env` block to the new shape (`env: {}`), so the legacy var disappears naturally. If you want immediate cleanup, just delete the `env` block from your MCP config — Memtrace doesn't need any env vars for the basic case.

## Part 6 — New env vars

| Var | Purpose |
|---|---|
| `MEMTRACE_PURGE_DATA=1` | Opt-in flag: `npm uninstall -g memtrace` will purge `~/.memtrace/`. Without it, uninstall preserves user data. |
| `MEMTRACE_UNINSTALL_PURGE_DATA=1` | Alias for the above. |
| `MEMTRACE_NO_WATCH_RESTORE=1` | Skip the watch-list restore on MCP boot. Use if you have stale watch state you want forgotten. |
| `MEMTRACE_SESSION_LEDGER=<path>` | Override the user-global ledger path. Useful for sandboxed test runs or per-workspace isolation. |
| `MEMTRACE_INSTALL_PARENT=1` | Set internally by `bin/memtrace.js` when self-upgrading; agents shouldn't need to set this. |
| `MEMTRACE_DAEMON_HEALTH_TIMEOUT_MS` | How long `memtrace daemon start` polls `/api/health` before giving up (default 10000). |
| `MEMTRACE_DAEMON_HEALTH_INTERVAL_MS` | Polling interval (default 500). |

## Part 7 — New API surface

- `GET /api/health` — daemon liveness probe (used by the new health-check loop in `memtrace daemon start`). Returns `{ status: "ok" }` when the dashboard is serving requests. Useful for external monitoring too.

## What didn't change

- Existing MCP tool surface (`find_symbol`, `find_code`, `get_impact`, etc.) — same shapes, no breaking changes
- Helm Chart / K8s manifest typed parsers — still run for those specific filenames
- Existing scanners (Express, NestJS, RTK Query, Rails routes, FastAPI, Gin, etc.) — untouched
- The `.gitignore` / `.memtraceignore` semantics — additive: defaults BEFORE user file, user file overlays

## Storage growth — known and deferred

Memtrace's graph is bi-temporal: every save / commit / re-index **appends** rows, it doesn't overwrite. Old rows get marked `invalid_at` rather than deleted, because that's what powers `get_evolution`, `replay_history`, and "what did this look like 3 commits ago" queries.

In practice, on a 100K-LOC repo over a year of dev work, this comes to a few hundred MB on disk. Not a problem.

In theory, it's unbounded. We don't yet have a WAL-compaction pass (PostgreSQL would call this `VACUUM`; LSM-tree DBs call it compaction). When we add one, the retention policy will be a product decision — keep all tombstones forever? 90 days? until the next git tag? — not a code one.

**Note**: the displayed node + edge counters in `/api/repos` and the canvas are already deduped at query time (live rows only, deduped by `(source, target, kind)` triple). So you'd only notice the on-disk growth if you `ls -lah ~/.memdb` or watch the data-dir size yourself. Until we ship compaction, `memtrace reset <repo>` followed by `memtrace index` is the workaround if you ever want a clean slate.

## Test surface

~500 new TDD cases + ~115 property-test blocks (tens of thousands of effective cases) added across this release. Every reported bug is locked as a regression test. Workspace gate green with zero pre-existing failures (10 latent tests cleared as part of round closure).

## How to upgrade

```bash
npm install -g memtrace@latest
```

Or manually:

```bash
memtrace install
```

Both paths are now data-preserving. If you set `MEMTRACE_PURGE_DATA=1` in your shell before running `npm uninstall`, you get the explicit wipe. Otherwise your `~/.memtrace/` and `.memdb/` survive.

## Acknowledgements

To **@Magalz**, **@Badmrpotatohead**, and **@Corpo** — sharp repros, concrete repros, patience while I worked through them. Most of the bug-fix half of this release wouldn't exist without your reports. If you've got more, the Discord is the right place.

Field-report shape from real dogfood sessions on a Next.js + Supabase + Drizzle production codebase drove most of the indexing side. The RLS-policy + cross-language edges, the test-fixture column-drift scenario, the "is this in benchmarks or in code?" question — all surfaced from real use, not speculation.

— alexthh

## See also

- [`docs/indexing-and-ignore-rules.md`](docs/indexing-and-ignore-rules.md) — the full ignore layer order including the new baseline
- [`docs/environment-variables.md`](docs/environment-variables.md) — every env var Memtrace reads
- [`docs/data-directories.md`](docs/data-directories.md) — what lives where on disk, what's safe to delete
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common upgrade questions including the "Memtrace index is empty" agent symptom
- [`docs/tools.md`](docs/tools.md) — MCP tool catalogue
