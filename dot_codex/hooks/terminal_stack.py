#!/usr/bin/env python3
"""Codex hook bridge and compact three-line WezTerm dashboard.

The SessionStart hook maps the launching WezTerm pane to Codex's exact rollout.
The Stop hook uses the existing terminal-stack TTS pipeline. Dashboard mode is
started in a three-row split for enhanced interactive Codex launches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
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
BLUE = f"{ESC}38;5;117m"
ORANGE = f"{ESC}38;5;208m"
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
            local_app = os.environ.get("LOCALAPPDATA")
            exe = Path(local_app) / "terminal-stack/tts-daemon/terminal-stack-tts.exe" if local_app else None
            if exe and exe.is_file():
                command = [str(exe), "hook", "--source", "codex", "--event", "stop",
                           "--state", "waiting"]
            else:
                script = Path.home() / ".claude/hooks/cc-speak.ps1"
                if not script.is_file():
                    return
                command = [
                    "pwsh.exe", "-NoLogo", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(script), "-State", "waiting", "-Source", "codex",
                ]
            subprocess.run(
                command, input=raw, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=8, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
            )
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


def duration_label(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    value = max(0, int(seconds))
    if value < 60:
        return f"{value}s"
    if value < 3600:
        return f"{value // 60}m{value % 60:02d}s"
    if value < 86400:
        return f"{value // 3600}h{(value % 3600) // 60:02d}m"
    return f"{value // 86400}d{(value % 86400) // 3600}h"


def as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value) if not isinstance(value, (dict, list, tuple)) else fallback
    except (TypeError, ValueError):
        return fallback


def as_epoch(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return number
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
        return "weekly"
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
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    added: int = 0
    removed: int = 0
    activity: str = "WAIT"
    current_action: str = "waiting"
    turn_started: float = 0.0
    last_turn_seconds: float = 0.0
    turn_active: bool = False
    tool_failures: int = 0
    plan_type: str = ""
    credit_balance: str = ""
    credit_unlimited: bool = False
    rates: list[dict[str, Any]] = field(default_factory=list)
    patch_calls: set[str] = field(default_factory=set)

    def _set_tool_action(self, item: dict[str, Any]) -> None:
        item_type = str(item.get("type") or "")
        lowered = item_type.lower()
        status = str(item.get("status") or "").lower()
        exit_code = item.get("exit_code")
        if status in {"failed", "error"} or (isinstance(exit_code, int) and exit_code != 0):
            self.tool_failures += 1
        if lowered == "commandexecution":
            command = item.get("command") or item.get("parsed_cmd") or "shell"
            if isinstance(command, list):
                command = " ".join(str(part) for part in command[:3])
            command = re.sub(r"\s+", " ", str(command)).strip()
            self.activity = "TOOL"
            self.current_action = f"shell {command[:42]}" if command else "shell"
        elif lowered == "filechange":
            changes = item.get("changes") or {}
            count = len(changes) if isinstance(changes, (dict, list)) else 1
            self.activity = "TOOL"
            self.current_action = f"edit {count} file{'s' if count != 1 else ''}"
        elif lowered == "mcptoolcall":
            name = item.get("tool") or item.get("name") or item.get("server") or "MCP tool"
            self.activity = "TOOL"
            self.current_action = str(name).replace("_", " ")[:48]
        elif lowered == "imageview":
            self.activity = "TOOL"
            self.current_action = "viewing image"
        elif lowered == "extension":
            action = item.get("action") or item.get("kind") or "extension"
            self.activity = "TOOL"
            self.current_action = str(action).replace("_", " ")[:48]
        elif lowered == "contextcompaction":
            self.activity = "THINK"
            self.current_action = "compacting context"
        elif lowered == "plan":
            self.activity = "THINK"
            self.current_action = "updating plan"
        elif lowered == "reasoning":
            self.activity = "THINK"
            self.current_action = "reasoning"

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
        elif kind == "response_item":
            response_type = str(payload.get("type") or "").lower()
            if response_type in {"function_call", "custom_tool_call"}:
                name = str(payload.get("name") or "tool").replace("_", " ")
                if name in {"request user input", "yield control"}:
                    self.activity = "WAIT"
                    self.current_action = "awaiting input"
                else:
                    self.activity = "TOOL"
                    self.current_action = name[:48]
            elif response_type == "reasoning":
                self.activity = "THINK"
                self.current_action = "reasoning"
        elif kind == "event_msg" and payload.get("type") == "task_started":
            self.turn_active = True
            self.turn_started = as_epoch(payload.get("started_at"), time.time())
            self.activity = "THINK"
            self.current_action = "starting turn"
        elif kind == "event_msg" and payload.get("type") == "task_complete":
            self.turn_active = False
            duration_ms = as_int(payload.get("duration_ms"))
            if duration_ms:
                self.last_turn_seconds = duration_ms / 1000
            elif self.turn_started:
                self.last_turn_seconds = max(0, time.time() - self.turn_started)
            self.activity = "DONE"
            self.current_action = "complete"
        elif kind == "event_msg" and str(payload.get("type") or "").lower() in {"error", "stream_error"}:
            self.activity = "ERROR"
            self.current_action = "agent error"
        elif kind == "event_msg" and payload.get("type") == "turn_aborted":
            self.turn_active = False
            self.activity = "ERROR"
            self.current_action = "turn aborted"
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            last = info.get("last_token_usage") or {}
            total = info.get("total_token_usage") or {}
            self.context_tokens = as_int(last.get("total_tokens"))
            self.total_tokens = as_int(total.get("total_tokens"), self.total_tokens)
            self.input_tokens = as_int(total.get("input_tokens"), self.input_tokens)
            self.output_tokens = as_int(total.get("output_tokens"), self.output_tokens)
            self.cached_tokens = as_int(total.get("cached_input_tokens"), self.cached_tokens)
            self.reasoning_tokens = as_int(total.get("reasoning_output_tokens"), self.reasoning_tokens)
            self.context_window = as_int(info.get("model_context_window"), self.context_window)
            limits = payload.get("rate_limits") or {}
            self.rates = [x for x in (limits.get("primary"), limits.get("secondary")) if isinstance(x, dict)]
            self.rates.sort(key=lambda value: as_int(value.get("window_minutes"), 999999))
            self.plan_type = str(limits.get("plan_type") or self.plan_type or "")
            credits = limits.get("credits") or {}
            if isinstance(credits, dict):
                self.credit_balance = str(credits.get("balance") or self.credit_balance or "")
                self.credit_unlimited = bool(credits.get("unlimited", self.credit_unlimited))
        elif kind == "event_msg" and payload.get("type") in {"patch_apply_end", "item_completed"}:
            item = payload.get("item") if payload.get("type") == "item_completed" else payload
            item_type = str(item.get("type") or "").lower().replace("_", "") if isinstance(item, dict) else ""
            if isinstance(item, dict):
                self._set_tool_action(item)
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
            dirty += 1
            untracked += 1
        elif line.startswith("u "):
            dirty += 1
            conflicts += 1
        elif line[:2] in {"1 ", "2 "}:
            dirty += 1
            fields = line.split()
            xy = fields[1] if len(fields) > 1 else ".."
            staged += int(xy[0] not in {".", " "})
            modified += int(xy[1] not in {".", " ", "D"})
            deleted += int("D" in xy)
    remote = git_output(cwd, "remote", "get-url", "origin")
    repo = ""
    if remote:
        match = re.search(r"(?:[:/])([^/:]+/[^/]+?)(?:\.git)?$", remote)
        repo = match.group(1) if match else remote
    root = git_output(cwd, "rev-parse", "--show-toplevel")
    upstream = git_output(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    stash_output = git_output(cwd, "stash", "list", "--format=%gd")
    stash_count = len(stash_output.splitlines()) if stash_output else 0
    commit_epoch = as_epoch(git_output(cwd, "log", "-1", "--format=%ct"))
    commit_age = max(0, time.time() - commit_epoch) if commit_epoch else None
    git_dir = git_output(cwd, "rev-parse", "--absolute-git-dir")
    common_dir = git_output(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    linked_worktree = bool(git_dir and common_dir and os.path.normcase(git_dir) != os.path.normcase(common_dir))
    return {"branch": branch, "dirty": dirty, "staged": staged, "modified": modified,
            "deleted": deleted, "untracked": untracked, "conflicts": conflicts,
            "ahead": ahead, "behind": behind, "repo": repo, "root": root,
            "upstream": upstream, "stash": stash_count, "commit_age": commit_age,
            "worktree": linked_worktree}


def gh_pr(cwd: str) -> dict[str, Any]:
    if not shutil.which("gh"):
        return {}
    fields = "number,isDraft,reviewDecision,mergeStateStatus,statusCheckRollup"
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", fields], cwd=cwd, text=True,
            encoding="utf-8", errors="replace", stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=6, check=False,
        )
        if result.returncode != 0:
            return {}
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def pr_health(pr: dict[str, Any]) -> dict[str, str]:
    if not pr or not pr.get("number"):
        return {}
    review = "draft" if pr.get("isDraft") else str(pr.get("reviewDecision") or "review").lower()
    if review == "approved":
        review = "approved"
    elif review == "changes_requested":
        review = "changes"
    elif review == "review_required":
        review = "review"
    checks = pr.get("statusCheckRollup") or []
    failing = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    ci = "none"
    if checks:
        conclusions = {str(item.get("conclusion") or "").upper() for item in checks if isinstance(item, dict)}
        statuses = {str(item.get("status") or "").upper() for item in checks if isinstance(item, dict)}
        if conclusions & failing:
            ci = "fail"
        elif any(status and status != "COMPLETED" for status in statuses) or "" in conclusions:
            ci = "pending"
        else:
            ci = "pass"
    merge_raw = str(pr.get("mergeStateStatus") or "").upper()
    if merge_raw == "DIRTY":
        merge = "conflict"
    elif merge_raw in {"CLEAN", "HAS_HOOKS", "UNSTABLE"}:
        merge = "ready" if merge_raw != "UNSTABLE" else "blocked"
    elif merge_raw in {"BLOCKED", "BEHIND"}:
        merge = "blocked"
    else:
        merge = "unknown"
    return {"number": str(pr["number"]), "review": review, "ci": ci, "merge": merge}


def tts_fault() -> str:
    config_path = Path.home() / ".claude/tts/config.json"
    config = read_json(config_path)
    if not config or not config.get("enabled"):
        return ""
    sources = config.get("sources") or {}
    if not isinstance(sources, dict) or "codex" not in sources:
        return "TTS codex source missing"
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        exe = Path(local_app) / "terminal-stack/tts-daemon/terminal-stack-tts.exe" if local_app else None
        hook_exists = bool(exe and exe.is_file()) or (Path.home() / ".claude/hooks/cc-speak.ps1").is_file()
    else:
        hook_exists = (Path.home() / ".claude/hooks/cc-speak.sh").is_file()
    if not hook_exists:
        return "TTS hook missing"
    daemon = config.get("daemon") or {}
    if not isinstance(daemon, dict) or not daemon.get("enabled"):
        return ""
    port = as_int(daemon.get("port"), 8890)
    host = str(daemon.get("hostOverride") or "127.0.0.1")
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=0.7) as response:
            health = json.loads(response.read(4096))
        if not isinstance(health, dict) or not health.get("ok"):
            return "TTS daemon unhealthy"
    except (OSError, ValueError, urllib.error.URLError):
        return "TTS daemon offline"
    return ""


def smart_path(cwd: str, root: str = "") -> tuple[str, str]:
    absolute = os.path.abspath(cwd)
    if root:
        try:
            relative = os.path.relpath(absolute, root)
            root_name = Path(root).name
            full = root_name if relative == "." else f"{root_name}/{relative.replace(os.sep, '/')}"
            compact = root_name if relative == "." else f"{root_name}/…/{Path(relative).name}"
            return full, compact
        except ValueError:
            pass
    home = os.path.abspath(str(Path.home()))
    if os.path.normcase(absolute).startswith(os.path.normcase(home)):
        relative = os.path.relpath(absolute, home)
        full = "~" if relative == "." else f"~/{relative.replace(os.sep, '/')}"
    else:
        full = absolute.replace(os.sep, "/")
    return full, Path(absolute).name or full


@dataclass
class Segment:
    full: str
    compact: str = ""
    priority: int = 50
    required: bool = False

    def short(self) -> str:
        return self.compact or self.full


def fit_segments(segments: list[Segment], width: int) -> str:
    separator = f" {DIM}│{RESET} "
    active = [segment for segment in segments if segment.full]
    values = [segment.full for segment in active]

    def render() -> str:
        return separator.join(values)

    if visible_len(render()) <= width:
        return render()

    for index in sorted(range(len(active)), key=lambda idx: active[idx].priority):
        compact = active[index].short()
        if compact != values[index] and visible_len(compact) < visible_len(values[index]):
            values[index] = compact
            if visible_len(render()) <= width:
                return render()
    while visible_len(render()) > width:
        removable = [index for index, segment in enumerate(active) if not segment.required and values[index]]
        if not removable:
            break
        index = min(removable, key=lambda idx: active[idx].priority)
        values[index] = ""
        kept = [(segment, value) for segment, value in zip(active, values) if value]
        active = [item[0] for item in kept]
        values = [item[1] for item in kept]
    line = render()
    if visible_len(line) <= width:
        return line
    plain = strip_ansi(line)
    return plain[: max(1, width - 1)] + "…"


def join_fit(parts: list[str], width: int) -> str:
    return fit_segments([Segment(part) for part in parts if part], width)


def permission_label(state: RolloutState) -> str:
    sandbox = state.sandbox.lower()
    approval = state.approval.lower()
    if approval == "never" and "danger-full-access" in sandbox:
        return f"{RED}yolo{RESET}"
    return f"{YELLOW}{approval}/{sandbox}{RESET}"


def change_segment(git: dict[str, Any]) -> Segment:
    if not git.get("dirty"):
        return Segment(f"{GREEN}✓ clean{RESET}", f"{GREEN}✓{RESET}", 100, True)
    full: list[str] = []
    specs = [
        ("staged", "+", GREEN), ("modified", "~", YELLOW),
        ("deleted", "-", RED), ("untracked", "?", CYAN), ("conflicts", "!", RED),
    ]
    for key, glyph, color in specs:
        if git.get(key):
            full.append(f"{color}{glyph}{git[key]}{RESET}")
    return Segment("changes " + " ".join(full), f"Δ{git.get('dirty', 0)}", 100, True)


def pr_segment(pr: dict[str, str]) -> Segment:
    if not pr:
        return Segment("")
    review = pr.get("review", "review")
    ci = pr.get("ci", "none")
    merge = pr.get("merge", "unknown")
    review_color = GREEN if review == "approved" else RED if review == "changes" else YELLOW
    ci_color = GREEN if ci == "pass" else RED if ci == "fail" else YELLOW if ci == "pending" else DIM
    merge_color = GREEN if merge == "ready" else RED if merge == "conflict" else YELLOW
    review_glyph = {"approved": "✓", "changes": "✗", "draft": "D", "review": "…"}.get(review, "…")
    ci_glyph = {"pass": "✓", "fail": "✗", "pending": "…", "none": "–"}.get(ci, "?")
    merge_glyph = {"ready": "✓", "conflict": "✗", "blocked": "!", "unknown": "?"}.get(merge, "?")
    full = (
        f" PR #{pr['number']} "
        f"{review_color}{review}{RESET} "
        f"CI {ci_color}{ci}{RESET} "
        f"merge {merge_color}{merge}{RESET}"
    )
    compact = (
        f"#{pr['number']} "
        f"{review_color}R{review_glyph}{RESET} "
        f"{ci_color}C{ci_glyph}{RESET} "
        f"{merge_color}M{merge_glyph}{RESET}"
    )
    return Segment(full, compact, 75)


def activity_segment(state: RolloutState, launched_at: float, now: float) -> Segment:
    colors = {"WAIT": DIM, "THINK": CYAN, "TOOL": MAGENTA, "DONE": GREEN, "ERROR": RED}
    color = colors.get(state.activity, DIM)
    turn_seconds = max(0, now - state.turn_started) if state.turn_active and state.turn_started else state.last_turn_seconds
    timer_color = ORANGE if turn_seconds >= 300 else YELLOW if turn_seconds >= 120 else BLUE
    session_seconds = max(0, now - launched_at) if launched_at else 0
    full = (
        f"{color}[{state.activity}]{RESET} {state.current_action} "
        f"{timer_color}turn {duration_label(turn_seconds)}{RESET} "
        f"{DIM}sess {duration_label(session_seconds)}{RESET}"
    )
    compact = f"{color}[{state.activity}]{RESET} {timer_color}{duration_label(turn_seconds)}{RESET}"
    return Segment(full, compact, 100, True)


def dashboard_lines(
    cwd: str,
    state: RolloutState,
    git: dict[str, Any],
    width: int,
    pr: dict[str, str] | None = None,
    launched_at: float = 0.0,
    now: float | None = None,
    audio_fault: str = "",
) -> list[str]:
    current_time = now if now is not None else time.time()
    path_full, path_compact = smart_path(cwd, str(git.get("root") or ""))
    branch = str(git.get("branch") or "?")
    upstream = str(git.get("upstream") or "")
    branch_full = f" {MAGENTA}{branch}{RESET}" + (f" → {upstream}" if upstream else "")
    branch_compact = f" {MAGENTA}{branch}{RESET}"
    line1 = fit_segments([
        Segment(f"󰉋 {CYAN}{path_full}{RESET}", f"󰉋 {CYAN}{path_compact}{RESET}", 100, True),
        Segment(f"󰊢 {git.get('repo', '')}", str(git.get("repo", "")).split("/", 1)[-1], 80),
        Segment(branch_full, branch_compact, 95, True),
        Segment(f"󰙅 linked worktree", "󰙅 wt", 55) if git.get("worktree") else Segment(""),
    ], width)

    sync_full: list[str] = []
    sync_compact = ""
    if git.get("ahead"):
        sync_full.append(f"↑{git['ahead']} ahead")
        sync_compact += f"↑{git['ahead']}"
    if git.get("behind"):
        sync_full.append(f"↓{git['behind']} behind")
        sync_compact += (" " if sync_compact else "") + f"↓{git['behind']}"
    patch = f"patch {GREEN}+{state.added}{RESET}/{RED}-{state.removed}{RESET}"
    patch_short = f"±{GREEN}{state.added}{RESET}/{RED}{state.removed}{RESET}"
    line2 = fit_segments([
        change_segment(git),
        Segment(" ".join(sync_full), sync_compact, 90),
        Segment(f"≡ {git.get('stash')} stashes", f"≡{git.get('stash')}", 55) if git.get("stash") else Segment(""),
        Segment(patch, patch_short, 95, True),
        Segment(f"󱑂 commit {duration_label(git.get('commit_age'))} ago", f"󱑂{duration_label(git.get('commit_age'))}", 40)
        if git.get("commit_age") is not None else Segment(""),
        pr_segment(pr or {}),
    ], width)

    context_pct = state.context_tokens * 100 / state.context_window if state.context_window else None
    context_full = (
        f"ctx {bar(context_pct)} {context_pct:.0f}% {DIM}{100 - context_pct:.0f}% left{RESET}"
        if context_pct is not None else f"ctx {bar(None)} ?"
    )
    context_short = f"ctx {bar(context_pct)} {context_pct:.0f}%" if context_pct is not None else f"ctx {bar(None)} ?"
    rate_segments: list[Segment] = []
    for limit in state.rates:
        pct = float(limit.get("used_percent") or 0)
        label = rate_name(limit.get("window_minutes"))
        rate_segments.append(Segment(
            f"{label} {bar(pct)} {pct:.0f}%{reset_label(limit.get('resets_at'))}",
            f"{label} {bar(pct)} {pct:.0f}%", 100, True,
        ))
    token_full = (
        f"tok {compact_int(state.total_tokens)} "
        f"i{compact_int(state.input_tokens)}/o{compact_int(state.output_tokens)}/c{compact_int(state.cached_tokens)}"
    )
    account = ""
    if state.credit_balance and not state.credit_unlimited:
        try:
            account = f"credits {compact_int(float(state.credit_balance))}"
        except ValueError:
            account = f"credits {state.credit_balance}"
    elif state.plan_type and state.plan_type.lower() not in {"pro", ""}:
        account = state.plan_type
    line3 = fit_segments([
        activity_segment(state, launched_at, current_time),
        Segment(f"model {state.model} · {state.effort}", f"{state.model}/{state.effort}", 90, True),
        Segment(context_full, context_short, 100, True),
        *rate_segments,
        Segment(token_full, f"tok {compact_int(state.total_tokens)}", 55),
        Segment(account, account, 25),
        Segment(f"{RED}!{state.tool_failures} failed tools{RESET}", f"{RED}!{state.tool_failures}{RESET}", 85)
        if state.tool_failures else Segment(""),
        Segment(permission_label(state), permission_label(state), 80),
        Segment(f"codex {state.version}", f"v{state.version}", 15),
        Segment(f"{RED}󰕾 {audio_fault}{RESET}", f"{RED}󰕾 TTS!{RESET}", 100, True) if audio_fault else Segment(""),
    ], width)
    return [line1, line2, line3]


def dashboard_main(args: argparse.Namespace) -> int:
    pane = args.pane
    cwd = os.path.abspath(args.cwd)
    launched_at = float(args.launched_at)
    reader = RolloutReader()
    git = git_status(cwd)
    pr = pr_health(gh_pr(cwd))
    audio_fault = tts_fault()
    initial_refresh = time.monotonic()
    last_git = initial_refresh
    last_pr = initial_refresh
    last_tts = initial_refresh
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
            if now - last_pr >= 45:
                pr = pr_health(gh_pr(cwd))
                last_pr = now
            if now - last_tts >= 30:
                audio_fault = tts_fault()
                last_tts = now
            width = max(20, shutil.get_terminal_size((120, 3)).columns)
            lines = dashboard_lines(
                cwd, reader.state, git, width, pr=pr, launched_at=launched_at,
                now=time.time(), audio_fault=audio_fault,
            )
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
