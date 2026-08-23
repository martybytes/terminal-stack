#!/usr/bin/env bash
# _agentmemory.sh — the deployment edits applied to AgentMemory's bundled hook
# scripts, plus the engine that applies them. POSIX twin of _agentmemory.ps1.
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.
#
# Why a twin rather than a shim: the .ps1 keys off $env:USERPROFILE and drives
# cmd.exe; on macOS and Linux there is no host-side wiring at all, so the stack
# serves and searches but never captures — silently, because every hook does
# fetch(...).catch(() => {}) and exits 0.
#
# Edits keep the .ps1's @T (tab) / @N (newline) encoding on purpose: it means
# this file needs no literal tabs and no escaping of the JavaScript's own $ and
# backticks, and a reviewer can diff the two files' edit text directly.
#
# Two things differ from the .ps1 by necessity, and only two:
#   1. the stale-secret recovery reads the 0600 cache under XDG_CONFIG_HOME
#      instead of `reg query HKCU\Environment`, which on Unix throws, is caught,
#      and leaves the recovery a permanent no-op;
#   2. hook commands are a POSIX `VAR=value node "<path>"` prefix instead of a
#      cmd.exe `set X=…&&` chain, which in a hooks file on a Mac fails silently
#      — precisely the failure this wiring exists to prevent.
#
# Every edit is idempotent (already-applied is detected) and fail-fast: neither
# the old nor the new form present means the vendor layout moved, which is an
# error rather than something to skip.

# ---- edit records -------------------------------------------------------------
# bash 3.2: no associative arrays. Parallel indexed arrays, one slot per edit.
AM_EDIT_N=0
AM_EDIT_LABEL=(); AM_EDIT_SCRIPTS=(); AM_EDIT_OLD=(); AM_EDIT_NEW=()
AM_EDIT_MARKER=(); AM_EDIT_ALTS=()

am_reset_edits() {
    AM_EDIT_N=0
    AM_EDIT_LABEL=(); AM_EDIT_SCRIPTS=(); AM_EDIT_OLD=(); AM_EDIT_NEW=()
    AM_EDIT_MARKER=(); AM_EDIT_ALTS=()
}

# am_add_edit <label> <scripts> <old> <new> [marker] [alternatives...]
#   scripts      — space-separated basenames, or '*' for every script
#   marker       — what "already applied?" tests when <new> is not a reliable
#                  probe. Defaults to <new>. The duplicate-guard edit inserts
#                  imports between the shebang and the first vendor import,
#                  which made the project-helper edit look permanently missing
#                  and would have had the sync rewrite every script every run.
#   alternatives — other forms this edit may rewrite from. Cursor has no
#                  agentmemory package, so its scripts are copied from the
#                  *Claude* cache and are already claude-tagged; without these
#                  the URL edit finds neither form and fails the whole run.
am_add_edit() {
    local i=$AM_EDIT_N
    AM_EDIT_LABEL[$i]="$1"
    AM_EDIT_SCRIPTS[$i]="$2"
    AM_EDIT_OLD[$i]="$3"
    AM_EDIT_NEW[$i]="$4"
    AM_EDIT_MARKER[$i]="${5:-$4}"
    shift 5 2>/dev/null || shift $#
    local alts=""
    for a in "$@"; do alts="${alts}${a}"$'\x01'; done
    AM_EDIT_ALTS[$i]="$alts"
    AM_EDIT_N=$((i + 1))
}

# The three harnesses this stack wires, and the console path that tags their
# traffic. Single source of truth for the URL.
AM_HOSTS="claude codex cursor"

am_agent_url() { printf 'http://localhost:3111/_agent/%s\n' "$1"; }

# ---- the edits ----------------------------------------------------------------

# am_build_edits <agent>
am_build_edits() {
    local agent="$1" tagged other
    tagged="$(am_agent_url "$agent")"
    am_reset_edits

    # 1. Tagged REST fallback. The env var normally supplies this; the fallback
    #    matters when a hook is launched without it, which is exactly when
    #    traffic would otherwise be recorded as an untagged Unknown host.
    local alts=()
    for other in $AM_HOSTS; do
        [ "$other" = "$agent" ] && continue
        alts+=("const REST_URL = process.env[\"AGENTMEMORY_URL\"] || \"$(am_agent_url "$other")\";")
    done
    am_add_edit 'tagged REST_URL fallback' '*' \
        'const REST_URL = process.env["AGENTMEMORY_URL"] || "http://localhost:3111";' \
        "const REST_URL = process.env[\"AGENTMEMORY_URL\"] || \"$tagged\";" \
        "const REST_URL = process.env[\"AGENTMEMORY_URL\"] || \"$tagged\";" \
        "${alts[@]}"

    # 2. Retrieval defaults on, with an explicit opt-out. AGENTMEMORY_INJECT_CONTEXT
    #    as an exported variable only reaches processes started after it was set,
    #    so long-running shells and desktop apps kept launching hooks without it
    #    and every one returned early. Default-on removes that whole class of
    #    silent failure; set it to "false" to turn retrieval off deliberately.
    am_add_edit 'context injection defaults on' 'session-start.mjs pre-tool-use.mjs' \
        'const INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] === "true";' \
        'const INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] !== "false";'

    # 2b. Give pre-tool-use the project helpers the other hooks already have.
    #     Without them its /enrich request carries no project, so the console
    #     recorded that retrieval against a blank project while /context and
    #     /session/start were attributed correctly. Copied verbatim from
    #     post-tool-use.mjs so the resolved name is identical (git top-level
    #     basename, not the raw cwd leaf, which disagrees whenever an agent runs
    #     from a subdirectory).
    am_add_edit 'pre-tool-use gains the project helpers' 'pre-tool-use.mjs' \
        '//#region src/hooks/pre-tool-use.ts' \
        'import { execSync } from "node:child_process";@Nimport { basename } from "node:path";@N//#region src/hooks/_project.ts@Nfunction resolveProject(cwd) {@N@Tconst explicit = process.env["AGENTMEMORY_PROJECT_NAME"];@N@Tif (explicit && explicit.trim()) return explicit.trim();@N@Tconst dir = cwd && cwd.trim() ? cwd : process.cwd();@N@Ttry {@N@T@Tconst top = execSync("git rev-parse --show-toplevel", {@N@T@T@Tcwd: dir,@N@T@T@Tstdio: [@N@T@T@T@T"ignore",@N@T@T@T@T"pipe",@N@T@T@T@T"ignore"@N@T@T@T],@N@T@T@Ttimeout: 500@N@T@T}).toString().trim();@N@T@Tif (top) return basename(top);@N@T} catch {}@N@Treturn basename(dir);@N}@Nfunction hookCwd(data) {@N@Tif (!data || typeof data !== "object") return void 0;@N@Tif (typeof data.cwd === "string" && data.cwd.trim()) return data.cwd;@N@Tconst roots = data.workspace_roots;@N@Tif (Array.isArray(roots)) {@N@T@Tfor (const root of roots) if (typeof root === "string" && root.trim()) return root;@N@T}@N@Tconst projectDir = process.env["DEVIN_PROJECT_DIR"] || process.env["CLAUDE_PROJECT_DIR"];@N@Tif (projectDir && projectDir.trim()) return projectDir;@N}@N//#endregion@N//#region src/hooks/pre-tool-use.ts' \
        'function resolveProject(cwd) {'

    # 2c. ...and use them, so file-path retrieval is project-attributed.
    am_add_edit 'pre-tool-use enrich carries a project' 'pre-tool-use.mjs' \
        '@Tconst project = typeof data.project === "string" && data.project.trim().length > 0 ? data.project.trim() : void 0;' \
        '@Tconst project = typeof data.project === "string" && data.project.trim().length > 0 ? data.project.trim() : resolveProject(hookCwd(data) || process.cwd());'

    # 3. Prompt-level retrieval, for every agent. This was Codex/Cursor-only on
    #    the theory that Claude already retrieves on file tools and at session
    #    start. It does not, in the way that matters: /enrich fires only for the
    #    vendor allow-list, is excluded for Bash by both the hooks.json matcher
    #    and the allow-list, and drops a Grep/Glob with no path argument. A
    #    shell-heavy session therefore retrieved almost nothing — measured live
    #    at 1041 captures against one /context in 5.7 hours.
    am_add_edit 'prompt-submit learns the injection gate' 'prompt-submit.mjs' \
        'const SECRET = process.env["AGENTMEMORY_SECRET"] || "";' \
        'const SECRET = process.env["AGENTMEMORY_SECRET"] || "";@Nconst INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] !== "false";'

    # 4. /agentmemory/context needs only { sessionId, project }, no file paths,
    #    so it is the one retrieval channel that works for a shell-heavy agent,
    #    and it reads nothing from the command. Same short timeout and
    #    swallow-and-exit-0 discipline as the other hooks, so a slow or absent
    #    server can never block a turn.
    am_add_edit 'prompt-level context retrieval' 'prompt-submit.mjs' \
        '@Tconst cwd = hookCwd(data) || process.cwd();@N@Tfetch(`${REST_URL}/agentmemory/observe`, {' \
        '@Tconst cwd = hookCwd(data) || process.cwd();@N@Tif (INJECT_CONTEXT) try {@N@T@Tconst amRes = await fetch(`${REST_URL}/agentmemory/context`, {@N@T@T@Tmethod: "POST",@N@T@T@Theaders: authHeaders(),@N@T@T@Tbody: JSON.stringify({ sessionId, project: resolveProject(cwd) }),@N@T@T@Tsignal: AbortSignal.timeout(2e3)@N@T@T});@N@T@Tif (amRes.ok) {@N@T@T@Tconst amCtx = await amRes.json();@N@T@T@Tif (amCtx.context) process.stdout.write(amCtx.context);@N@T@T}@N@T} catch {}@N@Tfetch(`${REST_URL}/agentmemory/observe`, {'

    # 5. Codex and Cursor drive a shell tool the vendor allow-list does not
    #    recognise, so they alone need the denylist inversion. Claude's
    #    PreToolUse uses that allow-list plus a hooks.json matcher — a different
    #    mechanism, which this edit does not fit.
    if [ "$agent" != claude ]; then
        am_add_edit 'shell denylist replaces file-tool allow-list' 'pre-tool-use.mjs' \
            'if (![@N@T@T"edit",@N@T@T"write",@N@T@T"create",@N@T@T"read",@N@T@T"view",@N@T@T"glob",@N@T@T"grep"@N@T].includes(normalizedToolName)) return;' \
            'if ([@N@T@T"bash",@N@T@T"shell",@N@T@T"sh",@N@T@T"cmd",@N@T@T"powershell",@N@T@T"pwsh",@N@T@T"exec",@N@T@T"local_shell",@N@T@T"run_command",@N@T@T"terminal"@N@T].includes(normalizedToolName)) return;'
    fi

    # 6. Stale-secret recovery, every script.
    #    UNIX FORM: the .ps1 re-reads HKCU\Environment here. On Unix that throws,
    #    is caught, and leaves the recovery a permanent no-op — so this reads the
    #    0600 cache docker-local maintains instead. Same fail-open discipline:
    #    any error returns the original response.
    am_add_edit 'stale secret recovery' '*' \
        'function authHeaders() {' \
        '// terminal-stack: recover from a stale AGENTMEMORY_SECRET.@N// An exported variable only reaches processes started after it was set, so a@N// long-lived shell keeps the pre-rotation secret and every request from that@N// session 401s -- silently, because /observe swallows errors in .catch() and@N// retrieval discards non-2xx behind if (res.ok). That cost 56 consecutive@N// captures on 2026-08-21, with nothing in any log. On a 401 the authoritative@N// value is re-read from the 0600 cache and the request retried once, then@N// cached for this process. Wrapping fetch rather than every call site keeps@N// this to one edit across six scripts, and it fails open.@Nlet amFreshSecret = null;@Nasync function amStoredSecret() {@N@Tif (amFreshSecret !== null) return amFreshSecret;@N@TamFreshSecret = "";@N@Ttry {@N@T@Tconst { readFileSync } = await import("node:fs");@N@T@Tconst { join } = await import("node:path");@N@T@Tconst { homedir } = await import("node:os");@N@T@Tconst base = process.env["XDG_CONFIG_HOME"] || join(homedir(), ".config");@N@T@Tconst raw = readFileSync(join(base, "docker-local", "agentmemory.secret"), "utf8").trim();@N@T@Tif (raw) amFreshSecret = raw;@N@T} catch {}@N@Treturn amFreshSecret;@N}@Nconst amBaseFetch = globalThis.fetch;@NglobalThis.fetch = async function (input, init) {@N@Tconst res = await amBaseFetch(input, init);@N@Ttry {@N@T@Tif (res.status !== 401) return res;@N@T@Tconst headers = init && init.headers;@N@T@Tif (!headers || typeof headers !== "object") return res;@N@T@Tconst fresh = await amStoredSecret();@N@T@T// Also covers a secret missing from the process entirely, not just a stale one.@N@T@Tif (!fresh || headers["Authorization"] === "Bearer " + fresh) return res;@N@T@Treturn await amBaseFetch(input, { ...init, headers: { ...headers, Authorization: "Bearer " + fresh } });@N@T} catch {}@N@Treturn res;@N};@Nfunction authHeaders() {@N'

    # LAST, deliberately: the pre-tool-use project-helper edit above anchors on
    # the shebang line too, and must consume its anchor before this one widens it.
    am_add_edit 'duplicate-invocation guard helper' '*' \
        '#!/usr/bin/env node@N' \
        '#!/usr/bin/env node@Nimport * as amFs from "node:fs";@Nimport * as amPath from "node:path";@Nimport * as amOs from "node:os";@Nimport * as amCrypto from "node:crypto";@N// terminal-stack: drop the duplicate hook invocation Codex registrations@N// produce. hooks.json (Desktop) and the plugin hooks.codex.json (CLI) both fire@N// for one event, so every observation was stored twice and every retrieval was@N// requested twice - Codex received the same context block twice per prompt.@N// Codex has no hooks-only toggle, silently ignores unknown plugin config keys,@N// and dropping either registration costs Desktop or CLI capture, so the@N// duplicate is dropped here, before any request is made.@Nconst AM_DEDUPE_TTL_MS = (() => {@N@Tconst raw = Number(process.env["AGENTMEMORY_DEDUPE_TTL_MS"]);@N@Treturn Number.isFinite(raw) && raw >= 0 ? raw : 1500;@N})();@Nfunction amDedupeDir() {@N@Tconst base = process.env["LOCALAPPDATA"] || amOs.tmpdir();@N@Treturn amPath.join(base, "terminal-stack", "agentmemory-dedupe");@N}@Nfunction amDuplicate(data) {@N@T// Fails open on every error path: a broken guard degrades to the old@N@T// duplicate-but-working behaviour rather than silently dropping capture.@N@Tif (AM_DEDUPE_TTL_MS <= 0) return false;@N@Ttry {@N@T@T// Excludes every timestamp deliberately: each hook process stamps its own,@N@T@T// and that is the only field that differs between the two registrations.@N@T@Tconst key = amCrypto.createHash("sha1").update(JSON.stringify([@N@T@T@Tdata && data.hook_event_name,@N@T@T@Tdata && (data.session_id || data.sessionId || data.conversation_id),@N@T@T@Tdata && data.cwd,@N@T@T@Tdata && (data.tool_name || data.toolName),@N@T@T@Tdata && (data.tool_input || data.toolArgs),@N@T@T@Tdata && (data.prompt || data.userPrompt)@N@T@T])).digest("hex");@N@T@Tconst dir = amDedupeDir();@N@T@TamFs.mkdirSync(dir, { recursive: true });@N@T@Tconst marker = amPath.join(dir, key);@N@T@Tconst now = Date.now();@N@T@Tlet duplicate = false;@N@T@Ttry {@N@T@T@T// Atomic exclusive create is the whole mutex. A read-then-write check@N@T@T@T// would let two processes 1ms apart both pass, which is the race this fixes.@N@T@T@TamFs.closeSync(amFs.openSync(marker, "wx"));@N@T@T} catch (err) {@N@T@T@Tif (err && err.code === "EEXIST") {@N@T@T@T@Tlet age = Infinity;@N@T@T@T@Ttry { age = now - amFs.statSync(marker).mtimeMs; } catch {}@N@T@T@T@Tif (age <= AM_DEDUPE_TTL_MS) duplicate = true;@N@T@T@T@Telse { try { amFs.unlinkSync(marker); amFs.closeSync(amFs.openSync(marker, "wx")); } catch {} }@N@T@T@T}@N@T@T}@N@T@T// Opportunistic sweep so the directory cannot grow without bound.@N@T@Ttry {@N@T@T@Tfor (const name of amFs.readdirSync(dir)) {@N@T@T@T@Tconst stale = amPath.join(dir, name);@N@T@T@T@Ttry { if (now - amFs.statSync(stale).mtimeMs > 6e4) amFs.unlinkSync(stale); } catch {}@N@T@T@T}@N@T@T} catch {}@N@T@Treturn duplicate;@N@T} catch {}@N@Treturn false;@N}@N'

    # One anchor that exists exactly once in all six hook scripts, right after
    # the payload is parsed and before anything is sent.
    am_add_edit 'duplicate-invocation guard' '*' \
        '@Tif (isSdkChildContext(data)) return;' \
        '@Tif (isSdkChildContext(data)) return;@N@Tif (amDuplicate(data)) return;'
}

# ---- application --------------------------------------------------------------
# The matching is literal substring replace over multi-KB, multi-line JavaScript,
# in both LF and CRLF forms. bash cannot do that safely: ${x//a/b} treats the
# needle as a glob, and sed is line-oriented and appends a trailing newline to a
# file that lacked one. python3 is already this repo's answer for structured
# rewrites (json_get in ts-agents.sh), so the engine lives there and the edit
# text stays here, diffable against the .ps1.
#
# Records reach python NUL-delimited: six fields per edit, alternatives joined
# by \x01. Nothing in JavaScript source contains either byte.
am_write_edits() {
    local out="$1" i
    : > "$out"
    for ((i = 0; i < AM_EDIT_N; i++)); do
        printf '%s\0%s\0%s\0%s\0%s\0%s\0' \
            "${AM_EDIT_LABEL[$i]}" "${AM_EDIT_SCRIPTS[$i]}" "${AM_EDIT_OLD[$i]}" \
            "${AM_EDIT_NEW[$i]}" "${AM_EDIT_MARKER[$i]}" "${AM_EDIT_ALTS[$i]}" >> "$out"
    done
}

# am_engine <mode> <edits-file> <backup-suffix> <script-path>...
#   mode: check | preview | apply | undo-preview | undo-apply
# Emits TAB-separated "KIND<TAB>text" lines: STEP, INFO, MISS, ERR.
# Exit 0 normally; 3 when an edit's anchor is gone (the vendor layout moved).
am_engine() {
    python3 - "$@" <<'PY'
import os, shutil, sys

mode, edits_path, backup_suffix = sys.argv[1], sys.argv[2], sys.argv[3]
paths = sys.argv[4:]

def expand(t):
    return t.replace("@T", "\t").replace("@N", "\n")

def crlf(t):
    return t.replace("\r\n", "\n").replace("\n", "\r\n")

raw = open(edits_path, "rb").read()
fields = raw.split(b"\0")[:-1] if raw else []
edits = []
for i in range(0, len(fields), 6):
    label, scripts, old, new, marker, alts = (f.decode("utf-8") for f in fields[i:i + 6])
    edits.append({
        "label": label,
        "scripts": scripts.split(),
        "old": expand(old),
        "new": expand(new),
        "marker": expand(marker),
        "alts": [expand(a) for a in alts.split("\x01") if a],
    })

def say(kind, text):
    sys.stdout.write("%s\t%s\n" % (kind, text))

def applies_to(edit, name):
    return "*" in edit["scripts"] or name in edit["scripts"]

def apply_one(text, edit, name, file_crlf):
    """-> (text, 'already'|'applied'); raises when the vendor layout moved.

    Inserted text follows the FILE's line endings, not the matched form's. A
    single-line anchor like `function authHeaders() {` is byte-identical in both
    forms, so "which form matched" cannot tell them apart — deciding that way
    injects LF blocks into a CRLF file and leaves it mixed.
    """
    for m in (edit["marker"], crlf(edit["marker"])):
        if m in text:
            return text, "already"
    for cand in [edit["old"]] + edit["alts"]:
        for form in (cand, crlf(cand)):
            if form in text:
                new = crlf(edit["new"]) if file_crlf else edit["new"]
                return text.replace(form, new), "applied"
    raise LookupError(
        "%s: neither the vendor form nor the patched form was found in %s; the "
        "AgentMemory layout has changed and this edit needs updating"
        % (edit["label"], name))

undo = mode.startswith("undo")
execute = mode in ("apply", "undo-apply")
rc = 0

for path in paths:
    name = os.path.basename(path)
    backup = path + backup_suffix

    if mode == "check":
        if not os.path.isfile(path):
            say("MISS", "%s (missing file)" % name)
            continue
        # newline="" — no universal-newline translation. Without it a CRLF
        # vendor file reads as LF, so the CRLF marker check never matches.
        text = open(path, encoding="utf-8", newline="").read()
        for edit in (e for e in edits if applies_to(e, name)):
            if edit["marker"] not in text and crlf(edit["marker"]) not in text:
                say("MISS", "%s: %s" % (name, edit["label"]))
        continue

    if undo:
        if not os.path.isfile(backup):
            say("INFO", "%s has no backup - left untouched" % name)
            continue
        say("STEP", "restore %s from its backup" % name)
        if execute:
            shutil.copyfile(backup, path)
        continue

    applicable = [e for e in edits if applies_to(e, name)]
    if not applicable:
        continue
    # newline="" — see the check branch above. Reading with translation on
    # would rewrite every CRLF vendor file to LF wholesale on the first patch.
    text = open(path, encoding="utf-8", newline="").read()
    # A vendor file is CRLF (the ~/.codex copies) or LF (the plugin cache).
    # Decide once, from the file, and insert to match.
    file_crlf = "\r\n" in text
    changed = []
    try:
        for edit in applicable:
            text, outcome = apply_one(text, edit, name, file_crlf)
            if outcome == "applied":
                changed.append(edit["label"])
    except LookupError as exc:
        say("ERR", str(exc))
        rc = 3
        continue

    if not changed:
        say("INFO", "%s already carries all %d edit(s)" % (name, len(applicable)))
        continue

    say("STEP", "patch %s: %s" % (name, "; ".join(changed)))
    if execute:
        # Back up the pristine vendor file once, never the already-patched one.
        if not os.path.exists(backup):
            shutil.copyfile(path, backup)
        # Write byte-exact: no trailing newline is added to a file that lacked one.
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

sys.exit(rc)
PY
}
