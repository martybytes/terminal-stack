# _config.ps1 — terminal-stack configuration store (Windows side).
# Dot-sourced by windows-bootstrap.ps1, sync-windows.ps1, and the pwsh ts-config.
#
# Windows has no chezmoi.toml, so the store is a JSON mirror at
# %LOCALAPPDATA%\terminal-stack\config.json (next to rollback-sha). In a combined
# Windows+WSL setup the WSL run_after hook is authoritative and also writes this
# file; the pwsh side is for Windows-standalone installs. The chord→binding and
# theme mapping here mirror .chezmoi.toml.tmpl / bootstrap/_config.sh.

# ── App catalog (winget ids) ─────────────────────────────────────────────────────
# Required prerequisites (WezTerm, Nerd Font, Starship, chezmoi, Git) are always
# installed and not listed here. tmux/tldr/nvtop/lazydocker are WSL/Linux-only.
$script:TsWingetIds = @{
    eza     = 'eza-community.eza'
    fzf     = 'junegunn.fzf'
    bat     = 'sharkdp.bat'
    delta   = 'dandavison.delta'
    ripgrep = 'BurntSushi.ripgrep.MSVC'
    zoxide  = 'ajeetdsouza.zoxide'
    glow    = 'charmbracelet.glow'
    micro   = 'zyedidia.micro'
    neovim  = 'Neovim.Neovim'
    zed     = 'Zed.Zed'
    gh      = 'GitHub.cli'
    ghq     = 'x-motemen.ghq'
    lazygit = 'JesseDuffield.lazygit'
    ffmpeg  = 'Gyan.FFmpeg'
}
$script:TsAppsRecommended = @('eza','fzf','bat','delta','ripgrep','zoxide','glow','micro','neovim','gh','ghq','lazygit')
$script:TsAppsOptional    = @('zed','ffmpeg')
$script:TsAppsAll         = $script:TsAppsRecommended + $script:TsAppsOptional

function Get-TsAppDesc([string]$id) {
    switch ($id) {
        'eza'     { 'modern ls (icons, git status)' }
        'fzf'     { 'fuzzy finder (Ctrl+R, Ctrl+T)' }
        'bat'     { 'cat with syntax highlighting' }
        'delta'   { 'git diff pager' }
        'ripgrep' { 'fast recursive grep (rg)' }
        'zoxide'  { 'smarter cd (z)' }
        'glow'    { 'terminal markdown renderer' }
        'micro'   { 'nano-like terminal editor' }
        'neovim'  { 'neovim editor (nvim)' }
        'zed'     { 'Zed GUI editor' }
        'gh'      { 'GitHub CLI (org enumeration for wso)' }
        'ghq'     { 'clone into the derived workspace path' }
        'lazygit' { 'git TUI (the wso status hand-off)' }
        'ffmpeg'  { 'ffplay for Claude TTS on Windows (Gyan.FFmpeg)' }
        default   { '' }
    }
}

# ── chord / theme mapping ────────────────────────────────────────────────────────
function ConvertTo-TsLeader([string]$chord) {
    if (-not $chord) { $chord = 'ctrl-space' }
    $parts = $chord.Split('-')
    $key = $parts[-1]
    $mods = @()
    if ($parts.Count -gt 1) {
        foreach ($m in $parts[0..($parts.Count - 2)]) {
            switch ($m.ToLower()) {
                'ctrl'  { $mods += 'CTRL' }
                'alt'   { $mods += 'ALT' }
                'shift' { $mods += 'SHIFT' }
                'super' { $mods += 'SUPER' }
                'win'   { $mods += 'SUPER' }
                'cmd'   { $mods += 'SUPER' }
            }
        }
    }
    $wkey = if ($key.ToLower() -eq 'space') { 'phys:Space' } else { $key }
    return @{ key = $wkey; mods = ($mods -join '|') }
}

function ConvertTo-TsTmuxPrefix([string]$chord) {
    if (-not $chord) { $chord = 'ctrl-b' }
    $parts = $chord.Split('-')
    $key = $parts[-1]
    $pre = ''
    if ($parts.Count -gt 1) {
        foreach ($m in $parts[0..($parts.Count - 2)]) {
            switch ($m.ToLower()) {
                'ctrl'  { $pre += 'C-' }
                'alt'   { $pre += 'M-' }
                'shift' { $pre += 'S-' }
            }
        }
    }
    $k = if ($key.ToLower() -eq 'space') { 'Space' } else { $key }
    return "$pre$k"
}

function Get-TsResolvedTheme([string]$mode) {
    switch ($mode) {
        'light' { return 'light' }
        'dark'  { return 'dark' }
    }
    # follow: read the Windows apps theme; default dark on any failure.
    try {
        $v = Get-ItemPropertyValue 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize' `
             -Name AppsUseLightTheme -ErrorAction Stop
        if ($v -eq 1) { return 'light' } else { return 'dark' }
    } catch { return 'dark' }
}

# ── store I/O ────────────────────────────────────────────────────────────────────
function Get-TsConfigPath { Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json' }

function Get-TsConfig {
    $p = Get-TsConfigPath
    if (Test-Path $p) {
        try { return (Get-Content $p -Raw | ConvertFrom-Json) } catch {}
    }
    return [pscustomobject]@{
        leaderChord = 'ctrl-space'; themeMode = 'dark'; tmuxPrefix = 'ctrl-b'; apps = @()
    }
}

function Save-TsConfig {
    param(
        [string]$LeaderChord = 'ctrl-space',
        [string]$ThemeMode   = 'dark',
        [string]$TmuxPrefix  = 'ctrl-b',
        [string[]]$Apps      = @(),
        $CcTts                = $null
    )
    $l = ConvertTo-TsLeader $LeaderChord
    if (-not $CcTts) {
        $existing = Get-TsConfig
        if ($existing.ccTts) { $CcTts = $existing.ccTts } else { $CcTts = Get-CcTtsDefaults }
    }
    $obj = [ordered]@{
        leaderChord        = $LeaderChord
        leaderKey          = $l.key
        leaderMods         = $l.mods
        themeMode          = $ThemeMode
        resolvedTheme      = (Get-TsResolvedTheme $ThemeMode)
        tmuxPrefix         = $TmuxPrefix
        tmuxPrefixResolved = (ConvertTo-TsTmuxPrefix $TmuxPrefix)
        apps               = @($Apps)
        ccTts              = $CcTts
    }
    $p = Get-TsConfigPath
    New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
    ($obj | ConvertTo-Json) | Set-Content -Encoding UTF8 $p
    return $obj
}

# ── Wizard prompts (env vars TS_LEADER / TS_THEME / TS_APPS skip each) ──────────
function Read-TsLeader {
    if ($env:TS_LEADER) { return $env:TS_LEADER }
    Write-Host ''
    Write-Host 'Leader key (WezTerm) — prefix for pane / tab / workspace commands:'
    Write-Host '  1) Ctrl+Space  (recommended)'
    Write-Host '  2) Ctrl+A'
    Write-Host '  3) Ctrl+B'
    Write-Host '  4) custom (type a chord like ctrl-x or alt-space)'
    switch (Read-Host 'Choose [1]') {
        '2'     { 'ctrl-a' }
        '3'     { 'ctrl-b' }
        '4'     { $c = Read-Host 'Enter chord (mod-key, e.g. ctrl-x)'; if ($c) { $c } else { 'ctrl-space' } }
        default { 'ctrl-space' }
    }
}
function Read-TsTheme {
    if ($env:TS_THEME) { return $env:TS_THEME }
    Write-Host ''
    Write-Host 'Theme:'
    Write-Host '  1) dark   (Catppuccin Mocha, recommended)'
    Write-Host '  2) light  (Catppuccin Latte)'
    Write-Host '  3) follow OS appearance'
    switch (Read-Host 'Choose [1]') {
        '2'     { 'light' }
        '3'     { 'follow' }
        default { 'dark' }
    }
}
function Read-TsApps {
    if ($env:TS_APPS) {
        switch ($env:TS_APPS) {
            'recommended' { return $script:TsAppsRecommended }
            'all'         { return $script:TsAppsAll }
            'none'        { return @() }
            default       { return ($env:TS_APPS -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
        }
    }
    Write-Host ''
    Write-Host 'Optional CLI tools (WezTerm, font, Starship, chezmoi — always installed):'
    Write-Host '  Note: winget may prompt for administrator elevation.'
    Write-Host ('  1) Install recommended set: ' + ($script:TsAppsRecommended -join ', '))
    Write-Host '  2) Customize (choose each)'
    Write-Host '  3) Skip all optional apps'
    switch (Read-Host 'Choose [1]') {
        '2' {
            $sel = @()
            foreach ($id in $script:TsAppsAll) {
                $def = if ($script:TsAppsRecommended -contains $id) { 'Y' } else { 'n' }
                $a = Read-Host ('  install {0} — {1}? [{2}]' -f $id, (Get-TsAppDesc $id), $def)
                if (-not $a) { $a = $def }
                if ($a -match '^(y|yes)$') { $sel += $id }
            }
            return $sel
        }
        '3' { return @() }
        default { return $script:TsAppsRecommended }
    }
}

# Install the selected toggleable apps via winget (catalog id -> winget id).
function Install-TsApps([string[]]$Apps) {
    if (-not $Apps -or $Apps.Count -eq 0) {
        Write-Host '==> No optional apps selected; skipping app install'
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning 'winget not available; recorded selection only.'
        return
    }
    foreach ($id in $Apps) {
        if ($script:TsWingetIds.ContainsKey($id)) {
            $wid = $script:TsWingetIds[$id]
            Write-Host "==> winget install $wid"
            & winget install --id $wid --exact --silent --accept-source-agreements --accept-package-agreements 2>&1 |
                Select-Object -Last 2
        }
    }
}

# Refresh only resolvedTheme from the live OS theme (used by ts-update for follow).
function Update-TsResolvedTheme {
    $c = Get-TsConfig
    Save-TsConfig -LeaderChord $c.leaderChord -ThemeMode $c.themeMode `
                  -TmuxPrefix $c.tmuxPrefix -Apps @($c.apps) -CcTts $c.ccTts | Out-Null
}

# ── Claude Code TTS (Kokoro / Chatterbox / edge) ────────────────────────────────
function Get-CcTtsDefaults {
    [ordered]@{
        enabled     = $false
        engine      = 'kokoro'
        messageMode = 'template'
        events      = @('waiting', 'error', 'question', 'permission')
        prefixClaude = 'Claude'
        prefixCursor = 'Cursor'
        prefixClaudeEnabled = $true
        prefixCursorEnabled = $true
        includeProject = $true
        excitement  = 0.25
        kokoro      = [ordered]@{
            url = 'http://127.0.0.1:8880'; voice = 'am_adam'; speed = 1.0
            format = 'mp3'; timeoutSec = 15
        }
        chatterbox  = [ordered]@{
            url = 'http://127.0.0.1:8881'; voice = 'adam'; energy = 0.25
            cfgWeight = 0.5; temperature = 0.6; timeoutSec = 60
        }
        edge        = [ordered]@{ enabled = $true; voice = 'en-US-AndrewMultilingualNeural' }
        templates   = [ordered]@{
            waiting    = "Done in {project}. I'm waiting for you."
            error      = 'Error in {project}. You may want to look.'
            question   = 'I have a question for you.'
            permission = 'Permission needed in {project}.'
        }
        maxChars    = 120
        debounceSec = 5
        player      = 'auto'
    }
}

function ConvertTo-CcTtsRuntimeJson {
    param($Tts)
    [ordered]@{
        enabled = [bool]$Tts.enabled
        engine = $Tts.engine
        events = @($Tts.events)
        sources = [ordered]@{
            claude = [ordered]@{
                prefixEnabled = [bool]$Tts.prefixClaudeEnabled
                prefix = $Tts.prefixClaude
            }
            cursor = [ordered]@{
                prefixEnabled = [bool]$Tts.prefixCursorEnabled
                prefix = $Tts.prefixCursor
            }
        }
        announce = [ordered]@{
            includeProject = [bool]$Tts.includeProject
            messageMode = $Tts.messageMode
            templates = $Tts.templates
        }
        excitement = [double]$Tts.excitement
        kokoro = $Tts.kokoro
        chatterbox = $Tts.chatterbox
        edge = $Tts.edge
        maxChars = [int]$Tts.maxChars
        debounceSec = [int]$Tts.debounceSec
        player = $Tts.player
    }
}

function Get-CcTtsConfig {
    $c = Get-TsConfig
    if ($c.ccTts) { return $c.ccTts }
    return (Get-CcTtsDefaults)
}

function Export-CcTtsJson {
    param([string]$Path = (Join-Path $env:USERPROFILE '.claude\tts\config.json'))
    $tts = Get-CcTtsConfig
    $runtime = ConvertTo-CcTtsRuntimeJson $tts
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($runtime | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-CcTtsKokoroProbe {
    param([string]$Url = 'http://127.0.0.1:8880')
    foreach ($suffix in @('/health', '/v1/models', '/docs')) {
        try {
            $r = Invoke-WebRequest -Uri ($Url.TrimEnd('/') + $suffix) -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch {}
    }
    return $false
}

function Show-CcTtsConfig {
    $tts = Get-CcTtsConfig
    Write-Host 'Claude Code TTS:'
    $tts | ConvertTo-Json -Depth 6 | Write-Host
    if (Test-CcTtsKokoroProbe -Url $tts.kokoro.url) {
        Write-Host "kokoro: up ($($tts.kokoro.url))"
    } else {
        Write-Host "kokoro: down ($($tts.kokoro.url))"
    }
    if (Get-Command edge-tts -ErrorAction SilentlyContinue) { Write-Host 'edge-tts: installed' }
}

function Read-TsCcTts {
    if ($env:TS_CC_TTS) { return $env:TS_CC_TTS }
    Write-Host ''
    Write-Host 'Claude Code voice notifications (local Kokoro TTS, am_adam)?'
    Write-Host '  Requires Kokoro on http://127.0.0.1:8880 (Docker). Does not install containers.'
    if (Test-CcTtsKokoroProbe) {
        Write-Host '  Kokoro probe: OK'
        Write-Host '  1) Enable (am_adam, waiting+error)  [recommended]'
    } else {
        Write-Host '  Kokoro probe: not reachable'
        Write-Host '  1) Enable (am_adam, waiting+error)'
    }
    Write-Host '  2) Enable anyway (start Kokoro later)'
    Write-Host '  3) Skip'
    switch (Read-Host 'Choose [3]') {
        '1' { 'on' }
        '2' { 'on' }
        default { 'off' }
    }
}

function Set-CcTtsWizardChoice {
    param([string]$Choice)
    $tts = Get-CcTtsDefaults
    if ($Choice -eq 'on') { $tts.enabled = $true }
    return $tts
}

function Invoke-TsConfigTts {
    param(
        [string]$Sub,
        [string]$Arg,
        [string]$Arg2,
        [scriptblock]$Apply
    )
    $tts = Get-CcTtsConfig
    switch ($Sub) {
        'show' { Show-CcTtsConfig; return }
        'on'   { $tts.enabled = $true }
        'off'  { $tts.enabled = $false }
        'engine' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts engine kokoro|chatterbox|auto'; return }
            $tts.engine = $Arg
        }
        'message' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts message template|hook'; return }
            $tts.messageMode = $Arg
        }
        'voice' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts voice <kokoro-voice>'; return }
            $tts.kokoro.voice = $Arg
        }
        'voice-chatter' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts voice-chatter <name>'; return }
            $tts.chatterbox.voice = $Arg
        }
        'energy' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts energy <0-1>'; return }
            $tts.chatterbox.energy = [double]$Arg
            $tts.excitement = [double]$Arg
        }
        'excitement' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts excitement <0-1>'; return }
            $tts.excitement = [double]$Arg
            $tts.chatterbox.energy = [double]$Arg
        }
        'prefix' {
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: ts-config tts prefix claude|cursor on|off|<label>'; return }
            switch ($Arg) {
                'claude' {
                    switch ($Arg2) {
                        'on'  { $tts.prefixClaudeEnabled = $true }
                        'off' { $tts.prefixClaudeEnabled = $false }
                        default { $tts.prefixClaude = $Arg2; $tts.prefixClaudeEnabled = $true }
                    }
                }
                'cursor' {
                    switch ($Arg2) {
                        'on'  { $tts.prefixCursorEnabled = $true }
                        'off' { $tts.prefixCursorEnabled = $false }
                        default { $tts.prefixCursor = $Arg2; $tts.prefixCursorEnabled = $true }
                    }
                }
                default { Write-Warning 'expected claude or cursor'; return }
            }
        }
        'project' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts project on|off'; return }
            $tts.includeProject = ($Arg -eq 'on')
        }
        'template' {
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: ts-config tts template waiting|error|question|permission "…"'; return }
            if (-not $tts.templates) { $tts.templates = @{} }
            switch ($Arg) {
                'waiting'    { $tts.templates.waiting = $Arg2 }
                'error'      { $tts.templates.error = $Arg2 }
                'question'   { $tts.templates.question = $Arg2 }
                'permission' { $tts.templates.permission = $Arg2 }
                default { Write-Warning "unknown template event '$Arg'"; return }
            }
        }
        'url' {
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: ts-config tts url kokoro|chatterbox <url>'; return }
            switch ($Arg) {
                'kokoro'     { $tts.kokoro.url = $Arg2 }
                'chatterbox' { $tts.chatterbox.url = $Arg2 }
                default      { Write-Warning 'expected kokoro or chatterbox'; return }
            }
        }
        'events' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts events waiting,error,question,permission'; return }
            $tts.events = @($Arg -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        'test' {
            $test = Join-Path $env:USERPROFILE '.claude\hooks\cc-tts-test.ps1'
            if (Test-Path -LiteralPath $test) {
                if ($Arg -eq '--source' -and $Arg2) { & $test -Source $Arg2 }
                else { & $test }
            } else {
                Write-Warning "cc-tts-test.ps1 not found at $test (run sync-windows / chezmoi apply)"
            }
            return
        }
        'reset' { $tts = Get-CcTtsDefaults }
        default {
            Write-Warning "ts-config tts: unknown subcommand '$Sub' (show, on, off, test, reset, ...)"
            return
        }
    }
    if ($Sub -in 'on','off','engine','message','voice','voice-chatter','energy','excitement','url','events','prefix','project','template','reset') {
        & $Apply $tts
    }
}
