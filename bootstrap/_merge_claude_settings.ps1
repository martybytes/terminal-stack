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
# loading, with nothing to indicate why. We own `statusLine` and `theme` whole, and
# `hooks` per ENTRY; whatever else the template happens to render, it owns those
# keys too, and only those. Everything else in the live file survives byte-for-byte.
#
# Why `hooks` is per entry: other tools write their own hooks into the same object.
# `herdr integration install claude` adds SessionStart, PreToolUse, Stop and friends
# calling .claude/hooks/herdr-agent-state.sh, and that is all herdr's agents panel
# has to go on. Splicing the `hooks` value wholesale deleted them on every sync. Each
# event array is now our rendered groups, then every live group with our hooks taken
# out (a group someone appended into keeps their hook). Same rule as the POSIX twin
# dot_claude/modify_settings.json.tmpl and as _merge_cursor_hooks.ps1, one level
# deeper because Claude nests `{matcher, hooks: [...]}`.
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

# Every command this stack has ever written into the `hooks` object, on any platform.
# Same list as the POSIX twin. Never `.claude/hooks/` on its own: herdr's
# herdr-agent-state.sh lives in that directory too.
$script:TsClaudeHookMarkers = @(
    'wez-tab-status',      # .claude/hooks/wez-tab-status.ps1 / .sh
    'cc-speak',            # .claude/hooks/cc-speak.sh, cc-speak-input.sh
    'cc-tts',              # .claude/hooks/cc-tts-*.sh
    'terminal-stack-tts'   # tts-daemon/terminal-stack-tts.exe hook ...
)

function Test-TsClaudeHookOurs {
    param($Hook, $Rendered)

    $cmd = if ($Hook -is [System.Collections.IDictionary]) { [string]$Hook['command'] } else { '' }
    foreach ($marker in $script:TsClaudeHookMarkers) {
        if ($cmd -like "*$marker*") { return $true }
    }
    $canon = ConvertTo-TsCanonicalJson $Hook
    foreach ($r in $Rendered) {
        if ((ConvertTo-TsCanonicalJson $r) -eq $canon) { return $true }
    }
    return $false
}

function Test-TsClaudeHookGroup($Group) {
    return ($Group -is [System.Collections.IDictionary]) -and $Group.Contains('hooks') -and
        ($Group['hooks'] -is [System.Collections.IList])
}

function Merge-TsClaudeHooks {
    # Per-entry merge of the `hooks` object; see the header.
    param($LiveHooks, $RenderedHooks)

    if ($RenderedHooks -isnot [System.Collections.IDictionary]) { $RenderedHooks = [ordered]@{} }
    if ($LiveHooks -isnot [System.Collections.IDictionary]) { $LiveHooks = [ordered]@{} }

    $events = [System.Collections.Generic.List[string]]::new()
    foreach ($k in $LiveHooks.Keys) { $events.Add([string]$k) }
    foreach ($k in $RenderedHooks.Keys) { if (-not $events.Contains([string]$k)) { $events.Add([string]$k) } }

    $result = [ordered]@{}
    foreach ($ev in $events) {
        $ours = if ($RenderedHooks.Contains($ev) -and $null -ne $RenderedHooks[$ev]) { @($RenderedHooks[$ev]) } else { @() }
        $renderedInner = @()
        foreach ($g in $ours) { if (Test-TsClaudeHookGroup $g) { $renderedInner += @($g['hooks']) } }

        $foreign = @()
        if ($LiveHooks.Contains($ev) -and $null -ne $LiveHooks[$ev]) {
            foreach ($group in @($LiveHooks[$ev])) {
                if (-not (Test-TsClaudeHookGroup $group)) {
                    # Not a shape we write; leave it exactly as found.
                    $foreign += , $group
                    continue
                }
                $all = @($group['hooks'])
                $kept = @($all | Where-Object { -not (Test-TsClaudeHookOurs $_ $renderedInner) })
                if ($kept.Count -eq $all.Count) {
                    $foreign += , $group
                } elseif ($kept.Count -gt 0) {
                    # Someone appended into a group we wrote: theirs survives.
                    $trimmed = [ordered]@{}
                    foreach ($k in $group.Keys) { $trimmed[$k] = $group[$k] }
                    $trimmed['hooks'] = $kept
                    $foreign += , $trimmed
                }
            }
        }
        # An event that ends up empty disappears: that is how turning TTS off still
        # removes our hooks without touching anyone else's.
        $list = @($ours) + @($foreign)
        if ($list.Count -gt 0) { $result[$ev] = $list }
    }
    return $result
}

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

    $fragRaw = Get-Content -LiteralPath $FragmentPath -Raw -Encoding UTF8
    $rendered = Read-TsJsonObject $FragmentPath $fragRaw 'merge-claude-settings'
    if ($null -eq $rendered) { return }
    $liveText = Get-Content -LiteralPath $LivePath -Raw -Encoding UTF8
    $live = Read-TsJsonObject $LivePath $liveText 'merge-claude-settings'
    if ($null -eq $live) { return }

    # Hand the engine a synthetic fragment with `hooks` already merged: it still does
    # the canonical comparison, round-trip verification, unrelated-key preservation
    # and backup, exactly as _merge_cursor_hooks.ps1 does.
    $fragObj = [ordered]@{}
    foreach ($k in $rendered.Keys) {
        if ($k -eq 'hooks') {
            $liveHookObj = if ($live.Contains('hooks')) { $live['hooks'] } else { $null }
            $fragObj[$k] = Merge-TsClaudeHooks $liveHookObj $rendered['hooks']
        } else {
            $fragObj[$k] = $rendered[$k]
        }
    }
    $fragText = $fragObj | ConvertTo-Json -Depth 20

    $tmp = [IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $tmp -Value $fragText -Encoding utf8 -NoNewline
        Merge-TsJsonSettings -FragmentPath $tmp -FragmentText $fragText `
            -LivePath $LivePath -Label 'merge-claude-settings'
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Merge-TsClaudeSettings @PSBoundParameters
}
