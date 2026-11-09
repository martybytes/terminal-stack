// Offline compaction of AgentMemory's `mem:insights` state scope.
//
// Runs from entrypoint.sh BEFORE the iii engine starts, so nothing else has the
// file open. Never run it against a live engine: the engine holds every scope
// in memory and rewrites the file whole on the next write, so an edit made
// underneath it is lost at best.
//
// Why it exists: agentmemory 0.9.29's reflect stage stored every new insight
// with the WHOLE concept cluster in `tags` and `sourceConceptCluster` and every
// matching fact id in `sourceMemoryIds`. On a graph whose concepts form one
// connected component that is ~5,400 names twice and ~5,600 ids per insight,
// about 280 KB each, five more on every consolidation run. On 11/09/2026 the
// scope was 4,824 insights in one 1.0 GB file, and the engine, which keeps
// every scope resident, sat at 17 GB and was OOM-killed at 28.5 GB. Nothing
// reads those three fields back; patch-agentmemory.mjs now stores only what
// the prompt actually used, and this trims the records written before that.
//
// File format (iii 0.11 file_based kv): one rkyv 0.8 ArchivedString holding
// the scope's JSON object, i.e. the UTF-8 JSON, zero padding to a 4-byte
// boundary, then an 8-byte out-of-line string repr: 4 length bytes (byte 0 is
// 0b10 followed by the low 6 bits of the length, bytes 1-3 the remaining bits,
// little-endian) and an i32 offset from the repr back to the string start.
// Strings of 8 bytes or fewer are stored inline instead (0xff padded).
//
// Usage:
//   node compact-insights.mjs <file> [--max-concepts N] [--max-facts N]
//        [--max-lessons N] [--backup-dir DIR] [--min-bytes N]
//   node compact-insights.mjs --verify-codec <dir>   decode+re-encode every
//        .bin in <dir> and report any that do not round-trip byte for byte
import {
  closeSync, openSync, readdirSync, readFileSync, renameSync, statSync,
  writeSync, copyFileSync, unlinkSync,
} from "node:fs";
import { basename, dirname, join } from "node:path";

export function decodeScope(buf) {
  if (buf.length < 8) throw new Error(`too short for an rkyv string (${buf.length} bytes)`);
  const repr = buf.subarray(buf.length - 8);
  if ((repr[0] & 0xc0) === 0x80) {
    const len = (repr[0] & 0x3f) | (repr[1] << 6) | (repr[2] << 14) | (repr[3] << 22);
    const offset = repr.readInt32LE(4);
    const start = buf.length - 8 + offset;
    if (start !== 0 || len > buf.length - 8) {
      throw new Error(`unexpected layout: len ${len}, offset ${offset}, size ${buf.length}`);
    }
    return { json: buf.subarray(0, len), inline: false };
  }
  // Inline: up to 8 bytes, 0xff padded, and nothing else in the file.
  if (buf.length !== 8) throw new Error(`not an rkyv string: ${buf.length} bytes with an inline repr`);
  let end = 8;
  while (end > 0 && repr[end - 1] === 0xff) end -= 1;
  return { json: repr.subarray(0, end), inline: true };
}

export function encodeHeader(len) {
  if (len >= 2 ** 30) throw new Error(`scope too large for the rkyv repr (${len} bytes)`);
  const pad = (4 - (len % 4)) % 4;
  const repr = Buffer.alloc(8);
  repr[0] = 0x80 | (len & 0x3f);
  repr[1] = (len >>> 6) & 0xff;
  repr[2] = (len >>> 14) & 0xff;
  repr[3] = (len >>> 22) & 0xff;
  repr.writeInt32LE(-(len + pad), 4);
  return { pad: Buffer.alloc(pad), repr };
}

export function encodeScope(json) {
  if (json.length <= 8) {
    const out = Buffer.alloc(8, 0xff);
    json.copy(out);
    return out;
  }
  const { pad, repr } = encodeHeader(json.length);
  return Buffer.concat([json, pad, repr]);
}

// Yields [keyStart, keyEnd, valueStart, valueEnd] for each member of a
// top-level JSON object, without parsing the whole thing: a 1 GB scope is past
// V8's string limit. Structural bytes are ASCII, so scanning UTF-8 is safe.
export function* members(json) {
  let i = 0;
  const n = json.length;
  const ws = (c) => c === 0x20 || c === 0x0a || c === 0x0d || c === 0x09;
  const skipString = (p) => {
    p += 1;
    while (p < n) {
      const c = json[p];
      if (c === 0x5c) p += 2;
      else if (c === 0x22) return p + 1;
      else p += 1;
    }
    throw new Error("unterminated string");
  };
  while (i < n && ws(json[i])) i += 1;
  if (json[i] !== 0x7b) throw new Error("scope is not a JSON object");
  i += 1;
  for (;;) {
    while (i < n && (ws(json[i]) || json[i] === 0x2c)) i += 1;
    if (json[i] === 0x7d) return;
    if (json[i] !== 0x22) throw new Error(`expected a key at byte ${i}`);
    const keyStart = i;
    i = skipString(i);
    const keyEnd = i;
    while (ws(json[i])) i += 1;
    if (json[i] !== 0x3a) throw new Error(`expected ':' at byte ${i}`);
    i += 1;
    while (ws(json[i])) i += 1;
    const valueStart = i;
    let depth = 0;
    for (;;) {
      const c = json[i];
      if (c === 0x22) { i = skipString(i); if (depth === 0) break; continue; }
      if (c === 0x7b || c === 0x5b) depth += 1;
      else if (c === 0x7d || c === 0x5d) { depth -= 1; if (depth === 0) { i += 1; break; } }
      else if (depth === 0 && (c === 0x2c || ws(c))) break;
      i += 1;
      if (i > n) throw new Error("unterminated value");
    }
    yield [keyStart, keyEnd, valueStart, i];
  }
}

export function trimInsight(insight, limits) {
  if (!insight || typeof insight !== "object") return false;
  const cut = {};
  const trim = (field, max) => {
    const v = insight[field];
    if (Array.isArray(v) && v.length > max) {
      cut[field] = v.length;
      insight[field] = v.slice(0, max);
    }
  };
  trim("tags", limits.concepts);
  trim("sourceConceptCluster", limits.concepts);
  trim("sourceMemoryIds", limits.facts);
  trim("sourceLessonIds", limits.lessons);
  if (Object.keys(cut).length === 0) return false;
  insight.sourceTruncated = { ...(insight.sourceTruncated || {}), ...cut };
  return true;
}

function stamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "").replace("T", "-");
}

export function compact(file, opts) {
  const before = statSync(file).size;
  if (before < opts.minBytes) {
    return { skipped: true, reason: `${before} bytes is under the ${opts.minBytes} byte threshold`, before };
  }
  const { json, inline } = decodeScope(readFileSync(file));
  if (inline) return { skipped: true, reason: "inline (tiny) scope", before };

  const tmp = join(opts.backupDir, `.${basename(file)}.compact-${process.pid}`);
  const fd = openSync(tmp, "w", 0o644);
  let written = 0;
  const put = (b) => { writeSync(fd, b); written += b.length; };
  let records = 0;
  let trimmed = 0;
  try {
    put(Buffer.from("{"));
    let first = true;
    for (const [ks, ke, vs, ve] of members(json)) {
      const value = JSON.parse(json.toString("utf8", vs, ve));
      records += 1;
      const changed = trimInsight(value, opts.limits);
      const out = changed ? Buffer.from(JSON.stringify(value), "utf8") : json.subarray(vs, ve);
      if (changed) trimmed += 1;
      if (!first) put(Buffer.from(","));
      first = false;
      put(json.subarray(ks, ke));
      put(Buffer.from(":"));
      put(out);
    }
    put(Buffer.from("}"));
    const { pad, repr } = encodeHeader(written);
    writeSync(fd, pad);
    writeSync(fd, repr);
  } finally {
    closeSync(fd);
  }

  // Prove the new file decodes and parses member by member before it replaces
  // anything, and that no record went missing.
  const check = decodeScope(readFileSync(tmp));
  let checked = 0;
  for (const [, , vs, ve] of members(check.json)) {
    JSON.parse(check.json.toString("utf8", vs, ve));
    checked += 1;
  }
  if (checked !== records) {
    unlinkSync(tmp);
    throw new Error(`rewrite lost records: ${records} in, ${checked} out`);
  }
  if (trimmed === 0) {
    unlinkSync(tmp);
    return { skipped: true, reason: "nothing to trim", before, records };
  }

  const backup = join(opts.backupDir, `${basename(file)}.before-compact-${stamp()}`);
  copyFileSync(file, backup);
  renameSync(tmp, file);
  return { skipped: false, before, after: statSync(file).size, records, trimmed, backup };
}

function verifyCodec(dir) {
  let ok = 0;
  const bad = [];
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".bin")) continue;
    const buf = readFileSync(join(dir, name));
    try {
      const { json } = decodeScope(buf);
      if (Buffer.compare(encodeScope(Buffer.from(json)), buf) === 0) ok += 1;
      else bad.push(`${name}: re-encode differs`);
    } catch (err) {
      bad.push(`${name}: ${err.message}`);
    }
  }
  return { ok, bad };
}

function main(argv) {
  if (argv[0] === "--verify-codec") {
    const r = verifyCodec(argv[1]);
    process.stdout.write(JSON.stringify(r) + "\n");
    process.exit(r.bad.length === 0 ? 0 : 1);
  }
  const num = (flag, fallback) => {
    const i = argv.indexOf(flag);
    const v = i === -1 ? fallback : Number(argv[i + 1]);
    if (!Number.isFinite(v) || v < 0) throw new Error(`${flag} must be a non-negative number`);
    return Math.floor(v);
  };
  const file = argv[0];
  if (!file || file.startsWith("--")) throw new Error("usage: compact-insights.mjs <file> [options]");
  const bi = argv.indexOf("--backup-dir");
  const opts = {
    minBytes: num("--min-bytes", 0),
    backupDir: bi === -1 ? dirname(dirname(file)) : argv[bi + 1],
    limits: {
      concepts: num("--max-concepts", 60),
      facts: num("--max-facts", 40),
      lessons: num("--max-lessons", 20),
    },
  };
  const result = compact(file, opts);
  process.stdout.write(JSON.stringify(result) + "\n");
}

if (process.argv[1] && import.meta.url.endsWith(basename(process.argv[1]))) {
  main(process.argv.slice(2));
}
