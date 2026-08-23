# gping (ping with a graph)

`ping` that draws latency over time, and can graph several hosts on one chart —
which is how you tell "my wifi is bad" from "that host is bad".

| Command | What it does |
|---|---|
| `gping example.com` | graph one host |
| `gping 1.1.1.1 8.8.8.8 example.com` | several at once, one line each |
| `gping -n 0.2 host` | 200 ms interval |
| `gping -b 60 host` | buffer 60 s of history on screen |
| `gping -4` / `-6` | force IPv4 / IPv6 |
| `gping -s` | simple graphics for terminals with poor glyph support |
| `gping --cmd "curl -s example.com"` | graph any command's execution time instead |

Keys: `q`/`Ctrl+C` quit.

Comparing your gateway against a public resolver in one command is the fastest
local-vs-upstream triage: `gping "$(ip route | awk '/default/{print $3; exit}')" 1.1.1.1`.
