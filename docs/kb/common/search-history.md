# Search & history

| Key / Command | What it does |
|---|---|
| `Ctrl+R` | fuzzy-search shell history — fzf in zsh; PSReadLine reverse search in pwsh |
| `Ctrl+T` | fzf: fuzzy-find a file, insert its path on the command line (zsh) |
| `Alt+C` | fzf: fuzzy-find a directory and cd into it (zsh) |
| `Esc` `Esc` | prepend `sudo` to the current/previous command (zsh sudo plugin) |
| `hgrep <pattern>` | grep the full command history — both shells |
| `history` | zsh: last 200 commands of **this** shell |
| `history all` | zsh: import other shells' lines, then list everything |
| `rg pattern` | ripgrep — recursive grep, fast, skips .git/node_modules |
| `rg -i` / `rg -l` / `rg -n` | case-insensitive / files-with-matches / line numbers |
| `curl -s … \| jq .` | pretty-print / query JSON |

## History, the stack way

zsh keeps 100k lines and appends **per shell** (`INC_APPEND_HISTORY`): a command
typed in another pane isn't visible here until imported. `history all` and `hgrep`
both run the import (`fc -RI`) first, so they always search everything. Two safety
valves: lines that look like secrets (`sk-…` keys, `Bearer` tokens,
`--token`/`--api-key` flags, `*_KEY=`/`*_SECRET=`/`*_PASSWORD=`/`*_TOKEN=`
assignments) are **discarded from history entirely**, and a leading space keeps any
command out (`HIST_IGNORE_SPACE`).

`hgrep` is case-insensitive in zsh; the pwsh version greps PSReadLine's saved
history file (`(Get-PSReadLineOption).HistorySavePath`), which is shared across
sessions already.

To search the docs themselves: `doc -g <pattern>`, or `doc cmd` to find a command
and drop it on your prompt.
