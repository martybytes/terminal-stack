# sync-windows.ps1 — PowerShell port of run_after_90-sync-windows.sh.
# Mirrors:
#   <SourceDir>\windows\**  → %USERPROFILE%\<relative path>
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

# Load the saved config (leader/theme tokens). Falls back to defaults when the
# config helper or config.json is absent (clone predating the wizard).
$cfgHelper = Join-Path $SourceDir 'bootstrap\_config.ps1'
if (Test-Path -LiteralPath $cfgHelper) { . $cfgHelper }
$tsCfg = if (Get-Command Get-TsConfig -ErrorAction SilentlyContinue) { Get-TsConfig } else { $null }
$ccTtsEnabled = $false
if ($tsCfg -and $tsCfg.ccTts -and $tsCfg.ccTts.enabled) { $ccTtsEnabled = $true }
$ccTtsStopHook = if ($ccTtsEnabled) {
@"
,
          {
            `"type`": `"command`",
            `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.claude/hooks/cc-speak.ps1 -State waiting`"
          }
"@
} else { '' }
$ccTtsStopFailureHook = if ($ccTtsEnabled) {
@"
,
          {
            `"type`": `"command`",
            `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.claude/hooks/cc-speak.ps1 -State error`"
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
    `"stop`": [
      {
        `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.cursor/hooks/cursor-tts.ps1`",
        `"timeout`": 15
      }
    ],
    `"postToolUse`": [
      {
        `"matcher`": `"AskQuestion|AskUserQuestion`",
        `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.cursor/hooks/cursor-tts-input.ps1`",
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
            `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.claude/hooks/cc-speak-input.ps1 -Event question`"
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
            `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.claude/hooks/cc-speak-input.ps1 -Event notification`"
          }
        ]
      }
    ],
    `"PermissionRequest`": [
      {
        `"matcher`": `"*`",
        `"hooks`": [
          {
            `"type`": `"command`",
            `"command`": `"pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/$WinUser/.claude/hooks/cc-speak-input.ps1 -Event permission`"
          }
        ]
      }
    ]
"@
} else { '' }
$tok = @{
    '__WIN_USER__'               = $WinUser
    '__LEADER_KEY__'             = if ($tsCfg.leaderKey)          { $tsCfg.leaderKey }          else { 'phys:Space' }
    '__LEADER_MODS__'            = if ($tsCfg.leaderMods)         { $tsCfg.leaderMods }         else { 'CTRL' }
    '__THEME_MODE__'             = if ($tsCfg.themeMode)          { $tsCfg.themeMode }          else { 'dark' }
    '__THEME_RESOLVED__'         = if ($tsCfg.resolvedTheme)      { $tsCfg.resolvedTheme }      else { 'dark' }
    '__TMUX_PREFIX__'            = if ($tsCfg.tmuxPrefixResolved) { $tsCfg.tmuxPrefixResolved } else { 'C-b' }
    '__WEZ_MUX__'                = if ($tsCfg.weztermMux)         { $tsCfg.weztermMux }         else { 'off' }
    '__WEZ_RESTORE__'            = if ($tsCfg.weztermRestore)     { $tsCfg.weztermRestore }     else { 'off' }
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

    Get-ChildItem -LiteralPath $SrcRoot -Recurse -File | ForEach-Object {
        $src = $_.FullName
        $rel = $src.Substring($SrcRoot.Length).TrimStart('\','/')

        if ($RenderTmpl -and $rel.EndsWith('.tmpl')) {
            $relOut = $rel.Substring(0, $rel.Length - 5)
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

        try {
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
            if ($RenderTmpl -and $rel.EndsWith('.tmpl') -and (Test-Path -LiteralPath $effectiveSrc)) {
                Remove-Item -LiteralPath $effectiveSrc -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Sync-MirrorTree -SrcRoot (Join-Path $SourceDir 'windows') -DstRoot $dstHome -RenderTmpl
Sync-MirrorTree -SrcRoot (Join-Path $SourceDir 'docs\kb') -DstRoot (Join-Path $localApp 'terminal-stack\docs\kb')

if (Get-Command Export-CcTtsJson -ErrorAction SilentlyContinue) {
    Export-CcTtsJson
    Write-Host "updated  $(Join-Path $env:USERPROFILE '.claude\tts\config.json')  (from config ccTts)"
}

$mergeHelper = Join-Path $SourceDir 'bootstrap\_merge_cursor_settings.ps1'
if (Test-Path -LiteralPath $mergeHelper) {
    . $mergeHelper
    Merge-TsCursorSettings
}

Write-Host "sync-windows: user=$WinUser, $created created, $updated updated, $unchanged unchanged"

# The mux server (unix domain 'main') loads its own copy of .wezterm.lua and is
# never restarted automatically — that would kill every live pane. Remind instead,
# and only when the mux is actually the thing hosting panes.
if ($weztermChanged -and $tok['__WEZ_MUX__'] -eq 'on') {
    Write-Warning 'WezTerm config changed. The GUI reloads live, but wezterm-mux-server keeps the old config for spawning panes.'
    Write-Warning "When convenient (closes all panes!): 'ts-mux restart'."
}
