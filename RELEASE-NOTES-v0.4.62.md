# Memtrace v0.4.62 - Workspace memory, code review workflow, GitHub App reviewer, benchmarks, and faster runtime

**Drafted:** 2026-05-21
**Scope:** product code review workflow, GitHub App integration, Martian benchmark readiness, multi-language review rules, runtime ownership, and MemDB cold-start work.

This release is the biggest Memtrace product step since the 0.4.x boot rewrite. Memtrace remains the memory layer for codebases: an indexed, temporal, embedded code graph that coding agents use for traversal, search, impact analysis, quality checks, and fresh context while users develop. This round adds code review as a major workflow on top of that foundation: Memtrace can review real GitHub pull requests, post comments through a GitHub App, and run the public Code Review Bench / WithMartian-style offline harness without replacing Memtrace with a separate benchmark-only script.

The important part: this is not a benchmark-only branch. The same review path is now exposed through the CLI, MCP, agent skills, and benchmark adapter.

## TL;DR

| Area | What changed |
|---|---|
| Product workflow | Added `memtrace code-review --pr <url> --post` for local-first GitHub PR reviews. |
| GitHub App | Added server-side GitHub App installation handling, webhook verification, and short-lived installation-token brokering through `memtrace-ui`. |
| MCP | Added a `review_github_pr` MCP tool so agents can run the same PR review flow. |
| Agent skills | Added the `memtrace-code-review` workflow skill for Claude, Cursor, Codex, and the existing skill installer paths. |
| Benchmark harness | Added Martian/Code Review Bench adapters that call the real Memtrace review workflow and inject results into the offline dataset. |
| Review quality | Added large multi-language rule coverage for auth, framework pitfalls, value semantics, determinism, param confusion, cross-module imports, and language-specific bug classes. |
| Graph policy | Added stricter review policy and graph gating so cross-module evidence can help without flooding low-confidence benchmark candidates. |
| Runtime | Added one-owner-per-workspace runtime attachment so duplicate `memtrace start` / `memtrace mcp` processes do not each open an embedded MemDB. |
| Cold start | Added MemDB work to persist more recovery/index state and bound boot replay, so large stores can become structurally ready faster. |
| User compatibility | No intentional breaking CLI or MCP changes. Existing `memtrace index .`, `memtrace start`, `memtrace mcp`, `memtrace stop`, and env overrides continue to work. |

## Why this release matters

Memtrace is not becoming "just a reviewer." The core product is still workspace memory for coding agents:

- code traversal and navigation over a real graph;
- temporal memory of how the codebase changed;
- incremental indexing so agent context stays fresh as users code;
- embeddings and semantic search for retrieval;
- impact analysis, relationships, quality checks, and regression discovery;
- persistent context that helps agents code better instead of re-reading the repo from scratch each turn.

The code reviewer is a feature built on that memory layer. Memtrace already had the hard part: a local code graph, temporal history, symbol search, impact analysis, cross-module relationships, embeddings, and quality tools. What was missing was a clean product loop for turning that memory into PR review output:

1. A developer indexes their workspace locally.
2. They push a branch and open a PR.
3. They run Memtrace against that PR from their machine.
4. Memtrace uses the local graph, local repo, and GitHub PR context to produce review comments.
5. The GitHub App posts comments back to the PR as Memtrace Code Reviewer.

That is now implemented.

This gives us the path we wanted for real online evidence without building a full SaaS code scanner. Source analysis stays on the user's machine. The hosted service handles only GitHub App auth, installation state, webhook verification, and token brokering.

## Product workflow: local-first GitHub PR review

New command:

```bash
memtrace code-review --pr https://github.com/OWNER/REPO/pull/123 --post
```

Useful options:

```bash
memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --max-comments 10 \
  --min-severity medium \
  --graph-mode strict
```

The command:

- resolves the GitHub PR;
- requests a short-lived installation token from the Memtrace token broker;
- fetches PR metadata and diff context;
- reads base-side files from the local git checkout where possible;
- runs the Memtrace review workflow against the actual PR diff;
- maps findings to changed right-side PR lines;
- posts GitHub review comments when `--post` is passed;
- supports dry-run mode for local inspection before posting.

This is a real product path, not a Python-only benchmark wrapper. The benchmark adapter calls into this same review logic rather than maintaining a separate scoring-only implementation.

## GitHub App integration

Added GitHub App support in `memtrace-ui`.

New server pieces:

- `memtrace-ui/src/server/github-app-core.ts`
- `memtrace-ui/src/server/github-app.ts`
- `memtrace-ui/src/routes/api/github/webhook.ts`
- `memtrace-ui/src/routes/api/github/installation-token.ts`
- `memtrace-ui/src/routes/github/setup.tsx`
- `memtrace-ui/drizzle/0008_github_app_installations.sql`

The hosted UI now handles:

- GitHub webhook signature verification;
- installation create/update/delete events;
- installation state persistence;
- repo-scoped installation-token minting;
- setup page after GitHub App installation;
- server-only handling of the GitHub App private key and webhook secret.

Security model:

- GitHub App private key stays server-side.
- Webhook secret stays server-side.
- CLI and local agents never contain the GitHub App private key.
- Source code review still runs locally.
- The hosted service does not need to ingest the user's codebase to produce review comments.

Required production env vars:

```bash
GITHUB_APP_ID=...
GITHUB_APP_CLIENT_ID=...
GITHUB_APP_CLIENT_SECRET=...
GITHUB_APP_PRIVATE_KEY_BASE64=...
GITHUB_APP_WEBHOOK_SECRET=...
GITHUB_APP_NAME=memtrace-code-reviewer
```

The migration that must run before production use:

```text
memtrace-ui/drizzle/0008_github_app_installations.sql
```

## MCP and agent workflow

Added MCP tool:

```text
review_github_pr
```

It accepts:

- `prUrl`
- `post`
- `repoRoot`
- `repoId`
- `graphMode`
- `minSeverity`
- `maxComments`

It calls the same implementation as the CLI. This is important because agents should not have a separate review engine from the product.

Added workflow skill:

```text
memtrace-code-review
```

Installed into:

- `skills/workflows/memtrace-code-review.md`
- `npm/memtrace/skills/workflows/memtrace-code-review.md`
- `npm/memtrace/installer/skills/workflows/memtrace-code-review.md`
- `installer/skills/workflows/memtrace-code-review.md`
- `installer/plugins/memtrace-skills/skills/memtrace-code-review/SKILL.md`

The skill is written for the same agent surface we already support: Claude, Cursor, Codex, and other agents that consume the Memtrace skill package.

## WithMartian / Code Review Bench readiness

This round added the missing pieces for a clean public benchmark workflow:

- a deterministic Memtrace review generator for the Martian offline dataset;
- result injection tooling for `benchmark_data.json`;
- fallback hooks where the benchmark needs enough candidates to score fairly;
- repo-id and MemDB data-dir overrides so the harness can point at the intended indexed workspace;
- Sentry/Grafana-oriented policy hardening without making the rules Sentry/Grafana-only;
- a GitHub App review path that can produce online PR evidence as Memtrace Code Reviewer.

The benchmark work lives under:

```text
scripts/martian-bench/
```

The key product decision: the benchmark harness should exercise Memtrace's review workflow. It should not become a detached benchmark-only Python implementation. The current adapter exists to feed the Martian dataset and collect results, but the review logic sits in Memtrace.

Current status:

- Local main contains the benchmark adapter and review workflow.
- The offline harness is ready for clean canonical runs.
- The online evidence path is now technically possible through the GitHub App.
- No public WithMartian PR/submission has been made by this release note.

Before submitting publicly, run one clean canonical benchmark run from a clean checkout and publish the exact run command, commit hash, `.env` assumptions, and generated results file.

## Multi-language review intelligence

This release adds broad bug-class coverage instead of one-off rules for individual benchmark files.

New and expanded categories:

- auth context and organization/member guard mistakes;
- JWT and API-key handling mistakes;
- Django and framework analogs across Rails, Spring, Prisma, EF Core, and related stacks;
- value semantics traps such as losing `0`, `false`, or empty values through truthiness defaults;
- determinism bugs such as unstable hash/cache keys and randomized iteration;
- parameter confusion and argument swaps;
- shadowed params and type narrowing mistakes;
- cross-module import/re-export resolution;
- Go, Java, TypeScript, JavaScript, Ruby, Python, C#, Rust, Swift, Kotlin, Lua, and C/C++ pattern broadening.

The goal was explicit: a pattern that is real in one language should be translated to other languages and frameworks where the same bug class exists. Where the trap does not translate cleanly, the rule should be skipped rather than forced into a high-false-positive shape.

Examples:

- Python `hash()` as a cache key is unstable across processes. Java `String.hashCode()` is not the same trap, so it should not be blindly ported.
- Python truthiness can lose `0` or empty containers. Ruby truthiness only treats `nil` and `false` as false, so the Ruby analog is narrower.
- Go map iteration is intentionally randomized, so serialization and deterministic ordering rules are valid there.

## Graph and cross-module policy

Graph evidence is valuable, but the benchmark punishes noisy extra candidates. This release does not treat "more graph findings" as automatically better.

The policy direction is:

- use graph/cross-module evidence when it improves localization and confidence;
- gate low-confidence graph findings before they crowd out precise AST/rule findings;
- keep `--graph-mode strict` as the default shape for public review quality;
- allow `--graph-mode off` for benchmark ablations or infrastructure debugging;
- do not let benchmark scoring pressure remove graph from the product.

This matters because Memtrace's long-term advantage is the indexed code graph and temporal memory. The immediate product fix is better ranking and policy filtering, not disabling graph permanently.

## Runtime owner and duplicate process control

Added a production runtime owner layer so one workspace store has one embedded MemDB owner.

Behavior:

- First process for a resolved `.memdb` becomes owner.
- Later processes for the same `.memdb` attach to the owner instead of opening another embedded store.
- A second `memtrace start` for the same workspace reports the existing owner/UI URL.
- `memtrace mcp` can attach to the existing owner.
- Different workspaces can still run concurrently.
- If UI port `3030` is busy, another workspace can choose a different port.

State files:

```text
<memdb_data_dir>/daemon.pid
<memdb_data_dir>/daemon-state.json
```

State includes:

- PID;
- loopback endpoint;
- UI port;
- store path;
- vector dim;
- embed model;
- status;
- heartbeat timestamp.

Compatibility:

- `MEMTRACE_MEMDB_DATA_DIR`
- `MEMTRACE_DATA_DIR`
- `MEMTRACE_UI_PORT`
- `MEMTRACE_MEMDB_MODE`
- `MEMTRACE_MEMDB_ENDPOINT`
- `MEMTRACE_SKIP_EMBED`
- `MEMTRACE_NO_REPLAY`

all keep precedence.

New debug escape hatch:

```bash
MEMTRACE_OWNER_ATTACH=0
```

Use this only when debugging the owner layer. It forces legacy direct embedded open behavior.

## Faster startup and background phase 2

`memtrace start` is now organized around structural readiness:

1. Open the structural store.
2. Bind UI/API.
3. Report ready.
4. Continue embedding/replay/indexing in the background unless explicitly configured otherwise.

Optional foreground mode:

```bash
MEMTRACE_START_PHASE2=foreground
```

Embedding failures should not make the structural graph unusable. Semantic search can be marked unavailable while graph/search remain usable.

## MemDB boot/replay work

The MemDB vendor submodule now includes a local commit for deeper boot/replay work:

```text
d2de6ab fix(real_engine): bound boot replay and persist graph indexes
```

This work covers:

- bounded recovery/replay paths;
- graph/index persistence hardening;
- count and property index recovery;
- edge adjacency persistence;
- RID/UUID index recovery;
- WAL reader/recovery fixes;
- protection against large stores spending startup time rebuilding state that should be recoverable.

The intended user result is simple: a large `.memdb` should become structurally usable quickly, similar to what users expect from normal databases. Semantic/vector attach still needs guardrails around dimension mismatch and HNSW attach stalls, but startup should not block the entire product on embedding or replay.

## UI and workspace behavior

The UI now fits the workspace-owner model:

- a workspace can contain one repo or multiple repos;
- `memtrace index .` in a repo remains valid;
- workspace-level indexing can collect sibling repos into one parent workspace store;
- `memtrace start` should show existing indexed repos from the resolved `.memdb`;
- indexing work can appear progressively rather than blocking UI bind.

Known product follow-up:

- relation rendering needs a UI pass so users can clearly see dependency edges and not only isolated node clouds;
- multi-repo startup needs clearer progress reporting per repo;
- graph state should be easier to inspect from the UI when phase 2 is still running.

## Compatibility and breaking changes

No intentional breaking changes.

Existing commands remain valid:

```bash
memtrace index .
memtrace start
memtrace mcp
memtrace stop
memtrace status
```

Existing repo-local `.memdb` directories continue to work.

Existing env overrides keep priority.

New behavior to know:

- duplicate starts for the same `.memdb` attach to the existing owner instead of opening another embedded MemDB;
- UI/API can become ready before embedding/replay is fully complete;
- semantic search can be disabled with a clear status if vector dimensions do not match the active provider;
- GitHub PR posting requires the GitHub App installation and server env vars.

## Validation performed

Local validation for this integration round:

- `cargo check -p memtrace-mcp --bin memtrace`
- `cargo build -p memtrace-mcp --bin memtrace`
- `memtrace code-review --help`
- `memtrace-ui` typecheck/build during GitHub App integration
- skill metadata tests
- installer skill transformer tests for Codex, Claude, and Cursor
- MemDB boot/recovery code committed in the vendor submodule

Before a public release, run the final gate from clean clones:

```bash
cargo build --release
cargo test --workspace
cd memtrace-ui && npm run typecheck && npm run build
node --test test/skill-metadata.test.js
node --test test/uninstall-legacy-cleanliness.test.js
cd installer && npm test -- --run tests/transformers/codex.skills.test.ts tests/transformers/claude.scope.test.ts tests/transformers/cursor.skills.test.ts
```

Before a public WithMartian submission, run the clean canonical benchmark command from a clean worktree and archive:

- Memtrace commit hash;
- MemDB submodule hash;
- benchmark repo commit hash;
- `.env` values that affect provider/model/graph mode;
- generated `benchmark_data.json`;
- raw candidate logs;
- scorer output.

## Deployment checklist

1. Push the MemDB submodule commit first.
2. Push Memtrace main with the updated submodule pointer.
3. Run the `0008_github_app_installations.sql` migration in production.
4. Ensure Vercel has the GitHub App env vars.
5. Redeploy `memtrace-ui`.
6. Install the GitHub App on a test repository.
7. Run:

```bash
memtrace code-review --pr https://github.com/OWNER/REPO/pull/123 --dry-run
memtrace code-review --pr https://github.com/OWNER/REPO/pull/123 --post
```

8. Confirm comments appear as Memtrace Code Reviewer.
9. Run one clean canonical WithMartian offline benchmark.
10. Prepare the public submission/PR with exact reproducibility details.

## Suggested public positioning

Memtrace is a local-first memory layer for codebases and coding agents. It keeps an indexed, embedded, temporal code graph fresh as users build, so agents can navigate, understand impact, detect regressions, improve quality, and review changes with real codebase context.

Code review is now one workflow powered by that memory layer. The user's code stays on their machine. The graph, embeddings, history, quality signals, and review analysis are local. The GitHub App exists to publish review comments and provide the public PR evidence required by review benchmarks and real-world workflows.

That is the right product shape for Memtrace:

- useful to real developers while they code, not only when a PR is opened;
- compatible with agent workflows;
- strong enough for benchmark evaluation;
- not dependent on uploading customer code into a SaaS scanner;
- extensible across languages because the bug classes are modeled as general review patterns.

## Known follow-ups

- Run a clean canonical 50/50 benchmark after the merge.
- Improve graph-result ranking so graph helps recall without hurting precision.
- Finish semantic evidence ablation to measure whether embeddings improve judge match quality.
- Add clearer UI display for relations/dependencies.
- Harden large-store vector attach and semantic cache startup further.
- Add product docs for GitHub App installation and `memtrace code-review`.
- Add a small public dogfood campaign with real PRs so WithMartian can see online Memtrace reviewer activity.
