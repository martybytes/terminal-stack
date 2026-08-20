# _cleanup.ps1 — find and (with confirmation) remove old terminal-stack clones and
# retired leftover files on Windows, plus a standalone health check. Dot-sourced by
# install.ps1 (post-clone cleanup + post-sync check) and by the profile's
# Test-TerminalStack / Repair-TerminalStack. Never touches the keep-list
# (profile.local.ps1, the personal doc layer, rollback state, *.local.md).
# Honors $env:TS_DRY_RUN = '1' (preview only).

# The canonical runtime clone location. Twin of the profile's
# Get-TsCanonicalCloneDir (identical body — parse-time isolation forces the copy;
# keep in sync both ways) and bootstrap/_config.sh ts_canonical_clone_dir.
function Get-TsCanonicalCloneDir { Join-Path $env:LOCALAPPDATA 'terminal-stack\stack' }

# True when a path is a DEV clone at a wso workspace tier path. Twin of the
# profile's Test-TsDevClone and bootstrap/_cleanup.sh ts_is_dev_clone (master).
function Test-TsDevClone([string]$Path) {
    ($Path -replace '\\', '/') -match '/(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$'
}

# CANONICAL CLONE CANDIDATE LIST (pwsh cleanup replica) — keep in sync with
# docs/decisions.md § "Runtime clone location" and the siblings:
# bootstrap/_cleanup.sh ts_clone_candidates (master), dot_zshrc
# _ts_clone_candidates, profile Get-TsCloneCandidates.
# Named Get-TsCleanupCloneCandidates (not Get-TsCloneCandidates) so dot-sourcing
# this file never shadows the richer profile function of the old shared name.
function Get-TsCleanupCloneCandidates {
    @(
        (Get-TsCanonicalCloneDir),
        (Join-Path $env:USERPROFILE 'code\terminal-stack'),
        (Join-Path $env:USERPROFILE 'terminal-stack'),
        (Join-Path $env:USERPROFILE 'Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE '.local\share\chezmoi'),
        'C:\DATA\Workspace\terminal-stack'
    )
}

# True when $dir is a git clone of terminal-stack (remote URL mentions it).
function Test-TsStackClone([string]$dir) {
    if (-not $dir) { return $false }
    if (-not (Test-Path (Join-Path $dir '.git'))) { return $false }
    $url = & git -C $dir config --get remote.origin.url 2>$null
    return [bool]($url -match 'terminal-stack')
}

# Stack clones other than $current (resolved to a canonical path). The canonical
# runtime location and dev clones (workspace tier paths) are never offered.
function Find-TsClones([string]$current) {
    $cur = if ($current -and (Test-Path $current)) { (Resolve-Path $current).Path } else { $current }
    $canon = Get-TsCanonicalCloneDir
    $seen = New-Object System.Collections.Generic.HashSet[string]
    foreach ($d in Get-TsCleanupCloneCandidates) {
        if (-not (Test-Path $d)) { continue }
        if (-not (Test-TsStackClone $d)) { continue }
        if (Test-TsDevClone $d) { continue }
        $rp = (Resolve-Path $d).Path
        if ($rp -ieq $cur) { continue }
        if ($rp -ieq $canon -or $rp.TrimEnd('\') -ieq $canon.TrimEnd('\')) { continue }
        if (-not $seen.Add($rp)) { continue }
        [pscustomobject]@{ Path = $d; Tick = $true; Kind = 'clone';
            Label = ('old clone — ' + ((& git -C $d log -1 --format='%h %s' 2>$null) -join ' ')) }
    }
}

# Remove a stale $env:TERMINAL_STACK_DIR pin from profile.local.ps1 (backed up
# first). Canonical needs no pin. Mirror logic of the profile's
# Set-TsSourceDirPersisted — keep the two in sync.
function Clear-TsSourceDirPin {
    $localProfile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    if ((Test-Path $localProfile) -and
        (Get-Content $localProfile | Where-Object { $_ -match '^\s*\$env:TERMINAL_STACK_DIR\s*=' })) {
        Backup-TsFile $localProfile
        # -Value, not a pipeline: when the pin is the ONLY line in the file the
        # filter yields nothing, and `… | Set-Content` with no pipeline input
        # leaves the file untouched — so the pin survived exactly the case this
        # is for (a machine whose only override is the pin). `-Value @()` truncates.
        $kept = @((Get-Content $localProfile) |
                  Where-Object { $_ -notmatch '^\s*\$env:TERMINAL_STACK_DIR\s*=' })
        Set-Content -LiteralPath $localProfile -Value $kept -Encoding utf8
        Write-Host "==> removed the `$env:TERMINAL_STACK_DIR pin from $localProfile (canonical location needs none)"
    }
    if (Test-Path Env:TERMINAL_STACK_DIR) { Remove-Item Env:TERMINAL_STACK_DIR }
}

# Move the runtime clone to a new location, git state (incl. dirty worktree,
# stashes, reflog) intact. Same-volume = instant rename; cross-volume = copy,
# HEAD-verify, then remove source. Returns $true on success. The caller runs
# sync/verify afterwards — this function has no sync side effect.
function Move-TsClone {
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Dest)
    if (-not (Test-TsStackClone $Source)) { Write-Warning "Move-TsClone: '$Source' is not a terminal-stack clone."; return $false }
    if (Test-Path $Dest) { Write-Warning "Move-TsClone: destination '$Dest' already exists."; return $false }
    if (($Dest.TrimEnd('\') + '\') -like (($Source.TrimEnd('\')) + '\*')) {
        Write-Warning 'Move-TsClone: destination is inside the source.'; return $false
    }
    if (& git -C $Source status --porcelain 2>$null) {
        Write-Host '==> clone has uncommitted changes — they move with it.'
    }
    $head = (& git -C $Source rev-parse HEAD 2>$null)
    $srcResolved = (Resolve-Path $Source).Path
    $returnTo = $null
    if ((Get-Location).Path.TrimEnd('\') -ieq $srcResolved.TrimEnd('\') -or
        (Get-Location).Path -like "$srcResolved\*") {
        # Windows can't rename a directory a process is sitting in — step out.
        $returnTo = $true
        Set-Location $env:USERPROFILE
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Write-Host "==> moving $Source -> $Dest"
    try {
        [System.IO.Directory]::Move($srcResolved, $Dest)
    } catch [System.IO.IOException] {
        if ($_.Exception.Message -match 'not on the same volume|different volume') {
            Copy-Item -LiteralPath $srcResolved -Destination $Dest -Recurse -Force
            if ((& git -C $Dest rev-parse HEAD 2>$null) -ne $head) {
                Write-Warning "Move-TsClone: HEAD mismatch after copy — source left at $Source; inspect $Dest."
                return $false
            }
            Remove-Item -LiteralPath $srcResolved -Recurse -Force
        } else {
            Write-Warning "Move-TsClone: move failed ($($_.Exception.Message)). Close shells/editors open in $Source and re-run ts-doctor -Repair."
            return $false
        }
    }
    if ((& git -C $Dest rev-parse HEAD 2>$null) -ne $head) {
        Write-Warning "Move-TsClone: HEAD mismatch after move — inspect $Dest before continuing."
        return $false
    }
    if ($returnTo) { Set-Location $Dest }
    # A pin at the old path is now stale; canonical needs no pin.
    if ($env:TERMINAL_STACK_DIR -and
        ($env:TERMINAL_STACK_DIR.TrimEnd('\') -ieq $Source.TrimEnd('\'))) {
        Clear-TsSourceDirPin
    }
    # Normalize an origin URL left over from the renamed account.
    $canonRemote = 'https://github.com/martybytes/terminal-stack.git'
    $origin = (& git -C $Dest config --get remote.origin.url 2>$null)
    if ($origin -and $origin -ne $canonRemote -and $origin -notmatch 'git@github\.com:martybytes/terminal-stack') {
        if (-not [Console]::IsInputRedirected) {
            $a = Read-Host "Origin is '$origin' — set it to $canonRemote? [Y/n]"
            if ($a -notmatch '^(n|no)$') {
                & git -C $Dest remote set-url origin $canonRemote
                Write-Host "==> origin -> $canonRemote"
            }
        }
    }
    Write-Host "==> clone relocated to $Dest"
    return $true
}

# Retired/leftover files under %USERPROFILE%. Known artifacts are pre-ticked;
# loose scripts that merely mention the stack are listed off-by-default.
function Find-TsStray {
    foreach ($n in @('command-reference.md','command-reference.txt','command-reference.html','.wezterm-ref')) {
        $p = Join-Path $env:USERPROFILE $n
        if (Test-Path $p) {
            [pscustomobject]@{ Path = $p; Tick = $true; Kind = 'file'; Label = 'retired terminal-stack artifact' }
        }
    }
    Get-ChildItem -Path $env:USERPROFILE -Filter '*.ps1' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'profile.local.ps1' } |
        ForEach-Object {
            if (Select-String -Path $_.FullName -Pattern 'terminal-stack|sync-windows|chezmoi' -Quiet -ErrorAction SilentlyContinue) {
                [pscustomobject]@{ Path = $_.FullName; Tick = $false; Kind = 'file';
                    Label = 'loose script mentioning terminal-stack (verify first)' }
            }
        }
}

# Back up a file as <path>.bak.YYYYMMDD[.N] before removal (repo convention).
function Backup-TsFile([string]$f) {
    if (-not (Test-Path $f)) { return }
    $stamp = Get-Date -Format 'yyyyMMdd'
    $bak = "$f.bak.$stamp"; $n = 1
    while (Test-Path $bak) { $bak = "$f.bak.$stamp.$n"; $n++ }
    Copy-Item -LiteralPath $f -Destination $bak -Force -ErrorAction SilentlyContinue
    Write-Host "==> backed up $f -> $bak"
}

# Interactive cleanup checklist. $current is the clone to KEEP (never offered).
function Invoke-TsCleanupMenu([string]$current) {
    $items = @()
    $items += @(Find-TsClones $current)
    $items += @(Find-TsStray)
    if ($items.Count -eq 0) { Write-Host '==> Cleanup: no old clones or leftover files found.'; return }

    while ($true) {
        Write-Host ''
        Write-Host '==> Old terminal-stack instances / leftover files found:'
        for ($i = 0; $i -lt $items.Count; $i++) {
            $mark = if ($items[$i].Tick) { 'x' } else { ' ' }
            Write-Host ("  [{0}] {1,2}) {2}" -f $mark, ($i + 1), $items[$i].Path)
            Write-Host ("         {0}" -f $items[$i].Label)
        }
        Write-Host '      Keep-list (profile.local.ps1, .doc.local, rollback state, *.local.md) is never shown.'
        $ans = Read-Host 'Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip cleanup'
        if ($ans -eq '') { break }
        elseif ($ans -match '^(s|skip)$') { Write-Host '==> Cleanup skipped.'; return }
        elseif ($ans -match '^(a|all)$')  { foreach ($it in $items) { $it.Tick = $true } }
        elseif ($ans -match '^(n|none)$') { foreach ($it in $items) { $it.Tick = $false } }
        elseif ($ans -match '^\d+$') {
            $idx = [int]$ans - 1
            if ($idx -ge 0 -and $idx -lt $items.Count) { $items[$idx].Tick = -not $items[$idx].Tick }
        } else { Write-Host '  ? enter a number, a, n, s, or Enter' }
    }

    $selected = @($items | Where-Object { $_.Tick })
    if ($selected.Count -eq 0) { Write-Host '==> Nothing selected; cleanup skipped.'; return }

    if ($env:TS_DRY_RUN -eq '1') {
        Write-Host "==> [dry-run] would remove $($selected.Count) item(s):"
        $selected | ForEach-Object { Write-Host "    $($_.Path)" }
        return
    }

    $confirm = Read-Host "Remove $($selected.Count) selected item(s)? This cannot be undone for clones. [y/N]"
    if ($confirm -notmatch '^(y|yes)$') { Write-Host '==> Cleanup cancelled; nothing removed.'; return }

    $removed = 0
    foreach ($it in $selected) {
        if ($it.Kind -eq 'file') { Backup-TsFile $it.Path }
        try { Remove-Item -LiteralPath $it.Path -Recurse -Force -ErrorAction Stop; Write-Host "==> removed $($it.Path)"; $removed++ }
        catch { Write-Warning "failed to remove $($it.Path): $_" }
    }
    Write-Host "==> Cleanup: removed $removed item(s)."
}

# Standalone health check. Returns the number of issues found (0 = healthy).
# $SourceDir is the resolved clone (from Resolve-TsSourceDir). $Quiet suppresses
# the per-check "ok" lines.
function Test-TsInstall {
    param([string]$SourceDir, [switch]$Quiet)
    $issues = 0
    function _ok([string]$m)  { if (-not $Quiet) { Write-Host "  ok  $m" } }
    function _bad([string]$m) { Write-Warning "  $m"; $script:_tsIssues++ }
    $script:_tsIssues = 0

    if (-not $Quiet) { Write-Host '==> terminal-stack doctor (Windows)' }

    if (-not $SourceDir -or -not (Test-Path (Join-Path $SourceDir '.git'))) {
        _bad "no terminal-stack clone found (set `$env:TERMINAL_STACK_DIR or re-run install.ps1)"
    } elseif (-not (Test-TsStackClone $SourceDir)) {
        _bad "$SourceDir is a git repo but not a terminal-stack clone"
    } else {
        _ok "clone: $SourceDir"
    }

    $cfg = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
    if (Test-Path $cfg) { _ok "config: $cfg" } else { _bad "config.json missing ($cfg) — run install.ps1 or ts-config" }

    if (Test-Path $PROFILE) {
        if (Select-String -Path $PROFILE -Pattern 'terminal-stack-update-start' -Quiet -ErrorAction SilentlyContinue) {
            _ok '$PROFILE has the terminal-stack block'
        } else { _bad '$PROFILE missing the terminal-stack block (re-run sync-windows.ps1)' }
    } else { _bad '$PROFILE not found (run sync-windows.ps1)' }

    # Location advisory (not a health failure): a legacy-path clone can be moved.
    $canon = Get-TsCanonicalCloneDir
    if ($SourceDir -and $SourceDir.TrimEnd('\') -ne $canon.TrimEnd('\')) {
        if (Test-TsDevClone $SourceDir) {
            Write-Host '  note: pinned at a dev clone (workspace tier path) — deliberate, leaving it alone.'
        } else {
            Write-Host "  note: clone is at a legacy location; 'ts-doctor -Repair' can move it to $canon"
        }
    }

    # Leftover clones are advisory, not a health failure — note without counting.
    $others = @(Find-TsClones $SourceDir)
    if ($others.Count -gt 0) {
        Write-Host '  note: other terminal-stack clones present (Repair-TerminalStack can clean them up):'
        $others | ForEach-Object { Write-Host "        $($_.Path)" }
    }

    $issues = $script:_tsIssues
    if ($issues -eq 0) { if (-not $Quiet) { Write-Host '==> all checks passed.' } }
    else { Write-Warning "$issues issue(s) found — run Repair-TerminalStack (ts-doctor -Repair) to fix." }
    return $issues
}
