# _cleanup.ps1 — find and (with confirmation) remove old terminal-stack clones and
# retired leftover files on Windows, plus a standalone health check. Dot-sourced by
# install.ps1 (post-clone cleanup + post-sync check) and by the profile's
# Test-TerminalStack / Repair-TerminalStack. Never touches the keep-list
# (profile.local.ps1, the personal doc layer, rollback state, *.local.md).
# Honors $env:TS_DRY_RUN = '1' (preview only).

# Candidate clone locations on Windows (current + historical).
# Named Get-TsCleanupCloneCandidates (not Get-TsCloneCandidates) so dot-sourcing
# this file never shadows the richer profile function of the old shared name.
function Get-TsCleanupCloneCandidates {
    @(
        (Join-Path $env:USERPROFILE 'terminal-stack'),
        'C:\DATA\Workspace\terminal-stack',
        (Join-Path $env:USERPROFILE 'code\terminal-stack'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE '.local\share\chezmoi')
    )
}

# True when $dir is a git clone of terminal-stack (remote URL mentions it).
function Test-TsStackClone([string]$dir) {
    if (-not $dir) { return $false }
    if (-not (Test-Path (Join-Path $dir '.git'))) { return $false }
    $url = & git -C $dir config --get remote.origin.url 2>$null
    return [bool]($url -match 'terminal-stack')
}

# Stack clones other than $current (resolved to a canonical path).
function Find-TsClones([string]$current) {
    $cur = if ($current -and (Test-Path $current)) { (Resolve-Path $current).Path } else { $current }
    $seen = New-Object System.Collections.Generic.HashSet[string]
    foreach ($d in Get-TsCleanupCloneCandidates) {
        if (-not (Test-Path $d)) { continue }
        if (-not (Test-TsStackClone $d)) { continue }
        $rp = (Resolve-Path $d).Path
        if ($rp -ieq $cur) { continue }
        if (-not $seen.Add($rp)) { continue }
        [pscustomobject]@{ Path = $d; Tick = $true; Kind = 'clone';
            Label = ('old clone — ' + ((& git -C $d log -1 --format='%h %s' 2>$null) -join ' ')) }
    }
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
