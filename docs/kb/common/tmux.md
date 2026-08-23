# tmux

The stack ships `~/.tmux.conf` (a chezmoi template) everywhere, but tmux earns its
keep on **remote servers** — locally, WezTerm panes cover the same ground.

## What the stack's config does

| Setting | Effect |
|---|---|
| prefix | configurable: `ts-config tmux <chord>`, default `C-b` — kept separate from the WezTerm leader so the two layers never collide |
| `mouse on` | click panes, drag borders, wheel-scroll |
| `base-index 1` / `pane-base-index 1` | windows and panes count from 1, matching the number row |
| `renumber-windows on` | closing window 2 of 4 leaves 1-3, not 1,3,4 |
| `escape-time 10` | near-instant `Esc` — vim/micro don't lag after Esc |
| `history-limit 50000` | scrollback lines per pane |
| `set-clipboard on` | OSC 52 — a copy made inside a **remote** tmux lands on your local clipboard (see `doc common/clipboard`) |
| truecolor | `tmux-256color` + RGB `terminal-features` for `xterm*`/`wezterm*`; without them the status colors quantize to 256 |
| `allow-passthrough on` + `extended-keys on` | modified keys and escape sequences reach the app — this is **why** `Shift+Enter` works in Claude Code inside tmux |

The status line's colors are **baked at apply time** from the saved theme.
`ts-config theme <dark|light|follow>` re-applies and re-bakes them; toggling the OS
appearance alone changes nothing until the next apply or `ts-update`.

## Sessions
| Command | What it does |
|---|---|
| `tmux new -A -s name` | attach if it exists, else create (best default) |
| `tmux ls` | list running sessions |
| `tmux attach -t name` / `tmux a -t name` | reattach |
| `tmux attach -d -t name` | reattach, kicking off any other client |
| `tmux kill-session -t name` | kill a named session |
| `tmux kill-server` | kill all sessions |

`ssht host [session]` does ssh + `tmux new -A` in one shot (zsh only) — see
`doc common/stack`.

## Keys (prefix = your chord, default `Ctrl+b`)
| Key | What it does |
|---|---|
| prefix `d` | detach (leaves session running) |
| prefix `s` | switch between sessions (picker) |
| prefix `%` | split side by side |
| prefix `"` | split top/bottom |
| prefix arrow | move between panes |
| prefix `x` | close current pane |
| prefix `z` | zoom current pane fullscreen (toggle) — great for logs |
| prefix `[` | scroll/copy mode (`q` to quit) |
| prefix `c` | new window |
| prefix `n` / prefix `p` | next / previous window |
| prefix `1-9` | jump to window by number |

## The terminal tab title

While a session is attached, **tmux owns the outer terminal's title**. It
intercepts the inner program's `OSC 2` completely — the inner title never
reaches the terminal — and substitutes `set-titles-string`, which this stack
sets to the session name with `ccs`'s `cc-` prefix stripped:

    set -g set-titles-string '#{s/^cc-//:session_name}'

So a `ccs` session in `~/src/terminal-stack` shows a tab reading
`terminal-stack`, and Claude Code's conversation slug never appears.

This is the **only** way to keep a project name in a Ghostty tab: Ghostty's
sticky tab title is reachable only from a keybind, with no CLI and no escape
sequence to trigger it. See `doc common/tools/ghostty`.

Note the variable is `session_name`, not `#S`. Inside `#{...}` tmux wants the
variable name, and `#{s/^cc-//:#S}` silently evaluates to an **empty string** —
a blank tab title, which is worse than a noisy one.
