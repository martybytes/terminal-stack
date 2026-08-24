# Node & Python runtimes

Two catalog groups, both asked about at install and re-askable with
`ts-config apps` / `ts-config wizard`.

## Node — managed by fnm

`fnm` rather than nvm: nvm costs 200-500ms on **every** shell start (it is a
large shell script), fnm about 10ms (a binary). It reads the same
`.nvmrc` / `.node-version` files, so per-project pins keep working.

Wired into both shells with `--use-on-cd`, so entering a directory with a pin
switches Node automatically.

| Command | What it does |
|---|---|
| `fnm list` | installed Node versions; `*` marks active and default |
| `fnm install --lts` / `fnm install 22` | add a version |
| `fnm use 22` / `fnm default 22` | switch now / set the default |
| `fnm env --use-on-cd` | the shell hook (already in your rc) |
| `node --version` / `npm --version` | what is active here |

**Global npm binaries live under the active Node**, and fnm's PATH entry is
created per shell. That is why `ts_apps_pending` calls `ts_load_node_env` before
probing — without it, `ts-update` would nag about `codex`/`gemini` forever even
with both installed.

Picking `fnm` at install also installs the current LTS: the manager alone gives
you no runtime. `node` is a separate catalog id for machines that want a single
brew/winget Node and no manager at all.

### `package.json` engines are deliberately ignored

The stack wires fnm with `--resolve-engines=false`, so only `.nvmrc` and
`.node-version` switch versions. Left on, fnm consults `engines.node` in
`package.json`, which means every `cd` into a JS repo runs fnm, and an `engines`
range that no fnm-installed version satisfies turns the `cd` into
`Do you want to install it? answer [y/N]:` -- even when the active `node` already
satisfies it, because fnm only counts versions it installed itself.

Want a repo to switch automatically? Give it a pin:

```sh
node -v > .node-version      # or: echo 24 > .node-version
fnm install                  # installs what the pin asks for
```

## Python

The interpreter comes from brew (`python@3.14`) / apt / winget. Everything else
is a CLI tool, and **`pip install` into the system Python is blocked** on modern
Homebrew and Debian (PEP 668) — use `uv tool install` or `pipx` for anything
global.

| Tool | What it is |
|---|---|
| `uv` | fast package/project manager; `uv tool install X` for global CLIs |
| `pipx` | the older, still-good way to install a Python CLI in its own env |
| `ruff` | linter + formatter in one fast binary — replaces flake8/isort/black |
| `ipython` | a far better REPL (`%timeit`, `%debug`, real completion) |
| `httpie` | `http GET example.com` — curl you can read |
| `poetry` | project/dependency manager with lockfiles |
| `pre-commit` | run hooks (ruff, formatters) before every commit |

| Command | What it does |
|---|---|
| `uv tool install <pkg>` / `uv tool list` | install/list a global Python CLI |
| `uv venv && source .venv/bin/activate` | a project venv, fast |
| `uv pip install -r requirements.txt` | pip-compatible, much faster |
| `pipx install <pkg>` / `pipx list` | the pipx equivalent |
| `ruff check .` / `ruff format .` | lint / format |
| `ipython` | the REPL |
| `http GET api.example.com/x` | HTTP request, pretty-printed |

### How they install on Windows

Only the compiled two come from winget — `python` (`Python.Python.3.13`) and
`ruff` (`astral-sh.ruff`), plus `uv` (`astral-sh.uv`). **The rest do not have a
winget package at all**, so `pipx`, `poetry`, `glances`, `ipython`, `httpie` and
`pre-commit` install through `Install-TsPyTool`: `uv tool install <name>` when uv
is present, falling back to `py -m pip install --user <name>`.

Three of them used to be listed as winget ids that do not exist — `pypa.pipx`,
`Python-Poetry.Poetry` and `nicolargo.glances`. `pipx` is in the recommended set,
so every Windows machine was offered it on every `ts-update`, accepted, and got
"No package found matching input criteria" back, forever. `ipython`, `httpie` and
`pre-commit` had no id and were skipped silently. Both halves are fixed; the
whole group installs on Windows now.

`uv tool` puts its shims in `%USERPROFILE%\.local\bin`, which uv's own installer
adds to PATH — but not to the PATH of a shell that was already open, which is why
the installer refreshes the process PATH before reporting what landed.

## The `agent` name

Both the grok and cursor-agent installers create a generic `agent` symlink in
`~/.local/bin`, so **whichever is installed last wins that name**. Both tools
always work under their own names (`grok`, `cursor-agent`) — prefer those, and
treat `agent` as ambiguous.
