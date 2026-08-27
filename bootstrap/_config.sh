#!/usr/bin/env bash
# _config.sh — terminal-stack configuration store (POSIX/Debian/macOS side).
# Sourced by the bootstraps, the wizard, and (indirectly) ts-config.
#
# Source of truth on this side is chezmoi [data] in ~/.config/chezmoi/chezmoi.toml.
# We store the RAW choices (leaderChord, themeMode, tmuxPrefix, resolvedTheme,
# weztermMux, weztermRestore, apps) and let .chezmoi.toml.tmpl derive the
# concrete bindings (leaderKey/leaderMods/tmuxPrefixResolved) on `chezmoi init`.
# resolvedTheme needs live OS detection, so it is computed here and stored.
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.

# Log colors — the bootstraps define these before sourcing us, but ts-config and
# the doctor source this file standalone, so provide a fallback.
: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

# shellcheck source=_cc_tts.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_cc_tts.sh"
# shellcheck source=_wezterm.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_wezterm.sh"

# ── App catalog ────────────────────────────────────────────────────────────────
# Toggleable apps the wizard/picker offers. Required prerequisites (zsh, git,
# curl, unzip, fontconfig, the Nerd Font, Starship, chezmoi) are always installed
# by the common_* steps and are NOT listed here.
#   TS_APPS_RECOMMENDED — pre-checked in the picker / installed by "recommended".
#   TS_APPS_OPTIONAL    — unchecked by default (GUI editor, GPU/docker tools,
#                         the agent CLIs — nothing here is installed unasked).
TS_APPS_RECOMMENDED="tmux eza fzf bat fd tree delta ripgrep zoxide atuin glow micro neovim gh ghq lazygit duf ncdu dust btop fnm python uv pipx ruff ipython claude codex cursor-agent grok gemini pi"
TS_APPS_OPTIONAL="zed tldr yazi nvtop lazydocker gdu bottom glances bandwhich gping rclone node httpie poetry pre-commit"
TS_APPS_ALL="$TS_APPS_RECOMMENDED $TS_APPS_OPTIONAL"

# Groups exist for the picker only — the saved `apps` array stays flat, so this
# adds no chezmoi [data] key and none of the 7-step blast radius that comes with
# one (CLAUDE.md, docs/decisions.md §§ at :236 and :325). Every catalog id must
# appear in exactly one group or it is unreachable from the group picker; a test
# asserts the union equals TS_APPS_ALL.
TS_APP_GROUPS="shell search disk system network git editors runtimes python ai"
ts_app_group_desc() {
    case "$1" in
        shell)   echo "shell essentials" ;;
        search)  echo "search and find" ;;
        disk)    echo "disk usage" ;;
        system)  echo "system monitors" ;;
        network) echo "network" ;;
        git)     echo "git tooling" ;;
        editors) echo "editors and readers" ;;
        runtimes) echo "language runtimes" ;;
        python)  echo "Python tooling" ;;
        ai)      echo "AI coding agents" ;;
        *)       echo "" ;;
    esac
}
ts_app_group_members() {
    case "$1" in
        shell)   echo "tmux eza bat tree zoxide fzf atuin" ;;
        search)  echo "ripgrep fd" ;;
        disk)    echo "duf ncdu dust gdu" ;;
        system)  echo "btop bottom glances nvtop lazydocker" ;;
        network) echo "bandwhich gping rclone" ;;
        git)     echo "delta gh ghq lazygit" ;;
        editors) echo "micro neovim glow zed tldr yazi" ;;
        runtimes) echo "fnm node" ;;
        python)  echo "python uv pipx ruff ipython httpie poetry pre-commit" ;;
        ai)      echo "claude codex cursor-agent grok gemini pi" ;;
        *)       echo "" ;;
    esac
}
# The group an id belongs to (empty when uncategorised).
ts_app_group_of() {
    local g
    for g in $TS_APP_GROUPS; do
        case " $(ts_app_group_members "$g") " in *" $1 "*) echo "$g"; return 0 ;; esac
    done
    echo ""
}

# Human-readable one-liners for the picker.
ts_app_desc() {
    case "$1" in
        tmux)       echo "terminal multiplexer (ssht, persistent sessions)";;
        eza)        echo "modern ls (icons, git status)";;
        fzf)        echo "fuzzy finder (Ctrl+R, Ctrl+T)";;
        bat)        echo "cat with syntax highlighting";;
        delta)      echo "git diff pager";;
        ripgrep)    echo "fast recursive grep (rg)";;
        zoxide)     echo "smarter cd (z)";;
        atuin)      echo "SQLite shell history, better Ctrl+R (opt-in)";;
        glow)       echo "terminal markdown renderer";;
        micro)      echo "nano-like terminal editor";;
        neovim)     echo "neovim editor (nvim)";;
        gh)         echo "GitHub CLI (org enumeration for wso)";;
        ghq)        echo "clone into the derived workspace path";;
        lazygit)    echo "git TUI (the wso status hand-off)";;
        zed)        echo "Zed GUI editor";;
        tldr)       echo "concise command examples";;
        yazi)       echo "terminal file manager (y to cd on exit)";;
        nvtop)      echo "GPU process monitor (NVIDIA hosts)";;
        lazydocker) echo "docker TUI (docker hosts)";;
        fd)         echo "fast, friendly find (the WezTerm sessionizer needs it)";;
        tree)       echo "directory tree as text";;
        duf)        echo "modern df — colourful disk free";;
        ncdu)       echo "interactive disk usage TUI";;
        dust)       echo "du with a tree view, sorted by size";;
        gdu)        echo "very fast disk usage TUI (ncdu alternative)";;
        btop)       echo "resource monitor (CPU, memory, disk, net, procs)";;
        bottom)     echo "alternative system monitor (btm)";;
        glances)    echo "cross-platform system monitor";;
        bandwhich)  echo "which process is using the bandwidth";;
        gping)      echo "ping with a live graph";;
        rclone)     echo "sync/mount 70+ storage backends, SMB shares included (ts-smb)";;
        claude)     echo "Claude Code CLI (cc/ccd wrappers drive it)";;
        codex)      echo "OpenAI Codex CLI (cx/cy wrappers drive it)";;
        cursor-agent) echo "Cursor's CLI agent";;
        grok)       echo "xAI Grok CLI (standalone binary; no Node needed)";;
        gemini)     echo "Google Gemini CLI";;
        pi)         echo "Pi coding agent (earendil-works; needs Node 22+)";;
        fnm)        echo "fast Node version manager (reads .nvmrc; ~10ms shell cost)";;
        node)       echo "Node.js itself, without a version manager";;
        python)     echo "Python 3 interpreter";;
        uv)         echo "fast Python package/project manager";;
        pipx)       echo "install Python CLI tools in isolated envs";;
        ruff)       echo "Python linter + formatter, one fast binary";;
        ipython)    echo "a far better Python REPL";;
        httpie)     echo "friendly HTTP client (readable curl)";;
        poetry)     echo "Python project/dependency manager";;
        pre-commit) echo "run git hooks before every commit";;
        *)          echo "";;
    esac
}

# The binary an app id actually puts on PATH. Mostly identity; a few differ.
ts_app_bin() {
    case "$1" in
        ripgrep) echo rg ;;
        neovim)  echo nvim ;;
        bottom)  echo btm ;;
        python)  echo python3 ;;
        # pre-commit's binary keeps the hyphen; listed for the reader, not a change.
        pre-commit) echo pre-commit ;;
        # Homebrew installs the gdu disk-usage TUI as `gdu-go` when coreutils is
        # present, because GNU coreutils already ships a `gdu` (its g-prefixed
        # du). Resolve to whichever is really there rather than reporting GNU du
        # as if it were the TUI — and deliberately DON'T shadow coreutils' gdu
        # with a symlink the way batcat/fdfind are handled: that name was theirs
        # first and may well be in use.
        gdu)     if command -v gdu-go >/dev/null 2>&1; then echo gdu-go; else echo gdu; fi ;;
        *)       echo "$1" ;;
    esac
}

# The agent CLIs do not come from a package manager, so they are installed by
# ts_install_ai_cli rather than brew/apt/winget. Kept out of the package-manager
# paths on purpose: a curl-pipe installer that fails must not look like an apt
# failure, and none of them belong in TS_APPS_RECOMMENDED.
ts_app_is_ai() {
    case " $(ts_app_group_members ai) " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# Apps this machine is expected to have but doesn't. Two sources, deliberately:
# the user's saved selection (an install that failed or a tool later removed),
# AND anything since added to TS_APPS_RECOMMENDED. The second half is the point —
# a machine configured before a tool joined the catalog would otherwise never
# get it however many times ts-update ran, which is exactly how gh/ghq/lazygit
# would have missed every existing install.
# Global npm binaries live under whatever Node fnm has active, and fnm's PATH
# entry is created per-shell — so a bash subshell (which is how ts-update calls
# this) cannot see codex/gemini and would nag about them forever. Load fnm's env
# first when it is available.
ts_load_node_env() {
    command -v fnm >/dev/null 2>&1 || return 0
    case ":$PATH:" in *:*fnm_multishells*:*) return 0 ;; esac
    eval "$(fnm env 2>/dev/null)" 2>/dev/null || true
}

# Can this platform actually install <id>? Returns 1 for ids that are real
# catalog entries but impossible here, so they are never offered and never nag.
# The Windows side has always done this ("Only offer what this platform can
# actually install" in Get-TsAppsPending); POSIX did not, so a macOS user who
# picked "install everything" was told nvtop was missing on every single
# ts-update, accepted, and watched it print "Linux-only; skipping" forever.
ts_app_installable() {
    case "$(uname -s 2>/dev/null)" in
        Darwin)
            case "$1" in
                nvtop) return 1 ;;   # NVIDIA/Linux only; no macOS build exists
            esac ;;
    esac
    return 0
}

ts_apps_pending() {
    local saved id seen="" out=""
    ts_load_node_env
    saved="$(ts_data_get_apps 2>/dev/null || true)"
    for id in $saved $TS_APPS_RECOMMENDED; do
        case " $seen " in *" $id "*) continue ;; esac
        seen="$seen $id"
        command -v "$(ts_app_bin "$id")" >/dev/null 2>&1 && continue
        ts_app_installable "$id" || continue
        out="$out $id"
    done
    echo "${out# }"
}

# Shown in the apps wizard when optional installs may need elevation.
ts_apps_install_note() {
    if command -v apt-get >/dev/null 2>&1; then
        printf '  Optional apps install via sudo apt (and may add PPAs). Your user must be able to run sudo.\n\n'
    elif [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        printf '  Optional apps install via Homebrew (user-space; no sudo for formulae).\n\n'
    fi
}

# ── Service readiness probes ───────────────────────────────────────────────────
# The wizard used to offer Headroom and AgentMemory as blind on/off questions and
# happily wire a machine to a service that was not running — the failure then
# showed up much later as an agent that silently retrieved nothing. These probe
# first, so the question can default sensibly and say what it found.
#
# "Answering" is the test, NOT a 2xx. AgentMemory returns 404 on `/` and 401 on
# `/agentmemory/health`; both prove a server is listening and speaking HTTP.
# `curl -fsS` treats either as failure, which is why `ts-agents agentmemory
# status` reported the service down while it was up and serving.

# ts_timeout <seconds> <cmd> [args...] — bound a command that might never return.
# macOS has no timeout(1); brew coreutils supplies gtimeout, and NEITHER is
# guaranteed. Without the watchdog fallback a check that merely wants a time
# bound becomes a hard 127 on a stock Mac, which is worse than the hang it was
# guarding against. `ts_smb_timeout` delegates here; do not fork a second copy.
ts_timeout() {
    local secs="$1"; shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$secs" "$@"
        return $?
    fi
    if command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$secs" "$@"
        return $?
    fi
    "$@" &
    local pid=$! rc=0
    ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null || true ) 2>/dev/null &
    local watchdog=$!
    wait "$pid" 2>/dev/null || rc=$?
    kill -TERM "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    return "$rc"
}

# ts_probe_http <url> [timeout] — 0 if anything answered, 1 if nothing did.
ts_probe_http() {
    local url="$1" t="${2:-2}" code
    command -v curl >/dev/null 2>&1 || return 1
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$t" "$url" 2>/dev/null || true)"
    case "$code" in ''|000) return 1 ;; *) return 0 ;; esac
}

# ts_probe_http_ok <url> [timeout] — stricter: only 2xx counts. For endpoints
# that are genuinely readiness checks, like Headroom's /readyz.
ts_probe_http_ok() {
    local url="$1" t="${2:-2}" code
    command -v curl >/dev/null 2>&1 || return 1
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$t" "$url" 2>/dev/null || true)"
    case "$code" in 2??) return 0 ;; *) return 1 ;; esac
}

# ts_docker_ports <name-substring> — published host ports for a running
# container, so a "not reachable" warning can say what IS listening instead of
# just repeating the port we expected.
ts_docker_ports() {
    command -v docker >/dev/null 2>&1 || return 1
    docker ps --filter "name=$1" --format '{{.Names}} {{.Ports}}' 2>/dev/null | head -3
}

# ts_probe_headroom — 0 when the proxy is ready. Echoes a human summary.
# MCP runs on demand through Docker stdio; ts-agents performs the real JSON-RPC
# initialize probe before it writes any client registration.
# The absorbed compose stacks live at <clone>/services/stacks/<name>/. Resolved
# from the clone — $TERMINAL_STACK_DIR, else chezmoi's source path — because that
# is the only answer that also works from the runtime clone, which is not under
# the workspace at all.
ts_stack_env_file() {                      # <stack> -> <clone>/services/stacks/<stack>/.env
    local src="${TERMINAL_STACK_DIR:-}"
    if [ -z "$src" ] && command -v chezmoi >/dev/null 2>&1; then
        src="$(chezmoi source-path 2>/dev/null || true)"
    fi
    [ -n "$src" ] || return 1
    printf '%s' "$src/services/stacks/$1/.env"
}

# One KEY=value out of a .env, without sourcing it: these files are compose's,
# not the shell's, and sourcing one would execute whatever is in it.
ts_env_value() {                           # <file> <key>
    [ -r "$1" ] || return 1
    sed -n "s/^$2=//p" "$1" | head -1
}

ts_probe_headroom() {
    local proxy="${1:-http://127.0.0.1:8787}" rc=1 token="" file="" root
    token="${HEADROOM_PROXY_TOKEN:-}"
    if [ -z "$token" ]; then
        # One rule everywhere: the stack tree is <clone>/services/. ts_stack_env_file
        # resolves it from the clone, never by walking the workspace for a sibling repo.
        file="${HEADROOM_ENV_FILE:-$(ts_stack_env_file headroom)}"
        [ -r "$file" ] && token="$(sed -n 's/^HEADROOM_PROXY_TOKEN=//p' "$file" | head -1)"
    fi
    if [ -n "$token" ] && curl -fsS --max-time 2 -H "X-Headroom-Proxy-Token: $token" "$proxy/stats" >/dev/null 2>&1; then
        printf '  Proxy:  authenticated at %s\n' "$proxy"
        rc=0
    else
        printf '  Proxy:  NOT usable at %s (unreachable, missing token, or unauthorized)\n' "$proxy"
        local seen; seen="$(ts_docker_ports headroom 2>/dev/null || true)"
        [ -n "$seen" ] && printf '          docker shows: %s\n' "$(printf '%s' "$seen" | tr '\n' ';')"
    fi
    printf '  MCP: Docker stdio; initialize is verified during headroom repair/status\n'
}

# ts_probe_agentmemory — 0 when the REST service answers at all.
ts_probe_agentmemory() {
    local rest="${1:-http://127.0.0.1:3111}" rc=1
    if ts_probe_http "$rest"; then
        printf '  Service: reachable at %s\n' "$rest"
        rc=0
    else
        printf '  Service: NOT reachable at %s\n' "$rest"
        local seen; seen="$(ts_docker_ports agentmemory 2>/dev/null || true)"
        [ -n "$seen" ] && printf '           docker shows: %s\n' "$(printf '%s' "$seen" | tr '\n' ';')"
    fi
    # The hook wiring is gated on the plugin cache, not on reachability, so a
    # missing cache is worth saying: enabling installs it, it is not an error.
    if [ -d "$HOME/.claude/plugins/cache/agentmemory" ] \
       || [ -d "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentmemory" ]; then
        printf '  Plugin:  installed\n'
    else
        printf '  Plugin:  not installed yet — turning this on installs it\n'
    fi
    return $rc
}

# ── Optional-install failure collection ────────────────────────────────────────
# NOTHING optional may ever be fatal. The bootstraps run under `set -euo
# pipefail`, and `set -e` exempts only the NON-final members of an && / || list:
#
#     brew list --cask zed >/dev/null 2>&1 || brew install --cask zed
#
# looks guarded and is not — the install is the final command, so its failure
# kills the whole script. That one line (a hand-installed /Applications/Zed.app
# that Homebrew did not know about) aborted a real install at line 55 of 207,
# taking every terminal, oh-my-zsh, chsh, chezmoi.toml and — worst — the entire
# persistence of the user's wizard answers with it, silently.
#
# So: every optional install ends in `|| ts_note_failure`, and the run reports
# what failed at the end instead of dying. This is the Windows path's existing
# discipline (windows-bootstrap.ps1 uses Install-WingetPackage "so a failure
# lands in the end-of-run report"); these two helpers bring POSIX into line.
TS_INSTALL_FAILURES=""

# ts_note_failure <what> [hint] — record and warn, never abort.
ts_note_failure() {
    local what="$1" hint="${2:-}"
    TS_INSTALL_FAILURES="${TS_INSTALL_FAILURES}${what}|${hint}
"
    echo "!! ${what} failed${hint:+ — $hint}" >&2
    return 0
}

# ts_report_failures — end-of-run summary. Returns 0 always: a report is not a
# failure, and the caller has already done everything it could.
ts_report_failures() {
    [ -n "$TS_INSTALL_FAILURES" ] || return 0
    echo
    echo "==> Some optional steps did not complete:"
    printf '%s' "$TS_INSTALL_FAILURES" | while IFS='|' read -r what hint; do
        [ -n "$what" ] || continue
        printf '    %-28s %s\n' "$what" "$hint"
    done
    echo "    Everything else was applied. Re-run the installer or the named"
    echo "    command to retry just these."
    return 0
}

# Install the selected toggleable apps via Homebrew (macOS). Idempotent: brew
# skips already-installed formulae. Debian/WSL uses common_install_selected_apps
# in _common-debian.sh instead (it needs the bespoke glow/neovim/… installers).
ts_brew_install_apps() {
    command -v brew >/dev/null 2>&1 || { echo "ts: brew not found; cannot install apps"; return 1; }
    local apps="$*"
    if [ -z "$apps" ]; then
        echo "==> No optional apps selected; skipping app install"
        return 0
    fi
    echo "==> Installing selected apps: $apps"
    local formulae="" id
    for id in $apps; do
        case "$id" in
            tmux)       formulae="$formulae tmux" ;;
            eza)        formulae="$formulae eza" ;;
            zoxide)     formulae="$formulae zoxide" ;;
            atuin)      formulae="$formulae atuin" ;;
            yazi)       formulae="$formulae yazi" ;;
            fzf)        formulae="$formulae fzf" ;;
            bat)        formulae="$formulae bat" ;;
            delta)      formulae="$formulae git-delta" ;;
            ripgrep)    formulae="$formulae ripgrep" ;;
            micro)      formulae="$formulae micro" ;;
            glow)       formulae="$formulae glow" ;;
            neovim)     formulae="$formulae neovim" ;;
            gh)         formulae="$formulae gh" ;;
            ghq)        formulae="$formulae ghq" ;;
            lazygit)    formulae="$formulae lazygit" ;;
            tldr)       formulae="$formulae tldr" ;;
            lazydocker) formulae="$formulae lazydocker" ;;
            fd)         formulae="$formulae fd" ;;
            tree)       formulae="$formulae tree" ;;
            duf)        formulae="$formulae duf" ;;
            ncdu)       formulae="$formulae ncdu" ;;
            dust)       formulae="$formulae dust" ;;
            gdu)        formulae="$formulae gdu" ;;
            btop)       formulae="$formulae btop" ;;
            bottom)     formulae="$formulae bottom" ;;
            glances)    formulae="$formulae glances" ;;
            bandwhich)  formulae="$formulae bandwhich" ;;
            gping)      formulae="$formulae gping" ;;
            rclone)     formulae="$formulae rclone" ;;
            fnm)        formulae="$formulae fnm" ;;
            node)       formulae="$formulae node" ;;
            python)     formulae="$formulae python@3.14" ;;
            uv)         formulae="$formulae uv" ;;
            pipx)       formulae="$formulae pipx" ;;
            ruff)       formulae="$formulae ruff" ;;
            ipython)    formulae="$formulae ipython" ;;
            httpie)     formulae="$formulae httpie" ;;
            poetry)     formulae="$formulae poetry" ;;
            pre-commit) formulae="$formulae pre-commit" ;;
            nvtop)      echo "==> nvtop is Linux-only; skipping on macOS" ;;
            # zed IS mapped — as a cask, handled below. Without this arm the
            # catch-all printed "no macOS package mapping; skipped" and then
            # installed it twelve lines later, so the transcript blamed the
            # wrong thing when the cask was what actually failed.
            zed)        ;;
            *)          ts_app_is_ai "$id" || echo "==> $id: no macOS package mapping; skipped" ;;
        esac
    done
    # `brew install $formulae` is the final command of the old `[ -n … ] && …`
    # list, so one bad bottle killed the bootstrap the same way zed did. An `if`
    # puts it in statement position where the `||` actually guards it.
    if [ -n "$formulae" ]; then
        # shellcheck disable=SC2086
        brew install $formulae || ts_note_failure "brew formulae" "retry: brew install$formulae"
    fi
    case " $apps " in *" zed "*)
        # Check the FILESYSTEM, not just Homebrew's registry. A Zed installed by
        # hand (or by zed.dev's own installer) leaves brew believing the cask is
        # absent, so a plain install collides with the existing bundle and errors
        # — which is the failure that aborted a whole bootstrap.
        #
        # A hand-placed app is not ours to replace, same rule as
        # ts_wezterm_install applies to a WezTerm outside a package manager.
        # `--cask --adopt` was tried and REJECTED: on a bundle whose xattrs brew
        # cannot rewrite it fails partway and REMOVES the app it was supposed to
        # adopt. Verified the hard way — it deleted a real /Applications/Zed.app.
        # Never adopt; never --force. Say it is there and move on.
        if brew list --cask zed >/dev/null 2>&1; then
            echo "==> zed: already installed"
        elif [ -d "${TS_ZED_APP:-/Applications/Zed.app}" ]; then
            echo "==> zed: already present at ${TS_ZED_APP:-/Applications/Zed.app} (installed outside Homebrew); leaving it alone."
        else
            brew install --cask zed || ts_note_failure "zed" "install it by hand later"
        fi ;;
    esac
    ts_install_node_lts "$apps" || ts_note_failure "Node LTS" "retry: ts-config apps node"
    ts_install_ai_clis "$apps"  || ts_note_failure "agent CLIs" "retry: ts-config apps claude,codex,…"
    return 0
}

# fnm installs the manager, not a runtime — without this, `node` still does not
# exist and every npm-based agent CLI below would decline. Idempotent: skipped
# when a Node is already current enough.
ts_install_node_lts() {
    case " $1 " in *" fnm "*) ;; *) return 0 ;; esac
    command -v fnm >/dev/null 2>&1 || return 0
    if [ "$(ts_node_major)" -ge 20 ] 2>/dev/null; then
        echo "==> node: $(node --version 2>/dev/null) already current"
        return 0
    fi
    echo "==> node: installing the current LTS via fnm"
    eval "$(fnm env 2>/dev/null)" || true
    fnm install --lts >/dev/null 2>&1 && fnm default lts-latest >/dev/null 2>&1 \
        || echo "!! fnm install --lts failed; run it by hand."
    eval "$(fnm env 2>/dev/null)" || true
    command -v node >/dev/null 2>&1 && echo "==> node: $(node --version)"
}

# ── Agent CLIs ─────────────────────────────────────────────────────────────────
# Not package-manager installs, so they get their own path. Each is idempotent
# (skips when already on PATH), never fatal, and only ever runs for an id the
# user actually ticked — every one of them lives in TS_APPS_OPTIONAL.
#
# Deliberately native installers and release binaries rather than npm: the Node
# on a machine is not the stack's to control (this was written on a Mac carrying
# node 10 from 2018, on which `npm` refuses to run at all), and @openai/codex
# needs Node 20+. Where npm really is the only channel, check the version and
# warn rather than fail.
ts_node_major() {
    command -v node >/dev/null 2>&1 || { echo 0; return; }
    node --version 2>/dev/null | sed -n 's/^v\([0-9][0-9]*\).*/\1/p' | head -1
}

ts_install_ai_cli() {
    local id="$1" bin
    bin="$(ts_app_bin "$id")"
    if command -v "$bin" >/dev/null 2>&1; then
        echo "==> $id: already installed ($(command -v "$bin"))"
        return 0
    fi
    case "$id" in
        claude)
            echo "==> claude: installing via the official installer"
            curl -fsSL https://claude.ai/install.sh | bash \
                || echo "!! claude install failed; see https://docs.claude.com/en/docs/claude-code" ;;
        cursor-agent)
            echo "==> cursor-agent: installing via the official installer"
            curl -fsS https://cursor.com/install | bash \
                || echo "!! cursor-agent install failed; see https://cursor.com/cli" ;;
        grok)
            # xAI ship a standalone binary, so this needs no Node at all. The
            # installer defaults to ~/.grok/bin and APPENDS a PATH line to
            # ~/.zshrc — which this stack owns whole-file, so chezmoi would wipe
            # it on the next apply. GROK_BIN_DIR puts the symlink somewhere
            # already on PATH and sidesteps that entirely.
            echo "==> grok: installing via the official installer"
            GROK_BIN_DIR="$HOME/.local/bin" bash -c \
                'curl -fsSL https://x.ai/cli/install.sh | bash' \
                || echo "!! grok install failed; see https://x.ai/build" ;;
        codex|gemini|pi)
            # npm-only. @openai/codex wants Node >= 16, @google/gemini-cli >= 20,
            # @earendil-works/pi-coding-agent >= 22.19 (engines field).
            local pkg want major
            case "$id" in
                codex)  pkg="@openai/codex";     want=16 ;;
                gemini) pkg="@google/gemini-cli"; want=20 ;;
                pi)     pkg="@earendil-works/pi-coding-agent"; want=22 ;;
            esac
            major="$(ts_node_major)"
            if [ "${major:-0}" -ge "$want" ] 2>/dev/null && command -v npm >/dev/null 2>&1; then
                echo "==> $id: installing $pkg via npm"
                npm install -g "$pkg" || echo "!! $id install failed."
            else
                # Deliberately no brew fallback for gemini: the `gemini-cli`
                # formula is deprecated upstream and scheduled for removal on
                # 2026-12-18, so installing from it would hand you a dead end.
                # Node is the supported path, and `fnm` in the runtimes group
                # is how you get one.
                echo "!! $id needs Node $want+ to install from npm (found: ${major:-none})."
                echo "   Install the runtime first: ts-config apps fnm   (then: fnm install --lts)"
            fi ;;
        *)
            echo "!! $id: no agent-CLI installer defined" ;;
    esac
}

ts_install_ai_clis() {
    local id
    for id in $1; do
        ts_app_is_ai "$id" && ts_install_ai_cli "$id"
    done
    return 0
}

# Print what each selected app resolved to, so a curl-pipe installer that failed
# quietly is visible rather than assumed.
ts_report_installed_apps() {
    local id bin path ver raw
    ts_load_node_env
    [ -z "${1:-}" ] && return 0
    echo
    echo "==> Installed tools:"
    for id in $1; do
        bin="$(ts_app_bin "$id")"
        if path="$(command -v "$bin" 2>/dev/null)"; then
            # Capture FIRST, then process. This used to be one four-stage
            # pipeline assigned directly, which under `set -euo pipefail` meant
            # any tool whose --version exits non-zero killed the whole function
            # — and with it `finish`, so `chezmoi apply` silently never ran.
            # tmux is exactly that tool (it wants -V and exits 1 on --version)
            # and it is FIRST in TS_APPS_RECOMMENDED, so the report died on
            # entry one every single time, printing only its own header.
            raw="$("$bin" --version 2>/dev/null || true)"
            [ -n "$raw" ] || raw="$("$bin" -V 2>/dev/null || true)"
            # Strip ANSI: btop and friends colour their own version output.
            ver="$(printf '%s\n' "$raw" | head -1 | sed $'s/\033\\[[0-9;]*m//g' | cut -c1-40 || true)"
            printf '    %-14s %s\n' "$id" "${ver:-$path}"
        elif ! ts_app_installable "$id"; then
            printf '    %-14s %s\n' "$id" "not available on this platform"
        else
            printf '    %-14s %s\n' "$id" "NOT FOUND on PATH"
        fi
    done
    echo "    (run 'exec zsh' to pick up shell integrations for newly installed tools)"
}

# ── chezmoi helpers ─────────────────────────────────────────────────────────────
ts_chezmoi_bin() {
    if [ -n "${TERMINAL_STACK_CHEZMOI:-}" ]; then echo "$TERMINAL_STACK_CHEZMOI"
    elif [ -x "$HOME/.local/bin/chezmoi" ]; then echo "$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then command -v chezmoi
    elif [ -x /usr/local/bin/chezmoi ]; then echo /usr/local/bin/chezmoi
    else return 1
    fi
}

ts_toml() { echo "${HOME}/.config/chezmoi/chezmoi.toml"; }

# The canonical runtime clone location (see docs/decisions.md § "Runtime clone
# location"). WSL shares ONE clone with Windows inside the app-data dir the
# stack already owns; native Linux/macOS use the XDG data home. Pins
# The Windows username for /mnt/c paths: chezmoi [data] first, then cmd.exe interop.
# The interop half is not optional. A clone installed before the bootstrap started
# recording windowsUsername has only that answer, and ts_mirror_windows_config used to
# resolve from [data] alone and `return 0` when it came back empty -- writing no mirror
# while reporting success. That is how the two config stores silently diverged: every
# WSL-side save updated chezmoi [data] and skipped the mirror, so the next pwsh sync
# rendered Windows-side files from stale values and, for ccTtsEnabled=false, removed every
# TTS hook. Same order as run_after_90-sync-windows.sh resolve_win_user and ts-mux.sh
# win_user.
ts_win_user() {
    local wu; wu="$(ts_data_get windowsUsername 2>/dev/null || true)"
    [ -n "$wu" ] && { printf '%s' "$wu"; return 0; }
    if [ -x /mnt/c/Windows/System32/cmd.exe ]; then
        wu="$(/mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true)"
        [ -n "$wu" ] && { printf '%s' "$wu"; return 0; }
    fi
    return 1
}

# (TERMINAL_STACK_DIR) are only for NON-canonical locations. Twins:
# dot_zshrc _ts_canonical_clone, profile/_cleanup.ps1 Get-TsCanonicalCloneDir.
ts_canonical_clone_dir() {
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        local wu=""
        wu="$(ts_win_user 2>/dev/null || true)"
        if [ -n "$wu" ]; then
            echo "/mnt/c/Users/$wu/AppData/Local/terminal-stack/stack"
            return 0
        fi
        # Last resort: a single existing match wins.
        local m matches=0 hit=""
        for m in /mnt/c/Users/*/AppData/Local/terminal-stack/stack; do
            [ -d "$m" ] || continue
            matches=$((matches + 1)); hit="$m"
        done
        [ "$matches" -eq 1 ] && { echo "$hit"; return 0; }
        return 1
    fi
    echo "${XDG_DATA_HOME:-$HOME/.local/share}/terminal-stack"
}

# Read the sourceDir currently recorded in chezmoi.toml (empty if unset/absent).
ts_source_dir_recorded() {
    local toml; toml="$(ts_toml)"
    [ -f "$toml" ] || return 0
    grep -E '^[[:space:]]*sourceDir[[:space:]]*=' "$toml" | head -n1 \
        | sed -E 's/^[[:space:]]*sourceDir[[:space:]]*=[[:space:]]*"?([^"]*)"?.*/\1/'
}

# Write/replace the sourceDir line in chezmoi.toml, preserving everything else
# (the [data] block, windowsUsername, …). Creates the file if missing.
ts_set_source_dir() {
    local dir="$1" toml tmp; toml="$(ts_toml)"
    mkdir -p "$(dirname "$toml")"
    if [ ! -f "$toml" ]; then printf 'sourceDir = "%s"\n' "$dir" > "$toml"; return 0; fi
    tmp="$(mktemp)"
    if grep -qE '^[[:space:]]*sourceDir[[:space:]]*=' "$toml"; then
        awk -v d="$dir" '/^[[:space:]]*sourceDir[[:space:]]*=/ {print "sourceDir = \"" d "\""; next} {print}' \
            "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
        { printf 'sourceDir = "%s"\n' "$dir"; cat "$toml"; } > "$tmp" && mv "$tmp" "$toml"
    fi
    rm -f "$tmp" 2>/dev/null || true
}

# Ensure chezmoi.toml's sourceDir points at <dir>. Creates the file if missing,
# repoints (preserving [data]) when it differs, no-ops when already correct.
# This is the fix for the "stale sourceDir on re-run" bug: a fresh clone at a new
# path was previously ignored because the bootstrap refused to touch an existing
# chezmoi.toml, so `chezmoi apply` kept deploying from the old clone.
ts_ensure_source_dir() {
    local dir="$1" cur; cur="$(ts_source_dir_recorded)"
    if [ -z "$cur" ]; then
        ts_set_source_dir "$dir"
        echo "$INFO chezmoi sourceDir set to $dir"
    elif [ "$cur" = "$dir" ]; then
        echo "$INFO chezmoi sourceDir already = $dir"
    else
        echo "$WARN chezmoi sourceDir was '$cur' — repointing to '$dir'"
        ts_set_source_dir "$dir"
    fi
}

# Set a scalar string key under [data], updating in place or appending.
# Uses awk + temp file (portable across GNU and BSD/macOS; no `sed -i`).
ts_data_set() {
    local key="$1" val="$2" toml tmp; toml="$(ts_toml)"
    [ -f "$toml" ] || { mkdir -p "$(dirname "$toml")"; printf '[data]\n' > "$toml"; }
    tmp="$(mktemp)"
    if grep -q "^$key = " "$toml"; then
        awk -v k="$key" -v v="$val" '$0 ~ "^"k" = " {print k" = \"" v "\""; next} {print}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    elif grep -q '^\[data\]' "$toml"; then
        awk -v k="$key" -v v="$val" '{print} /^\[data\]/ && !ins {print k" = \"" v "\""; ins=1}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
        printf '\n[data]\n%s = "%s"\n' "$key" "$val" >> "$toml"
    fi
    rm -f "$tmp" 2>/dev/null || true
}

# Set the apps array under [data].
ts_data_set_apps() {
    local toml tmp arr="" a; toml="$(ts_toml)"
    for a in "$@"; do arr="$arr${arr:+, }\"$a\""; done
    local line="apps = [$arr]"
    [ -f "$toml" ] || { mkdir -p "$(dirname "$toml")"; printf '[data]\n' > "$toml"; }
    tmp="$(mktemp)"
    if grep -q '^apps = ' "$toml"; then
        awk -v line="$line" '/^apps = / {print line; next} {print}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    elif grep -q '^\[data\]' "$toml"; then
        awk -v line="$line" '{print} /^\[data\]/ && !ins {print line; ins=1}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
        printf '\n[data]\n%s\n' "$line" >> "$toml"
    fi
    rm -f "$tmp" 2>/dev/null || true
}

# Read a derived/raw value through chezmoi (authoritative; reflects the template).
# Batched [data] read: one `chezmoi execute-template` for every key the Windows mirror
# needs. Writing that mirror made 49 separate spawns, which measured **229 seconds** on a
# combined host, because chezmoi re-reads its source state per invocation and the source
# dir lives on /mnt/c. Nobody noticed until the mirror actually started being written: the
# writer used to bail out early, so the cost was hidden behind a silent no-op.
#
# Values are framed as key=<<value>> so a value containing "=" survives. A key that is not
# prefetched still resolves, because ts_data_get falls back to its own spawn -- a missing
# entry here is only slow, never wrong. Values containing a newline are the one shape this
# cannot carry; every key below is a scalar.
TS_MIRROR_DATA_KEYS="
    ccTtsChatterboxCfgWeight ccTtsChatterboxEnergy ccTtsChatterboxTemperature 
    ccTtsChatterboxTimeout ccTtsChatterboxUrl ccTtsChatterboxVoice ccTtsDaemon 
    ccTtsDaemonPort ccTtsDebounceSec ccTtsDuckPercent ccTtsEdgeEnabled ccTtsEdgeVoice 
    ccTtsEnabled ccTtsEngine ccTtsEvents ccTtsExcitement ccTtsHaikuModel 
    ccTtsIncludeProject ccTtsKokoroFormat ccTtsKokoroSpeed ccTtsKokoroTimeout 
    ccTtsKokoroUrl ccTtsKokoroVoice ccTtsMaxChars ccTtsMessageMode ccTtsMusicMode 
    ccTtsOllamaModel ccTtsOllamaUrl ccTtsPlayer ccTtsPrefixClaude ccTtsPrefixClaudeEnabled 
    ccTtsPrefixCodex ccTtsPrefixCodexEnabled ccTtsPrefixCursor ccTtsPrefixCursorEnabled 
    ccTtsSummarizer ccTtsTemplateError ccTtsTemplatePermission ccTtsTemplateQuestion 
    ccTtsTemplateWaiting ccTtsVoicePool leaderChord tmuxPrefix windowsUsername
    weztermMux weztermRestore atuinEnabled headroomEnabled headroomCursorMode
    cavemanEnabled agentmemoryEnabled playwrightEnabled memoryBackend
"

ts_data_prefetch() {
    local cz tmpl="" k v line out
    cz="$(ts_chezmoi_bin)" || return 0
    for k in "$@"; do
        tmpl="${tmpl}${k}=<<{{ if hasKey . \"${k}\" }}{{ index . \"${k}\" }}{{ end }}>>
"
    done
    [ -n "$tmpl" ] || return 0
    out="$("$cz" execute-template "$tmpl" 2>/dev/null)" || return 0
    while IFS= read -r line; do
        case "$line" in *"=<<"*">>") ;; *) continue ;; esac
        k="${line%%=<<*}"
        case "$k" in ''|*[!A-Za-z0-9_]*) continue ;; esac
        v="${line#*=<<}"; v="${v%>>}"
        eval "TS_DATA_CACHE_${k}=\$v"
        eval "TS_DATA_CACHE_SET_${k}=1"
    done <<EOF
$out
EOF
}

ts_data_get() {
    # Prefetched value if there is one; the marker variable distinguishes "cached empty"
    # from "never fetched", which matters because plenty of these keys are legitimately "".
    local _hit=""
    eval "_hit=\${TS_DATA_CACHE_SET_${1}:-}"
    if [ -n "$_hit" ]; then
        eval "printf '%s' \"\$TS_DATA_CACHE_${1}\""
        return 0
    fi
    local cz; cz="$(ts_chezmoi_bin)" || return 1
    "$cz" execute-template "{{ if hasKey . \"$1\" }}{{ index . \"$1\" }}{{ end }}" 2>/dev/null
}

# Read the apps array as a space-separated list.
ts_data_get_apps() {
    local cz; cz="$(ts_chezmoi_bin)" || return 1
    "$cz" execute-template '{{ if hasKey . "apps" }}{{ range $i,$a := .apps }}{{ if $i }} {{ end }}{{ $a }}{{ end }}{{ end }}' 2>/dev/null
}

# Per-machine, user-global coding-agent integrations. Fresh machines default to
# off. AgentMemory alone migrates to on when its pre-toggle plugin wiring already
# exists, so an upgrade does not silently disable an established installation.
ts_agent_get() {
    local key="$1" env_name="" v=""
    case "$key" in
        headroomEnabled) env_name=TS_HEADROOM ;;
        headroomCursorMode) env_name=TS_HEADROOM_CURSOR ;;
        cavemanEnabled) env_name=TS_CAVEMAN ;;
        agentmemoryEnabled) env_name=TS_AGENTMEMORY ;;
        playwrightEnabled) env_name=TS_PLAYWRIGHT ;;
        memoryBackend) env_name=TS_MEMORY_BACKEND ;;
        *) echo "ts_agent_get: unknown key '$key'" >&2; return 2 ;;
    esac
    eval "v=\${$env_name:-}"
    [ -n "$v" ] || v="$(ts_data_get "$key" 2>/dev/null || true)"
    if [ -z "$v" ] && [ "$key" = headroomCursorMode ]; then v=mcp; fi
    # agentmemory is the default backend: it is what a machine with no answer
    # has effectively been running, since Headroom's memory needs a --memory the
    # compose file has never passed. A machine that upgrades into this key keeps
    # doing exactly what it was doing.
    if [ -z "$v" ] && [ "$key" = memoryBackend ]; then v=agentmemory; fi
    if [ -z "$v" ] && [ "$key" = agentmemoryEnabled ]; then
        if [ -d "$HOME/.claude/plugins/cache/agentmemory/agentmemory" ] \
            || [ -d "$HOME/.codex/plugins/cache/agentmemory/agentmemory" ]; then v=on; fi
        if [ -z "$v" ] && [ -d /mnt/c/Users ]; then
            local winuser=""; winuser="$(ts_win_user 2>/dev/null || true)"
            if [ -n "$winuser" ] && { [ -d "/mnt/c/Users/$winuser/.claude/plugins/cache/agentmemory/agentmemory" ] \
                || [ -d "/mnt/c/Users/$winuser/.codex/plugins/cache/agentmemory/agentmemory" ]; }; then v=on; fi
        fi
    fi
    [ -n "$v" ] || v=off
    printf '%s\n' "$(printf '%s' "$v" | tr 'A-Z' 'a-z')"
}

ts_agent_set() {
    local key="$1" value="$2"
    case "$key:$value" in
        headroomEnabled:on|headroomEnabled:off|cavemanEnabled:on|cavemanEnabled:off|agentmemoryEnabled:on|agentmemoryEnabled:off|headroomCursorMode:mcp|headroomCursorMode:byok|headroomCursorMode:off|playwrightEnabled:on|playwrightEnabled:off|memoryBackend:agentmemory|memoryBackend:headroom|memoryBackend:none) ;;
        *) echo "ts_agent_set: invalid $key=$value" >&2; return 2 ;;
    esac
    ts_data_set "$key" "$value"
    ts_mirror_windows_config
}

# ── the memory backend ───────────────────────────────────────────────────────
# AgentMemory or Headroom, never both. They do the same job, so running both
# gives you two half-filled stores and no way to know which one holds the answer
# you are looking for.
#
# This is the ONLY writer of agentmemoryEnabled. Anything that sets that key on
# its own can produce a combination the install wizard refuses to offer, which
# is how a "cannot happen" state happens.
#
# Three values:
#   agentmemory  AgentMemory remembers, Headroom compresses   (the default)
#   headroom     Headroom does both; AgentMemory is not installed
#   none         no memory at all
ts_memory_backend_get() { ts_agent_get memoryBackend; }

# The headroom stack's COMPOSE_FILE is derived, never hand-edited: Qdrant and
# Neo4j are only referenced -- and so only ever pulled -- when the overlay is
# selected, and the overlay is what passes --memory.
ts_memory_compose_spec() {                 # <backend> -> the COMPOSE_FILE value
    case "$1" in
        headroom) printf 'docker-compose.yml:docker-compose.memory.yml' ;;
        *)        printf 'docker-compose.yml' ;;
    esac
}

# Rewrite one key in a .env, in place, creating it if absent. sed -i is not
# portable (BSD wants an argument, GNU does not) and appends a newline to a file
# that lacked one, which the two script sets would then fight over.
ts_memory_write_compose_file() {           # <backend>
    local backend="$1" env_file spec tmp
    env_file="$(ts_stack_env_file headroom 2>/dev/null || true)"
    [ -n "$env_file" ] && [ -f "$env_file" ] || return 0
    spec="$(ts_memory_compose_spec "$backend")"
    tmp="$env_file.tmp.$$"
    awk -v spec="$spec" '
        /^COMPOSE_FILE=/            { print "COMPOSE_FILE=" spec; seen = 1; next }
        /^COMPOSE_PATH_SEPARATOR=/  { print; sep = 1; next }
        { print }
        END {
            if (!sep)  print "COMPOSE_PATH_SEPARATOR=:"
            if (!seen) print "COMPOSE_FILE=" spec
        }
    ' "$env_file" > "$tmp" && mv "$tmp" "$env_file"
}

ts_memory_apply() {                        # <agentmemory|headroom|none>
    local backend="$1"
    case "$backend" in
        agentmemory|headroom|none) ;;
        *) echo "ts_memory_apply: invalid backend '$backend'" >&2; return 2 ;;
    esac
    ts_agent_set memoryBackend "$backend" || return 1
    # Derived, in the same breath. A separate command to "also turn AgentMemory
    # off" is a command someone forgets to run.
    if [ "$backend" = agentmemory ]; then ts_agent_set agentmemoryEnabled on
    else                                  ts_agent_set agentmemoryEnabled off; fi
    ts_memory_write_compose_file "$backend"
}

# The agent toggles that are genuinely independent choices. agentmemoryEnabled is
# NOT among them: it is derived from memoryBackend, and ts_memory_apply is its
# only writer (see the comment above it). Every caller here follows this with
# ts_memory_apply, which is what actually records the wizard's memory answer --
# writing the derived key here and never the authoritative one is precisely how a
# machine ended up with agentmemoryEnabled=off next to memoryBackend=agentmemory,
# a combination the wizard cannot offer and ts-doctor reports as drift.
# The 4th positional argument is still accepted and ignored, so an out-of-tree
# caller does not silently start passing cursor mode into caveman.
ts_agents_save_config() {
    local headroom="${1:-off}" cursor="${2:-mcp}" caveman="${3:-off}"
    ts_data_set headroomEnabled "$headroom"
    ts_data_set headroomCursorMode "$cursor"
    ts_data_set cavemanEnabled "$caveman"
    ts_mirror_windows_config
}

ts_agents_apply_wizard() {
    local script="${1:-}"
    [ -f "$script" ] || return 0
    [ "${TS_WIZ_HEADROOM:-off}" = on ] && bash "$script" headroom on "${TS_WIZ_HEADROOM_CURSOR:-mcp}" || [ "${TS_WIZ_HEADROOM:-off}" != on ] || echo "$WARN Headroom client setup failed; retry: ts-config agents headroom repair" >&2
    [ "${TS_WIZ_CAVEMAN:-off}" = on ] && bash "$script" caveman on || [ "${TS_WIZ_CAVEMAN:-off}" != on ] || echo "$WARN Caveman setup failed; retry: ts-config agents caveman repair" >&2
    [ "${TS_WIZ_AGENTMEMORY:-off}" = on ] && bash "$script" agentmemory on || [ "${TS_WIZ_AGENTMEMORY:-off}" != on ] || echo "$WARN AgentMemory setup failed; retry: ts-config agents agentmemory repair" >&2
}

# ── WezTerm multiplexer domain ──────────────────────────────────────────────────
# "on"  → .wezterm.lua sets unix_domains = {{ name = 'main' }} + default_domain,
#         so panes live in wezterm-mux-server and survive a GUI crash.
# "off" → panes are spawned locally by the GUI (the default; see ts-mux -h for the
#         trade-offs). Stored on its own, not through ts_save_config, so the
#         ts-mux command can flip it without re-stating every other choice.
ts_wez_mux_get() {
    local v; v="$(ts_data_get weztermMux 2>/dev/null || true)"
    case "$v" in on|off) echo "$v" ;; *) echo off ;; esac
}

# ts_wez_mux_set <on|off> — persist, regenerate derived keys, mirror to Windows.
ts_wez_mux_set() {
    case "$1" in on|off) ;; *) echo "ts_wez_mux_set: expected on|off" >&2; return 2 ;; esac
    ts_data_set weztermMux "$1"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# ── WezTerm session restore ─────────────────────────────────────────────────────
# "on"  -> .wezterm.lua registers resurrect's gui-startup handler, so WezTerm
#          reopens the last session (tabs, panes, scrollback) at launch.
# "off" -> starts clean (the default). The autosave still runs either way, so
#          Leader+L can restore on demand. Stored on its own like weztermMux.
ts_wez_restore_get() {
    local v; v="$(ts_data_get weztermRestore 2>/dev/null || true)"
    case "$v" in on|off) echo "$v" ;; *) echo off ;; esac
}

# ts_wez_restore_set <on|off> — persist, regenerate derived keys, mirror to Windows.
ts_wez_restore_set() {
    case "$1" in on|off) ;; *) echo "ts_wez_restore_set: expected on|off" >&2; return 2 ;; esac
    ts_data_set weztermRestore "$1"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# ── atuin shell history ─────────────────────────────────────────────────────────
# "on"  -> chezmoi renders the eval line into ~/.config/terminal-stack/atuin.zsh,
#          which dot_zshrc sources. atuin then owns Ctrl+R.
# "off" -> that fragment renders empty (the default), so Ctrl+R stays with fzf.
#
# This is a saved setting rather than a `command -v atuin` guard on purpose.
# atuin *replaces* an existing binding, and the binary is frequently already
# present (a brew dependency, an old manual install) while completely dormant —
# a presence check would hijack Ctrl+R on the next apply without anyone choosing
# it. Stored on its own like weztermMux, so flipping it doesn't re-state every
# other wizard answer.
#
# dot_zshrc is deliberately NOT a chezmoi template: CLAUDE.md documents
# `chezmoi re-add ~/.zshrc`, and re-adding a rendered file into a .tmpl would
# clobber the template directives. Hence the sourced fragment.
ts_atuin_get() {
    local v; v="$(ts_data_get atuinEnabled 2>/dev/null || true)"
    case "$v" in on|off) echo "$v" ;; *) echo off ;; esac
}

# ts_atuin_set <on|off> — persist, regenerate derived keys, mirror to Windows.
ts_atuin_set() {
    case "$1" in on|off) ;; *) echo "ts_atuin_set: expected on|off" >&2; return 2 ;; esac
    ts_data_set atuinEnabled "$1"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# ── Ghostty config ──────────────────────────────────────────────────────────────
# "on"  (default) -> chezmoi renders ~/.config/ghostty/config and the custom
#                    light theme.
# "off"           -> .chezmoiignore drops both, so apply stops touching them.
#
# Turning it off does NOT itself delete anything: .chezmoiignore is evaluated on
# every machine, so a removal rule there would wipe a hand-written Ghostty config
# on a box that never opted in. `ts-config ghostty off` does the removal (and the
# backup restore) explicitly, for the machine you run it on.
ts_ghostty_get() {
    local v; v="$(ts_data_get ghosttyConfig 2>/dev/null || true)"
    case "$v" in on|off) echo "$v" ;; *) echo on ;; esac
}

# ts_ghostty_set <on|off> — persist, regenerate derived keys, mirror to Windows.
ts_ghostty_set() {
    case "$1" in on|off) ;; *) echo "ts_ghostty_set: expected on|off" >&2; return 2 ;; esac
    ts_data_set ghosttyConfig "$1"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# ── OS appearance detection ─────────────────────────────────────────────────────
# Echoes the baked palette (light|dark) for a theme mode. follow → detect; on any
# failure default to dark (the stack's historical look).
resolve_os_theme() {
    local mode="${1:-dark}"
    case "$mode" in
        light) echo light; return 0;;
        dark)  echo dark;  return 0;;
    esac
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        local v
        v="$(/mnt/c/Windows/System32/reg.exe query \
             'HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize' \
             /v AppsUseLightTheme 2>/dev/null | tr -d '\r')"
        case "$v" in *0x1*) echo light; return 0;; *0x0*) echo dark; return 0;; esac
        echo dark; return 0
    fi
    case "$(uname -s 2>/dev/null)" in
        Darwin)
            if defaults read -g AppleInterfaceStyle 2>/dev/null | grep -qi dark
            then echo dark; else echo light; fi
            return 0;;
        *)
            local cs; cs="$(gsettings get org.gnome.desktop.interface color-scheme 2>/dev/null)"
            case "$cs" in
                *dark*) echo dark; return 0;;
                *light*|*default*) echo light; return 0;;
            esac
            local th; th="$(gsettings get org.gnome.desktop.interface gtk-theme 2>/dev/null)"
            case "$th" in *-dark*|*Dark*|*-Dark*) echo dark; return 0;; esac
            echo dark; return 0;;
    esac
}

# ── Save + propagate ─────────────────────────────────────────────────────────────
# ts_save_config <leaderChord> <themeMode> <tmuxPrefix> [appId ...]
# Writes the raw choices, computes resolvedTheme, regenerates derived keys via
# `chezmoi init`, and mirrors the Windows config.json when /mnt/c is present.
ts_save_config() {
    local leader="$1" theme="$2" tprefix="$3"; shift 3 || true
    ts_data_set leaderChord "$leader"
    ts_data_set themeMode "$theme"
    ts_data_set tmuxPrefix "$tprefix"
    ts_data_set resolvedTheme "$(resolve_os_theme "$theme")"
    ts_data_set_apps "$@"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# Refresh only resolvedTheme from the live OS (used by ts-update for follow mode).
ts_refresh_resolved_theme() {
    local mode; mode="$(ts_data_get themeMode)"; [ -n "$mode" ] || mode="dark"
    ts_data_set resolvedTheme "$(resolve_os_theme "$mode")"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
}

# Mirror the derived config to the Windows side so sync-windows.ps1 / a
# Windows-standalone ts-config agree with the WSL source of truth.
ts_mirror_windows_config() {
    [ -d /mnt/c/Users ] || return 0
    # One render up front, so the ~49 reads below cost one chezmoi spawn between them.
    # shellcheck disable=SC2086
    ts_data_prefetch $TS_MIRROR_DATA_KEYS
    local cz; cz="$(ts_chezmoi_bin)" || return 0
    local winuser; winuser="$(ts_win_user 2>/dev/null || true)"
    if [ -z "$winuser" ] || [ ! -d "/mnt/c/Users/$winuser" ]; then
        # Loud on purpose. A silent skip leaves the Windows mirror stale while the save
        # reports success, and the next pwsh sync renders from those old values.
        echo "warning: could not resolve the Windows username - the Windows config mirror was NOT updated." >&2
        echo "  Windows-side settings keep their previous values; ts-doctor reports the divergence." >&2
        return 0
    fi
    local dst="/mnt/c/Users/$winuser/AppData/Local/terminal-stack"
    mkdir -p "$dst" 2>/dev/null || return 0
    local lk="" lm="" tm="" rt="" tr="" appscsv="" jsonapps=""
    # These six are derived expressions rather than plain [data] keys, so they cannot go
    # through ts_data_prefetch's hasKey form -- but they can still share one spawn. Six
    # separate renders cost about thirty seconds of the mirror write on a combined host.
    local _derived _dline _dk _dv
    _derived="$("$cz" execute-template 'lk=<<{{ .leaderKey }}>>
lm=<<{{ .leaderMods }}>>
tm=<<{{ .themeMode }}>>
rt=<<{{ .resolvedTheme }}>>
tr=<<{{ .tmuxPrefixResolved }}>>
appscsv=<<{{ if hasKey . "apps" }}{{ range $i,$a := .apps }}{{ if $i }},{{ end }}{{ $a }}{{ end }}{{ end }}>>' 2>/dev/null)"
    while IFS= read -r _dline; do
        case "$_dline" in *"=<<"*">>") ;; *) continue ;; esac
        _dk="${_dline%%=<<*}"
        _dv="${_dline#*=<<}"; _dv="${_dv%>>}"
        case "$_dk" in
            lk) lk="$_dv" ;;
            lm) lm="$_dv" ;;
            tm) tm="$_dv" ;;
            rt) rt="$_dv" ;;
            tr) tr="$_dv" ;;
            appscsv) appscsv="$_dv" ;;
        esac
    done <<EOF
$_derived
EOF
    local a IFS=,
    for a in $appscsv; do [ -n "$a" ] && jsonapps="$jsonapps${jsonapps:+, }\"$a\""; done
    unset IFS
    cat > "$dst/config.json" <<EOF
{
  "leaderKey": "$lk",
  "leaderMods": "$lm",
  "leaderChord": "$(ts_data_get leaderChord)",
  "themeMode": "$tm",
  "resolvedTheme": "$rt",
  "tmuxPrefix": "$(ts_data_get tmuxPrefix)",
  "tmuxPrefixResolved": "$tr",
  "weztermMux": "$(ts_wez_mux_get)",
  "weztermRestore": "$(ts_wez_restore_get)",
  "atuinEnabled": "$(ts_atuin_get)",
  "headroomEnabled": "$(ts_agent_get headroomEnabled)",
  "headroomCursorMode": "$(ts_agent_get headroomCursorMode)",
  "cavemanEnabled": "$(ts_agent_get cavemanEnabled)",
  "agentmemoryEnabled": "$(ts_agent_get agentmemoryEnabled)",
  "playwrightEnabled": "$(ts_agent_get playwrightEnabled)",
  "memoryBackend": "$(ts_agent_get memoryBackend)",
  "apps": [$jsonapps],
$(ts_cc_tts_json_for_mirror)
}
EOF
}
