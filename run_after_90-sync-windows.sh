#!/usr/bin/env bash
# Sync from the chezmoi source tree to the Windows user profile:
#   $CHEZMOI_SOURCE_DIR/windows/**  → /mnt/c/Users/<windowsUsername>/
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
#   __CC_TTS_STOP_HOOK__ / __CC_TTS_STOPFAILURE_HOOK__ / __CC_TTS_CURSOR_HOOKS__ /
#   __CC_TTS_PRETOOLUSE_TTS__ / __CC_TTS_INPUT_HOOKS__  optional cc-speak hooks (when ccTtsEnabled)
#
# Idempotent: only writes targets whose content differs.
# Backs up any pre-existing target to <path>.bak.YYYYMMDD[.N] before overwrite.
set -euo pipefail

stack_root="${CHEZMOI_SOURCE_DIR:-$HOME/.local/share/chezmoi}"
windows_src="$stack_root/windows"
kb_src="$stack_root/docs/kb"

# Non-WSL / no Windows mount available — no destination to sync to. Bail before
# we try to resolve a Windows username we can't possibly find. Native Linux and
# macOS land here.
if [ ! -d /mnt/c/Users ]; then
  exit 0
fi

if [ ! -d "$windows_src" ] && [ ! -d "$kb_src" ]; then
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
CC_TTS_ENABLED="$(cfg ccTtsEnabled false)"
if [ "$CC_TTS_ENABLED" = true ]; then
  CC_TTS_STOP_HOOK=$',
          {
            "type": "command",
            "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.claude/hooks/cc-speak.ps1 -State waiting"
          }'
  CC_TTS_STOPFAILURE_HOOK=$',
          {
            "type": "command",
            "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.claude/hooks/cc-speak.ps1 -State error"
          }'
  CC_TTS_CURSOR_HOOKS='{
    "afterFileEdit": [
      {
        "command": "cat > /dev/null",
        "timeout": 1
      }
    ],
    "stop": [
      {
        "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.cursor/hooks/cursor-tts.ps1",
        "timeout": 15
      }
    ],
    "postToolUse": [
      {
        "matcher": "AskQuestion|AskUserQuestion",
        "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.cursor/hooks/cursor-tts-input.ps1",
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
            "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.claude/hooks/cc-speak-input.ps1 -Event question"
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
            "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.claude/hooks/cc-speak-input.ps1 -Event notification"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/'"$WIN_USER"'/.claude/hooks/cc-speak-input.ps1 -Event permission"
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

today="$(date +%Y%m%d)"
created=0
updated=0
unchanged=0
wezterm_cfg_changed=0

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

# sync_tree <src_root> <dst_root> <render_tmpl:0|1>
sync_tree() {
  local src_root="$1" dst_root="$2" render_tmpl="${3:-0}"
  local src rel rel_out effective_src dst bak n

  [ -d "$src_root" ] || return 0

  while IFS= read -r -d '' src; do
    rel="${src#"$src_root"/}"

    if [ "$render_tmpl" = 1 ] && [[ "$rel" == *.tmpl ]]; then
      rel_out="${rel%.tmpl}"
      if command -v python3 >/dev/null 2>&1; then
        WIN_USER="$WIN_USER" LEADER_KEY="$LEADER_KEY" LEADER_MODS="$LEADER_MODS" \
        THEME_MODE="$THEME_MODE" THEME_RESOLVED="$THEME_RESOLVED" TMUX_PREFIX="$TMUX_PREFIX" \
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
  done < <(find "$src_root" -type f -print0)
}

sync_tree "$windows_src" "$dst_home" 1
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
  pwsh_exe=""
  for p in /mnt/c/Program\ Files/PowerShell/7/pwsh.exe \
           /mnt/c/Program\ Files/PowerShell/7-preview/pwsh.exe; do
    if [ -x "$p" ]; then pwsh_exe="$p"; break; fi
  done
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

printf 'sync-windows: user=%s, %d created, %d updated, %d unchanged\n' "$WIN_USER" "$created" "$updated" "$unchanged"

# The mux server (unix domain 'main') loads its own copy of .wezterm.lua and is
# never restarted automatically — that would kill every live pane. Remind instead.
if [ "$wezterm_cfg_changed" = 1 ]; then
  echo "sync-windows: WezTerm config changed. The GUI reloads live, but wezterm-mux-server keeps the old config for spawning panes." >&2
  echo "  When convenient (closes all panes!): close WezTerm, then 'taskkill /IM wezterm-mux-server.exe /F' and relaunch." >&2
fi
