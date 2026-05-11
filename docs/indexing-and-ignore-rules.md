# Controlling what gets indexed

Memtrace's filesystem walker is **gitignore-aware out of the box**. You can
also drop a `.memtraceignore` file for paths you want git to track but
Memtrace to skip, and there's a built-in always-on skip list for
dependency / build / cache directories. This page explains all three
layers and how to verify what's being indexed.

## TL;DR

| Layer | Honoured by default? | Configurable? |
|---|---|---|
| `.gitignore` (any level) + `.git/info/exclude` + global gitignore | ✅ yes | turn off with `--no-ignore-vcs` on `index_directory` |
| **Default ignore baseline** (`benchmarks/`, `datasets/`, `tests/fixtures/`, generated files, lock files, …) | ✅ always on, shipped with the binary | override with `!path` rules in `.memtraceignore` |
| `.memtraceignore` (repo root) | ✅ yes when present | edit the file |
| Built-in skip list (`node_modules`, `target`, `dist`, …) | ✅ always on | not user-configurable |
| File-extension skip list (binaries, media, archives) | ✅ always on | not user-configurable |
| File-name skip list (lock files, `.env`, `LICENSE`, …) | ✅ always on | not user-configurable |
| Max file size (512 KB) | ✅ always on | not user-configurable |

If a path is excluded by **any** of the above layers, it doesn't get
indexed.

## Layer 0 — Default ignore baseline (built-in, added in v0.3.88)

When Memtrace added generic YAML / JSON / TOML / SQL / HCL parsing, a
practical problem appeared: every key in every benchmark fixture,
dataset dump, generated config, and lock file became a graph node.
On a real repo that's tens of thousands of useless `ConfigKey` nodes
buried under a few hundred real symbols. The default baseline fixes
that by skipping the obvious noise before files are parsed.

The list shipped in v0.3.88:

```
benchmarks/**/*
**/datasets/**
**/test_data/**
**/tests/fixtures/**
**/__fixtures__/**
**/__test_data__/**
**/*.gen.{json,ts,go,py,rs}
**/*-fixture.{json,yaml,toml,yml}
**/*.fixture.{json,yaml,toml,yml}
**/node_modules/**
**/target/**
**/.next/**
**/dist/**
**/build/**
**/coverage/**
**/package-lock.json
**/yarn.lock
**/pnpm-lock.yaml
**/.vscode/**
**/.idea/**
**/.DS_Store
```

**Important:** framework-aware scanners (`Cargo.toml`, `package.json`,
`pyproject.toml`, `.github/workflows/*.yml`, Helm `Chart.yaml`, K8s
manifests, Terraform `*.tf`, SQL migrations) are **filename-gated**
and still fire even if the file lives under a default-ignored
directory. A `package.json` inside `tests/fixtures/sample-pkg/`
*will* emit its scripts and dependencies as graph nodes. The skip
only applies to the **generic** config-key extractors that would
otherwise emit a `ConfigKey` per `key: value` pair.

If you do want a specific file under a noise path indexed for its
generic content too, add a `!` re-include to your `.memtraceignore`:

```
# .memtraceignore
!tests/fixtures/special-config.yaml
```

User patterns overlay the baseline — the same `!path` override
semantics gitignore uses.

To see the per-category skip counters for a session:

```
memtrace status
```

prints lines like:

```
  Indexed:                       1,247 files
  Skipped by default ignore:        42 files
  Skipped by user .memtraceignore:   8 files
  Skipped by scanner gate:          18 files
```

`Skipped by scanner gate` is a defence-in-depth: the generic
config-key extractors also check the same patterns, so a fixture
file that reaches them somehow still produces zero `ConfigKey`
emission. JSON form (`memtrace status --json`) exposes the same
numbers under `.noise_filter.*`.

Counters are process-lifetime; they reset only when the daemon
restarts.

## Layer 1 — Your gitignores (always honoured)

Memtrace uses Rust's `ignore` crate (the same library `ripgrep` and `fd`
use), so it respects every place git looks for ignore rules:

- `.gitignore` files at every level of the tree (repo root, subdirs)
- `.git/info/exclude` (your local-only excludes)
- The global gitignore configured by `git config --global core.excludesfile`
- `.git/hooks/...` and any vendored `.git/` content

This means: **if a path is already ignored by git, you don't need to do
anything for Memtrace.** It's already invisible to the indexer.

To verify a specific path is ignored:

```bash
git check-ignore -v path/to/file
# Prints the matching gitignore rule, or exits non-zero if NOT ignored.
```

If `git check-ignore` says it's ignored, Memtrace will skip it too.

## Layer 2 — `.memtraceignore` (Memtrace-specific)

For paths you want **git to track** but **Memtrace to skip**, drop a
`.memtraceignore` file at the repo root. Same syntax as `.gitignore`:

```
# .memtraceignore — at the repo root

# Generated protobuf bindings: in source control, but huge and uninteresting
generated/
*.pb.go
*.pb.ts

# Auto-emitted route trees and migration files
src/routeTree.gen.ts
drizzle/migrations/

# Test fixtures with megabyte JSON blobs we don't want embeddings of
tests/fixtures/large/

# Vendored dependency you committed but don't want analysed
third_party/legacy-sdk/
```

The same syntax as `.gitignore` applies: `*` globs, `**/` for any-depth,
leading `!` for negation, `/` at the end means directory-only, and so on.

Memtrace re-reads `.memtraceignore` on every `index_directory` call. If
file watching is on (`memtrace start` with watching enabled), changes to
`.memtraceignore` take effect on the next reindex of the affected paths.

**Why a separate file?** Some teams want git to keep generated bindings,
migration SQL, or fixture data tracked for review purposes — but those
files shouldn't pollute the symbol graph or burn embedding budget. The
two needs are orthogonal, so they get two files.

## Layer 3 — Built-in always-on skip list

Even with no `.gitignore` and no `.memtraceignore`, the walker hard-skips
the following — always:

### Directory names (skipped wherever they appear in the tree)

```
Package manager artefacts:
  node_modules, .yarn, .pnp, .npm, .pnpm, .pnpm-store,
  bower_components, .bower_cache

Build output:
  dist, out, .next, .nuxt, .svelte-kit, .turbo, storybook-static,
  .expo, .output, .vercel, .netlify

Compiled / vendor:
  vendor, target, bin, obj, pkg

Test / coverage:
  coverage, .nyc_output, htmlcov, lcov-report

Caches & virtual envs:
  .cache, __pycache__, .tox, .venv, venv, env, .env, .mypy_cache,
  .pytest_cache, .ruff_cache, .hypothesis, .eggs

IDE / editor:
  .idea, .vscode, .vs, .fleet

Infra state / generated:
  .terraform, .gradle, .m2, .ivy2

Docs / generated:
  _site, site, .docusaurus, .parcel-cache, .rollup.cache

Version control internals:
  .git, .hg, .svn

Local packaging artefacts (Memtrace tooling output):
  npm, skills

Memtrace's own state:
  .memdb (the local graph store — indexing this would feedback-loop)
  .claude (agent runtime state, especially .claude/worktrees/)
```

This list is the canonical source: see
[`crates/code-intelligence/src/ingestion/walker.rs`](https://github.com/syncable-dev/memtrace-public/blob/main/crates/code-intelligence/src/ingestion/walker.rs)
(`EXCLUDED_DIRS`).

### File extensions (skipped regardless of where they live)

```
Images: png, jpg, jpeg, gif, bmp, webp, ico, svg, tiff, tif, avif, heic, heif,
        raw, psd, ai, sketch, fig
Video/audio: mp4, mkv, avi, mov, wmv, flv, webm, m4v, mp3, wav, ogg, flac, aac, m4a, wma
Fonts: woff, woff2, ttf, otf, eot
Archives: zip, tar, gz, tgz, bz2, xz, 7z, rar, deb, rpm, pkg, dmg, iso, apk, ipa
Compiled: o, a, so, dylib, dll, exe, lib, class, jar, war, ear, pyc, pyo, pyd, wasm
Databases: db, sqlite, sqlite3, mdb, accdb
Documents: pdf, doc, docx, xls, xlsx, ppt, pptx, odt, ods, odp
Certs / keys: pem, key, crt, cer, pfx, p12, jks
Lock files: lock
Source maps: map
```

### Filenames (exact base-name match)

```
Lock files: yarn.lock, package-lock.json, pnpm-lock.yaml, npm-shrinkwrap.json,
            Gemfile.lock, Pipfile.lock, poetry.lock, Cargo.lock, composer.lock,
            mix.lock, pubspec.lock, Podfile.lock
Env / secrets: .env, .env.local, .env.development, .env.production,
               .env.staging, .env.test, .env.example, .env.sample
Version pins: .node-version, .nvmrc, .ruby-version, .python-version, .tool-versions
Ignore files: .gitignore, .npmignore, .dockerignore, .prettierignore, .eslintignore
Pure config: .editorconfig, .prettierrc, .prettierrc.json, .eslintrc,
             .eslintrc.json, .eslintrc.js, .stylelintrc, .babelrc
Licences: LICENSE, LICENSE.txt, LICENSE.md, NOTICE, COPYING
Changelogs: CHANGELOG, CHANGELOG.md, CHANGELOG.txt
Build artefacts: tsconfig.tsbuildinfo, .terraform.lock.hcl
Misc: thumbs.db, .DS_Store, desktop.ini
```

### Max file size

Files larger than **512 KB** are skipped. Minified bundles, yarn release
blobs, and generated single-file artefacts are typically hundreds of KB
and contribute no useful structure — they'd just dilute embeddings and
inflate the graph.

## Verifying what's actually being indexed

After running `memtrace start` (or `index_directory`), check what landed
in the graph:

```bash
# In your local UI (defaults to http://localhost:3030):
#   Repository panel — shows file count, language breakdown, repo paths

# Or via the MCP tools your agent has access to:
#   list_indexed_repositories       → repo IDs and roots
#   get_repository_stats(repoId)    → file/symbol/edge counts per repo
```

If a path you expected isn't there:

1. **Check git first.** `git check-ignore -v <path>` — if it prints a
   match, gitignore is filtering it. Edit your gitignore (or use a
   negation rule `!path`) if you want it indexed.
2. **Check `.memtraceignore`.** If it exists in your repo root, look for
   any pattern that matches the path. The syntax is identical to
   `.gitignore`, so the same `git check-ignore`-style mental model works.
3. **Check the always-on list above.** If the path is under
   `node_modules/`, `target/`, `dist/`, etc., it's hard-skipped and not
   user-configurable. The intent is that these directories are *never*
   meaningful to index.
4. **Check the file size.** Files >512 KB are skipped silently. If you
   need a big generated file indexed, you currently can't — open an
   issue with the use case.
5. **Check the file extension / name.** Binary blobs, lock files, and
   `.env*` files are never indexed. This is by design (`.env` files
   aren't indexed even when they're in your repo).

## Common patterns

**A monorepo where you only want one workspace indexed**

`.memtraceignore` at the repo root:

```
# Skip every package except the one we're working on
packages/*/
!packages/api/
```

**A repo with vendored / committed dependencies you don't want indexed**

```
third_party/
deps/
external/
```

**Generated code (proto, GraphQL, OpenAPI clients)**

```
*.pb.go
*.pb.ts
src/__generated__/
src/graphql/generated/
schemas/openapi.generated.ts
```

**Test fixtures with embeddings-unfriendly content**

```
tests/fixtures/
**/__snapshots__/
**/*.snap
```

## What about per-symbol exclusions?

Currently no — the smallest unit Memtrace can ignore is a file. If you
want a single function in a 5000-line file to not be indexed, the only
option is to extract it to a separate file you can `.memtraceignore`.
This is a known limitation; the structural cost of partial-file ignores
in a graph database is high enough we haven't built it.

## Reindexing after changing ignore rules

When you change `.gitignore` or `.memtraceignore`, the walker picks up
the new rules on the next `index_directory` call. Newly-ignored files
are *not* automatically removed from the graph — they're just skipped on
the next walk. To purge previously-indexed files that are now ignored:

```bash
# Re-index from scratch (drops the prior graph for this repo)
memtrace index --clear-existing /path/to/repo
```

Or via MCP:
```
index_directory(path="/path/to/repo", clear_existing=true)
```

If you only want to add new ignore rules without losing the existing
graph, the next incremental reindex (`memtrace index <path>` without
`--clear-existing`, or `index_directory` with `incremental: true`) will
detect deletions and remove orphaned symbols. This is generally the
right move when adding a few new patterns.

## See also

- [`getting-started.md`](getting-started.md) — first-time setup
- [`architecture.md`](architecture.md) — what indexing actually does at
  the symbol-graph level
- [`performance-tuning.md`](performance-tuning.md) — what to do when an
  indexed repo is bigger than you'd like
- [`environment-variables.md`](environment-variables.md) — runtime knobs
