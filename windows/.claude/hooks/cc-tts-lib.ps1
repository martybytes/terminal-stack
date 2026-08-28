# cc-tts-lib.ps1 — shared TTS config + speech formatting (dot-sourced).
$script:CcTtsConfigDir = Join-Path $env:USERPROFILE '.claude\tts'
$script:CcTtsConfigBase = Join-Path $script:CcTtsConfigDir 'config.json'
$script:CcTtsConfigLocal = Join-Path $script:CcTtsConfigDir 'local.json'
$script:CcTtsLegacy = Join-Path $env:USERPROFILE '.claude\tts.json'
$script:CcTtsMerged = $null

function Merge-CcTtsHashtable {
    param($Base, $Over)
    if ($Over -isnot [hashtable] -and $Over -isnot [pscustomobject]) { return $Base }
    $out = @{}
    foreach ($k in $Base.Keys) { $out[$k] = $Base[$k] }
    # Normalize the override into name/value pairs. $Over is usually a [hashtable]
    # (its PSObject.Properties exposes Count/Keys/Values, NOT the data keys), but may
    # also be a [pscustomobject]. Iterating the wrong one silently drops all overrides.
    $pairs = if ($Over -is [hashtable]) {
        $Over.GetEnumerator() | ForEach-Object { [pscustomobject]@{ Name = $_.Key; Value = $_.Value } }
    } else {
        $Over.PSObject.Properties | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Value = $_.Value } }
    }
    foreach ($prop in $pairs) {
        if ([string]$prop.Name -like '_*') { continue }
        if ($out.ContainsKey($prop.Name) -and $out[$prop.Name] -is [hashtable] -and ($prop.Value -is [pscustomobject] -or $prop.Value -is [hashtable])) {
            $out[$prop.Name] = Merge-CcTtsHashtable $out[$prop.Name] (ConvertTo-Hashtable $prop.Value)
        } else {
            $out[$prop.Name] = $prop.Value
        }
    }
    return $out
}

function ConvertTo-Hashtable {
    param($Obj)
    if ($null -eq $Obj) { return @{} }
    if ($Obj -is [hashtable]) { return $Obj }
    $h = @{}
    foreach ($p in $Obj.PSObject.Properties) {
        if ($p.Value -is [pscustomobject]) { $h[$p.Name] = ConvertTo-Hashtable $p.Value }
        else { $h[$p.Name] = $p.Value }
    }
    return $h
}

function Initialize-CcTtsConfig {
    if ($script:CcTtsMerged) { return $script:CcTtsMerged }

    if (-not (Test-Path -LiteralPath $script:CcTtsConfigDir)) {
        New-Item -ItemType Directory -Path $script:CcTtsConfigDir -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $script:CcTtsConfigBase) -and (Test-Path -LiteralPath $script:CcTtsLegacy)) {
        Copy-Item -LiteralPath $script:CcTtsLegacy -Destination $script:CcTtsConfigBase -Force
    }
    if (-not (Test-Path -LiteralPath $script:CcTtsConfigBase)) {
        if (Test-Path -LiteralPath $script:CcTtsLegacy) {
            $script:CcTtsMerged = Get-Content -LiteralPath $script:CcTtsLegacy -Raw | ConvertFrom-Json
            return $script:CcTtsMerged
        }
        return $null
    }

    $cfg = Get-Content -LiteralPath $script:CcTtsConfigBase -Raw | ConvertFrom-Json
    if (Test-Path -LiteralPath $script:CcTtsConfigLocal) {
        $loc = Get-Content -LiteralPath $script:CcTtsConfigLocal -Raw | ConvertFrom-Json
        $cfgHash = ConvertTo-Hashtable $cfg
        $locHash = ConvertTo-Hashtable $loc
        $merged = Merge-CcTtsHashtable $cfgHash $locHash
        $cfg = $merged | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    }
    if ($cfg.templates -and -not $cfg.announce) {
        $cfg | Add-Member -NotePropertyName announce -NotePropertyValue ([pscustomobject]@{
            includeProject = $true
            messageMode = if ($cfg.messageMode) { $cfg.messageMode } else { 'template' }
            templates = $cfg.templates
        }) -Force
    }
    $script:CcTtsMerged = $cfg
    return $cfg
}

function Get-CcTtsConfigValue {
    param([string]$Path, $Default = $null)
    $cfg = Initialize-CcTtsConfig
    if (-not $cfg) { return $Default }
    $cur = $cfg
    foreach ($part in $Path.Trim('.').Split('.')) {
        if ($null -eq $cur) { return $Default }
        $cur = $cur.$part
    }
    if ($null -eq $cur) { return $Default }
    return $cur
}

function Test-CcTtsEventEnabled {
    param([string]$Event)
    $events = Get-CcTtsConfigValue 'events' @('waiting', 'error')
    if ($events -is [string]) { $events = $events.Split(',') | ForEach-Object { $_.Trim() } }
    return ($events -contains $Event)
}

function Get-CcTtsEffectiveExcitement {
    $e = Get-CcTtsConfigValue 'excitement' $null
    if ($null -ne $e) { return [double]$e }
    return [double](Get-CcTtsConfigValue 'chatterbox.energy' 0.25)
}

function Get-CcTtsEffectiveKokoroSpeed {
    $exc = Get-CcTtsConfigValue 'excitement' $null
    if ($null -ne $exc) { return [math]::Round(0.8 + [double]$exc * 0.4, 2) }
    return [double](Get-CcTtsConfigValue 'kokoro.speed' 1.0)
}

function Build-CcTtsSpeech {
    param(
        [string]$Source = 'claude',
        [string]$State = 'waiting',
        [string]$Project = '',
        [string]$OverrideText = ''
    )
    $cfg = Initialize-CcTtsConfig
    if (-not $cfg) { return '' }

    $maxChars = [int](Get-CcTtsConfigValue 'maxChars' 120)
    $includeProject = Get-CcTtsConfigValue 'announce.includeProject' $true
    if (-not $includeProject) { $Project = '' }

    $text = $OverrideText
    if (-not $text) {
        $tpl = Get-CcTtsConfigValue "announce.templates.$State" ''
        if (-not $tpl) { $tpl = Get-CcTtsConfigValue "templates.$State" '' }
        $text = ($tpl -replace '\{project\}', $Project)
    }
    $text = ($text -replace "[\r\n]+", ' ').Trim()

    if ($Source -ne 'test') {
        $prefixEnabled = Get-CcTtsConfigValue "sources.$Source.prefixEnabled" $true
        $prefix = Get-CcTtsConfigValue "sources.$Source.prefix" $Source
        if ($prefixEnabled -and $prefix -and -not $text.StartsWith("$prefix.")) {
            $text = "$prefix. $text"
        }
    }

    if ($text.Length -gt $maxChars) { $text = $text.Substring(0, $maxChars) }
    return $text
}

function Invoke-CcTtsSynth {
    param([string]$Text, [string]$OutPath)
    $cfg = Initialize-CcTtsConfig
    if (-not $cfg) { return $false }
    $engine = Get-CcTtsConfigValue 'engine' 'kokoro'
    try {
        switch ($engine) {
            'kokoro' {
                $k = $cfg.kokoro
                $body = @{
                    model = 'kokoro'; input = $Text; voice = $k.voice
                    response_format = $k.format; speed = [double](Get-CcTtsEffectiveKokoroSpeed)
                } | ConvertTo-Json -Compress
                Invoke-RestMethod -Uri ($k.url.TrimEnd('/') + '/v1/audio/speech') `
                    -Method Post -ContentType 'application/json' -Body $body `
                    -TimeoutSec $k.timeoutSec -OutFile $OutPath
                return $true
            }
            'chatterbox' {
                $c = $cfg.chatterbox
                $exag = [math]::Round(0.25 + [double](Get-CcTtsEffectiveExcitement), 2)
                $body = @{
                    input = $Text; voice = $c.voice; exaggeration = $exag
                    cfg_weight = [double]$c.cfgWeight; temperature = [double]$c.temperature
                } | ConvertTo-Json -Compress
                Invoke-RestMethod -Uri ($c.url.TrimEnd('/') + '/v1/audio/speech') `
                    -Method Post -ContentType 'application/json' -Body $body `
                    -TimeoutSec $c.timeoutSec -OutFile $OutPath
                return $true
            }
            'auto' {
                try {
                    $k = $cfg.kokoro
                    $body = @{
                        model = 'kokoro'; input = $Text; voice = $k.voice
                        response_format = $k.format; speed = [double](Get-CcTtsEffectiveKokoroSpeed)
                    } | ConvertTo-Json -Compress
                    Invoke-RestMethod -Uri ($k.url.TrimEnd('/') + '/v1/audio/speech') `
                        -Method Post -ContentType 'application/json' -Body $body `
                        -TimeoutSec $k.timeoutSec -OutFile $OutPath
                    return $true
                } catch {
                    $c = $cfg.chatterbox
                    $exag = [math]::Round(0.25 + [double](Get-CcTtsEffectiveExcitement), 2)
                    $body = @{
                        input = $Text; voice = $c.voice; exaggeration = $exag
                        cfg_weight = [double]$c.cfgWeight; temperature = [double]$c.temperature
                    } | ConvertTo-Json -Compress
                    Invoke-RestMethod -Uri ($c.url.TrimEnd('/') + '/v1/audio/speech') `
                        -Method Post -ContentType 'application/json' -Body $body `
                        -TimeoutSec $c.timeoutSec -OutFile $OutPath
                    return $true
                }
            }
        }
    } catch {}
    if (Get-CcTtsConfigValue 'edge.enabled' $true) {
        $voice = Get-CcTtsConfigValue 'edge.voice' 'en-US-AndrewMultilingualNeural'
        if (Get-Command edge-tts -ErrorAction SilentlyContinue) {
            & edge-tts --voice $voice --text $Text --write-media $OutPath 2>$null
            return (Test-Path -LiteralPath $OutPath)
        }
    }
    return $false
}

function Invoke-CcTtsSapiSpeak {
    <#
      The Windows floor, and the reason "on" can no longer mean silence here.

      Invoke-CcTtsSynth's ladder ended at edge-tts and returned $false, so a
      native-Windows host with the daemon off, kokoro down and edge-tts not
      installed produced nothing at all -- the exact gap /usr/bin/say was added
      to close on macOS, still open on the platform this stack started on.

      It SPEAKS rather than synthesising to a file, deliberately. The Windows
      playback path is cc-tts-play.ps1, which requires ffplay and errors without
      it; a floor that depends on a package the user may not have is not a floor.
      SAPI is part of Windows and needs neither a file nor a player.

      The daemon already does exactly this (ttsd/playback.py) -- this is the same
      rung for the hook path, which is what runs when the daemon is off.

      Never throws: the caller's alternative is silence, so a failure here must
      leave things no worse than they already were.
    #>
    param([string]$Text)
    if (-not $Text) { return $false }
    try {
        # The system voice, deliberately: no ccTts* key selects a SAPI voice,
        # and inventing one here would be a setting the schema does not describe
        # and nothing else can read.
        $sapi = New-Object -ComObject SAPI.SpVoice
        $sapi.Speak($Text) | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Parse-CcTtsInputHook {
    param([string]$InputJson, [string]$Event)
    $state = 'question'
    $override = ''
    if (-not $InputJson) { return @{ State = $state; Override = $override } }
    try {
        $data = $InputJson | ConvertFrom-Json
        switch ($Event) {
            'permission' {
                $state = 'permission'
                if ($data.tool_name) { $override = [string]$data.tool_name }
                elseif ($data.message) { $override = [string]$data.message }
            }
            'notification' {
                $state = 'question'
                if ($data.message) { $override = [string]$data.message }
            }
            'cursor_question' {
                $state = 'question'
                $q = $data.tool_input
                if ($q.questions -and $q.questions.Count -gt 0) {
                    $first = $q.questions[0]
                    if ($first.prompt) { $override = [string]$first.prompt }
                    elseif ($first.question) { $override = [string]$first.question }
                    elseif ($first.header) { $override = [string]$first.header }
                }
            }
            default {
                if ($data.tool_input.questions -and $data.tool_input.questions.Count -gt 0) {
                    $first = $data.tool_input.questions[0]
                    if ($first.question) { $override = [string]$first.question }
                }
            }
        }
    } catch {}
    return @{ State = $state; Override = $override }
}

# ── ttsd daemon sender ─────────────────────────────────────────────────────────
# On native Windows the daemon listens on loopback, so no token/host ladder is
# needed: a dead daemon refuses the connection instantly and the caller falls
# back to the direct cc-tts-notify path — never silence.

function Test-CcTtsDaemonReady {
    return [bool](Get-CcTtsConfigValue 'daemon.enabled' $false)
}

function Send-CcTtsDaemonEvent {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Event,
        [string]$State = '',
        [string]$InputJson = '',
        [string]$Override = ''
    )
    try {
        # CC_TTS_DAEMON_PORT_OVERRIDE: test hook (cc-tts-test -DaemonFallback)
        # forces an unreachable port to prove the direct-speak fallback fires.
        $port = if ($env:CC_TTS_DAEMON_PORT_OVERRIDE) { [int]$env:CC_TTS_DAEMON_PORT_OVERRIDE }
                else { [int](Get-CcTtsConfigValue 'daemon.port' 8890) }
        $hook = $null
        if ($InputJson) { try { $hook = $InputJson | ConvertFrom-Json } catch {} }
        $pdir = if ($env:CLAUDE_PROJECT_DIR) { $env:CLAUDE_PROJECT_DIR }
                elseif ($env:CURSOR_PROJECT_DIR) { $env:CURSOR_PROJECT_DIR }
                else { "$PWD" }
        $sid = if ($hook -and $hook.session_id) { [string]$hook.session_id }
               elseif ($hook -and $hook.conversation_id) { [string]$hook.conversation_id }
               else { 'dir:' + $pdir }  # stable per directory; hook pwsh PIDs are per-invocation
        $payload = [ordered]@{
            v = 1
            source = $Source
            host = 'windows'
            event = $Event
            state = $State
            session_key = "${Source}:${sid}"
            project = [ordered]@{ dir = "$pdir"; name = (Split-Path -Leaf $pdir) }
            cwd = "$PWD"
            transcript_path = if ($hook -and $hook.transcript_path) { [string]$hook.transcript_path } else { '' }
            override = $Override
            message = [ordered]@{
                text = if ($hook -and $hook.last_assistant_message) { [string]$hook.last_assistant_message }
                       elseif ($hook -and $hook.text) { [string]$hook.text } else { '' }
                error_type = if ($hook -and $hook.error_type) { [string]$hook.error_type } else { '' }
                notification_type = if ($hook -and $hook.notification_type) { [string]$hook.notification_type } else { '' }
                tool_name = if ($hook -and $hook.tool_name) { [string]$hook.tool_name } else { '' }
                stop_status = if ($hook -and $hook.status) { [string]$hook.status } else { '' }
            }
            wezterm = [ordered]@{ pane = if ($env:WEZTERM_PANE) { "$env:WEZTERM_PANE" } else { '' } }
            ts = [double][DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000
        }
        $json = $payload | ConvertTo-Json -Depth 6 -Compress
        $client = [System.Net.Http.HttpClient]::new()
        try {
            $client.Timeout = [TimeSpan]::FromMilliseconds(1500)
            $content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, 'application/json')
            $resp = $client.PostAsync("http://127.0.0.1:$port/v1/event", $content).GetAwaiter().GetResult()
            return $resp.IsSuccessStatusCode
        } finally {
            $client.Dispose()
        }
    } catch {
        return $false
    }
}
