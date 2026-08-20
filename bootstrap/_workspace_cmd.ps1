# _workspace_cmd.ps1 — the `wso` subcommands for Windows. Dot-sourced by
# _workspace.ps1; kept in its own file so the layout library stays readable and
# so the two halves mirror the bash split (_workspace.sh / wso.sh).
#
# Every verb here matches bootstrap/wso.sh exactly: same names, same flags, same
# output shape, same safety gates. Honors $env:TS_DRY_RUN = '1'.

function Write-TsWsInfo([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Blue }
function Write-TsWsWarn([string]$Msg) { Write-Host "!! $Msg"  -ForegroundColor Yellow }

# Read-Host blocks forever when stdin is redirected — a piped invocation, CI, or
# an agent harness. The bash side's ts_tty_prompt returns "" in that case and
# every caller falls through to its default; mirror that instead of hanging.
function Read-TsWsPrompt([string]$Prompt) {
    if ([Console]::IsInputRedirected) { return '' }
    return (Read-Host $Prompt)
}

# Non-interactive answers NO unless TS_WS_YES=1 was set explicitly. Defaulting a
# confirmation to "yes" because nobody could be asked is how unattended runs move
# things they should not have.
function Confirm-TsWs([string]$Prompt) {
    if ($env:TS_WS_YES -eq '1') { return $true }
    if ([Console]::IsInputRedirected) {
        Write-TsWsWarn "$Prompt -> no terminal to ask; assuming no (set TS_WS_YES=1 to auto-confirm)"
        return $false
    }
    $a = Read-Host $Prompt
    return ($a -match '^(y|Y|yes|YES)$')
}

# Strip the workspace root for display. The trailing separator is load-bearing:
# without it "C:\DATA\Workspace-md\foo" matches the root "C:\DATA\Workspace" and
# renders as "-md\foo". Legacy sibling roots are exactly the paths this command
# reports on before a migration, so that is the common case, not a corner one.
function Get-TsWsRelative([string]$Path, [string]$Root) {
    if (-not $Root) { return $Path }
    $prefix = $Root.TrimEnd('\') + '\'
    if ($Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        return $Path.Substring($prefix.Length)
    }
    return $Path
}

# ------------------------------------------------------------------ status ----

function Invoke-TsWsStatus([string[]]$Arguments) {
    $root = Get-TsWsRoot
    $onlyDirty = $false; $org = ''
    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        switch -Regex ($Arguments[$i]) {
            '^--dirty$' { $onlyDirty = $true }
            '^--org$'   { $org = $Arguments[$i + 1]; $i++ }
            default     { Write-Warning "wso status: unknown option: $($Arguments[$i])"; return }
        }
    }
    $n = 0; $nd = 0; $nu = 0; $ndet = 0; $nnr = 0
    foreach ($d in (Get-TsWsAllRepos)) {
        if ($org -and $d -notmatch [regex]::Escape("\$org\")) { continue }
        $n++
        $st = Get-TsWsGitState $d
        $origin = Get-TsWsOrigin $d
        if ($st.Dirty -gt 0) { $nd++ }
        if ($st.Unpushed -gt 0) { $nu++ }
        if ($st.Head -eq 'DETACHED') { $ndet++ }
        if (-not $origin) { $nnr++ }
        $flags = @()
        if ($st.Dirty -gt 0)    { $flags += "$($st.Dirty) dirty" }
        if ($st.Unpushed -gt 0) { $flags += "$($st.Unpushed) unpushed" }
        if ($st.Stashes -gt 0)  { $flags += "$($st.Stashes) stash" }
        if ($st.Head -eq 'DETACHED') { $flags += 'DETACHED' }
        if (-not $origin) { $flags += 'no-remote' }
        if ($flags.Count) {
            "{0,-58} {1}" -f (Get-TsWsRelative $d $root), ($flags -join ' ')
        } elseif (-not $onlyDirty -and $env:TS_WS_VERBOSE -eq '1') {
            "{0,-58} ok" -f (Get-TsWsRelative $d $root)
        }
    }
    "--"
    "{0} repos   {1} dirty   {2} unpushed   {3} detached   {4} no-remote" -f $n, $nd, $nu, $ndet, $nnr
}

# -------------------------------------------------------------------- plan ----

# Build the migration plan. Status is move | inplace | conflict | blocked | runtime.
function Get-TsWsPlan {
    $root = Get-TsWsRoot
    $runtime = Get-TsWsRuntimeClone
    $rows = foreach ($d in (Get-TsWsScanCandidates)) {
        # Never plan the active runtime clone into the tree — relocating it
        # breaks the install; ts-doctor -Repair owns that move.
        if ($runtime) {
            $dResolved = try { (Resolve-Path -LiteralPath $d).Path } catch { $d }
            if ($dResolved.TrimEnd('\') -ieq $runtime.TrimEnd('\')) {
                [pscustomobject]@{ Status = 'runtime'; Source = $d; Dest = ''
                    Note = 'active terminal-stack runtime clone - not migrated (relocate with ts-doctor -Repair)' }
                continue
            }
        }
        # Belt and braces: skip ANY un-tiered terminal-stack clone, not only the
        # one that resolved as active. Get-TsWsRuntimeClone returns $null in
        # exactly the broken states where this matters most (dangling pin, clone
        # at a legacy path), and a $null there used to switch the guard off — that
        # is how a runtime clone got migrated to a tier path and orphaned the
        # install. A real dev clone already lives at a tier path and is therefore
        # never a scan candidate, so nothing legitimate is blocked here.
        if ((& git -C $d config --get remote.origin.url 2>$null) -match 'terminal-stack') {
            [pscustomobject]@{ Status = 'runtime'; Source = $d; Dest = ''
                Note = 'terminal-stack clone at the workspace root - not migrated (relocate with ts-doctor -Repair)' }
            continue
        }
        $dest = Get-TsWsDestFor $d
        if (-not $dest.Rel) {
            [pscustomobject]@{ Status = 'blocked'; Source = $d; Dest = ''; Note = $dest.Note }
            continue
        }
        $full = Join-Path $root $dest.Rel
        if ($full -eq $d) {
            [pscustomobject]@{ Status = 'inplace'; Source = $d; Dest = $full; Note = 'already correct' }
        } elseif (Test-Path -LiteralPath $full) {
            $n = 'destination already exists'
            if ($dest.Note) { $n += "; $($dest.Note)" }
            [pscustomobject]@{ Status = 'conflict'; Source = $d; Dest = $full; Note = $n }
        } else {
            [pscustomobject]@{ Status = 'move'; Source = $d; Dest = $full; Note = $dest.Note }
        }
    }
    $rows = @($rows)
    # Two sources claiming one destination is the diverged-duplicate case.
    # Demote every member so neither moves and the pair is visible.
    $counts = @{}
    foreach ($r in $rows) { if ($r.Status -eq 'move') { $counts[$r.Dest] = 1 + [int]$counts[$r.Dest] } }
    foreach ($r in $rows) {
        if ($r.Status -eq 'move' -and $counts[$r.Dest] -gt 1) {
            $r.Status = 'conflict'; $r.Note = 'two sources claim this path - resolve by hand'
        }
    }
    return $rows
}

function Show-TsWsPlan($Rows, [string]$Mode) {
    $root = Get-TsWsRoot
    ""
    "=============================================================================="
    " Workspace migration plan"
    " Root: $root"
    " Mode: $Mode"
    "=============================================================================="
    foreach ($tier in @('src', 'public', 'local', 'scratch')) {
        $pfx = (Join-Path $root $tier) + '\'
        $block = @($Rows | Where-Object {
            $_.Status -eq 'move' -and $_.Dest.StartsWith($pfx, [StringComparison]::OrdinalIgnoreCase) })
        if (-not $block.Count) { continue }
        ""
        "-- $tier --------------------------------------------------------------"
        foreach ($r in $block) {
            "   {0,-46} <- {1}" -f (Get-TsWsRelative $r.Dest $root), $r.Source
            if ($r.Note) { "      note: $($r.Note)" }
        }
    }
    $blocked = @($Rows | Where-Object { $_.Status -in @('conflict', 'blocked', 'runtime') })
    if ($blocked.Count) {
        ""
        "-- BLOCKED ------------------------------------------------------------"
        foreach ($r in $blocked) {
            "   {0,-46} {1}" -f (Split-Path -Leaf $r.Source), $r.Note
            "      at: $($r.Source)"
        }
        ""
        "   Resolve these by hand, then re-run. Nothing above was moved."
    }
    ""
    "{0} ready, {1} conflicted, {2} blocked, {3} already correct" -f `
        @($Rows | Where-Object { $_.Status -eq 'move' }).Count,
        @($Rows | Where-Object { $_.Status -eq 'conflict' }).Count,
        @($Rows | Where-Object { $_.Status -in @('blocked', 'runtime') }).Count,
        @($Rows | Where-Object { $_.Status -eq 'inplace' }).Count
    ""
}

# ----------------------------------------------------------------- migrate ----

function Invoke-TsWsMigrate([string[]]$Arguments) {
    $root = Get-TsWsRoot
    $fixRemotes = $false
    foreach ($a in $Arguments) {
        switch -Regex ($a) {
            '^--fix-remotes$' { $fixRemotes = $true }
            default { Write-Warning "wso migrate: unknown option: $a"; return }
        }
    }
    $rows = Get-TsWsPlan
    Show-TsWsPlan $rows 'EXECUTE'
    $moves = @($rows | Where-Object { $_.Status -eq 'move' })
    if (-not $moves.Count) { Write-TsWsInfo 'Nothing to move.'; return }
    if ($env:TS_DRY_RUN -eq '1') {
        Write-TsWsInfo "[dry-run] would move $($moves.Count) repo(s); nothing changed."; return
    }
    if (-not (Confirm-TsWs "Move $($moves.Count) repo(s)? Working trees, stashes and untracked files are preserved. [y/N]")) {
        Write-TsWsInfo 'Migration cancelled; nothing moved.'; return
    }
    $log = New-TsWsRunLog 'migrate'
    $moved = 0; $failed = 0
    foreach ($r in $moves) {
        if (Move-TsWsRepo $r.Source $r.Dest) {
            Write-TsWsInfo "moved $(Split-Path -Leaf $r.Source) -> $(Get-TsWsRelative $r.Dest (Get-TsWsRoot))"
            "moved`t$(ConvertTo-TsWsLogPath $r.Source $root)`t$(ConvertTo-TsWsLogPath $r.Dest $root)" | Add-Content -LiteralPath $log -Encoding utf8
            $moved++
            if ($fixRemotes) { Repair-TsWsRemote $r.Dest }
        } else {
            "failed`t$(ConvertTo-TsWsLogPath $r.Source $root)`t$(ConvertTo-TsWsLogPath $r.Dest $root)" | Add-Content -LiteralPath $log -Encoding utf8
            $failed++
        }
    }
    ""
    Write-TsWsInfo "$moved moved, $failed failed. Log: $log"
    Write-TsWsInfo 'Source roots were NOT deleted. Verify, then remove the empty ones by hand.'
}

# Rewrite origin to the configured scheme and canonical owner. Only touches
# owners you control; public/ clones keep whatever scheme upstream uses,
# because you have no push access there.
function Repair-TsWsRemote([string]$Dir) {
    $origin = Get-TsWsOrigin $Dir
    if (-not $origin) { return }
    $p = ConvertFrom-TsWsRemote $origin
    if (-not $p) { return }
    $canon = Get-TsWsCanonOwner $p.Owner
    $tier  = Get-TsWsTierForOwner $canon
    $scheme = if ($tier -eq 'src') { Get-TsWsSetting 'scheme_own' 'ssh' }
              else { Get-TsWsSetting 'scheme_public' 'preserve' }
    $want = New-TsWsRemoteUrl $scheme $p.Host $canon $p.Repo $origin
    if ($want -eq $origin) { return }
    if ($env:TS_DRY_RUN -eq '1') { Write-TsWsInfo "[dry-run] remote $origin -> $want"; return }
    & git -C $Dir remote set-url origin $want
    if ($LASTEXITCODE -eq 0) { Write-TsWsInfo "  remote: $origin -> $want" }
}

# -------------------------------------------------------------------- sync ----

# Fast-forward only, never on a dirty tree. A ff-only merge cannot destroy
# uncommitted work - it just refuses - so the skips are the output that matters.
function Sync-TsWsRepo([string]$Dir) {
    $root = Get-TsWsRoot
    $rel = Get-TsWsRelative $Dir $root
    $st = Get-TsWsGitState $Dir
    if (-not (Get-TsWsOrigin $Dir)) { "{0,-58} {1}" -f $rel, 'skipped (no remote)'; return }
    if ($st.Head -eq 'DETACHED')    { "{0,-58} {1}" -f $rel, 'skipped (detached HEAD)'; return }
    if ($st.Dirty -gt 0)            { "{0,-58} {1}" -f $rel, "skipped ($($st.Dirty) uncommitted)"; return }
    & git -C $Dir fetch --quiet --prune 2>$null
    if ($LASTEXITCODE -ne 0) { "{0,-58} {1}" -f $rel, 'FETCH FAILED'; return }
    $before = & git -C $Dir rev-parse HEAD 2>$null
    & git -C $Dir merge --ff-only --quiet '@{u}' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $after = & git -C $Dir rev-parse HEAD 2>$null
        if ($before -eq $after) {
            if ($env:TS_WS_VERBOSE -eq '1') { "{0,-58} {1}" -f $rel, 'up to date' }
        } else { "{0,-58} {1}" -f $rel, 'fast-forwarded' }
    } else {
        & git -C $Dir rev-parse '@{u}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { "{0,-58} {1}" -f $rel, 'SKIPPED (diverged - needs you)' }
        else { "{0,-58} {1}" -f $rel, 'skipped (no upstream)' }
    }
}

function Invoke-TsWsSync([string[]]$Arguments) {
    $org = ''
    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        switch -Regex ($Arguments[$i]) {
            '^--org$' { $org = $Arguments[$i + 1]; $i++ }
            default   { Write-Warning "wso sync: unknown option: $($Arguments[$i])"; return }
        }
    }
    foreach ($d in (Get-TsWsManagedRepos @('src', 'public', 'local'))) {
        if ($org -and $d -notmatch [regex]::Escape("\$org\")) { continue }
        Sync-TsWsRepo $d
    }
    Show-TsWsMissing
}

# What exists in your orgs but not on this machine. Reported, never cloned -
# putting 100 repos on a laptop is a decision, not a default.
function Show-TsWsMissing {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { return }
    $root = Get-TsWsRoot
    $hostName = Get-TsWsSetting 'host_default' 'github.com'
    $missing = 0
    foreach ($owner in (Get-TsWsOwnOwners)) {
        $names = & gh repo list $owner --limit 500 --json name -q '.[].name' 2>$null
        foreach ($r in $names) {
            if (-not $r) { continue }
            if (Test-Path -LiteralPath (Join-Path $root "src\$hostName\$owner\$r")) { continue }
            if (Test-Path -LiteralPath (Join-Path $root "archive\$hostName\$owner\$r")) { continue }
            $missing++
            if ($missing -le 20) { "   missing: $owner/$r" }
        }
    }
    if ($missing -gt 0) {
        "--"
        "$missing repo(s) in your orgs are not on this machine. 'wso synceverything' clones them."
    }
}

function Invoke-TsWsSyncEverything {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Warning 'wso: gh not found - needed to enumerate your orgs. See: wso doctor'; return
    }
    Invoke-TsWsSync @()
    $root = Get-TsWsRoot
    $hostName = Get-TsWsSetting 'host_default' 'github.com'
    $scheme = Get-TsWsSetting 'scheme_own' 'ssh'
    $cloned = 0
    foreach ($owner in (Get-TsWsOwnOwners)) {
        $names = & gh repo list $owner --limit 500 --json name -q '.[].name' 2>$null
        foreach ($r in $names) {
            if (-not $r) { continue }
            $dest = Join-Path $root "src\$hostName\$owner\$r"
            if (Test-Path -LiteralPath $dest) { continue }
            if (Test-Path -LiteralPath (Join-Path $root "archive\$hostName\$owner\$r")) { continue }
            if ($env:TS_DRY_RUN -eq '1') { Write-TsWsInfo "[dry-run] would clone $owner/$r"; continue }
            New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
            $url = New-TsWsRemoteUrl $scheme $hostName $owner $r ''
            & git clone --quiet $url $dest
            if ($LASTEXITCODE -eq 0) { Write-TsWsInfo "cloned $owner/$r"; $cloned++ }
            else { Write-TsWsWarn "failed to clone $owner/$r" }
        }
    }
    Write-TsWsInfo "$cloned cloned."
}

# --------------------------------------------------------------------- get ----

function Invoke-TsWsGet([string[]]$Arguments) {
    $spec = if ($Arguments.Count) { $Arguments[0] } else { '' }
    if (-not $spec) { Write-Warning 'usage: wso get <url|owner/repo>'; return }
    $root = Get-TsWsRoot
    $p = ConvertFrom-TsWsRemote $spec
    if ($p) { $hostName = $p.Host; $owner = $p.Owner; $repo = $p.Repo }
    elseif ($spec -match '^([^/]+)/([^/]+)$') {
        $hostName = Get-TsWsSetting 'host_default' 'github.com'
        $owner = $Matches[1]; $repo = $Matches[2]
    } else { Write-Warning "wso get: cannot parse '$spec' (expected a URL or owner/repo)"; return }
    $canon = Get-TsWsCanonOwner $owner
    $tier  = Get-TsWsTierForOwner $canon
    $dest  = Join-Path $root "$tier\$hostName\$($canon -replace '/','\')\$repo"
    if (Test-Path -LiteralPath $dest) { Write-TsWsInfo "already here: $dest"; return $dest }
    $scheme = if ($tier -eq 'src') { Get-TsWsSetting 'scheme_own' 'ssh' }
              else { Get-TsWsSetting 'scheme_public' 'preserve' }
    $url = New-TsWsRemoteUrl $scheme $hostName $canon $repo $spec
    if (-not $url) { $url = $spec }
    if ($env:TS_DRY_RUN -eq '1') { Write-TsWsInfo "[dry-run] would clone $url -> $dest"; return }
    New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
    & git clone $url $dest
    if ($LASTEXITCODE -eq 0) { return $dest }
}

# ----------------------------------------------------------------- orphans ----

function Invoke-TsWsOrphans([string[]]$Arguments) {
    $doPush = $false
    foreach ($a in $Arguments) {
        switch -Regex ($a) {
            '^--push$' { $doPush = $true }
            default { Write-Warning "wso orphans: unknown option: $a"; return }
        }
    }
    $root = Get-TsWsRoot
    $found = 0
    foreach ($d in (Get-TsWsAllRepos)) {
        if (Get-TsWsOrigin $d) { continue }
        $found++
        $commits = & git -C $d rev-list --all --count 2>$null
        $branches = (& git -C $d for-each-ref --format='%(refname:short)' refs/heads 2>$null) -join ' '
        "{0,-44} {1,6} commits   {2}" -f (Get-TsWsRelative $d $root), $commits, $branches
        if ($doPush) { Publish-TsWsOrphan $d }
    }
    if ($found -eq 0) {
        Write-TsWsInfo 'No repos without a remote. Nothing here exists on only one disk.'
    } else {
        "--"
        "$found repo(s) exist on this disk only. 'wso orphans --push' creates a private remote for each."
    }
}

# Creating a GitHub repo is outward-facing and not trivially undone, so this
# confirms per repo and shows authorship first: a large history with no remote
# is usually a clone whose origin was stripped, and that should not be pushed
# into a company org without a look.
function Publish-TsWsOrphan([string]$Dir) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-TsWsWarn 'gh not found; cannot create remotes.'; return
    }
    $name = Split-Path -Leaf $Dir
    ""
    Write-TsWsInfo $Dir
    $authors = (& git -C $Dir log --format='%ae' 2>$null | Sort-Object -Unique | Select-Object -First 5) -join ' '
    "     authors: $authors"
    $owner = Read-TsWsPrompt '     owner for this repo (blank = skip)'
    if (-not $owner) { '     skipped.'; return }
    if ($env:TS_DRY_RUN -eq '1') {
        Write-TsWsInfo "[dry-run] would run: gh repo create $owner/$name --private --source $Dir --push"; return
    }
    if (-not (Confirm-TsWs "     create PRIVATE $owner/$name and push all branches? [y/N]")) {
        '     skipped.'; return
    }
    Push-Location $Dir
    try {
        & gh repo create "$owner/$name" --private --source . --push
        if ($LASTEXITCODE -eq 0) { & git push --all; Write-TsWsInfo "pushed $owner/$name" }
    } finally { Pop-Location }
}

# ----------------------------------------------------------------- archive ----

function Invoke-TsWsArchive([string[]]$Arguments) {
    $root = Get-TsWsRoot
    $days = ''
    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        switch -Regex ($Arguments[$i]) {
            '^--days$' { $days = $Arguments[$i + 1]; $i++ }
            default { Write-Warning "wso archive: unknown option: $($Arguments[$i])"; return }
        }
    }
    $default = Get-TsWsSetting 'archive_days' '90'
    if (-not $days) { $days = $env:TS_WS_DAYS }
    if (-not $days) {
        $a = Read-TsWsPrompt "Archive repos untouched for how many days? [$default]"
        $days = if ($a) { $a } else { $default }
    }
    if ($days -notmatch '^\d+$') { Write-Warning "wso archive: --days needs a number, got '$days'"; return }
    $days = [int]$days

    Write-TsWsInfo "Scanning src/ for repos untouched for $days+ days..."
    $now = [DateTime]::UtcNow
    $items = @()
    foreach ($d in (Get-TsWsManagedRepos @('src'))) {
        $act = Get-TsWsLastActivity $d
        $age = if ($act) { [int]($now - $act).TotalDays } else { 99999 }
        if ($age -lt $days) { continue }
        $why = Get-TsWsUnsafeReason $d
        $when = if ($act) { $act.ToString('yyyy-MM-dd') } else { 'never' }
        $label = "last activity $when  (${age}d ago)"
        if ($why) { $label += "  - HELD: $why" }
        $items += [pscustomobject]@{ Path = $d; Label = $label; Ticked = (-not $why); Why = $why }
    }
    if (-not $items.Count) {
        Write-TsWsInfo "Nothing in src/ is older than $days days. That is the correct outcome most months."
        return
    }

    while ($true) {
        ""
        Write-TsWsInfo "Cold repos ($days+ days). Ticked ones will move to archive\:"
        for ($i = 0; $i -lt $items.Count; $i++) {
            $mark = if ($items[$i].Ticked) { 'x' } else { ' ' }
            "  [{0}] {1,2}) {2}" -f $mark, ($i + 1), (Get-TsWsRelative $items[$i].Path $root)
            "         $($items[$i].Label)"
        }
        "      HELD repos have uncommitted, unpushed or stashed work and cannot be ticked."
        $ans = Read-TsWsPrompt 'Toggle a number, [a]ll safe, [n]one, Enter to continue, [s]kip'
        if ($ans -eq '') { break }
        elseif ($ans -match '^[sS]$') { Write-TsWsInfo 'Archive skipped.'; return }
        elseif ($ans -match '^[aA]$') { foreach ($it in $items) { if (-not $it.Why) { $it.Ticked = $true } } }
        elseif ($ans -match '^([nN]|no|NO)$') { foreach ($it in $items) { $it.Ticked = $false } }
        elseif ($ans -match '^\d+$') {
            $idx = [int]$ans - 1
            if ($idx -ge 0 -and $idx -lt $items.Count) {
                if ($items[$idx].Why) {
                    "  ! $(Split-Path -Leaf $items[$idx].Path) is held: $($items[$idx].Why). Commit or push it first."
                } else { $items[$idx].Ticked = -not $items[$idx].Ticked }
            }
        } else { '  ? enter a number, a, n, s, or Enter' }
    }

    $sel = @($items | Where-Object { $_.Ticked })
    if (-not $sel.Count) { Write-TsWsInfo 'Nothing selected; nothing archived.'; return }
    if ($env:TS_DRY_RUN -eq '1') {
        Write-TsWsInfo "[dry-run] would archive $($sel.Count) repo(s):"
        foreach ($s in $sel) { "    $(Get-TsWsRelative $s.Path $root)" }
        return
    }
    if (-not (Confirm-TsWs "Archive $($sel.Count) repo(s)? They move to archive\ and can be restored with 'wso unarchive'. [y/N]")) {
        Write-TsWsInfo 'Cancelled; nothing archived.'; return
    }
    $log = New-TsWsRunLog 'archive'
    $srcPrefix = (Join-Path $root 'src') + '\'
    $n = 0
    foreach ($s in $sel) {
        # Re-check right before moving: the checklist may have been open a
        # while, and a repo can go dirty between the scan and the confirm.
        $why = Get-TsWsUnsafeReason $s.Path
        if ($why) { Write-TsWsWarn "$(Split-Path -Leaf $s.Path) became unsafe ($why); skipped."; continue }
        $rel = $s.Path.Substring($srcPrefix.Length)
        $dest = Join-Path $root "archive\$rel"
        if (Move-TsWsRepo $s.Path $dest) {
            Write-TsWsInfo "archived $(Get-TsWsRelative $s.Path $root) -> archive\$rel"
            "archived`t$(ConvertTo-TsWsLogPath $s.Path $root)`t$(ConvertTo-TsWsLogPath $dest $root)" | Add-Content -LiteralPath $log -Encoding utf8
            $n++
        }
    }
    Write-TsWsInfo "$n archived. Log: $log"
}

# --------------------------------------------------------------- unarchive ----

function Invoke-TsWsUnarchive([string[]]$Arguments) {
    $root = Get-TsWsRoot
    $mode = 'pick'; $name = ''; $org = ''; $update = $false
    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        # `break` per arm is load-bearing: switch -Regex without it runs EVERY
        # matching pattern, so "--undo-last" would also fall into the catch-all
        # "^-" arm and be rejected as unknown. Same convention as `doc`.
        switch -Regex ($Arguments[$i]) {
            '^--all$'        { $mode = 'all'; break }
            '^--undo-last$'  { $mode = 'undo'; break }
            '^--org$'        { $mode = 'org'; $org = $Arguments[$i + 1]; $i++; break }
            '^--update$'     { $update = $true; break }
            '^-'             { Write-Warning "wso unarchive: unknown option: $($Arguments[$i])"; return }
            default          { $mode = 'name'; $name = $Arguments[$i]; break }
        }
    }
    $archiveRoot = Join-Path $root 'archive'
    if (-not (Test-Path -LiteralPath $archiveRoot)) { Write-TsWsInfo 'Nothing archived on this machine.'; return }

    $picks = @()
    switch ($mode) {
        'undo' {
            $log = Get-TsWsLatestRunLog 'archive'
            if (-not $log) { Write-TsWsInfo 'No archive run to undo.'; return }
            Write-TsWsInfo "Reversing $log"
            foreach ($line in (Get-Content -LiteralPath $log | Select-Object -Skip 1)) {
                $f = $line -split "`t"
                # Logged relative and forward-slashed, so a run written by the
                # bash side on the same tree resolves here too.
                if ($f.Count -ge 3 -and $f[0] -eq 'archived') {
                    $abs = ConvertFrom-TsWsLogPath $f[2] $root
                    if (Test-Path -LiteralPath $abs) { $picks += $abs }
                }
            }
        }
        'all' { $picks = @(Get-TsWsManagedRepos @('archive')) }
        'org' { $picks = @(Get-TsWsManagedRepos @('archive') | Where-Object { $_ -match [regex]::Escape("\$org\") }) }
        'name'{ $picks = @(Get-TsWsManagedRepos @('archive') | Where-Object { (Split-Path -Leaf $_) -like "*$name*" }) }
        'pick' {
            if (-not (Get-Command fzf -ErrorAction SilentlyContinue)) {
                Write-Warning 'wso unarchive: fzf not installed - use "wso unarchive <name>" or --org/--all'; return
            }
            $prefix = $archiveRoot + '\'
            $sel = Get-TsWsManagedRepos @('archive') |
                   ForEach-Object { $_.Substring($prefix.Length) } |
                   fzf --multi --height 60% --reverse --prompt 'unarchive> ' --header 'TAB=select multiple, enter=restore'
            if (-not $sel) { return }
            $picks = @($sel | ForEach-Object { Join-Path $archiveRoot $_ })
        }
    }
    if (-not $picks.Count) { Write-TsWsInfo 'Nothing matched.'; return }
    Write-TsWsInfo "Restoring $($picks.Count) repo(s) to src\:"
    foreach ($p in $picks) { "    $(Get-TsWsRelative $p $root)" }
    if ($env:TS_DRY_RUN -eq '1') { Write-TsWsInfo '[dry-run] nothing moved.'; return }
    if (-not (Confirm-TsWs "Restore $($picks.Count) repo(s)? [y/N]")) { Write-TsWsInfo 'Cancelled.'; return }

    $prefix = $archiveRoot + '\'
    $n = 0
    foreach ($p in $picks) {
        $rel = $p.Substring($prefix.Length)
        $dest = Join-Path $root "src\$rel"
        if (Move-TsWsRepo $p $dest) {
            Write-TsWsInfo "restored src\$rel"; $n++
            if ($update) { Sync-TsWsRepo $dest }
        }
    }
    Write-TsWsInfo "$n restored."
}

# ---------------------------------------------------------------- identity ----

# Writes this machine's git rules. These cannot be tracked: the paths are
# machine-specific and the emails are personal, and neither may enter the
# source tree.
function Invoke-TsWsIdentity {
    $root = Get-TsWsRoot
    $gitdir = Join-Path $env:USERPROFILE '.config\git'
    New-Item -ItemType Directory -Path $gitdir -Force | Out-Null
    $out = Join-Path $gitdir 'terminal-stack-workspace.gitconfig'
    $hostName = Get-TsWsSetting 'host_default' 'github.com'
    # Forward slashes: git wants them in config on Windows too.
    $rootFwd = $root -replace '\\', '/'

    $lines = @(
        "# Generated by 'wso identity'. Per-machine - do not commit."
        "# Regenerate any time; your ~/.gitconfig is not touched beyond one include.path."
        ''
        '[ghq]'
        "  root = $rootFwd/public"
    )
    foreach ($owner in (Get-TsWsOwnOwners)) {
        $lines += "[ghq `"https://$hostName/$owner`"]"
        $lines += "  root = $rootFwd/src"
    }
    foreach ($owner in (Get-TsWsOwnOwners)) {
        $idf = Join-Path $gitdir "identity-$owner"
        $idfFwd = $idf -replace '\\', '/'
        $curName = ''; $curEmail = ''
        if (Test-Path -LiteralPath $idf) {
            $curName  = (& git config -f $idf user.name 2>$null)
            $curEmail = (& git config -f $idf user.email 2>$null)
        } else {
            $curName = (& git config --global user.name 2>$null)
        }
        ""
        Write-TsWsInfo "Identity for $owner"
        $n = Read-TsWsPrompt "  name  [$curName]";  if (-not $n) { $n = $curName }
        $e = Read-TsWsPrompt "  email [$curEmail]"; if (-not $e) { $e = $curEmail }
        $k = Read-TsWsPrompt '  signing key (blank = none)'
        if (-not $e) { Write-TsWsWarn "no email given for $owner; skipped."; continue }
        if (Test-Path -LiteralPath $idf) { Backup-TsWsFile $idf }
        $id = @("# Generated by 'wso identity' - per-machine, do not commit.", '[user]',
                "  name = $n", "  email = $e")
        if ($k) { $id += "  signingkey = $k" }
        $id | Set-Content -LiteralPath $idf -Encoding utf8
        Write-TsWsInfo "wrote $idf"
        $lines += ''
        $lines += "[includeIf `"gitdir:$rootFwd/src/$hostName/$owner/`"]"
        $lines += "  path = $idfFwd"
        $lines += "[includeIf `"gitdir:$rootFwd/archive/$hostName/$owner/`"]"
        $lines += "  path = $idfFwd"
    }
    if (Test-Path -LiteralPath $out) { Backup-TsWsFile $out }
    $lines | Set-Content -LiteralPath $out -Encoding utf8
    Write-TsWsInfo "wrote $out"
    $existing = & git config --global --get-all include.path 2>$null
    if ($existing -match 'terminal-stack-workspace\.gitconfig') {
        Write-TsWsInfo 'git include.path already set'
    } else {
        & git config --global --add include.path ($out -replace '\\', '/')
        Write-TsWsInfo "added git include.path -> $out"
    }
}

# Repo convention: <path>.bak.YYYYMMDD, then .1/.2 on a same-day re-run.
function Backup-TsWsFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $stamp = Get-Date -Format 'yyyyMMdd'
    $bak = "$Path.bak.$stamp"; $n = 1
    while (Test-Path -LiteralPath $bak) { $bak = "$Path.bak.$stamp.$n"; $n++ }
    Copy-Item -LiteralPath $Path -Destination $bak -Force
    Write-TsWsInfo "backed up $Path -> $bak"
}

# ------------------------------------------------------------------ doctor ----

function Invoke-TsWsDoctor {
    $root = Get-TsWsRoot
    $issues = 0
    Write-TsWsInfo 'Workspace'
    "  root            $root"
    foreach ($t in @('src', 'public', 'archive', 'local', 'scratch')) {
        $p = Join-Path $root $t
        if (Test-Path -LiteralPath $p) {
            "  {0,-15} {1} repo(s)" -f "$t\", @(Get-TsWsManagedRepos @($t)).Count
        } else { "  {0,-15} (not created yet)" -f "$t\" }
    }
    ""
    Write-TsWsInfo 'Config'
    foreach ($f in (Get-TsWsConfPaths)) { "  $f" }
    "  orgs            $((Get-TsWsOwnOwners) -join ' ')"
    $c = Get-TsWsConfig
    "  renames         $(($c.Renames.Keys | ForEach-Object { "$_=$($c.Renames[$_])" }) -join ' ')"
    "  archive_days    $(Get-TsWsSetting 'archive_days' '90')"
    "  scheme_own      $(Get-TsWsSetting 'scheme_own' 'ssh')"
    ""
    Write-TsWsInfo 'Tools'
    foreach ($t in @('git', 'gh', 'ghq', 'fzf', 'lazygit')) {
        $cmd = Get-Command $t -ErrorAction SilentlyContinue
        if ($cmd) { "  {0,-8} ok    {1}" -f $t, $cmd.Source }
        else { "  {0,-8} MISSING - install it: ts-config apps" -f $t; $issues++ }
    }
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        & gh auth status 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { '  gh auth  ok' }
        else { '  gh auth  NOT LOGGED IN - run: gh auth login'; $issues++ }
    }
    ""
    Write-TsWsInfo 'Git'
    $inc = & git config --global --get-all include.path 2>$null
    if ($inc -match 'terminal-stack-workspace\.gitconfig') { '  identity rules  ok' }
    else { '  identity rules  not installed - run: wso identity'; $issues++ }
    $ff = & git config --get pull.ff 2>$null
    "  pull.ff         $(if ($ff) { $ff } else { '(unset - expected "only")' })"
    ""
    if ($issues -eq 0) { Write-TsWsInfo 'All good.' } else { Write-TsWsWarn "$issues issue(s) found." }
}

# ---------------------------------------------------------------- dispatch ----

# Byte-identical to lines 2-19 of bootstrap/wso.sh, which that script prints for
# --help by self-extracting its own header. Change one, change the other.
function Show-TsWsHelp {
    @'
wso - workspace organizer. Keeps many repos across several GitHub owners in one
derivable tree, and makes bulk operations over them safe.

Usage:
  wso status [--dirty] [--org X]  what is dirty / unpushed / detached (read-only)
  wso plan                        preview the migration; never writes
  wso migrate [--fix-remotes]     execute it (moves only; asks first)
  wso sync [--org X]              fast-forward-only update of what is here
  wso synceverything              sync, then clone every missing org repo
  wso archive [--days N]          interactive: threshold, checklist, confirm
  wso unarchive [name|--org X|--all|--undo-last] [--update]
  wso get <url|owner/repo>        clone to the derived path
  wso orphans [--push]            repos with no remote (they exist on one disk)
  wso identity                    write this machine's git identity rules
  wso doctor                      tools, config and tree health

Layout is <root>/<tier>/<host>/<owner>/<repo>; see bootstrap/workspace.conf.
Honors TS_DRY_RUN=1 (preview only) everywhere that writes.
'@
}

function Invoke-Wso {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    if (-not (Get-TsWsRoot)) {
        Write-Warning 'wso: no workspace found - set $env:WORKSPACE_DIR in profile.local.ps1'
        return
    }
    $cmd  = if ($Arguments -and $Arguments.Count) { $Arguments[0] } else { '' }
    $rest = if ($Arguments -and $Arguments.Count -gt 1) { $Arguments[1..($Arguments.Count - 1)] } else { @() }
    switch -Regex ($cmd) {
        '^$'               { Invoke-TsWsStatus @(); break }
        '^status$'         { Invoke-TsWsStatus $rest; break }
        '^plan$'           { Show-TsWsPlan (Get-TsWsPlan) 'DRY RUN - nothing is moved'; break }
        '^migrate$'        { Invoke-TsWsMigrate $rest; break }
        '^sync$'           { Invoke-TsWsSync $rest; break }
        '^synceverything$' { Invoke-TsWsSyncEverything; break }
        '^archive$'        { Invoke-TsWsArchive $rest; break }
        '^unarchive$'      { Invoke-TsWsUnarchive $rest; break }
        '^get$'            { Invoke-TsWsGet $rest; break }
        '^orphans$'        { Invoke-TsWsOrphans $rest; break }
        '^identity$'       { Invoke-TsWsIdentity; break }
        '^doctor$'         { Invoke-TsWsDoctor; break }
        '^(-h|--help|help)$' { Show-TsWsHelp; break }
        default { Write-Warning "wso: unknown command '$cmd' (try: status, plan, migrate, sync, archive, unarchive, get, orphans, identity, doctor, --help)"; break }
    }
}
