<#
.NAME        ts-agentmemory
.SYNOPSIS    Wire Claude Code, Codex and Cursor to a local agentmemory server: tagged URLs,
             retrieval on by default, the deployment hook-script edits, and the duplicate-
             invocation guard. Previews by default.
.PLATFORM    windows
.USAGE       bootstrap\ts-agentmemory.ps1 [-Apply] [-Undo] [-Check] [-Host claude|codex|cursor]
.WHEN        Runs automatically from both sync paths, so a plugin upgrade that reverts the
             hook-script edits is repaired on the next `ts-update` / `chezmoi apply`. Run it by
             hand to preview, to check, or to undo.
.NOTE        Why this lives in terminal-stack and not next to the Docker stack: this repo owns
             the harness surface — ~/.claude/settings.json, ~/.cursor/hooks.json, dot_codex/**,
             the TTS hooks for all three agents — and already carries agentmemory-aware code in
             bootstrap/_merge_claude_settings.ps1 and bootstrap/_merge_cursor_hooks.ps1, which
             exist to stop agentmemory's hook entries being clobbered. The server image, compose
             file and in-container patches stay in docker-local. Which hooks exist and what they
             run is a terminal-stack concern; what the server does with the request is not.

             Auto-detected, with no saved setting: a host is wired only when its agentmemory
             plugin cache is present, and skipped silently otherwise. Gating on the cache rather
             than on server reachability means the wiring survives the container being stopped.
             A new [data] key would cost the documented 7-step blast radius and could drift
             between chezmoi [data] and the Windows mirror the way ccTtsEnabled did.

             The HMAC secret is never read or written here. The plugin's own .mcp.json reads
             ${AGENTMEMORY_SECRET:-} from the User environment.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Undo,
    [switch]$Check,
    [ValidateSet('claude', 'codex', 'cursor')][string[]]$HostName
)

$ErrorActionPreference = 'Stop'
$execute = $Apply
$mode = if ($Check) { 'CHECK' } elseif ($Undo -and $Apply) { 'UNDO' } elseif ($Apply) { 'APPLY' } else { 'PREVIEW' }

function Section([string]$t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Step([string]$t)    { $tag = if ($execute) { '[DO]  ' } else { '[would]' }; Write-Host "$tag $t" -ForegroundColor ($(if ($execute) { 'Green' } else { 'Yellow' })) }
function Info([string]$t)    { Write-Host "       $t" -ForegroundColor DarkGray }
function Warn([string]$t)    { Write-Host "  !    $t" -ForegroundColor Yellow }
function Pass([string]$t)    { Write-Host "  OK   $t" -ForegroundColor Green }

. (Join-Path $PSScriptRoot '_agentmemory.ps1')
. (Join-Path $PSScriptRoot '_merge_json_settings.ps1')

$script:problems = 0
function Fail([string]$t) { $script:problems++; Warn $t }

$stamp = Get-Date -Format 'yyyyMMdd'
$wanted = if ($HostName) { $HostName } else { $script:TsAmHosts | ForEach-Object { $_.Name } }

if (-not $Check) {
    Write-Host "ts-agentmemory  mode=$mode" -ForegroundColor White
    if (-not $execute) { Write-Host '(preview only - add -Apply to write, or -Undo -Apply to remove)' -ForegroundColor DarkGray }
}

# ---- shared helpers ---------------------------------------------------------

function Backup-AmFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $bak = Get-TsBackupPath -dst $Path -stamp $stamp
    Copy-Item -LiteralPath $Path -Destination $bak -Force
    Info "backup $bak"
}

function Get-AmPluginVersionDir([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $null }
    return Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Name } catch { [version]'0.0.0' } } -Descending |
        Select-Object -First 1
}

# Resolve script paths inside the selected plugin version, refusing to escape it.
function Get-AmScriptPaths([string]$VersionRoot, [string[]]$Names, [string]$SubDir = 'scripts') {
    $root = [IO.Path]::GetFullPath($VersionRoot).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $out = @()
    foreach ($n in $Names) {
        $p = [IO.Path]::GetFullPath((Join-Path $VersionRoot (Join-Path $SubDir $n)))
        if (-not $p.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to touch a script outside the plugin version: $p"
        }
        if (Test-Path -LiteralPath $p -PathType Leaf) { $out += $p }
    }
    return $out
}

$script:CodexScripts  = @('session-start.mjs', 'prompt-submit.mjs', 'pre-tool-use.mjs', 'post-tool-use.mjs', 'pre-compact.mjs', 'stop.mjs')
$script:CursorScripts = @('session-start.mjs', 'prompt-submit.mjs', 'pre-tool-use.mjs', 'post-tool-use.mjs', 'post-tool-failure.mjs', 'stop.mjs', 'session-end.mjs')

# cmd /s strips only the outermost quote pair, so the quoted script path survives a
# profile directory containing spaces. Both variables are inlined rather than inherited:
# a User env var only reaches processes started after it was set, so long-running shells
# and desktop apps launched hooks without it and every retrieval returned early.
function New-AmHookCommand([string]$Agent, [string]$ScriptPath) {
    $p = $ScriptPath.Replace('\', '/')
    $url = Get-TsAmAgentUrl $Agent
    return "cmd /d /s /c `"set AGENTMEMORY_URL=$url&& set AGENTMEMORY_INJECT_CONTEXT=true&& node `"$p`"`""
}

function Test-AmOwnedCommand([string]$Command) {
    return $Command -like '*hooks/agentmemory/*' -or $Command -like '*hooks\agentmemory\*'
}

# Copy the vendor scripts to a stable location and apply the edits to the copy, so a
# plugin upgrade cannot silently revert the deployed behaviour underneath a live agent.
function Sync-AmStableScripts([string]$SourceDir, [string]$DestDir, [string[]]$Names, [object[]]$Edits) {
    $changed = 0
    if (-not (Test-Path -LiteralPath $DestDir -PathType Container)) {
        Step "create $DestDir"
        if ($execute) { New-Item -ItemType Directory -Path $DestDir -Force | Out-Null }
    }
    foreach ($name in $Names) {
        $src = Join-Path $SourceDir $name
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { Warn "vendor script missing: $name"; continue }
        $content = Get-Content -LiteralPath $src -Raw
        foreach ($edit in @($Edits | Where-Object { $_.Scripts -contains '*' -or $_.Scripts -contains $name })) {
            $ref = [ref]$content
            $null = Set-AmEditInText $ref $edit $name
            $content = $ref.Value
        }
        $dst = Join-Path $DestDir $name
        $current = if (Test-Path -LiteralPath $dst -PathType Leaf) { Get-Content -LiteralPath $dst -Raw } else { $null }
        if ($current -eq $content) { continue }
        Step "install $name"
        if ($execute) { Set-Content -LiteralPath $dst -Value $content -Encoding utf8 -NoNewline }
        $changed++
    }
    return $changed
}

# ---- Claude Code ------------------------------------------------------------

function Invoke-AmClaude {
    $root = Join-Path $env:USERPROFILE '.claude'
    $ver = Get-AmPluginVersionDir (Join-Path $root 'plugins\cache\agentmemory\agentmemory')
    if (-not $ver) { Info 'Claude Code: agentmemory plugin not installed, skipped'; return }

    Section 'Claude Code'
    Info "plugin $($ver.Name)"

    # settings.json: only the two env keys. statusLine/hooks/theme belong to this repo's
    # own splice, and everything else in the file belongs to Claude Code. Splicing just
    # the `env` value keeps every other byte where it was, and keeps agentmemory from
    # owning the whole key so unrelated env vars survive.
    $settingsPath = Join-Path $root 'settings.json'
    $desired = [ordered]@{
        AGENTMEMORY_URL            = Get-TsAmAgentUrl 'claude'
        AGENTMEMORY_INJECT_CONTEXT = 'true'
    }
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        Warn "$settingsPath does not exist yet; start Claude Code once, then re-run"
    } else {
        $liveText = Get-Content -LiteralPath $settingsPath -Raw
        $live = Read-TsJsonObject $settingsPath $liveText 'ts-agentmemory'
        if ($null -eq $live) { Fail "could not parse $settingsPath" }
        else {
            $env0 = if ($live.Contains('env') -and $live['env'] -is [System.Collections.IDictionary]) { $live['env'] } else { [ordered]@{} }
            $merged = [ordered]@{}
            foreach ($k in $env0.Keys) { $merged[$k] = $env0[$k] }
            foreach ($k in $desired.Keys) {
                if ($Undo) { $merged.Remove($k) | Out-Null } else { $merged[$k] = $desired[$k] }
            }
            $same = (ConvertTo-TsCanonicalJson $merged) -eq (ConvertTo-TsCanonicalJson $env0)
            if ($same) {
                if ($Check) { Pass 'Claude settings env is correct' } else { Info 'settings env already correct' }
            } elseif ($Check) {
                Fail 'Claude settings env is missing AGENTMEMORY_URL / AGENTMEMORY_INJECT_CONTEXT'
            } else {
                Step "update env in $settingsPath"
                if ($execute) {
                    $fragText = ([ordered]@{ env = $merged } | ConvertTo-Json -Depth 20)
                    $tmp = [IO.Path]::GetTempFileName()
                    try {
                        Set-Content -LiteralPath $tmp -Value $fragText -Encoding utf8 -NoNewline
                        Merge-TsJsonSettings -FragmentPath $tmp -FragmentText $fragText `
                            -LivePath $settingsPath -Label 'ts-agentmemory'
                    } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
                }
            }
        }
    }

    $edits = Get-AmHookEdits -Agent claude
    $paths = Get-AmScriptPaths $ver.FullName @('session-start.mjs', 'prompt-submit.mjs',
                                                 'pre-tool-use.mjs')
    if ($Check) {
        $missing = Test-AmHookEdits -ScriptPaths $paths -Edits $edits
        if ($missing.Count -eq 0) { Pass 'Claude hook edits present' }
        else { Fail "Claude hook edits reverted (a plugin upgrade does this): $($missing[0])" }
    } else {
        Invoke-AmHookEdits -ScriptPaths $paths -Edits $edits -Execute:$execute -Undo:$Undo `
            -OnStep { param($m) Step $m } -OnInfo { param($m) Info $m }
    }
}

# ---- Codex ------------------------------------------------------------------

function Invoke-AmCodex {
    $root = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $ver = Get-AmPluginVersionDir (Join-Path $root 'plugins\cache\agentmemory\agentmemory')
    if (-not $ver) { Info 'Codex: agentmemory plugin not installed, skipped'; return }

    Section 'Codex'
    Info "plugin $($ver.Name)"
    $edits = Get-AmHookEdits -Agent codex

    # Two registrations are live: this hooks.json (Codex Desktop) and the plugin's own
    # hooks.codex.json (the CLI). Both are patched, and the duplicate invocation is
    # dropped by the guard the edits install. Codex exposes no hooks-only toggle and
    # silently ignores unknown plugin config keys, so removing one is not an option
    # without losing Desktop or CLI capture.
    $pluginPaths = Get-AmScriptPaths $ver.FullName $script:CodexScripts
    $stableDir = Join-Path $root 'hooks\agentmemory\scripts'
    $stablePaths = @($script:CodexScripts | ForEach-Object { Join-Path $stableDir $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })

    if ($Check) {
        foreach ($set in @(
            @{ N = 'Codex plugin cache (CLI)'; P = $pluginPaths },
            @{ N = 'Codex stable copies (Desktop)'; P = $stablePaths }
        )) {
            if ($set.P.Count -eq 0) { Warn "$($set.N): no scripts found"; continue }
            $missing = Test-AmHookEdits -ScriptPaths $set.P -Edits $edits
            if ($missing.Count -eq 0) { Pass "$($set.N): edits present" }
            else { Fail "$($set.N): edits reverted: $($missing[0])" }
        }
        return
    }

    Invoke-AmHookEdits -ScriptPaths $pluginPaths -Edits $edits -Execute:$execute -Undo:$Undo `
        -OnStep { param($m) Step $m } -OnInfo { param($m) Info $m }

    if ($Undo) {
        if (Test-Path -LiteralPath $stableDir -PathType Container) {
            Step "remove $stableDir"
            if ($execute) { Remove-Item -LiteralPath $stableDir -Recurse -Force }
        }
    } else {
        $null = Sync-AmStableScripts (Join-Path $ver.FullName 'scripts') $stableDir $script:CodexScripts $edits
    }

    # hooks.json: own only our own entries, leave anyone else's alone. No PreToolUse
    # matcher — the script decides what it can serve, and the vendor allow-list excluded
    # the tool Codex emits most (Bash), so a matcher here only hides tools from it.
    $hooksPath = Join-Path $root 'hooks.json'
    $desired = [ordered]@{
        SessionStart     = @{ script = 'session-start.mjs'; status = 'agentmemory: loading session context' }
        UserPromptSubmit = @{ script = 'prompt-submit.mjs';  status = 'agentmemory: recalling relevant memories' }
        PreToolUse       = @{ script = 'pre-tool-use.mjs' }
        PostToolUse      = @{ script = 'post-tool-use.mjs' }
        PreCompact       = @{ script = 'pre-compact.mjs' }
        Stop             = @{ script = 'stop.mjs' }
    }
    $cfg = if (Test-Path -LiteralPath $hooksPath -PathType Leaf) {
        Get-Content -LiteralPath $hooksPath -Raw | ConvertFrom-Json -AsHashtable
    } else { [ordered]@{ hooks = [ordered]@{} } }
    if (-not $cfg.ContainsKey('hooks') -or $cfg['hooks'] -isnot [System.Collections.IDictionary]) { $cfg['hooks'] = [ordered]@{} }

    $changed = @()
    foreach ($event in $desired.Keys) {
        $groups = @(if ($cfg['hooks'].Contains($event)) { $cfg['hooks'][$event] } else { @() })
        $foreign = @($groups | Where-Object {
            $cmds = @($_.hooks | ForEach-Object { [string]$_.command })
            -not ($cmds | Where-Object { Test-AmOwnedCommand $_ })
        })
        if ($Undo) {
            if ($foreign.Count -ne $groups.Count) {
                $changed += $event
                if ($foreign.Count -eq 0) { $cfg['hooks'].Remove($event) | Out-Null } else { $cfg['hooks'][$event] = $foreign }
            }
            continue
        }
        $hook = [ordered]@{ type = 'command'; command = (New-AmHookCommand 'codex' (Join-Path $stableDir $desired[$event].script)) }
        if ($desired[$event].status) { $hook['statusMessage'] = $desired[$event].status }
        $group = [ordered]@{ hooks = @($hook) }
        $want = @($foreign) + @($group)
        if ((ConvertTo-TsCanonicalJson $want) -ne (ConvertTo-TsCanonicalJson $groups)) {
            $changed += $event
            $cfg['hooks'][$event] = $want
        }
    }

    if ($changed.Count -eq 0) { Info 'hooks.json already correct' }
    else {
        Step "$(if ($Undo) { 'remove' } else { 'update' }) hooks.json: $($changed -join ', ')"
        if ($execute) {
            Backup-AmFile $hooksPath
            $cfg | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $hooksPath -Encoding utf8
            Info 'restart Codex Desktop to load the change'
        }
    }
}

# ---- Cursor -----------------------------------------------------------------

function Invoke-AmCursor {
    $cursorHome = Join-Path $env:USERPROFILE '.cursor'
    if (-not (Test-Path -LiteralPath $cursorHome -PathType Container)) { Info 'Cursor: not installed, skipped'; return }
    # Cursor ships no agentmemory package, so its scripts are copied from the Claude
    # plugin cache -- that cache is the only source for them.
    $srcVer = Get-AmPluginVersionDir (Join-Path $env:USERPROFILE '.claude\plugins\cache\agentmemory\agentmemory')
    if (-not $srcVer) { Info 'Cursor: no agentmemory plugin cache to copy scripts from, skipped'; return }

    Section 'Cursor'
    $edits = Get-AmHookEdits -Agent cursor
    $destDir = Join-Path $cursorHome 'hooks\agentmemory'
    $destPaths = @($script:CursorScripts | ForEach-Object { Join-Path $destDir $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })

    if ($Check) {
        if ($destPaths.Count -eq 0) { Fail 'Cursor agentmemory hook scripts are not installed' }
        else {
            $missing = Test-AmHookEdits -ScriptPaths $destPaths -Edits $edits
            if ($missing.Count -eq 0) { Pass 'Cursor hook edits present' }
            else { Fail "Cursor hook edits reverted: $($missing[0])" }
        }
        return
    }

    if ($Undo) {
        if (Test-Path -LiteralPath $destDir -PathType Container) {
            Step "remove $destDir"
            if ($execute) { Remove-Item -LiteralPath $destDir -Recurse -Force }
        }
    } else {
        $null = Sync-AmStableScripts (Join-Path $srcVer.FullName 'scripts') $destDir $script:CursorScripts $edits
    }

    # mcp.json: own only the agentmemory server entry.
    $mcpPath = Join-Path $cursorHome 'mcp.json'
    $mcp = if (Test-Path -LiteralPath $mcpPath -PathType Leaf) {
        Get-Content -LiteralPath $mcpPath -Raw | ConvertFrom-Json -AsHashtable
    } else { [ordered]@{ mcpServers = [ordered]@{} } }
    if (-not $mcp.ContainsKey('mcpServers') -or $mcp['mcpServers'] -isnot [System.Collections.IDictionary]) { $mcp['mcpServers'] = [ordered]@{} }
    $wantEntry = [ordered]@{
        command = 'npx'
        args    = @('-y', '@agentmemory/mcp')
        env     = [ordered]@{
            AGENTMEMORY_URL    = Get-TsAmAgentUrl 'cursor'
            AGENTMEMORY_SECRET = '${env:AGENTMEMORY_SECRET}'
        }
    }
    $haveEntry = if ($mcp['mcpServers'].Contains('agentmemory')) { $mcp['mcpServers']['agentmemory'] } else { $null }
    $mcpChanged = $false
    if ($Undo) {
        if ($haveEntry) { Step "remove agentmemory from $mcpPath"; $mcp['mcpServers'].Remove('agentmemory') | Out-Null; $mcpChanged = $true }
    } elseif ((ConvertTo-TsCanonicalJson $haveEntry) -ne (ConvertTo-TsCanonicalJson $wantEntry)) {
        Step "$(if ($haveEntry) { 'update' } else { 'add' }) agentmemory in $mcpPath"
        $mcp['mcpServers']['agentmemory'] = $wantEntry
        $mcpChanged = $true
    } else { Info 'mcp.json already correct' }
    if ($mcpChanged -and $execute) {
        Backup-AmFile $mcpPath
        $mcp | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $mcpPath -Encoding utf8
    }

    # hooks.json: per-entry ownership. Other tools share these event arrays -- this
    # repo's own TTS hooks live in `stop` and `postToolUse` too -- so only our own
    # entries may be touched. terminal-stack's sync owns the TTS ones separately via
    # bootstrap/_merge_cursor_hooks.ps1.
    $hooksPath = Join-Path $cursorHome 'hooks.json'
    $desired = [ordered]@{
        sessionStart       = 'session-start.mjs'
        beforeSubmitPrompt = 'prompt-submit.mjs'
        preToolUse         = 'pre-tool-use.mjs'
        postToolUse        = 'post-tool-use.mjs'
        postToolUseFailure = 'post-tool-failure.mjs'
        stop               = 'stop.mjs'
        sessionEnd         = 'session-end.mjs'
    }
    $cfg = if (Test-Path -LiteralPath $hooksPath -PathType Leaf) {
        Get-Content -LiteralPath $hooksPath -Raw | ConvertFrom-Json -AsHashtable
    } else { [ordered]@{ version = 1; hooks = [ordered]@{} } }
    if (-not $cfg.ContainsKey('version')) { $cfg['version'] = 1 }
    if (-not $cfg.ContainsKey('hooks') -or $cfg['hooks'] -isnot [System.Collections.IDictionary]) { $cfg['hooks'] = [ordered]@{} }

    $changed = @()
    foreach ($event in $desired.Keys) {
        $entries = @(if ($cfg['hooks'].Contains($event)) { $cfg['hooks'][$event] } else { @() })
        $foreign = @($entries | Where-Object { -not (Test-AmOwnedCommand ([string]$_.command)) })
        if ($Undo) {
            if ($foreign.Count -ne $entries.Count) {
                $changed += $event
                if ($foreign.Count -eq 0) { $cfg['hooks'].Remove($event) | Out-Null } else { $cfg['hooks'][$event] = $foreign }
            }
            continue
        }
        $entry = [ordered]@{ command = (New-AmHookCommand 'cursor' (Join-Path $destDir $desired[$event])) }
        if ($event -eq 'preToolUse') { $entry['matcher'] = 'Shell|Read|Write|Grep' }
        # ours last, matching what the previous installer produced, so re-running either
        # tool converges instead of reordering the file every time.
        $want = @($foreign) + @($entry)
        if ((ConvertTo-TsCanonicalJson $want) -ne (ConvertTo-TsCanonicalJson $entries)) {
            $changed += $event
            $cfg['hooks'][$event] = $want
        }
    }
    if ($changed.Count -eq 0) { Info 'hooks.json already correct' }
    else {
        Step "$(if ($Undo) { 'remove' } else { 'update' }) hooks.json: $($changed -join ', ')"
        if ($execute) {
            Backup-AmFile $hooksPath
            $cfg | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $hooksPath -Encoding utf8
            Info 'restart Cursor to load the change'
        }
    }
}

# ---- run --------------------------------------------------------------------

foreach ($h in $wanted) {
    switch ($h) {
        'claude' { Invoke-AmClaude }
        'codex'  { Invoke-AmCodex }
        'cursor' { Invoke-AmCursor }
    }
}

if ($Check) { exit ([int]($script:problems -gt 0)) }

Write-Host ''
if ($script:problems -gt 0) { Write-Host "$script:problems problem(s) - see the ! lines above." -ForegroundColor Yellow }
elseif (-not $execute) { Write-Host 'Nothing changed (preview). Add -Apply to write.' -ForegroundColor White }
else { Write-Host "Done ($mode). Restart each agent: hooks and env are read at process start." -ForegroundColor Green }
