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

headroom_status() {
    local proxy mcp ok=1
    proxy="$(json_get headroom.proxyUrl)"; mcp="$(json_get headroom.mcpUrl)"
    echo "Headroom:"
    if curl -fsS --max-time 1 "$proxy/readyz" >/dev/null 2>&1 \
        || curl -fsS --max-time 1 "$proxy/health" >/dev/null 2>&1; then
        echo "  ok  proxy reachable at $proxy"
    else echo "  !!  proxy not reachable at $proxy (docker-local owns it)"; ok=0; fi
    if curl -sS --max-time 1 "$mcp" >/dev/null 2>&1; then echo "  ok  MCP sidecar reachable at $mcp"
    else echo "  !!  MCP sidecar not reachable at $mcp"; ok=0; fi
    echo "  dashboard: $(json_get headroom.dashboardUrl)"
    [ "$ok" = 1 ]
}

headroom_apply() {
    local url; url="$(json_get headroom.mcpUrl)"
    command -v claude >/dev/null 2>&1 && { claude mcp remove --scope user headroom >/dev/null 2>&1 || true; claude mcp add --transport http --scope user headroom "$url"; }
    command -v codex >/dev/null 2>&1 && { codex mcp remove headroom >/dev/null 2>&1 || true; codex mcp add headroom --url "$url"; }
    if [ "$cursor_mode" = mcp ] && [ -d "$HOME/.cursor" ]; then cursor_mcp headroom "$url"
    else cursor_mcp headroom ""; fi
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
    echo 'AgentMemory plugin enabled. Docker, secrets, and server feature flags were not changed.'
}

agentmemory_remove() {
    command -v claude >/dev/null 2>&1 && { if [ "$action" = uninstall ]; then claude plugin uninstall agentmemory@agentmemory --scope user --keep-data -y || true; else claude plugin disable agentmemory@agentmemory --scope user || true; fi; }
    command -v codex >/dev/null 2>&1 && codex plugin remove agentmemory@agentmemory || true
}

run_one() {
    case "$1:$action" in
        headroom:status) headroom_status ;;
        headroom:dashboard) command -v open >/dev/null 2>&1 && open "$(json_get headroom.dashboardUrl)" || command -v xdg-open >/dev/null 2>&1 && xdg-open "$(json_get headroom.dashboardUrl)" ;;
        headroom:on|headroom:repair) headroom_apply; headroom_status ;;
        headroom:off|headroom:uninstall) headroom_apply_remove; echo 'Headroom client routing removed; Docker was not changed.' ;;
        caveman:status) echo "Caveman: pinned $(json_get caveman.version)"; grep -q 'terminal-stack-caveman-start' "${CODEX_HOME:-$HOME/.codex}/AGENTS.md" 2>/dev/null ;;
        caveman:on|caveman:repair) caveman_apply ;;
        caveman:off|caveman:uninstall) caveman_remove ;;
        agentmemory:status) echo "AgentMemory: pinned $(json_get agentmemory.version)"; curl -fsS --max-time 1 "$(json_get agentmemory.restUrl)" >/dev/null ;;
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
