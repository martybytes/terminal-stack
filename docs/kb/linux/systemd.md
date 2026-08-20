# Linux — services & logs (systemd)

Runbook for the ssh-target servers this stack manages. `systemctl` drives
units, `journalctl` reads their logs. Control verbs need `sudo`; the read-only
ones don't.

## Services
| Command | What it does |
|---|---|
| `systemctl status svc` | running? PID, uptime, recent log lines |
| `sudo systemctl start\|stop\|restart svc` | service control |
| `sudo systemctl enable --now svc` | start now + at boot (`disable` undoes) |
| `systemctl is-active svc` / `is-enabled svc` | script-friendly yes/no |
| `systemctl --failed` | every unit currently in a failed state |
| `sudo systemctl daemon-reload` | after editing a unit file |
| `systemctl cat svc` | the unit file (+ drop-ins) actually in effect |
| `systemctl list-timers` | scheduled jobs — the cron replacement |
| `systemctl --user ...` | per-user units: same verbs, no sudo |

## Logs (journalctl)
| Command | What it does |
|---|---|
| `journalctl -u svc -f` | follow a service's logs live |
| `journalctl -u svc -n 100` | last 100 lines |
| `journalctl -u svc --since "1 hour ago"` | recent history (`--since today` works too) |
| `journalctl -b` | everything since this boot (`-b -1` = previous boot) |
| `journalctl -p err -b` | errors and worse since boot |
| `journalctl --disk-usage` | how much space the journal eats |

If `enable`/`start` complains the unit is masked: `sudo systemctl unmask svc`.
