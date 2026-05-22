---
name: memtrace-code-review
description: "Always use when the user asks to review a GitHub pull request, run Memtrace code review, post Memtrace review comments, create a PR with a review step, or publish local graph-backed review findings to GitHub. Prefer the review_github_pr MCP tool over manual diff inspection."
---

## Overview

Use Memtrace's local-first PR review workflow. The agent should call the `review_github_pr` MCP tool so review runs against the developer's local indexed graph, AST detectors, YAML rule pack, and review policy. GitHub is used for PR context and optional comment publication; source code analysis stays local.

## Default Flow

1. If the user gives a GitHub PR URL and asks to inspect or review it, call `review_github_pr` with `post: false`.
2. If the user explicitly asks to publish, post comments, or complete the PR review, call `review_github_pr` with `post: true`.
3. Use `graphMode: "strict"` by default. Use `graphMode: "off"` only when the user asks to benchmark non-graph behavior or the local graph is unavailable.
4. Default to `minSeverity: "high"` and `maxComments: 5` when posting. For previews, `maxComments: 10` is acceptable.
5. Pass `repoRoot` when the PR checkout is not the current working directory. Pass `repoId` when the indexed repository id is known.

## Feature Branch to Reviewed PR

When the user asks for a full PR workflow, do the work in this order:

1. Create a focused feature branch from the current base branch.
2. Make the requested code change using the normal Memtrace source-code skills first.
3. Run focused tests or checks that match the change.
4. Commit and push the branch.
5. Create the GitHub PR.
6. Run `review_github_pr` with `post: true`; use watch mode when the CLI path is available and the user wants PR comment commands.
7. Tell the user which `@memtrace` commands are available on the PR: `review`, `rerun`, `explain`, `ignore`, `fix this`, and `merge`.

## Example User Prompts

- "Review this PR with Memtrace: https://github.com/OWNER/REPO/pull/123"
- "Use Memtrace to review this pull request and post the findings: https://github.com/OWNER/REPO/pull/123"
- "Create the PR, then run Memtrace code review and publish the review comments."
- "Make this change on a branch, push a PR, run Memtrace review, and watch for follow-up commands."

## Guardrails

- Do not start with generic grep, rg, or manual diff review when `review_github_pr` is available.
- Do not post comments unless the user explicitly requested publication.
- Do not create benchmark-specific or PR-specific findings. The review must come from general Memtrace detectors, graph evidence, and policy ranking.
- Do not imply that `@memtrace` commands work on arbitrary GitHub PRs. Commands require a PR watch created by the user's local Memtrace install.
- Make sure the local checkout is the PR head, or warn that review uses local files and can be stale when `HEAD` differs from the PR head.
- Use the local indexed repo for graph review. If the repository is not indexed, or the wrong `repoId` is used, graph-backed findings can be missing.
- If the tool reports missing auth, tell the user to run `memtrace auth login`.
- If the tool reports missing GitHub App installation, tell the user to install Memtrace Code Reviewer on that repository.
- If the tool reports missing local graph context, tell the user to run `memtrace index .` at the workspace root.
- For `explain`, `ignore`, and `fix this`, tell the user to reply to the specific Memtrace inline review comment so the command has a finding target.
- If the user asks for `@memtrace fix this`, explain that automatic fixes need a configured local agent command. Codex and Claude Code are supported; Cursor requires Cursor Agent auth; Windsurf and VS Code/Copilot can use skills/MCP but do not yet have a supported headless fix adapter.

## Output

For previews, summarize:
- PR URL and repository
- Graph state
- Number of candidate comments
- File, line, severity, and message for each finding

For posted reviews, report the PR URL and number of comments posted.
