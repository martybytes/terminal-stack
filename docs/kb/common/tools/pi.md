# pi (Pi coding agent)

Earendil's self-extensible coding agent, in the `ai` group alongside `claude`,
`codex`, `cursor-agent`, `grok` and `gemini`.

## How this stack wires it

- **npm, like `codex` and `gemini`** — package `@earendil-works/pi-coding-agent`,
  binary `pi`. Installed by `ts_install_ai_cli` / `Install-TsAiCli`, never by
  brew/apt/winget, so a failing npm install cannot look like a package-manager
  failure.
- **Needs Node 22.19+** (its `engines` field), the highest floor of any tool
  here — `codex` wants 16, `gemini` 20. If Node is older the installer *says
  what to do* rather than failing:
  `ts-config apps fnm`, then `fnm install --lts`.
- **Pre-ticked but still asked**, like every agent CLI. Untick it and nothing
  happens.

| Command | What it does |
|---|---|
| `pi` | interactive agent in the current directory |
| `pi -p "explain this repo"` | one-shot prompt |
| `pi --version` | version |

Config lives in `~/.pi`. Pi has **no built-in permission system** — it runs with
the permissions of whoever launched it. Upstream documents containerization
(Docker, or a micro-VM) if you want a boundary; nothing here sandboxes it.

See also `doc common/tools/grok`, `doc common/tools/gemini`, `doc claude-code`.
