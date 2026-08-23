# bottom (btm — system monitor)

**The binary is `btm`, not `bottom`.** A clean, keyboard-driven system monitor —
lighter than `btop`, with better graphs and a proper search syntax.

| Command | What it does |
|---|---|
| `btm` | start it |
| `btm -b` | basic mode — no graphs, minimal rows |
| `btm -g` | group processes by name |
| `btm -t` | process tree |
| `btm --rate 2s` | slower refresh (kinder over ssh) |
| `btm -C ~/.config/bottom/bottom.toml` | explicit config file |

Keys: `?` help, `/` search processes, `dd` kill, `Tab` group, `e` expand the
focused widget, `Ctrl+←/→` move between widgets, `q` quit.

The process search takes expressions: `btm` then `/`, and type e.g.
`cpu > 5 && name = node` or `mem > 500mb`.

`btop` is the prettier one; `glances` the most portable. This stack maps the
catalog id `bottom` to the binary `btm` (`ts_app_bin`).
