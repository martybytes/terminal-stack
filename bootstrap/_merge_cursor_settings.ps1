# _merge_cursor_settings.ps1 — shallow-merge stack-owned Cursor IDE terminal keys
# from windows\AppData\Roaming\Cursor\User\terminal-stack.terminal.json
# into %APPDATA%\Cursor\User\settings.json (backup before write).
# Invoked by scripts\sync-windows.ps1 and run_after_90-sync-windows.sh.
#
# The live file is edited TEXTUALLY, one top-level key at a time. Re-serialising
# the whole file (ConvertTo-Json) would delete every // comment the user wrote and
# reflow their formatting, so we splice values into the raw text instead and leave
# every byte we do not own untouched.

function Get-TsBackupPath([string]$dst, [string]$stamp) {
    $bak = "$dst.bak.$stamp"
    if (-not (Test-Path -LiteralPath $bak)) { return $bak }
    $n = 1
    while (Test-Path -LiteralPath "$dst.bak.$stamp.$n") { $n++ }
    return "$dst.bak.$stamp.$n"
}

# ---- environment resolution ------------------------------------------------
# The fragment ships __TOKEN__ placeholders rather than literal paths: pwsh may be
# under Program Files, Program Files (x86), or a per-user winget/Store install in
# %LOCALAPPDATA%\Microsoft\WindowsApps, and Git may be per-user too.

function Resolve-TsPwshPath {
    $cmd = Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($p in @(
        (Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'),
        (Join-Path $env:ProgramFiles 'PowerShell\7-preview\pwsh.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'PowerShell\7\pwsh.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\pwsh.exe')
    )) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return 'pwsh.exe'   # last resort: rely on PATH
}

function Resolve-TsGitCmdDir {
    # Prefer <install root>/cmd. Get-Command often finds git.exe in mingw64/bin,
    # which is the wrong thing to put on PATH: it is full of MSYS DLLs and ships a
    # curl.exe that shadows Windows' own System32/curl.exe. <root>/cmd holds just
    # git/gitk/git-lfs/scalar and is the directory Git for Windows means for PATH.
    $cmd = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) {
        $probe = Split-Path -Parent $cmd.Source
        for ($i = 0; $i -lt 3 -and $probe; $i++) {
            $candidate = Join-Path $probe 'cmd'
            if (Test-Path -LiteralPath (Join-Path $candidate 'git.exe')) { return $candidate }
            $probe = Split-Path -Parent $probe
        }
        return (Split-Path -Parent $cmd.Source)   # non-standard layout: use what we found
    }
    foreach ($p in @(
        (Join-Path $env:ProgramFiles 'Git\cmd'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\cmd'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd')
    )) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

function ConvertTo-TsJsonStringBody([string]$s) {
    # Escape for embedding inside a JSON string literal (backslash first).
    # The replacement is a literal 2-backslash string: the regex '\\' matches ONE
    # backslash, and backslash carries no special meaning in a .NET replacement.
    return ($s -replace '\\', '\\' -replace '"', '\"')
}

function Expand-TsFragmentTokens([string]$text) {
    $text = $text -replace '__PWSH_EXE__', (ConvertTo-TsJsonStringBody (Resolve-TsPwshPath))
    $gitDir = Resolve-TsGitCmdDir
    if ($gitDir) {
        return $text -replace '__GIT_CMD_DIR__', (ConvertTo-TsJsonStringBody $gitDir)
    }
    # No Git found: drop the prefix and its separator rather than emit ";${env:Path}".
    return ($text -replace '__GIT_CMD_DIR__;', '') -replace '__GIT_CMD_DIR__', ''
}

# ---- JSONC-aware text scanning ---------------------------------------------
# PowerShell 7's ConvertFrom-Json (Newtonsoft) already tolerates // and /* */
# comments, so we never strip them; these helpers find the exact span of a
# top-level key's value so it can be replaced in place.

function Get-TsStringEnd([string]$t, [int]$i) {
    # $i is the opening quote; returns the index just past the closing quote.
    $i++
    while ($i -lt $t.Length) {
        if ($t[$i] -eq '\') { $i += 2; continue }
        if ($t[$i] -eq '"') { return $i + 1 }
        $i++
    }
    return $i
}

function Get-TsTriviaEnd([string]$t, [int]$i) {
    # Skip whitespace and // or /* */ comments.
    while ($i -lt $t.Length) {
        $c = $t[$i]
        if ([char]::IsWhiteSpace($c)) { $i++; continue }
        if ($c -eq '/' -and ($i + 1) -lt $t.Length) {
            if ($t[$i + 1] -eq '/') {
                while ($i -lt $t.Length -and $t[$i] -ne "`n") { $i++ }
                continue
            }
            if ($t[$i + 1] -eq '*') {
                $i += 2
                while (($i + 1) -lt $t.Length -and -not ($t[$i] -eq '*' -and $t[$i + 1] -eq '/')) { $i++ }
                $i += 2
                continue
            }
        }
        break
    }
    return $i
}

function Get-TsValueEnd([string]$t, [int]$i) {
    # $i is the first char of a value; returns the index just past it.
    $c = $t[$i]
    if ($c -eq '"') { return Get-TsStringEnd $t $i }
    if ($c -eq '{' -or $c -eq '[') {
        $depth = 0
        while ($i -lt $t.Length) {
            $ch = $t[$i]
            if ($ch -eq '"') { $i = Get-TsStringEnd $t $i; continue }
            if ($ch -eq '/' -and ($i + 1) -lt $t.Length -and ($t[$i + 1] -eq '/' -or $t[$i + 1] -eq '*')) {
                $i = Get-TsTriviaEnd $t $i; continue
            }
            if ($ch -eq '{' -or $ch -eq '[') { $depth++ }
            elseif ($ch -eq '}' -or $ch -eq ']') {
                $depth--
                if ($depth -le 0) { return $i + 1 }
            }
            $i++
        }
        return $i
    }
    while ($i -lt $t.Length -and $t[$i] -notmatch '[,}\]\s]') { $i++ }
    return $i
}

function Find-TsTopLevelKey([string]$t, [string]$key) {
    $i = Get-TsTriviaEnd $t 0
    if ($i -ge $t.Length -or $t[$i] -ne '{') { return $null }
    $i++
    while ($true) {
        $i = Get-TsTriviaEnd $t $i
        if ($i -ge $t.Length -or $t[$i] -eq '}') { return $null }
        if ($t[$i] -eq ',') { $i++; continue }
        if ($t[$i] -ne '"') { return $null }
        $ks = $i
        $ke = Get-TsStringEnd $t $i
        $name = $t.Substring($ks + 1, $ke - $ks - 2) -replace '\\"', '"' -replace '\\\\', '\'
        $i = Get-TsTriviaEnd $t $ke
        if ($i -ge $t.Length -or $t[$i] -ne ':') { return $null }
        $i = Get-TsTriviaEnd $t ($i + 1)
        if ($i -ge $t.Length) { return $null }
        $vs = $i
        $ve = Get-TsValueEnd $t $i
        if ($name -eq $key) {
            return [pscustomobject]@{ KeyStart = $ks; ValueStart = $vs; ValueEnd = $ve }
        }
        $i = $ve
    }
}

function Set-TsTopLevelKey([string]$t, [string]$key, [string]$valueText) {
    $nl = if ($t -match "`r`n") { "`r`n" } else { "`n" }
    # The fragment authors its value at the same nesting depth a top-level key sits
    # at in the destination, so it splices in as-is; re-indenting would double it.
    $value = $valueText
    $span = Find-TsTopLevelKey $t $key
    if ($span) {
        return $t.Substring(0, $span.ValueStart) + $value + $t.Substring($span.ValueEnd)
    }
    $close = $t.LastIndexOf('}')
    if ($close -lt 0) { return $null }
    $before = $t.Substring(0, $close).TrimEnd()
    $sep = if ($before.EndsWith('{')) { '' } else { ',' }
    $keyJson = '"' + (ConvertTo-TsJsonStringBody $key) + '"'
    return $before + $sep + $nl + '  ' + $keyJson + ': ' + $value + $nl + $t.Substring($close)
}

# ---- comparison -------------------------------------------------------------

function ConvertTo-TsCanonicalJson($v) {
    # Order-insensitive canonical form, so an equal-but-reordered object does not
    # look "changed" and trigger a pointless rewrite on every sync.
    if ($null -eq $v) { return 'null' }
    if ($v -is [System.Collections.IDictionary]) {
        $parts = @()
        foreach ($k in ($v.Keys | Sort-Object)) {
            $parts += (ConvertTo-Json ([string]$k) -Compress) + ':' + (ConvertTo-TsCanonicalJson $v[$k])
        }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [System.Collections.IEnumerable] -and $v -isnot [string]) {
        $parts = @()
        foreach ($e in $v) { $parts += (ConvertTo-TsCanonicalJson $e) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-Json $v -Compress)
}

function Read-TsJsonObject([string]$path, [string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return [ordered]@{} }
    try {
        # -AsHashtable keeps key order (PS 7.3+) and avoids PSObject-wrapping every
        # scalar, which is what made an earlier converter eat JSON arrays.
        return ConvertFrom-Json $text -AsHashtable
    } catch {
        Write-Warning "merge-cursor-settings: could not parse $path ($($_.Exception.Message)); skipping merge."
        return $null
    }
}

# ---- entry point ------------------------------------------------------------

function Merge-TsCursorSettings {
    [CmdletBinding()]
    param(
        [string]$FragmentPath,
        [string]$LivePath
    )

    if (-not $FragmentPath) {
        # Prefer the repo copy next to this script: %APPDATA% can be redirected
        # (roaming profile / OneDrive KFM) away from %USERPROFILE%\AppData\Roaming,
        # which would leave the mirrored fragment somewhere we never look.
        $candidates = @()
        if ($PSScriptRoot) {
            $candidates += (Join-Path $PSScriptRoot '..\windows\AppData\Roaming\Cursor\User\terminal-stack.terminal.json')
        }
        if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA 'Cursor\User\terminal-stack.terminal.json') }
        if ($env:USERPROFILE) { $candidates += (Join-Path $env:USERPROFILE 'AppData\Roaming\Cursor\User\terminal-stack.terminal.json') }
        foreach ($c in $candidates) {
            if (Test-Path -LiteralPath $c) { $FragmentPath = (Resolve-Path -LiteralPath $c).Path; break }
        }
    }
    if (-not $FragmentPath -or -not (Test-Path -LiteralPath $FragmentPath)) {
        Write-Warning 'merge-cursor-settings: fragment not found; skipping.'
        return
    }

    if (-not $LivePath) {
        $appData = $env:APPDATA
        if (-not $appData) {
            Write-Warning 'merge-cursor-settings: $env:APPDATA is unset; skipping.'
            return
        }
        # Only touch Cursor if Cursor is actually installed — otherwise we would
        # manufacture a phantom %APPDATA%\Cursor\User profile on every apply.
        $cursorRoot = Join-Path $appData 'Cursor'
        if (-not (Test-Path -LiteralPath $cursorRoot -PathType Container)) {
            Write-Host 'merge-cursor-settings: Cursor not installed; skipping.'
            return
        }
        $LivePath = Join-Path $appData 'Cursor\User\settings.json'
    }

    $fragText = Expand-TsFragmentTokens (Get-Content -LiteralPath $FragmentPath -Raw -Encoding UTF8)
    $fragment = Read-TsJsonObject $FragmentPath $fragText
    if ($null -eq $fragment) { return }
    if ($fragment.Count -eq 0) {
        Write-Warning 'merge-cursor-settings: fragment is empty; skipping.'
        return
    }

    $liveText = if (Test-Path -LiteralPath $LivePath) {
        Get-Content -LiteralPath $LivePath -Raw -Encoding UTF8
    } else { '{}' }
    if ([string]::IsNullOrWhiteSpace($liveText)) { $liveText = '{}' }
    $live = Read-TsJsonObject $LivePath $liveText
    if ($null -eq $live) { return }

    $newText = $liveText
    $changed = @()
    foreach ($key in @($fragment.Keys)) {
        $want = ConvertTo-TsCanonicalJson $fragment[$key]
        $have = if ($live.Contains($key)) { ConvertTo-TsCanonicalJson $live[$key] } else { $null }
        if ($want -eq $have) { continue }
        $span = Find-TsTopLevelKey $fragText $key
        if (-not $span) {
            Write-Warning "merge-cursor-settings: could not locate '$key' in the fragment; skipping that key."
            continue
        }
        $valueText = $fragText.Substring($span.ValueStart, $span.ValueEnd - $span.ValueStart)
        $spliced = Set-TsTopLevelKey $newText $key $valueText
        if ($null -eq $spliced) {
            Write-Warning "merge-cursor-settings: $LivePath is not a JSON object; skipping merge."
            return
        }
        $newText = $spliced
        $changed += $key
    }

    if ($changed.Count -eq 0) {
        Write-Host "merge-cursor-settings: $LivePath already up to date"
        return
    }

    # Never write something we cannot read back: a splice bug must not cost the
    # user their settings file.
    $verify = try { ConvertFrom-Json $newText -AsHashtable } catch { $null }
    if ($null -eq $verify) {
        Write-Warning "merge-cursor-settings: merged result is not valid JSON; leaving $LivePath untouched."
        return
    }
    foreach ($key in @($fragment.Keys)) {
        if (-not $verify.Contains($key)) {
            Write-Warning "merge-cursor-settings: post-merge check lost '$key'; leaving $LivePath untouched."
            return
        }
        if ((ConvertTo-TsCanonicalJson $verify[$key]) -ne (ConvertTo-TsCanonicalJson $fragment[$key])) {
            Write-Warning "merge-cursor-settings: post-merge check failed for '$key'; leaving $LivePath untouched."
            return
        }
    }
    # Every pre-existing key the stack does not own must survive byte-comparable.
    foreach ($key in @($live.Keys)) {
        if ($fragment.Contains($key)) { continue }
        if (-not $verify.Contains($key) -or
            (ConvertTo-TsCanonicalJson $verify[$key]) -ne (ConvertTo-TsCanonicalJson $live[$key])) {
            Write-Warning "merge-cursor-settings: merge would alter unrelated key '$key'; leaving $LivePath untouched."
            return
        }
    }

    $liveDir = Split-Path -Parent $LivePath
    if (-not (Test-Path -LiteralPath $liveDir -PathType Container)) {
        New-Item -ItemType Directory -Path $liveDir -Force | Out-Null
    }

    if (Test-Path -LiteralPath $LivePath) {
        $stamp = Get-Date -Format 'yyyyMMdd'
        $bak = Get-TsBackupPath -dst $LivePath -stamp $stamp
        Copy-Item -LiteralPath $LivePath -Destination $bak -Force
        Write-Host "merge-cursor-settings: backup $bak"
    }

    Set-Content -LiteralPath $LivePath -Value $newText -Encoding utf8 -NoNewline
    Write-Host "merge-cursor-settings: updated $LivePath ($($changed -join ', '))"
}

if ($MyInvocation.InvocationName -ne '.') {
    Merge-TsCursorSettings @args
}
