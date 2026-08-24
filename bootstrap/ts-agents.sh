#!/usr/bin/env bash
# ts-agents.sh — user-global Headroom, Caveman and AgentMemory lifecycle adapter.
# Docker services and project repositories are intentionally out of scope.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$ROOT/agent-tools.json"
tool="${1:-all}" action="${2:-status}" cursor_mode="${3:-mcp}"

case "$tool" in all|headroom|caveman|agentmemory) ;; *) echo "ts-agents: unknown tool '$tool'" >&2; exit 2;; esac
case "$action" in status|on|off|repair|uninstall|dashboard) ;; *) echo "ts-agents: unknown action '$action'" >&2; exit 2;; esac
case "$cursor_mode" in mcp|byok|off) ;; *) echo "ts-agents: cursor mode must be mcp, byok, or off" >&2; exit 2;; esac

# On a combined Windows/WSL install the actual GUI agents and user configuration
# live on Windows. Use the same adapter as native PowerShell so the two entrypoints
# cannot drift.
if grep -qi microsoft /proc/version 2>/dev/null; then
    ps=""
    for p in "/mnt/c/Program Files/PowerShell/7/pwsh.exe" "/mnt/c/Program Files/PowerShell/7-preview/pwsh.exe"; do
        [ -x "$p" ] && { ps="$p"; break; }
    done
    if [ -n "$ps" ]; then
        win="$(wslpath -w "$ROOT/ts-agents.ps1")"
        exec "$ps" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$win" \
            -Tool "$tool" -Action "$action" -CursorMode "$cursor_mode"
    fi
fi

# Any HTTP response means a server is there. A 404/401 is not "down".
am_probe() {
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1" 2>/dev/null || true)"
    case "$code" in
        ''|000) echo "  !!  not reachable at $1"; return 1 ;;
        *)      echo "  ok  reachable at $1 (HTTP $code)"; return 0 ;;
    esac
}

json_get() {
    python3 - "$MANIFEST" "$1" <<'PY'
import json, sys
node = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split('.'):
    node = node[part]
print(node)
PY
}

cursor_mcp() {
    local name="$1" url="${2:-}" path="$HOME/.cursor/mcp.json"
    python3 - "$path" "$name" "$url" <<'PY'
import json, os, shutil, sys, time
path, name, url = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as f: cfg = json.load(f)
except FileNotFoundError:
    cfg = {"mcpServers": {}}
except Exception as exc:
    raise SystemExit(f"Refusing to overwrite malformed JSON {path}: {exc}")
servers = cfg.setdefault("mcpServers", {})
if url: servers[name] = {"url": url}
else: servers.pop(name, None)
os.makedirs(os.path.dirname(path), exist_ok=True)
if os.path.exists(path): shutil.copy2(path, path + ".bak." + time.strftime("%Y%m%d-%H%M%S"))
with open(path, "w", encoding="utf-8") as f: json.dump(cfg, f, indent=2); f.write("\n")
PY
}

# The stack tree is always <clone>/services/, so there is nothing to search for:
# $ROOT is this script's directory. The old four-root workspace walk could not
# work from the runtime clone (not under the workspace) and, post-merge, could
# only find a stale file from an archived repo. HEADROOM_ENV_FILE stays as the
# documented override.
headroom_token() {
    if [ -n "${HEADROOM_PROXY_TOKEN:-}" ]; then printf '%s' "$HEADROOM_PROXY_TOKEN"; return 0; fi
    local file
    file="${HEADROOM_ENV_FILE:-$ROOT/../services/stacks/headroom/.env}"
    [ -r "${file:-}" ] || return 1
    sed -n 's/^HEADROOM_PROXY_TOKEN=//p' "$file" | head -1
}

# Probe the proxy and SAY WHY it failed. One 2s attempt reported a cold
# container as broken, and `on`/`repair` gate on this, so a slow first hit
# turned into 'registrations were not changed' with nothing to act on. A
# real HTTP answer (401, 500) is conclusive and is not retried; only a
# connection failure or timeout is.
headroom_probe_auth() {
    local token="$1" proxy="$2" code attempt
    for attempt in 1 2; do
        # curl PRINTS 000 and exits non-zero on a connection failure, so a
        # `|| echo 000` fallback concatenates and yields 000000.
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
            -H "X-Headroom-Proxy-Token: $token" "$proxy/stats" 2>/dev/null)" || code=000
        case "${code:-000}" in
            2??) return 0 ;;
            000)
                # set -e safe: a bare `[ ] && { }` as the last command of the
                # loop body would abort the retry it exists to allow.
                if [ "$attempt" = 2 ]; then printf unreachable; return 1; fi
                ;;
            *) printf 'HTTP %s' "$code"; return 1 ;;
        esac
    done
}

headroom_status() {
    local proxy mcp token why proxy_ok=0
    proxy="$(json_get headroom.proxyUrl)"; mcp="$(json_get headroom.mcpUrl)"
    echo "Headroom:"
    token="$(headroom_token)" || token=""
    if [ -z "$token" ]; then
        echo "  !!  proxy token unavailable; set HEADROOM_PROXY_TOKEN or HEADROOM_ENV_FILE"
    elif why="$(headroom_probe_auth "$token" "$proxy")"; then
        echo "  ok  proxy authentication works at $proxy"
        proxy_ok=1
    else
        echo "  !!  proxy authentication failed at $proxy: $why (ts-stack runs the proxy)"
    fi
    if am_probe "$mcp" >/dev/null 2>&1; then echo "  ok  MCP reachable at $mcp"
    else
        # Not a fault in this stack: `headroom mcp serve` is a SEPARATE process
        # (default 127.0.0.1:8788) that the headroom stack's compose does not start.
        echo "  !!  MCP not reachable at $mcp"
        echo "      start it with: headroom mcp serve --transport http"
    fi
    echo "  dashboard: $(json_get headroom.dashboardUrl)"
    [ "$proxy_ok" = 1 ]
}

headroom_apply() {
    local url; url="$(json_get headroom.mcpUrl)"
    # The proxy container on 8787 does not provide this optional MCP service.
    # Do not leave clients pointing at a dead 8788 endpoint: Codex attempts every
    # registered MCP server at startup and warns on every launch.
    if am_probe "$url" >/dev/null 2>&1; then
        command -v claude >/dev/null 2>&1 && { claude mcp remove --scope user headroom >/dev/null 2>&1 || true; claude mcp add --transport http --scope user headroom "$url"; }
        command -v codex >/dev/null 2>&1 && { codex mcp remove headroom >/dev/null 2>&1 || true; codex mcp add headroom --url "$url"; }
        if [ "$cursor_mode" = mcp ] && [ -d "$HOME/.cursor" ]; then cursor_mcp headroom "$url"
        else cursor_mcp headroom ""; fi
    else
        command -v claude >/dev/null 2>&1 && claude mcp remove --scope user headroom >/dev/null 2>&1 || true
        command -v codex >/dev/null 2>&1 && codex mcp remove headroom >/dev/null 2>&1 || true
        cursor_mcp headroom ""
        echo "  --  optional Headroom MCP is offline; removed stale client registrations"
    fi
    if [ "$cursor_mode" = byok ]; then
        echo "Cursor BYOK: set its global provider base URL to http://127.0.0.1:8787 and use a provider API key."
    fi
}

caveman_rule() {
    local want="$1" path="${CODEX_HOME:-$HOME/.codex}/AGENTS.md" tmp
    mkdir -p "$(dirname "$path")"; tmp="$(mktemp)"
    [ -f "$path" ] && awk '/<!-- terminal-stack-caveman-start -->/{skip=1;next}/<!-- terminal-stack-caveman-end -->/{skip=0;next}!skip{print}' "$path" > "$tmp" || :
    if [ "$want" = on ]; then
        printf '\n%s\n%s\n%s\n' \
            '<!-- terminal-stack-caveman-start -->' \
            'Caveman is enabled globally. Apply the installed caveman skill to every response; use full mode unless the user asks otherwise.' \
            '<!-- terminal-stack-caveman-end -->' >> "$tmp"
    fi
    [ -f "$path" ] && cp -p "$path" "$path.bak.$(date +%Y%m%d-%H%M%S)"
    mv "$tmp" "$path"
}

caveman_apply() {
    local source; source="$(json_get caveman.source)"
    if command -v claude >/dev/null 2>&1; then
        claude plugin marketplace add "$(json_get caveman.claudeMarketplace)" --scope user || true
        claude plugin install caveman@caveman --scope user -y || true
        claude plugin enable caveman@caveman --scope user || true
    fi
    command -v npx >/dev/null 2>&1 && npx -y skills@latest add "$source" -g -y --copy -a codex cursor -s caveman || true
    caveman_rule on
    echo 'Cursor manual User Rule: Always apply the global caveman skill; use full mode unless I ask otherwise.'
}

caveman_remove() {
    if command -v claude >/dev/null 2>&1; then
        if [ "$action" = uninstall ]; then claude plugin uninstall caveman@caveman --scope user --keep-data -y || true
        else claude plugin disable caveman@caveman --scope user || true; fi
    fi
    if [ "$action" = uninstall ] && command -v npx >/dev/null 2>&1; then
        npx -y skills@latest remove caveman -g -y -a codex cursor || true
    fi
    caveman_rule off
}

agentmemory_apply() {
    if command -v claude >/dev/null 2>&1; then
        claude plugin marketplace add "$(json_get agentmemory.source)@$(json_get agentmemory.ref)" --scope user || true
        claude plugin install agentmemory@agentmemory --scope user -y || true
        claude plugin enable agentmemory@agentmemory --scope user || true
    fi
    if command -v codex >/dev/null 2>&1; then
        codex plugin marketplace add "$(json_get agentmemory.source)" --ref "$(json_get agentmemory.ref)" || true
        codex plugin add agentmemory@agentmemory || true
    fi
    # Host-side hook wiring. Installing the plugin is only half the job: without
    # the deployment edits the hooks POST nothing and retrieval never fires, and
    # nothing logs it because every vendor hook does fetch(...).catch(() => {})
    # then exits 0. Re-run on every `on`/`repair` because a plugin upgrade
    # replaces the cache and silently reverts every edit.
    if [ -x "$ROOT/ts-agentmemory.sh" ]; then
        bash "$ROOT/ts-agentmemory.sh" --apply || echo 'ts-agents: agentmemory hook wiring reported problems (see above).'
    fi
    echo 'AgentMemory plugin enabled. Docker, secrets, and server feature flags were not changed.'
}

agentmemory_remove() {
    # Undo the host-side wiring first, while the plugin cache it patched is still
    # present — the restore reads the .agent007memory-original backups beside the
    # vendor scripts.
    [ -x "$ROOT/ts-agentmemory.sh" ] && { bash "$ROOT/ts-agentmemory.sh" --undo --apply || true; }
    command -v claude >/dev/null 2>&1 && { if [ "$action" = uninstall ]; then claude plugin uninstall agentmemory@agentmemory --scope user --keep-data -y || true; else claude plugin disable agentmemory@agentmemory --scope user || true; fi; }
    command -v codex >/dev/null 2>&1 && codex plugin remove agentmemory@agentmemory || true
}

run_one() {
    case "$1:$action" in
        headroom:status) headroom_status ;;
        headroom:dashboard) command -v open >/dev/null 2>&1 && open "$(json_get headroom.dashboardUrl)" || command -v xdg-open >/dev/null 2>&1 && xdg-open "$(json_get headroom.dashboardUrl)" ;;
        headroom:on|headroom:repair) headroom_status && headroom_apply && headroom_status ;;
        headroom:off|headroom:uninstall) headroom_apply_remove; echo 'Headroom client routing removed; Docker was not changed.' ;;
        caveman:status) echo "Caveman: pinned $(json_get caveman.version)"; grep -q 'terminal-stack-caveman-start' "${CODEX_HOME:-$HOME/.codex}/AGENTS.md" 2>/dev/null ;;
        caveman:on|caveman:repair) caveman_apply ;;
        caveman:off|caveman:uninstall) caveman_remove ;;
        agentmemory:status)
            echo "AgentMemory: pinned $(json_get agentmemory.version)"
            # NOT `curl -fsS`: AgentMemory answers 404 on / and 401 on
            # /agentmemory/health, and -f turns either into a failure — so this
            # reported the service DOWN while it was up and serving. Any HTTP
            # response proves something is listening.
            am_probe "$(json_get agentmemory.restUrl)" ;;
        agentmemory:on|agentmemory:repair) agentmemory_apply ;;
        agentmemory:off|agentmemory:uninstall) agentmemory_remove ;;
        *) echo "ts-agents: unsupported action $action for $1" >&2; return 2 ;;
    esac
}

headroom_apply_remove() {
    command -v claude >/dev/null 2>&1 && claude mcp remove --scope user headroom >/dev/null 2>&1 || true
    command -v codex >/dev/null 2>&1 && codex mcp remove headroom >/dev/null 2>&1 || true
    cursor_mcp headroom ""
}

if [ "$tool" = all ]; then
    rc=0; for name in headroom caveman agentmemory; do run_one "$name" || rc=1; done; exit "$rc"
else run_one "$tool"; fi
