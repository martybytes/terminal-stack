# ripgrep (rg)

Fast recursive grep — respects `.gitignore`, skips binaries. A **recommended**
catalog app (`tstack config apps`; winget id `BurntSushi.ripgrep.MSVC`).

## In this stack

`doc -g <pattern>` greps every kb topic with rg when it's installed
(`--line-number --heading --color=always`) and pages long results through
`less -RF`; without rg it degrades to plain `grep -rn` (zsh) or `Select-String`
(pwsh).

## Daily commands
| Command | What |
|---|---|
| `rg pattern` | recursive search from cwd |
| `rg -i pattern` | case-insensitive (`-S` = smart case) |
| `rg -w pattern` | whole word |
| `rg -l pattern` | files with matches only |
| `rg -c pattern` | match count per file |
| `rg -C 3 pattern` | 3 lines of context (`-A`/`-B` for after/before) |
| `rg -t py pattern` | only python files (`rg --type-list` for the names) |
| `rg -g '*.md' pattern` | glob filter (`-g '!vendor/**'` to exclude) |
| `rg --hidden --no-ignore pattern` | include hidden + ignored files |
| `rg -U 'foo\n.*bar'` | multiline — pattern may span lines |
| `rg 'foo' -r 'bar'` | preview a replacement (stdout only — rg never edits) |
| `rg -o 'pat'` | print only the matched text |
| `rg --files \| rg name` | fuzzy over filenames |
