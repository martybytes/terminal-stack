#!/usr/bin/env bash
# Sync from the chezmoi source tree to the Windows user profile:
#   $CHEZMOI_SOURCE_DIR/windows/**  → /mnt/c/Users/<windowsUsername>/
#   $CHEZMOI_SOURCE_DIR/dot_codex/** → /mnt/c/Users/<windowsUsername>/.codex/
#   $CHEZMOI_SOURCE_DIR/docs/kb/**  → /mnt/c/Users/<windowsUsername>/AppData/Local/terminal-stack/docs/kb/
#
# Username resolution order:
#   1. chezmoi data: `windowsUsername` under the [data] section of chezmoi.toml
#   2. Fallback: `cmd.exe /c echo %USERNAME%` via WSL interop
#
# Files ending in `.tmpl` under windows/ are rendered before copy: tokens are
# replaced and the `.tmpl` suffix is stripped on the destination path. Tokens:
#   __WIN_USER__        resolved Windows username
#   __LEADER_KEY__      WezTerm leader key   (from leaderKey   in chezmoi [data])
#   __LEADER_MODS__     WezTerm leader mods  (from leaderMods)
#   __THEME_MODE__      dark|light|follow    (from themeMode)
#   __THEME_RESOLVED__  baked palette light|dark (from resolvedTheme)
#   __TMUX_PREFIX__     tmux prefix spec     (from tmuxPrefixResolved)
#   __WEZ_MUX__         on|off WezTerm mux domain (from weztermMux; see ts-mux)
#   __WEZ_RESTORE__     on|off reopen last session (from weztermRestore)
#   __CC_TTS_STOP_HOOK__ / __CC_TTS_STOPFAILURE_HOOK__ / __CC_TTS_CURSOR_HOOKS__ /
#   __CC_TTS_PRETOOLUSE_TTS__ / __CC_TTS_INPUT_HOOKS__  optional cc-speak hooks (when ccTtsEnabled)
#
# Idempotent: only writes targets whose content differs.
# Backs up any pre-existing target to <path>.bak.YYYYMMDD[.N] before overwrite.
set -euo pipefail

stack_root="${CHEZMOI_SOURCE_DIR:-$HOME/.local/share/chezmoi}"
windows_src="$stack_root/windows"
codex_src="$stack_root/dot_codex"
kb_src="$stack_root/docs/kb"

# Non-WSL / no Windows mount available — no destination to sync to. Bail before
# we try to resolve a Windows username we can't possibly find. Native Linux and
# macOS land here.
if [ ! -d /mnt/c/Users ]; then
  exit 0
fi

if [ ! -d "$windows_src" ] && [ ! -d "$codex_src" ] && [ ! -d "$kb_src" ]; then
  exit 0
fi

resolve_win_user() {
  local cz=""
  if command -v chezmoi >/dev/null 2>&1; then
    cz="chezmoi"
  elif [ -x "$HOME/.local/bin/chezmoi" ]; then
    cz="$HOME/.local/bin/chezmoi"
  elif [ -x /usr/local/bin/chezmoi ]; then
    cz="/usr/local/bin/chezmoi"
  fi

  if [ -n "$cz" ]; then
    local u
    u=$("$cz" execute-template '{{ if hasKey . "windowsUsername" }}{{ .windowsUsername }}{{ end }}' 2>/dev/null || true)
    if [ -n "$u" ]; then echo "$u"; return 0; fi
  fi

  if [ -x /mnt/c/Windows/System32/cmd.exe ]; then
    local u
    u=$(/mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true)
    if [ -n "$u" ]; then echo "$u"; return 0; fi
  fi

  return 1
}

WIN_USER="$(resolve_win_user || true)"
if [ -z "$WIN_USER" ]; then
  echo "sync-windows: could not resolve Windows username." >&2
  echo "  Add to ~/.config/chezmoi/chezmoi.toml:" >&2
  echo "    [data]" >&2
  echo "    windowsUsername = \"<your-windows-username>\"" >&2
  exit 1
fi

# Resolve the terminal-stack config tokens from chezmoi [data], each with a
# default so a clone that predates the wizard renders today's behaviour.
resolve_cz() {
  if command -v chezmoi >/dev/null 2>&1; then command -v chezmoi
  elif [ -x "$HOME/.local/bin/chezmoi" ]; then echo "$HOME/.local/bin/chezmoi"
  elif [ -x /usr/local/bin/chezmoi ]; then echo /usr/local/bin/chezmoi
  else return 1; fi
}
cfg() {  # cfg <data-key> <default>
  local cz v=""
  if cz="$(resolve_cz)"; then
    v="$("$cz" execute-template "{{ if hasKey . \"$1\" }}{{ index . \"$1\" }}{{ end }}" 2>/dev/null || true)"
  fi
  [ -n "$v" ] && echo "$v" || echo "$2"
}
LEADER_KEY="$(cfg leaderKey 'phys:Space')"
LEADER_MODS="$(cfg leaderMods 'CTRL')"
THEME_MODE="$(cfg themeMode 'dark')"
THEME_RESOLVED="$(cfg resolvedTheme 'dark')"
TMUX_PREFIX="$(cfg tmuxPrefixResolved 'C-b')"
WEZ_MUX="$(cfg weztermMux 'off')"
WEZ_RESTORE="$(cfg weztermRestore 'off')"
CC_TTS_ENABLED="$(cfg ccTtsEnabled false)"
HEADROOM_ENABLED="$(cfg headroomEnabled off)"
HEADROOM_CURSOR_MODE="$(cfg headroomCursorMode mcp)"
CAVEMAN_ENABLED="$(cfg cavemanEnabled off)"
AGENTMEMORY_ENABLED="$(cfg agentmemoryEnabled off)"
if [ "$CC_TTS_ENABLED" = true ]; then
  CC_TTS_STOP_HOOK=$',
          {
            "type": "command",
            "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event stop --state waiting"
          }'
  CC_TTS_STOPFAILURE_HOOK=$',
          {
            "type": "command",
            "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event stop_failure --state error"
          }'
  CC_TTS_CURSOR_HOOKS='{
    "afterFileEdit": [
      {
        "command": "cat > /dev/null",
        "timeout": 1
      }
    ],
    "afterAgentResponse": [
      {
        "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source cursor --event cursor_response --state waiting",
        "timeout": 15
      }
    ],
    "stop": [
      {
        "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source cursor --event cursor_stop --state waiting",
        "timeout": 15
      }
    ],
    "postToolUse": [
      {
        "matcher": "AskQuestion|AskUserQuestion",
        "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source cursor --event cursor_question --state question",
        "timeout": 15
      }
    ]
  }'
  CC_TTS_PRETOOLUSE_TTS=$',
      {
        "matcher": "AskUserQuestion",
        "hooks": [
          {
            "type": "command",
            "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event question --state question"
          }
        ]
      }'
  CC_TTS_INPUT_HOOKS=$',
    "Notification": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "C:/Users/'"$WIN_USER"'/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event notification --state question"
          }
        ]
      }
    ]'
else
  CC_TTS_STOP_HOOK=""
  CC_TTS_STOPFAILURE_HOOK=""
  CC_TTS_CURSOR_HOOKS='{}'
  CC_TTS_PRETOOLUSE_TTS=""
  CC_TTS_INPUT_HOOKS=""
fi

dst_home="/mnt/c/Users/$WIN_USER"
if [ ! -d "$dst_home" ]; then
  exit 0
fi

if [ "$CC_TTS_ENABLED" = true ]; then
  tts_exe="$dst_home/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe"
  if [ ! -f "$tts_exe" ]; then
    installer="$stack_root/bootstrap/install-tts-daemon.ps1"
    pwsh_exe="/mnt/c/Program Files/PowerShell/7/pwsh.exe"
    [ -f "$installer" ] && [ -x "$pwsh_exe" ] || {
      echo "sync-windows: TTS is enabled but its EXE installer is unavailable." >&2
      exit 1
    }
    installer_win="$(wslpath -w "$installer")"
    if [ "$(cfg ccTtsDaemon off)" = on ]; then
      "$pwsh_exe" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$installer_win"
    else
      "$pwsh_exe" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$installer_win" -NoStart -NoAutostart
    fi
    [ -f "$tts_exe" ] || { echo "sync-windows: TTS EXE install failed." >&2; exit 1; }
  fi
fi

today="$(date +%Y%m%d)"
created=0
updated=0
unchanged=0
wezterm_cfg_changed=0

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

resolve_pwsh() {
  local p
  for p in /mnt/c/Program\ Files/PowerShell/7/pwsh.exe \
           /mnt/c/Program\ Files/PowerShell/7-preview/pwsh.exe; do
    if [ -x "$p" ]; then printf '%s' "$p"; return 0; fi
  done
  return 1
}

# merge_part_owned <helper-basename> <stage-name> <rendered-src> <dst>
# Two Windows destinations are part-owned: another tool writes the same file, so a
# whole-file copy deletes its state. On 2026-08-20 one sync did exactly that to both.
#
#   .claude/settings.json  Claude Code owns `model`, `enabledPlugins`, `permissions`,
#                          `env`, `extraKnownMarketplaces` (set by /model, /plugin).
#                          Losing `enabledPlugins` silently disabled the agentmemory
#                          plugin: twelve lifecycle hooks and its MCP server stopped
#                          loading, with nothing to say why.
#   .cursor/hooks.json     agentmemory's seven Cursor hooks live in the same `hooks`
#                          object as our TTS hooks — two of them in the very same
#                          event arrays — so ownership there is per entry.
#
# Both merges are pwsh: the splice engine and the entry-level ownership rules are
# already written there, and the destination is a Windows path either way.
merge_part_owned() {
  local helper_name="$1" stage_name="$2" src="$3" dst="$4"
  local helper="$stack_root/bootstrap/$helper_name" pwsh_bin stage
  if [ ! -f "$helper" ]; then
    echo "sync-windows: $helper missing; leaving $dst alone." >&2
    return 0
  fi
  if ! pwsh_bin="$(resolve_pwsh)"; then
    if [ -e "$dst" ]; then
      echo "sync-windows: pwsh not found; leaving $dst alone — a whole-file copy would delete another tool's own entries." >&2
      return 0
    fi
    # Nothing there yet, so nothing to preserve: the plain copy is correct.
    mkdir -p -- "$(dirname -- "$dst")"
    cp -- "$src" "$dst"
    printf 'created  %s\n' "$dst"
    return 0
  fi
  # Stage the rendered fragment on the Windows side so pwsh.exe reads a real
  # C:\ path instead of a \\wsl.localhost round trip.
  stage="$dst_home/AppData/Local/Temp/$stage_name"
  mkdir -p -- "$(dirname -- "$stage")"
  cp -- "$src" "$stage"
  if ! "$pwsh_bin" -NoLogo -NonInteractive -ExecutionPolicy Bypass \
       -File "$(wslpath -w "$helper")" \
       -FragmentPath "$(wslpath -w "$stage")" \
       -LivePath "$(wslpath -w "$dst")"; then
    echo "sync-windows: merge via $helper_name failed (non-fatal); $dst left as it was." >&2
  fi
  rm -f -- "$stage"
  return 0
}

# sync_tree <src_root> <dst_root> <render_tmpl:0|1>
sync_tree() {
  local src_root="$1" dst_root="$2" render_tmpl="${3:-0}"
  local src rel rel_out rel_dir rel_leaf effective_src dst bak n is_modifier modified

  [ -d "$src_root" ] || return 0

  while IFS= read -r -d '' src; do
    rel="${src#"$src_root"/}"
    is_modifier=0
    modified=""
    [[ "${rel##*/}" == modify_* ]] && is_modifier=1

    if [ "$render_tmpl" = 1 ] && [[ "$rel" == *.tmpl ]]; then
      rel_out="${rel%.tmpl}"
      if [ "$is_modifier" = 1 ]; then
        rel_leaf="${rel_out##*/}"
        rel_leaf="${rel_leaf#modify_}"
        rel_leaf="${rel_leaf#private_}"
        if [[ "$rel_out" == */* ]]; then
          rel_dir="${rel_out%/*}"
          rel_out="$rel_dir/$rel_leaf"
        else
          rel_out="$rel_leaf"
        fi
      fi
      if command -v python3 >/dev/null 2>&1; then
        WIN_USER="$WIN_USER" LEADER_KEY="$LEADER_KEY" LEADER_MODS="$LEADER_MODS" \
        THEME_MODE="$THEME_MODE" THEME_RESOLVED="$THEME_RESOLVED" TMUX_PREFIX="$TMUX_PREFIX" \
        WEZ_MUX="$WEZ_MUX" WEZ_RESTORE="$WEZ_RESTORE" \
        CC_TTS_STOP_HOOK="$CC_TTS_STOP_HOOK" CC_TTS_STOPFAILURE_HOOK="$CC_TTS_STOPFAILURE_HOOK" \
        CC_TTS_CURSOR_HOOKS="$CC_TTS_CURSOR_HOOKS" CC_TTS_PRETOOLUSE_TTS="$CC_TTS_PRETOOLUSE_TTS" \
        CC_TTS_INPUT_HOOKS="$CC_TTS_INPUT_HOOKS" \
        python3 - "$src" <<'PY' > "$rendered"
import os, sys
text = open(sys.argv[1], encoding="utf-8").read()
repl = {
    "__WIN_USER__": os.environ.get("WIN_USER", ""),
    "__LEADER_KEY__": os.environ.get("LEADER_KEY", ""),
    "__LEADER_MODS__": os.environ.get("LEADER_MODS", ""),
    "__THEME_MODE__": os.environ.get("THEME_MODE", ""),
    "__THEME_RESOLVED__": os.environ.get("THEME_RESOLVED", ""),
    "__TMUX_PREFIX__": os.environ.get("TMUX_PREFIX", ""),
    "__WEZ_MUX__": os.environ.get("WEZ_MUX", "off"),
    "__WEZ_RESTORE__": os.environ.get("WEZ_RESTORE", "off"),
    "__CC_TTS_STOP_HOOK__": os.environ.get("CC_TTS_STOP_HOOK", ""),
    "__CC_TTS_STOPFAILURE_HOOK__": os.environ.get("CC_TTS_STOPFAILURE_HOOK", ""),
    "__CC_TTS_CURSOR_HOOKS__": os.environ.get("CC_TTS_CURSOR_HOOKS", "{}"),
    "__CC_TTS_PRETOOLUSE_TTS__": os.environ.get("CC_TTS_PRETOOLUSE_TTS", ""),
    "__CC_TTS_INPUT_HOOKS__": os.environ.get("CC_TTS_INPUT_HOOKS", ""),
}
for k, v in repl.items():
    text = text.replace(k, v)
sys.stdout.write(text)
PY
      else
        # No sed fallback: it cannot substitute the multi-line __CC_TTS_*__
        # tokens (renders broken JSON) and | as delimiter breaks on two-modifier
        # leaders like CTRL|SHIFT. python3 ships with WSL Ubuntu — require it.
        echo "sync-windows: python3 is required to render $rel — install python3 and re-run." >&2
        exit 1
      fi
      effective_src="$rendered"
    else
      rel_out="$rel"
      effective_src="$src"
    fi

    dst="$dst_root/$rel_out"
    if [ "$is_modifier" = 1 ]; then
      modified="$(mktemp)"
      if [ -f "$dst" ]; then
        python3 "$effective_src" < "$dst" > "$modified"
      else
        python3 "$effective_src" < /dev/null > "$modified"
      fi
      effective_src="$modified"
    fi

    case "$dst" in
      "$dst_home/.claude/settings.json")
        merge_part_owned _merge_claude_settings.ps1 \
          terminal-stack-claude-settings.json "$effective_src" "$dst"
        continue
        ;;
      "$dst_home/.cursor/hooks.json")
        merge_part_owned _merge_cursor_hooks.ps1 \
          terminal-stack-cursor-hooks.json "$effective_src" "$dst"
        continue
        ;;
    esac

    if [ -e "$dst" ]; then
      if cmp -s "$effective_src" "$dst"; then
        unchanged=$((unchanged + 1))
        continue
      fi
      bak="$dst.bak.$today"
      if [ -e "$bak" ]; then
        n=1
        while [ -e "$dst.bak.$today.$n" ]; do n=$((n + 1)); done
        bak="$dst.bak.$today.$n"
      fi
      cp -p -- "$dst" "$bak"
      cp -- "$effective_src" "$dst"
      updated=$((updated + 1))
      printf 'updated  %s  (backup: %s)\n' "$dst" "$bak"
      case "$dst" in "$dst_home/.wezterm"*) wezterm_cfg_changed=1 ;; esac
    else
      mkdir -p -- "$(dirname -- "$dst")"
      cp -- "$effective_src" "$dst"
      created=$((created + 1))
      printf 'created  %s\n' "$dst"
      case "$dst" in "$dst_home/.wezterm"*) wezterm_cfg_changed=1 ;; esac
    fi
    [ -z "$modified" ] || rm -f -- "$modified"
  done < <(find "$src_root" -type d -name __pycache__ -prune -o \
    -type f ! -name '*.pyc' ! -name '*.pyo' -print0)
}

sync_tree "$windows_src" "$dst_home" 1
sync_tree "$codex_src" "$dst_home/.codex" 1
sync_tree "$kb_src" "$dst_home/AppData/Local/terminal-stack/docs/kb" 0

# Render ~/.claude/tts/config.json on the Windows side from chezmoi [data] (same as WSL apply).
# Idempotent + backed up, matching sync_tree's discipline: render to a temp file,
# skip when identical, back up as .bak.YYYYMMDD[.N] before overwriting.
if cz="$(resolve_cz)" && [ -f "$stack_root/dot_claude/tts/config.json.tmpl" ]; then
  tts_dst="$dst_home/.claude/tts/config.json"
  mkdir -p "$(dirname "$tts_dst")"
  if "$cz" execute-template "$(cat "$stack_root/dot_claude/tts/config.json.tmpl")" > "$rendered" 2>/dev/null; then
    if [ -e "$tts_dst" ] && cmp -s "$rendered" "$tts_dst"; then
      : # unchanged
    else
      if [ -e "$tts_dst" ]; then
        bak="$tts_dst.bak.$today"
        if [ -e "$bak" ]; then
          n=1
          while [ -e "$tts_dst.bak.$today.$n" ]; do n=$((n + 1)); done
          bak="$tts_dst.bak.$today.$n"
        fi
        cp -p -- "$tts_dst" "$bak"
      fi
      cp -- "$rendered" "$tts_dst"
      printf 'updated  %s  (chezmoi tts config)\n' "$tts_dst"
    fi
  fi
fi

merge_helper="$stack_root/bootstrap/_merge_cursor_settings.ps1"
if [ -f "$merge_helper" ]; then
  pwsh_exe="$(resolve_pwsh || true)"
  if [ -n "$pwsh_exe" ]; then
    # pwsh.exe is a Windows binary: WSL interop does not translate argument paths, so the
    # POSIX $merge_helper must be converted. -ExecutionPolicy Bypass matches every other
    # pwsh call in this file and is required because the script resolves over a
    # \\wsl.localhost UNC path, which PowerShell treats as remote (RemoteSigned blocks it).
    merge_helper_win="$(wslpath -w "$merge_helper" 2>/dev/null || printf '%s' "$merge_helper")"
    if ! "$pwsh_exe" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$merge_helper_win"; then
      echo "sync-windows: Cursor settings merge failed (non-fatal)." >&2
    fi
  else
    echo "sync-windows: pwsh not found; skipping Cursor settings merge." >&2
  fi
fi

# Enabled user-global coding-agent integrations are reconciled on update. The
# adapter runs on Windows because that is where the GUI agents and their user
# configuration live on a combined host.
agents_script="$stack_root/bootstrap/ts-agents.ps1"
agents_pwsh="$(resolve_pwsh || true)"
if [ -f "$agents_script" ] && [ -n "$agents_pwsh" ]; then
  agents_script_win="$(wslpath -w "$agents_script" 2>/dev/null || printf '%s' "$agents_script")"
  if [ "$HEADROOM_ENABLED" = on ] && ! "$agents_pwsh" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$agents_script_win" -Tool headroom -Action status -CursorMode "$HEADROOM_CURSOR_MODE" >/dev/null 2>&1; then
    "$agents_pwsh" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$agents_script_win" -Tool headroom -Action repair -CursorMode "$HEADROOM_CURSOR_MODE" \
      || echo "sync-windows: Headroom reconciliation failed (non-fatal)." >&2
  fi
  if [ "$CAVEMAN_ENABLED" = on ] && ! "$agents_pwsh" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$agents_script_win" -Tool caveman -Action status >/dev/null 2>&1; then
    "$agents_pwsh" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$agents_script_win" -Tool caveman -Action repair \
      || echo "sync-windows: Caveman reconciliation failed (non-fatal)." >&2
  fi
fi

# agentmemory harness wiring. The hook scripts live in vendor plugin caches, so a plugin
# upgrade silently reverts every edit and retrieval stops with nothing to show for it.
# Re-applying here is what makes that self-repairing rather than a manual step nobody
# remembers. -Check first, so a correctly-wired machine stays silent; the script also
# no-ops per host when agentmemory is not installed there.
am_script="$stack_root/bootstrap/ts-agentmemory.ps1"
if [ "$AGENTMEMORY_ENABLED" = on ] && [ -f "$am_script" ]; then
  am_pwsh="$(resolve_pwsh || true)"
  if [ -n "$am_pwsh" ]; then
    am_script_win="$(wslpath -w "$am_script" 2>/dev/null || printf '%s' "$am_script")"
    if ! "$am_pwsh" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$am_script_win" -Check >/dev/null 2>&1; then
      echo "sync-windows: repairing agentmemory hook wiring"
      "$am_pwsh" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$am_script_win" -Apply \
        || echo "sync-windows: agentmemory hook wiring failed (non-fatal)." >&2
    fi
  else
    echo "sync-windows: pwsh not found; skipping agentmemory hook wiring." >&2
  fi
fi

printf 'sync-windows: user=%s, %d created, %d updated, %d unchanged\n' "$WIN_USER" "$created" "$updated" "$unchanged"

# The mux server (unix domain 'main') loads its own copy of .wezterm.lua and is
# never restarted automatically — that would kill every live pane. Remind instead,
# and only when the mux is actually the thing hosting panes.
if [ "$wezterm_cfg_changed" = 1 ] && [ "$WEZ_MUX" = on ]; then
  echo "sync-windows: WezTerm config changed. The GUI reloads live, but wezterm-mux-server keeps the old config for spawning panes." >&2
  echo "  When convenient (closes all panes!): 'ts-mux restart'." >&2
fi
