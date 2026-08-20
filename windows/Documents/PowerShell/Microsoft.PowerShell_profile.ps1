$env:_ZO_ECHO = '1'
$env:_ZO_EXCLUDE_DIRS = 'C:\Windows\*;*\node_modules\*;*\.git\*;*\target\*;*\dist\*;*\build\*'

function zoxide-prune {
  zoxide query -l | Where-Object { -not (Test-Path $_) } | ForEach-Object { zoxide remove $_ }
}

# ---- workspace-nav-start ----
# Workspace navigation (mirrors the zsh ws* functions). $env:WORKSPACE_DIR
# (set in profile.local.ps1) wins; otherwise the first existing autodetect
# candidate. Resolved at call time so the local override always applies.
function Get-TsWorkspace {
    if ($env:WORKSPACE_DIR) { return $env:WORKSPACE_DIR }
    foreach ($d in @(
        'C:\DATA\Workspace',
        (Join-Path $env:USERPROFILE 'workspace'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace')
    )) {
        if (Test-Path $d) { return $d }
    }
    return $null
}
# Sibling resolver: handles both Workspace_Personal and Workspace-Personal naming.
function Get-TsWorkspaceSibling([string]$Suffix) {
    $root = Get-TsWorkspace
    if (-not $root) { return $null }
    foreach ($d in @("${root}_${Suffix}", "${root}-${Suffix}")) {
        if (Test-Path $d) { return $d }
    }
    return $null
}
function ws {
    $r = Get-TsWorkspace
    if ($r) { Set-Location $r } else { Write-Warning 'ws: no workspace found — set $env:WORKSPACE_DIR in profile.local.ps1' }
}
function wsp {
    $r = Get-TsWorkspaceSibling 'Personal'
    if ($r) { Set-Location $r } else { Write-Warning 'wsp: no *_Personal sibling' }
}
# wspu prefers the organised public\ tier and falls back to the old *_Public
# sibling root, so it keeps working before, during and after `wso migrate`.
function wspu {
    $root = Get-TsWorkspace
    if ($root) {
        foreach ($d in @((Join-Path $root 'public\github.com'), (Join-Path $root 'public'))) {
            if (Test-Path -LiteralPath $d) { Set-Location $d; return }
        }
    }
    $r = Get-TsWorkspaceSibling 'Public'
    if ($r) { Set-Location $r } else { Write-Warning 'wspu: no public\ tier and no *_Public sibling' }
}

# --- organised tree: per-owner jumps -----------------------------------------
# Repos live at <workspace>\<tier>\<host>\<owner>\<repo>; see `doc workspace-org`.
# These stay profile functions rather than moving into `wso` because a child
# process cannot change the parent shell's directory.
function Set-TsWsOrgLocation([string]$Owner, [string]$Name) {
    $root = Get-TsWorkspace
    if (-not $root) { Write-Warning "${Name}: no workspace found"; return }
    foreach ($d in @((Join-Path $root "src\github.com\$Owner"),
                     (Join-Path $root "archive\github.com\$Owner"))) {
        if (Test-Path -LiteralPath $d) { Set-Location $d; return }
    }
    Write-Warning "${Name}: $root\src\github.com\$Owner does not exist yet - run 'wso plan'"
}
function ws37 { Set-TsWsOrgLocation '37metrics'        'ws37' }
function ws42 { Set-TsWsOrgLocation 'dimension42ai'    'ws42' }
function wsmb { Set-TsWsOrgLocation 'martybytes'       'wsmb' }
function wsmd { Set-TsWsOrgLocation 'moleculardesigns' 'wsmd' }
function wsar {
    $root = Get-TsWorkspace
    if (-not $root) { Write-Warning 'wsar: no workspace found'; return }
    foreach ($d in @((Join-Path $root 'archive\github.com'), (Join-Path $root 'archive'))) {
        if (Test-Path -LiteralPath $d) { Set-Location $d; return }
    }
    Write-Warning 'wsar: nothing archived on this machine yet'
}

# wsj — fuzzy-jump to any repo in the tree. This is what makes the deep paths
# free: you never type them. Falls back to a filtered menu without fzf.
function wsj {
    param([string]$Query)
    $root = Get-TsWorkspace
    if (-not $root) { Write-Warning 'wsj: no workspace found'; return }
    $repos = @()
    foreach ($t in @('src', 'public', 'archive', 'local')) {
        $p = Join-Path $root $t
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $repos += Get-ChildItem -LiteralPath $p -Directory -Recurse -Depth 4 -Force -ErrorAction SilentlyContinue |
                  Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName '.git') } |
                  ForEach-Object { $_.FullName.Substring($root.Length).TrimStart('\') }
    }
    if (-not $repos.Count) { Write-Warning "wsj: no repos found under $root - run 'wso plan'"; return }
    $sel = $null
    if (Get-Command fzf -ErrorAction SilentlyContinue) {
        $sel = $repos | Sort-Object | fzf --height 40% --reverse --query "$Query" --prompt 'repo> '
    } elseif ($Query) {
        $hits = @($repos | Where-Object { $_ -like "*$Query*" } | Sort-Object)
        if (-not $hits.Count) { Write-Warning "wsj: no repo matching '$Query'"; return }
        if ($hits.Count -eq 1) { $sel = $hits[0] }
        else {
            for ($i = 0; $i -lt $hits.Count; $i++) { "{0,3}) {1}" -f ($i + 1), $hits[$i] }
            $n = Read-Host 'select [1]'
            if (-not $n) { $n = 1 }
            $sel = $hits[[int]$n - 1]
        }
    } else {
        Write-Warning "wsj: fzf not installed - pass a search term, e.g. 'wsj ironcl'"; return
    }
    if ($sel) { Set-Location (Join-Path $root $sel) }
}

# Work workspace. $env:WORK_WORKSPACE_DIR (set in profile.local.ps1) wins;
# otherwise the *_Work / *-Work sibling of the main workspace — same naming rule
# as wsp/wspu. `wsw --set` writes that override for you, so a machine whose work
# tree lives somewhere unrelated to the main workspace needs no hand-editing.
function Get-TsWorkspaceWork {
    if ($env:WORK_WORKSPACE_DIR) { return $env:WORK_WORKSPACE_DIR }
    return (Get-TsWorkspaceSibling 'Work')
}
function Set-TsWorkspaceWork([string]$Path) {
    if (-not $Path) { $Path = (Get-Location).Path }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Write-Warning "wsw: not a directory: $Path"
        return
    }
    $full = (Resolve-Path -LiteralPath $Path).Path
    $rc   = Join-Path (Split-Path $PROFILE) 'profile.local.ps1'
    $line = "`$env:WORK_WORKSPACE_DIR = '" + ($full -replace "'", "''") + "'"
    if (Test-Path -LiteralPath $rc) {
        $stamp = Get-Date -Format 'yyyyMMdd'
        $bak = "$rc.bak.$stamp"; $n = 1
        while (Test-Path -LiteralPath $bak) { $bak = "$rc.bak.$stamp.$n"; $n++ }
        Copy-Item -LiteralPath $rc -Destination $bak -Force
        Write-Host "wsw: backup $bak"
        $kept = @(Get-Content -LiteralPath $rc | Where-Object { $_ -notmatch '^\s*\$env:WORK_WORKSPACE_DIR\s*=' })
        Set-Content -LiteralPath $rc -Value ($kept + $line) -Encoding utf8
        Write-Host "wsw: updated $rc"
    } else {
        $dir = Split-Path -Parent $rc
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Set-Content -LiteralPath $rc -Encoding utf8 -Value @(
            '# Per-machine pwsh overrides — not synced by the stack.', $line)
        Write-Host "wsw: created $rc"
    }
    $env:WORK_WORKSPACE_DIR = $full
    Write-Host "wsw: WORK_WORKSPACE_DIR=$full"
}
function wsw {
    if ($args.Count -gt 0) {
        switch -Regex ([string]$args[0]) {
            '^(--set|-s|-set)$' { Set-TsWorkspaceWork ([string]$args[1]); return }
            '^(--show|-show)$'  {
                $r = Get-TsWorkspaceWork
                if ($r) { Write-Output $r } else { Write-Warning 'wsw: no work workspace configured' }
                return
            }
            '^(-h|--help|-help)$' {
                Write-Output 'wsw              cd to the work workspace'
                Write-Output 'wsw --set [dir]  define it in profile.local.ps1 (default: current dir)'
                Write-Output 'wsw --show       print the resolved path'
                return
            }
        }
    }
    $r = Get-TsWorkspaceWork
    if ($r) {
        Set-Location $r
    } else {
        Write-Warning "wsw: no work workspace found — looked for `$env:WORK_WORKSPACE_DIR and *_Work/*-Work siblings of $(Get-TsWorkspace)"
        Write-Warning "wsw: run 'wsw --set [dir]' to define one in profile.local.ps1"
    }
}
# Project-specific shortcuts (wscalibra, wsnetsuite, …) belong in
# profile.local.ps1 — see profile.local.ps1.example.
# ---- workspace-nav-end ----

function Set-WezTabTitle([string]$title) {
    if (-not $env:WEZTERM_PANE) { return }
    & wezterm.exe cli set-tab-title $title 2>$null
    # Empty title marks CC exit -> clear cc_state; WezTerm Lua restores pane bg.
    if (-not $title) {
        try {
            [Console]::Out.Write("$([char]27)]1337;SetUserVar=cc_state=$([char]7)")
        } catch {}
    }
}

# Bare project leaf as the tab title — no 'cc' prefix: the WezTerm tab bar's
# Claude icon and state dots already say Claude, and the prefix wasted tab width.
function cc    { Set-WezTabTitle "$(Split-Path -Leaf $PWD)"; try { claude @args } finally { Set-WezTabTitle "" } }
function ccc   { Set-WezTabTitle "$(Split-Path -Leaf $PWD)"; try { claude --continue @args } finally { Set-WezTabTitle "" } }
function ccd   { Set-WezTabTitle "$(Split-Path -Leaf $PWD)"; try { claude --dangerously-skip-permissions @args } finally { Set-WezTabTitle "" } }
function ccdc  { Set-WezTabTitle "$(Split-Path -Leaf $PWD)"; try { claude --dangerously-skip-permissions --continue @args } finally { Set-WezTabTitle "" } }
function ccr   { Set-WezTabTitle "$(Split-Path -Leaf $PWD)"; try { claude --resume @args } finally { Set-WezTabTitle "" } }
function ccdr  { Set-WezTabTitle "$(Split-Path -Leaf $PWD)"; try { claude --dangerously-skip-permissions --resume @args } finally { Set-WezTabTitle "" } }
function cca   { Set-WezTabTitle "agents"; try { claude agents } finally { Set-WezTabTitle "" } }

# Escape hatch: vanilla pwsh, no profile (no starship/zoxide/aliases).
# Nested — `exit` drops back to the customized shell.
function plain { Set-WezTabTitle "plain • $(Split-Path -Leaf $PWD)"; try { pwsh -NoLogo -NoProfile @args } finally { Set-WezTabTitle "" } }

# ---- starship-stack-start ----

# Cursor/Claude agent shells set TERM=dumb and CURSOR_AGENT=1 — skip prompt chrome there.
function Test-TsAgentShell {
    if ($env:CURSOR_AGENT -eq '1') { return $true }
    if ($env:TERM -eq 'dumb') { return $true }
    if ($env:CI -eq 'true' -or $env:CI -eq '1') { return $true }
    return $false
}

# Native console children (Claude Code, etc.) can SetConsoleOutputCP back to 437 on exit; [Console]::OutputEncoding caches and won't catch it, so probe the OS codepage directly.
if (-not ('Native.ConsoleCP' -as [type])) {
    Add-Type -Namespace Native -Name ConsoleCP -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint GetConsoleOutputCP();
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern bool SetConsoleOutputCP(uint wCodePageID);
'@ | Out-Null
}
[Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

if (-not (Test-TsAgentShell)) {
    Invoke-Expression (&starship init powershell)
    if (Get-Command Enable-TransientPrompt -ErrorAction SilentlyContinue) { Enable-TransientPrompt }

    function Invoke-Starship-PreCommand {
        if ([Native.ConsoleCP]::GetConsoleOutputCP() -ne 65001) {
            [Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            [Console]::InputEncoding  = [System.Text.Encoding]::UTF8
        }
        $loc = $executionContext.SessionState.Path.CurrentLocation
        if ($loc.Provider.Name -eq 'FileSystem') {
            $hostName = ($env:COMPUTERNAME).ToLower()
            $providerPath = $loc.ProviderPath -replace '\\', '/'
            Write-Host -NoNewline "`e]7;file://${hostName}/${providerPath}`a"
            $leaf = Split-Path -Leaf $loc.Path
            if ([string]::IsNullOrEmpty($leaf)) { $leaf = $loc.Path }
            Write-Host -NoNewline "`e]0;pwsh • $leaf`a"
        }
    }
}
# ---- starship-stack-end ----

# ---- cli-tools-start ----
# Default editor: micro (a nano alternative), when installed. git follows $EDITOR.
if (Get-Command micro -ErrorAction SilentlyContinue) { $env:EDITOR = 'micro' }

if (Get-Command zoxide -ErrorAction SilentlyContinue) {
    Invoke-Expression (& { (zoxide init powershell | Out-String) })
}

if (Get-Command eza -ErrorAction SilentlyContinue) {
    # Bold blue directories everywhere (matches WezTerm ANSI blue in both themes).
    $env:EZA_COLORS = 'di=1;34:da=1;34:ln=1;36'
    # Built-in `ls` is an alias to Get-ChildItem; remove before redefining as a function.
    Remove-Item Alias:ls -Force -ErrorAction SilentlyContinue
    function ls { eza --icons=always --git --group-directories-first @args }
    function ll { eza -l --icons=always --git --group-directories-first @args }
    function la { eza -la --icons=always --git --group-directories-first @args }
    function lt { eza --tree --icons=always --git --group-directories-first @args }
}

# lsr — "list by recent": top-level directories ranked by the newest LastWriteTime
# among their immediate children (one level deep, no recursion). A directory's own
# timestamp only moves when entries are added or removed, so `ls -lt`/eza bury a
# project whose files you edited all day. Mirrors the zsh lsr.
# Emits objects rather than Format-Table output, so `lsr | Where-Object ...` works.
function lsr {
    param([string]$Path = '.', [switch]$All)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Write-Warning "lsr: not a directory: $Path"
        return
    }
    # -Force on the CHILDREN always (hidden files still count as activity); on the
    # top-level listing only with -All. Note "hidden" is the hidden ATTRIBUTE here,
    # where the zsh version keys off a leading dot.
    Get-ChildItem -LiteralPath $Path -Directory -Force:$All -ErrorAction SilentlyContinue |
        ForEach-Object {
            $newest = Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue |
                      Sort-Object LastWriteTime -Descending |
                      Select-Object -First 1
            [pscustomobject]@{
                Name   = $_.Name
                Latest = if ($newest) { $newest.LastWriteTime } else { $null }
                Item   = if ($newest) { $newest.Name } else { '(empty)' }
            }
        } |
        # Explicit MinValue key so empty dirs pin to the bottom instead of relying
        # on however Sort-Object happens to order $null.
        Sort-Object -Property @{
            Expression = { if ($_.Latest) { $_.Latest } else { [datetime]::MinValue } }
        } -Descending
}

# lsrr — lsr, capped at the 20 most recent. Same parameters as lsr, and still
# emits objects, so it composes the same way.
function lsrr { lsr @args | Select-Object -First 20 }

# ref — alias into the `doc` knowledge base (replaced the old command-reference file).
function ref { doc @args }

# rmf <path...> — delete file(s)/folder(s) recursively with no confirmation prompts.
function rmf {
    param([Parameter(Mandatory, ValueFromRemainingArguments = $true)][string[]]$Paths)
    Remove-Item -Path $Paths -Recurse -Force -Confirm:$false
}
# ---- cli-tools-end ----

# ---- git-shortcuts-start ----
# Git muscle-memory, matching the zsh side (oh-my-zsh git plugin + stack
# overrides). gp always means PULL and gl always means LOG on this stack.
function gst { git status @args }
function gp  { git pull @args }
function gco { git checkout @args }
function gf  { git fetch @args }
function gl  { git log --oneline --graph --decorate -10 @args }
function gd  { git diff @args }
function ga  { git add @args }
function gb  { git branch @args }
# ---- git-shortcuts-end ----

# ---- terminal-stack-update-start ----
# Resolution order: -SourceDir → $env:TERMINAL_STACK_DIR → canonical location →
# legacy candidates in list order. We deliberately do NOT consult
# `chezmoi source-path` here: on Windows that returns chezmoi's default
# sourceDir (~/.local/share/chezmoi) regardless of where the actual clone
# lives, because Windows users don't configure chezmoi.toml (the WSL side does).

# The canonical runtime clone location — inside the app-data dir the stack
# already owns (config.json, rollback-sha, docs mirror). Pins are only for
# NON-canonical locations. Twin copies: bootstrap/_cleanup.ps1 (parse-time
# isolation), bootstrap/_config.sh ts_canonical_clone_dir (bash).
function Get-TsCanonicalCloneDir { Join-Path $env:LOCALAPPDATA 'terminal-stack\stack' }

# True when a path is a DEV clone at a wso workspace tier path
# (<tier>/<host-with-dot>/<owner>/<repo>). Dev clones are invisible to
# auto-resolution unless pinned. Twin of bootstrap/_cleanup.sh ts_is_dev_clone.
function Test-TsDevClone([string]$Path) {
    ($Path -replace '\\', '/') -match '/(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$'
}

# CANONICAL CLONE CANDIDATE LIST (pwsh replica) — pin, then canonical, then
# legacy defaults. Keep in sync with docs/decisions.md § "Runtime clone location"
# and the siblings: bootstrap/_cleanup.sh ts_clone_candidates (master),
# dot_zshrc _ts_clone_candidates, bootstrap/_cleanup.ps1 Get-TsCleanupCloneCandidates.
function Get-TsCloneCandidates {
    $seen = @{}
    @(
        $env:TERMINAL_STACK_DIR,
        (Get-TsCanonicalCloneDir),
        (Join-Path $env:USERPROFILE 'code\terminal-stack'),
        (Join-Path $env:USERPROFILE 'terminal-stack'),
        (Join-Path $env:USERPROFILE 'Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE '.local\share\chezmoi'),
        'C:\DATA\Workspace\terminal-stack'
    ) | Where-Object {
        if (-not $_) { return $false }
        $k = $_.ToLower(); if ($seen[$k]) { $false } else { $seen[$k] = $true; $true }
    }
}

# A path is a terminal-stack clone when it is a git repo whose origin names the
# project. The name test is necessary but NOT sufficient to pick one: a stale
# install under ~\terminal-stack from an old account still matches, which is
# exactly how a machine ends up re-syncing an ancient profile over a current one.
# Dev clones (workspace tier paths) are skipped unless they ARE the pin.
function Get-TsClones {
    $out = foreach ($d in (Get-TsCloneCandidates)) {
        if (-not (Test-Path (Join-Path $d '.git'))) { continue }
        if ((Test-TsDevClone $d) -and $d -ne $env:TERMINAL_STACK_DIR) { continue }
        $origin = & git -C $d config --get remote.origin.url 2>$null
        if ($origin -notmatch 'terminal-stack') { continue }
        $ct = & git -C $d log -1 --format=%ct 2>$null
        [pscustomobject]@{
            Path   = $d
            Origin = ([string]$origin).Trim()
            Commit = if ($ct) { [int64]$ct } else { 0 }
            Short  = (& git -C $d log -1 --format='%h %s' 2>$null)
        }
    }
    # Candidate order IS the priority: pin > canonical > legacy. (Ranking by
    # newest commit was removed — it would prefer a dev clone the moment you
    # commit to it, updating the tree you're developing in.)
    return @($out)
}

# Resolve the clone to operate on. An explicit -SourceDir or $env:TERMINAL_STACK_DIR
# always wins. Otherwise take the highest-priority real clone and, when more than
# one exists, say so — silently choosing between two clones is how the wrong
# profile gets deployed.
#
# The two pin sources are NOT equivalent when the pin is dangling. -SourceDir is
# typed per call, so a bad one is a mistake worth failing on. $env:TERMINAL_STACK_DIR
# arrives from profile.local.ps1 in every session, so a stale line there would
# otherwise brick ts-update / wso / doc machine-wide with no way out — it degrades
# to the normal candidate search instead.
function Resolve-TsSourceDir([string]$SourceDir) {
    if ($SourceDir) {
        if (-not (Test-Path (Join-Path $SourceDir '.git'))) {
            Write-Warning "terminal-stack clone not found at $SourceDir. Pass -SourceDir <path> or re-run install.ps1."
            return $null
        }
        return $SourceDir
    }
    if ($env:TERMINAL_STACK_DIR) {
        if (Test-Path (Join-Path $env:TERMINAL_STACK_DIR '.git')) {
            return $env:TERMINAL_STACK_DIR
        }
        Write-Warning "stale `$env:TERMINAL_STACK_DIR pin: no clone at $($env:TERMINAL_STACK_DIR) — searching the usual locations."
        Write-Host   "  Clear it with 'ts-doctor -Repair', or delete the line from $(Join-Path (Split-Path $PROFILE) 'profile.local.ps1')."
        $stalePin = $true
    }
    $clones = Get-TsClones
    if (-not $clones.Count) {
        Write-Warning 'No terminal-stack clone found. Pass -SourceDir <path> or re-run install.ps1.'
        return $null
    }
    if ($stalePin) { Write-Host "  using $($clones[0].Path)" }
    if ($clones.Count -gt 1) {
        Write-Warning "$($clones.Count) terminal-stack clones found; using the highest-priority location:"
        foreach ($c in $clones) {
            $mark = if ($c.Path -eq $clones[0].Path) { '->' } else { '  ' }
            Write-Host ("  {0} {1}" -f $mark, $c.Path)
            Write-Host ("       {0}  |  {1}" -f $c.Origin, $c.Short)
        }
        Write-Host "  Consolidate with 'ts-doctor -Repair' (or pin one: Set-TsSourceDirPersisted '<path>')"
    }
    return $clones[0].Path
}

function Invoke-TsSync([string]$SourceDir) {
    $sync = Join-Path $SourceDir 'scripts\sync-windows.ps1'
    if (Test-Path $sync) {
        & $sync -SourceDir $SourceDir
    } else {
        Write-Warning "$sync not found; Windows-side dotfiles not applied."
    }
}

function Get-TsStateFile {
    Join-Path $env:LOCALAPPDATA 'terminal-stack\rollback-sha'
}

function Update-TerminalStack {
    [CmdletBinding()]
    param([string]$SourceDir)

    $SourceDir = Resolve-TsSourceDir $SourceDir
    if (-not $SourceDir) { return }

    # Preflight: a resolved dir that isn't a terminal-stack clone means a stale /
    # moved install. Nudge toward ts-doctor rather than pulling the wrong repo.
    $remote = & git -C $SourceDir config --get remote.origin.url 2>$null
    if ($remote -notmatch 'terminal-stack') {
        Write-Warning "ts-update: '$SourceDir' doesn't look like a terminal-stack clone. Run 'ts-doctor' to check."
    }
    Write-Host "==> clone: $SourceDir"
    # Location notice only — moving is ts-doctor's job, never a side effect of updating.
    $canon = Get-TsCanonicalCloneDir
    if ($SourceDir.TrimEnd('\') -ne $canon.TrimEnd('\') -and -not (Test-TsDevClone $SourceDir)) {
        Write-Host "ts-update: note — clone is at a legacy location; run 'ts-doctor -Repair' to move it to $canon."
    }
    # A second clone is not just untidy: whichever one ts-update picks is the one
    # that overwrites $PROFILE, so an unnoticed leftover silently reinstates an
    # old profile. Offer to pin the choice once rather than re-deciding it on
    # every run. Skipped when pinned, non-interactive, or already canonical
    # (canonical needs no pin — consolidate via ts-doctor instead).
    if (-not $env:TERMINAL_STACK_DIR -and $SourceDir.TrimEnd('\') -ne $canon.TrimEnd('\')) {
        $all = Get-TsClones
        if ($all.Count -gt 1 -and -not [Console]::IsInputRedirected) {
            $a = Read-Host "Pin '$SourceDir' as this machine's clone and stop asking? [y/N]"
            if ($a -match '^(y|Y|yes|YES)$') { Set-TsSourceDirPersisted $SourceDir }
        }
    }

    & git -C $SourceDir fetch --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warning 'git fetch failed; not applying.'; return }

    # '@{u}' must be quoted — pwsh would otherwise parse it as a hashtable.
    $incoming = & git -C $SourceDir log --oneline 'HEAD..@{u}' 2>$null
    if ($incoming) {
        Write-Host '==> incoming changes:'
        $incoming | ForEach-Object { Write-Host "  $_" }
        # Record the rollback point only when something is actually incoming —
        # a no-op re-run must not clobber the last real rollback point.
        $stateFile = Get-TsStateFile
        New-Item -ItemType Directory -Force -Path (Split-Path $stateFile) | Out-Null
        (& git -C $SourceDir rev-parse HEAD) | Set-Content $stateFile
        Write-Host "==> recorded rollback point: $(& git -C $SourceDir rev-parse --short HEAD) (ts-rollback to undo)"
        & git -C $SourceDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Warning 'git pull failed; not applying.'; return }
    } else {
        Write-Host '==> already up to date'
    }
    # Re-bake the resolved (light/dark) palette from the live OS theme so a
    # `follow`-mode user who toggled Windows appearance gets the new palette on
    # this update. No-op for fixed dark/light; non-fatal if the helper is absent.
    $cfgHelper = Join-Path $SourceDir 'bootstrap\_config.ps1'
    if (Test-Path $cfgHelper) {
        try { . $cfgHelper; Update-TsResolvedTheme } catch { Write-Warning "resolvedTheme refresh skipped: $_" }
    }
    Invoke-TsSync $SourceDir

    # Config files are only half an update: a release that adds a CLI tool is
    # inert until the tool exists. Offer the gap rather than installing behind
    # your back, and skip the question entirely when there is nothing to do or
    # nobody to ask.
    if (Test-Path $cfgHelper) {
        try {
            . $cfgHelper
            $pending = @(Get-TsAppsPending)
            if ($pending.Count) {
                Write-Host "==> $($pending.Count) app(s) from the catalog are not installed:"
                foreach ($p in $pending) { Write-Host ("    {0,-10} {1}" -f $p, (Get-TsAppDesc $p)) }
                if ([Console]::IsInputRedirected) {
                    Write-Host "    Install them with: ts-config apps"
                } else {
                    $a = Read-Host 'Install them now? [y/N]'
                    if ($a -match '^(y|Y|yes|YES)$') {
                        Install-TsApps $pending
                        # Record them, so the selection reflects what is actually here.
                        $cfg = Get-TsConfig
                        $merged = @(@($cfg.apps) + $pending | Where-Object { $_ } | Select-Object -Unique)
                        Save-TsConfig -LeaderChord $cfg.leaderChord -ThemeMode $cfg.themeMode `
                                      -TmuxPrefix $cfg.tmuxPrefix -Apps $merged | Out-Null
                    } else {
                        Write-Host '    Skipped. Run ts-config apps when you want them.'
                    }
                }
            }
        } catch { Write-Warning "app check skipped: $_" }
    }
}
Set-Alias -Name ts-update -Value Update-TerminalStack

# Undo the last ts-update: reset the clone to the recorded pre-update SHA and
# re-apply. Manual fallback (state file missing): README § Updating & rollback.
function Restore-TerminalStack {
    [CmdletBinding()]
    param([string]$SourceDir)

    $SourceDir = Resolve-TsSourceDir $SourceDir
    if (-not $SourceDir) { return }

    $stateFile = Get-TsStateFile
    if (-not (Test-Path $stateFile)) {
        Write-Warning "no recorded rollback point ($stateFile)."
        Write-Warning "Manual procedure: git -C $SourceDir reset --hard <sha>; scripts\sync-windows.ps1"
        return
    }
    $sha = (Get-Content $stateFile -First 1).Trim()
    & git -C $SourceDir rev-parse --verify --quiet "$sha^{commit}" *> $null
    if ($LASTEXITCODE -ne 0) { Write-Warning "recorded SHA $sha not found in $SourceDir."; return }

    # The clone may double as a dev checkout — never reset --hard over real work.
    if (& git -C $SourceDir status --porcelain) {
        Write-Warning "$SourceDir has uncommitted changes; refusing to reset --hard. Commit or stash first."
        return
    }
    Write-Host "==> resetting $SourceDir to $sha (recorded before last ts-update)"
    & git -C $SourceDir reset --hard $sha
    if ($LASTEXITCODE -ne 0) { return }
    Invoke-TsSync $SourceDir
    Write-Host '==> done. run ts-update to return to latest.'
}
Set-Alias -Name ts-rollback -Value Restore-TerminalStack

# Configure the stack: leader key, theme (dark/light/follow), tmux prefix, apps,
# and the WezTerm mux / startup-restore toggles.
# Bare `ts-config` opens an interactive menu; `ts-config theme follow` etc. set one
# value. Writes %LOCALAPPDATA%\terminal-stack\config.json and re-syncs the Windows
# files. NOTE: in a combined WSL+Windows setup, prefer running `ts-config` from WSL
# (its chezmoi apply is authoritative for the Windows-side files).
function Set-TerminalStackConfig {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)][string]$Action,
        [Parameter(Position = 1)][string]$Value,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
    )

    $src = Resolve-TsSourceDir
    if (-not $src) { return }
    $helper = Join-Path $src 'bootstrap\_config.ps1'
    if (-not (Test-Path $helper)) { Write-Warning "$helper not found; cannot configure."; return }
    . $helper

    $c = Get-TsConfig
    $leader = if ($c.leaderChord) { $c.leaderChord } else { 'ctrl-space' }
    $theme  = if ($c.themeMode)   { $c.themeMode }   else { 'dark' }
    $tmux   = if ($c.tmuxPrefix)  { $c.tmuxPrefix }  else { 'ctrl-b' }
    $apps   = @($c.apps)
    $ccTts  = if ($c.ccTts) { $c.ccTts } else { Get-CcTtsDefaults }

    $save = {
        param($Tts = $ccTts)
        Save-TsConfig -LeaderChord $leader -ThemeMode $theme -TmuxPrefix $tmux -Apps $apps -CcTts $Tts | Out-Null
        Export-CcTtsJson
        Invoke-TsSync $src
        Write-Host '==> done.'
    }

    switch ($Action) {
        '' {
            while ($true) {
                Write-Host ''
                Write-Host 'terminal-stack config:'
                Write-Host "  leader     : $leader"
                Write-Host "  theme      : $theme   (palette $(Get-TsResolvedTheme $theme))"
                Write-Host "  tmux       : $tmux"
                Write-Host "  apps       : $($apps -join ', ')"
                Write-Host "  cc-tts     : $(if ($ccTts.enabled) { 'on' } else { 'off' })"
                Write-Host "  wezmux     : $(Get-TsWeztermMux)"
                Write-Host "  wezrestore : $(Get-TsWeztermRestore)"
                Write-Host ''
                Write-Host '  1) leader  2) theme  3) tmux prefix  4) apps  5) re-apply  6) Claude TTS  7) WezTerm mux  8) session restore  q) quit'
                switch (Read-Host 'Choose') {
                    '1' { $leader = Read-TsLeader; & $save }
                    '2' { $theme  = Read-TsTheme;  & $save }
                    '3' { $t = Read-Host 'tmux prefix chord (e.g. ctrl-a) [ctrl-b]'; $tmux = if ($t) { $t } else { 'ctrl-b' }; & $save }
                    '4' { $apps = @(Read-TsApps); Install-TsApps $apps; & $save }
                    '5' { & $save }
                    '6' {
                        Show-CcTtsConfig
                        switch (Read-Host 'TTS: a) on  b) off  c) test  d) back') {
                            'a' { $ccTts.enabled = $true; & $save $ccTts }
                            'b' { $ccTts.enabled = $false; & $save $ccTts }
                            'c' { Invoke-TsConfigTts -Sub test -Apply $save }
                        }
                    }
                    '7' { Invoke-TsMux status }
                    '8' { $restore = Read-TsWeztermRestore; Save-TsConfig -WeztermRestore $restore | Out-Null; Invoke-TsSync $src; Write-Host '==> done.' }
                    default { return }
                }
            }
        }
        'show' {
            Write-Host "leader     : $leader"
            Write-Host "theme      : $theme   (palette $(Get-TsResolvedTheme $theme))"
            Write-Host "tmux       : $tmux"
            Write-Host "apps       : $($apps -join ', ')"
            Write-Host "wezmux     : $(Get-TsWeztermMux)   (ts-mux on|off|status)"
            Write-Host "wezrestore : $(Get-TsWeztermRestore)   (ts-config restore on|off)"
        }
        'leader' { if (-not $Value) { Write-Warning 'usage: ts-config leader <chord>'; return }; $leader = $Value; & $save }
        'theme'  { if (-not $Value) { Write-Warning 'usage: ts-config theme <dark|light|follow>'; return }; $theme = $Value; & $save }
        'tmux'   { if (-not $Value) { Write-Warning 'usage: ts-config tmux <chord>'; return }; $tmux = $Value; & $save }
        'apps'   {
            if ($Value) {
                switch ($Value) {
                    'recommended' { $apps = $script:TsAppsRecommended }
                    'all'         { $apps = $script:TsAppsAll }
                    'none'        { $apps = @() }
                    default       { $apps = ($Value -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
                }
            } else { $apps = @(Read-TsApps) }
            Install-TsApps $apps; & $save
        }
        'tts' {
            Invoke-TsConfigTts -Sub $Value -Arg $Rest[0] -Arg2 $Rest[1] -Apply {
                param($Tts)
                $ccTts = $Tts
                & $save $Tts
            }
        }
        # Reopening the last WezTerm session at startup. Stored on its own like the
        # mux key, so flipping it need not re-state every other choice.
        'restore' {
            if ($Value -notin 'on', 'off') { Write-Warning 'usage: ts-config restore <on|off>'; return }
            Save-TsConfig -WeztermRestore $Value | Out-Null
            Invoke-TsSync $src
            Write-Host '==> done.'
        }
        # The mux has its own verbs (kill/restart/reset), so ts-config just hands off.
        'mux'    {
            $muxArgs = @(@($Value) + @($Rest) | Where-Object { $_ })
            Invoke-TsMux @muxArgs
        }
        default { Write-Warning "ts-config: unknown command '$Action' (show, leader, theme, tmux, apps, tts, mux, restore)" }
    }
}
Set-Alias -Name ts-config -Value Set-TerminalStackConfig

# WezTerm multiplexer domain — turn it on/off and drive the live mux server.
# PARALLEL implementation of bootstrap/ts-mux.sh (not a wrapper): change one,
# change the other, and keep the -h output byte-identical. In a combined
# WSL+Windows setup prefer the WSL `ts-mux` — its chezmoi apply is authoritative
# for the Windows-side files; this one writes config.json and re-syncs.
$script:TsMuxHelp = @'
ts-mux — WezTerm multiplexer domain: keep panes alive when the GUI dies.

Usage:
  ts-mux [status]   the setting, the mux server, and the panes it hosts
  ts-mux on         host panes in the mux domain (unix domain "main")
  ts-mux off        spawn panes locally (the default)
  ts-mux list       wezterm cli list — every pane the mux knows about
  ts-mux kill       stop wezterm-mux-server       [KILLS EVERY PANE IT HOSTS]
  ts-mux restart    stop it, then start a fresh one, so it re-reads the config
  ts-mux reset      back to default: off + re-apply + kill + clear stale sockets
  ts-mux -h         this help

  -y, --yes         skip the confirmation for kill / restart / reset

With the mux on, your shells run inside wezterm-mux-server instead of the GUI, so
a GUI crash leaves every pane (and everything running in it) alive and relaunching
WezTerm reattaches. The costs are why it is off by default: the mux server loads
its OWN copy of .wezterm.lua, so a config change needs "ts-mux restart" — which
kills every pane — and not just a GUI reload; and the Claude per-pane tint needs
pane:inject_output, which mux panes do not have.

on/off re-render .wezterm.lua and take effect for newly spawned tabs; relaunch
WezTerm for a clean switch. Panes already hosted in the mux stay there until you
close them or run "ts-mux kill". The setting is saved with the rest of the config
(chezmoi [data] weztermMux / config.json weztermMux) and shown by "ts-config show".
'@

function Get-TsWezExe([string]$Name) {
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = Join-Path $env:ProgramFiles "WezTerm\$Name.exe"
    if (Test-Path -LiteralPath $p) { return $p }
    return $null
}

function Get-TsMuxProcess { @(Get-Process -Name 'wezterm-mux-server' -ErrorAction SilentlyContinue) }

# The RENDERED config the GUI actually loads — used to spot a saved setting that
# has not been synced yet.
function Get-TsRenderedMux {
    $f = Join-Path $env:USERPROFILE '.wezterm.lua'
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    $lines = Get-Content -LiteralPath $f
    foreach ($line in $lines) {
        if ($line -match "^local MUX_ENABLED = '(on|off)'") { return $Matches[1] }
    }
    # A config rendered before this toggle existed: the domain was unconditional.
    if ($lines | Where-Object { $_ -match "^config\.default_domain = 'main'" }) { return 'on (pre-toggle)' }
    return 'off (pre-toggle)'
}

function Invoke-TsMux {
    [CmdletBinding()]
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$MuxArgs)

    $yes = $false
    $cmd = ''
    foreach ($a in @($MuxArgs)) {
        # `break` on every case: switch -Regex falls through, so without it '-y'
        # would also hit the '^-' unknown-flag arm below.
        switch -Regex ($a) {
            '^(-y|--yes)$'       { $yes = $true; break }
            '^(-h|--help|help)$' { Write-Host $script:TsMuxHelp; return }
            '^-'                 { Write-Warning "ts-mux: unknown flag '$a' (try: ts-mux -h)"; return }
            default              { if ($cmd) { Write-Warning "ts-mux: unexpected argument '$a'"; return }; $cmd = $a }
        }
    }
    if (-not $cmd) { $cmd = 'status' }

    $src = Resolve-TsSourceDir
    if (-not $src) { return }
    $helper = Join-Path $src 'bootstrap\_config.ps1'
    if (-not (Test-Path $helper)) { Write-Warning "$helper not found; cannot configure."; return }
    . $helper

    $confirm = {
        param($Prompt)
        if ($yes) { return $true }
        if ([Console]::IsInputRedirected) {
            Write-Warning 'ts-mux: no terminal to confirm on — re-run with -y if you mean it.'
            return $false
        }
        $a = Read-Host "$Prompt [y/N]"
        if ($a -match '^(y|yes)$') { return $true }
        Write-Host 'aborted.'
        return $false
    }

    $stop = {
        $procs = Get-TsMuxProcess
        if (-not $procs.Count) { Write-Host '==> wezterm-mux-server is not running.'; return $true }
        $pidList = ($procs | ForEach-Object { $_.Id }) -join ' '
        if (-not (& $confirm "Stop wezterm-mux-server (pid $pidList)? Every pane it hosts dies — including this one, if you are in one")) { return $false }
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        if ((Get-TsMuxProcess).Count) {
            Write-Warning 'wezterm-mux-server is still running — kill it by hand.'
            return $false
        }
        Write-Host '==> wezterm-mux-server stopped.'
        return $true
    }

    $start = {
        if ((Get-TsMuxProcess).Count) { Write-Host '==> wezterm-mux-server is already running.'; return }
        $bin = Get-TsWezExe 'wezterm-mux-server'
        if (-not $bin) {
            Write-Warning 'ts-mux: wezterm-mux-server not found — relaunch WezTerm and it will spawn one.'
            return
        }
        Write-Host '==> starting wezterm-mux-server --daemonize'
        Start-Process -FilePath $bin -ArgumentList '--daemonize' -WindowStyle Hidden
    }

    $setMux = {
        param($Want)
        $c = Get-TsConfig
        if ((Get-TsWeztermMux) -eq $Want) {
            Write-Host "==> mux already $Want; re-syncing anyway to refresh the rendered config."
        }
        Save-TsConfig -LeaderChord $c.leaderChord -ThemeMode $c.themeMode -TmuxPrefix $c.tmuxPrefix `
                      -Apps @($c.apps) -WeztermMux $Want -CcTts $c.ccTts | Out-Null
        Invoke-TsSync $src
        Write-Host '==> done.'
        if ($Want -eq 'on') {
            Write-Host "    Panes now spawn into the mux domain 'main'. Relaunch WezTerm for a"
            Write-Host "    clean switch; 'ts-mux status' shows the server once it starts."
        } else {
            Write-Host '    New tabs spawn locally again. Panes already hosted by the mux stay'
            Write-Host "    there until you close them or run 'ts-mux kill'."
        }
    }

    switch ($cmd) {
        'status' {
            $setting = Get-TsWeztermMux
            $rendered = Get-TsRenderedMux
            $procs = Get-TsMuxProcess
            Write-Host 'ts-mux:'
            Write-Host "  setting  : $setting   (saved as weztermMux)"
            if (-not $rendered) {
                Write-Host '  rendered : (no .wezterm.lua found — run sync-windows.ps1)'
            } elseif ($rendered -ne $setting) {
                Write-Host "  rendered : $rendered   !! stale — run 'ts-update' or sync-windows.ps1"
            } else {
                Write-Host "  rendered : $rendered   ($(Join-Path $env:USERPROFILE '.wezterm.lua'))"
            }
            if ($procs.Count) {
                Write-Host "  server   : running (pid $(($procs | ForEach-Object { $_.Id }) -join ' '))"
            } else {
                Write-Host '  server   : not running'
            }
            $cli = Get-TsWezExe 'wezterm'
            if ($cli) {
                $rows = @(& $cli cli list 2>$null | Select-Object -Skip 1 | Where-Object { $_.Trim() })
                Write-Host "  panes    : $($rows.Count)   ('ts-mux list' for detail)"
            }
            if ($setting -eq 'off' -and $procs.Count) {
                Write-Host '  note     : panes spawned while the mux was on are still hosted by it;'
                Write-Host "             they stay alive until you close them or run 'ts-mux kill'."
            }
        }
        'on'  { & $setMux 'on' }
        'off' { & $setMux 'off' }
        'list' {
            $cli = Get-TsWezExe 'wezterm'
            if (-not $cli) { Write-Warning 'ts-mux: wezterm CLI not found on PATH.'; return }
            & $cli cli list
        }
        'kill'    { & $stop | Out-Null }
        'restart' { if (& $stop) { & $start } }
        'reset' {
            if (-not (& $confirm 'Reset the WezTerm mux: set it off, re-sync, stop the server (every pane it hosts dies) and clear stale sockets')) { return }
            $yes = $true
            & $setMux 'off'
            & $stop | Out-Null
            $n = 0
            $dir = Join-Path $env:LOCALAPPDATA 'wezterm'
            if (Test-Path -LiteralPath $dir) {
                foreach ($f in @('sock', 'gui-sock-*')) {
                    Get-ChildItem -LiteralPath $dir -Filter $f -ErrorAction SilentlyContinue | ForEach-Object {
                        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
                        $n++
                    }
                }
            }
            Write-Host "==> cleared $n stale socket file(s)"
            Write-Host '==> mux reset to the default (off).'
        }
        default { Write-Warning "ts-mux: unknown command '$cmd' (status, on, off, list, kill, restart, reset)" }
    }
}
Set-Alias -Name ts-mux -Value Invoke-TsMux

# Probe known clone locations for one that actually contains the repo — used so
# the doctor still runs when $env:TERMINAL_STACK_DIR / the default path is wrong.
# Same priority as Get-TsCloneCandidates; dev clones skipped unless pinned.
function Find-TsAnyClone {
    foreach ($d in (Get-TsCloneCandidates)) {
        if (-not $d) { continue }
        if ((Test-TsDevClone $d) -and $d -ne $env:TERMINAL_STACK_DIR) { continue }
        if (Test-Path (Join-Path $d 'bootstrap\_cleanup.ps1')) { return $d }
    }
    return $null
}

# Persist $env:TERMINAL_STACK_DIR to profile.local.ps1 so ts-update / ts-config
# find a clone that isn't at the default %USERPROFILE%\terminal-stack.
function Set-TsSourceDirPersisted([string]$SourceDir) {
    $localProfile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    New-Item -ItemType Directory -Force -Path (Split-Path $localProfile) | Out-Null
    $line = "`$env:TERMINAL_STACK_DIR = '$SourceDir'"
    if ((Test-Path $localProfile) -and (Get-Content $localProfile | Where-Object { $_ -match '^\s*\$env:TERMINAL_STACK_DIR\s*=' })) {
        (Get-Content $localProfile) -replace '^\s*\$env:TERMINAL_STACK_DIR\s*=.*', $line | Set-Content $localProfile
    } else {
        Add-Content -Path $localProfile -Value $line
    }
    $env:TERMINAL_STACK_DIR = $SourceDir
    Write-Host "==> persisted `$env:TERMINAL_STACK_DIR = $SourceDir to $localProfile"
}

# Diagnose / repair the Windows install: missing/moved clone, stale config, leftover
# old clones. `ts-doctor` checks (read-only); `ts-doctor -Repair` fixes (move the
# clone to the canonical location, re-sync, offer cleanup). POSIX counterpart:
# bootstrap/ts-doctor.sh.
function Invoke-TsDoctor {
    [CmdletBinding()] param([switch]$Repair, [switch]$Quiet)
    $clone = Find-TsAnyClone
    if (-not $clone) { Write-Warning 'No terminal-stack clone found. Re-run install.ps1 (irm ... | iex).'; return }
    . (Join-Path $clone 'bootstrap\_cleanup.ps1')
    $src = Resolve-TsSourceDir
    if (-not $src) { $src = $clone }
    $canon = Get-TsCanonicalCloneDir
    if ($Repair) {
        # Offer the canonical-location move first (Move-TsClone clears a stale pin).
        if ($src.TrimEnd('\') -ne $canon.TrimEnd('\') -and -not (Test-TsDevClone $src) `
            -and (Get-Command Move-TsClone -ErrorAction SilentlyContinue)) {
            if (Test-Path $canon) {
                # Move-TsClone refuses an existing destination, and the cleanup
                # menu never offers the canonical path — so "resolve it there"
                # used to be a dead end. Decide it here instead.
                if (Test-TsStackClone $canon) {
                    Write-Warning "two clones: '$src' and the canonical '$canon'."
                    Write-Host   "  switching to $canon; the cleanup menu below can remove '$src'."
                    $src = $canon
                } else {
                    Write-Warning "'$canon' exists but is not a terminal-stack clone."
                    Write-Host   "  Move it aside or delete it, then re-run 'ts-doctor -Repair' to relocate '$src'."
                }
            } elseif (-not [Console]::IsInputRedirected) {
                $a = Read-Host "Move '$src' to the canonical location '$canon'? [Y/n]"
                if ($a -notmatch '^(n|no)$') {
                    if (Move-TsClone -Source $src -Dest $canon) { $src = $canon }
                }
            }
        }
        # Fallback pin only when the clone stays at a non-canonical path.
        if ($src.TrimEnd('\') -ne $canon.TrimEnd('\') -and `
            (Resolve-Path $clone -ErrorAction SilentlyContinue).Path -ne (Resolve-Path $src -ErrorAction SilentlyContinue).Path) {
            Set-TsSourceDirPersisted $src
        }
        Invoke-TsSync $src
        Invoke-TsCleanupMenu $src
        Test-TsInstall -SourceDir $src | Out-Null
    } else {
        if ($src.TrimEnd('\') -ne $canon.TrimEnd('\') -and -not (Test-TsDevClone $src)) {
            Write-Host "note: clone is at a legacy location; 'ts-doctor -Repair' can move it to $canon"
        } elseif (Test-TsDevClone $src) {
            Write-Host 'note: pinned at a dev clone (workspace tier path) — deliberate, leaving it alone.'
        }
        Test-TsInstall -SourceDir $src -Quiet:$Quiet | Out-Null
    }
}
function Test-TerminalStack    { [CmdletBinding()] param([switch]$Quiet) Invoke-TsDoctor -Quiet:$Quiet }
function Repair-TerminalStack  { Invoke-TsDoctor -Repair }
Set-Alias -Name ts-doctor -Value Invoke-TsDoctor
# ---- terminal-stack-update-end ----

# ---- claude-code-start ----
function ccnotify {
    param([string]$Action)
    $f = "$HOME\.claude\.toast-notify"
    switch ($Action) {
        'on'  { New-Item $f -ItemType File -Force | Out-Null; Write-Host 'CC toast: ON' }
        'off' { Remove-Item $f -ErrorAction SilentlyContinue; Write-Host 'CC toast: OFF' }
        default {
            if (Test-Path $f) { Write-Host 'CC toast: ON  (ccnotify off to disable)' }
            else              { Write-Host 'CC toast: OFF (ccnotify on  to enable)'  }
        }
    }
}

function cctts {
    param([string]$Action, [string]$Extra)
    switch ($Action) {
        'on'   { ts-config tts on }
        'off'  { ts-config tts off }
        'test' { ts-config tts test }
        'show' { ts-config tts show }
        default {
            $en = $false
            $cfgPath = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
            if (Test-Path $cfgPath) {
                try { $en = [bool](Get-Content $cfgPath -Raw | ConvertFrom-Json).ccTts.enabled } catch {}
            }
            if ($en) { Write-Host 'CC TTS: ON  (cctts off to disable; ts-config tts for settings)' }
            else     { Write-Host 'CC TTS: OFF (cctts on to enable)' }
        }
    }
}
# ---- claude-code-end ----

# ---- wzr-start ----
# wzr — WezTerm key reference. Now a thin alias into `doc` (docs/kb/wezterm/*).
# `wzr` browses the WezTerm topics; `wzr panes` opens that one.
function wzr { param([string]$Topic) if ($Topic) { doc "wezterm/$Topic" } else { doc wezterm } }
# ---- wzr-end ----

# ---- editor-launch-start ----
# npp [files...] — open file(s) in Notepad++ (like `ws`, but launches an editor).
# Resolve the exe lazily and invoke with the call operator `&` (the install path
# has spaces, so it must be invoked, not run as a bare command). GUI app, so `&`
# returns to the prompt immediately rather than blocking.
function npp {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
    $exe = (Get-Command notepad++ -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        foreach ($c in @("$env:ProgramFiles\Notepad++\notepad++.exe",
                         "${env:ProgramFiles(x86)}\Notepad++\notepad++.exe")) {
            if (Test-Path $c) { $exe = $c; break }
        }
    }
    if (-not $exe) {
        Write-Warning 'npp: Notepad++ not found — install it or add notepad++.exe to PATH'
        return
    }
    if (-not $Paths) { & $exe; return }
    # Resolve each arg against the current dir so relative paths open correctly;
    # a not-yet-existing path is passed through (Notepad++ opens a new buffer).
    # @(...) forces an array even for one path — foreach with a single output
    # collapses $resolved to a bare string, and `& $exe @resolved` on a string
    # splats its individual CHARACTERS as separate arguments (PowerShell splat
    # gotcha), which silently truncated every single-file open to its first
    # character before this was caught.
    $resolved = @(foreach ($p in $Paths) {
        $full = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
        if     ($full)                                 { $full.Path }
        elseif ([System.IO.Path]::IsPathRooted($p))    { $p }
        else                                           { Join-Path (Get-Location).Path $p }
    })
    & $exe @resolved
}

# pm [files...] — open file(s) in PrettyMark (like `npp`, but for PrettyMark's md viewer).
function pm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
    $exe = (Get-Command prettymark -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        $c = "$env:ProgramFiles\PrettyMark\PrettyMark.exe"
        if (Test-Path $c) { $exe = $c }
    }
    if (-not $exe) {
        Write-Warning 'pm: PrettyMark not found — install it or add PrettyMark.exe to PATH'
        return
    }
    if (-not $Paths) { & $exe; return }
    # @(...) forces an array even for one path — see the comment on npp above.
    $resolved = @(foreach ($p in $Paths) {
        $full = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
        if     ($full)                               { $full.Path }
        elseif ([System.IO.Path]::IsPathRooted($p))  { $p }
        else                                          { Join-Path (Get-Location).Path $p }
    })
    & $exe @resolved
}

# pm's Paths only makes sense as markdown files — restrict Tab-completion to
# .md files (and directories, so subfolders stay navigable). No key-rebinding
# needed: Tab already cycles whatever a completer returns, so `pm ` + Tab
# cycling every .md file and `pm ins` + Tab narrowing to INSTALL.md are the
# same completer, just with an empty vs. partial $wordToComplete.
Register-ArgumentCompleter -CommandName pm -ParameterName Paths -ScriptBlock {
    param($commandName, $parameterName, $wordToComplete, $commandAst, $fakeBoundParameters)
    # A trailing separator means "list this directory's contents" — Split-Path
    # would otherwise treat the directory name itself as the leaf-in-progress
    # and match the directory, not descend into it.
    if ($wordToComplete -and $wordToComplete[-1] -in '\', '/') {
        $dir = $wordToComplete; $leaf = ''
    } elseif ($wordToComplete) {
        $dir = Split-Path $wordToComplete -Parent
        $leaf = Split-Path $wordToComplete -Leaf
    } else {
        $dir = ''; $leaf = ''
    }
    $searchDir = if ($dir) { $dir } else { '.' }
    Get-ChildItem -LiteralPath $searchDir -ErrorAction SilentlyContinue |
        Where-Object { $_.PSIsContainer -or $_.Extension -eq '.md' } |
        Where-Object { $_.Name -like "$leaf*" } |
        Sort-Object { -not $_.PSIsContainer }, Name |
        ForEach-Object {
            $rel = if ($dir) { Join-Path $dir $_.Name } else { $_.Name }
            if ($_.PSIsContainer) { $rel += '\' }
            $text = if ($rel -match "[\s']") { "'$($rel -replace "'", "''")'" } else { $rel }
            [System.Management.Automation.CompletionResult]::new($text, $_.Name, 'ParameterValue', $rel)
        }
}

# c [folder] — open folder in Cursor with the classic UI (like `npp`, but for Cursor).
function c {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
    $exe = (Get-Command cursor -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        Write-Warning 'c: cursor CLI not found on PATH — install Cursor and enable its shell command'
        return
    }
    if (-not $Paths) { $Paths = @('.') }
    & $exe @Paths --classic
}
# ---- editor-launch-end ----

# ---- doc-start ----
# `doc` — personal markdown knowledge base. Topics live in <clone>/docs/kb
# (tracked) + ~/.doc.local (untracked personal layer); rendered by glow, bat
# fallback. On Windows, sync-windows.ps1 also mirrors docs/kb to
# %LOCALAPPDATA%\terminal-stack\docs\kb (read fallback; edit/sync use the clone).
# See docs/kb/_index.md. (`ref`/`wzr` are separate for now.)
function Get-DocRoot {
    # Overrides, then the clone candidates (canonical first, dev clones skipped
    # unless pinned), then the read-only %LOCALAPPDATA% mirror LAST — note the
    # mirror (…\terminal-stack\docs\kb) is distinct from the canonical clone's kb
    # (…\terminal-stack\stack\docs\kb).
    $cands = @()
    if ($env:DOC_ROOT) { $cands += $env:DOC_ROOT }
    foreach ($d in (Get-TsCloneCandidates)) {
        if ((Test-TsDevClone $d) -and $d -ne $env:TERMINAL_STACK_DIR) { continue }
        $cands += (Join-Path $d 'docs\kb')
    }
    if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA 'terminal-stack\docs\kb') }
    foreach ($c in $cands) { if ($c -and (Test-Path -LiteralPath $c -PathType Container)) { return (Resolve-Path -LiteralPath $c).Path } }
    return $null
}
function Get-DocRepo {
    $src = Resolve-TsSourceDir
    if (-not $src) { return $null }
    $kb = Join-Path $src 'docs\kb'
    if (Test-Path -LiteralPath $kb -PathType Container) { return (Resolve-Path -LiteralPath $src).Path }
    return $null
}
function Get-DocLocal { if ($env:DOC_LOCAL) { $env:DOC_LOCAL } else { Join-Path $env:USERPROFILE '.doc.local' } }

# Rendering style: the repo ships glamour style JSONs in docs/kb/_style (they
# ride the same mirror sync as the topics), so glow renders identically on
# every platform/build. Theme follows the saved resolvedTheme; override with
# $env:DOC_STYLE (dark | light | path\to\style.json).
function Get-DocStyle {
    $theme = $env:DOC_STYLE
    if ($theme -and (Test-Path -LiteralPath $theme)) { return $theme }
    if ($theme -notin @('dark', 'light')) {
        $theme = 'dark'
        $cfg = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
        if (Test-Path -LiteralPath $cfg) {
            try {
                $j = Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json
                if ($j.resolvedTheme -in @('dark', 'light')) { $theme = $j.resolvedTheme }
            } catch {}
        }
    }
    $root = Get-DocRoot
    if ($root) {
        $f = Join-Path $root "_style\$theme.json"
        if (Test-Path -LiteralPath $f) { return $f }
    }
    return $theme
}
# Reading width: terminal width minus a hair, capped for readability.
function Get-DocWidth {
    $w = 100
    try { $w = $Host.UI.RawUI.WindowSize.Width } catch {}
    if (-not $w -or $w -lt 1) { $w = 100 }
    $w -= 2
    if ($w -gt 100) { $w = 100 }
    if ($w -lt 40)  { $w = 40 }
    return $w
}

function Get-DocIndex([string]$Os = 'windows') {
    $roots = [ordered]@{}
    $r = Get-DocRoot; if ($r) { $roots[$r] = '' }
    $l = Get-DocLocal; if (Test-Path -LiteralPath $l) { $roots[(Resolve-Path -LiteralPath $l).Path] = ' [local]' }
    $subs = if ($Os -eq 'all') { $null } else { @('common', 'wezterm', $Os) }
    foreach ($root in $roots.Keys) {
        $tag = $roots[$root]
        $files = if ($subs) {
            @(foreach ($s in $subs) { $d = Join-Path $root $s; if (Test-Path -LiteralPath $d) { Get-ChildItem -LiteralPath $d -Recurse -File -Filter *.md } }) +
            @(Get-ChildItem -LiteralPath $root -File -Filter *.md)
        } else { Get-ChildItem -LiteralPath $root -Recurse -File -Filter *.md }
        foreach ($f in $files) {
            $rel = ($f.FullName.Substring($root.Length).TrimStart('\', '/') -replace '\.md$', '') -replace '\\', '/'
            [pscustomobject]@{ Label = "$rel$tag"; Path = $f.FullName }
        }
    }
}

function Invoke-DocView([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { Write-Warning "doc: not found: $path"; return }
    # Render at an explicit width + shipped style, page with less when available
    # (Git for Windows ships less; search with /, q quits, short topics print
    # straight through thanks to -F).
    $glow = Get-Command glow -EA SilentlyContinue
    $less = Get-Command less -EA SilentlyContinue
    if ($glow -and $less) { & glow -s (Get-DocStyle) -w (Get-DocWidth) $path | & $less -RF }
    elseif ($glow)        { & glow -p $path }
    elseif (Get-Command bat -EA SilentlyContinue) { & bat --language=markdown --paging=always $path }
    else {
        try { Get-Content -LiteralPath $path | Out-Host -Paging }
        catch { Get-Content -LiteralPath $path }
    }
}

function Invoke-DocOpen([string]$query, [string]$os) {
    $m = @(Get-DocIndex 'all' | Where-Object { $_.Label -like "*$query*" })
    if ($m.Count -eq 0) {
        if (Get-Command fzf -EA SilentlyContinue) { Invoke-DocFinder $os $query }   # no exact hit -> fuzzy finder
        else { Write-Warning "doc: no topic matching '$query' (try: doc ls)" }
        return
    }
    # If every match is the same topic (tracked + its [local] twin), open the [local] one.
    $bases = $m | Group-Object { $_.Label -replace ' \[local\]$', '' }
    if ($bases.Count -eq 1) {
        $pick = ($m | Where-Object { $_.Label -match '\[local\]$' } | Select-Object -First 1)
        if (-not $pick) { $pick = $m[0] }
        Invoke-DocView $pick.Path; return
    }
    if (Get-Command fzf -EA SilentlyContinue) { Invoke-DocFinder $os $query }
    else { Write-Host "Multiple matches for '$query':"; $m | ForEach-Object { "  $($_.Label)" } }
}

function Invoke-DocFinder([string]$os, [string]$query) {
    if (-not (Get-Command fzf -EA SilentlyContinue)) { Write-Warning 'doc: fzf not installed'; return }
    $idx = Get-DocIndex $os | Sort-Object Label
    if (-not $idx) { Write-Warning 'doc: no topics found'; return }
    # Preview runs through cmd.exe on Windows, so the width var is %…% syntax;
    # fzf exports FZF_PREVIEW_COLUMNS to the preview process.
    $prev = if (Get-Command glow -EA SilentlyContinue) {
        "glow -s `"$(Get-DocStyle)`" -w %FZF_PREVIEW_COLUMNS% {2}"
    } else { 'bat --color=always --style=plain {2}' }
    $ed = if ($env:EDITOR) { $env:EDITOR } elseif (Get-Command micro -EA SilentlyContinue) { 'micro' } else { 'notepad' }
    $sel = ($idx | ForEach-Object { "$($_.Label)`t$($_.Path)" }) |
        fzf --delimiter="`t" --with-nth=1 --query=$query --border --prompt='doc> ' `
            --preview=$prev --preview-window='right,60%,wrap,border-left' `
            --bind='ctrl-u:preview-half-page-up,ctrl-d:preview-half-page-down,ctrl-/:toggle-preview' `
            --bind="alt-e:execute($ed {2})" `
            --header='enter=open · ctrl-u/d=scroll preview · ctrl-/=toggle · alt-e=edit'
    if ($sel) { Invoke-DocView (($sel -split "`t")[-1]) }
}

# Find an individual command across all docs and drop it on the prompt to run.
function Invoke-DocCmd([string]$query) {
    if (-not (Get-Command fzf -EA SilentlyContinue)) { Write-Warning 'doc: fzf not installed'; return }
    $rows = foreach ($f in (Get-DocIndex 'all')) {
        $n = 0; $infence = $false
        foreach ($line in (Get-Content -LiteralPath $f.Path)) {
            $n++
            if ($line -match '^\s*```') { $infence = -not $infence; continue }
            if ($infence) { $t = $line.Trim(); if ($t -and $t -notmatch '^#') { "$t`t$($f.Path)`t$n" } }
        }
    }
    if (-not $rows) { Write-Warning 'doc: no commands found'; return }
    $cprev = if (Get-Command bat -EA SilentlyContinue) {
        'bat --color=always --highlight-line {3} {2}'
    } else { 'type {2}' }   # cmd builtin — no highlight, but never breaks without bat
    $sel = $rows | fzf --delimiter="`t" --with-nth=1 --query=$query --border --prompt='cmd> ' `
        --preview=$cprev --preview-window='right,60%,wrap,border-left' `
        --bind='ctrl-u:preview-half-page-up,ctrl-d:preview-half-page-down,ctrl-/:toggle-preview' `
        --header='enter = put command on your prompt · ctrl-u/d=scroll preview'
    if ($sel) { [Microsoft.PowerShell.PSConsoleReadLine]::Insert((($sel -split "`t")[0])) }
}

function Invoke-DocGrep([string]$pat) {
    if (-not $pat) { Write-Host 'usage: doc -g <pattern>'; return }
    $files = @((Get-DocIndex 'all').Path)
    if (-not $files) { Write-Warning 'doc: no docs'; return }
    $out = if (Get-Command rg -EA SilentlyContinue) { & rg --line-number --heading --color=always $pat @files }
           else { Select-String -Path $files -Pattern $pat | ForEach-Object { "$($_.Filename):$($_.LineNumber): $($_.Line.Trim())" } }
    if (-not $out) { return }
    # Page long results (less ships with Git for Windows); plain output otherwise.
    $less = Get-Command less -EA SilentlyContinue
    if ($less) { $out | & $less -RF } else { $out }
}

function Invoke-DocEdit([string]$mode, [string]$arg, [string]$os) {
    $editor = if ($env:EDITOR) { $env:EDITOR } elseif (Get-Command micro -EA SilentlyContinue) { 'micro' } else { 'notepad' }
    # Edits belong in the clone (or ~/.doc.local) — never the %LOCALAPPDATA%
    # mirror, which the next sync overwrites.
    $repo = Get-DocRepo
    $root = if ($repo) { Join-Path $repo 'docs\kb' } else { Get-DocRoot }
    $mirror = Join-Path $env:LOCALAPPDATA 'terminal-stack\docs\kb'
    if ($mode -eq 'new') {
        if (-not $arg) { Write-Host 'usage: doc new <os>/<name>   e.g. doc new linux/foo'; return }
        if ($root -like "$mirror*") {
            Write-Warning 'doc new: only the read-only mirror is available — clone terminal-stack (or set $env:TERMINAL_STACK_DIR) first.'
            return
        }
        $p = Join-Path $root ($arg -replace '/', '\')
        if (-not $p.EndsWith('.md')) { $p += '.md' }
        New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
        if (-not (Test-Path -LiteralPath $p)) { "# $((Split-Path $p -Leaf) -replace '\.md$','')`n" | Set-Content -LiteralPath $p -Encoding utf8 }
        & $editor $p
    } else {
        $m = @(Get-DocIndex 'all' | Where-Object { $_.Label -like "*$arg*" })
        if ($m.Count -lt 1) { Write-Warning "doc edit: no topic matching '$arg'"; return }
        $target = $m[0].Path
        if ($target -like "$mirror*") {
            $rel = $target.Substring($mirror.Length).TrimStart('\')
            $cand = if ($repo) { Join-Path $repo "docs\kb\$rel" } else { $null }
            if ($cand -and (Test-Path -LiteralPath $cand)) { $target = $cand }
            else { Write-Warning "doc edit: '$arg' resolves to the read-only mirror — clone terminal-stack to edit it."; return }
        }
        & $editor $target
    }
}

function Update-DocChangelog([string]$repo, [string[]]$topics) {
    $cl = Join-Path $repo 'CHANGELOG.md'
    if (-not (Test-Path -LiteralPath $cl)) { return }
    $lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $cl)
    $bullet = "- **Docs:** updated $((($topics | ForEach-Object { '`' + $_ + '`' }) -join ', '))."
    $ui = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^## \[Unreleased\]') { $ui = $i; break } }
    if ($ui -lt 0) { return }
    $docsIdx = -1
    for ($i = $ui + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^## ') { break }
        if ($lines[$i] -match '^### Docs\s*$') { $docsIdx = $i; break }
    }
    if ($docsIdx -ge 0) {
        $ins = $docsIdx + 1
        if ($ins -lt $lines.Count -and $lines[$ins] -eq '') { $ins++ }
        $lines.Insert($ins, $bullet)
    } else {
        $block = @('', '### Docs', '', $bullet)
        for ($k = $block.Count - 1; $k -ge 0; $k--) { $lines.Insert($ui + 1, $block[$k]) }
    }
    Set-Content -LiteralPath $cl -Value $lines -Encoding utf8
}

function Invoke-DocSync([string]$msg) {
    $repo = Get-DocRepo
    if (-not $repo) { Write-Warning 'doc sync: no terminal-stack clone (set $env:TERMINAL_STACK_DIR)'; return }
    Push-Location $repo
    try {
        $changed = & git status --porcelain -- docs/kb
        if (-not $changed) { Write-Host 'doc sync: no changes under docs/kb.'; return }
        Write-Host 'doc sync: changes:'; $changed | ForEach-Object { "  $_" }
        $topics = @($changed | ForEach-Object { (($_ -replace '^...', '') -replace '^docs/kb/', '' -replace '\.md$', '').Trim('"', ' ') } | Sort-Object -Unique)
        Update-DocChangelog $repo $topics
        & git add -- docs/kb CHANGELOG.md
        $prefill = if ($msg) { $msg } else { "docs(kb): update $($topics -join ', ')" }
        & git commit -e -m $prefill
        if ($LASTEXITCODE -ne 0) { Write-Warning 'doc sync: commit aborted; staged changes left in place.'; return }
        $ans = Read-Host 'push to origin? [y/N]'
        if ($ans -match '^(y|yes)$') { & git push } else { Write-Host "doc sync: not pushed (git -C `"$repo`" push)" }
    } finally { Pop-Location }
}

function Write-DocHelp {
    @'
doc                     fuzzy-find a topic (live preview) -> open in less
doc <topic>             open a topic directly (e.g. doc veracrypt, doc ssh-keys)
doc -g <pattern>        grep across every topic (paged)
doc cmd [pattern]       find a command and drop it on your prompt
doc tui [local]         glow's tree browser (tracked kb; 'local' = ~/.doc.local)
doc edit <topic>        edit a topic   |   doc new <os>/<name>   scaffold one
doc ls                  list topics (this OS + common + local)
doc --os <linux|macos|windows> ...    browse another OS
doc sync [msg]          commit doc edits back to the repo (+ changelog, confirm push)

picker keys: ctrl-u/ctrl-d scroll preview · ctrl-/ toggle preview · alt-e edit
reader keys: j/k or arrows scroll · /pattern searches · q quits
style: docs/kb/_style/<dark|light>.json follows your theme ($env:DOC_STYLE overrides)
'@
}

function doc {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    $os = 'windows'; $rest = @()
    if ($Arguments) {
        for ($i = 0; $i -lt $Arguments.Count; $i++) {
            if ($Arguments[$i] -eq '--os' -and $i + 1 -lt $Arguments.Count) { $os = $Arguments[$i + 1]; $i++ }
            else { $rest += $Arguments[$i] }
        }
    }
    $cmd = if ($rest.Count) { $rest[0] } else { '' }
    $tail = if ($rest.Count -gt 1) { ($rest[1..($rest.Count - 1)] -join ' ') } else { '' }
    if (-not (Get-DocRoot)) { Write-Warning "doc: can't find docs/kb (set `$env:TERMINAL_STACK_DIR or `$env:DOC_ROOT)"; return }
    switch -Regex ($cmd) {
        '^$'            { Invoke-DocFinder $os ''; break }
        '^(find)$'      { Invoke-DocFinder $os $tail; break }
        '^(-g|grep)$'   { Invoke-DocGrep $tail; break }
        '^(cmd|c)$'     { Invoke-DocCmd $tail; break }
        '^(tui)$'       {
            if (-not (Get-Command glow -EA SilentlyContinue)) { Write-Warning 'doc tui needs glow (winget install charmbracelet.glow)' }
            elseif ($tail -eq 'local') {
                $l = Get-DocLocal
                if (Test-Path -LiteralPath $l) { & glow $l } else { Write-Warning "doc tui local: $l does not exist" }
            }
            else { & glow (Get-DocRoot) }
            break
        }
        '^(ls|list)$'   { Get-DocIndex $os | Sort-Object Label | ForEach-Object { $_.Label }; break }
        '^(edit|new)$'  { Invoke-DocEdit $cmd $tail $os; break }
        '^(sync)$'      { Invoke-DocSync $tail; break }
        '^(-h|--help|help)$' { Write-DocHelp; break }
        default         { Invoke-DocOpen $cmd $os; break }
    }
}
# ---- doc-end ----

# ---- clipboard-start ----
# ccat — bat without paging (we deliberately don't shadow `cat`/Get-Content).
function ccat {
    if (-not (Get-Command bat -ErrorAction SilentlyContinue)) {
        Write-Warning 'ccat: bat not found — install it or use Get-Content'
        return
    }
    & bat --paging=never @args
}

# clipcopy — pipe input to the clipboard; catclip — a file's contents.
function clipcopy { $input | Set-Clipboard }
function catclip {
    param([Parameter(Mandatory)][string]$Path)
    Get-Content -LiteralPath $Path -Raw | Set-Clipboard
}

# hgrep — search PowerShell (PSReadLine) command history.
function hgrep {
    param([Parameter(ValueFromRemainingArguments)][string[]]$Pattern)
    if (-not $Pattern) { Write-Host 'usage: hgrep <pattern>'; return }
    $h = (Get-PSReadLineOption).HistorySavePath
    if (Test-Path -LiteralPath $h) { Select-String -LiteralPath $h -Pattern ($Pattern -join ' ') | ForEach-Object { $_.Line } }
}
# ---- clipboard-end ----

# ---- workspace-organizer-start ----
# wso — workspace organizer. Thin wrapper: the verbs live in the clone
# (bootstrap\_workspace.ps1 + _workspace_cmd.ps1) so they can be fixed with a
# `ts-update` rather than a profile re-sync, and so the same code serves a
# standalone invocation. The bash twin is bootstrap/wso.sh.
function wso {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    $src = Resolve-TsSourceDir
    if (-not $src) { return }
    $lib = Join-Path $src 'bootstrap\_workspace.ps1'
    if (-not (Test-Path -LiteralPath $lib)) {
        Write-Warning "$lib not found; cannot run wso. Try 'ts-update'."
        return
    }
    . $lib
    # Hand the resolved clone to the library so Get-TsWsRuntimeClone can never
    # disagree with Resolve-TsSourceDir — a disagreement switches off the
    # "never migrate the runtime clone" guard, and `wso migrate` then relocates
    # the install. The zsh twin does the same (dot_zshrc wso).
    $prevPin = $env:TERMINAL_STACK_DIR
    try {
        $env:TERMINAL_STACK_DIR = $src
        Invoke-Wso @Arguments
    } finally {
        if ($null -eq $prevPin) { Remove-Item Env:TERMINAL_STACK_DIR -ErrorAction SilentlyContinue }
        else { $env:TERMINAL_STACK_DIR = $prevPin }
    }
}
# ---- workspace-organizer-end ----

# ---- local-overrides-start ----
# Per-machine overrides (not synced by the stack). The Windows counterpart of
# ~/.zshrc.local — see profile.local.ps1.example. Keep this block last so
# local definitions win.
$tsLocalProfile = Join-Path (Split-Path $PROFILE) 'profile.local.ps1'
if (Test-Path $tsLocalProfile) { . $tsLocalProfile }
# ---- local-overrides-end ----
