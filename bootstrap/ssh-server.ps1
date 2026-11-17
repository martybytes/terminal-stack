# ssh-server.ps1 -- the ELEVATED half of `tstack ssh setup` (Windows sshd).
#
# Takes a plan file written by tstack/ssh.py and nothing else: no free-form
# commands, so the one script the stack runs as admin executes data, not code.
# Writes a result JSON the caller reports from. Idempotent: re-running a plan
# that is already in place changes nothing but the service state.
#
# Order is the safety:
#   1. install OpenSSH Server if missing, and make sure sshd_config exists
#   2. back up sshd_config, splice the managed block in FIRST (sshd keeps the
#      first value it reads), and `sshd -t` it; a failing config is rolled back
#   3. keys (admin file only when sshd reads it), DefaultShell = pwsh, services
#   4. firewall: replace our managed rules; disable (never delete) other rules
#      for the same ports so the chosen scope is the one in force
#   5. restart sshd, prove a key login on the new port, and only THEN switch
#      passwords off -- the answer that cannot lock you out
# docs/kb/windows/ssh-server.md; docs/decisions.md "SSH server".

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Result
)

$ErrorActionPreference = 'Stop'
$steps = [System.Collections.Generic.List[object]]::new()
function Add-TsStep([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $steps.Add([ordered]@{ name = $Name; ok = $Ok; detail = $Detail })
    $mark = if ($Ok) { 'ok  ' } else { 'FAIL' }
    Write-Host ("  {0}  {1}{2}" -f $mark, $Name, $(if ($Detail) { ": $Detail" } else { '' }))
}
function Save-TsResult([bool]$Ok) {
    [ordered]@{ ok = $Ok; steps = $steps } | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $Result -Encoding UTF8
}
# Twin of tstack/ssh.py backup(): .bak.YYYYMMDD, then .1, .2 -- never clobber.
function Backup-TsFile([string]$Path) {
    $stem = "$Path.bak.$(Get-Date -Format yyyyMMdd)"
    $target = $stem; $n = 0
    while (Test-Path -LiteralPath $target) { $n++; $target = "$stem.$n" }
    Copy-Item -LiteralPath $Path -Destination $target
    return $target
}

$p = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
$sshDir = Join-Path $env:ProgramData 'ssh'
$config = Join-Path $sshDir 'sshd_config'
$sshd = Join-Path $env:SystemRoot 'System32\OpenSSH\sshd.exe'
$startMarker = '# ---- terminal-stack-start'
$endMarker = '# ---- terminal-stack-end ----'

function Set-TsBlock([string]$Block) {
    $text = if (Test-Path -LiteralPath $config) { Get-Content -LiteralPath $config -Raw } else { '' }
    $lines = $text -split "`r?`n"
    $start = [array]::FindIndex($lines, [Predicate[string]] { param($l) $l.StartsWith($startMarker) })
    $end = [array]::FindIndex($lines, [Predicate[string]] { param($l) $l.StartsWith($endMarker) })
    $blockLines = ($Block.TrimEnd("`n") -split "`n")
    if ($start -ge 0 -and $end -ge $start) {
        $before = if ($start -gt 0) { $lines[0..($start - 1)] } else { @() }
        $after = if ($end + 1 -lt $lines.Count) { $lines[($end + 1)..($lines.Count - 1)] } else { @() }
    } else {
        $before = @(); $after = $lines
    }
    # Port is ADDITIVE: every Port line is another listener, so the block cannot
    # win by coming first. The user's own Port lines are commented out, tagged.
    # Twin of splice_block in tstack/ssh.py.
    $fix = { param($l) if ($l -match '^\s*Port\s+\S') { '# terminal-stack disabled: ' + $l.TrimStart() } else { $l } }
    $new = @(@($before) | ForEach-Object { & $fix $_ }) + $blockLines + @(@($after) | ForEach-Object { & $fix $_ })
    # sshd on Windows reads CRLF or LF; keep the file's own convention (CRLF as shipped).
    Set-Content -LiteralPath $config -Value (($new -join "`r`n").TrimEnd("`r`n") + "`r`n") -NoNewline -Encoding ascii
}

try {
  if ($p.windows) {
    # 1. OpenSSH Server ---------------------------------------------------------
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
        Add-WindowsCapability -Online -Name $cap.Name | Out-Null
        Add-TsStep 'install OpenSSH Server' $true $cap.Name
    } else {
        Add-TsStep 'OpenSSH Server installed' $true
    }
    if (-not (Test-Path -LiteralPath $config)) {
        # sshd writes its default config on first start.
        Start-Service sshd; Stop-Service sshd
        if (-not (Test-Path -LiteralPath $config)) {
            Copy-Item (Join-Path $env:SystemRoot 'System32\OpenSSH\sshd_config_default') $config
        }
    }

    # 2. sshd_config ------------------------------------------------------------
    $bak = Backup-TsFile $config
    Set-TsBlock $p.sshd_block
    $test = & $sshd -t 2>&1
    if ($LASTEXITCODE -ne 0) {
        Copy-Item -LiteralPath $bak -Destination $config -Force
        Add-TsStep 'sshd_config' $false "sshd -t refused it, restored the backup: $test"
        Save-TsResult $false; exit 1
    }
    Add-TsStep 'sshd_config managed block' $true "backup: $bak"

    # 3. keys, shell, services --------------------------------------------------
    if ($p.admin_keys_active -and $p.admin_keys.Count -gt 0) {
        $adminKeys = Join-Path $sshDir 'administrators_authorized_keys'
        $existing = if (Test-Path -LiteralPath $adminKeys) { Get-Content -LiteralPath $adminKeys } else { @() }
        $blobs = @($existing | ForEach-Object { ($_ -split '\s+') } | Where-Object { $_ -match '^AAAA' })
        $add = @($p.admin_keys | Where-Object { ($_ -split '\s+')[1] -notin $blobs })
        if ($add.Count -gt 0) {
            if (Test-Path -LiteralPath $adminKeys) { Backup-TsFile $adminKeys | Out-Null }
            Add-Content -LiteralPath $adminKeys -Value $add -Encoding ascii
        }
        # sshd ignores this file unless only SYSTEM and Administrators can touch it.
        & icacls.exe $adminKeys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
        Add-TsStep 'administrators_authorized_keys' $true "$($add.Count) added, ACL set"
    }
    if ($p.default_shell -and (Test-Path -LiteralPath $p.default_shell)) {
        New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
        New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
            -Value $p.default_shell -PropertyType String -Force | Out-Null
        Add-TsStep 'login shell' $true $p.default_shell
    }
    foreach ($svc in 'sshd', 'ssh-agent') {
        Set-Service -Name $svc -StartupType Automatic
    }
    Start-Service ssh-agent
    Add-TsStep 'services sshd, ssh-agent' $true 'Automatic'

    # 4. firewall ---------------------------------------------------------------
    Get-NetFirewallRule -Group 'terminal-stack ssh' -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like 'terminal-stack sshd (Windows*' } | Remove-NetFirewallRule
    $hostRules = @($p.firewall | Where-Object { $_.Layer -eq 'host' })
    foreach ($r in $hostRules) {
        $remote = if ($r.Remote -eq 'Any') { 'Any' } else { $r.Remote -split ',' }
        New-NetFirewallRule -DisplayName $r.Name -Group 'terminal-stack ssh' -Direction Inbound `
            -Action Allow -Protocol TCP -LocalPort $r.Port -Profile ($r.Profile -split ',') `
            -RemoteAddress $remote | Out-Null
    }
    $ports = @($hostRules | ForEach-Object { $_.Port } | Select-Object -Unique)
    $disabled = @()
    foreach ($rule in Get-NetFirewallRule -Direction Inbound -Enabled True -ErrorAction SilentlyContinue) {
        if ($rule.Group -eq 'terminal-stack ssh') { continue }
        $pf = $rule | Get-NetFirewallPortFilter
        if ($pf.Protocol -eq 'TCP' -and ($ports | Where-Object { $_ -in @($pf.LocalPort) })) {
            Disable-NetFirewallRule -Name $rule.Name
            $disabled += $rule.DisplayName
        }
    }
    $fwDetail = "$($hostRules.Count) rule(s)"
    if ($disabled) { $fwDetail += "; disabled (not deleted): $($disabled -join ', ')" }
    Add-TsStep 'firewall' $true $fwDetail
  }

    # 4b. WSL: Hyper-V firewall (mirrored-mode inbound to WSL) and the keep-alive.
    if ($p.keepalive_distro) {
        try {
            Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like 'terminal-stack-sshd-wsl-*' } | Remove-NetFirewallHyperVRule
            $i = 0
            foreach ($r in @($p.firewall | Where-Object { $_.Layer -eq 'hyperv' })) {
                $remote = if ($r.Remote -eq 'Any') { 'Any' } else { $r.Remote -split ',' }
                New-NetFirewallHyperVRule -Name "terminal-stack-sshd-wsl-$i" -DisplayName $r.Name `
                    -Direction Inbound -VMCreatorId $p.wsl_vm_creator -Protocol TCP `
                    -LocalPorts $r.Port -RemoteAddresses $remote -Profiles ($r.Profile -replace ',', ', ') `
                    -Action Allow | Out-Null
                $i++
            }
            Add-TsStep 'Hyper-V firewall (WSL)' $true "$i rule(s)"
        } catch {
            Add-TsStep 'Hyper-V firewall (WSL)' $false "$($_.Exception.Message)"
        }
        # WSL stops a distro once no client is attached, taking sshd with it. A
        # hidden `sleep infinity` client, started at logon, keeps it up.
        $wslExe = Join-Path $env:SystemRoot 'System32\wsl.exe'
        $conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
        $action = New-ScheduledTaskAction -Execute $conhost `
            -Argument "--headless `"$wslExe`" -d $($p.keepalive_distro) --exec sleep infinity"
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $p.keepalive_task -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Force | Out-Null
        Add-TsStep 'WSL keep-alive task' $true $p.keepalive_task
    }

  if ($p.windows) {

    # 5. restart, prove a key login, then passwords ------------------------------
    Restart-Service sshd
    $verified = $false
    if ($p.ssh_exe -and (Test-Path -LiteralPath $p.ssh_exe)) {
        # It must land on WINDOWS: a login that reaches some other sshd on the
        # port proves nothing about this one.
        $answer = & $p.ssh_exe @($p.verify_args) 2>$null
        $verified = ($LASTEXITCODE -eq 0) -and ("$answer" -match [regex]::Escape($p.verify_expect))
    }
    Add-TsStep "key login on port $($p.settings.sshWindowsPort)" $verified $(if ($verified) { 'verified' } else { 'no agent or local key could log in' })
    if ($p.password_off_after_verify) {
        if ($verified) {
            Set-TsBlock $p.sshd_block_final
            & $sshd -t 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Restart-Service sshd
                Add-TsStep 'passwords off' $true 'after a verified key login'
            } else {
                Set-TsBlock $p.sshd_block
                Add-TsStep 'passwords off' $false 'sshd -t refused the final block; left on'
            }
        } else {
            Add-TsStep 'passwords off' $false 'left ON: no key login could be verified from this PC'
        }
    } elseif ($p.password_off_without_verify) {
        Add-TsStep 'passwords off' $true 'without a local proof, as you chose'
    }
  }
    Save-TsResult $true
} catch {
    Add-TsStep 'error' $false "$($_.Exception.Message)"
    Save-TsResult $false
    exit 1
}
