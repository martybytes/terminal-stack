# _config.ps1 — terminal-stack configuration store (Windows side).
# Dot-sourced by windows-bootstrap.ps1, sync-windows.ps1, and the pwsh ts-config.
#
# Windows has no chezmoi.toml, so the store is a JSON mirror at
# %LOCALAPPDATA%\terminal-stack\config.json (next to rollback-sha). In a combined
# Windows+WSL setup the WSL run_after hook is authoritative and also writes this
# file; the pwsh side is for Windows-standalone installs. The chord→binding and
# theme mapping here mirror .chezmoi.toml.tmpl / bootstrap/_config.sh.

# ── App catalog (winget ids) ─────────────────────────────────────────────────────
# Required prerequisites (Nerd Font, Starship, chezmoi, Git) are always installed
# and not listed here. WezTerm is a wizard choice (Read-TsWezterm), not a
# prerequisite. tmux/tldr/nvtop/lazydocker are WSL/Linux-only.
$script:TsWingetIds = @{
    eza        = 'eza-community.eza'
    fzf        = 'junegunn.fzf'
    bat        = 'sharkdp.bat'
    delta      = 'dandavison.delta'
    ripgrep    = 'BurntSushi.ripgrep.MSVC'
    zoxide     = 'ajeetdsouza.zoxide'
    glow       = 'charmbracelet.glow'
    micro      = 'zyedidia.micro'
    neovim     = 'Neovim.Neovim'
    zed        = 'ZedIndustries.Zed'
    gh         = 'GitHub.cli'
    ghq        = 'x-motemen.ghq'
    lazygit    = 'JesseDuffield.lazygit'
    prettymark = 'Eagle1.PrettyMark'
}
$script:TsAppsRecommended = @('eza','fzf','bat','delta','ripgrep','zoxide','glow','micro','neovim','gh','ghq','lazygit','prettymark')
$script:TsAppsOptional    = @('zed')
$script:TsAppsAll         = $script:TsAppsRecommended + $script:TsAppsOptional

# The binary an app id actually puts on PATH. Mostly identity; a few differ.
function Get-TsAppBin([string]$id) {
    switch ($id) {
        'ripgrep' { 'rg' }
        'neovim'  { 'nvim' }
        default   { $id }
    }
}

# Apps whose winget install doesn't register a PATH binary — GUI apps that only
# land in Program Files. Checked as a fallback so Get-TsAppsPending doesn't nag
# forever about something that's actually installed. Keep in sync with the exe
# path the `pm` launcher (in $PROFILE) resolves.
$script:TsAppFixedPaths = @{
    prettymark = "$env:ProgramFiles\PrettyMark\PrettyMark.exe"
}

function Test-TsAppInstalled([string]$id) {
    if (Get-Command (Get-TsAppBin $id) -ErrorAction SilentlyContinue) { return $true }
    if ($script:TsAppFixedPaths.ContainsKey($id)) { return (Test-Path $script:TsAppFixedPaths[$id]) }
    return $false
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
        if (Test-TsAppInstalled $id) { continue }
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
        'prettymark' { 'markdown viewer (pm alias)' }
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
        leaderChord = 'ctrl-space'; themeMode = 'dark'; tmuxPrefix = 'ctrl-b'
        weztermMux = 'off'; weztermRestore = 'off'; apps = @()
    }
}

# WezTerm multiplexer domain: 'on' hosts panes in wezterm-mux-server (they survive
# a GUI crash), 'off' spawns them locally. Default off — see `ts-mux -h`.
# POSIX twin: bootstrap/_config.sh ts_wez_mux_get.
function Get-TsWeztermMux {
    $v = (Get-TsConfig).weztermMux
    if ($v -eq 'on') { return 'on' }
    return 'off'
}

# Reopen the last session at WezTerm start: 'on' registers resurrect's
# gui-startup restore, 'off' (default) starts clean. The autosave runs either
# way, so Leader+L still restores on demand.
# POSIX twin: bootstrap/_config.sh ts_wez_restore_get.
function Get-TsWeztermRestore {
    $v = (Get-TsConfig).weztermRestore
    if ($v -eq 'on') { return 'on' }
    return 'off'
}

function Save-TsConfig {
    param(
        [string]$LeaderChord = 'ctrl-space',
        [string]$ThemeMode   = 'dark',
        [string]$TmuxPrefix  = 'ctrl-b',
        [string[]]$Apps      = @(),
        [string]$WeztermMux  = 'off',
        [string]$WeztermRestore = 'off',
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
    # Same for the mux setting: only ts-mux passes it, so every other save must
    # carry the stored value forward rather than resetting it to the default.
    if (-not $PSBoundParameters.ContainsKey('WeztermMux') -and $existing.weztermMux) {
        $WeztermMux = $existing.weztermMux
    }
    if ($WeztermMux -ne 'on') { $WeztermMux = 'off' }
    if (-not $PSBoundParameters.ContainsKey('WeztermRestore') -and $existing.weztermRestore) {
        $WeztermRestore = $existing.weztermRestore
    }
    if ($WeztermRestore -ne 'on') { $WeztermRestore = 'off' }
    $obj = [ordered]@{
        leaderChord        = $LeaderChord
        leaderKey          = $l.key
        leaderMods         = $l.mods
        themeMode          = $ThemeMode
        resolvedTheme      = (Get-TsResolvedTheme $ThemeMode)
        tmuxPrefix         = $TmuxPrefix
        tmuxPrefixResolved = (ConvertTo-TsTmuxPrefix $TmuxPrefix)
        weztermMux         = $WeztermMux
        weztermRestore     = $WeztermRestore
        apps               = @($Apps)
        ccTts              = $CcTts
    }
    $p = Get-TsConfigPath
    New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
    ($obj | ConvertTo-Json) | Set-Content -Encoding UTF8 $p
    return $obj
}

# ── Wizard prompts ──────────────────────────────────────────────────────────────
# Env vars skip each prompt: TS_LEADER, TS_THEME, TS_WEZTERM, TS_WEZ_MUX,
# TS_WEZ_RESTORE, TS_APPS, TS_CC_TTS
# (and WORKSPACE_DIR for the workspace question in windows-bootstrap.ps1).

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

# The multiplexer domain (ts-mux). Default off: it changes how every pane is
# hosted and how a config reload behaves, which is a decision to make once at
# install rather than inherit.
# Twin of bootstrap/_wizard.sh ts_prompt_wezterm_mux — keep the rendering identical.
function Read-TsWeztermMux {
    if ($env:TS_WEZ_MUX) { if ($env:TS_WEZ_MUX -eq 'on') { return 'on' } else { return 'off' } }
    Read-TsChoice -Title 'WezTerm multiplexer (keeps panes alive when the GUI dies):' -Default 'off' -Intro @(
        '  On: your shells run in wezterm-mux-server, so a GUI crash leaves every',
        '  pane alive and relaunching WezTerm reattaches. Cost: config changes then',
        '  need "ts-mux restart" (kills every pane) and mux panes lose the Claude tint.'
    ) -Options @(
        @{ Key = 'off'; Label = 'off'; Note = 'panes are spawned by the GUI' },
        @{ Key = 'on';  Label = 'on';  Note = 'panes survive a GUI crash' }
    )
}

# Reopen the last session at WezTerm start (resurrect's gui-startup restore).
# Default off: a terminal that silently reopens yesterday's shells is a surprise,
# and the autosave runs either way so Leader+L can restore on demand.
# Twin of bootstrap/_wizard.sh ts_prompt_wezterm_restore — keep the rendering identical.
function Read-TsWeztermRestore {
    if ($env:TS_WEZ_RESTORE) { if ($env:TS_WEZ_RESTORE -eq 'on') { return 'on' } else { return 'off' } }
    Read-TsChoice -Title 'WezTerm session restore (reopen the last session at startup):' -Default 'off' -Intro @(
        '  On: WezTerm reopens the tabs, panes and scrollback you had when you last',
        '  closed it. Off: it starts clean, and Leader+L still restores a session on',
        '  demand from the same autosaved state.'
    ) -Options @(
        @{ Key = 'off'; Label = 'off'; Note = 'start clean every time' },
        @{ Key = 'on';  Label = 'on';  Note = 'reopen the last session' }
    )
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
        prefixCodex = 'Codex'
        prefixClaudeEnabled = $true
        prefixCursorEnabled = $true
        prefixCodexEnabled = $true
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
        daemon      = [ordered]@{ enabled = $false; port = 8890 }
        summarize   = [ordered]@{
            mode = 'template'; haikuModel = 'claude-haiku-4-5'
            ollamaUrl = 'http://127.0.0.1:11434'; ollamaModel = 'llama3.2:3b'
        }
        music       = [ordered]@{ mode = 'duck'; duckPercent = 30 }
        voicePool   = @('am_adam', 'am_michael', 'af_heart', 'bm_george')
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
            codex = [ordered]@{
                prefixEnabled = [bool]$Tts.prefixCodexEnabled
                prefix = $Tts.prefixCodex
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
        daemon = [ordered]@{
            enabled = [bool]$Tts.daemon.enabled
            port = [int]$Tts.daemon.port
            coalesceSec = 1.8
            doneMaxAgeSec = 20
            maxQueue = 12
            postTimeoutMs = 250
            hostOverride = ''
            suppressFocused = $false
            cursor = [ordered]@{ holdSec = 3; cooldownSec = 15 }
        }
        summarize = [ordered]@{
            mode = $Tts.summarize.mode
            haiku = [ordered]@{
                model = $Tts.summarize.haikuModel
                keyEnv = 'ANTHROPIC_API_KEY'
                timeoutSec = 3
            }
            ollama = [ordered]@{
                url = $Tts.summarize.ollamaUrl
                model = $Tts.summarize.ollamaModel
                timeoutSec = 4
            }
            emptyMeansSilent = $false
        }
        music = [ordered]@{
            mode = $Tts.music.mode
            duckPercent = [int]$Tts.music.duckPercent
            smartThresholdSec = 5
            apps = 'all'
            maxDuckSec = 15
        }
        voices = [ordered]@{ perSession = $false; pool = @($Tts.voicePool) }
        quietHours = [ordered]@{
            enabled = $false; start = '22:00'; end = '07:00'; allowInteractive = $true
        }
    }
}

function Get-CcTtsConfig {
    $c = Get-TsConfig
    if (-not $c.ccTts) { return (Get-CcTtsDefaults) }
    # Fill members added after the config was first stored (pre-daemon upgrades).
    $tts = $c.ccTts
    $defaults = Get-CcTtsDefaults
    foreach ($key in @('daemon', 'summarize', 'music', 'voicePool',
                       'prefixCodex', 'prefixCodexEnabled')) {
        if ($null -eq $tts.$key) {
            $tts | Add-Member -NotePropertyName $key -NotePropertyValue $defaults[$key] -Force
        }
    }
    return $tts
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

function Read-TsCcTtsDaemon {
    if ($env:TS_CC_TTS_DAEMON) { return $(if ($env:TS_CC_TTS_DAEMON -eq 'on') { 'on' } else { 'off' }) }
    Read-TsChoice -Title 'Route voice notifications through the tray daemon?' `
        -Default 'off' -Intro @(
            '  Queues/coalesces announcements, per-session voices, ducks music while speaking.',
            '  Builds one console-free EXE under %LOCALAPPDATA%\terminal-stack. Python is build-time only.'
        ) -Options @(
            @{ Key = 'off'; Label = 'Direct EXE playback' },
            @{ Key = 'on';  Label = 'Tray daemon'; Note = 'installs now, autostarts at login' }
        )
}

function Invoke-TsCcTtsDaemonInstaller {
    param([string[]]$Arguments = @())
    $script = Join-Path $PSScriptRoot 'install-tts-daemon.ps1'
    if (-not (Test-Path -LiteralPath $script)) {
        Write-Warning "tts daemon: install-tts-daemon.ps1 not found at $script"
        return $false
    }
    # Out-Host, not the pipeline: a bare `& pwsh` here would capture the child's
    # stdout into this function's RETURN VALUE — the installer's output (and its
    # error text) vanishes, and callers coercing the array to bool read any
    # failure as success. That exact bug shipped once; keep the stream on the
    # console and return only the boolean.
    & pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File $script @Arguments | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Show-CcTtsDaemonStatus {
    $tts = Get-CcTtsConfig
    $port = if ($tts.daemon -and $tts.daemon.port) { [int]$tts.daemon.port } else { 8890 }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2 -UseBasicParsing
        Write-Host "tts daemon: $($r.Content)"
        $sha = & git -C (Split-Path -Parent $PSScriptRoot) rev-parse HEAD 2>$null
        if ($sha -and ($r.Content -notmatch [regex]::Escape($sha))) {
            Write-Host 'tts daemon: running an older build than this clone — ts-config tts daemon restart'
        }
    } catch {
        Write-Host "tts daemon: not reachable on port $port (hooks fall back to direct playback)"
        $enabled = if ($tts.daemon) { [bool]$tts.daemon.enabled } else { $false }
        Write-Host "  saved setting daemon.enabled=$enabled  —  start: ts-config tts daemon on"
    }
}

function Test-CcTtsDaemonHealthy {
    $tts = Get-CcTtsConfig
    $port = if ($tts.daemon -and $tts.daemon.port) { [int]$tts.daemon.port } else { 8890 }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2 -UseBasicParsing
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Get-CcTtsDuckSnapshotPath {
    Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\state\duck-snapshot.json'
}

function Repair-CcTtsDuckSnapshot {
    # ts-doctor --repair: a snapshot left by a daemon that died mid-duck means
    # per-app volumes are still lowered (Windows persists them). The daemon's
    # own oneshot restores them; a live daemon owns its snapshot — leave it.
    $snap = Get-CcTtsDuckSnapshotPath
    if (-not (Test-Path -LiteralPath $snap)) { return }
    if (Test-CcTtsDaemonHealthy) { return }
    $ttsExe = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
    if (-not (Test-Path -LiteralPath $ttsExe)) {
        Write-Warning "stale duck snapshot at $snap but no TTS executable — reinstall with ts-config tts daemon install"
        return
    }
    & $ttsExe restore-volumes
}

# ── `summarizer self` marker blocks for Claude and Codex ──────────────────────
# Same discipline as the $PROFILE marker regions; the asset carries its own
# start/end markers. Backups follow the repo's .bak.YYYYMMDD[.N] convention.
# Lines are collected into an array and written with -Value — never
# `Where-Object | Set-Content` (an empty pipeline silently writes nothing).

$script:CcTtsSelfStart = '<!-- terminal-stack-tts-start -->'
$script:CcTtsSelfEnd = '<!-- terminal-stack-tts-end -->'

function Backup-CcTtsUserFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $stamp = Get-Date -Format 'yyyyMMdd'
    $bak = "$Path.bak.$stamp"; $n = 1
    while (Test-Path -LiteralPath $bak) { $bak = "$Path.bak.$stamp.$n"; $n++ }
    Copy-Item -LiteralPath $Path -Destination $bak
}

function Get-CcTtsSelfStripped {
    param([string]$Path)
    $out = [System.Collections.Generic.List[string]]::new()
    $skip = $false
    foreach ($line in @(Get-Content -LiteralPath $Path)) {
        if ($skip) {
            if ($line.Contains($script:CcTtsSelfEnd)) { $skip = $false }
            continue
        }
        if ($line.Contains($script:CcTtsSelfStart)) { $skip = $true; continue }
        $out.Add($line)
    }
    return $out
}

function Get-CcTtsCodexInstructionPath {
    $codexHome = if ($env:CODEX_HOME) {
        $env:CODEX_HOME
    } else {
        Join-Path $env:USERPROFILE '.codex'
    }
    $override = Join-Path $codexHome 'AGENTS.override.md'
    if ((Test-Path -LiteralPath $override) -and (Get-Item -LiteralPath $override).Length -gt 0) {
        return $override
    }
    return (Join-Path $codexHome 'AGENTS.md')
}

function Install-CcTtsSelfBlockAtPath {
    param([string]$Target, [string]$Agent)
    $asset = Join-Path $PSScriptRoot 'tts-daemon\assets\speak-summary.md'
    if (-not (Test-Path -LiteralPath $asset)) {
        Write-Warning 'tts: speak-summary.md asset not found (run ts-update?)'
        return $false
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
    $lines = @()
    if (Test-Path -LiteralPath $Target) {
        Backup-CcTtsUserFile $Target
        $lines = @(Get-CcTtsSelfStripped $Target) + @('')
    }
    $lines += @(Get-Content -LiteralPath $asset)
    Set-Content -LiteralPath $Target -Value $lines -Encoding UTF8
    Write-Host "tts: spoken-summary instruction installed for $Agent in $Target"
    return $true
}

function Install-CcTtsSelfBlock {
    $targets = @(
        @{ Agent = 'Claude'; Path = (Join-Path $env:USERPROFILE '.claude\CLAUDE.md') }
        @{ Agent = 'Codex';  Path = (Get-CcTtsCodexInstructionPath) }
    )
    foreach ($item in $targets) {
        Install-CcTtsSelfBlockAtPath -Target $item.Path -Agent $item.Agent | Out-Null
    }
    Write-Host 'tts: Cursor uses its final-response hook text when no GUI-managed User Rule marker is present'
}

function Remove-CcTtsSelfBlock {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $targets = @(
        (Join-Path $env:USERPROFILE '.claude\CLAUDE.md')
        (Join-Path $codexHome 'AGENTS.md')
        (Join-Path $codexHome 'AGENTS.override.md')
    ) | Select-Object -Unique
    foreach ($target in $targets) {
        if (-not (Test-Path -LiteralPath $target)) { continue }
        $raw = Get-Content -LiteralPath $target -Raw
        if (-not $raw.Contains($script:CcTtsSelfStart)) { continue }
        Backup-CcTtsUserFile $target
        $lines = @(Get-CcTtsSelfStripped $target)
        Set-Content -LiteralPath $target -Value $lines -Encoding UTF8
        Write-Host "tts: spoken-summary instruction removed from $target"
    }
}

function Invoke-CcTtsDaemonConfigReload {
    param($Tts)
    if (-not $Tts.daemon -or -not $Tts.daemon.enabled) { return }
    $port = if ($Tts.daemon.port) { [int]$Tts.daemon.port } else { 8890 }
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$port/v1/config/reload" `
            -Method Post -TimeoutSec 1 -UseBasicParsing | Out-Null
        Write-Host 'tts: running daemon reloaded the new configuration'
    } catch {
        # Never-silence fallback remains active; a stopped/older daemon is not an error here.
    }
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
        'on'   {
            $ttsExe = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
            if ((-not (Test-Path -LiteralPath $ttsExe)) `
                    -and (-not (Invoke-TsCcTtsDaemonInstaller @('-NoStart', '-NoAutostart')))) {
                return
            }
            $tts.enabled = $true
        }
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
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: ts-config tts prefix claude|cursor|codex on|off|<label>'; return }
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
                'codex' {
                    switch ($Arg2) {
                        'on'  { $tts.prefixCodexEnabled = $true }
                        'off' { $tts.prefixCodexEnabled = $false }
                        default { $tts.prefixCodex = $Arg2; $tts.prefixCodexEnabled = $true }
                    }
                }
                default { Write-Warning 'expected claude, cursor, or codex'; return }
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
        'daemon' {
            switch ($Arg) {
                'on' {
                    if (-not (Invoke-TsCcTtsDaemonInstaller)) { return }
                    $tts.daemon.enabled = $true
                    Write-Host "note: this enables the daemon for Windows-side hooks; if you also run Claude in WSL, run 'ts-config tts daemon on' from WSL so those hooks route to it too."
                }
                'off' {
                    Invoke-TsCcTtsDaemonInstaller @('-Uninstall') | Out-Null
                    $tts.daemon.enabled = $false
                }
                'install' { Invoke-TsCcTtsDaemonInstaller @('-NoStart') | Out-Null; return }
                'restart' {
                    Invoke-TsCcTtsDaemonInstaller @('-Uninstall') | Out-Null
                    Invoke-TsCcTtsDaemonInstaller | Out-Null
                    return
                }
                default { Show-CcTtsDaemonStatus; return }
            }
        }
        'summarizer' {
            if ($Arg -notin 'template', 'self', 'haiku', 'ollama') {
                Write-Warning 'usage: ts-config tts summarizer template|self|haiku|ollama'; return
            }
            $tts.summarize.mode = $Arg
            if ($Arg -eq 'self') { Install-CcTtsSelfBlock } else { Remove-CcTtsSelfBlock }
        }
        'haiku-model' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts haiku-model <model>'; return }
            $tts.summarize.haikuModel = $Arg
        }
        'ollama' {
            if (-not $Arg) { Write-Warning 'usage: ts-config tts ollama <url> [<model>]'; return }
            $tts.summarize.ollamaUrl = $Arg
            if ($Arg2) { $tts.summarize.ollamaModel = $Arg2 }
        }
        'music' {
            if ($Arg -notin 'duck', 'smart', 'pause', 'off') {
                Write-Warning 'usage: ts-config tts music duck|smart|pause|off'; return
            }
            $tts.music.mode = $Arg
        }
        'duck-level' {
            if ($Arg -notmatch '^\d+$' -or [int]$Arg -gt 100) {
                Write-Warning 'usage: ts-config tts duck-level <0-100>'; return
            }
            $tts.music.duckPercent = [int]$Arg
        }
        'voices' {
            if (-not $Arg -or $Arg -eq 'show') {
                Write-Host "voice pool: $(@($tts.voicePool) -join ',')"
                return
            }
            $tts.voicePool = @($Arg -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        'port' {
            if ($Arg -notmatch '^\d+$') { Write-Warning 'usage: ts-config tts port <n>'; return }
            $tts.daemon.port = [int]$Arg
        }
        'test' {
            $test = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
            if (Test-Path -LiteralPath $test) {
                $source = if ($Arg -eq '--source' -and $Arg2) { $Arg2 } else { 'test' }
                & $test test --source $source
            } else {
                Write-Warning "terminal-stack-tts.exe not found at $test (run ts-config tts on)"
            }
            return
        }
        'reset' { $tts = Get-CcTtsDefaults }
        default {
            Write-Warning "ts-config tts: unknown subcommand '$Sub' (show, on, off, test, reset, ...)"
            return
        }
    }
    if ($Sub -in 'on','off','engine','message','voice','voice-chatter','energy','excitement','url','events','prefix','project','template','reset','daemon','summarizer','haiku-model','ollama','music','duck-level','voices','port') {
        & $Apply $tts
        Invoke-CcTtsDaemonConfigReload $tts
    }
}
