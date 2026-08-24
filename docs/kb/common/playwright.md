# playwright — the browser MCP server

An always-on browser your agents can drive, in a container. Long-form reference:
`services/stacks/playwright/README.md`.

## What it is

A Playwright MCP server on `127.0.0.1:8931`, pinned by digest, running
`--isolated` so each client gets a fresh browser context and nothing persists
between sessions. Output is capped and written inside the container.

```sh
ts-stack up playwright
ts-stack status
services/stacks/playwright/check-playwright.sh   # a real two-session probe
```

## Using it

Agents reach it as an MCP server at `http://127.0.0.1:8931/mcp`. There is also a
`playwright-cli` for driving a browser directly from a shell, which is the better
tool when you want to watch what happens rather than have an agent report it.

## Notes

- It reserves 2 GB of shared memory (`shm_size`), because a browser without it
  crashes in ways that look like your test being wrong. That is why this stack is
  offered but off by default.
- The image is pinned by **digest**, not just tag — the only one here that is.
- Nothing is persisted: no volume, no profile, no cookies. A session that needs
  state has to establish it.

See also: `doc services` · `doc frontend-testing`
