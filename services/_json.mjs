#!/usr/bin/env node
// _json.mjs - JSON reads and safe round-trip edits for the .sh scripts.
// Used via the json_get / json_set / json_eq / json_str wrappers in _common.sh.
//
// This exists because the .sh side has no ConvertTo-Json/ConvertFrom-Json. It
// deliberately REFUSES to write a file it could not parse, so a hand-edited
// ~/.cursor/mcp.json or cli.config.json is never silently replaced and
// unrelated settings are never lost - the same contract that
// setup-playwright-agents.ps1 states at :200 and :246.
//
// There is no .ps1 twin: PowerShell has this built in. Registered as an
// intentional asymmetry in docs/conventions.md.

import { readFileSync, writeFileSync, renameSync, unlinkSync, existsSync } from 'node:fs';
import { dirname, basename, join } from 'node:path';

const [, , cmd, ...rest] = process.argv;
const fail = (m) => { process.stderr.write(`_json.mjs: ${m}\n`); process.exit(2); };

// Path syntax: dotted, with bracket segments for keys containing dots or
// slashes, and for array indexes.
//   services.agentmemory.image
//   dependencies["@playwright/cli"].version
//   plugins["agentmemory@agentmemory"][0].installPath
function parsePath(spec) {
  const out = [];
  const re = /\[("((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|(\d+))\]|([^.[\]]+)/g;
  let m;
  while ((m = re.exec(spec)) !== null) {
    if (m[2] !== undefined) out.push(JSON.parse('"' + m[2] + '"'));
    else if (m[3] !== undefined) out.push(m[3]);
    else if (m[4] !== undefined) out.push(Number(m[4]));
    else out.push(m[5]);
  }
  if (!out.length) fail(`empty path: ${spec}`);
  return out;
}

const BOM = 0xfeff;
const stripBom = (t) => (t.charCodeAt(0) === BOM ? t.slice(1) : t);

function readJson(src) {
  let text;
  if (src === '-') text = readFileSync(0, 'utf8');
  else {
    if (!existsSync(src)) return { text: null, data: undefined };
    text = readFileSync(src, 'utf8');
  }
  if (text.trim() === '') return { text, data: undefined };
  try { return { text, data: JSON.parse(stripBom(text)) }; }
  catch (e) { fail(`${src} is not valid JSON (${e.message}) - refusing to touch it`); }
}

function get(data, path) {
  let cur = data;
  for (const k of path) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[k];
  }
  return cur;
}

function set(data, path, value) {
  if (data === undefined || data === null) data = typeof path[0] === 'number' ? [] : {};
  let cur = data;
  for (let i = 0; i < path.length - 1; i++) {
    const k = path[i];
    if (cur[k] === undefined || cur[k] === null || typeof cur[k] !== 'object') {
      cur[k] = typeof path[i + 1] === 'number' ? [] : {};
    }
    cur = cur[k];
  }
  cur[path[path.length - 1]] = value;
  return data;
}

// Match PowerShell's ConvertTo-Json, which escapes non-ASCII as \uXXXX where
// JSON.stringify emits it literally. Without this the two script sets would
// write byte-different .billing.env files for the same project name.
// Built with the RegExp constructor so this source file stays pure ASCII.
const NON_ASCII = new RegExp('[\\u0080-\\uFFFF]', 'g');
const asciiEscape = (s) => s.replace(NON_ASCII,
  (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));

// Keep the file's own shape: its indent, and whether it ended with a newline.
function writeAtomic(file, data, originalText) {
  let indent = 2;
  if (originalText) {
    const m = originalText.match(/\n([ \t]+)\S/);
    if (m) indent = m[1] === '\t' ? '\t' : m[1].length;
  }
  // An empty or whitespace-only original counts as "no original": a new file
  // should end with a newline, not inherit the absence of one from nothing.
  const endsWithNewline = !originalText || originalText.trim() === ''
    ? true : /\n$/.test(originalText);
  const body = JSON.stringify(data, null, indent) + (endsWithNewline ? '\n' : '');
  const tmp = join(dirname(file), `.${basename(file)}.${process.pid}.tmp`);
  try {
    writeFileSync(tmp, body, { encoding: 'utf8', mode: 0o600 });
    renameSync(tmp, file);
  } catch (e) {
    try { unlinkSync(tmp); } catch { /* nothing to clean up */ }
    fail(`could not write ${file}: ${e.message}`);
  }
}

switch (cmd) {
  case 'get': {
    const [src, spec] = rest;
    if (!src || !spec) fail('usage: _json.mjs get <file|-> <path>');
    const { data } = readJson(src);
    const v = get(data, parsePath(spec));
    if (v === undefined) process.exit(1);
    process.stdout.write(typeof v === 'string' ? v : JSON.stringify(v));
    process.stdout.write('\n');
    break;
  }
  case 'set': {
    const [file, spec, json] = rest;
    if (!file || !spec || json === undefined) fail('usage: _json.mjs set <file> <path> <json>');
    let value;
    try { value = JSON.parse(json); }
    catch (e) { fail(`value is not valid JSON: ${e.message}`); }
    const { text, data } = readJson(file);
    writeAtomic(file, set(data, parsePath(spec), value), text);
    break;
  }
  case 'eq': {
    const [src, spec, json] = rest;
    if (!src || !spec || json === undefined) fail('usage: _json.mjs eq <file|-> <path> <json>');
    let want;
    try { want = JSON.parse(json); }
    catch (e) { fail(`value is not valid JSON: ${e.message}`); }
    const { data } = readJson(src);
    const got = get(data, parsePath(spec));
    process.exit(JSON.stringify(got) === JSON.stringify(want) ? 0 : 1);
    break;
  }
  case 'str': {
    if (rest[0] === undefined) fail('usage: _json.mjs str <text>');
    process.stdout.write(asciiEscape(JSON.stringify(rest[0])) + '\n');
    break;
  }
  default:
    fail(`unknown command '${cmd || ''}' - expected get, set, eq or str`);
}
