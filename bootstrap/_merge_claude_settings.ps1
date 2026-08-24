# _merge_claude_settings.ps1 — splice the stack-owned keys of a rendered
# windows\.claude\settings.json.tmpl into the live %USERPROFILE%\.claude\settings.json
# instead of replacing the file. Invoked by scripts\sync-windows.ps1 and
# run_after_90-sync-windows.sh; the splice engine is _merge_json_settings.ps1.
#
# Why not the plain whole-file mirror every other windows\** file gets: Claude Code
# WRITES this same file. `model`, `enabledPlugins`, `permissions`, `env`,
# `extraKnownMarketplaces` and friends are its own state, set by /model and
# /plugin, not ours — and a whole-file copy silently deletes every one of them.
# That is what disabled the agentmemory plugin on 2026-08-20: `enabledPlugins`
# went missing mid-session and the plugin's hooks and MCP server simply stopped
# loading, with nothing to indicate why. We own `statusLine`, `hooks` and `theme`;
# whatever else the template happens to render, it owns those keys too, and only
# those. Everything else in the live file survives byte-for-byte.
#
# Client wiring that lives in this file (the AgentMemory URL, plugin enablement) is
# deliberately outside version control — see services\stacks\agentmemory\README.md.
# Do not "fix" this by adding those keys to the template.

[CmdletBinding()]
param(
    [string]$FragmentPath,
    [string]$LivePath
)

$tsMergeEngine = Join-Path $PSScriptRoot '_merge_json_settings.ps1'
if (-not (Test-Path -LiteralPath $tsMergeEngine)) {
    throw "merge-claude-settings: splice engine not found: $tsMergeEngine"
}
. $tsMergeEngine

function Merge-TsClaudeSettings {
    [CmdletBinding()]
    param(
        # A *rendered* settings.json (tokens already substituted) — the sync scripts
        # hand over the temp file they rendered, never windows\.claude\settings.json.tmpl.
        [Parameter(Mandatory)][string]$FragmentPath,
        [string]$LivePath
    )

    if (-not $LivePath) {
        $home_ = $env:USERPROFILE
        if (-not $home_) {
            Write-Warning 'merge-claude-settings: $env:USERPROFILE is unset; skipping.'
            return
        }
        $LivePath = Join-Path $home_ '.claude\settings.json'
    }

    # No live file yet (fresh machine): nothing to preserve, so the plain copy the
    # mirror would have done is exactly right — and cheaper than a splice.
    if (-not (Test-Path -LiteralPath $LivePath -PathType Leaf)) {
        $liveDir = Split-Path -Parent $LivePath
        if (-not (Test-Path -LiteralPath $liveDir -PathType Container)) {
            New-Item -ItemType Directory -Path $liveDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $FragmentPath -Destination $LivePath -Force
        Write-Host "created  $LivePath"
        return
    }

    Merge-TsJsonSettings -FragmentPath $FragmentPath -LivePath $LivePath `
        -Label 'merge-claude-settings'
}

if ($MyInvocation.InvocationName -ne '.') {
    Merge-TsClaudeSettings @PSBoundParameters
}
