"""`tstack ssh` - reach this PC over SSH: PowerShell on one port, Ubuntu on another.

A thin entry point over `tstack/ssh.py`, the split `tstack herdr` has over
`tstack/herdr.py`. The wizard asks the same questions (`ssh_questions`) and the
Windows installer runs `tstack ssh setup --from-wizard` after saving them.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .. import platform as plat
from .. import ssh

if TYPE_CHECKING:
    from ..wizard.flow import Asker

HELP = """tstack ssh - reach this PC over SSH.

Usage:
  tstack ssh [status]          what is set up, on each side, against what is saved
  tstack ssh setup             ask the SSH questions, pick the keys, and apply
  tstack ssh setup --dry-run   show the plan; change nothing
  tstack ssh setup --yes       take the saved answers and defaults, ask nothing
  tstack ssh keys              list the keys that may log in

Defaults: `ssh -p 22 you@this-pc` opens PowerShell, `ssh -p 2222 you@this-pc`
opens Ubuntu (WSL). Both ports are yours to change. Applying needs admin for
the Windows half: one UAC prompt, and declining it prints the exact command.
Passwords are switched off only after a key login has been proven to work.
docs: doc windows/ssh-server
"""

MARK = {"ok": "ok  ", "warn": "warn", "no": "no  ", "info": "    "}


def say(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def status() -> int:
    s = ssh.settings()
    say(f"==> SSH server: {s['sshServer']}  (targets {s['sshTargets']}, scope {s['sshScope']}, "
        f"passwords {s['sshPasswordAuth']})")  # fmt: skip
    if plat.kind() != plat.WINDOWS:
        say("    Set up from Windows: `tstack ssh setup` in PowerShell.")
        return 0
    for state, what, detail in ssh.windows_status(s).lines:
        say(f"    {MARK.get(state, '    ')}  {what:<18} {detail}")
    return 0


def keys() -> int:
    path = ssh.authorized_keys_path()
    found = (
        ssh.parse_keys(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else []
    )
    say(f"==> {path}: {len(found)} key(s)")
    for k in found:
        say(f"    {k.short}")
    return 0


# ------------------------------------------------------------------ setup


def _pick_keys(ask: Asker) -> list[ssh.Key]:
    """The four sources, any combination, each walked through in turn."""
    console = ask.console
    sources = ask.tick(
        "Which keys may log in? (tick any)",
        [
            ("local", "this PC's keys", "the .pub files in ~/.ssh"),
            ("github", "GitHub", "the keys published at github.com/<you>.keys"),
            ("paste", "paste a key", "from the computer you will connect from"),
            ("generate", "make a new pair", "for a computer that has no key yet"),
        ],
        ["local"],
        "  A key here can log in to the sides you enabled. Nothing is removed:\n"
        "  keys already authorized stay authorized. `tstack ssh keys` lists them.",
    )
    chosen: list[ssh.Key] = []

    def add(k: ssh.Key) -> None:
        if all(k.blob != o.blob for o in chosen):
            chosen.append(k)

    if "local" in sources:
        local = ssh.local_keys()
        if not local:
            console.say("  No .pub files in ~/.ssh.")
        else:
            options = []
            for k in local:
                note = k.source
                private = ssh.ssh_dir() / k.source.removesuffix(".pub")
                if ssh.has_passphrase(private) is False:
                    note += "  (no passphrase!)"
                options.append((k.blob, k.short, note))
            picked = ask.tick("This PC's keys to authorize:", options, [])
            for k in local:
                if k.blob in picked:
                    add(k)
    if "github" in sources:
        while True:
            user = ask.text("  GitHub username (blank to skip): ").strip()
            if not user:
                break
            try:
                gh = ssh.github_keys(user)
            except OSError as exc:
                console.say(f"  {exc}")
                if not console.interactive:
                    break
                continue
            if not gh:
                console.say(f"  {user} has no public keys on GitHub.")
                break
            picked = ask.tick(
                f"Keys published by {user}:",
                [(k.blob, k.short, "") for k in gh],
                [k.blob for k in gh],
            )
            for k in gh:
                if k.blob in picked:
                    add(k)
            break
    if "paste" in sources:
        while True:
            line = ask.text("  Paste one public key line (blank when done): ").strip()
            if not line:
                break
            pasted = ssh.parse_key(line, source="pasted")
            if pasted is None:
                console.say("  That is not a public key line (ssh-ed25519 AAAA... comment).")
                if not console.interactive:
                    break
                continue
            add(pasted)
            console.say(f"  added {pasted.short}")
    if "generate" in sources:
        name = ask.text("  Name for the new key (e.g. laptop): ").strip() or "remote"
        comment = f"{name}@terminal-stack"
        console.say("  ssh-keygen asks for a passphrase next. Use one: the key is a login.")
        made = ssh.generate_key(name, comment)
        if made is None:
            console.say("  Could not create it (ssh-keygen missing, or that name already exists).")
        else:
            path, k = made
            add(k)
            console.say(f"  created {path} and {path}.pub")
            console.say("  Copy the PRIVATE file to the other computer's ~/.ssh/, then delete it")
            console.say("  here if this PC should not keep it. Its .pub is authorized.")
    return chosen


def setup(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    from_wizard = "--from-wizard" in argv
    if plat.kind() != plat.WINDOWS:
        say("tstack ssh setup runs on Windows (it configures both the Windows and the WSL side).")
        return 2
    import os

    from ..wizard import flow
    from ..wizard.console import Console

    # --yes / TS_ASSUME_YES: take every default, ask nothing. stdin is no guide on
    # Windows: NUL reports itself as a terminal, so isatty() cannot tell.
    quiet = "--yes" in argv or bool(os.environ.get("TS_ASSUME_YES"))
    console = Console() if quiet else Console.open()
    ask = flow.Asker(console, banner="SSH server setup")
    try:
        values = ssh.settings() if from_wizard else flow.ssh_questions(ask, [], bare=False)
        if values.get("sshServer") != "on":
            if not from_wizard and not dry:
                ssh.save(values)
            say("==> SSH server off: nothing to apply.")
            return 0
        problem = ssh.port_problem(values)
        if problem:
            say(f"==> {problem}")
            return 2
        chosen = _pick_keys(ask)
    except (flow.GoBack, flow.QuitWizard):
        say("==> quit - nothing was changed.")
        return 3
    if not dry and not from_wizard:
        ssh.save(values)
    return apply(values, chosen, ask, dry=dry)


def apply(values: dict[str, str], chosen: list[ssh.Key], ask: Asker, *, dry: bool) -> int:
    """Both halves, in an order that cannot strand you:

    1. ~/.ssh/authorized_keys on Windows, and the WSL sshd + its keys, passwords
       still on where they are to go off (no admin needed for either)
    2. .wslconfig -> mirrored (the user's file; every other line kept)
    3. ONE elevated run: Windows sshd, firewall, Hyper-V rule, keep-alive task;
       it proves a Windows key login before switching Windows passwords off
    4. `wsl --shutdown` (with consent: it closes WSL shells), then the keep-alive
    5. prove a WSL key login, then switch WSL passwords off
    """
    import os

    if os.environ.get("SSH_CONNECTION") and not dry:
        say("==> WARNING: this session is itself over SSH. A mistake can drop it, and the")
        say("    port may move. Run this from the PC's own console the first time.")
        if ask.choose("Continue anyway?", [("no", "no", ""), ("yes", "yes", "")], "no") != "yes":
            return 3
    force_off = False
    local_blobs = {k.blob for k in ssh.local_keys()}
    if (
        values.get("sshPasswordAuth") == "off"
        and chosen
        and not any(k.blob in local_blobs for k in chosen)
    ):
        force_off = (
            ask.choose(
                "None of the chosen keys is on this PC, so a key login cannot be tested here.",
                [
                    (
                        "keep",
                        "leave passwords on",
                        "test from the other computer, then re-run setup",
                    ),
                    ("off", "switch passwords off anyway", "only if you are sure the key works"),
                ],
                "keep",
            )
            == "off"
        )
    distro = ssh.wsl_default_distro() if ssh.wants_wsl(values) else ""
    if ssh.wants_wsl(values) and not distro:
        say("==> WSL side requested, but no WSL distro was found. Install Ubuntu, then re-run.")
        return 1
    plan = ssh.plan_windows(values, chosen, force_password_off=force_off, distro=distro)
    wsl_first_pw = (
        "on"
        if values.get("sshPasswordAuth") == "off" and not force_off
        else values["sshPasswordAuth"]
    )

    say("")
    say("==> Plan")
    if ssh.wants_windows(values):
        say(f"    Windows: sshd on port {values['sshWindowsPort']}, login shell "
            f"{plan.default_shell or 'unchanged'}")  # fmt: skip
        say(
            "    Windows keys file sshd reads for you: "
            + (
                "administrators_authorized_keys"
                if plan.admin_keys_active
                else "~/.ssh/authorized_keys"
            )
        )
    if ssh.wants_wsl(values):
        say(f"    WSL ({distro}): openssh-server on port {values['sshWslPort']}, mirrored networking, "
            "a logon task that keeps WSL up")  # fmt: skip
    for r in plan.firewall:
        say(f"    firewall: {r['Name']}  port {r['Port']}  {r['Profile']}  from {r['Remote']}")
    say(f"    keys to authorize: {len(chosen)}")
    for k in chosen:
        say(f"      {k.short}")
    if values.get("sshPasswordAuth") == "off":
        say(
            "    passwords: off "
            + ("now" if force_off else "once a key login is verified on each side")
        )
    if dry:
        say("==> dry run: nothing changed.")
        return 0

    failed = False
    # 1 ------------------------------------------------------------------
    if ssh.wants_windows(values):
        added = ssh.write_user_authorized(chosen)
        say(f"==> Windows ~/.ssh/authorized_keys: {len(added)} added")
    if ssh.wants_wsl(values):
        say(f"==> WSL: installing / configuring openssh-server in {distro} ...")
        ok, why = ssh.wsl_apply_server(distro, values, wsl_first_pw)
        if not ok:
            say(f"    failed: {why}")
            failed = True
        added_wsl, why = ssh.wsl_authorize(distro, chosen)
        say(
            f"    WSL ~/.ssh/authorized_keys: {len(added_wsl)} added" + (f" ({why})" if why else "")
        )
        # 2 --------------------------------------------------------------
        changed = ssh.set_mirrored()
        say(
            "==> .wslconfig: networkingMode=mirrored "
            + ("set (backup taken)" if changed else "already set")
        )
    else:
        changed = False

    # 3 ------------------------------------------------------------------
    say("==> Applying the admin part (one UAC prompt) ...")
    result, plan_file = ssh.run_elevated(plan)
    if result is None:
        say("==> Not applied: the UAC prompt was declined, or pwsh is missing.")
        say("    From an ELEVATED PowerShell:")
        say(f"    {ssh.manual_command(plan_file)}")
        return 1
    if not result.get("ok"):
        failed = True
        say("==> The admin part failed:")
        for step in result.get("steps", []):
            if not step.get("ok"):
                say(f"    {step.get('name')}: {step.get('detail')}")

    # 4 ------------------------------------------------------------------
    if ssh.wants_wsl(values):
        if changed:
            restart = ask.choose(
                "Mirrored networking takes effect after `wsl --shutdown`, which closes every WSL shell.",
                [
                    ("now", "shut WSL down now", ""),
                    ("later", "later", "port 2222 works locally until then"),
                ],
                "now",
            )
            if restart == "now":
                ssh.wsl_shutdown()
                say("==> WSL restarted with mirrored networking.")
        ssh.start_keepalive()
        # 5 --------------------------------------------------------------
        if values.get("sshPasswordAuth") == "off" and not force_off:
            if ssh.verify_login(values["sshWslPort"], ssh.wsl_user(distro)):
                ok, why = ssh.wsl_apply_server(distro, values, "off")
                say("==> WSL passwords off (a key login was verified)" if ok else f"==> WSL: {why}")
            else:
                say("==> WSL passwords left ON: no key login could be verified from this PC.")
                say("    Test from the other computer, then re-run `tstack ssh setup`.")
        elif force_off:
            ssh.wsl_apply_server(distro, values, "off")

    say("")
    say("==> " + ("Finished with problems (above)." if failed else "Done.") + " Connect with:")
    user = os.environ.get("USERNAME", "you")
    wuser = ssh.wsl_user(distro) if distro else user
    hosts = ssh.lan_ips() + ([ssh.tailscale_ip()] if ssh.tailscale_ip() else [])
    for host in hosts:
        if ssh.wants_windows(values):
            say(f"    ssh -p {values['sshWindowsPort']} {user}@{host}    PowerShell")
        if ssh.wants_wsl(values):
            say(f"    ssh -p {values['sshWslPort']} {wuser}@{host}    Ubuntu")
    say("    A computer that used another port before needs its ~/.ssh/config updated.")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    args = [a for a in argv if a]
    verb = args[0] if args and not args[0].startswith("-") else "status"
    if verb in ("-h", "--help", "help") or "-h" in args or "--help" in args:
        say(HELP.rstrip())
        return 0
    if verb == "status":
        return status()
    if verb == "keys":
        return keys()
    if verb == "setup":
        return setup(args[1:])
    say(f"tstack ssh: unknown command '{verb}'")
    say(HELP.rstrip())
    return 2
