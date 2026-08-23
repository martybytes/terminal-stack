# bandwhich (bandwidth by process)

Answers the question the other monitors cannot: *which process* is using the
network right now, and to which remote host.

**It needs elevated rights** — it reads raw sockets. Run it with `sudo`, or grant
the capability once on Linux:

```sh
sudo setcap cap_net_raw,cap_net_admin=eip "$(command -v bandwhich)"
```

| Command | What it does |
|---|---|
| `sudo bandwhich` | live table: processes, connections, remote addresses |
| `sudo bandwhich -i en0` | watch one interface |
| `sudo bandwhich -n` | no reverse DNS — much faster, shows raw IPs |
| `sudo bandwhich -r` | raw output, for piping |
| `sudo bandwhich --total-utilization` | totals instead of per-connection rows |

Keys: `Tab` cycle the panes (processes / connections / remote addresses),
`space` pause, `q` quit.

`gping` for reachability and latency; this for volume.
