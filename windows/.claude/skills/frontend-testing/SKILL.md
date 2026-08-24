---
name: frontend-testing
description: Verify or debug web interfaces and frontend changes with Playwright CLI, Playwright MCP, or an existing repo-local Playwright Test suite. Use for browser interaction checks, visual evidence, console or network diagnosis, and end-to-end regression work.
---

# Frontend testing

Choose the smallest browser workflow that provides credible evidence.

## Choose the interface

- Prefer `playwright-cli` for ordinary agent-driven navigation, interaction, screenshots, traces, and exploratory checks. Read its installed skill or `playwright-cli --help` when command details are needed.
- Use the configured `playwright` MCP tools when persistent page context or richer accessibility-tree inspection materially helps.
- Treat a repo-local Playwright Test suite as the source of truth for repeatable regression coverage. Use the repository's pinned version and existing configuration.
- Do not build or run an upstream Playwright source checkout as the agent runtime.

## Sessions and state

- Keep sessions isolated by default. When concurrent agents could share a workspace, choose a unique CLI session name such as `<agent>-<repo>-<task>` and close it after the check.
- Use a test account or the repository's ignored storage-state file for authenticated flows. Do not attach to a personal signed-in browser, create a persistent profile, or expose credentials unless the user explicitly requests that workflow.
- Start the application using its documented command and derive the target URL from repository configuration or runtime output instead of guessing.

## Produce evidence

- Verify the requested user-visible behavior and inspect relevant console errors and failed network requests.
- Record the exercised URL or flow, assertions, failures, and useful artifact paths in the result.
- Interactive browser evidence does not replace durable tests. Run existing end-to-end tests after relevant changes; add or edit committed tests only when the task authorizes implementation or test changes.
- Keep transient Playwright artifacts outside the application worktree unless the user asks for a deliverable there. With `playwright-cli`, omit `--filename` for a transient capture or pass an absolute artifact path; an explicit relative filename resolves against the current working directory.
