# Memtrace v0.3.88 — Lua + Swift + infra language coverage, UI filters, leaner counts

The biggest single-release expansion to date: five new programming-language families, eleven new framework scanners, and a UI that lets you focus on what you care about.

## TL;DR

| Area | Was | Is |
|---|---|---|
| **Indexed languages** | 16 | **20+** — Lua and Swift land as first-class, plus YAML / HCL / JSON / TOML / SQL get full AST parsing |
| **Framework scanners** | Express / Encore / NestJS / RTK / TanStack / SWR / Rails routes / FastAPI / Flask / Django / Gin / Chi / Echo / Actix | **+ Vapor, Hummingbird, URLSession, AsyncHTTPClient, SwiftUI, Lapis, OpenResty, Kong, Wippy, GitHub Actions, Terraform variable refs, `package.json` deps, `Cargo.toml` deps, PostgreSQL RLS policies** |
| **Repository node/edge counts** | overcounted by ~4–5× (bi-temporal replay rows counted as separate edges) | live-only, deduped — matches the canvas exactly |
| **`memtrace reset <repo>` after upgrade** | sometimes failed with `codec: bad kind N` on stored records with torn-page corruption — forced a full `.memdb` wipe | tolerant — corrupt records skipped with a warn log, the reset completes |
| **Generic config files (random YAML / JSON / TOML)** | every key in every file in `benchmarks/`, `datasets/`, `tests/fixtures/` became a graph node — flooded the canvas | default ignore baseline skips obvious noise paths; framework files (`Cargo.toml`, `package.json`, `.github/workflows/`) still fire normally |
| **Graph view default** | every node kind shown — dense and unreadable on real repos | code-only view by default; toggle config / IaC / DB families on individually via the **Visible Kinds** panel (top-left of the canvas) |
| **Node-kind colors** | 16 colored kinds, the new ones rendered as featureless grey circles | every kind has a distinct color in the **Node Types** legend |
| **Inspector source preview** for config nodes | "No source available" — config-key nodes had `start_line` but no `content` | source slice populated (up to 4 KB), shown in the inspector code tab |

## New language coverage

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

Generic key extraction + GitHub Actions specific. Helm `Chart.yaml` and Kubernetes manifests continue to flow through their typed parsers (unchanged); other YAML routes through tree-sitter. **GitHub Actions scanner** emits `CIJob` per top-level job, `CIStep` per step, and `JobDependency` edges from `needs:` declarations — so workflow graphs become first-class.

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

## UI changes

### Visible Kinds filter panel

New collapsible panel in the top-left of the graph canvas. Each node kind has a checkbox grouped by family (Programming / Config / IaC / DB). Defaults to **code-only**: programming kinds visible, the config / IaC / DB kinds hidden. One click on **Show all** reveals everything. **Reset defaults** returns to code-only.

State persists in your browser's localStorage — your choice survives reload.

**Important contract**: the filter affects the canvas only. Agent queries through MCP (`find_symbol`, `find_code`, `get_impact`, etc.) still see every kind regardless of what's toggled. This matches the panel's tooltip text — your agent doesn't get filtered out from under it.

### Node Types legend

Now shows all kinds with distinct colors. Config kinds (cyan family), IaC kinds (orange family), DB kinds (purple family). Hidden kinds (per the Visible Kinds panel) render at 40% opacity in the legend.

### Inspector content for non-function nodes

Click a config node and the inspector's code tab now shows the source slice (up to 4 KB, capped on huge files with a `<… N bytes elided …>` marker). Previously you'd see "No source available" because only function/class nodes populated the content field.

## Default ignore baseline

Memtrace now ships a built-in `.memtraceignore` baseline that auto-skips obvious noise paths before they get parsed:

- `benchmarks/**`, `**/datasets/**`, `**/test_data/**`, `**/tests/fixtures/**`, `**/__fixtures__/**`
- `**/*.gen.{json,ts,go,py,rs}`, `**/*.fixture.{json,yaml,toml,yml}`
- `**/node_modules/**`, `**/target/**`, `**/.next/**`, `**/dist/**`, `**/build/**`, `**/coverage/**`
- `**/package-lock.json`, `**/yarn.lock`, `**/pnpm-lock.yaml`
- `**/.vscode/**`, `**/.idea/**`, `**/.DS_Store`

Your existing `.memtraceignore` overlays on top — `!path` re-include syntax still works for the rare case you do want a benchmark fixture indexed. See [`indexing-and-ignore-rules.md`](docs/indexing-and-ignore-rules.md) for the full layer order.

**Concrete impact**: on a large repo with benchmark fixtures, dataset dumps, and generated configs, node count drops 70–90% on re-index. Real code stays untouched. `Cargo.toml` and `package.json` etc. still get scanned even if they live under a noise path — framework scanners are filename-gated and run regardless.

## `memtrace status` — new skip counters

```
  Indexed:                       1,247 files
  Skipped by default ignore:        42 files
  Skipped by user .memtraceignore:   8 files
  Skipped by scanner gate:          18 files
```

JSON output (`--json`) exposes the same numbers under `.noise_filter`.

## Bug fixes for existing users

### `memtrace reset <repo>` after upgrade

A latent torn-page bug in the write-ahead log could leave a record with a corrupt 1-byte kind discriminator. Pre-fix, `delete_by_property` would bubble `codec: bad kind N` and abort, leaving users stuck with a `.memdb` they had to wipe manually. Post-fix, the reader skips the corrupt record with a rate-limited warn log and the reset completes. Other records in the same database stay intact.

You should never need to wipe your `.memdb` after an upgrade again.

### Repository counts in `/api/repos`

Previously the dashboard's repository sidebar showed `0 nodes` because the live-count call silently swallowed errors. Now you'll see live node + edge counts that match the canvas. When a count genuinely fails, the count comes back `null` AND a warn log is emitted — no more silent zeros.

### Edge over-count

The same endpoint also over-counted edges by ~4–5× because every per-commit replay row was counted independently. Now de-duplicated by `(source, target, kind)` triple, same shape the canvas uses. The dashboard and the canvas finally agree.

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

## Acknowledgements

Field-report shape from real dogfood sessions on a Next.js + Supabase + Drizzle production codebase drove most of these. The RLS-policy + cross-language edges, the test-fixture column-drift scenario, the "is this in benchmarks or in code?" question — all surfaced from real use, not speculation.

## See also

- [`docs/indexing-and-ignore-rules.md`](docs/indexing-and-ignore-rules.md) — the full ignore layer order including the new baseline
- [`docs/tools.md`](docs/tools.md) — MCP tool catalogue
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common upgrade questions
