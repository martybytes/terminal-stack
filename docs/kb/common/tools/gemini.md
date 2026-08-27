# gemini (Google Gemini CLI)

Google's coding agent in the terminal.

## How this stack wires it

- **Installed from npm** (`@google/gemini-cli`), as part of the `ai` group in the
  install questionnaire. Pre-ticked but still asked.
- **Needs Node 20+.** If the runtime is too old the installer says so and points
  at `fnm` rather than failing — pick `fnm` from the `runtimes` group and it
  installs the current LTS for you.
- **No brew fallback, deliberately.** Homebrew's `gemini-cli` formula is
  deprecated upstream and scheduled for removal on 2026-12-18, so installing
  from it would hand you a dead end. npm is the supported path.
- Because it is a global npm package it lives under whatever Node fnm has active,
  and fnm's PATH entry is per-shell — which is why `tstack update`'s "not installed"
  check loads fnm's environment before probing.

| Command | What it does |
|---|---|
| `gemini` | interactive session in the current directory |
| `gemini -p "summarise this repo"` | one-shot prompt |
| `gemini --version` | installed version |
| `npm install -g @google/gemini-cli` | upgrade (or re-run `tstack config apps gemini`) |
| `npm ls -g --depth 0` | what else is installed globally under this Node |

Authenticates against a Google account on first run; an API key from AI Studio
works for headless use.

See also `doc claude-code`, `doc codex`, `doc grok`, `doc node-python`.
