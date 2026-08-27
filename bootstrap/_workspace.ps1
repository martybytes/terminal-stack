# _workspace.ps1 — Windows-native port of bootstrap/_workspace.sh + wso.sh.
#
# The bash pair is the reference implementation and runs on WSL, native Linux
# and macOS. This is the parallel Windows code path, not a wrapper around it:
# calling into WSL would fail on a Windows-standalone install, and driving
# C:\ paths across the 9p boundary is slow enough to matter over ~100 repos.
#
# Same layout, same subcommands, same output, same safety gates. Dot-sourced by
# the `wso` function in $PROFILE; also runnable standalone.
#
# Layout: <root>\<tier>\<host>\<owner>\<repo>
#   src\      owners listed in workspace.conf   (yours; must never be lost)
#   public\   everyone else                     (third-party; disposable cache)
#   archive\  cold repos, mirrors src\ exactly  (per-machine, never synced)
#   local\    no remote yet                     (holding pen)
#   scratch\  not a git repo at all

$script:TsWsTiers = @('src', 'public', 'archive', 'local', 'scratch')

# ------------------------------------------------------------------ config ----

function Get-TsWsConfPaths {
    $out = @()
    $here = Split-Path -Parent $PSCommandPath
    $tracked = Join-Path $here 'workspace.conf'
    if (Test-Path -LiteralPath $tracked) { $out += $tracked }
    $local = Join-Path $env:LOCALAPPDATA 'terminal-stack\workspace.local.conf'
    if (Test-Path -LiteralPath $local) { $out += $local }
    return $out
}

# Parse the whitespace-delimited directive files into one config object.
# Later files win key-by-key, so the per-machine override beats the tracked map.
function Get-TsWsConfig {
    if ($script:TsWsConfig -and -not $env:TS_WS_RELOAD) { return $script:TsWsConfig }
    $orgs = @{}; $renames = @{}; $settings = @{}
    foreach ($f in Get-TsWsConfPaths) {
        foreach ($line in (Get-Content -LiteralPath $f -ErrorAction SilentlyContinue)) {
            $t = $line.Trim()
            if (-not $t -or $t.StartsWith('#')) { continue }
            $p = $t -split '\s+'
            if ($p.Count -lt 3) { continue }
            switch ($p[0]) {
                'org'    { $orgs[$p[1].ToLower()]    = $p[2] }
                'rename' { $renames[$p[1].ToLower()] = $p[2] }
                'set'    { $settings[$p[1]]          = $p[2] }
                default  { Write-Warning "workspace.conf: unknown directive '$($p[0])' in $f" }
            }
        }
    }
    $script:TsWsConfig = [pscustomobject]@{
        Orgs = $orgs; Renames = $renames; Settings = $settings
    }
    return $script:TsWsConfig
}

function Get-TsWsSetting([string]$Key, [string]$Default) {
    $c = Get-TsWsConfig
    if ($c.Settings.ContainsKey($Key)) { return $c.Settings[$Key] }
    return $Default
}

# Owner -> canonical owner, applying the rename map (martsamp77 -> martybytes).
function Get-TsWsCanonOwner([string]$Owner) {
    $c = Get-TsWsConfig
    $k = $Owner.ToLower()
    if ($c.Renames.ContainsKey($k)) { return $c.Renames[$k] }
    return $Owner
}

# Owner -> tier. Resolves the canonical name first, so a renamed owner still
# lands in src/ instead of falling through to public/.
function Get-TsWsTierForOwner([string]$Owner) {
    $c = Get-TsWsConfig
    $k = (Get-TsWsCanonOwner $Owner).ToLower()
    if ($c.Orgs.ContainsKey($k)) { return $c.Orgs[$k] }
    return (Get-TsWsSetting 'default_tier' 'public')
}

function Get-TsWsOwnOwners {
    $c = Get-TsWsConfig
    return @($c.Orgs.Keys | Where-Object { $c.Orgs[$_] -eq 'src' } | Sort-Object)
}

# --------------------------------------------------------------- workspace ----

# Reuses the profile's Get-TsWorkspace when it is loaded; falls back to the same
# probe order when this file is run standalone.
function Get-TsWsRoot {
    if (Get-Command Get-TsWorkspace -ErrorAction SilentlyContinue) {
        $r = Get-TsWorkspace
        if ($r) { return $r }
    }
    if ($env:WORKSPACE_DIR) { return $env:WORKSPACE_DIR }
    foreach ($d in @(
        'C:\DATA\Workspace',
        (Join-Path $env:USERPROFILE 'workspace'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace')
    )) { if (Test-Path -LiteralPath $d) { return $d } }
    return $null
}

function Get-TsWsStateDir { Join-Path $env:LOCALAPPDATA 'terminal-stack' }

# The ACTIVE terminal-stack runtime clone (the one tstack update updates), resolved.
# wso must never migrate it: relocating the runtime clone breaks the install
# (that's tstack doctor's job).
#
# Reuses the profile's Resolve-TsSourceDir when it is loaded — the same
# delegation Get-TsWsRoot does for Get-TsWorkspace. A narrower resolver here is
# not a harmless simplification: this guard returning $null is what let
# `wso migrate` relocate a runtime clone that lived at a legacy path, because
# pin → canonical alone doesn't know about the legacy candidates.
# Standalone fallback: $env:TERMINAL_STACK_DIR → the canonical location.
function Get-TsWsRuntimeClone {
    $src = $null
    if (Get-Command Resolve-TsSourceDir -ErrorAction SilentlyContinue) {
        # Quietly — an unresolvable clone is not this function's error to report,
        # and the caller has already said its piece. Resolve-TsSourceDir is a
        # simple function, so -WarningAction would bind as a positional argument
        # instead of suppressing anything; set the preference in scope instead.
        $WarningPreference = 'SilentlyContinue'
        $src = Resolve-TsSourceDir 6>$null
    }
    if (-not $src) { $src = $env:TERMINAL_STACK_DIR }
    if (-not $src) {
        $canon = Join-Path $env:LOCALAPPDATA 'terminal-stack\stack'
        if (Test-Path (Join-Path $canon '.git')) { $src = $canon }
    }
    if (-not $src -or -not (Test-Path -LiteralPath $src)) { return $null }
    return (Resolve-Path -LiteralPath $src).Path
}

# ----------------------------------------------------------- remote parsing ----

# Returns @{Host;Owner;Repo} or $null. Handles every form git emits:
#   git@host:owner/repo.git      ssh://git@host:22/owner/repo.git
#   https://user@host/owner/repo git://host/owner/repo.git
# Nested GitLab groups collapse into Owner so group/subgroup/repo stays unique.
function ConvertFrom-TsWsRemote([string]$Url) {
    if (-not $Url) { return $null }
    $u = $Url.Trim()
    $u = $u -replace '\.git/?$', ''
    $u = $u.TrimEnd('/')
    $hostName = ''; $path = ''
    if ($u -match '^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$') {
        $hostName = $Matches[1]; $path = $Matches[2]
    }
    elseif ($u -match '^(?:[^@/]+@)?([^:/]+):(.+)$') {
        $hostName = $Matches[1]; $path = $Matches[2]
    }
    else { return $null }
    $segs = @($path.Trim('/') -split '/' | Where-Object { $_ -ne '' })
    if ($segs.Count -lt 2) { return $null }
    return [pscustomobject]@{
        Host  = $hostName.ToLower()
        Owner = ($segs[0..($segs.Count - 2)] -join '/')
        Repo  = $segs[-1]
    }
}

function New-TsWsRemoteUrl([string]$Scheme, [string]$HostName, [string]$Owner, [string]$Repo, [string]$Original) {
    switch ($Scheme) {
        'ssh'   { return "git@${HostName}:$Owner/$Repo.git" }
        'https' { return "https://$HostName/$Owner/$Repo.git" }
        default { return $Original }
    }
}

function Get-TsWsOrigin([string]$Path) {
    $u = & git -C $Path config --get remote.origin.url 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $u) { return $null }
    return ([string]($u | Select-Object -First 1)).Trim()
}

# ---------------------------------------------------------------- dest_for ----

# The single place a repo's home is decided. Returns @{Tier;Rel;Note}.
function Get-TsWsDestFor([string]$Dir) {
    $name = Split-Path -Leaf $Dir
    if (-not (Test-Path -LiteralPath (Join-Path $Dir '.git'))) {
        return [pscustomobject]@{ Tier = 'scratch'; Rel = "scratch\$name"; Note = 'not a git repo' }
    }
    $origin = Get-TsWsOrigin $Dir
    if (-not $origin) {
        return [pscustomobject]@{ Tier = 'local'; Rel = "local\$name"
                                  Note = 'NO REMOTE - push before this becomes a real path' }
    }
    $p = ConvertFrom-TsWsRemote $origin
    if (-not $p) {
        return [pscustomobject]@{ Tier = 'local'; Rel = ''; Note = "unparseable remote: $origin" }
    }
    $canon = Get-TsWsCanonOwner $p.Owner
    $tier  = Get-TsWsTierForOwner $canon
    $note  = ''
    if ($canon -ne $p.Owner) { $note = "owner renamed $($p.Owner) -> $canon" }
    if ($name -ne $p.Repo) {
        if ($note) { $note += '; ' }
        $note += "folder '$name' renamed to match remote"
    }
    $ownerPath = $canon -replace '/', '\'
    return [pscustomobject]@{
        Tier = $tier
        Rel  = "$tier\$($p.Host)\$ownerPath\$($p.Repo)"
        Note = $note
    }
}

# --------------------------------------------------------------- git state ----

function Get-TsWsGitState([string]$Dir) {
    $porcelain = @(& git -C $Dir status --porcelain 2>$null)
    $dirty = @($porcelain | Where-Object { $_ }).Count
    # Commits on ANY local branch that no remote has. A repo can be clean and
    # still hold the only copy of work, on a branch you are not standing on.
    $unpushed = 0
    $u = & git -C $Dir rev-list --count --branches --not --remotes 2>$null
    if ($LASTEXITCODE -eq 0 -and $u) { $unpushed = [int]$u }
    $stashes = 0
    $s = & git -C $Dir rev-list --walk-reflogs --count refs/stash 2>$null
    if ($LASTEXITCODE -eq 0 -and $s) { $stashes = [int]$s }
    $head = & git -C $Dir symbolic-ref --quiet --short HEAD 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $head) { $head = 'DETACHED' }
    return [pscustomobject]@{
        Dirty = $dirty; Unpushed = $unpushed; Stashes = $stashes; Head = ([string]$head).Trim()
    }
}

# Returns '' when safe to move away, otherwise the reason it is held.
function Get-TsWsUnsafeReason([string]$Dir) {
    $st = Get-TsWsGitState $Dir
    $why = @()
    if ($st.Dirty -gt 0)    { $why += "$($st.Dirty) uncommitted" }
    if ($st.Unpushed -gt 0) { $why += "$($st.Unpushed) unpushed" }
    if ($st.Stashes -gt 0)  { $why += "$($st.Stashes) stashed" }
    if ($st.Head -eq 'DETACHED') { $why += 'detached-HEAD' }
    if (-not (Get-TsWsOrigin $Dir)) { $why += 'no-remote' }
    return ($why -join ' ')
}

# --------------------------------------------------------------- staleness ----

# Newest LastWriteTime among a repo's immediate children, EXCLUDING .git.
#
# A directory's own timestamp only moves when entries are added or removed, so
# ranking on it buries a repo you edited all day — the trap `lsr` exists to
# avoid. Excluding .git matters even more here: git fetch, gc and status all
# churn files under .git, which would make every repo look touched today.
function Get-TsWsNewestChild([string]$Dir) {
    $newest = $null
    foreach ($c in (Get-ChildItem -LiteralPath $Dir -Force -ErrorAction SilentlyContinue)) {
        if ($c.Name -eq '.git') { continue }
        if (-not $newest -or $c.LastWriteTimeUtc -gt $newest) { $newest = $c.LastWriteTimeUtc }
    }
    return $newest
}

# The later of the last commit and the newest working file. A repo cloned last
# week but never committed to is not stale, and neither is one you have been
# editing without committing.
function Get-TsWsLastActivity([string]$Dir) {
    $best = $null
    $ct = & git -C $Dir log -1 --format=%ct 2>$null
    if ($LASTEXITCODE -eq 0 -and $ct) {
        $best = [DateTimeOffset]::FromUnixTimeSeconds([int64]$ct).UtcDateTime
    }
    $child = Get-TsWsNewestChild $Dir
    if ($child -and (-not $best -or $child -gt $best)) { $best = $child }
    return $best
}

# ------------------------------------------------------------------- moves ----

function Test-TsWsSameVolume([string]$A, [string]$B) {
    # $probe, not $b: PowerShell variable names are case-insensitive, so $b IS
    # the $B parameter. Harmless here (both are strings), but the same shape in
    # Read-TsMulti coerced a scriptblock into a string and broke the wizard.
    $probe = $B
    while ($probe -and -not (Test-Path -LiteralPath $probe)) { $probe = Split-Path -Parent $probe }
    if (-not $probe) { return $false }
    $ra = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $A).Path)
    $rb = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $probe).Path)
    return ($ra -and $ra -eq $rb)
}

# Move with retry. Windows releases directory handles asynchronously, and an
# editor, terminal, language server or indexer holding one makes the rename
# fail transiently. Within a volume this is an atomic rename, so dirty files,
# stashes, reflog and untracked scratch all survive; across volumes it would
# silently become a copy, so we refuse instead.
function Move-TsWsRepo([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Write-Warning "destination exists, refusing: $Destination"; return $false
    }
    if (-not (Test-TsWsSameVolume $Source $Destination)) {
        Write-Warning "$Source and $Destination are on different volumes; that is a copy, not a rename."
        Write-Warning "Move it by hand, or point the workspace root at the same volume."
        return $false
    }
    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $max = if ($env:TS_WS_MOVE_RETRIES) { [int]$env:TS_WS_MOVE_RETRIES } else { 5 }
    for ($n = 0; $n -lt $max; $n++) {
        try {
            Move-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
            return $true
        } catch {
            $err = $_.Exception.Message
            Start-Sleep -Seconds 1
        }
    }
    Write-Warning "could not move $Source - $err"
    Write-Warning "  something is holding it open (editor, terminal, language server, indexer)"
    return $false
}

# -------------------------------------------------------------------- logs ----

# Run logs live inside the workspace, not in per-OS state. They describe the
# workspace, not the machine — and on a combined Windows+WSL setup both sides
# drive the same tree, so an `--undo-last` from PowerShell must see an archive
# run done from zsh. Splitting them by OS state dir would silently hide it.
# The leading dot keeps the directory out of Get-TsWsScanCandidates.
function Get-TsWsRunLogDir { Join-Path (Get-TsWsRoot) '.terminal-stack\workspace-runs' }

# Run logs store paths RELATIVE to the workspace root, with forward slashes.
# Absolute paths would be unreadable from the other side of a combined
# Windows+WSL setup: "C:\...\archive\x" means nothing to zsh. These two helpers
# are the only places that format matters.
function ConvertTo-TsWsLogPath([string]$Path, [string]$Root) {
    if (-not $Root) { $Root = Get-TsWsRoot }
    $prefix = $Root.TrimEnd('\') + '\'
    if ($Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        $Path = $Path.Substring($prefix.Length)
    }
    return ($Path -replace '\\', '/')
}
function ConvertFrom-TsWsLogPath([string]$Rel, [string]$Root) {
    if (-not $Root) { $Root = Get-TsWsRoot }
    return (Join-Path $Root ($Rel -replace '/', '\'))
}

function New-TsWsRunLog([string]$Kind) {
    $dir = Get-TsWsRunLogDir
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $f = Join-Path $dir ((Get-Date -Format 'yyyyMMdd-HHmmss') + "-$Kind.tsv")
    "action`tsource`tdestination" | Set-Content -LiteralPath $f -Encoding utf8
    return $f
}

function Get-TsWsLatestRunLog([string]$Kind) {
    $dir = Get-TsWsRunLogDir
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    return (Get-ChildItem -LiteralPath $dir -Filter "*-$Kind.tsv" -ErrorAction SilentlyContinue |
            Sort-Object Name | Select-Object -Last 1).FullName
}

# ---------------------------------------------------------------- scanning ----

# Scan roots: the workspace plus its legacy siblings (Workspace_Public,
# Workspace-md, ...). The sibling list comes from enumerating the parent rather
# than guessing suffixes — NTFS is case-insensitive, so probing both "-md" and
# "-MD" finds the same directory twice and plans every repo inside it twice.
function Get-TsWsScanRoots {
    $root = Get-TsWsRoot
    if (-not $root) { return @() }
    $root = $root.TrimEnd('\')
    $out = [System.Collections.Generic.List[string]]::new()
    $out.Add($root)
    $parent = Split-Path -Parent $root
    $base   = (Split-Path -Leaf $root).ToLower()
    if ($parent -and (Test-Path -LiteralPath $parent)) {
        foreach ($d in (Get-ChildItem -LiteralPath $parent -Directory -Force -ErrorAction SilentlyContinue)) {
            $n = $d.Name.ToLower()
            if ($n -like "$base[-_]*") { $out.Add($d.FullName) }
        }
    }
    if ($env:TS_WS_EXTRA_ROOTS) {
        foreach ($e in ($env:TS_WS_EXTRA_ROOTS -split ';')) {
            if ($e -and (Test-Path -LiteralPath $e)) { $out.Add($e) }
        }
    }
    $seen = @{}
    return @($out | Where-Object { $k = $_.ToLower(); if ($seen[$k]) { $false } else { $seen[$k] = $true; $true } })
}

# Immediate children of each scan root, minus tier dirs and dotfiles. Tier dirs
# are skipped so a re-run after migration does not migrate the tree into itself.
function Get-TsWsScanCandidates {
    $root = (Get-TsWsRoot)
    if ($root) { $root = $root.TrimEnd('\') }
    foreach ($r in (Get-TsWsScanRoots)) {
        $isRoot = ($r.TrimEnd('\') -eq $root)
        foreach ($d in (Get-ChildItem -LiteralPath $r -Directory -Force -ErrorAction SilentlyContinue)) {
            if ($d.Name.StartsWith('.')) { continue }
            # Skip tier directories, but ONLY directly under the workspace root.
            # Legacy sibling roots can legitimately hold a repo named "public" or
            # "local"; treating those as tiers would silently drop a real repo
            # from the migration plan, which is the one thing this must never do.
            if ($isRoot -and $script:TsWsTiers -contains $d.Name.ToLower()) { continue }
            $d.FullName
        }
    }
}

function Get-TsWsManagedRepos([string[]]$Tiers = @('src', 'public', 'archive', 'local')) {
    $root = Get-TsWsRoot
    if (-not $root) { return }
    foreach ($t in $Tiers) {
        $p = Join-Path $root $t
        if (-not (Test-Path -LiteralPath $p)) { continue }
        # Depth 4, not 3: nested GitLab groups (tier/host/group/subgroup/repo)
        # are a supported remote shape (see ConvertFrom-TsWsRemote) and the bash
        # twin (ts_ws_managed_repos, -maxdepth 5) already finds them.
        Get-ChildItem -LiteralPath $p -Directory -Recurse -Depth 4 -Force -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName '.git') } |
            ForEach-Object { $_.FullName }
    }
}

function Get-TsWsAllRepos {
    Get-TsWsManagedRepos
    Get-TsWsScanCandidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ '.git') }
}

# The subcommand layer lives alongside this file; keeping the layout library and
# the verbs separate mirrors the bash split (_workspace.sh / wso.sh).
$script:TsWsCmdPath = Join-Path (Split-Path -Parent $PSCommandPath) '_workspace_cmd.ps1'
if (Test-Path -LiteralPath $script:TsWsCmdPath) { . $script:TsWsCmdPath }
