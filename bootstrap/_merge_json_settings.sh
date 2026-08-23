#!/usr/bin/env bash
# _merge_json_settings.sh — the JSONC key-splice engine behind every settings
# file this stack part-owns. POSIX twin of _merge_json_settings.ps1.
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.
#
# The live file is edited TEXTUALLY, one top-level key at a time. Re-serialising
# the whole file would delete every // comment the user wrote and reflow their
# formatting, so values are spliced into the raw text and every byte we do not
# own is left alone. That is also what lets a part-owned file keep the keys its
# own app writes — Claude Code's model, enabledPlugins, permissions, env — across
# a sync. Whole-file copying this class of file is how the agentmemory plugin got
# silently disabled once already.

# ts_json_backup_path <path> <stamp> — repo convention: <path>.bak.YYYYMMDD, then
# .1/.2 on a same-day re-run. Never clobbers a same-day backup.
ts_json_backup_path() {
    local dst="$1" stamp="$2" base bak n
    base="$dst.bak.$stamp"; bak="$base"; n=1
    while [ -e "$bak" ]; do bak="$base.$n"; n=$((n + 1)); done
    printf '%s\n' "$bak"
}

# ts_merge_json_key <live-path> <key> <value-json> <label>
# Splices one top-level key's value into the live file, textually. Creates the
# file when absent. Prints "changed" or "same" on stdout; non-zero on a parse
# failure, in which case the live file is left exactly as it was.
ts_merge_json_key() {
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, os, sys

path, key, value_text, label = sys.argv[1:5]

def string_end(t, i):
    """i points at the opening quote; return the index just past the closer."""
    i += 1
    while i < len(t):
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        i += 1
    return -1

def trivia_end(t, i):
    """Skip whitespace and // or /* */ comments. PowerShell's Newtonsoft parser
    tolerates both, so we must not strip them — only step over them."""
    while i < len(t):
        c = t[i]
        if c in " \t\r\n":
            i += 1
        elif t.startswith("//", i):
            j = t.find("\n", i)
            i = len(t) if j < 0 else j
        elif t.startswith("/*", i):
            j = t.find("*/", i)
            i = len(t) if j < 0 else j + 2
        else:
            break
    return i

def value_end(t, i):
    """i points at the first char of a value; return the index just past it."""
    i = trivia_end(t, i)
    if i >= len(t):
        return -1
    c = t[i]
    if c == '"':
        return string_end(t, i)
    if c in "{[":
        close = "}" if c == "{" else "]"
        depth = 0
        while i < len(t):
            ch = t[i]
            if ch == '"':
                i = string_end(t, i)
                if i < 0:
                    return -1
                continue
            if t.startswith("//", i) or t.startswith("/*", i):
                i = trivia_end(t, i)
                continue
            if ch == c:
                depth += 1
            elif ch == close:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return -1
    # bare literal: number, true, false, null
    j = i
    while j < len(t) and t[j] not in ",}\n\r \t":
        j += 1
    return j

def strip_jsonc(t):
    """Blank out // and /* */ comments (never inside strings) so python's json
    can validate what PowerShell's Newtonsoft parser accepts. Comments are
    replaced with spaces rather than removed so every offset stays valid, and
    trailing commas are dropped — both are legal in the files this splices."""
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == '"':
            j = string_end(t, i)
            if j < 0:
                out.append(t[i:]); break
            out.append(t[i:j]); i = j; continue
        if t.startswith("//", i):
            j = t.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j; continue
        if t.startswith("/*", i):
            j = t.find("*/", i)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i)); i = j; continue
        out.append(c); i += 1
    s = "".join(out)
    # trailing commas: ,} and ,]
    res, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == '"':
            j = string_end(s, i)
            if j < 0:
                res.append(s[i:]); break
            res.append(s[i:j]); i = j; continue
        if c == ",":
            k = i + 1
            while k < n and s[k] in " \t\r\n":
                k += 1
            if k < n and s[k] in "}]":
                res.append(" "); i += 1; continue
        res.append(c); i += 1
    return "".join(res)


def find_top_level_key(t, key):
    """-> (key_start, value_start, value_end) or None. Only depth 1 counts."""
    i, depth = 0, 0
    while i < len(t):
        c = t[i]
        if t.startswith("//", i) or t.startswith("/*", i):
            i = trivia_end(t, i)
            continue
        if c == '"':
            start = i
            end = string_end(t, i)
            if end < 0:
                return None
            if depth == 1:
                name = t[start:end]
                try:
                    name = json.loads(name)
                except ValueError:
                    name = None
                j = trivia_end(t, end)
                if j < len(t) and t[j] == ":" and name == key:
                    vs = trivia_end(t, j + 1)
                    ve = value_end(t, vs)
                    if ve < 0:
                        return None
                    return (start, vs, ve)
                # not our key: skip its value so nested keys never match
                if j < len(t) and t[j] == ":":
                    vs = trivia_end(t, j + 1)
                    ve = value_end(t, vs)
                    if ve < 0:
                        return None
                    i = ve
                    continue
            i = end
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return None

if os.path.isfile(path):
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
else:
    # A fresh file gets a shape the insert path renders tidily.
    text = "{\n}\n"

# Refuse to touch a file we cannot parse — echoing it back untouched is always
# better than overwriting someone's config with our guess at its contents.
try:
    json.loads(strip_jsonc(text))
except ValueError as exc:
    sys.stderr.write("%s: %s will not parse (%s); left untouched\n" % (label, path, exc))
    raise SystemExit(2)

span = find_top_level_key(text, key)
if span:
    ks, vs, ve = span
    if text[vs:ve].strip() == value_text.strip():
        print("same")
        raise SystemExit(0)
    out = text[:vs] + value_text + text[ve:]
else:
    # Insert as the first key, preserving the opening brace's own trivia.
    ob = text.find("{")
    if ob < 0:
        sys.stderr.write("%s: %s has no JSON object\n" % (label, path))
        raise SystemExit(2)
    after = trivia_end(text, ob + 1)
    sep = "" if text[after:after + 1] == "}" else ","
    tail = text[ob + 1:]
    # An empty object renders as {\n  "key": value\n} rather than {"key": value}}.
    if not sep and not tail.lstrip().startswith("}\n") and tail.lstrip() == "}":
        tail = "\n" + tail.lstrip()
    elif not sep:
        tail = "\n" + tail.lstrip()
    out = text[:ob + 1] + "\n  " + json.dumps(key) + ": " + value_text + sep + tail

# Never leave a broken file behind: re-parse before writing.
try:
    json.loads(strip_jsonc(out))
except ValueError as exc:
    sys.stderr.write("%s: splice would break %s (%s); left untouched\n" % (label, path, exc))
    raise SystemExit(2)

os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
tmp = path + ".ts-tmp"
with open(tmp, "w", encoding="utf-8", newline="") as fh:
    fh.write(out)
os.replace(tmp, path)
print("changed")
PY
}
