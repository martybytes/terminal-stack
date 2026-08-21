# _merge_cursor_hooks.ps1 — splice the stack-owned hook entries of a rendered
# windows\.cursor\hooks.json.tmpl into the live %USERPROFILE%\.cursor\hooks.json
# instead of replacing the file. Invoked by scripts\sync-windows.ps1 and
# run_after_90-sync-windows.sh; the top-level splice engine is _merge_json_settings.ps1.
#
# Why this needs more than the key-splice _merge_claude_settings.ps1 does: everything
# in this file lives under ONE top-level `hooks` key, and other tools put their
# entries in the same event arrays we use. agentmemory's Cursor wiring
# (docker-local\agentmemory\setup-cursor-integration.ps1) adds seven hooks, two of
# which — `stop` and `postToolUse` — are events our TTS hooks are already in. So
# ownership here is per *entry*, not per key: rebuild each event array from our
# rendered entries plus every foreign entry that was already there, then splice the
# whole `hooks` value back in.
#
# Copying the file whole deleted all seven of those hooks on 2026-08-20 — the same
# sync that disabled the agentmemory Claude Code plugin. See docs\decisions.md
# § "Why `~/.claude/settings.json` is spliced, not copied".
#
# Ordering is ours-then-theirs, which is what `setup-cursor-integration.ps1` also
# produces (it appends itself after everything it does not own). The two converge
# instead of fighting, so neither rewrites the file on the other's account.

[CmdletBinding()]
param(
    [string]$FragmentPath,
    [string]$LivePath
)

$tsMergeEngine = Join-Path $PSScriptRoot '_merge_json_settings.ps1'
if (-not (Test-Path -LiteralPath $tsMergeEngine)) {
    throw "merge-cursor-hooks: splice engine not found: $tsMergeEngine"
}
. $tsMergeEngine

# What this stack has ever written into ~/.cursor/hooks.json, identified by what the
# entry's command references. An entry matching none of these — and not identical to
# something we are rendering right now — belongs to someone else and must survive:
# agentmemory's `./hooks/agentmemory/*.mjs`, or anything the user added by hand.
$script:TsCursorHookMarkers = @(
    'terminal-stack',   # AppData\Local\terminal-stack\tts-daemon\terminal-stack-tts.exe
    'cursor-tts',       # legacy .cursor/hooks/cursor-tts*.ps1 (Windows) / *.sh (WSL)
    'cat > /dev/null'   # our afterFileEdit no-op. Needs to be a marker, not just an
                        # exact match against the render: with TTS off we render no
                        # hooks at all, and it has to go then too.
)

function Test-TsCursorHookOurs {
    # $Ours is what the template renders for this event. Matching it exactly counts as
    # ours too, which is how the marker-less `cat > /dev/null` afterFileEdit no-op is
    # recognised without special-casing it.
    param($Entry, $Ours)

    $cmd = if ($Entry -is [System.Collections.IDictionary]) { [string]$Entry['command'] } else { '' }
    foreach ($marker in $script:TsCursorHookMarkers) {
        if ($cmd -like "*$marker*") { return $true }
    }
    $canon = ConvertTo-TsCanonicalJson $Entry
    foreach ($o in $Ours) {
        if ((ConvertTo-TsCanonicalJson $o) -eq $canon) { return $true }
    }
    return $false
}

function Merge-TsCursorHooks {
    [CmdletBinding()]
    param(
        # A *rendered* hooks.json (tokens already substituted) — the sync scripts hand
        # over the temp file they rendered, never windows\.cursor\hooks.json.tmpl.
        [Parameter(Mandatory)][string]$FragmentPath,
        [string]$LivePath
    )

    if (-not (Test-Path -LiteralPath $FragmentPath -PathType Leaf)) {
        Write-Warning "merge-cursor-hooks: fragment not found: $FragmentPath; skipping."
        return
    }

    if (-not $LivePath) {
        if (-not $env:USERPROFILE) {
            Write-Warning 'merge-cursor-hooks: $env:USERPROFILE is unset; skipping.'
            return
        }
        $LivePath = Join-Path $env:USERPROFILE '.cursor\hooks.json'
    }

    $fragRaw = Get-Content -LiteralPath $FragmentPath -Raw -Encoding UTF8

    # No live file yet: nothing to preserve, so the plain copy the mirror would have
    # done is exactly right.
    if (-not (Test-Path -LiteralPath $LivePath -PathType Leaf)) {
        $liveDir = Split-Path -Parent $LivePath
        if (-not (Test-Path -LiteralPath $liveDir -PathType Container)) {
            New-Item -ItemType Directory -Path $liveDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $FragmentPath -Destination $LivePath -Force
        Write-Host "created  $LivePath"
        return
    }

    $rendered = Read-TsJsonObject $FragmentPath $fragRaw 'merge-cursor-hooks'
    if ($null -eq $rendered) { return }
    $liveText = Get-Content -LiteralPath $LivePath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($liveText)) { $liveText = '{}' }
    $live = Read-TsJsonObject $LivePath $liveText 'merge-cursor-hooks'
    if ($null -eq $live) { return }

    $renderedHooks = if ($rendered.Contains('hooks') -and $rendered['hooks'] -is [System.Collections.IDictionary]) {
        $rendered['hooks']
    } else { [ordered]@{} }
    $liveHooks = if ($live.Contains('hooks') -and $live['hooks'] -is [System.Collections.IDictionary]) {
        $live['hooks']
    } else { [ordered]@{} }

    # Live event order first so an untouched file keeps its shape, then any event only
    # the template has.
    $events = [System.Collections.Generic.List[string]]::new()
    foreach ($k in $liveHooks.Keys) { $events.Add([string]$k) }
    foreach ($k in $renderedHooks.Keys) { if (-not $events.Contains([string]$k)) { $events.Add([string]$k) } }

    $merged = [ordered]@{}
    foreach ($ev in $events) {
        $ours = if ($renderedHooks.Contains($ev)) { @($renderedHooks[$ev]) } else { @() }
        $foreign = @()
        if ($liveHooks.Contains($ev)) {
            foreach ($entry in @($liveHooks[$ev])) {
                if ($null -eq $entry) { continue }
                if (-not (Test-TsCursorHookOurs $entry $ours)) { $foreign += $entry }
            }
        }
        # An event we no longer render and nobody else uses disappears — that is how
        # turning TTS off removes our hooks without touching anyone else's.
        $list = @($ours) + @($foreign)
        if ($list.Count -gt 0) { $merged[$ev] = $list }
    }

    # Hand the engine a synthetic fragment: it does the canonical-comparison,
    # round-trip verification, unrelated-key preservation and backup, and only the
    # `hooks` value is re-serialised — any other top-level key stays byte-for-byte.
    $fragObj = [ordered]@{}
    if ($rendered.Contains('version')) { $fragObj['version'] = $rendered['version'] }
    $fragObj['hooks'] = $merged
    $fragText = $fragObj | ConvertTo-Json -Depth 20

    $tmp = [IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $tmp -Value $fragText -Encoding utf8 -NoNewline
        Merge-TsJsonSettings -FragmentPath $tmp -FragmentText $fragText `
            -LivePath $LivePath -Label 'merge-cursor-hooks'
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Merge-TsCursorHooks @PSBoundParameters
}
