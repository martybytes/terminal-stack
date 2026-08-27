# btop (resource monitor)

A full-screen monitor for CPU, memory, disks, network and processes, with mouse
support and a process tree. The nicest of the `top` family to look at.

| Command | What it does |
|---|---|
| `btop` | start it |
| `btop --preset 1` | start on a saved layout preset (0-9) |
| `btop --utf-force` | force UTF-8 when the locale is misdetected |
| `btop --low-color` | 16-colour mode for a dumb terminal |
| `btop --tty_on` | TTY-friendly rendering over a serial console |

Keys: `Esc`/`m` menu, `1`-`4` toggle the CPU/memory/network/process boxes,
`f` filter processes, `t` tree view, `+`/`-` expand-collapse, `k` kill the
selected process, `q` quit. Settings live in `~/.config/btop/btop.conf` and the
menu writes them for you.

**On Windows the command is `btop4win`, not `btop`.** winget's
`aristocratos.btop4win` is a separate port with its own executable name; there is
no `btop.exe`. `tstack update` probed for `btop` and so offered to install it on
every run even though it was already there.

`bottom` (`btm`) is the leaner alternative; `glances` adds a web UI and remote
mode; `nvtop` covers GPUs.
