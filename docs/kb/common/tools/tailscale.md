# Tailscale (find and reach private-network devices)

Tailscale gives each device a stable private IP and, with MagicDNS, a full DNS
name such as `origin.example.ts.net`. The `tail-*` helpers answer common identity
questions; the native commands remain useful on any machine.

## Everyday discovery

| Need | terminal-stack helper | Native command |
|---|---|---|
| This device's identity, IPs, and FQDN | `tail-self` | `tailscale status --json` |
| All devices, online first | `tail-hosts` | `tailscale status` |
| Only online devices | `tail-hosts --online` | `tailscale status --active` |
| This device's IPv4 | `tail-ip` | `tailscale ip -4` |
| Another device's IPv4 | `tail-ip origin` | `tailscale ip -4 origin` |
| This device's full DNS name | `tail-fqdn` | `tailscale status --json | jq -r '.Self.DNSName | rtrimstr(".")'` |
| Find by partial host, DNS name, or IP | `tail-find orig` | inspect `tailscale status` |

`tail-fqdn HOST` accepts a hostname, short MagicDNS name, full name, or
Tailscale IP. It refuses ambiguous matches. The final dot in raw `.DNSName`
values is normal DNS notation; the helpers remove it for command-line use.

```sh
# Local hostname, FQDN, and every Tailscale IP.
tailscale status --json | jq '{host:.Self.HostName, fqdn:.Self.DNSName, ips:.Self.TailscaleIPs}'

# Online peers: OS, hostname, FQDN, and IPv4.
tailscale status --json | jq -r '
  .Peer[] | select(.Online) |
  [.OS, .HostName, (.DNSName|rtrimstr(".")),
   ([.TailscaleIPs[] | select(test("^[0-9]+\\."))][0])] | @tsv'
```

## Connectivity and diagnosis

| Command | What it answers |
|---|---|
| `tail-status` / `tailscale status` | Which devices exist and are active? |
| `tail-ping HOST` / `tailscale ping HOST` | Can Tailscale reach it, and does the path become direct instead of DERP-relayed? |
| `tail-netcheck` / `tailscale netcheck` | Does this network permit UDP, IPv4/IPv6, and efficient NAT traversal? |
| `tail-nc HOST PORT` / `tailscale nc HOST PORT` | Open a raw stdin/stdout connection. This is not a quick port probe and can wait for input. |
| `tail-ssh HOST` / `tailscale ssh HOST` | Open Tailscale SSH when policy and the destination permit it. |
| `tailscale whois 100.x.y.z` | Which machine and user own an IP? |

The first Tailscale ping may use DERP while a direct path is negotiated. If it
works but ordinary traffic does not, inspect the destination OS firewall and
the tailnet access policy.

## Connection and service commands

| Command | Purpose / caution |
|---|---|
| `tailscale up` | Connect and authenticate if needed. |
| `tailscale down` | Disconnect without expiring this device's login. |
| `tailscale get` / `tailscale set FLAG` | Read or change individual preferences. |
| `tailscale exit-node list` | List available exit nodes. |
| `tailscale set --exit-node=HOST` | Use an exit node; pass an empty value to stop. |
| `tailscale serve --help` | Publish a local service only inside the tailnet. |
| `tailscale funnel --help` | Publish through the public internet—more exposed than Serve. |
| `tailscale file cp FILE HOST:` | Send a file with Taildrop. |
| `tailscale file get DIR` | Receive waiting Taildrop files. |
| `tailscale update` | Update interactively; `--yes` suppresses confirmation. |

Use `tailscale set` for individual changes. Before using `up` with flags, read
the displayed command carefully because some versions require the complete
intended preference set.

Official references: [CLI](https://tailscale.com/kb/1080/cli),
[MagicDNS](https://tailscale.com/kb/1081/magicdns),
[exit nodes](https://tailscale.com/kb/1103/exit-nodes),
[Serve](https://tailscale.com/kb/1242/tailscale-serve), and
[Funnel](https://tailscale.com/kb/1223/funnel).
