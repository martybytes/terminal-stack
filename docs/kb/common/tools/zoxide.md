# zoxide (smarter cd)

Learns every directory you cd into; jump back by substring. A **recommended**
catalog app, initialized in both shells — `eval "$(zoxide init zsh)"` in
`~/.zshrc`, `zoxide init powershell` in `$PROFILE`. Since the `ws*` jump
functions (`ws`, `wsj`, `ws37`, …) are plain cd's under the hood, every landing
they make becomes a `z` target too. (oh-my-zsh's `z` plugin is deliberately not
loaded — zoxide provides `z`/`zi` in its place.)

## Daily commands
| Command | What |
|---|---|
| `z foo` | cd to the best match for "foo" |
| `z foo bar` | match on multiple keywords |
| `zi` | interactive picker (fzf) among matches |
| `z -` | back to the previous dir |
| `zoxide query foo` | show where `z foo` would go |
| `zoxide query -l` | list the database (ranked) |
| `zoxide add <path>` | seed a directory by hand |
| `zoxide remove <path>` | drop a dead entry |

## Windows extra

`$PROFILE` defines `zoxide-prune`: it walks `zoxide query -l` and removes every
entry whose path no longer exists. Run it after moving repos around —
`wso migrate` / `wso archive` leave stale paths in the database.
