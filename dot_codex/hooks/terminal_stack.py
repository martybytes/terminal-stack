#!/usr/bin/env python3
"""Codex hook bridge and compact three-line WezTerm dashboard.

The SessionStart hook maps the launching WezTerm pane to Codex's exact rollout.
The Stop hook uses the existing terminal-stack TTS pipeline.  Dashboard mode is
started in a three-row split by the cy/cyr shell wrappers.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ESC = "\x1b["
RESET = f"{ESC}0m"
DIM = f"{ESC}2m"
GREEN = f"{ESC}38;5;78m"
YELLOW = f"{ESC}38;5;220m"
RED = f"{ESC}38;5;203m"
CYAN = f"{ESC}38;5;81m"
MAGENTA = f"{ESC}38;5;176m"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def state_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "terminal-stack" / "codex-status"


def pane_key(pane: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", pane)[:128]


def mapping_path(pane: str) -> Path:
    return state_root() / f"pane-{pane_key(pane)}.json"


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def hook_payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def hook_event(payload: dict[str, Any]) -> str:
    return str(payload.get("hook_event_name") or payload.get("event") or "").lower()


def save_hook_mapping(payload: dict[str, Any]) -> None:
    pane = str(os.environ.get("TS_CODEX_PARENT_PANE") or os.environ.get("WEZTERM_PANE") or "")
    if not pane:
        return
    current = read_json(mapping_path(pane))
    current.update(
        {
            "pane": pane,
            "session_id": payload.get("session_id") or payload.get("thread_id") or current.get("session_id", ""),
            "transcript_path": payload.get("transcript_path") or payload.get("rollout_path") or current.get("transcript_path", ""),
            "cwd": payload.get("cwd") or current.get("cwd") or os.getcwd(),
            "updated_at": time.time(),
        }
    )
    atomic_json(mapping_path(pane), current)


def run_tts(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        if os.name == "nt":
            script = Path.home() / ".claude/hooks/cc-speak.ps1"
            if not script.exists():
                return
            command = [
                "pwsh.exe", "-NoLogo", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-State", "waiting", "-Source", "codex",
            ]
            subprocess.run(command, input=raw, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=8, check=False)
        else:
            script = Path.home() / ".claude/hooks/cc-speak.sh"
            if not script.exists():
                return
            env = os.environ.copy()
            env["CC_TTS_SOURCE"] = "codex"
            subprocess.run(["bash", str(script), "waiting"], input=raw, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def hook_main() -> int:
    payload = hook_payload()
    save_hook_mapping(payload)
    if hook_event(payload) in {"stop", "sessionstop", "session_stop"}:
        run_tts(payload)
    return 0


def strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value)


def visible_len(value: str) -> int:
    return len(strip_ansi(value))


def color_for(percent: float) -> str:
    if percent >= 90:
        return RED
    if percent >= 70:
        return YELLOW
    return GREEN


def bar(percent: float | int | None, cells: int = 10) -> str:
    if percent is None:
        return f"{DIM}{'░' * cells}{RESET}"
    value = max(0.0, min(100.0, float(percent)))
    filled = min(cells, max(0, round(value * cells / 100)))
    return f"{color_for(value)}{'█' * filled}{DIM}{'░' * (cells - filled)}{RESET}"


def compact_int(value: int | float | None) -> str:
    if value is None:
        return "?"
    number = float(value)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.1f}m"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(int(number))


def as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value) if not isinstance(value, (dict, list, tuple)) else fallback
    except (TypeError, ValueError):
        return fallback


def reset_label(epoch: Any) -> str:
    try:
        remaining = max(0, int(float(epoch) - time.time()))
    except (TypeError, ValueError):
        return ""
    if remaining >= 86400:
        return f" ↻{remaining // 86400}d"
    if remaining >= 3600:
        return f" ↻{remaining // 3600}h"
    return f" ↻{max(1, remaining // 60)}m"


def rate_name(minutes: Any) -> str:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return "usage"
    if value == 300:
        return "5h"
    if value == 10080:
        return "7d"
    if value % 1440 == 0:
        return f"{value // 1440}d"
    if value % 60 == 0:
        return f"{value // 60}h"
    return f"{value}m"


def count_update(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def count_patch(item: dict[str, Any]) -> tuple[int, int]:
    if not isinstance(item, dict):
        return 0, 0
    changes = item.get("changes") or item.get("patch") or []
    if isinstance(changes, dict):
        changes = list(changes.values())
    if not isinstance(changes, list):
        changes = [item]
    added = removed = 0
    for change in changes:
        if not isinstance(change, dict):
            continue
        kind = str(change.get("kind") or change.get("type") or "").lower()
        content = str(change.get("content") or "")
        if kind in {"add", "create", "add_file"}:
            added += len(content.splitlines())
        elif kind in {"delete", "remove", "delete_file"}:
            removed += len(content.splitlines())
        else:
            diff = str(change.get("unified_diff") or change.get("diff") or content)
            plus, minus = count_update(diff)
            added += plus
            removed += minus
    if added == removed == 0:
        diff = str(item.get("unified_diff") or item.get("diff") or "")
        return count_update(diff)
    return added, removed


@dataclass
class RolloutState:
    model: str = "Codex"
    effort: str = "?"
    approval: str = "?"
    sandbox: str = "?"
    version: str = "?"
    cwd: str = ""
    context_tokens: int = 0
    context_window: int = 0
    total_tokens: int = 0
    added: int = 0
    removed: int = 0
    rates: list[dict[str, Any]] = field(default_factory=list)
    patch_calls: set[str] = field(default_factory=set)

    def consume(self, record: dict[str, Any]) -> None:
        kind = record.get("type")
        payload = record.get("payload") or {}
        if kind == "session_meta":
            self.version = str(payload.get("cli_version") or self.version)
            self.cwd = str(payload.get("cwd") or self.cwd)
            self.context_window = as_int(payload.get("context_window"), self.context_window)
        elif kind == "turn_context":
            self.model = str(payload.get("model") or self.model)
            self.effort = str(payload.get("effort") or self.effort)
            self.approval = str(payload.get("approval_policy") or self.approval)
            policy = payload.get("sandbox_policy") or payload.get("permission_profile") or {}
            self.sandbox = str(policy.get("type") if isinstance(policy, dict) else policy or self.sandbox)
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            last = info.get("last_token_usage") or {}
            total = info.get("total_token_usage") or {}
            self.context_tokens = as_int(last.get("total_tokens"))
            self.total_tokens = as_int(total.get("total_tokens"), self.total_tokens)
            self.context_window = as_int(info.get("model_context_window"), self.context_window)
            limits = payload.get("rate_limits") or {}
            self.rates = [x for x in (limits.get("primary"), limits.get("secondary")) if isinstance(x, dict)]
            self.rates.sort(key=lambda value: as_int(value.get("window_minutes"), 999999))
        elif kind == "event_msg" and payload.get("type") in {"patch_apply_end", "item_completed"}:
            item = payload.get("item") if payload.get("type") == "item_completed" else payload
            item_type = str(item.get("type") or "").lower().replace("_", "") if isinstance(item, dict) else ""
            if not isinstance(item, dict) or item_type not in {"", "patchapplyend", "filechange"}:
                return
            if item.get("success") is False or item.get("status") in {"failed", "error"}:
                return
            call_id = str(item.get("call_id") or item.get("id") or payload.get("call_id") or "")
            if call_id and call_id in self.patch_calls:
                return
            plus, minus = count_patch(item)
            self.added += plus
            self.removed += minus
            if call_id:
                self.patch_calls.add(call_id)


class RolloutReader:
    def __init__(self) -> None:
        self.path: Path | None = None
        self.offset = 0
        self.state = RolloutState()

    def select(self, path: Path | None) -> None:
        if path == self.path:
            return
        self.path = path
        self.offset = 0
        self.state = RolloutState()

    def refresh(self) -> None:
        if not self.path:
            return
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.offset = 0
                self.state = RolloutState()
            with self.path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(self.offset)
                for line in stream:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            self.state.consume(value)
                    except ValueError:
                        continue
                self.offset = stream.tell()
        except OSError:
            pass


def transcript_from_mapping(pane: str) -> Path | None:
    value = read_json(mapping_path(pane))
    raw = str(value.get("transcript_path") or "")
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate
    session = str(value.get("session_id") or "")
    if session:
        for candidate in (Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions").rglob("*.jsonl"):
            if session in candidate.name:
                return candidate
    return None


def rollout_cwd(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for _ in range(4):
                record = json.loads(stream.readline())
                if record.get("type") == "session_meta":
                    return str((record.get("payload") or {}).get("cwd") or "")
    except (OSError, ValueError):
        pass
    return ""


def discover_rollout(cwd: str, launched_at: float) -> Path | None:
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    try:
        candidates = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    except OSError:
        return None
    wanted = os.path.normcase(os.path.abspath(cwd))
    for candidate in candidates:
        try:
            if candidate.stat().st_mtime + 10 < launched_at:
                continue
        except OSError:
            continue
        found = rollout_cwd(candidate)
        if found and os.path.normcase(os.path.abspath(found)) == wanted:
            return candidate
    return None


def git_output(cwd: str, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", cwd, *args], text=True, encoding="utf-8",
                              errors="replace", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=2, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def git_status(cwd: str) -> dict[str, Any]:
    branch = git_output(cwd, "branch", "--show-current") or "detached"
    porcelain = git_output(cwd, "status", "--porcelain=v2", "--branch")
    dirty = staged = modified = deleted = untracked = conflicts = ahead = behind = 0
    for line in porcelain.splitlines():
        if line.startswith("# branch.ab "):
            match = re.search(r"\+(\d+)\s+-(\d+)", line)
            if match:
                ahead, behind = map(int, match.groups())
        elif line.startswith("?"):
            untracked += 1
        elif line.startswith("u "):
            conflicts += 1
        elif line[:2] in {"1 ", "2 "}:
            fields = line.split()
            xy = fields[1] if len(fields) > 1 else ".."
            staged += int(xy[0] not in {".", " "})
            modified += int(xy[1] not in {".", " ", "D"})
            deleted += int("D" in xy)
    dirty = staged + modified + deleted + untracked + conflicts
    remote = git_output(cwd, "remote", "get-url", "origin")
    repo = ""
    if remote:
        match = re.search(r"(?:[:/])([^/:]+/[^/]+?)(?:\.git)?$", remote)
        repo = match.group(1) if match else remote
    return {"branch": branch, "dirty": dirty, "staged": staged, "modified": modified,
            "deleted": deleted, "untracked": untracked, "conflicts": conflicts,
            "ahead": ahead, "behind": behind, "repo": repo}


def join_fit(parts: list[str], width: int) -> str:
    active = [part for part in parts if part]
    separator = f" {DIM}│{RESET} "
    while len(active) > 1 and visible_len(separator.join(active)) > width:
        active.pop()
    line = separator.join(active)
    if visible_len(line) <= width:
        return line
    plain = strip_ansi(line)
    return plain[: max(1, width - 1)] + "…"


def permission_label(state: RolloutState) -> str:
    sandbox = state.sandbox.lower()
    approval = state.approval.lower()
    if approval == "never" and "danger-full-access" in sandbox:
        return f"{RED}yolo{RESET}"
    return f"{YELLOW}{approval}/{sandbox}{RESET}"


def dashboard_lines(cwd: str, state: RolloutState, git: dict[str, Any], width: int) -> list[str]:
    leaf = Path(cwd).name or cwd
    dirty = f" Δ{git['dirty']}" if git.get("dirty") else " ✓"
    sync = ""
    if git.get("ahead"):
        sync += f" ↑{git['ahead']}"
    if git.get("behind"):
        sync += f" ↓{git['behind']}"
    line1 = join_fit([
        f"{CYAN}{leaf}{RESET}",
        f"{MAGENTA}{git.get('branch', '?')}{RESET}{dirty}{sync}",
        str(git.get("repo") or ""),
    ], width)

    context_pct = state.context_tokens * 100 / state.context_window if state.context_window else None
    rates = []
    for limit in state.rates:
        pct = limit.get("used_percent")
        rates.append(f"{rate_name(limit.get('window_minutes'))} {bar(pct)} {float(pct or 0):.0f}%{reset_label(limit.get('resets_at'))}")
    line2 = join_fit([
        f"{state.model}/{state.effort}",
        f"ctx {bar(context_pct)} {context_pct:.0f}%" if context_pct is not None else f"ctx {bar(None)} ?",
        *rates,
    ], width)

    host = f"{getpass.getuser()}@{socket.gethostname().split('.')[0]}"
    line3 = join_fit([
        host,
        f"tokens {compact_int(state.total_tokens)}",
        f"patch {GREEN}+{state.added}{RESET}/{RED}-{state.removed}{RESET}",
        permission_label(state),
        f"codex {state.version}",
    ], width)
    return [line1, line2, line3]


def dashboard_main(args: argparse.Namespace) -> int:
    pane = args.pane
    cwd = os.path.abspath(args.cwd)
    launched_at = float(args.launched_at)
    reader = RolloutReader()
    git = git_status(cwd)
    last_git = 0.0
    try:
        sys.stdout.write(f"{ESC}?25l")
        while True:
            path = transcript_from_mapping(pane) or discover_rollout(cwd, launched_at)
            reader.select(path)
            reader.refresh()
            now = time.monotonic()
            if now - last_git >= 2:
                git = git_status(cwd)
                last_git = now
            width = max(20, shutil.get_terminal_size((120, 3)).columns)
            lines = dashboard_lines(cwd, reader.state, git, width)
            sys.stdout.write(f"{ESC}H" + "\n".join(f"{ESC}2K{line}" for line in lines))
            sys.stdout.flush()
            time.sleep(0.75)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write(f"{RESET}{ESC}?25h")
        sys.stdout.flush()


def cleanup_main(pane: str) -> int:
    target = mapping_path(pane)
    root = state_root().resolve()
    try:
        resolved = target.resolve()
        if resolved.parent == root and resolved.is_file():
            resolved.unlink()
    except OSError:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("hook")
    dashboard = sub.add_parser("dashboard")
    dashboard.add_argument("--pane", required=True)
    dashboard.add_argument("--cwd", required=True)
    dashboard.add_argument("--launched-at", required=True)
    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--pane", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "hook":
        return hook_main()
    if args.mode == "cleanup":
        return cleanup_main(args.pane)
    return dashboard_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
