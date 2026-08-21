# _merge_json_settings.ps1 — the JSONC key-splice engine behind every settings
# file this stack part-owns. Dot-sourced by _merge_cursor_settings.ps1 and
# _merge_claude_settings.ps1; it never acts on its own.
#
# The live file is edited TEXTUALLY, one top-level key at a time. Re-serialising
# the whole file (ConvertTo-Json) would delete every // comment the user wrote and
# reflow their formatting, so we splice values into the raw text instead and leave
# every byte we do not own untouched. That is also what lets a file the stack only
# part-owns keep the keys its own app writes (Claude Code's `model`,
# `enabledPlugins`, `permissions`, `env`, …) across a sync.

function Get-TsBackupPath([string]$dst, [string]$stamp) {
    $bak = "$dst.bak.$stamp"
    if (-not (Test-Path -LiteralPath $bak)) { return $bak }
    $n = 1
    while (Test-Path -LiteralPath "$dst.bak.$stamp.$n") { $n++ }
    return "$dst.bak.$stamp.$n"
}

function ConvertTo-TsJsonStringBody([string]$s) {
    # Escape for embedding inside a JSON string literal (backslash first).
    # The replacement is a literal 2-backslash string: the regex '\\' matches ONE
    # backslash, and backslash carries no special meaning in a .NET replacement.
    return ($s -replace '\\', '\\' -replace '"', '\"')
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

function Read-TsJsonObject([string]$path, [string]$text, [string]$label = 'merge-settings') {
    if ([string]::IsNullOrWhiteSpace($text)) { return [ordered]@{} }
    try {
        # -AsHashtable keeps key order (PS 7.3+) and avoids PSObject-wrapping every
        # scalar, which is what made an earlier converter eat JSON arrays.
        return ConvertFrom-Json $text -AsHashtable
    } catch {
        Write-Warning "${label}: could not parse $path ($($_.Exception.Message)); skipping merge."
        return $null
    }
}

# ---- entry point ------------------------------------------------------------

function Merge-TsJsonSettings {
    # Splice every top-level key of $FragmentPath into $LivePath, leaving all other
    # keys — and all formatting and comments — exactly as they were. Backs the live
    # file up as .bak.yyyyMMdd[.N] before writing, and refuses to write at all if the
    # spliced result no longer parses or would disturb a key the fragment does not own.
    #
    # $FragmentText lets a caller pass fragment text it has already token-expanded
    # (or rendered) rather than have this re-read the file from disk.
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FragmentPath,
        [Parameter(Mandatory)][string]$LivePath,
        [string]$FragmentText,
        [string]$Label = 'merge-settings'
    )

    if (-not (Test-Path -LiteralPath $FragmentPath -PathType Leaf)) {
        Write-Warning "${Label}: fragment not found: $FragmentPath; skipping."
        return
    }
    $fragText = if ($PSBoundParameters.ContainsKey('FragmentText')) {
        $FragmentText
    } else {
        Get-Content -LiteralPath $FragmentPath -Raw -Encoding UTF8
    }

    $fragment = Read-TsJsonObject $FragmentPath $fragText $Label
    if ($null -eq $fragment) { return }
    if ($fragment.Count -eq 0) {
        Write-Warning "${Label}: fragment is empty; skipping."
        return
    }

    $liveText = if (Test-Path -LiteralPath $LivePath) {
        Get-Content -LiteralPath $LivePath -Raw -Encoding UTF8
    } else { '{}' }
    if ([string]::IsNullOrWhiteSpace($liveText)) { $liveText = '{}' }
    $live = Read-TsJsonObject $LivePath $liveText $Label
    if ($null -eq $live) { return }

    $newText = $liveText
    $changed = @()
    foreach ($key in @($fragment.Keys)) {
        $want = ConvertTo-TsCanonicalJson $fragment[$key]
        $have = if ($live.Contains($key)) { ConvertTo-TsCanonicalJson $live[$key] } else { $null }
        if ($want -eq $have) { continue }
        $span = Find-TsTopLevelKey $fragText $key
        if (-not $span) {
            Write-Warning "${Label}: could not locate '$key' in the fragment; skipping that key."
            continue
        }
        $valueText = $fragText.Substring($span.ValueStart, $span.ValueEnd - $span.ValueStart)
        $spliced = Set-TsTopLevelKey $newText $key $valueText
        if ($null -eq $spliced) {
            Write-Warning "${Label}: $LivePath is not a JSON object; skipping merge."
            return
        }
        $newText = $spliced
        $changed += $key
    }

    if ($changed.Count -eq 0) {
        Write-Host "${Label}: $LivePath already up to date"
        return
    }

    # Never write something we cannot read back: a splice bug must not cost the
    # user their settings file.
    $verify = try { ConvertFrom-Json $newText -AsHashtable } catch { $null }
    if ($null -eq $verify) {
        Write-Warning "${Label}: merged result is not valid JSON; leaving $LivePath untouched."
        return
    }
    foreach ($key in @($fragment.Keys)) {
        if (-not $verify.Contains($key)) {
            Write-Warning "${Label}: post-merge check lost '$key'; leaving $LivePath untouched."
            return
        }
        if ((ConvertTo-TsCanonicalJson $verify[$key]) -ne (ConvertTo-TsCanonicalJson $fragment[$key])) {
            Write-Warning "${Label}: post-merge check failed for '$key'; leaving $LivePath untouched."
            return
        }
    }
    # Every pre-existing key the stack does not own must survive byte-comparable.
    foreach ($key in @($live.Keys)) {
        if ($fragment.Contains($key)) { continue }
        if (-not $verify.Contains($key) -or
            (ConvertTo-TsCanonicalJson $verify[$key]) -ne (ConvertTo-TsCanonicalJson $live[$key])) {
            Write-Warning "${Label}: merge would alter unrelated key '$key'; leaving $LivePath untouched."
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
        Write-Host "${Label}: backup $bak"
    }

    Set-Content -LiteralPath $LivePath -Value $newText -Encoding utf8 -NoNewline
    Write-Host "${Label}: updated $LivePath ($($changed -join ', '))"
}
