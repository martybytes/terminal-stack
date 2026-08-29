# _config.ps1 — terminal-stack configuration store (Windows side).
# Dot-sourced by windows-bootstrap.ps1, sync-windows.ps1, and the pwsh tstack config.
#
# Windows has no chezmoi.toml, so the store is a JSON mirror at
# %LOCALAPPDATA%\terminal-stack\config.json (next to rollback-sha). In a combined
# Windows+WSL setup the WSL run_after hook is authoritative and also writes this
# file; the pwsh side is for Windows-standalone installs. The chord→binding and
# theme mapping here mirror .chezmoi.toml.tmpl / bootstrap/_config.sh.

# ── App catalog (winget ids) ─────────────────────────────────────────────────────
# Required prerequisites (Nerd Font, Starship, chezmoi, Git) are always installed
# and not listed here. Terminal emulators are a wizard choice (Read-TsTerminals), not a
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
    fd         = 'sharkdp.fd'
    duf        = 'muesli.duf'
    dust       = 'bootandy.dust'
    gdu        = 'dundee.gdu'
    btop       = 'aristocratos.btop4win'
    bottom     = 'Clement.bottom'
    gping      = 'orf.gping'
    rclone     = 'Rclone.Rclone'
    fnm        = 'Schniz.fnm'
    node       = 'OpenJS.NodeJS'
    python     = 'Python.Python.3.13'
    uv         = 'astral-sh.uv'
    ruff       = 'astral-sh.ruff'
    yazi       = 'sxyazi.yazi'
    # Deliberately absent: ncdu, bandwhich, tree and atuin. The first three have
    # no reliable winget id (or, for bandwhich, no Windows build). atuin has no
    # winget manifest at all, and `atuin init` has no PowerShell target — its
    # shells are zsh/bash/fish/nu/xonsh — so even a hand-installed binary would
    # get no Ctrl+R integration here; on a Windows box atuin belongs in WSL.
    # An id that always fails is worse than an honest "not available on this
    # platform" — Test-TsAppInstallable skips anything no path here can install,
    # so they simply never nag on Windows.
    #
    # Also absent, for the opposite reason: pipx, poetry, glances, ipython,
    # httpie and pre-commit. pypa.pipx, Python-Poetry.Poetry and
    # nicolargo.glances were all in this table and all three answer "No package
    # found matching input criteria" — pipx is in the recommended set, so it
    # failed on every Windows machine on every run. They are real, installable
    # tools that simply do not come from winget; $TsPyTools routes them through
    # Install-TsPyTool instead.
}
# ── App catalog ────────────────────────────────────────────────────────────────
# Read from bootstrap/apps.conf, the same file bootstrap/_config.sh and
# tstack/apps.py read. There used to be TWO hand-maintained catalogs -- this one
# and the bash one -- with different id lists, different group membership and
# their own copies of the descriptions and the two default sets. A third reader
# forced the issue: the settings dashboard, the wizard and `tstack config apps`
# all need the catalog, and only one of those is bash.
#
# The platform column replaces the second id list this file used to be. It says
# "can this platform install it", NOT "is it in winget" -- conflating the two is
# why a Windows box missing grok/gemini/pi/cursor-agent was never once told so.
function Get-TsAppsConfPath {
    Join-Path $PSScriptRoot 'apps.conf'
}

function Read-TsAppsCatalog {
    $path = Get-TsAppsConfPath
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Warning "$path is missing; the app catalog is empty."
        return @()
    }
    $rows = @()
    foreach ($line in (Get-Content -LiteralPath $path)) {
        $trimmed = $line.Trim()
        # Only a FULL-LINE comment is a comment: `#` is legal inside a
        # description, which is the rest of the line by definition.
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $parts = $trimmed -split '\s+', 5
        if ($parts.Count -lt 5) { Write-Warning "apps.conf: malformed row: $trimmed"; continue }
        # Windows here, always: this file is only ever loaded on the Windows side.
        $plat = $parts[3]
        if ($plat -ne 'all' -and $plat -ne 'windows') { continue }
        $rows += [pscustomobject]@{
            Id = $parts[0]; Group = $parts[1]; Classes = $parts[2]
            Platforms = $plat; Description = $parts[4]
        }
    }
    return $rows
}

$script:TsAppCatalog      = @(Read-TsAppsCatalog)
$script:TsAppsAll         = @($script:TsAppCatalog | ForEach-Object { $_.Id })
$script:TsAppsRecommended = @($script:TsAppCatalog |
    Where-Object { $_.Classes -in @('both', 'dev') } | ForEach-Object { $_.Id })
$script:TsAppsSysadmin    = @($script:TsAppCatalog |
    Where-Object { $_.Classes -in @('both', 'sys') } | ForEach-Object { $_.Id })
$script:TsAppsOptional    = @($script:TsAppsAll | Where-Object { $script:TsAppsRecommended -notcontains $_ })

# Neither default set is a subset of the other: a server's kit includes the
# monitors that are merely optional on a laptop, and drops the runtimes and
# agent CLIs entirely.
function Get-TsAppsForClass([string]$Class) {
    if ($Class -eq 'sysadmin') { return $script:TsAppsSysadmin }
    return $script:TsAppsRecommended
}

# Group descriptions are presentation, so they stay here rather than in the data
# file; membership and order come from it. Twin of ts_app_group_desc.
$script:TsAppGroupDesc = @{
    shell = 'shell essentials'; search = 'search and find'; disk = 'disk usage'
    system = 'system monitors'; network = 'network'; git = 'git tooling'
    editors = 'editors and readers'; runtimes = 'language runtimes'
    python = 'Python tooling'; ai = 'AI coding agents'; models = 'local model sizing'
}
$script:TsAppGroups = [ordered]@{}
foreach ($g in @($script:TsAppCatalog | ForEach-Object { $_.Group } | Select-Object -Unique)) {
    $script:TsAppGroups[$g] = @{
        Desc    = $(if ($script:TsAppGroupDesc.ContainsKey($g)) { $script:TsAppGroupDesc[$g] } else { $g })
        Members = @($script:TsAppCatalog | Where-Object { $_.Group -eq $g } | ForEach-Object { $_.Id })
    }
}

function Get-TsAppGroupOf([string]$id) {
    foreach ($g in $script:TsAppGroups.Keys) {
        if ($script:TsAppGroups[$g].Members -contains $id) { return $g }
    }
    return ''
}
function Test-TsAppIsAi([string]$id) { return ($script:TsAppGroups['ai'].Members -contains $id) }

# Python CLI tools. None of these has a winget manifest — pypa.pipx,
# Python-Poetry.Poetry and nicolargo.glances were all in $TsWingetIds and all
# three were dead ids — but every one installs cleanly from PyPI, so they route
# through Install-TsPyTool rather than being declared unavailable. macOS/Linux
# get the same set from brew (ts_install_apps in bootstrap/_config.sh).
$script:TsPyTools = @('pipx','ipython','httpie','poetry','pre-commit','glances')
function Test-TsAppIsPy([string]$id) { return ($script:TsPyTools -contains $id) }

# Can this platform actually install <id>? Twin of ts_app_installable in
# bootstrap/_config.sh. This used to be a bare $TsWingetIds.ContainsKey, which
# quietly meant "is it in winget" rather than "can we install it": the agent
# CLIs are recommended and installable via Install-TsAiCli, yet a Windows box
# missing grok/gemini/pi/cursor-agent was never once told so.
function Test-TsAppInstallable([string]$id) {
    if ($script:TsWingetIds.ContainsKey($id)) { return $true }
    if (Test-TsAppIsAi $id) { return $true }
    if (Test-TsAppIsPy $id) { return $true }
    return $false
}

# The binary an app id actually puts on PATH. Mostly identity; a few differ.
function Get-TsAppBin([string]$id) {
    switch ($id) {
        'ripgrep' { 'rg' }
        'neovim'  { 'nvim' }
        'bottom'  { 'btm' }
        'python'  { 'python3' }
        'cursor-agent' { 'cursor-agent' }
        # The Windows port is a different program with a different name: winget's
        # aristocratos.btop4win installs btop4win.exe, never btop.exe. Probing for
        # `btop` therefore never found it, so Get-TsAppsPending offered it on every
        # single tstack update and winget answered "No available upgrade found" every
        # time. Deliberately NOT mirrored into ts_app_bin in bootstrap/_config.sh —
        # apt and brew both install it as plain `btop`.
        'btop'    { 'btop4win' }
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
# it however many times tstack update ran, which is exactly how gh/ghq/lazygit would
# have missed every existing install.
# Which class this machine looks like, INFERRED from what it has chosen rather
# than saved. The install profile is a wizard branch and deliberately not stored;
# the class is needed on every update, so it comes from a predicate that cannot
# drift: does the saved selection contain anything outside the sysadmin set?
#
# Without it a machine set up as a server is told on every update that it is
# missing fnm, poetry and six agent CLIs it deliberately declined -- the same nag
# Test-TsAppInstallable exists to end, in a new place.
# Twin of ts_apps_saved_class in bootstrap/_config.sh.
function Get-TsSavedAppClass {
    $saved = @()
    try { $saved = @((Get-TsConfig).apps) } catch {}
    # Never configured: keep the old behaviour rather than guessing.
    if (-not $saved.Count) { return 'developer' }
    foreach ($id in $saved) {
        if ($id -and $script:TsAppsSysadmin -notcontains $id) { return 'developer' }
    }
    return 'sysadmin'
}

function Get-TsAppsPending {
    # Refresh PATH from the persisted Machine+User values FIRST, the way the
    # POSIX twin calls ts_load_node_env. Without it this reads the PATH this
    # process started with, so anything installed since — by an installer that
    # edited the User PATH, or by fnm, whose entry is per-shell — reads as
    # missing. Measured: grok, gemini and pi were all installed and all three
    # were offered again on every single tstack update.
    Update-TsSessionPath
    $saved = @()
    try { $saved = @((Get-TsConfig).apps) } catch {}
    $seen = @{}; $out = @()
    foreach ($id in ($saved + (Get-TsAppsForClass (Get-TsSavedAppClass)))) {
        if (-not $id) { continue }
        if ($seen[$id]) { continue }
        $seen[$id] = $true
        if (Test-TsAppInstalled $id) { continue }
        # Only offer what this platform can actually install.
        if (-not (Test-TsAppInstallable $id)) { continue }
        $out += $id
    }
    return $out
}

function Get-TsAppDesc([string]$id) {
    $row = $script:TsAppCatalog | Where-Object { $_.Id -eq $id } | Select-Object -First 1
    if ($row) { return $row.Description }
    return ''
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
# Optional-property read that survives Set-StrictMode. Under strictness a missing
# property on a pscustomobject -- exactly what ConvertFrom-Json hands back for a config
# written before a key existed -- is a terminating error, not $null. Empty strings fall
# back too, preserving the truthiness the dot-access callers relied on.
function Get-TsProp($Object, [string]$Name, $Default = $null) {
    if ($null -eq $Object) { return $Default }
    if ($Object -is [System.Collections.IDictionary]) {
        if (-not $Object.Contains($Name)) { return $Default }
        $value = $Object[$Name]
    } else {
        $prop = $Object.PSObject.Properties[$Name]
        if ($null -eq $prop) { return $Default }
        $value = $prop.Value
    }
    if ($null -eq $value -or $value -eq '') { return $Default }
    return $value
}

# Point a clone's git hooks at .githooks so the pre-commit and pre-push gates run
# in it. See ts_install_git_hooks in bootstrap/_config.sh for why this exists: the
# hook file claimed a bootstrap installed it, nothing ever did, core.hooksPath was
# unset in every clone, and the only automated gate in the repo had never run.
function Install-TsGitHooks {
    param([string]$CloneDir)
    if (-not $CloneDir) { return }
    if (-not (Test-Path -LiteralPath (Join-Path $CloneDir '.git'))) { return }
    if (-not (Test-Path -LiteralPath (Join-Path $CloneDir '.githooks'))) { return }
    $have = & git -C $CloneDir config --local --get core.hooksPath 2>$null
    if ($have -eq '.githooks') { return }
    & git -C $CloneDir config --local core.hooksPath '.githooks' 2>$null
    Write-Host '  git hooks: core.hooksPath -> .githooks (pre-commit and pre-push gates active)'
}

# $null when there is no Windows side, rather than a throw. pwsh runs on macOS
# and Linux, where $env:LOCALAPPDATA is unset and Join-Path -Path $null is a
# terminating error -- so dot-sourcing this file and calling Get-TsConfig died
# there, including in the strict-mode repro docs/powershell-quirks.md gives for
# checking exactly this class of bug. Python's twin (tstack/store.py
# mirror_path) already returns None; the callers below fall through to the
# defaults. On Windows LOCALAPPDATA is always set, so nothing changes there.
function Get-TsConfigPath {
    if (-not $env:LOCALAPPDATA) { return $null }
    Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
}

function Get-TsConfig {
    $p = Get-TsConfigPath
    if ($p -and (Test-Path $p)) {
        try { return (Get-Content $p -Raw | ConvertFrom-Json) } catch {}
    }
    return [pscustomobject]@{
        leaderChord = 'ctrl-space'; themeMode = 'dark'; tmuxPrefix = 'ctrl-b'
        weztermMux = 'off'; weztermRestore = 'off'; ghosttyConfig = 'on'; apps = @()
        headroomEnabled = 'off'; headroomCursorMode = 'mcp'
        cavemanEnabled = 'off'; agentmemoryEnabled = 'off'
        memoryBackend = 'agentmemory'
        starshipPreset = 'terminal-stack'; atuinEnabled = 'off'
    }
}

# User-global coding-agent integrations. A missing AgentMemory key migrates to on
# only when this machine is already wired, preserving the behavior of installs
# created before the explicit per-machine toggle existed. All other fresh defaults
# are off. TS_* environment values are launch/install-time overrides, not secrets.
function Get-TsAgentSetting([string]$Name) {
    $envName = switch ($Name) {
        'headroomEnabled'   { 'TS_HEADROOM' }
        'headroomCursorMode'{ 'TS_HEADROOM_CURSOR' }
        'cavemanEnabled'    { 'TS_CAVEMAN' }
        'agentmemoryEnabled'{ 'TS_AGENTMEMORY' }
        'playwrightEnabled' { 'TS_PLAYWRIGHT' }
        'memoryBackend'     { 'TS_MEMORY_BACKEND' }
    }
    if ($envName) {
        $override = [Environment]::GetEnvironmentVariable($envName, 'Process')
        if ($override) { return $override.ToLowerInvariant() }
    }
    $cfg = Get-TsConfig
    $saved = Get-TsProp $cfg $Name $null
    if ($saved) { return "$saved".ToLowerInvariant() }
    if ($Name -eq 'headroomCursorMode') { return 'mcp' }
    # agentmemory is the default backend: it is what a machine with no answer
    # has effectively been running, since Headroom's memory needs a --memory the
    # compose file has never passed. Upgrading into this key changes nothing.
    if ($Name -eq 'memoryBackend') { return 'agentmemory' }
    if ($Name -eq 'agentmemoryEnabled') {
        $claudeCache = Join-Path $env:USERPROFILE '.claude\plugins\cache\agentmemory\agentmemory'
        $codexCache = Join-Path $env:USERPROFILE '.codex\plugins\cache\agentmemory\agentmemory'
        if ((Test-Path -LiteralPath $claudeCache) -or (Test-Path -LiteralPath $codexCache)) { return 'on' }
    }
    return 'off'
}

# WezTerm multiplexer domain: 'on' hosts panes in wezterm-mux-server (they survive
# a GUI crash), 'off' spawns them locally. Default off — see `tstack mux -h`.
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
        [ValidateSet('on','off')][string]$GhosttyConfig = 'on',
        $CcTts                = $null,
        [ValidateSet('on','off')][string]$HeadroomEnabled = 'off',
        [ValidateSet('mcp','byok','off')][string]$HeadroomCursorMode = 'mcp',
        [ValidateSet('on','off')][string]$CavemanEnabled = 'off',
        [ValidateSet('on','off')][string]$AgentmemoryEnabled = 'off',
        [ValidateSet('on','off')][string]$PlaywrightEnabled = 'off',
        [ValidateSet('agentmemory','headroom','none')][string]$MemoryBackend = 'agentmemory',
        # No ValidateSet: `starship preset --list` is the authority and it grows,
        # so a hardcoded set here would reject a preset the installed starship
        # has. bootstrap/_config.sh's ts_starship_set asks starship instead.
        [string]$StarshipPreset = 'terminal-stack',
        [ValidateSet('on','off')][string]$AtuinEnabled = 'off'
    )
    $l = ConvertTo-TsLeader $LeaderChord
    $existing = Get-TsConfig
    if (-not $CcTts) { $CcTts = Get-TsProp $existing ccTts (Get-CcTtsDefaults) }
    # Callers that don't pass -TmuxPrefix (e.g. the Windows bootstrap re-run)
    # must not silently reset a prefix the WSL side already configured.
    if (-not $PSBoundParameters.ContainsKey('TmuxPrefix') -and $existing.tmuxPrefix) {
        $TmuxPrefix = $existing.tmuxPrefix
    }
    # Same for the mux setting: only tstack mux passes it, so every other save must
    # carry the stored value forward rather than resetting it to the default.
    if (-not $PSBoundParameters.ContainsKey('WeztermMux') -and $existing.weztermMux) {
        $WeztermMux = $existing.weztermMux
    }
    if ($WeztermMux -ne 'on') { $WeztermMux = 'off' }
    if (-not $PSBoundParameters.ContainsKey('WeztermRestore') -and $existing.weztermRestore) {
        $WeztermRestore = $existing.weztermRestore
    }
    if ($WeztermRestore -ne 'on') { $WeztermRestore = 'off' }
    # Defaults on, so the carry-forward keeps an explicit 'off' rather than an
    # explicit 'on' — the mirror image of the two above.
    if (-not $PSBoundParameters.ContainsKey('GhosttyConfig') -and $existing.ghosttyConfig) {
        $GhosttyConfig = $existing.ghosttyConfig
    }
    if ($GhosttyConfig -ne 'off') { $GhosttyConfig = 'on' }
    foreach ($pair in @(
        @{ Param = 'HeadroomEnabled'; Name = 'headroomEnabled'; Default = 'off' },
        @{ Param = 'HeadroomCursorMode'; Name = 'headroomCursorMode'; Default = 'mcp' },
        @{ Param = 'CavemanEnabled'; Name = 'cavemanEnabled'; Default = 'off' },
        @{ Param = 'AgentmemoryEnabled'; Name = 'agentmemoryEnabled'; Default = $(Get-TsAgentSetting agentmemoryEnabled) },
        @{ Param = 'PlaywrightEnabled'; Name = 'playwrightEnabled'; Default = 'off' },
        @{ Param = 'MemoryBackend'; Name = 'memoryBackend'; Default = 'agentmemory' },
        # Both of these are written by the WSL side and read by the Windows sync,
        # and neither was in this table -- so a Windows-side save STRIPPED them
        # from config.json, silently, exactly as the ccTts comment above warns.
        # starshipPreset decides which prompt sync-windows.ps1 deploys, so losing
        # it visibly reverts the prompt; atuinEnabled has no pwsh consumer today
        # but is the same bug and is fixed with it rather than left as the next
        # one to find.
        @{ Param = 'StarshipPreset'; Name = 'starshipPreset'; Default = 'terminal-stack' },
        @{ Param = 'AtuinEnabled'; Name = 'atuinEnabled'; Default = 'off' }
    )) {
        if (-not $PSBoundParameters.ContainsKey($pair.Param)) {
            Set-Variable -Name $pair.Param -Value (Get-TsProp $existing $pair.Name $pair.Default)
        }
    }
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
        ghosttyConfig      = $GhosttyConfig
        apps               = @($Apps)
        ccTts              = $CcTts
        headroomEnabled    = $HeadroomEnabled
        headroomCursorMode = $HeadroomCursorMode
        cavemanEnabled     = $CavemanEnabled
        agentmemoryEnabled = $AgentmemoryEnabled
        playwrightEnabled = $PlaywrightEnabled
        memoryBackend      = $MemoryBackend
        starshipPreset     = $StarshipPreset
        atuinEnabled       = $AtuinEnabled
    }
    $p = Get-TsConfigPath
    # No Windows side means nowhere to mirror to. Return the object anyway --
    # the caller uses it -- rather than throwing on Split-Path -Path $null.
    if (-not $p) { return $obj }
    New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
    ($obj | ConvertTo-Json) | Set-Content -Encoding UTF8 $p
    return $obj
}

# <clone>\services\stacks\<stack>\.env. One rule everywhere: the stack tree is
# always under the clone, so there is nothing to search for. POSIX twin:
# bootstrap/_config.sh ts_stack_env_file.
function Get-TsStackEnvFile([string]$Stack) {
    Join-Path (Split-Path -Parent $PSScriptRoot) "services\stacks\$Stack\.env"
}

# ── the memory backend ──────────────────────────────────────────────────────────
# AgentMemory or Headroom, never both. They do the same job, so running both
# gives two half-filled stores and no way to know which one holds the answer.
#
# This is the ONLY writer of agentmemoryEnabled. Anything that sets that key on
# its own can produce a combination the wizard refuses to offer, which is how a
# "cannot happen" state happens.
# POSIX twin: bootstrap/_config.sh ts_memory_apply.
function Get-TsMemoryBackend { Get-TsAgentSetting memoryBackend }

# The headroom stack's COMPOSE_FILE is derived, never hand-edited: Qdrant and
# Neo4j are only referenced -- and so only ever pulled -- when the overlay is
# selected, and the overlay is what passes --memory.
function Get-TsMemoryComposeSpec([string]$Backend) {
    if ($Backend -eq 'headroom') { return 'docker-compose.yml:docker-compose.memory.yml' }
    return 'docker-compose.yml'
}

function Set-TsMemoryComposeFile([string]$Backend) {
    $envFile = Get-TsStackEnvFile 'headroom'
    if (-not $envFile -or -not (Test-Path -LiteralPath $envFile)) { return }
    $spec = Get-TsMemoryComposeSpec $Backend
    $lines = @(Get-Content -LiteralPath $envFile)
    $sawFile = $false; $sawSep = $false
    $out = foreach ($line in $lines) {
        if ($line -match '^COMPOSE_FILE=')           { $sawFile = $true; "COMPOSE_FILE=$spec" }
        elseif ($line -match '^COMPOSE_PATH_SEPARATOR=') { $sawSep = $true; $line }
        else { $line }
    }
    $out = @($out)
    if (-not $sawSep)  { $out += 'COMPOSE_PATH_SEPARATOR=:' }
    if (-not $sawFile) { $out += "COMPOSE_FILE=$spec" }
    # -Value, never a Where-Object pipeline: an empty pipeline leaves the file
    # untouched with no error, which is the documented trap in this repo.
    Set-Content -LiteralPath $envFile -Value $out -Encoding UTF8
}

function Set-TsMemoryBackend([ValidateSet('agentmemory','headroom','none')][string]$Backend) {
    Save-TsConfig -MemoryBackend $Backend | Out-Null
    # Derived in the same breath. A separate "also turn AgentMemory off" command
    # is a command someone forgets to run.
    if ($Backend -eq 'agentmemory') { Save-TsConfig -AgentmemoryEnabled 'on'  | Out-Null }
    else                            { Save-TsConfig -AgentmemoryEnabled 'off' | Out-Null }
    Set-TsMemoryComposeFile $Backend
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

# ── terminal prompt primitives ──
# Here, not in the wizard's own file, and for the reason the POSIX twin gives in
# _config.sh: these are not wizard questions. `Set-TerminalStackConfig`'s menu
# edits ONE setting at a time and still has to ask. Moving the questionnaire to
# Python took the whole Read-Ts* half of this file with it, and five items of
# that menu -- leader, theme, apps, session restore, re-run wizard -- were left
# calling functions that no longer existed. `tests/test_shell_symbols.py` fails
# on the next such deletion rather than leaving it to be found by hand.

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
        $note = $o['Note']   # index, not dot: Note is optional and dot access throws under strictness
        $suffix = if ($note) { "  ($note)" } else { '' }
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










# ── WezTerm channel facts ───────────────────────────────────────────────────────
# POSIX twin: bootstrap/_wezterm.sh — keep the reported facts and the switching
# rules identical. Neither channel is ever installed automatically: the wizard
# asks, tstack update offers, tstack config wezterm changes it. Upstream's newest stable
# is 20240203 (February 2024, no cut since), which is why nightly is the
# pre-selected answer rather than the forced one.
#
# The channel is NOT a saved setting — it is read back from winget, which cannot
# drift out of sync with what is actually installed.
$script:TsWezRepo = 'wezterm/wezterm'
$script:TsWezNetTimeout = 5

# Parse a `wezterm --version` line into @{Version;Date;Hash}. Releases are named
# <YYYYMMDD>-<HHMMSS>-<githash>, so the build date needs no network call.
function Get-TsWezVersionParts([string]$Raw) {
    if ($Raw -match '(\d{8})-(\d{6})-([0-9a-f]+)') {
        return @{ Version = "$($Matches[1])-$($Matches[2])-$($Matches[3])"; Date = $Matches[1]; Hash = $Matches[3] }
    }
    return $null
}

function Get-TsWezInstalled {
    $cmd = Get-Command wezterm -CommandType Application -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    try { $raw = & wezterm --version 2>$null } catch { return $null }
    return (Get-TsWezVersionParts "$raw")
}

function Format-TsWezDate([string]$Ymd) {
    if ($Ymd -match '^\d{8}$') { return "{0}-{1}-{2}" -f $Ymd.Substring(0,4), $Ymd.Substring(4,2), $Ymd.Substring(6,2) }
    return $Ymd
}

# stable | nightly | unknown | none — from winget, never stored. "unknown" means
# wezterm is on PATH but winget does not own it: report it, never replace it.
function Get-TsWezChannel {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $n = & winget list --id 'wez.wezterm.nightly' --exact 2>&1
        if ($LASTEXITCODE -eq 0 -and ($n -match 'wez\.wezterm\.nightly')) { return 'nightly' }
        $st = & winget list --id 'wez.wezterm' --exact 2>&1
        if ($LASTEXITCODE -eq 0 -and ($st -match 'wez\.wezterm')) { return 'stable' }
    }
    if (Get-Command wezterm -CommandType Application -ErrorAction SilentlyContinue) { return 'unknown' }
    return 'none'
}

# One place for the API call. gh is authenticated (5000/hr) where present; the
# bare REST endpoint is 60/hr per IP. Fails open — callers treat $null as offline.
function Invoke-TsGhApi([string]$Path) {
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        try {
            $out = & gh api $Path 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return ($out | ConvertFrom-Json) }
        } catch {}
    }
    try {
        return Invoke-RestMethod -Uri "https://api.github.com/$Path" -TimeoutSec $script:TsWezNetTimeout `
            -Headers @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'terminal-stack' }
    } catch { return $null }
}

function Get-TsWezLatestStable {
    $d = Invoke-TsGhApi "repos/$($script:TsWezRepo)/releases/latest"
    if (-not $d -or -not $d.tag_name) { return $null }
    return @{ Tag = $d.tag_name; Date = "$($d.published_at)".Substring(0,10) }
}

# The rolling nightly tag's own published_at is stuck in 2019; each ASSET's
# updated_at is the real build time, and it differs per platform.
function Get-TsWezLatestNightly {
    $d = Invoke-TsGhApi "repos/$($script:TsWezRepo)/releases/tags/nightly"
    if (-not $d) { return $null }
    $best = ''
    foreach ($a in $d.assets) { if ($a.name -eq 'WezTerm-nightly-setup.exe') { $best = "$($a.updated_at)".Substring(0,10) } }
    if (-not $best) { foreach ($a in $d.assets) { $u = "$($a.updated_at)"; if ($u -and $u.Substring(0,10) -gt $best) { $best = $u.Substring(0,10) } } }
    if (-not $best) { return $null }
    return $best
}

function Get-TsWezCommitsSince([string]$Hash) {
    if (-not $Hash) { return $null }
    $d = Invoke-TsGhApi "repos/$($script:TsWezRepo)/compare/$Hash...main"
    if (-not $d -or -not $d.total_commits) { return $null }
    return $d.total_commits
}

# Upstream's own docs/changelog.md, sliced at the heading matching the installed
# version. raw.githubusercontent.com has no API rate limit; cached because it is
# ~225 KB. Returns the markdown slice, or $null.
function Get-TsWezChangesText([string]$Version) {
    $dir = Join-Path $env:LOCALAPPDATA 'terminal-stack'
    $file = Join-Path $dir 'wezterm-changelog.md'
    $fresh = (Test-Path $file) -and ((Get-Date) - (Get-Item $file).LastWriteTime).TotalSeconds -lt 3600
    if (-not $fresh) {
        try {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$($script:TsWezRepo)/main/docs/changelog.md" `
                -TimeoutSec $script:TsWezNetTimeout -UseBasicParsing -OutFile $file
        } catch {}
    }
    if (-not (Test-Path $file)) { return $null }
    $lines = Get-Content -LiteralPath $file
    $start = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -like '## Changes*') { $start = $i + 1; break } }
    if ($start -lt 0) { return $null }
    $end = $lines.Count
    if ($Version) {
        for ($i = $start; $i -lt $lines.Count; $i++) {
            if ($lines[$i].StartsWith('### ') -and $lines[$i].Contains($Version)) { $end = $i; break }
        }
    }
    return ($lines[$start..($end - 1)] -join "`n").Trim()
}

# "Changed 20  New 32  Fixed 74  Updated 9", or '' when unavailable.
function Get-TsWezChangesTally([string]$Version) {
    $text = Get-TsWezChangesText $Version
    if (-not $text) { return '' }
    $section = $null; $counts = [ordered]@{}
    foreach ($line in ($text -split "`n")) {
        if ($line -match '^#### +(.+?)\s*$') { $section = $Matches[1]; if (-not $counts.Contains($section)) { $counts[$section] = 0 }; continue }
        if ($section -and $line -match '^\* ') { $counts[$section] = $counts[$section] + 1 }
    }
    return (@($counts.Keys | Where-Object { $counts[$_] } | ForEach-Object { "$_ $($counts[$_])" }) -join '  ')
}

function Show-TsWezStatus {
    $inst = Get-TsWezInstalled
    $channel = Get-TsWezChannel
    Write-Host '==> WezTerm'
    if (-not $inst) {
        Write-Host '    Installed : not installed'
    } else {
        Write-Host ("    Installed : {0}  ({1}, {2})" -f $inst.Version, $channel, (Format-TsWezDate $inst.Date))
        if ($channel -eq 'unknown') {
            Write-Host '                not from a package manager here — left alone by install/upgrade'
        }
    }
    $st = Get-TsWezLatestStable
    $ni = Get-TsWezLatestNightly
    if (-not $st -and -not $ni) { Write-Host '    Latest    : (offline — could not reach GitHub)'; return }
    if ($ni) { Write-Host "    nightly   : built $ni" }
    if ($st) {
        $line = "    stable    : {0}  ({1})" -f $st.Tag, $st.Date
        if ($inst -and $st.Tag -eq $inst.Version) { $line += '  — you are on it' }
        Write-Host $line
    }
    if ($inst) {
        $tally = Get-TsWezChangesTally $inst.Version
        $commits = Get-TsWezCommitsSince $inst.Hash
        if ($commits -or $tally) {
            $line = '    Since your build:'
            if ($commits) { $line += " $commits commits" }
            if ($commits -and $tally) { $line += ' —' }
            if ($tally) { $line += " $tally" }
            Write-Host $line
            if ($tally) { Write-Host '    Full notes: tstack config wezterm changes' }
        }
    }
}

# A newer build on the channel you are already on? One line when yes, nothing
# otherwise — tstack update gates its offer on this, so silence is the common case.
function Get-TsWezUpdateAvailable {
    $inst = Get-TsWezInstalled
    if (-not $inst) { return '' }
    switch (Get-TsWezChannel) {
        'stable' {
            $st = Get-TsWezLatestStable
            if (-not $st -or $st.Tag -eq $inst.Version) { return '' }
            return "stable $($st.Tag) ($($st.Date)) is newer than your $($inst.Version)"
        }
        'nightly' {
            $ni = Get-TsWezLatestNightly
            if (-not $ni) { return '' }
            if (($ni -replace '-','') -le $inst.Date) { return '' }
            return "a nightly built $ni is newer than your $(Format-TsWezDate $inst.Date) build"
        }
        default { return '' }
    }
}

# Install/switch channel. Switching means removing the other package first: the
# two winget packages both install WezTerm to the same place.
function Install-TsWezterm([string]$Channel) {
    if ($Channel -notin 'stable', 'nightly') { Write-Warning 'Install-TsWezterm: expected stable|nightly'; return }
    if ((Get-TsWezChannel) -eq 'unknown') {
        Write-Host '==> WezTerm: installed outside winget; leaving it alone.'
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Write-Warning 'winget not available.'; return }
    $want  = if ($Channel -eq 'nightly') { 'wez.wezterm.nightly' } else { 'wez.wezterm' }
    $other = if ($Channel -eq 'nightly') { 'wez.wezterm' } else { 'wez.wezterm.nightly' }
    $o = & winget list --id $other --exact 2>&1
    if ($LASTEXITCODE -eq 0 -and ($o -match [regex]::Escape($other))) {
        Write-Host "==> WezTerm: removing $other (switching channel)"
        & winget uninstall --id $other --exact --silent 2>&1 | Select-Object -Last 2
    }
    if (Get-Command Install-WingetPackage -ErrorAction SilentlyContinue) {
        Install-WingetPackage -Id $want -Because "terminal emulator ($Channel)" | Out-Null
    } else {
        Write-Host "==> winget install $want"
        & winget install --id $want --exact --silent --accept-source-agreements --accept-package-agreements 2>&1 |
            Select-Object -Last 2
    }
}

function Update-TsWezterm {
    switch (Get-TsWezChannel) {
        'stable'  { Install-TsWezterm 'stable' }
        'nightly' { Install-TsWezterm 'nightly' }
        'unknown' { Write-Host '==> WezTerm: installed outside winget; upgrade it the way you installed it.' }
        default   { Write-Host "==> WezTerm: not installed. 'tstack config wezterm install nightly' to add it." }
    }
}

# Which GUI terminal emulators to install — a tick-list, so each is individually
# opt-in and "none" is one keystroke away. WezTerm appears TWICE, once per
# channel: upstream's newest stable is 20240203 (February 2024, no cut since),
# so nightly is what this stack's Lua config targets and is the pre-selected
# answer — but it is never automatic, and the intro shows the real build dates
# so the choice is made on facts rather than on a default nobody read.
# Twin of bootstrap/_wizard.sh ts_prompt_terminals — keep the rendering identical.
$script:TsTerminalCandidates = @(
    @{ Key = 'wezterm-nightly'; Label = 'WezTerm nightly'; Note = 'current builds; what this stack configures' }
    @{ Key = 'wezterm-stable';  Label = 'WezTerm stable';  Note = '20240203 — upstream has not cut one since' }
)
$script:TsTerminalWingetIds = @{ 'wezterm-nightly' = 'wez.wezterm.nightly'; 'wezterm-stable' = 'wez.wezterm' }

# The WezTerm channel a selection names, or '' when WezTerm was not picked.
function Get-TsTerminalsChannel([string[]]$Selected) {
    if ($Selected -contains 'wezterm-nightly') { return 'nightly' }
    if ($Selected -contains 'wezterm-stable')  { return 'stable' }
    return ''
}










# Install the selected toggleable apps via winget (catalog id -> winget id).
# Workspace root for the ws/wsp/wspu profile functions. Same contract as the
# WSL/Linux/Mac bootstraps: $env:WORKSPACE_DIR skips the prompt.
function Get-TsDetectedWorkspace {
    foreach ($d in @(
        'C:\DATA\Workspace',
        (Join-Path $env:USERPROFILE 'workspace'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace')
    )) { if (Test-Path $d) { return $d } }
    return $null
}

# The interpreter the questionnaire and the rest of tstack run on. Same probe as
# bootstrap/tts-daemon/build.ps1's Find-Python, and the same floor: 3.10.
# Returns $null rather than throwing -- the caller says what it needed it for.
function Get-TsPython {
    foreach ($candidate in @('python', 'python3', 'py')) {
        $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $command) { continue }
        try {
            $version = & $command.Source -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
            if ($version -and ([version]$version.Trim() -ge [version]'3.10')) { return $command.Source }
        } catch {}
    }
    return $null
}

# ── The install questionnaire ───────────────────────────────────────────────────
# Every Read-Ts* prompt that used to live here is gone. The questionnaire is one
# Python implementation, tstack/wizard/, shared with the bash bootstraps -- two
# implementations of fourteen questions had to be kept in agreement by hand, and
# had not been: this side rejected a whole multi-answer where bash applied the
# valid tokens and warned about the rest.
#
# windows-bootstrap.ps1 runs `tstack wizard --emit json` and reads the object.
# The JSON keys are the PascalCase names the old hashtable used, so every $w.X
# downstream is unchanged.

# Run the questionnaire and return its answers as an object, or $null if the
# user quit or it failed. ONE copy, because there are two callers -- the
# bootstrap and `tstack config wizard` in $PROFILE -- and the last time each had
# its own, $PROFILE was still calling a Read-TsWizard that no longer existed.
#
# -Only runs a single question ("apps"), which is what the config menu's apps
# item needs; the POSIX twin is run_wizard_apps in bootstrap/ts-config.sh.
function Invoke-TsWizard {
    param([string]$SourceDir, [switch]$AskTerminals, [string]$Only)
    $python = Get-TsPython
    if (-not $python) {
        Write-Warning 'python3 is required to run the install questionnaire.'
        return $null
    }
    $out = Join-Path ([IO.Path]::GetTempPath()) ("tswiz-" + [guid]::NewGuid() + ".json")
    $wizardArgs = @((Join-Path $SourceDir 'tstack\main.py'), 'wizard', '--emit', 'json', '--out', $out)
    if ($Only) { $wizardArgs += @('--only', $Only) }
    if ($AskTerminals) { $wizardArgs += '--ask-terminals' }
    if ($env:TS_ASSUME_YES) { $wizardArgs += '--assume-yes' }
    try {
        & $python @wizardArgs
        $rc = $LASTEXITCODE
        # 3 is "quit at the review", which every caller treats as cancelled --
        # not as a failure to report.
        if ($rc -ne 0 -or -not (Test-Path -LiteralPath $out)) { return $null }
        return (Get-Content -LiteralPath $out -Raw | ConvertFrom-Json)
    } finally {
        Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
    }
}

function Read-TsWorkspaceDir {
    if ($env:WORKSPACE_DIR) {
        Write-Host "==> WORKSPACE_DIR=$($env:WORKSPACE_DIR) (from env; skipping prompt)"
        return $env:WORKSPACE_DIR
    }
    $detected = Get-TsDetectedWorkspace
    $promptDefault = if ($detected) { $detected } else { 'none' }
    if (-not (Test-TsInteractive)) { return $detected }
    Write-Host ''
    $answer = Read-Host "Workspace directory [$promptDefault]"
    if ($answer) { $answer.Trim() } else { $detected }
}

# Persist a workspace answer that differs from the autodetect. Lives here, not in
# windows-bootstrap.ps1, so `tstack config wizard` does not silently drop the answer
# it just asked for. The caller owns any -WhatIf/ShouldProcess gate.
function Save-TsWorkspaceOverride {
    param([string]$Choice)

    $detected = Get-TsDetectedWorkspace
    if (-not $Choice) {
        Write-Warning 'No workspace directory found or chosen. Set one later: $env:WORKSPACE_DIR in profile.local.ps1'
        return
    }
    if ($Choice -eq $detected) {
        Write-Host "==> Workspace: $Choice (autodetected; no override needed)"
        return
    }
    if (-not (Test-Path $Choice)) { Write-Warning "$Choice does not exist (yet) — ws will warn until it does." }
    # pwsh 7's $PROFILE is Documents\PowerShell\...; resolve via MyDocuments so
    # this works even when the caller runs under Windows PowerShell 5.
    $localProfile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    New-Item -ItemType Directory -Force -Path (Split-Path $localProfile) | Out-Null
    $line = "`$env:WORKSPACE_DIR = '$Choice'"
    if ((Test-Path $localProfile) -and (Get-Content $localProfile | Where-Object { $_ -match '^\s*\$env:WORKSPACE_DIR\s*=' })) {
        # -replace can't go empty, so the pipeline-into-Set-Content trap does not apply.
        (Get-Content $localProfile) -replace '^\s*\$env:WORKSPACE_DIR\s*=.*', $line | Set-Content $localProfile
        Write-Host "==> Updated WORKSPACE_DIR in $localProfile"
    } else {
        Add-Content -Path $localProfile -Value $line
        Write-Host "==> Wrote WORKSPACE_DIR=$Choice to $localProfile"
    }
}

# The whole install questionnaire, in one place so both the bootstrap and
# `tstack config wizard` ask exactly the same questions in the same order. POSIX
# twin: ts_wizard_ask / ts_wizard_collect in bootstrap/_wizard.sh.
# The first question. Everything else in this wizard is downstream of it, which
# is why it is first: asking about the leader key, the mux, voice notifications
# and a memory backend BEFORE establishing that is fourteen questions aimed at
# someone who wanted one thing.
#
# NOT a saved setting, deliberately -- it decides what the REST of the wizard
# asks and what those answers default to, and every one of them is saved on its
# own. A stored `profile` would be a second copy of state that can disagree with
# the settings it produced. Twin of ts_prompt_profile in bootstrap/_wizard.sh.
# ── which prompt ────────────────────────────────────────────────────────────────
# Twins of ts_starship_* in bootstrap/_config.sh. "terminal-stack" (default) is
# this repo's own prompt; any other value is one of Starship's built-in presets,
# rendered over the mirrored starship.toml by scripts/sync-windows.ps1.
function Get-TsStarshipPresets {
    $starship = Get-Command starship -ErrorAction SilentlyContinue
    if (-not $starship) { return @() }
    # `--list` emits a trailing blank line; a bare pass-through turns it into an
    # empty entry in every menu.
    return @(& $starship.Source preset --list 2>$null |
        Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() })
}

function Get-TsStarshipPreset {
    $v = (Get-TsConfig).starshipPreset
    if ($v) { return [string]$v }
    return 'terminal-stack'
}

# Render one prompt exactly as it would look, without installing it.
#
# STARSHIP_SHELL must be EMPTY, not unset: with a shell name starship emits that
# shell's escaping, which prints as literal punctuation rather than as colour.
function Show-TsStarshipPreview([string]$Name) {
    $starship = Get-Command starship -ErrorAction SilentlyContinue
    if (-not $starship) { Write-Host '  (starship is not installed yet)'; return }
    $cfg = $null
    try {
        if ($Name -eq 'terminal-stack') {
            $cfg = Join-Path $env:USERPROFILE '.config\starship.toml'
            if (-not (Test-Path -LiteralPath $cfg)) {
                Write-Host '  (not deployed yet -- it appears after the first sync)'
                return
            }
        } else {
            # Redirect, never `-o`: that refuses to overwrite an existing file,
            # which would leave the temp file empty and the preview silently blank.
            $body = & $starship.Source preset $Name 2>$null
            if (-not $body) { Write-Host "  (no preset named $Name)"; return }
            $cfg = [IO.Path]::GetTempFileName()
            Set-Content -LiteralPath $cfg -Value (($body -join "`n") + "`n") -NoNewline -Encoding UTF8
        }
        $savedShell = $env:STARSHIP_SHELL
        $savedConfig = $env:STARSHIP_CONFIG
        try {
            $env:STARSHIP_SHELL = ''
            $env:STARSHIP_CONFIG = $cfg
            & $starship.Source prompt 2>$null
            Write-Host ''
        } finally {
            $env:STARSHIP_SHELL = $savedShell
            $env:STARSHIP_CONFIG = $savedConfig
        }
    } finally {
        if ($cfg -and $Name -ne 'terminal-stack' -and (Test-Path -LiteralPath $cfg)) {
            Remove-Item -LiteralPath $cfg -Force -ErrorAction SilentlyContinue
        }
    }
}





function Install-TsTerminals {
    param([string[]]$Selected)

    if (-not $Selected) { Write-Host '==> Terminal emulator: none selected — skipped'; return }
    $channel = Get-TsTerminalsChannel $Selected
    if ($channel) {
        # Install-TsWezterm removes the other channel first; nothing is removed
        # when WezTerm was not selected at all.
        Install-TsWezterm $channel
    } else {
        Write-Host '==> WezTerm: not selected — skipped'
    }
}

# Pull Machine + User Path back out of the environment and rebuild the process
# PATH from them. An installer that ran a moment ago edited the persisted Path,
# but this process was started before that, so Get-Command still cannot see what
# was just installed — which is how Show-TsInstalledApps came to report a tool
# as "NOT FOUND on PATH" seconds after installing it successfully. This is the
# pwsh counterpart of ts_load_node_env's role in ts_apps_pending. Prepending the
# live process PATH keeps anything a session set by hand (fnm's per-shell entry,
# a manual prepend) from being dropped.
function Update-TsSessionPath {
    try {
        $persisted = @(
            [Environment]::GetEnvironmentVariable('Path', 'Machine'),
            [Environment]::GetEnvironmentVariable('Path', 'User')
        ) -join ';'
        $seen = @{}; $merged = @()
        foreach ($dir in (($env:PATH + ';' + $persisted) -split ';')) {
            $d = $dir.Trim()
            if (-not $d) { continue }
            if ($seen.ContainsKey($d.ToLower())) { continue }
            $seen[$d.ToLower()] = $true
            $merged += $d
        }
        $env:PATH = $merged -join ';'
    } catch { }   # never fatal: a stale PATH only costs an inaccurate report
}

function Install-TsApps([string[]]$Apps) {
    if (-not $Apps -or $Apps.Count -eq 0) {
        Write-Host '==> No optional apps selected; skipping app install'
        return
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        foreach ($id in $Apps) {
            if (Test-TsAppIsAi $id) { continue }   # handled by Install-TsAiCli below
            if (Test-TsAppIsPy $id) { continue }   # handled by Install-TsPyTool below
            if ($script:TsWingetIds.ContainsKey($id)) {
                $wid = $script:TsWingetIds[$id]
                Write-Host "==> winget install $wid"
                & winget install --id $wid --exact --silent --accept-source-agreements --accept-package-agreements 2>&1 |
                    Select-Object -Last 2
            } else {
                Write-Host "==> ${id}: no Windows package available; skipped"
            }
        }
    } else {
        Write-Warning 'winget not available; recorded selection only.'
    }
    # Python tools go after the winget pass and before the agent CLIs: `python`
    # and `uv` are themselves winget entries, and Install-TsPyTool prefers uv.
    # Refresh PATH first so a uv installed seconds ago is actually visible.
    if (@($Apps | Where-Object { Test-TsAppIsPy $_ }).Count) {
        Update-TsSessionPath
        foreach ($id in $Apps) { if (Test-TsAppIsPy $id) { Install-TsPyTool $id } }
    }
    foreach ($id in $Apps) { if (Test-TsAppIsAi $id) { Install-TsAiCli $id } }
    Update-TsSessionPath
}

# The Python CLI tools, none of which winget carries. Idempotent, never fatal,
# and only ever runs for an id in $TsPyTools. Twin of the brew half of
# ts_install_apps in bootstrap/_config.sh.
#
# uv first: it is already in the recommended set, it puts real shims on PATH
# (%USERPROFILE%\.local\bin, which its own installer adds), and it needs no
# ambient Python.
# `py -m pip install --user` is the fallback for a machine that declined uv.
function Install-TsPyTool([string]$id) {
    $bin = Get-TsAppBin $id
    $existing = Get-Command $bin -CommandType Application -ErrorAction SilentlyContinue
    if ($existing) { Write-Host "==> ${id}: already installed ($($existing.Source))"; return }
    # The PyPI distribution name is the catalog id for every tool in $TsPyTools.
    # If one ever differs, map it here rather than at the call sites.
    $pkg = $id

    if (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue) {
        Write-Host "==> ${id}: uv tool install $pkg"
        & uv tool install $pkg 2>&1 | Select-Object -Last 3
        if ($LASTEXITCODE -eq 0) { return }
        Write-Warning "${id}: uv tool install failed; trying pip"
    }
    $py = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python -CommandType Application -ErrorAction SilentlyContinue }
    if (-not $py) {
        Write-Warning "${id}: no uv and no Python found; install one, then: uv tool install $pkg"
        return
    }
    Write-Host "==> ${id}: $($py.Name) -m pip install --user $pkg"
    & $py.Source -m pip install --user --disable-pip-version-check $pkg 2>&1 | Select-Object -Last 3
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "${id}: install failed; run manually: uv tool install $pkg"
    }
}

# The agent CLIs do not come from winget, so they get their own path. Idempotent
# (skips when already on PATH), never fatal, and only ever runs for an id that
# was actually ticked — every one of them is in $TsAppsOptional.
# Twin of ts_install_ai_cli in bootstrap/_config.sh.
function Install-TsAiCli([string]$id) {
    $bin = Get-TsAppBin $id
    $existing = Get-Command $bin -CommandType Application -ErrorAction SilentlyContinue
    if ($existing) { Write-Host "==> ${id}: already installed ($($existing.Source))"; return }
    switch ($id) {
        'claude' {
            Write-Host '==> claude: installing via the official installer'
            try { & powershell -NoProfile -Command "irm https://claude.ai/install.ps1 | iex" }
            catch { Write-Warning 'claude install failed; see https://docs.claude.com/en/docs/claude-code' }
        }
        'grok' {
            # xAI ship a standalone binary, so this needs no Node at all.
            Write-Host '==> grok: installing via the official installer'
            try { & powershell -NoProfile -Command "irm https://x.ai/cli/install.ps1 | iex" }
            catch { Write-Warning 'grok install failed; see https://x.ai/build' }
        }
        { $_ -in 'codex', 'gemini', 'pi' } {
            # npm-only. @openai/codex wants Node >= 16, @google/gemini-cli >= 20,
            # @earendil-works/pi-coding-agent >= 22.19 (its engines field).
            # No brew/winget fallback for gemini: the `gemini-cli` formula is
            # deprecated upstream and scheduled for removal on 2026-12-18.
            $pkg = switch ($id) {
                'codex'  { '@openai/codex' }
                'gemini' { '@google/gemini-cli' }
                'pi'     { '@earendil-works/pi-coding-agent' }
            }
            $want = switch ($id) { 'codex' { 16 } 'gemini' { 20 } 'pi' { 22 } }
            $node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue
            $major = 0
            if ($node) { $major = [int]((& node --version) -replace '^v(\d+).*', '$1') }
            if ($major -ge $want -and (Get-Command npm -ErrorAction SilentlyContinue)) {
                Write-Host "==> ${id}: installing $pkg via npm"
                & npm install -g $pkg
                if ($LASTEXITCODE -ne 0) { Write-Warning "$id install failed." }
            } else {
                Write-Warning "$id needs Node $want+ to install from npm (found: $(if ($major) { $major } else { 'none' }))."
                Write-Host '   Install the runtime first: tstack config apps fnm   (then: fnm install --lts)'
            }
        }
        'cursor-agent' {
            # There IS a Windows installer — the same URL as the POSIX one with
            # ?win32=true, which serves a PowerShell script instead of a shell
            # one. This used to warn "no Windows installer this stack can call;
            # install it inside WSL", which was simply wrong.
            #
            # Run under Windows PowerShell rather than pwsh, matching claude and
            # grok above: the script calls Get-WmiObject, which 5.1 always has
            # and which pwsh has removed and reinstated across versions.
            # Execution policy is not a concern — it governs script FILES, and
            # `iex` on a string is unaffected, so this works even where 5.1 is
            # Restricted.
            #
            # It installs to %LOCALAPPDATA%\cursor-agent and adds that to the
            # USER PATH (and the calling shell's), so Update-TsSessionPath makes
            # it visible to the rest of this run. Note the installer deletes that
            # directory before unpacking, so re-running it is destructive but
            # idempotent — which is exactly why the already-installed guard above
            # matters. It also drops a generic `agent.exe` alias beside it, the
            # same name grok claims; prefer `cursor-agent` (see doc node-python).
            Write-Host '==> cursor-agent: installing via the official installer'
            try { & powershell -NoProfile -Command "irm 'https://cursor.com/install?win32=true' | iex" }
            catch { Write-Warning 'cursor-agent install failed; see https://cursor.com/cli' }
        }
        default { Write-Warning "${id}: no agent-CLI installer defined" }
    }
}

# Print what each selected app resolved to, so an installer that failed quietly
# is visible rather than assumed.
# Twin of ts_report_installed_apps in bootstrap/_config.sh.
function Show-TsInstalledApps([string[]]$Apps) {
    if (-not $Apps -or $Apps.Count -eq 0) { return }
    Write-Host ''
    Write-Host '==> Installed tools:'
    foreach ($id in $Apps) {
        $bin = Get-TsAppBin $id
        $cmd = Get-Command $bin -CommandType Application -ErrorAction SilentlyContinue
        if ($cmd) {
            $ver = ''
            try { $ver = (& $bin --version 2>$null | Select-Object -First 1) } catch {}
            if (-not $ver) { $ver = $cmd.Source }
            Write-Host ("    {0,-14} {1}" -f $id, ("$ver" -replace '\e\[[0-9;]*m', '').Substring(0, [Math]::Min(40, "$ver".Length)))
        } elseif ($script:TsAppFixedPaths.ContainsKey($id) -and (Test-Path $script:TsAppFixedPaths[$id])) {
            Write-Host ("    {0,-14} {1}" -f $id, $script:TsAppFixedPaths[$id])
        } else {
            Write-Host ("    {0,-14} {1}" -f $id, 'NOT FOUND on PATH')
        }
    }
}

# Refresh only resolvedTheme from the live OS theme (used by tstack update for follow).
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
            url = 'http://127.0.0.1:8880'; model = 'kokoro'; voice = 'am_adam'; speed = 1.0
            format = 'mp3'; timeoutSec = 15
        }
        chatterbox  = [ordered]@{
            url = 'http://127.0.0.1:8881'; voice = 'adam'; energy = 0.25
            cfgWeight = 0.5; temperature = 0.6; timeoutSec = 60
        }
        # macOS-only, and carried here anyway: a combined Windows+WSL machine
        # writes this store from the WSL side, and a key the pwsh table omits is
        # STRIPPED from config.json on the next Windows save. That is how
        # atuinEnabled kept disappearing.
        say         = [ordered]@{ voice = '' }
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
        say = $Tts.say
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
    $tts = Get-TsProp (Get-TsConfig) ccTts
    if (-not $tts) { return (Get-CcTtsDefaults) }
    # Fill members added after the config was first stored (pre-daemon upgrades). The probe
    # itself has to be strict-safe: testing for a missing member is the whole point.
    $defaults = Get-CcTtsDefaults
    foreach ($key in @('daemon', 'summarize', 'music', 'voicePool',
                       'prefixCodex', 'prefixCodexEnabled')) {
        if ($null -eq (Get-TsProp $tts $key)) {
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


function Set-CcTtsWizardChoice {
    param([string]$Choice)
    $tts = Get-CcTtsDefaults
    if ($Choice -eq 'on') { $tts.enabled = $true }
    return $tts
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
            Write-Host 'tts daemon: running an older build than this clone — tstack config tts daemon restart'
        }
    } catch {
        Write-Host "tts daemon: not reachable on port $port (hooks fall back to direct playback)"
        $enabled = if ($tts.daemon) { [bool]$tts.daemon.enabled } else { $false }
        Write-Host "  saved setting daemon.enabled=$enabled  —  start: tstack config tts daemon on"
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
    # tstack doctor --repair: a snapshot left by a daemon that died mid-duck means
    # per-app volumes are still lowered (Windows persists them). The daemon's
    # own oneshot restores them; a live daemon owns its snapshot — leave it.
    $snap = Get-CcTtsDuckSnapshotPath
    if (-not (Test-Path -LiteralPath $snap)) { return }
    if (Test-CcTtsDaemonHealthy) { return }
    $ttsExe = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
    if (-not (Test-Path -LiteralPath $ttsExe)) {
        Write-Warning "stale duck snapshot at $snap but no TTS executable — reinstall with tstack config tts daemon install"
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
        Write-Warning 'tts: speak-summary.md asset not found (run tstack update?)'
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
            if (-not $Arg) { Write-Warning 'usage: tstack config tts engine kokoro|chatterbox|auto'; return }
            $tts.engine = $Arg
        }
        'message' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts message template|hook'; return }
            $tts.messageMode = $Arg
        }
        'voice' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts voice <kokoro-voice>'; return }
            $tts.kokoro.voice = $Arg
        }
        'voice-chatter' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts voice-chatter <name>'; return }
            $tts.chatterbox.voice = $Arg
        }
        'energy' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts energy <0-1>'; return }
            $tts.chatterbox.energy = [double]$Arg
            $tts.excitement = [double]$Arg
        }
        'excitement' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts excitement <0-1>'; return }
            $tts.excitement = [double]$Arg
            $tts.chatterbox.energy = [double]$Arg
        }
        'prefix' {
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: tstack config tts prefix claude|cursor|codex on|off|<label>'; return }
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
            if (-not $Arg) { Write-Warning 'usage: tstack config tts project on|off'; return }
            $tts.includeProject = ($Arg -eq 'on')
        }
        'template' {
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: tstack config tts template waiting|error|question|permission "…"'; return }
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
            if (-not $Arg -or -not $Arg2) { Write-Warning 'usage: tstack config tts url kokoro|chatterbox <url>'; return }
            switch ($Arg) {
                'kokoro'     { $tts.kokoro.url = $Arg2 }
                'chatterbox' { $tts.chatterbox.url = $Arg2 }
                default      { Write-Warning 'expected kokoro or chatterbox'; return }
            }
        }
        'events' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts events waiting,error,question,permission'; return }
            $tts.events = @($Arg -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        'daemon' {
            switch ($Arg) {
                'on' {
                    if (-not (Invoke-TsCcTtsDaemonInstaller)) { return }
                    $tts.daemon.enabled = $true
                    Write-Host "note: this enables the daemon for Windows-side hooks; if you also run Claude in WSL, run 'tstack config tts daemon on' from WSL so those hooks route to it too."
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
                Write-Warning 'usage: tstack config tts summarizer template|self|haiku|ollama'; return
            }
            $tts.summarize.mode = $Arg
            if ($Arg -eq 'self') { Install-CcTtsSelfBlock } else { Remove-CcTtsSelfBlock }
        }
        'haiku-model' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts haiku-model <model>'; return }
            $tts.summarize.haikuModel = $Arg
        }
        'ollama' {
            if (-not $Arg) { Write-Warning 'usage: tstack config tts ollama <url> [<model>]'; return }
            $tts.summarize.ollamaUrl = $Arg
            if ($Arg2) { $tts.summarize.ollamaModel = $Arg2 }
        }
        'music' {
            if ($Arg -notin 'duck', 'smart', 'pause', 'off') {
                Write-Warning 'usage: tstack config tts music duck|smart|pause|off'; return
            }
            $tts.music.mode = $Arg
        }
        'duck-level' {
            if ($Arg -notmatch '^\d+$' -or [int]$Arg -gt 100) {
                Write-Warning 'usage: tstack config tts duck-level <0-100>'; return
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
            if ($Arg -notmatch '^\d+$') { Write-Warning 'usage: tstack config tts port <n>'; return }
            $tts.daemon.port = [int]$Arg
        }
        'test' {
            $test = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
            if (Test-Path -LiteralPath $test) {
                $source = if ($Arg -eq '--source' -and $Arg2) { $Arg2 } else { 'test' }
                & $test test --source $source
            } else {
                Write-Warning "terminal-stack-tts.exe not found at $test (run tstack config tts on)"
            }
            return
        }
        'history' {
            # Same reasoning as the bash twin: read it from the executable, so a dead
            # daemon is still able to explain itself.
            $exe = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
            if (-not (Test-Path -LiteralPath $exe)) {
                Write-Warning "terminal-stack-tts.exe not found at $exe (run tstack config tts daemon install)"
                return
            }
            $hargs = @('history')
            if ($Arg -in '--dupes', 'dupes') {
                $hargs += '--dupes'
                if ($Arg2 -match '^[\d.]+$') { $hargs += @('--within', $Arg2) }
            } elseif ($Arg -match '^\d+$') {
                $hargs += @('--limit', $Arg)
            }
            & $exe @hargs | Out-Host
            return
        }
        'reset' { $tts = Get-CcTtsDefaults }
        default {
            Write-Warning "tstack config tts: unknown subcommand '$Sub' (show, on, off, test, reset, ...)"
            return
        }
    }
    if ($Sub -in 'on','off','engine','message','voice','voice-chatter','energy','excitement','url','events','prefix','project','template','reset','daemon','summarizer','haiku-model','ollama','music','duck-level','voices','port') {
        & $Apply $tts
        Invoke-CcTtsDaemonConfigReload $tts
    }
}
