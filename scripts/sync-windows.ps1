# sync-windows.ps1 — PowerShell port of run_after_90-sync-windows.sh.
# Mirrors:
#   <SourceDir>\windows\**  → %USERPROFILE%\<relative path>
#   <SourceDir>\dot_codex\** → %USERPROFILE%\.codex\<relative path>
#   <SourceDir>\docs\kb\**  → %LOCALAPPDATA%\terminal-stack\docs\kb\<relative path>
# with the same .tmpl __WIN_USER__ substitution and .bak.yyyyMMdd[.N] backup
# convention as the bash hook. Lets Windows-only users (no WSL) update the stack
# via install.ps1 or Update-TerminalStack without ever invoking chezmoi.
#
# The bash hook (run_after_90-sync-windows.sh) is still the source of truth
# when chezmoi apply runs from WSL — this script is a parallel Windows-native
# code path, not a replacement.
#
# Idempotent: only writes targets whose bytes differ.

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceDir,
    [string]$WinUser = $env:USERNAME
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($WinUser)) {
    throw "sync-windows: -WinUser is empty and `$env:USERNAME is unset."
}

$dstHome = $env:USERPROFILE
if (-not $dstHome -or -not (Test-Path -LiteralPath $dstHome -PathType Container)) {
    throw "sync-windows: `$env:USERPROFILE ($dstHome) is not a valid directory."
}

$localApp = $env:LOCALAPPDATA
if (-not $localApp) {
    throw 'sync-windows: $env:LOCALAPPDATA is unset.'
}
$canonicalSource = Join-Path $localApp 'terminal-stack\stack'
if ((Test-Path -LiteralPath (Join-Path $SourceDir '.git')) -and
    $SourceDir.TrimEnd('\') -eq $canonicalSource.TrimEnd('\')) {
    $dirtySource = @(& git -C $SourceDir status --porcelain 2>$null)
    if ($dirtySource.Count) {
        throw "sync-windows: canonical runtime clone is dirty; refusing to deploy uncommitted files:`n$($dirtySource -join "`n")"
    }
}

# Load the saved config (leader/theme tokens). Falls back to defaults when the
# config helper or config.json is absent (clone predating the wizard).
$cfgHelper = Join-Path $SourceDir 'bootstrap\_config.ps1'
if (Test-Path -LiteralPath $cfgHelper) { . $cfgHelper }
$tsCfg = if (Get-Command Get-TsConfig -ErrorAction SilentlyContinue) { Get-TsConfig } else { $null }
$ccTtsEnabled = $false
if ($tsCfg -and $tsCfg.ccTts -and $tsCfg.ccTts.enabled) { $ccTtsEnabled = $true }
if ($ccTtsEnabled) {
    $ttsExe = Join-Path $localApp 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
    if (-not (Test-Path -LiteralPath $ttsExe)) {
        $installer = Join-Path $SourceDir 'bootstrap\install-tts-daemon.ps1'
        if (-not (Test-Path -LiteralPath $installer)) {
            throw "sync-windows: TTS is enabled but installer is missing: $installer"
        }
        $daemonEnabled = [bool]($tsCfg.ccTts.daemon -and $tsCfg.ccTts.daemon.enabled)
        $installArgs = if ($daemonEnabled) { @() } else { @('-NoStart', '-NoAutostart') }
        & $installer @installArgs
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ttsExe)) {
            throw 'sync-windows: failed to install terminal-stack-tts.exe'
        }
    }
}
$ccTtsStopHook = if ($ccTtsEnabled) {
@"
,
          {
            `"type`": `"command`",
            `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event stop --state waiting`"
          }
"@
} else { '' }
$ccTtsStopFailureHook = if ($ccTtsEnabled) {
@"
,
          {
            `"type`": `"command`",
            `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event stop_failure --state error`"
          }
"@
} else { '' }
$ccTtsCursorHooks = if ($ccTtsEnabled) {
@"
{
    `"afterFileEdit`": [
      {
        `"command`": `"cat > /dev/null`",
        `"timeout`": 1
      }
    ],
    `"afterAgentResponse`": [
      {
        `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source cursor --event cursor_response --state waiting`",
        `"timeout`": 15
      }
    ],
    `"stop`": [
      {
        `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source cursor --event cursor_stop --state waiting`",
        `"timeout`": 15
      }
    ],
    `"postToolUse`": [
      {
        `"matcher`": `"AskQuestion|AskUserQuestion`",
        `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source cursor --event cursor_question --state question`",
        `"timeout`": 15
      }
    ]
  }
"@
} else { '{}' }
$ccTtsPreToolUseTts = if ($ccTtsEnabled) {
@"
,
      {
        `"matcher`": `"AskUserQuestion`",
        `"hooks`": [
          {
            `"type`": `"command`",
            `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event question --state question`"
          }
        ]
      }
"@
} else { '' }
$ccTtsInputHooks = if ($ccTtsEnabled) {
@"
,
    `"Notification`": [
      {
        `"matcher`": `"*`",
        `"hooks`": [
          {
            `"type`": `"command`",
            `"command`": `"C:/Users/$WinUser/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe hook --source claude --event notification --state question`"
          }
        ]
      }
    ]
"@
} else { '' }
# Ghostty's config format has no conditionals and Windows mirror files get token
# substitution, not Go templates, so themeMode is mapped to a theme here - the
# twin of the `case` in run_after_90-sync-windows.sh. A split `dark:...,light:...`
# theme always tracks the OS, so `follow` cannot be expressed by pinning
# window-theme and an explicit mode cannot be expressed by a split theme.
$script:tsGhosttyOn = if ($tsCfg.ghosttyConfig) { $tsCfg.ghosttyConfig } else { 'on' }
$ghosttyThemeMode = if ($tsCfg.themeMode) { $tsCfg.themeMode } else { 'dark' }
$ghosttyTheme, $ghosttyWindowTheme = switch ($ghosttyThemeMode) {
    'light'  { 'vs-code-light-modern', 'light' }
    'follow' { 'dark:Catppuccin Mocha,light:vs-code-light-modern', 'auto' }
    default  { 'Catppuccin Mocha', 'dark' }
}
$tok = @{
    '__WIN_USER__'               = $WinUser
    '__LEADER_KEY__'             = if ($tsCfg.leaderKey)          { $tsCfg.leaderKey }          else { 'phys:Space' }
    '__LEADER_MODS__'            = if ($tsCfg.leaderMods)         { $tsCfg.leaderMods }         else { 'CTRL' }
    '__THEME_MODE__'             = if ($tsCfg.themeMode)          { $tsCfg.themeMode }          else { 'dark' }
    '__THEME_RESOLVED__'         = if ($tsCfg.resolvedTheme)      { $tsCfg.resolvedTheme }      else { 'dark' }
    '__TMUX_PREFIX__'            = if ($tsCfg.tmuxPrefixResolved) { $tsCfg.tmuxPrefixResolved } else { 'C-b' }
    '__WEZ_MUX__'                = if ($tsCfg.weztermMux)         { $tsCfg.weztermMux }         else { 'off' }
    '__WEZ_RESTORE__'            = if ($tsCfg.weztermRestore)     { $tsCfg.weztermRestore }     else { 'off' }
    '__GHOSTTY_THEME__'          = $ghosttyTheme
    '__GHOSTTY_WINDOW_THEME__'   = $ghosttyWindowTheme
    '__CC_TTS_STOP_HOOK__'       = $ccTtsStopHook
    '__CC_TTS_STOPFAILURE_HOOK__'= $ccTtsStopFailureHook
    '__CC_TTS_CURSOR_HOOKS__'    = $ccTtsCursorHooks
    '__CC_TTS_PRETOOLUSE_TTS__'  = $ccTtsPreToolUseTts
    '__CC_TTS_INPUT_HOOKS__'     = $ccTtsInputHooks
}

$today = Get-Date -Format 'yyyyMMdd'
$created = 0
$updated = 0
$unchanged = 0
$weztermChanged = $false

function Get-BackupPath([string]$dst, [string]$stamp) {
    $bak = "$dst.bak.$stamp"
    if (-not (Test-Path -LiteralPath $bak)) { return $bak }
    $n = 1
    while (Test-Path -LiteralPath "$dst.bak.$stamp.$n") { $n++ }
    return "$dst.bak.$stamp.$n"
}

function Sync-MirrorTree {
    param(
        [Parameter(Mandatory)][string]$SrcRoot,
        [Parameter(Mandatory)][string]$DstRoot,
        [switch]$RenderTmpl
    )

    if (-not (Test-Path -LiteralPath $SrcRoot -PathType Container)) {
        Write-Warning "sync-windows: $SrcRoot not found; skipping."
        return
    }

    Get-ChildItem -LiteralPath $SrcRoot -Recurse -File | Where-Object {
        $_.Extension -notin '.pyc', '.pyo' -and
        $_.FullName -notmatch '[\\/]__pycache__[\\/]'
    } | ForEach-Object {
            $src = $_.FullName
            $rel = $src.Substring($SrcRoot.Length).TrimStart('\','/')

            # ghosttyConfig=off: skip the subtree, never delete it. Twin of the
            # same guard in run_after_90-sync-windows.sh; removing what is already
            # there is tstack config's job, so a hand-written config on a box that
            # never opted in is untouched by a sync.
            if ($script:tsGhosttyOn -ne 'on' -and
                ($rel -replace '\\', '/') -like 'AppData/Local/ghostty/*') { return }
            $rendered = $null
            $modified = $null

            $isModifier = (Split-Path -Leaf $rel).StartsWith('modify_')
            if ($RenderTmpl -and $rel.EndsWith('.tmpl')) {
                $relOut = $rel.Substring(0, $rel.Length - 5)
                if ($isModifier) {
                    $relDir = Split-Path -Parent $relOut
                    $relLeaf = (Split-Path -Leaf $relOut).Substring(7)
                    if ($relLeaf.StartsWith('private_')) { $relLeaf = $relLeaf.Substring(8) }
                    $relOut = if ($relDir) { Join-Path $relDir $relLeaf } else { $relLeaf }
                }
            $rendered = [IO.Path]::GetTempFileName()
            $content = (Get-Content -LiteralPath $src -Raw)
            # String .Replace, not -replace: regex replacement would interpret
            # $1/$& in token values and silently corrupt the render.
            foreach ($k in $tok.Keys) { $content = $content.Replace($k, [string]$tok[$k]) }
            $content | Set-Content -LiteralPath $rendered -NoNewline -Encoding utf8
            $effectiveSrc = $rendered
        } else {
            $relOut = $rel
            $effectiveSrc = $src
        }

        $dst = Join-Path $DstRoot $relOut
            $dstDir = Split-Path -Parent $dst
            if ($isModifier) {
                $modified = [IO.Path]::GetTempFileName()
                $live = if (Test-Path -LiteralPath $dst -PathType Leaf) {
                    Get-Content -LiteralPath $dst -Raw
                } else { '' }
                $python = Get-Command python -ErrorAction SilentlyContinue
                $pythonArgs = @()
                if (-not $python) {
                    $python = Get-Command py -ErrorAction SilentlyContinue
                    $pythonArgs = @('-3')
                }
                if (-not $python) { throw "sync-windows: Python 3 required to merge $dst" }
                $merged = $live | & $python.Source @pythonArgs $effectiveSrc
                if ($LASTEXITCODE -ne 0) { throw "sync-windows: modifier failed for $dst" }
                (($merged -join "`n") + "`n") |
                    Set-Content -LiteralPath $modified -NoNewline -Encoding utf8
                $effectiveSrc = $modified
            }

        try {
            # Claude Code writes this file too (model, enabledPlugins, permissions,
            # env, …). Splice our keys in rather than copy the whole file over the
            # top of its state — see bootstrap\_merge_claude_settings.ps1.
            if ($relOut -eq '.claude\settings.json') {
                Merge-TsClaudeSettings -FragmentPath $effectiveSrc -LivePath $dst
                return
            }
            # Same problem one level deeper: agentmemory's Cursor hooks share the
            # `stop` and `postToolUse` event arrays with our TTS hooks, so ownership
            # is per entry — see bootstrap\_merge_cursor_hooks.ps1.
            if ($relOut -eq '.cursor\hooks.json') {
                Merge-TsCursorHooks -FragmentPath $effectiveSrc -LivePath $dst
                return
            }
            if (Test-Path -LiteralPath $dst -PathType Leaf) {
                $srcHash = (Get-FileHash -LiteralPath $effectiveSrc -Algorithm SHA256).Hash
                $dstHash = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
                if ($srcHash -eq $dstHash) {
                    $script:unchanged++
                    return
                }
                $bak = Get-BackupPath -dst $dst -stamp $today
                Copy-Item -LiteralPath $dst -Destination $bak -Force
                Copy-Item -LiteralPath $effectiveSrc -Destination $dst -Force
                $script:updated++
                if ($relOut -like '.wezterm*') { $script:weztermChanged = $true }
                Write-Host "updated  $dst  (backup: $bak)"
            } else {
                if (-not (Test-Path -LiteralPath $dstDir -PathType Container)) {
                    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
                }
                Copy-Item -LiteralPath $effectiveSrc -Destination $dst -Force
                $script:created++
                if ($relOut -like '.wezterm*') { $script:weztermChanged = $true }
                Write-Host "created  $dst"
            }
            } finally {
                foreach ($tmp in @($rendered, $modified)) {
                    if ($tmp -and (Test-Path -LiteralPath $tmp)) {
                        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
                    }
                }
            }
    }
}

# Loaded before the mirror runs: Sync-MirrorTree routes .claude\settings.json and
# .cursor\hooks.json through these instead of overwriting them.
foreach ($helper in @('bootstrap\_merge_claude_settings.ps1', 'bootstrap\_merge_cursor_hooks.ps1')) {
    $helperPath = Join-Path $SourceDir $helper
    if (-not (Test-Path -LiteralPath $helperPath)) {
        throw "sync-windows: missing $helperPath"
    }
    . $helperPath
}

Sync-MirrorTree -SrcRoot (Join-Path $SourceDir 'windows') -DstRoot $dstHome -RenderTmpl
Sync-MirrorTree -SrcRoot (Join-Path $SourceDir 'dot_codex') -DstRoot (Join-Path $dstHome '.codex') -RenderTmpl
Sync-MirrorTree -SrcRoot (Join-Path $SourceDir 'docs\kb') -DstRoot (Join-Path $localApp 'terminal-stack\docs\kb')

if (Get-Command Export-CcTtsJson -ErrorAction SilentlyContinue) {
    Export-CcTtsJson
    Write-Host "updated  $(Join-Path $env:USERPROFILE '.claude\tts\config.json')  (from config ccTts)"
}

# Which prompt. The mirror above has already written this stack's own
# starship.toml with __THEME_RESOLVED__ substituted; if a starship PRESET is
# chosen instead, replace it with the preset's own content.
#
# Twin of the block in run_after_90-sync-windows.sh, and it exists for the same
# reason the mirror does: a combined machine showing tokyo-night in WSL and this
# stack's prompt in PowerShell is exactly the split-brain the mirror prevents.
#
# `starship preset` writes to STDOUT here rather than through -o: -o refuses to
# overwrite an existing file, and the destination almost always exists.
$preset = if ($tsCfg.starshipPreset) { [string]$tsCfg.starshipPreset } else { 'terminal-stack' }
if ($preset -ne 'terminal-stack') {
    $starship = Get-Command starship -ErrorAction SilentlyContinue
    if (-not $starship) {
        Write-Warning "starship is not on PATH, so the '$preset' preset was not rendered; kept this stack's prompt."
    } else {
        $starDst = Join-Path $dstHome '.config\starship.toml'
        $body = & $starship.Source preset $preset 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $body) {
            Write-Warning "starship has no preset named '$preset'; kept this stack's prompt."
        } else {
            $text = ($body -join "`n") + "`n"
            $current = if (Test-Path -LiteralPath $starDst) {
                Get-Content -LiteralPath $starDst -Raw
            } else { $null }
            if ($current -ne $text) {
                if ($null -ne $current) {
                    Copy-Item -LiteralPath $starDst -Destination (Get-BackupPath $starDst (Get-Date -Format 'yyyyMMdd')) -Force
                }
                $dir = Split-Path -Parent $starDst
                if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
                Set-Content -LiteralPath $starDst -Value $text -NoNewline -Encoding UTF8
                Write-Host "updated  $starDst  (starship preset: $preset)"
            }
        }
    }
}

$mergeHelper = Join-Path $SourceDir 'bootstrap\_merge_cursor_settings.ps1'
if (Test-Path -LiteralPath $mergeHelper) {
    . $mergeHelper
    Merge-TsCursorSettings
}

# The interpreter tstack runs on, for the agent wiring.
function Get-TsSyncPython {
    foreach ($name in @('python', 'python3')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

# Enabled user-global coding-agent integrations are reconciled on update. Disabled
# tools are not installed or contacted, which is what lets each computer differ.
$agentsScript = Join-Path $SourceDir 'tstack/main.py'
$headroomEnabled = if (Get-Command Get-TsAgentSetting -ErrorAction SilentlyContinue) { (Get-TsAgentSetting headroomEnabled) -eq 'on' } else { $false }
$cavemanEnabled = if (Get-Command Get-TsAgentSetting -ErrorAction SilentlyContinue) { (Get-TsAgentSetting cavemanEnabled) -eq 'on' } else { $false }
$agentmemoryEnabled = if (Get-Command Get-TsAgentSetting -ErrorAction SilentlyContinue) { (Get-TsAgentSetting agentmemoryEnabled) -eq 'on' } else { $false }
$agentsPython = Get-TsSyncPython
if ($agentsPython -and (Test-Path -LiteralPath $agentsScript)) {
    if ($headroomEnabled) {
        & $agentsPython $agentsScript agents headroom status (Get-TsAgentSetting headroomCursorMode) *> $null
        if ($LASTEXITCODE -ne 0) { & $agentsPython $agentsScript agents headroom repair (Get-TsAgentSetting headroomCursorMode) | Out-Host }
    }
    if ($cavemanEnabled) {
        & $agentsPython $agentsScript agents caveman status *> $null
        if ($LASTEXITCODE -ne 0) { & $agentsPython $agentsScript agents caveman repair | Out-Host }
    }
}

# AgentMemory's hook scripts live in vendor plugin caches, so an upgrade silently
# reverts terminal-stack's retrieval edits. The low-level check avoids network work
# when the pinned plugin is already installed and healthy.
# Forward slash on purpose: PowerShell accepts it and it cannot be mangled by a
# generator that treats backslash-t as a tab -- which is exactly how this line was
# first written, and Test-Path then turned the mistake into a silent no-op.
$amScript = Join-Path $SourceDir 'bootstrap/ts-agentmemory.ps1'
if (-not (Test-Path -LiteralPath $amScript)) { throw "sync-windows: missing $amScript" }
if ($agentmemoryEnabled) {
    & $amScript -Check *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'sync-windows: repairing agentmemory hook wiring'
        & $amScript -Apply | Out-Host
    }
}

Write-Host "sync-windows: user=$WinUser, $created created, $updated updated, $unchanged unchanged"

# The mux server (unix domain 'main') loads its own copy of .wezterm.lua and is
# never restarted automatically — that would kill every live pane. Remind instead,
# and only when the mux is actually the thing hosting panes.
if ($weztermChanged -and $tok['__WEZ_MUX__'] -eq 'on') {
    Write-Warning 'WezTerm config changed. The GUI reloads live, but wezterm-mux-server keeps the old config for spawning panes.'
    Write-Warning "When convenient (closes all panes!): 'tstack mux restart'."
}

# A failed -Check followed by a successful repair leaves PowerShell's process-wide
# LASTEXITCODE at 1. The sync itself succeeded; do not make tstack update report failure.
$global:LASTEXITCODE = 0
