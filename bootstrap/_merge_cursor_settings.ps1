# _merge_cursor_settings.ps1 — shallow-merge stack-owned Cursor IDE terminal keys
# from %USERPROFILE%\AppData\Roaming\Cursor\User\terminal-stack.terminal.json
# into %APPDATA%\Cursor\User\settings.json (backup before write).
# Invoked by scripts\sync-windows.ps1 and run_after_90-sync-windows.sh.

function Get-TsBackupPath([string]$dst, [string]$stamp) {
    $bak = "$dst.bak.$stamp"
    if (-not (Test-Path -LiteralPath $bak)) { return $bak }
    $n = 1
    while (Test-Path -LiteralPath "$dst.bak.$stamp.$n") { $n++ }
    return "$dst.bak.$stamp.$n"
}

function ConvertTo-TsOrderedHashtable($InputObject) {
    if ($null -eq $InputObject) { return $null }
    if ($InputObject -is [System.Collections.IDictionary]) {
        $ht = [ordered]@{}
        foreach ($key in $InputObject.Keys) {
            $ht[$key] = ConvertTo-TsOrderedHashtable $InputObject[$key]
        }
        return $ht
    }
    # Must be [System.Management.Automation.PSCustomObject], NOT the [pscustomobject]
    # accelerator: that resolves to PSObject, which matches every pipeline-wrapped value.
    # With the accelerator, array elements matched here and were replaced by their property
    # bag ("solo" -> {"Length":4}, 120 -> {}), destroying every array in the file.
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $ht = [ordered]@{}
        foreach ($prop in $InputObject.PSObject.Properties) {
            $ht[$prop.Name] = ConvertTo-TsOrderedHashtable $prop.Value
        }
        return $ht
    }
    if ($InputObject -is [System.Collections.IEnumerable] -and $InputObject -isnot [string]) {
        # foreach (not ForEach-Object) so elements are not PSObject-wrapped; the leading
        # comma on the return survives PowerShell's unrolling, which otherwise turns
        # [] into $null and [x] into a bare scalar.
        $out = @()
        foreach ($item in $InputObject) { $out += ,(ConvertTo-TsOrderedHashtable $item) }
        return ,$out
    }
    return $InputObject
}

function Read-TsJsonObject([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return [ordered]@{} }
    $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) { return [ordered]@{} }
    # VS Code/Cursor settings.json may contain // comments — strip whole-line comments.
    $lines = $raw -split "`r?`n" | Where-Object { $_ -notmatch '^\s*//' }
    $stripped = $lines -join "`n"
    try {
        return ConvertTo-TsOrderedHashtable (ConvertFrom-Json $stripped)
    } catch {
        Write-Warning "merge-cursor-settings: could not parse $path ($($_.Exception.Message)); skipping merge."
        return $null
    }
}

function Merge-TsCursorSettings {
    [CmdletBinding()]
    param(
        [string]$FragmentPath,
        [string]$LivePath
    )

    if (-not $FragmentPath) {
        $FragmentPath = Join-Path $env:USERPROFILE 'AppData\Roaming\Cursor\User\terminal-stack.terminal.json'
    }
    if (-not $LivePath) {
        $appData = $env:APPDATA
        if (-not $appData) {
            Write-Warning 'merge-cursor-settings: $env:APPDATA is unset; skipping.'
            return
        }
        $LivePath = Join-Path $appData 'Cursor\User\settings.json'
    }

    if (-not (Test-Path -LiteralPath $FragmentPath)) {
        Write-Warning "merge-cursor-settings: fragment not found at $FragmentPath; skipping."
        return
    }

    $fragment = Read-TsJsonObject $FragmentPath
    if ($null -eq $fragment) { return }
    if ($fragment.Count -eq 0) {
        Write-Warning 'merge-cursor-settings: fragment is empty; skipping.'
        return
    }

    $live = Read-TsJsonObject $LivePath
    if ($null -eq $live) { return }

    $changed = $false
    foreach ($key in @($fragment.Keys)) {
        $fragVal = $fragment[$key]
        $liveVal = if ($live.Contains($key)) { $live[$key] } else { $null }
        $fragJson = ($fragVal | ConvertTo-Json -Depth 20 -Compress)
        $liveJson = if ($null -ne $liveVal) { ($liveVal | ConvertTo-Json -Depth 20 -Compress) } else { '' }
        if ($fragJson -ne $liveJson) {
            $live[$key] = $fragVal
            $changed = $true
        }
    }

    if (-not $changed) {
        Write-Host "merge-cursor-settings: $LivePath already up to date"
        return
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

    ($live | ConvertTo-Json -Depth 20) + "`n" | Set-Content -LiteralPath $LivePath -Encoding utf8 -NoNewline
    Write-Host "merge-cursor-settings: updated $LivePath"
}

if ($MyInvocation.InvocationName -ne '.') {
    Merge-TsCursorSettings @args
}
