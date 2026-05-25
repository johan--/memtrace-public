# Memtrace Code Reviewer

Memtrace can review GitHub pull requests using the same local code graph your
agents use while coding. It can run from the CLI or through an agent skill.
Either way, analysis happens on your machine.

![Animated Memtrace code review flow](code-reviewer-flow.svg)

## The Short Version

1. Make sure the repository is indexed locally.
2. Make a feature branch and open a GitHub pull request.
3. Run `memtrace code-review --post --watch` on the PR.
4. Keep a local Memtrace owner running for watched commands: `memtrace start`,
   a headless daemon, or an active `memtrace mcp` session.
5. Reply on GitHub with `@memtrace ...` commands when you want a rerun,
   explanation, ignore, local fix, or merge attempt.

```bash
# If this repo is not indexed yet:
memtrace index .

git checkout -b feat/my-change
# make your change
git add .
git commit -m "Add my change"
git push -u origin feat/my-change

gh pr create --fill

memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --watch \
  --repo-root "$PWD"
```

## What Runs Where

Memtrace has four moving parts in the review flow:

| Part | Where it runs | What it does |
|---|---|---|
| Review engine | Your machine | Reads the PR diff, local checkout, AST rules, YAML rules, and indexed graph. |
| GitHub App | GitHub + Memtrace auth service | Lets Memtrace post review comments and read PR replies. |
| Watch loop | Your machine | Picks up `@memtrace` commands and executes them locally. |
| Optional fix agent | Your machine | Applies `@memtrace fix this` in an isolated worktree when configured. |

The hosted service does not run fixes and does not need your local repo path.
It only helps route GitHub App auth and, where available, relay relevant
`@memtrace` PR comments to your local Memtrace process.

## Before Reviewing a PR

This guide assumes Memtrace is already installed. If you are setting up a new
machine, use [`getting-started.md`](getting-started.md) first.

For code review, the important checks are repository-specific:

- The local checkout points at the same repository as the PR.
- The PR branch or PR head is checked out locally.
- The repository has been indexed by Memtrace.
- The Memtrace GitHub App is installed on that GitHub repository.
- Use `--post --watch` when you want `@memtrace` PR comments to work.
- Keep one local Memtrace owner running while you expect commands to
  execute: `memtrace start`, the headless daemon service, or an active
  `memtrace mcp` process.

Useful checks:

```bash
memtrace status
memtrace code-review --help
memtrace pr status
```

## Review a PR from the CLI

Use preview mode first when you want to see what Memtrace would post:

```bash
memtrace code-review --pr https://github.com/OWNER/REPO/pull/123
```

Post review comments:

```bash
memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --repo-root "$PWD"
```

Post and keep watching the PR for commands:

```bash
memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --watch \
  --repo-root "$PWD" \
  --repo-id Memtrace
```

Use `--repo-id` when your indexed repository id is not the folder name. Use
`--graph-mode off` only when you intentionally want AST/rule-only review.

## Review a PR from an Agent

After installing Memtrace skills, ask your agent in normal language. The
`memtrace-code-review` skill tells the agent to use the Memtrace PR review
tool instead of manually reading diffs.

Good prompts:

```text
Create a feature branch for the timeline border fix, commit it, push a PR,
then run Memtrace code review and post the review comments.
```

```text
Review this PR with Memtrace and post findings:
https://github.com/OWNER/REPO/pull/123
```

```text
Use Memtrace to review the current PR, watch it, and tell me what to reply
with if I want a fix.
```

Agent support has two layers:

| Capability | Claude Code | Codex | Cursor | Windsurf | VS Code/Copilot |
|---|---:|---:|---:|---:|---:|
| Memtrace skills + MCP | yes | yes | yes | yes | yes |
| Review, rerun, explain, ignore | yes | yes | yes | yes | yes |
| Automatic `fix this` | yes | yes | yes, when Cursor Agent is logged in | not yet | not yet |

The reviewer itself is editor-independent. Automatic local fixes need a
headless agent runner.

## GitHub Commands

When a PR is watched, comment on the PR or reply to a Memtrace inline review
comment.

| Command | Use it when | Notes |
|---|---|---|
| `@memtrace review` | You want a fresh review. | Same as rerun. |
| `@memtrace rerun` | New commits landed or you changed ignore state. | Posts a new review if findings remain. |
| `@memtrace explain` | You want a short explanation of a finding. | Best as a reply to a Memtrace inline comment. |
| `@memtrace ignore` | The finding is not useful for this PR. | Best as a reply to a Memtrace inline comment. Future reviews suppress that finding. |
| `@memtrace fix this` | You want a local agent to fix one finding. | Requires `MEMTRACE_PR_AGENT_COMMAND`. Same-repo PR branches only in the first version. |
| `@memtrace merge` | You want Memtrace to ask GitHub to merge the PR. | GitHub still enforces branch protection, checks, and app permissions. |

Memtrace reacts with eyes when a command is picked up. It removes that
acknowledgement when the command completes, then reacts with `+1` on success or
`confused` when it needs attention. It also posts a short reply on GitHub.

If a command does not run immediately, force a sync:

```bash
memtrace pr sync
memtrace pr status
```

## Enable `@memtrace fix this`

`fix this` is intentionally local. Memtrace creates an isolated worktree under
`~/.memtrace/pr-worktrees/`, sends JSON context to your configured agent, then
commits and pushes the result to the PR branch if files changed.

Memtrace only needs an executable command. The command receives JSON on stdin,
edits the isolated worktree, prints a short summary, and exits `0` on success.

The examples below use the helper adapter from a Memtrace source checkout. If
your installed package does not include that helper yet, point
`MEMTRACE_PR_AGENT_COMMAND` at your own wrapper with the same stdin contract.
Most users only need this section when they want `@memtrace fix this`.

Configure one provider before starting watch mode.

Codex:

```bash
export MEMTRACE_PR_AGENT_COMMAND="$PWD/scripts/pr-agents/memtrace-pr-agent codex"
```

Claude Code:

```bash
export MEMTRACE_PR_AGENT_COMMAND="$PWD/scripts/pr-agents/memtrace-pr-agent claude"
```

Cursor Agent:

```bash
cursor agent login
export MEMTRACE_PR_AGENT_COMMAND="$PWD/scripts/pr-agents/memtrace-pr-agent cursor"
```

Then run the watched review:

```bash
memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --watch \
  --repo-root "$PWD"
```

Windsurf and VS Code/Copilot can use Memtrace skills and MCP today. Automatic
`fix this` is not wired for them until there is a supported headless local agent
adapter.

Custom adapter contract:

```bash
export MEMTRACE_PR_AGENT_COMMAND="/path/to/your-agent-wrapper"
```

Your wrapper receives a JSON payload with the PR URL, worktree path, command,
triggering comment, target finding, and head SHA. Exit non-zero when no safe fix
can be made; Memtrace will reply on GitHub with the failure reason.

## Typical Feature Workflow

Use this when you want a clean branch, PR, and review cycle.

```bash
# 1. Start from current main
git checkout main
git pull --ff-only

# 2. Create a focused branch
git checkout -b feat/descriptive-name

# 3. Ask your agent to implement the change, or do it yourself
# Example prompt:
# "Use Memtrace first, implement the dashboard empty state, add focused tests."

# 4. Commit and push
git add .
git commit -m "Add dashboard empty state"
git push -u origin feat/descriptive-name

# 5. Open a PR
gh pr create --fill

# 6. Run Memtrace review
memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --watch \
  --repo-root "$PWD"

# 7. Use GitHub comments for follow-up
# @memtrace explain
# @memtrace fix this
# @memtrace rerun
```

## What Memtrace Looks For

The reviewer combines several local signals:

- AST review detectors for high-confidence bug patterns.
- YAML rule packs for language and framework issues.
- Cross-module graph checks when `--graph-mode strict` is enabled.
- Local repository context from the indexed Memtrace graph.

It is not a generic style bot. It tries to post fewer, higher-signal findings.

## Pitfalls and Limitations

Memtrace PR review is local-first. That is the point, but it also means GitHub
comments are not enough by themselves. A watched command succeeds only when the
local Memtrace instance that armed the watch still has the right repository
context.

### The local checkout must match the PR

Review runs against the PR diff from GitHub, but file contents come from your
local checkout. If your local `HEAD` is on `main`, on another feature branch, or
behind the PR head, Memtrace can warn that the local head differs from the PR
head and the review can miss context or produce stale results.

Before running review or relying on `@memtrace rerun`, make sure the local repo
is at the PR head:

```bash
git fetch origin pull/123/head:pr-123
git checkout pr-123

memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --watch \
  --repo-root "$PWD"
```

For same-repo branches, checking out the branch directly is fine:

```bash
git fetch origin
git checkout feature-branch
git pull --ff-only
```

### The repo must be indexed locally

Graph-backed review needs an indexed Memtrace repository. If you point Memtrace
at a random GitHub PR for a repo that is not indexed on your machine, it cannot
use local graph context for that project. AST and rule checks may still run, but
cross-module findings and graph-backed confidence will be missing or much
weaker.

Run this from the repository root before expecting graph review:

```bash
memtrace index .
memtrace status
```

Use the correct `--repo-id` when the indexed repo id is not the folder name:

```bash
memtrace code-review \
  --pr https://github.com/OWNER/REPO/pull/123 \
  --post \
  --watch \
  --repo-root "$PWD" \
  --repo-id MyIndexedRepo
```

This matters in monorepos. If only one package or service is indexed, Memtrace
only has graph context for that indexed scope.

### A PR must be watched before commands work

`@memtrace` comments are not a global GitHub command surface. Memtrace only
reacts to PRs that were armed with `--post --watch` from a local install:

```bash
memtrace code-review --pr https://github.com/OWNER/REPO/pull/123 --post --watch
```

The local machine that armed the watch is the machine that executes the command.
If that machine is offline, logged out, or missing the saved watch state,
GitHub comments will not immediately run. The hosted relay can queue command
metadata for a short time, and GitHub polling remains a fallback, but local
execution still requires a running local Memtrace owner or a manual sync:

```bash
memtrace pr status
memtrace pr sync
```

Old comments from before the watch was created are ignored. Commands are also
deduped, so editing or re-syncing an already-processed command should not rerun
it.

### Some commands need an inline Memtrace finding

Top-level PR comments work for broad commands:

```text
@memtrace review
@memtrace rerun
```

Finding-specific commands need to be replies to a Memtrace inline review
comment so Memtrace can bind the command to a hidden finding marker:

```text
@memtrace explain
@memtrace ignore
@memtrace fix this
```

If you write `@memtrace fix this` as a general PR comment, Memtrace may see the
command but it does not know which finding to fix.

### GitHub permissions still apply

Memtrace checks the command author's GitHub permission before executing.

| Command type | Who can run it |
|---|---|
| `review`, `rerun`, `explain` | PR author or repository collaborator |
| `ignore`, `fix this`, `merge` | Users with `write`, `maintain`, or `admin` permission |

`@memtrace merge` only asks GitHub to merge the PR. Branch protection, required
checks, review requirements, merge queues, and GitHub App permissions can still
reject it.

### `fix this` is intentionally limited

Automatic fixes need a configured local headless agent:

```bash
export MEMTRACE_PR_AGENT_COMMAND="/path/to/agent-wrapper"
```

In the current version, `fix this` works only for same-repo PR branches. Fork PR
pushes are not supported yet. The local repo must also be able to fetch the PR
head, create a worktree under `~/.memtrace/pr-worktrees/`, commit, and push back
to the PR branch.

Supported fix quality depends on the configured agent. Memtrace supplies the PR
URL, worktree path, triggering comment, target finding, and head SHA as JSON on
stdin, but the agent still has to be installed, authenticated, and capable of
running non-interactively.

### It is not a full human reviewer

Memtrace is designed to post fewer, higher-signal findings from deterministic
rules, AST checks, and graph context. It is not meant to comment on every style
preference, naming issue, product choice, or architectural concern. A clean
review means Memtrace did not find a high-confidence issue in the changed lines;
it does not prove the PR is correct.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `--post` cannot publish comments | Install the Memtrace GitHub App on the repository. |
| Commands do not run | Confirm the PR was started with `--post --watch`, keep local Memtrace running, and run `memtrace pr sync` once. |
| `fix this` says agent command is missing | Set `MEMTRACE_PR_AGENT_COMMAND` before running watch mode. |
| Cursor fix fails with auth | Run `cursor agent login` or set `CURSOR_API_KEY`. |
| Merge is rejected | Check GitHub App permissions, branch protection, and required checks. |
| Graph review says context is missing | Run `memtrace index .` from the repo root and rerun review. |
| Review looks stale | Check out the PR head locally, rerun `memtrace code-review`, then use `@memtrace rerun`. |
| `explain`, `ignore`, or `fix this` lacks context | Reply directly to the Memtrace inline review comment instead of posting a top-level PR comment. |

## Privacy

Review execution is local-first. Source analysis, graph traversal, and automatic
fixes run on your machine. GitHub receives normal PR review comments and command
replies because that is where the collaboration happens.

See [`privacy-and-telemetry.md`](privacy-and-telemetry.md) for the complete
privacy model.
