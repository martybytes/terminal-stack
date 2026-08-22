"""The dashboard page, as a Python string literal.

Deliberately not a bundled data file. The spec's only `datas` entry is a 41-byte build
artifact, and the repo's one real source asset (`assets/speak-summary.md`) is clone-resident
by design, which cannot work for a frozen EXE living in `%LOCALAPPDATA%` with no reliable
path back to the clone. The `_MEIPASS` lookup that would be needed degrades silently to a
default on OSError, and the same silent degrade here would mean a blank page served by a
healthy daemon. A string literal cannot be forgotten in a spec edit.

`__TS_TOKEN__` is substituted at serve time. The page is same-origin, and no route sends
CORS headers, so cross-origin script cannot read the token out of it; that plus the Host
allowlist is what makes a write endpoint on an unauthenticated loopback port acceptable.

Self-contained on purpose: no CDN, no external font, no build step. Palette is Catppuccin
Mocha, matching the rest of the stack.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>terminal-stack TTS</title>
<style>
  :root {
    --base:#1e1e2e; --mantle:#181825; --surface:#313244; --overlay:#6c7086;
    --text:#cdd6f4; --subtext:#a6adc8; --green:#a6e3a1; --yellow:#f9e2af;
    --red:#f38ba8; --peach:#fab387; --blue:#89b4fa; --mauve:#cba6f7; --teal:#94e2d5;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--base); color:var(--text);
         font:13px/1.5 ui-monospace,"Cascadia Code",Consolas,monospace; }
  header { display:flex; align-items:center; gap:16px; flex-wrap:wrap;
           padding:10px 16px; background:var(--mantle);
           border-bottom:1px solid var(--surface); position:sticky; top:0; z-index:3; }
  h1 { font-size:14px; margin:0; font-weight:600; letter-spacing:.02em; }
  .pill { padding:2px 8px; border-radius:10px; background:var(--surface);
          color:var(--subtext); font-size:11px; white-space:nowrap; }
  .pill b { color:var(--text); font-weight:600; }
  .pill.good { color:var(--green); } .pill.warn { color:var(--yellow); }
  .pill.bad { color:var(--red); } .pill.mute { color:var(--peach); }
  nav { display:flex; gap:2px; padding:0 16px; background:var(--mantle);
        border-bottom:1px solid var(--surface); position:sticky; top:41px; z-index:3; }
  nav button { background:none; border:0; border-bottom:2px solid transparent;
               color:var(--subtext); padding:8px 14px; cursor:pointer; font:inherit; }
  nav button[aria-selected="true"] { color:var(--text); border-bottom-color:var(--mauve); }
  main { padding:12px 16px 40px; }
  section[hidden] { display:none; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px; }
  .card { background:var(--mantle); border:1px solid var(--surface); border-radius:6px;
          padding:10px 12px; }
  .card h2 { font-size:11px; margin:0 0 6px; color:var(--overlay);
             text-transform:uppercase; letter-spacing:.08em; font-weight:600; }
  .card .v { font-size:16px; } .card .n { color:var(--subtext); font-size:11px; margin-top:4px; }
  .stream { background:var(--mantle); border:1px solid var(--surface); border-radius:6px;
            height:calc(100vh - 190px); overflow-y:auto; padding:6px 0; }
  .row { display:flex; gap:10px; padding:1px 12px; white-space:pre-wrap;
         word-break:break-word; }
  .row:hover { background:var(--surface); }
  .t { color:var(--overlay); flex:0 0 auto; }
  .who { color:var(--blue); flex:0 0 auto; }
  .cont { color:var(--overlay); padding-left:34px; }
  .lv-warning .m { color:var(--yellow); } .lv-error .m, .lv-critical .m { color:var(--red); }
  .lv-debug { color:var(--overlay); }
  .d { flex:0 0 84px; }
  .d-spoken { color:var(--green); } .d-deduped, .d-muted, .d-cooldown { color:var(--overlay); }
  .d-suppressed_dnd { color:var(--peach); }
  .d-failed, .d-synth_failed, .d-play_failed, .d-dropped_stale { color:var(--red); }
  .tools { display:flex; gap:8px; align-items:center; margin-bottom:8px; flex-wrap:wrap; }
  input[type=search], input[type=text], input[type=number], input[type=password], select {
      background:var(--mantle); border:1px solid var(--surface); color:var(--text);
      border-radius:4px; padding:4px 8px; font:inherit; }
  input[type=search] { min-width:200px; }
  button.act { background:var(--surface); border:0; color:var(--text); font:inherit;
        border-radius:4px; padding:4px 10px; cursor:pointer; }
  button.act[aria-pressed="true"] { background:var(--mauve); color:var(--mantle); }
  button.act.primary { background:var(--mauve); color:var(--mantle); }
  button.act.danger { background:var(--red); color:var(--mantle); }
  button.act:disabled { opacity:.5; cursor:default; }
  .note { color:var(--subtext); font-size:11px; }
  .empty { color:var(--overlay); padding:14px 12px; }
  fieldset { border:1px solid var(--surface); border-radius:6px; margin:0 0 12px;
             padding:10px 12px; background:var(--mantle); }
  legend { color:var(--overlay); font-size:11px; text-transform:uppercase;
           letter-spacing:.08em; padding:0 6px; }
  .f { display:grid; grid-template-columns:260px 1fr; gap:10px; align-items:start;
       padding:5px 0; border-top:1px solid var(--base); }
  .f:first-of-type { border-top:0; }
  .f > label { color:var(--subtext); padding-top:4px; }
  .f .hint { color:var(--overlay); font-size:11px; }
  .f .over { color:var(--peach); font-size:11px; }
  .f.dirty > label { color:var(--yellow); }
  .warnbar { background:var(--surface); border-left:3px solid var(--yellow);
             padding:6px 10px; margin-bottom:10px; font-size:12px; }
  .savebar { position:sticky; bottom:0; background:var(--mantle);
             border-top:1px solid var(--surface); padding:8px 0; display:flex; gap:8px;
             align-items:center; }
  pre.result { background:var(--mantle); border:1px solid var(--surface); border-radius:6px;
               padding:10px; white-space:pre-wrap; margin:8px 0 0; }
</style></head><body>

<header>
  <h1>terminal-stack TTS</h1>
  <span class="pill" id="p-state">connecting…</span>
  <span class="pill" id="p-mute"></span>
  <span class="pill" id="p-mode"></span>
  <span class="pill" id="p-silent"></span>
  <span class="pill" id="p-ver"></span>
</header>

<nav role="tablist">
  <button role="tab" data-tab="status" aria-selected="true">Status</button>
  <button role="tab" data-tab="timeline" aria-selected="false">Timeline</button>
  <button role="tab" data-tab="log" aria-selected="false">Log</button>
  <button role="tab" data-tab="settings" aria-selected="false">Settings</button>
</nav>

<main>
  <section id="status">
    <div class="grid" id="cards"></div>
    <p class="note" id="status-note"></p>
  </section>

  <section id="timeline" hidden>
    <div class="tools">
      <input type="search" id="tl-filter" placeholder="filter (project, session, line)">
      <button class="act" id="tl-sort" aria-pressed="true">newest first</button>
      <button class="act" id="tl-follow" aria-pressed="true">following</button>
      <span class="note" id="tl-note"></span>
    </div>
    <div class="stream" id="tl"></div>
  </section>

  <section id="log" hidden>
    <div class="tools">
      <input type="search" id="lg-filter" placeholder="filter">
      <button class="act" id="lg-sort" aria-pressed="true">newest first</button>
      <button class="act" id="lg-follow" aria-pressed="true">following</button>
      <button class="act" id="lg-clear">clear</button>
      <span class="note" id="lg-note"></span>
    </div>
    <div class="stream" id="lg"></div>
  </section>

  <section id="settings" hidden>
    <div class="warnbar">
      These are <b>machine-local overrides</b> written to
      <code>~/.claude/tts/local.json</code>. They win over the saved settings and survive
      every apply, but they do not travel to your other machines. For a setting that
      should propagate, use <code>ts-config tts …</code> from WSL.
    </div>
    <div id="secrets"></div>
    <div id="fields"></div>
    <div class="savebar">
      <button class="act primary" id="save" disabled>Save</button>
      <button class="act" id="revert" disabled>Discard changes</button>
      <span class="note" id="save-note"></span>
    </div>
  </section>
</main>

<script>
const TOKEN = "__TS_TOKEN__";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => (
  {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

document.querySelectorAll('nav button').forEach((b) => b.onclick = () => {
  document.querySelectorAll('nav button').forEach((o) =>
    o.setAttribute('aria-selected', String(o === b)));
  for (const name of ['status', 'timeline', 'log', 'settings'])
    $(name).hidden = name !== b.dataset.tab;
});

async function get(url) {
  const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) throw new Error(url + ' -> ' + res.status);
  return res.json();
}
async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-TS-Token': TOKEN },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || (url + ' -> ' + res.status));
  return data;
}

/* Newest-first is the default for both streams, and new rows arrive at the top. "Following"
   therefore means "stay pinned to the newest end", which is the top in that order and the
   bottom in the other. Toggling the order just reverses the DOM, so no refetch is needed. */
function panel(boxId, sortId, followId, filterId) {
  const box = $(boxId);
  const state = { newestFirst: true, following: true };
  $(sortId).onclick = () => {
    state.newestFirst = !state.newestFirst;
    $(sortId).setAttribute('aria-pressed', String(state.newestFirst));
    $(sortId).textContent = state.newestFirst ? 'newest first' : 'oldest first';
    for (const row of [...box.children].reverse()) box.appendChild(row);
    box.scrollTop = state.newestFirst ? 0 : box.scrollHeight;
  };
  $(followId).onclick = () => {
    state.following = !state.following;
    $(followId).setAttribute('aria-pressed', String(state.following));
    $(followId).textContent = state.following ? 'following' : 'paused';
  };
  const filter = () => {
    const q = $(filterId).value.trim().toLowerCase();
    for (const row of box.children)
      row.style.display = !q || row.textContent.toLowerCase().includes(q) ? '' : 'none';
  };
  $(filterId).oninput = filter;
  return {
    box,
    /* `html` is one row. Callers pass rows oldest-first; each insert at the newest end
       leaves the newest row at the visible edge either way. */
    add(html) {
      const top = state.newestFirst;
      const atEdge = top ? box.scrollTop <= 40
                         : box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
      box.insertAdjacentHTML(top ? 'afterbegin' : 'beforeend', html);
      while (box.childElementCount > 2000)
        (top ? box.lastElementChild : box.firstElementChild).remove();
      if (state.following && atEdge) box.scrollTop = top ? 0 : box.scrollHeight;
    },
    filter,
    clear() { box.innerHTML = ''; },
  };
}
const tl = panel('tl', 'tl-sort', 'tl-follow', 'tl-filter');
const lg = panel('lg', 'lg-sort', 'lg-follow', 'lg-filter');
$('lg-clear').onclick = () => lg.clear();

const card = (title, value, note) =>
  `<div class="card"><h2>${esc(title)}</h2><div class="v">${esc(value)}</div>` +
  (note ? `<div class="n">${esc(note)}</div>` : '') + `</div>`;

const secs = (n) => {
  if (n === null || n === undefined || n === '-') return 'never';
  if (n < 90) return Math.round(n) + 's ago';
  if (n < 5400) return Math.round(n / 60) + 'm ago';
  return (n / 3600).toFixed(1) + 'h ago';
};

async function refreshStatus() {
  try {
    const [st, mu, sum] = await Promise.all([
      get('/v1/status'), get('/v1/mute'), get('/v1/history/summary')]);
    $('p-state').textContent = 'daemon up';
    $('p-state').className = 'pill good';
    $('p-ver').innerHTML = 'build <b>' + esc(String(st.version).slice(0, 12)) + '</b>';
    $('p-mute').textContent = mu.muted ? (mu.describe || 'MUTED') : 'not muted';
    $('p-mute').className = 'pill ' + (mu.muted ? 'mute' : '');
    $('p-mode').innerHTML = 'summarizer <b>' + esc(st.summarizerMode) + '</b>';
    $('p-mode').className = 'pill ' + (st.summarizerDegraded ? 'warn' : '');
    $('p-silent').textContent = 'daemon last spoke ' + secs(sum.daemon_silent_for);
    $('p-silent').className = 'pill ' + (sum.daemon_silent_for === null ? 'warn' : '');

    const cards = [
      card('Spoken (24h)', sum.spoken, 'durable, survives restarts'),
      card('Deduped (24h)', sum.deduped, 'one event, several hooks'),
      card('Duplicate bursts', sum.dupes, sum.dupes ? 'inspect the timeline' : 'none'),
      card('Queue', Array.isArray(st.queue) ? st.queue.length : st.queue, 'waiting to speak'),
      card('Audio', st.audio, 'duck state'),
      card('Engine', st.lastEngine || 'none yet', 'last synth'),
      card('This process', `${st.spoken} spoken / ${st.suppressed} suppressed`,
           'counters die with the daemon'),
      card('Music', st.musicMode, 'while speaking'),
    ];
    if (st.summarizerDegraded)
      cards.unshift(card('Summarizer degraded', st.summarizerDegraded + 'x',
                         st.summarizerLastDegrade || 'fell back to template'));
    $('cards').innerHTML = cards.join('');
    $('status-note').textContent = st.lastLine ? 'Last line: ' + st.lastLine : '';
  } catch (err) {
    $('p-state').textContent = 'daemon unreachable';
    $('p-state').className = 'pill bad';
    $('status-note').textContent = String(err);
  }
}

let lastTs = 0;
const seen = new Set();
async function refreshTimeline() {
  try {
    const url = lastTs ? `/v1/history?limit=200&since=${lastTs}` : '/v1/history?limit=200';
    const data = await get(url);
    const rows = (data.rows || []).slice().reverse();   // API is newest first
    let added = 0;
    for (const r of rows) {
      if (seen.has(r.id)) continue;         // `since` is >=, so re-delivery happens
      seen.add(r.id);
      lastTs = Math.max(lastTs, r.ts);
      const when = new Date(r.ts * 1000).toLocaleTimeString();
      const ms = r.play_ms ? ` ${(r.play_ms / 1000).toFixed(1)}s` : '';
      tl.add(`<div class="row"><span class="t">${esc(when)}</span>` +
        `<span class="d d-${esc(r.decision)}">${esc(r.decision)}</span>` +
        `<span class="who">${esc(r.project || r.session_key || '')}</span>` +
        `<span class="m">${esc(r.line || r.state || '')}${esc(ms)}</span></div>`);
      added++;
    }
    if (added) tl.filter();
    if (!tl.box.childElementCount)
      // An empty result is ambiguous: history fails open and returns [] when its database
      // is unusable, so "all quiet" is not a safe thing to claim.
      tl.box.innerHTML = '<div class="empty">No decisions recorded yet. ' +
        'If this stays empty while audio plays, the history database is unreadable.</div>';
    $('tl-note').textContent = seen.size + ' rows';
  } catch (err) { $('tl-note').textContent = String(err); }
}

function startLog() {
  const stream = new EventSource('/v1/logs/stream');
  stream.onopen = () => { $('lg-note').textContent = 'streaming'; };
  stream.onerror = () => { $('lg-note').textContent = 'stream dropped, retrying'; };
  stream.addEventListener('meta', (e) => {
    $('lg-note').textContent = (JSON.parse(e.data).note) || ''; });
  stream.addEventListener('line', (e) => {
    const p = JSON.parse(e.data);
    lg.add(p.ts
      ? `<div class="row lv-${esc(p.level)}"><span class="t">${esc(p.ts.slice(11, 19))}</span>` +
        `<span class="who">${esc(p.logger.replace(/^ttsd\\.?/, '') || 'ttsd')}</span>` +
        `<span class="m">${esc(p.message)}</span></div>`
      : `<div class="row cont">${esc(p.raw)}</div>`);
    if ($('lg-filter').value) lg.filter();
  });
}

/* ── settings ─────────────────────────────────────────────────────────────── */
let schema = [], effective = {}, pending = {};

const control = (f, value) => {
  const id = 'f-' + f.key;
  if (f.kind === 'bool')
    return `<input type="checkbox" id="${id}" data-key="${esc(f.key)}"` +
           `${value ? ' checked' : ''}>`;
  if (f.kind === 'enum')
    return `<select id="${id}" data-key="${esc(f.key)}">` + f.options.map((o) =>
      `<option${o === value ? ' selected' : ''}>${esc(o)}</option>`).join('') + `</select>`;
  if (f.kind === 'csv')
    return `<input type="text" id="${id}" data-key="${esc(f.key)}" size="40" ` +
           `value="${esc(Array.isArray(value) ? value.join(',') : value)}">`;
  if (f.kind === 'int' || f.kind === 'float')
    return `<input type="number" id="${id}" data-key="${esc(f.key)}" step="any" ` +
           `value="${esc(value)}">`;
  return `<input type="text" id="${id}" data-key="${esc(f.key)}" size="46" ` +
         `value="${esc(value)}">`;
};

function renderSettings() {
  const groups = [...new Set(schema.map((f) => f.group))];
  $('fields').innerHTML = groups.map((group) => {
    const fields = schema.filter((f) => f.group === group);
    const banner = group === 'Needs a restart'
      ? '<div class="warnbar">A config reload cannot apply these: the daemon reads them ' +
        'once at startup. Save, then restart. ' +
        '<button class="act danger" id="restart">Restart the daemon</button></div>'
      : group === 'Shell fallback only'
      ? '<div class="warnbar">The daemon never reads these. They affect the shell and ' +
        'PowerShell fallback path, which is what speaks when the daemon is down.</div>'
      : '';
    return `<fieldset><legend>${esc(group)}</legend>${banner}` + fields.map((f) => {
      const e = effective[f.key] || {};
      const over = e.layer === 'local'
        ? `<div class="over">overriding the saved value: ${esc(JSON.stringify(e.saved))}</div>`
        : '';
      return `<div class="f" id="w-${esc(f.key)}"><label for="f-${esc(f.key)}">` +
        `${esc(f.label)}<div class="hint">${esc(f.key)}</div></label><div>` +
        control(f, e.effective) +
        (f.note ? `<div class="hint">${esc(f.note)}</div>` : '') + over + `</div></div>`;
    }).join('') + `</fieldset>`;
  }).join('');

  $('fields').querySelectorAll('[data-key]').forEach((el) => {
    el.oninput = el.onchange = () => {
      const key = el.dataset.key;
      pending[key] = el.type === 'checkbox' ? el.checked : el.value;
      $('w-' + key).classList.add('dirty');
      $('save').disabled = $('revert').disabled = false;
      $('save-note').textContent = Object.keys(pending).length + ' unsaved';
    };
  });
  const restart = $('restart');
  if (restart) restart.onclick = async () => {
    if (!confirm('Restart the TTS daemon? Anything speaking now stops.')) return;
    try { await post('/v1/daemon/restart'); $('save-note').textContent = 'restarting…'; }
    catch (err) { $('save-note').textContent = String(err); }
  };
}

function renderSecrets(info) {
  const s = info || {};
  const where = s.set ? `set, from the ${s.source === 'store' ? 'secret store' : 'environment'}`
                      : 'not set';
  const tail = s.set && s.tail ? ` (…${esc(s.tail)})` : '';
  $('secrets').innerHTML = `<fieldset><legend>Secrets</legend>
    <div class="f"><label>Anthropic API key<div class="hint">for the haiku summarizer</div></label>
      <div>
        <input type="password" id="sec-key" size="46" placeholder="${esc(where)}${tail}">
        <button class="act" id="sec-save">Save key</button>
        <button class="act" id="sec-clear">Clear</button>
        <div class="hint">Stored in the daemon's state directory, never in either config
          store and never in git. An environment variable also works, but the daemon starts
          at logon and cannot see one exported later.</div>
        <div class="hint" id="sec-note"></div>
      </div></div>
    <div class="f"><label>Summarizer test<div class="hint">what actually runs</div></label>
      <div><button class="act" id="test-run">Test the current mode</button>
        <div class="hint">A missing key makes haiku behave exactly like template. This says
          which mode ran, where the key came from, and whether it fell back.</div>
        <pre class="result" id="test-out" hidden></pre></div></div>
    </fieldset>`;

  $('sec-save').onclick = async () => {
    const value = $('sec-key').value;
    if (!value) { $('sec-note').textContent = 'nothing entered'; return; }
    try {
      await post('/v1/secrets/set', { name: 'anthropicApiKey', value });
      $('sec-key').value = '';
      $('sec-note').textContent = 'saved';
      loadSettings();
    } catch (err) { $('sec-note').textContent = String(err); }
  };
  $('sec-clear').onclick = async () => {
    try {
      await post('/v1/secrets/set', { name: 'anthropicApiKey', value: '' });
      $('sec-note').textContent = 'cleared';
      loadSettings();
    } catch (err) { $('sec-note').textContent = String(err); }
  };
  $('test-run').onclick = async () => {
    $('test-out').hidden = false;
    $('test-out').textContent = 'running…';
    try {
      const r = await post('/v1/summarizer/test', {});
      $('test-out').textContent =
        `mode requested : ${r.mode}\\n` +
        `ran            : ${r.ran}\\n` +
        `key            : ${r.key}\\n` +
        `took           : ${r.ms} ms\\n` +
        `fell back      : ${r.fell_back ? 'yes' : 'no'}` +
        (r.reason ? `  (${r.reason})` : '') + `\\n` +
        `spoken line    : ${r.line}\\n\\n` +
        `note           : ${r.note}`;
    } catch (err) { $('test-out').textContent = String(err); }
  };
}

async function loadSettings() {
  try {
    const [sch, eff] = await Promise.all([
      get('/v1/config/schema'), get('/v1/config/effective')]);
    schema = sch.fields || [];
    effective = eff.values || {};
    pending = {};
    renderSecrets(eff.secrets && eff.secrets.anthropicApiKey);
    renderSettings();
    $('save').disabled = $('revert').disabled = true;
    $('save-note').textContent = '';
  } catch (err) { $('save-note').textContent = String(err); }
}

$('save').onclick = async () => {
  $('save').disabled = true;
  try {
    const res = await post('/v1/config/set', { updates: pending });
    if (res.errors && Object.keys(res.errors).length) {
      $('save-note').textContent = 'rejected: ' + Object.entries(res.errors)
        .map(([k, v]) => `${k} (${v})`).join(', ');
    } else {
      $('save-note').textContent = 'saved ' + (res.written || 0) + ' setting(s)';
    }
    await loadSettings();
  } catch (err) {
    $('save-note').textContent = String(err);
    $('save').disabled = false;
  }
};
$('revert').onclick = () => loadSettings();

refreshStatus(); refreshTimeline(); startLog(); loadSettings();
setInterval(refreshStatus, 3000);
setInterval(refreshTimeline, 2000);
</script></body></html>
"""
