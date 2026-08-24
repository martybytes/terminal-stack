<#
.NAME        ts-agents
.SYNOPSIS    Reconcile user-global Headroom, Caveman and AgentMemory integrations.
.USAGE       ts-agents.ps1 [-Tool all|headroom|caveman|agentmemory]
                           [-Action status|on|off|repair|uninstall|dashboard]
                           [-CursorMode mcp|byok|off]
.NOTE        This script owns only user-scoped agent configuration. It never edits a
             project and never creates, starts, stops, or removes Docker resources.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'headroom', 'caveman', 'agentmemory')]
    [string]$Tool = 'all',
    [ValidateSet('status', 'on', 'off', 'repair', 'uninstall', 'dashboard')]
    [string]$Action = 'status',
    [ValidateSet('mcp', 'byok', 'off')]
    [string]$CursorMode = 'mcp'
)

$ErrorActionPreference = 'Stop'
$manifestPath = Join-Path $PSScriptRoot 'agent-tools.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Missing $manifestPath" }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$script:Failures = 0

function Info([string]$Message) { Write-Host "  $Message" }
function Good([string]$Message) { Write-Host "  ok  $Message" -ForegroundColor Green }
function Bad([string]$Message)  { Write-Host "  !!  $Message" -ForegroundColor Yellow; $script:Failures++ }

function Get-TsNativeCommand([string]$Name) {
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

function Invoke-TsNative {
    param([string]$Command, [string[]]$Arguments, [switch]$AllowFailure)
    if (-not $Command) {
        if (-not $AllowFailure) { Bad "required command is not installed" }
        return $false
    }
    & $Command @Arguments | Out-Host
    $ok = ($LASTEXITCODE -eq 0)
    if (-not $ok -and -not $AllowFailure) { Bad "$([IO.Path]::GetFileName($Command)) failed (exit $LASTEXITCODE)" }
    return $ok
}

function Test-TsHttp([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 1 -UseBasicParsing
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch { return $false }
}

function Get-TsHeadroomToken {
    if ($env:HEADROOM_PROXY_TOKEN) { return $env:HEADROOM_PROXY_TOKEN }
    $file = $env:HEADROOM_ENV_FILE
    if (-not $file) {
        $roots = @($env:WORKSPACE_DIR, 'C:\DATA\Workspace', (Join-Path $HOME 'Documents\Workspace'),
            (Join-Path $HOME 'workspace'), (Join-Path $HOME 'Workspace')) | Where-Object { $_ }
        foreach ($root in $roots) {
            $candidate = Join-Path $root 'src\github.com\martybytes\docker-local\headroom\.env'
            if (Test-Path -LiteralPath $candidate) { $file = $candidate; break }
        }
    }
    if (-not $file -or -not (Test-Path -LiteralPath $file)) { return $null }
    $line = Get-Content -LiteralPath $file | Where-Object { $_ -match '^HEADROOM_PROXY_TOKEN=' } | Select-Object -First 1
    if ($line) { return ($line -replace '^HEADROOM_PROXY_TOKEN=', '') }
    return $null
}

# Twin of headroom_probe_auth in ts-agents.sh: probe, and record WHY it
# failed. One 2s attempt reported a cold container as broken, and `on`/`repair`
# gate on this, so a slow first hit turned into 'registrations were not
# changed' with nothing to act on. A real HTTP answer is conclusive and is not
# retried; only a connection failure or timeout is.
$script:TsHeadroomAuthReason = ''
function Test-TsHeadroomAuth {
    $script:TsHeadroomAuthReason = ''
    $token = Get-TsHeadroomToken
    if (-not $token) {
        $script:TsHeadroomAuthReason = 'no proxy token (set HEADROOM_PROXY_TOKEN or HEADROOM_ENV_FILE)'
        return $false
    }
    $uri = ([string]$manifest.headroom.proxyUrl).TrimEnd('/') + '/stats'
    foreach ($attempt in 1, 2) {
        try {
            $r = Invoke-WebRequest -Uri $uri -TimeoutSec 5 -UseBasicParsing `
                -Headers @{ 'X-Headroom-Proxy-Token' = $token }
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { return $true }
            $script:TsHeadroomAuthReason = "HTTP $($r.StatusCode)"
            return $false
        } catch {
            $code = $_.Exception.Response.StatusCode.value__
            if ($code) { $script:TsHeadroomAuthReason = "HTTP $code"; return $false }
            $script:TsHeadroomAuthReason = 'unreachable'
        }
    }
    return $false
}

function Test-TsTcp([string]$HostName, [int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return ($task.Wait(1000) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}

function Read-TsJson([string]$Path, [hashtable]$Default) {
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    try { return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable) }
    catch { throw "Refusing to overwrite malformed JSON: $Path" }
}

function Write-TsJson([string]$Path, [hashtable]$Value) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    if (Test-Path -LiteralPath $Path) {
        $stamp = Get-Date -Format 'yyyyMMdd'
        $backup = "$Path.bak.$stamp"; $n = 1
        while (Test-Path -LiteralPath $backup) { $backup = "$Path.bak.$stamp.$n"; $n++ }
        Copy-Item -LiteralPath $Path -Destination $backup
    }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Set-TsCursorMcp([string]$Name, $Entry) {
    $path = Join-Path $env:USERPROFILE '.cursor\mcp.json'
    $cfg = Read-TsJson $path ([ordered]@{ mcpServers = [ordered]@{} })
    if (-not $cfg.ContainsKey('mcpServers') -or $cfg.mcpServers -isnot [System.Collections.IDictionary]) {
        $cfg.mcpServers = [ordered]@{}
    }
    if ($null -eq $Entry) { $cfg.mcpServers.Remove($Name) | Out-Null }
    else { $cfg.mcpServers[$Name] = $Entry }
    Write-TsJson $path $cfg
}

function Test-TsCursorMcp([string]$Name, [string]$Url) {
    $path = Join-Path $env:USERPROFILE '.cursor\mcp.json'
    try {
        $cfg = Read-TsJson $path ([ordered]@{ mcpServers = [ordered]@{} })
        return ($cfg.mcpServers.ContainsKey($Name) -and $cfg.mcpServers[$Name].url -eq $Url)
    } catch { return $false }
}

function Invoke-TsMcpRegistration([ValidateSet('add','remove')][string]$Verb) {
    $url = [string]$manifest.headroom.mcpUrl
    $claude = Get-TsNativeCommand 'claude'
    $codex = Get-TsNativeCommand 'codex'
    $mcpReady = Test-TsTcp '127.0.0.1' 8788
    if ($Verb -eq 'add' -and $mcpReady) {
        if ($claude) {
            & $claude mcp remove --scope user headroom *> $null
            Invoke-TsNative $claude @('mcp','add','--transport','http','--scope','user','headroom',$url) | Out-Null
        } else { Info 'Claude Code not installed; skipped Headroom MCP registration' }
        if ($codex) {
            & $codex mcp remove headroom *> $null
            Invoke-TsNative $codex @('mcp','add','headroom','--url',$url) | Out-Null
        } else { Info 'Codex not installed; skipped Headroom MCP registration' }
        if ($CursorMode -eq 'mcp' -and (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.cursor'))) {
            Set-TsCursorMcp headroom ([ordered]@{ url = $url })
            Good 'Cursor Headroom MCP registered at user scope'
        } elseif ($CursorMode -eq 'byok') {
            Set-TsCursorMcp headroom $null
            Info 'Cursor BYOK selected: set the global provider base URL to http://127.0.0.1:8787 and use a provider API key.'
            Info 'Cursor subscription traffic cannot be redirected through a custom base URL.'
        } else { Set-TsCursorMcp headroom $null }
    } else {
        if ($claude) { & $claude mcp remove --scope user headroom *> $null }
        if ($codex) { & $codex mcp remove headroom *> $null }
        Set-TsCursorMcp headroom $null
        if ($Verb -eq 'add') { Info 'optional Headroom MCP is offline; removed stale client registrations' }
    }
}

function Show-TsHeadroomStatus {
    Write-Host 'Headroom:'
    $proxy = [string]$manifest.headroom.proxyUrl
    if (Test-TsHeadroomAuth) { Good "proxy authentication works at $proxy" }
    else { Bad "proxy unusable at $proxy ($script:TsHeadroomAuthReason)" }
    if (Test-TsTcp '127.0.0.1' 8788) { Good "MCP sidecar reachable at $($manifest.headroom.mcpUrl)" }
    else { Info "MCP sidecar not reachable at $($manifest.headroom.mcpUrl) (optional separate process)" }
    $mcpUrl = [string]$manifest.headroom.mcpUrl
    $claudeJson = Join-Path $env:USERPROFILE '.claude.json'
    try {
        $claudeCfg = Read-TsJson $claudeJson ([ordered]@{})
        if ($claudeCfg.ContainsKey('mcpServers') -and $claudeCfg.mcpServers.ContainsKey('headroom') -and $claudeCfg.mcpServers.headroom.url -eq $mcpUrl) {
            Good 'Claude user-scope MCP registration present'
        } elseif (Test-TsTcp '127.0.0.1' 8788) { Bad 'Claude user-scope MCP registration missing' }
        else { Info 'Claude Headroom MCP registration absent while sidecar is offline (expected)' }
    } catch { Bad "could not inspect $claudeJson" }
    $codexCfg = Join-Path $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }) 'config.toml'
    $codexText = if (Test-Path -LiteralPath $codexCfg) { Get-Content -LiteralPath $codexCfg -Raw } else { '' }
    if ($codexText -match '(?ms)^\[mcp_servers\.headroom\]\s+url\s*=\s*"http://127\.0\.0\.1:8788/mcp"') { Good 'Codex user-scope MCP registration present' }
    elseif (Test-TsTcp '127.0.0.1' 8788) { Bad 'Codex user-scope MCP registration missing' }
    else { Info 'Codex Headroom MCP registration absent while sidecar is offline (expected)' }
    if ((Get-TsAgentRuntimeCursorMode) -eq 'mcp' -and (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.cursor'))) {
        if (Test-TsCursorMcp headroom $mcpUrl) { Good 'Cursor user-scope MCP registration present' }
        else { Bad 'Cursor user-scope MCP registration missing' }
    }
    Info "dashboard: $($manifest.headroom.dashboardUrl)"
    Info "pinned compatibility: $($manifest.headroom.version) ($($manifest.headroom.dockerImage))"
}

function Get-TsAgentRuntimeCursorMode {
    $path = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
    try {
        $cfg = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($cfg.headroomCursorMode -in 'mcp','byok','off') { return $cfg.headroomCursorMode }
    } catch {}
    return $CursorMode
}

function Invoke-TsHeadroom {
    switch ($Action) {
        'dashboard' { Start-Process ([string]$manifest.headroom.dashboardUrl); return }
        'status' { Show-TsHeadroomStatus; return }
        'on' { if (-not (Test-TsHeadroomAuth)) { Bad "Headroom proxy authentication failed ($script:TsHeadroomAuthReason); leaving direct mode unchanged."; return }; Invoke-TsMcpRegistration add; Show-TsHeadroomStatus; return }
        'repair' { if (-not (Test-TsHeadroomAuth)) { Bad "Headroom proxy authentication failed ($script:TsHeadroomAuthReason); registrations were not changed."; return }; Invoke-TsMcpRegistration add; Show-TsHeadroomStatus; return }
        'off' { Invoke-TsMcpRegistration remove; Info 'Headroom routing and MCP registrations removed; Docker was not changed.'; return }
        'uninstall' { Invoke-TsMcpRegistration remove; Info 'Terminal-stack Headroom registrations removed; Docker was not changed.'; return }
    }
}

$script:CavemanStart = '<!-- terminal-stack-caveman-start -->'
$script:CavemanEnd = '<!-- terminal-stack-caveman-end -->'
function Set-TsCavemanCodexRule([bool]$Enable) {
    $codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $path = Join-Path $codexRoot 'AGENTS.md'
    $lines = [System.Collections.Generic.List[string]]::new()
    $skip = $false
    if (Test-Path -LiteralPath $path) {
        foreach ($line in @(Get-Content -LiteralPath $path)) {
            if ($line.Contains($script:CavemanStart)) { $skip = $true; continue }
            if ($line.Contains($script:CavemanEnd)) { $skip = $false; continue }
            if (-not $skip) { $lines.Add($line) }
        }
    }
    if ($Enable) {
        if ($lines.Count -and $lines[$lines.Count - 1]) { $lines.Add('') }
        $lines.Add($script:CavemanStart)
        $lines.Add('Caveman is enabled globally. Apply the installed caveman skill to every response; use full mode unless the user asks otherwise.')
        $lines.Add($script:CavemanEnd)
    }
    New-Item -ItemType Directory -Force -Path $codexRoot | Out-Null
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination "$path.bak.$(Get-Date -Format yyyyMMdd-HHmmss)" }
    Set-Content -LiteralPath $path -Value $lines -Encoding utf8
}

function Install-TsCaveman {
    $claude = Get-TsNativeCommand 'claude'
    if ($claude) {
        Invoke-TsNative $claude @('plugin','marketplace','add',[string]$manifest.caveman.claudeMarketplace,'--scope','user') -AllowFailure | Out-Null
        Invoke-TsNative $claude @('plugin','install','caveman@caveman','--scope','user','-y') -AllowFailure | Out-Null
        Invoke-TsNative $claude @('plugin','enable','caveman@caveman','--scope','user') -AllowFailure | Out-Null
    } else { Info 'Claude Code not installed; skipped Caveman plugin' }
    $npx = Get-TsNativeCommand 'npx'
    if ($npx) {
        Invoke-TsNative $npx @('-y','skills@latest','add',[string]$manifest.caveman.source,'-g','-y','--copy','-a','codex','cursor','-s',[string]$manifest.caveman.skill) -AllowFailure | Out-Null
    } else { Info 'npx not installed; skipped global Codex/Cursor Caveman skill' }
    Set-TsCavemanCodexRule $true
    Good "Caveman $($manifest.caveman.version) enabled for installed agents"
    Info 'Cursor: add this once in Settings > Rules > User Rules: "Always apply the global caveman skill; use full mode unless I ask otherwise."'
}

function Remove-TsCaveman([bool]$Uninstall) {
    $claude = Get-TsNativeCommand 'claude'
    if ($claude) {
        if ($Uninstall) { Invoke-TsNative $claude @('plugin','uninstall','caveman@caveman','--scope','user','--keep-data','-y') -AllowFailure | Out-Null }
        else { Invoke-TsNative $claude @('plugin','disable','caveman@caveman','--scope','user') -AllowFailure | Out-Null }
    }
    $npx = Get-TsNativeCommand 'npx'
    if ($Uninstall -and $npx) { Invoke-TsNative $npx @('-y','skills@latest','remove','caveman','-g','-y','-a','codex','cursor') -AllowFailure | Out-Null }
    Set-TsCavemanCodexRule $false
    Info "Caveman automation removed$(if (-not $Uninstall) { '; the downloaded global skill was preserved' }). Remove the Cursor User Rule manually if you added it."
}

function Show-TsCavemanStatus {
    Write-Host 'Caveman:'
    $rule = Join-Path $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }) 'AGENTS.md'
    if ((Test-Path -LiteralPath $rule) -and (Select-String -LiteralPath $rule -SimpleMatch $script:CavemanStart -Quiet)) {
        Good 'Codex global always-on rule present'
    } else { Bad 'Codex global always-on rule absent' }
    $claude = Get-TsNativeCommand 'claude'
    if ($claude) {
        $plugins = (& $claude plugin list --json 2>$null | Out-String)
        if ($plugins -match 'caveman@caveman') { Good 'Claude Caveman plugin installed' } else { Bad 'Claude Caveman plugin not installed' }
    }
    $skillPath = Join-Path $env:USERPROFILE '.agents\skills\caveman\SKILL.md'
    if (Test-Path -LiteralPath $skillPath) { Good 'global Codex/Cursor caveman skill installed' }
    else { Bad 'global Codex/Cursor caveman skill missing' }
    Info "pinned version: $($manifest.caveman.version)"
}

function Invoke-TsCaveman {
    switch ($Action) {
        'status' { Show-TsCavemanStatus }
        'on' { Install-TsCaveman; Show-TsCavemanStatus }
        'repair' { Install-TsCaveman; Show-TsCavemanStatus }
        'off' { Remove-TsCaveman $false }
        'uninstall' { Remove-TsCaveman $true }
        default { Bad "Caveman has no '$Action' action" }
    }
}

function Install-TsAgentMemory {
    $claude = Get-TsNativeCommand 'claude'
    if ($claude) {
        $claudeSource = "$($manifest.agentmemory.source)@$($manifest.agentmemory.ref)"
        Invoke-TsNative $claude @('plugin','marketplace','add',$claudeSource,'--scope','user') -AllowFailure | Out-Null
        Invoke-TsNative $claude @('plugin','install','agentmemory@agentmemory','--scope','user','-y') -AllowFailure | Out-Null
        Invoke-TsNative $claude @('plugin','enable','agentmemory@agentmemory','--scope','user') -AllowFailure | Out-Null
    }
    $codex = Get-TsNativeCommand 'codex'
    if ($codex) {
        Invoke-TsNative $codex @('plugin','marketplace','add',[string]$manifest.agentmemory.source,'--ref',[string]$manifest.agentmemory.ref) -AllowFailure | Out-Null
        Invoke-TsNative $codex @('plugin','add','agentmemory@agentmemory') -AllowFailure | Out-Null
    }
    $adapter = Join-Path $PSScriptRoot 'ts-agentmemory.ps1'
    & $adapter -Apply
    if ($LASTEXITCODE -ne 0) { Bad 'AgentMemory hook adapter failed' }
}

function Remove-TsAgentMemory([bool]$Uninstall) {
    $adapter = Join-Path $PSScriptRoot 'ts-agentmemory.ps1'
    & $adapter -Undo -Apply
    $claude = Get-TsNativeCommand 'claude'
    $codex = Get-TsNativeCommand 'codex'
    if ($claude) {
        if ($Uninstall) { Invoke-TsNative $claude @('plugin','uninstall','agentmemory@agentmemory','--scope','user','--keep-data','-y') -AllowFailure | Out-Null }
        else { Invoke-TsNative $claude @('plugin','disable','agentmemory@agentmemory','--scope','user') -AllowFailure | Out-Null }
    }
    if ($codex) { Invoke-TsNative $codex @('plugin','remove','agentmemory@agentmemory') -AllowFailure | Out-Null }
    Info 'AgentMemory client wiring removed; server, secret, container, and data were not changed.'
}

function Show-TsAgentMemoryStatus {
    Write-Host 'AgentMemory:'
    if ((Test-TsHttp "$($manifest.agentmemory.restUrl)/health") -or (Test-TsTcp '127.0.0.1' 3111)) { Good "REST server reachable at $($manifest.agentmemory.restUrl)" }
    else { Bad "REST server not reachable at $($manifest.agentmemory.restUrl)" }
    if ((Test-TsHttp ([string]$manifest.agentmemory.viewerUrl)) -or (Test-TsTcp '127.0.0.1' 3113)) { Good "viewer reachable at $($manifest.agentmemory.viewerUrl)" }
    else { Info "viewer not reachable at $($manifest.agentmemory.viewerUrl)" }
    $adapter = Join-Path $PSScriptRoot 'ts-agentmemory.ps1'
    & $adapter -Check
    if ($LASTEXITCODE -eq 0) { Good 'agent hook wiring intact' } else { Bad 'agent hook wiring incomplete' }
    Info "pinned plugin version: $($manifest.agentmemory.version)"
}

function Invoke-TsAgentMemory {
    switch ($Action) {
        'status' { Show-TsAgentMemoryStatus }
        'on' { Install-TsAgentMemory; Show-TsAgentMemoryStatus }
        'repair' { Install-TsAgentMemory; Show-TsAgentMemoryStatus }
        'off' { Remove-TsAgentMemory $false }
        'uninstall' { Remove-TsAgentMemory $true }
        default { Bad "AgentMemory has no '$Action' action" }
    }
}

$selected = if ($Tool -eq 'all') { @('headroom','caveman','agentmemory') } else { @($Tool) }
foreach ($name in $selected) {
    switch ($name) {
        'headroom' { Invoke-TsHeadroom }
        'caveman' { Invoke-TsCaveman }
        'agentmemory' { Invoke-TsAgentMemory }
    }
}

if ($script:Failures) { exit 1 }
