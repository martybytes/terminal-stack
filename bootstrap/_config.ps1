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

# The binary an app id actually puts on PATH. Mostly identity; a few differ.
function Get-TsAppBin([string]$id) {
    switch ($id) {
        'ripgrep' { 'rg' }
        'neovim'  { 'nvim' }
        default   { $id }
    }
}

# Apps this machine is expected to have but doesn't. Two sources, deliberately:
# the saved selection (an install that failed or a tool later removed), AND
# anything since added to the recommended set. The second half is the point — a
# machine configured before a tool joined the catalog would otherwise never get
# it however many times ts-update ran, which is exactly how gh/ghq/lazygit would
# have missed every existing install.
function Get-TsAppsPending {
    $saved = @()
    try { $saved = @((Get-TsConfig).apps) } catch {}
    $seen = @{}; $out = @()
    foreach ($id in ($saved + $script:TsAppsRecommended)) {
        if (-not $id) { continue }
        if ($seen[$id]) { continue }
        $seen[$id] = $true
        if (Get-Command (Get-TsAppBin $id) -ErrorAction SilentlyContinue) { continue }
        # Only offer what this platform can actually install.
        if (-not $script:TsWingetIds.ContainsKey($id)) { continue }
        $out += $id
    }
    return $out
}

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
    $existing = Get-TsConfig
    if (-not $CcTts) {
        if ($existing.ccTts) { $CcTts = $existing.ccTts } else { $CcTts = Get-CcTtsDefaults }
    }
    # Callers that don't pass -TmuxPrefix (e.g. the Windows bootstrap re-run)
    # must not silently reset a prefix the WSL side already configured.
    if (-not $PSBoundParameters.ContainsKey('TmuxPrefix') -and $existing.tmuxPrefix) {
        $TmuxPrefix = $existing.tmuxPrefix
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

# The menu prompt every wizard question uses. Marks the default and says how to
# take it, accepts the option's name as well as its number, and RE-PROMPTS on
# anything else — the old `switch (Read-Host 'Choose [1]') { default {...} }`
# silently selected option 1 for a typo, a stray 'y', or a fat-fingered '9',
# which is the opposite of what a default is for.
#
# One definition of "is there a human here" for every prompt in the wizard, so
# headless behaviour can't drift between questions. POSIX twin: the `> /dev/tty`
# probe in _wizard.sh ts_tty_prompt.
function Test-TsInteractive { -not [Console]::IsInputRedirected }

# Map one typed answer onto an option Key; $null when it matches nothing.
# Split out from the prompt loop so the matching rules are testable without a
# terminal.
function Resolve-TsChoiceAnswer {
    param([Parameter(Mandatory)][object[]]$Options, [string]$Answer)
    $a = "$Answer".Trim()
    if (-not $a) { return $null }
    if ($a -match '^\d+$' -and [int]$a -ge 1 -and [int]$a -le $Options.Count) {
        return $Options[[int]$a - 1].Key
    }
    $named = @($Options | Where-Object { $_.Key -ieq $a })
    if ($named.Count) { return $named[0].Key }
    return $null
}

# $Options is an ordered list of @{ Key; Label; Note }. Returns the chosen Key.
# Twin of bootstrap/_wizard.sh ts_prompt_choice — keep the rendered output
# identical (parse-time isolation forces the copy).
function Read-TsChoice {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][object[]]$Options,
        [Parameter(Mandatory)][string]$Default,
        [string[]]$Intro = @()
    )
    Write-Host ''
    Write-Host $Title
    foreach ($line in $Intro) { Write-Host $line }
    for ($i = 0; $i -lt $Options.Count; $i++) {
        $o = $Options[$i]
        $suffix = if ($o.Note) { "  ($($o.Note))" } else { '' }
        $mark = ' '
        if ($o.Key -eq $Default) { $mark = '>'; $suffix += '  [default — press Enter]' }
        Write-Host (" {0}  {1}) {2}{3}" -f $mark, ($i + 1), $o.Label, $suffix)
    }
    $range = "1-$($Options.Count)"
    if (-not (Test-TsInteractive)) {
        Write-Host "Choose [$range, Enter=default]: (non-interactive — taking the default)"
        return $Default
    }
    for ($try = 0; $try -lt 3; $try++) {
        $ans = "$(Read-Host "Choose [$range, Enter=default]")".Trim()
        if (-not $ans) { return $Default }
        $key = Resolve-TsChoiceAnswer -Options $Options -Answer $ans
        if ($key) { return $key }
        Write-Host "  '$ans' is not one of the choices — enter $range, a name, or press Enter for the default."
    }
    Write-Host '  three invalid answers — taking the default.'
    return $Default
}

function Read-TsLeader {
    if ($env:TS_LEADER) { return $env:TS_LEADER }
    $c = Read-TsChoice -Title 'Leader key (WezTerm) — prefix for pane / tab / workspace commands:' -Default 'ctrl-space' -Options @(
        @{ Key = 'ctrl-space'; Label = 'Ctrl+Space' },
        @{ Key = 'ctrl-a';     Label = 'Ctrl+A';     Note = 'tmux muscle memory' },
        @{ Key = 'ctrl-b';     Label = 'Ctrl+B';     Note = 'tmux default' },
        @{ Key = 'alt-space';  Label = 'Alt+Space' },
        @{ Key = 'custom';     Label = 'custom chord' }
    )
    if ($c -ne 'custom') { return $c }
    $chord = Read-Host 'Enter chord (mod-key, e.g. ctrl-x or alt-space)'
    if ($chord) { $chord.Trim() } else { 'ctrl-space' }
}

function Read-TsTheme {
    if ($env:TS_THEME) { return $env:TS_THEME }
    Read-TsChoice -Title 'Theme:' -Default 'dark' -Options @(
        @{ Key = 'dark';   Label = 'dark';   Note = 'Catppuccin Mocha' },
        @{ Key = 'light';  Label = 'light';  Note = 'VS Code Light Modern' },
        @{ Key = 'follow'; Label = 'follow OS appearance'; Note = 'WezTerm switches live' }
    )
}

# WezTerm used to be an unconditional install. It isn't universal (Windows
# Terminal users, machines that already have it), and the nightly winget
# manifest goes stale often enough that the install failed outright in the
# field — so it is a choice now, and a stale nightly falls back to stable.
function Read-TsWezterm {
    if ($env:TS_WEZTERM) { return $env:TS_WEZTERM }
    if (Get-Command wezterm -ErrorAction SilentlyContinue) {
        Read-TsChoice -Title 'Terminal emulator (WezTerm):' -Default 'skip' -Intro @(
            "  Found: $((Get-Command wezterm).Source)"
        ) -Options @(
            @{ Key = 'skip';    Label = 'keep the installed WezTerm' },
            @{ Key = 'nightly'; Label = 'reinstall/upgrade to nightly'; Note = 'what this config targets' },
            @{ Key = 'stable';  Label = 'reinstall/upgrade to stable' }
        )
    } else {
        Read-TsChoice -Title 'Terminal emulator (WezTerm):' -Default 'nightly' -Options @(
            @{ Key = 'nightly'; Label = 'WezTerm nightly'; Note = 'what this config targets' },
            @{ Key = 'stable';  Label = 'WezTerm stable';  Note = 'winget wez.wezterm' },
            @{ Key = 'skip';    Label = "skip — I'll use Windows Terminal or install it myself" }
        )
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
    $choice = Read-TsChoice -Title 'Optional CLI tools (font, Starship, chezmoi — always installed):' -Default 'recommended' -Intro @(
        '  winget may prompt for administrator elevation.',
        ('  recommended: ' + ($script:TsAppsRecommended -join ', ')),
        ('  also available: ' + ($script:TsAppsOptional -join ', '))
    ) -Options @(
        @{ Key = 'recommended'; Label = 'install the recommended set' },
        @{ Key = 'all';         Label = 'install everything'; Note = 'recommended + ' + ($script:TsAppsOptional -join ', ') },
        @{ Key = 'customize';   Label = 'choose which ones' },
        @{ Key = 'none';        Label = 'skip all optional apps' }
    )
    switch ($choice) {
        'all'  { return $script:TsAppsAll }
        'none' { return @() }
        'customize' { return (Read-TsAppsCustom) }
        default { return $script:TsAppsRecommended }
    }
}

# Customize: a single comma-separated line, or Enter to walk the list one by
# one. Fourteen consecutive Y/n prompts is a lot to sit through when you already
# know you want three of them.
function Read-TsAppsCustom {
    Write-Host ''
    Write-Host ('  Available: ' + ($script:TsAppsAll -join ', '))
    $csv = Read-Host '  Type a comma-separated list, or Enter to be asked one at a time'
    if ($csv) {
        $want = @($csv -split ',' | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
        $sel = @($script:TsAppsAll | Where-Object { $want -contains $_.ToLower() })
        $unknown = @($want | Where-Object { $script:TsAppsAll -notcontains $_ })
        if ($unknown.Count) { Write-Warning ('not in the catalog, ignored: ' + ($unknown -join ', ')) }
        Write-Host ('  Selected: ' + $(if ($sel.Count) { $sel -join ', ' } else { '<none>' }))
        return $sel
    }
    $sel = @()
    foreach ($id in $script:TsAppsAll) {
        $def = if ($script:TsAppsRecommended -contains $id) { 'Y' } else { 'n' }
        $a = Read-Host ('  install {0} — {1}? [{2}]' -f $id, (Get-TsAppDesc $id), $def)
        if (-not $a) { $a = $def }
        if ($a -match '^(y|yes)$') { $sel += $id }
    }
    return $sel
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
    # Reachable Kokoro means enabling it actually does something now, so that
    # becomes the default; otherwise enabling is opt-in.
    $reachable = Test-CcTtsKokoroProbe
    $probe = if ($reachable) { '  Kokoro probe: OK' } else { '  Kokoro probe: not reachable' }
    Read-TsChoice -Title 'Claude Code voice notifications (local Kokoro TTS, am_adam)?' `
        -Default $(if ($reachable) { 'on' } else { 'off' }) -Intro @(
            '  Requires Kokoro on http://127.0.0.1:8880 (Docker). Does not install containers.',
            $probe
        ) -Options @(
            @{ Key = 'on';  Label = 'Enable'; Note = 'am_adam, waiting+error' },
            @{ Key = 'off'; Label = 'Skip' }
        )
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
