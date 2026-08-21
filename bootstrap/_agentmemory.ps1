# _agentmemory-hook-edits.ps1 — the deployment edits applied to AgentMemory's bundled
# hook scripts, shared by setup-codex-agent-tagging.ps1 (Codex plugin cache),
# setup-codex-desktop-hooks.ps1 (the ~/.codex stable copies) and
# setup-claude-integration.ps1 (Claude plugin cache). Dot-source it; it does nothing
# on its own.
#
# Why these live here rather than in one setup script: the same six scripts exist in
# two places for Codex (plugin cache for the CLI, ~/.codex/hooks/agentmemory for
# Desktop) and again for Claude. Defining each edit once keeps the three installers
# from drifting, which is how the Cursor script ended up not reproducing its own
# installed state.
#
# Edits are authored with LF and applied line-ending-agnostically: the ~/.codex copies
# are written by PowerShell and end up CRLF, while the plugin cache ships LF. An edit
# that only matched one of those would silently no-op on the other.
#
# Every edit is idempotent (already-applied is detected) and fail-fast (neither the
# old nor the new form present means the vendor layout moved — that is an error, not
# something to skip).

# Deliberately no Set-StrictMode here: this file is dot-sourced, and strictness would
# leak into the caller's scope. check-capture.ps1 tests for optional properties that
# StrictMode turns into terminating errors.

# Author edits with @T for a tab and @N for a newline, so this file needs no literal
# tabs and no PowerShell escaping of the JavaScript's own $ and backtick characters.
function Expand-AmEditText([string]$text) {
    return ($text -replace '@T', "`t") -replace '@N', "`n"
}

function New-AmEdit([string]$Label, [string[]]$Scripts, [string]$Old, [string]$New, [string]$Marker, [string[]]$Alternatives) {
    # $Marker is what "is this already applied?" tests, when the full $New text is not a
    # reliable probe. Detecting on $New assumes nothing else ever inserts inside it: the
    # duplicate-guard edit adds imports between the shebang and the first vendor import,
    # which made the project-helper edit look permanently missing and would have had the
    # sync rewrite every hook script on every run. Defaults to $New.
    return [pscustomobject]@{
        Label   = $Label
        Scripts = $Scripts
        Old     = Expand-AmEditText $Old
        New     = Expand-AmEditText $New
        Marker  = if ($PSBoundParameters.ContainsKey('Marker') -and $Marker) { Expand-AmEditText $Marker } else { Expand-AmEditText $New }
        # Other forms this edit can rewrite from. Cursor has no agentmemory package of its
        # own, so its scripts are copied from the Claude plugin cache -- which is already
        # claude-tagged. Without alternatives the URL edit finds neither the vendor form nor
        # the cursor form and fails the whole run.
        Alternatives = @(if ($Alternatives) { $Alternatives | ForEach-Object { Expand-AmEditText $_ } })
    }
}

# The three harnesses this stack wires, and the console path that tags their traffic.
# Single source of truth: the four installers this replaced each carried their own copy
# of the URL string.
$script:TsAmHosts = @(
    [pscustomobject]@{ Name = 'claude'; Label = 'Claude Code' }
    [pscustomobject]@{ Name = 'codex';  Label = 'Codex' }
    [pscustomobject]@{ Name = 'cursor'; Label = 'Cursor' }
)

function Get-TsAmAgentUrl([string]$Agent) {
    return "http://localhost:3111/_agent/$Agent"
}

# ---- the edits ---------------------------------------------------------------

function Get-AmHookEdits {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('claude', 'codex', 'cursor')][string]$Agent
    )

    $taggedUrl = Get-TsAmAgentUrl $Agent
    $edits = @()

    # 1. Tagged REST fallback. The env var normally supplies this; the fallback matters
    #    when a hook is launched without it, which is exactly when traffic would
    #    otherwise be recorded as an untagged Unknown host.
    $otherTagged = @(
        $script:TsAmHosts | Where-Object { $_.Name -ne $Agent } | ForEach-Object {
            "const REST_URL = process.env[`"AGENTMEMORY_URL`"] || `"$(Get-TsAmAgentUrl $_.Name)`";"
        }
    )
    $edits += New-AmEdit 'tagged REST_URL fallback' @('*') `
        'const REST_URL = process.env["AGENTMEMORY_URL"] || "http://localhost:3111";' `
        "const REST_URL = process.env[`"AGENTMEMORY_URL`"] || `"$taggedUrl`";" `
        -Alternatives $otherTagged

    # 2. Retrieval defaults on, with an explicit opt-out. AGENTMEMORY_INJECT_CONTEXT as
    #    a User env var only reaches processes started after it was set, so long-running
    #    shells and desktop apps kept launching hooks without it and every one of them
    #    returned early. Default-on removes that whole class of silent failure; set the
    #    variable to "false" to turn retrieval off deliberately.
    $edits += New-AmEdit 'context injection defaults on' @('session-start.mjs', 'pre-tool-use.mjs') `
        'const INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] === "true";' `
        'const INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] !== "false";'


    # 2b. Give pre-tool-use the project helpers the other hooks already have. Without
    #     them its /enrich request carries no project, so the console recorded that
    #     retrieval against a blank project while /context and /session/start were
    #     attributed correctly. Copied verbatim from post-tool-use.mjs so the resolved
    #     name is identical (git top-level basename, not the raw cwd leaf, which would
    #     disagree whenever an agent runs from a subdirectory).
    $edits += New-AmEdit 'pre-tool-use gains the project helpers' @('pre-tool-use.mjs') `
        ('//#region src/hooks/pre-tool-use.ts') `
        -Marker 'function resolveProject(cwd) {' `
        ('import { execSync } from "node:child_process";@N' +
         'import { basename } from "node:path";@N' +
         '//#region src/hooks/_project.ts@Nfunction resolveProject(cwd) {@N@Tconst explicit = process.env["AGENTMEMORY_PROJECT_NAME"];@N@Tif (explicit && explicit.trim()) return explicit.trim();@N@Tconst dir = cwd && cwd.trim() ? cwd : process.cwd();@N@Ttry {@N@T@Tconst top = execSync("git rev-parse --show-toplevel", {@N@T@T@Tcwd: dir,@N@T@T@Tstdio: [@N@T@T@T@T"ignore",@N@T@T@T@T"pipe",@N@T@T@T@T"ignore"@N@T@T@T],@N@T@T@Ttimeout: 500@N@T@T}).toString().trim();@N@T@Tif (top) return basename(top);@N@T} catch {}@N@Treturn basename(dir);@N}@Nfunction hookCwd(data) {@N@Tif (!data || typeof data !== "object") return void 0;@N@Tif (typeof data.cwd === "string" && data.cwd.trim()) return data.cwd;@N@Tconst roots = data.workspace_roots;@N@Tif (Array.isArray(roots)) {@N@T@Tfor (const root of roots) if (typeof root === "string" && root.trim()) return root;@N@T}@N@Tconst projectDir = process.env["DEVIN_PROJECT_DIR"] || process.env["CLAUDE_PROJECT_DIR"];@N@Tif (projectDir && projectDir.trim()) return projectDir;@N}@N//#endregion@N' +
         '//#region src/hooks/pre-tool-use.ts')

    # 2c. ...and use them, so file-path retrieval is project-attributed like the rest.
    $edits += New-AmEdit 'pre-tool-use enrich carries a project' @('pre-tool-use.mjs') `
        ('@Tconst project = typeof data.project === "string" && data.project.trim().length > 0 ? data.project.trim() : void 0;') `
        ('@Tconst project = typeof data.project === "string" && data.project.trim().length > 0 ? data.project.trim() : resolveProject(hookCwd(data) || process.cwd());')

    # Prompt-level retrieval, for every agent. This used to be Codex/Cursor-only on the
    # theory that Claude "already retrieves on file tools and at session start". It does
    # not, in the way that matters: /enrich fires only for the vendor allow-list
    # (edit/write/create/read/view/glob/grep), is excluded for Bash by both the hooks.json
    # matcher and the allow-list, and drops a Grep/Glob with no path argument. A
    # shell-heavy session therefore retrieved almost nothing -- measured live at 1041
    # captures against 250 /enrich and one /context (a compaction) over 5.7 hours, while
    # Codex, which has this edit, retrieved on every prompt. /agentmemory/context needs
    # only { sessionId, project }, so it is the one channel that works regardless of what
    # tools the turn happens to use.
    # 3. prompt-submit.mjs has no INJECT_CONTEXT of its own because upstream never
    #    retrieves from it.
    $edits += New-AmEdit 'prompt-submit learns the injection gate' @('prompt-submit.mjs') `
        'const SECRET = process.env["AGENTMEMORY_SECRET"] || "";' `
        ('const SECRET = process.env["AGENTMEMORY_SECRET"] || "";@N' +
         'const INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] !== "false";')

    # 4. Session/prompt-level retrieval. Upstream prompt-submit.mjs is write-only — it
    #    POSTs /observe and nothing else — despite the hook advertising "recalling
    #    relevant memories". /agentmemory/context needs only { sessionId, project }, no
    #    file paths, so this is the one retrieval channel that works for a Bash-heavy
    #    agent with no trustworthy structured path, and it reads nothing from the
    #    command. Same short timeout and swallow-and-exit-0 discipline as the other
    #    hooks, so a slow or absent server can never block a turn.
    $edits += New-AmEdit 'prompt-level context retrieval' @('prompt-submit.mjs') `
        ('@Tconst cwd = hookCwd(data) || process.cwd();@N' +
         '@Tfetch(`${REST_URL}/agentmemory/observe`, {') `
        ('@Tconst cwd = hookCwd(data) || process.cwd();@N' +
         '@Tif (INJECT_CONTEXT) try {@N' +
         '@T@Tconst amRes = await fetch(`${REST_URL}/agentmemory/context`, {@N' +
         '@T@T@Tmethod: "POST",@N' +
         '@T@T@Theaders: authHeaders(),@N' +
         '@T@T@Tbody: JSON.stringify({ sessionId, project: resolveProject(cwd) }),@N' +
         '@T@T@Tsignal: AbortSignal.timeout(2e3)@N' +
         '@T@T});@N' +
         '@T@Tif (amRes.ok) {@N' +
         '@T@T@Tconst amCtx = await amRes.json();@N' +
         '@T@T@Tif (amCtx.context) process.stdout.write(amCtx.context);@N' +
         '@T@T}@N' +
         '@T} catch {}@N' +
         '@Tfetch(`${REST_URL}/agentmemory/observe`, {')

    # Codex and Cursor drive a shell tool whose name the vendor allow-list does not
    # recognise, so they alone need the denylist inversion below. Claude's PreToolUse
    # uses that allow-list plus a hooks.json matcher -- a different mechanism, which this
    # edit does not fit.
    if ($Agent -ne 'claude') {
        # 5. Codex emits mostly "Bash", which the vendor allow-list
        #    (edit/write/create/read/view/glob/grep) excluded, so pre-tool-use retrieval
        #    never fired for Codex at all. Inverting to a shell denylist supports whatever
        #    file-tool names Codex actually emits without having to enumerate them, and
        #    without ever inspecting a command string: the existing "no structured path
        #    field, no request" rule below is untouched, so a tool that carries no path
        #    still costs nothing. Shell-family tools are served by prompt-level retrieval
        #    (edits 3 and 4) instead, where the prompt is trustworthy input and no command
        #    parsing is required.
        $edits += New-AmEdit 'shell denylist replaces file-tool allow-list' @('pre-tool-use.mjs') `
            ('if (![@N@T@T"edit",@N@T@T"write",@N@T@T"create",@N@T@T"read",@N@T@T"view",@N@T@T"glob",@N@T@T"grep"@N@T].includes(normalizedToolName)) return;') `
            ('if ([@N@T@T"bash",@N@T@T"shell",@N@T@T"sh",@N@T@T"cmd",@N@T@T"powershell",@N@T@T"pwsh",@N@T@T"exec",@N@T@T"local_shell",@N@T@T"run_command",@N@T@T"terminal"@N@T].includes(normalizedToolName)) return;')
    }

    # 6. Stale-secret recovery, every script. See the JS comment for the incident.
    $edits += New-AmEdit 'stale secret recovery' @('*') `
        'function authHeaders() {' `
        ('// terminal-stack: recover from a stale AGENTMEMORY_SECRET.@N' +
         '// A User environment variable only reaches processes started after it was set, so a@N' +
         '// long-lived shell keeps the pre-rotation secret and every request from that session@N' +
         '// 401s -- silently, because /observe swallows errors in .catch() and retrieval@N' +
         '// discards non-2xx behind if (res.ok). That cost 56 consecutive captures on@N' +
         '// 2026-08-21, with nothing in any log. On a 401 the authoritative value is re-read@N' +
         '// from the registry and the request retried once, then cached for this process.@N' +
         '// Wrapping fetch rather than every call site keeps this to one edit across six@N' +
         '// scripts, and it fails open: any error here returns the original response.@N' +
         'let amFreshSecret = null;@N' +
         'async function amRegistrySecret() {@N' +
         '@Tif (amFreshSecret !== null) return amFreshSecret;@N' +
         '@TamFreshSecret = "";@N' +
         '@Ttry {@N' +
         '@T@Tconst { execSync } = await import("node:child_process");@N' +
         '@T@Tconst out = execSync(''reg query "HKCU\\Environment" /v AGENTMEMORY_SECRET'', {@N' +
         '@T@T@Tstdio: ["ignore", "pipe", "ignore"],@N' +
         '@T@T@Ttimeout: 2e3@N' +
         '@T@T}).toString();@N' +
         '@T@Tfor (const line of out.split("\n")) {@N' +
         '@T@T@Tif (!line.includes("AGENTMEMORY_SECRET")) continue;@N' +
         '@T@T@Tconst cells = line.split(String.fromCharCode(9)).join(" ").trim().split(" ").filter(Boolean);@N' +
         '@T@T@Tif (cells.length) amFreshSecret = cells[cells.length - 1].trim();@N' +
         '@T@T@Tbreak;@N' +
         '@T@T}@N' +
         '@T} catch {}@N' +
         '@Treturn amFreshSecret;@N' +
         '}@N' +
         'const amBaseFetch = globalThis.fetch;@N' +
         'globalThis.fetch = async function (input, init) {@N' +
         '@Tconst res = await amBaseFetch(input, init);@N' +
         '@Ttry {@N' +
         '@T@Tif (res.status !== 401) return res;@N' +
         '@T@Tconst headers = init && init.headers;@N' +
         '@T@Tif (!headers || typeof headers !== "object") return res;@N' +
         '@T@Tconst fresh = await amRegistrySecret();@N' +
         '@T@T// Also covers a secret missing from the process entirely, not just a stale one.@N' +
         '@T@Tif (!fresh || headers["Authorization"] === "Bearer " + fresh) return res;@N' +
         '@T@Treturn await amBaseFetch(input, { ...init, headers: { ...headers, Authorization: "Bearer " + fresh } });@N' +
         '@T} catch {}@N' +
         '@Treturn res;@N' +
         '};@N' +
         'function authHeaders() {@N')

    # LAST, deliberately: the pre-tool-use project-helper edit above anchors on the
    # shebang line too, and must consume its anchor before this one widens it.
    $edits += New-AmEdit 'duplicate-invocation guard helper' @('*') `
        ('#!/usr/bin/env node@N') `
        ('#!/usr/bin/env node@N' +
         'import * as amFs from "node:fs";@N' +
         'import * as amPath from "node:path";@N' +
         'import * as amOs from "node:os";@N' +
         'import * as amCrypto from "node:crypto";@N' +
         '// terminal-stack: drop the duplicate hook invocation Codex registrations@N// produce. ~/.codex/hooks.json (Desktop) and the plugin hooks.codex.json (CLI)@N// both fire for one event, so every observation was stored twice and every@N// retrieval was requested twice - Codex received the same context block twice per@N// prompt. Codex has no hooks-only toggle, silently ignores unknown plugin config@N// keys, and dropping either registration costs Desktop or CLI capture, so the@N// duplicate is dropped here, before any request is made.@Nconst AM_DEDUPE_TTL_MS = (() => {@N@Tconst raw = Number(process.env["AGENTMEMORY_DEDUPE_TTL_MS"]);@N@Treturn Number.isFinite(raw) && raw >= 0 ? raw : 1500;@N})();@Nfunction amDedupeDir() {@N@Tconst base = process.env["LOCALAPPDATA"] || amOs.tmpdir();@N@Treturn amPath.join(base, "terminal-stack", "agentmemory-dedupe");@N}@Nfunction amDuplicate(data) {@N@T// Fails open on every error path: a broken guard degrades to the old@N@T// duplicate-but-working behaviour rather than silently dropping capture.@N@Tif (AM_DEDUPE_TTL_MS <= 0) return false;@N@Ttry {@N@T@T// Excludes every timestamp deliberately: each hook process stamps its own,@N@T@T// and that is the only field that differs between the two registrations.@N@T@Tconst key = amCrypto.createHash("sha1").update(JSON.stringify([@N@T@T@Tdata && data.hook_event_name,@N@T@T@Tdata && (data.session_id || data.sessionId || data.conversation_id),@N@T@T@Tdata && data.cwd,@N@T@T@Tdata && (data.tool_name || data.toolName),@N@T@T@Tdata && (data.tool_input || data.toolArgs),@N@T@T@Tdata && (data.prompt || data.userPrompt)@N@T@T])).digest("hex");@N@T@Tconst dir = amDedupeDir();@N@T@TamFs.mkdirSync(dir, { recursive: true });@N@T@Tconst marker = amPath.join(dir, key);@N@T@Tconst now = Date.now();@N@T@Tlet duplicate = false;@N@T@Ttry {@N@T@T@T// Atomic exclusive create is the whole mutex. A read-then-write check would@N@T@T@T// let two processes 1ms apart both pass, which is the race this exists to fix.@N@T@T@TamFs.closeSync(amFs.openSync(marker, "wx"));@N@T@T} catch (err) {@N@T@T@Tif (err && err.code === "EEXIST") {@N@T@T@T@Tlet age = Infinity;@N@T@T@T@Ttry { age = now - amFs.statSync(marker).mtimeMs; } catch {}@N@T@T@T@Tif (age <= AM_DEDUPE_TTL_MS) duplicate = true;@N@T@T@T@Telse { try { amFs.unlinkSync(marker); amFs.closeSync(amFs.openSync(marker, "wx")); } catch {} }@N@T@T@T}@N@T@T}@N@T@T// Opportunistic sweep so the directory cannot grow without bound.@N@T@Ttry {@N@T@T@Tfor (const name of amFs.readdirSync(dir)) {@N@T@T@T@Tconst stale = amPath.join(dir, name);@N@T@T@T@Ttry { if (now - amFs.statSync(stale).mtimeMs > 6e4) amFs.unlinkSync(stale); } catch {}@N@T@T@T}@N@T@T} catch {}@N@T@Treturn duplicate;@N@T} catch {}@N@Treturn false;@N}@N')

    # One anchor that exists exactly once in all six hook scripts, right after the
    # payload is parsed and before anything is sent.
    $edits += New-AmEdit 'duplicate-invocation guard' @('*') `
        ('@Tif (isSdkChildContext(data)) return;') `
        ('@Tif (isSdkChildContext(data)) return;@N@Tif (amDuplicate(data)) return;')

    return $edits
}

# ---- application ------------------------------------------------------------

function Convert-AmToCrlf([string]$text) {
    return (($text -replace "`r`n", "`n") -replace "`n", "`r`n")
}

# Returns 'applied', 'already', or throws when the vendor layout no longer matches.
function Set-AmEditInText([ref]$Text, $Edit, [string]$ScriptName) {
    foreach ($marker in @($Edit.Marker, (Convert-AmToCrlf $Edit.Marker))) {
        if ($Text.Value.Contains($marker)) { return 'already' }
    }
    foreach ($candidate in (@($Edit.Old) + @($Edit.Alternatives))) {
        foreach ($form in @($candidate, (Convert-AmToCrlf $candidate))) {
            if ($Text.Value.Contains($form)) {
                $newForm = if ($form -eq $candidate) { $Edit.New } else { Convert-AmToCrlf $Edit.New }
                $Text.Value = $Text.Value.Replace($form, $newForm)
                return 'applied'
            }
        }
    }
    throw "$($Edit.Label): neither the vendor form nor the patched form was found in $ScriptName; the AgentMemory layout has changed and this edit needs updating"
}

function Invoke-AmHookEdits {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string[]]$ScriptPaths,
        [Parameter(Mandatory)][object[]]$Edits,
        [switch]$Execute,
        [switch]$Undo,
        [string]$BackupSuffix = '.agent007memory-original',
        [scriptblock]$OnStep,
        [scriptblock]$OnInfo
    )

    $say  = { param($m) if ($OnInfo) { & $OnInfo $m } else { Write-Host "       $m" -ForegroundColor DarkGray } }
    $step = { param($m) if ($OnStep) { & $OnStep $m } else { Write-Host "[do]   $m" } }

    foreach ($scriptPath in $ScriptPaths) {
        $name = Split-Path -Leaf $scriptPath
        $backupPath = "$scriptPath$BackupSuffix"

        if ($Undo) {
            if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
                & $say "$name has no backup - left untouched"
                continue
            }
            & $step "restore $name from its backup"
            if ($Execute) { Copy-Item -LiteralPath $backupPath -Destination $scriptPath -Force }
            continue
        }

        $applicable = @($Edits | Where-Object { $_.Scripts -contains '*' -or $_.Scripts -contains $name })
        if ($applicable.Count -eq 0) { continue }

        $original = Get-Content -LiteralPath $scriptPath -Raw
        $text = $original
        $changed = @()
        foreach ($edit in $applicable) {
            $ref = [ref]$text
            $outcome = Set-AmEditInText $ref $edit $name
            $text = $ref.Value
            if ($outcome -eq 'applied') { $changed += $edit.Label }
        }

        if ($changed.Count -eq 0) {
            & $say "$name already carries all $($applicable.Count) edit(s)"
            continue
        }

        & $step "patch ${name}: $($changed -join '; ')"
        if ($Execute) {
            if (-not (Test-Path -LiteralPath $backupPath)) {
                Copy-Item -LiteralPath $scriptPath -Destination $backupPath
            }
            Set-Content -LiteralPath $scriptPath -Value $text -Encoding utf8 -NoNewline
        }
    }
}

function Test-AmHookEdits {
    # Returns the labels that are NOT present, so callers can verify after applying and
    # so check-capture.ps1 can detect a plugin upgrade having reverted them.
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string[]]$ScriptPaths,
        [Parameter(Mandatory)][object[]]$Edits
    )

    $missing = @()
    foreach ($scriptPath in $ScriptPaths) {
        if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
            $missing += "$(Split-Path -Leaf $scriptPath) (missing file)"
            continue
        }
        $name = Split-Path -Leaf $scriptPath
        $text = Get-Content -LiteralPath $scriptPath -Raw
        foreach ($edit in @($Edits | Where-Object { $_.Scripts -contains '*' -or $_.Scripts -contains $name })) {
            if (-not ($text.Contains($edit.Marker) -or $text.Contains((Convert-AmToCrlf $edit.Marker)))) {
                $missing += "${name}: $($edit.Label)"
            }
        }
    }
    # -NoEnumerate so an empty result is still an array and callers can use .Count
    Write-Output -NoEnumerate $missing
}
