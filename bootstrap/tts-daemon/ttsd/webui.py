"""The dashboard page, as a Python string literal.

Deliberately not a bundled data file. The spec's only `datas` entry is a 41-byte build
artifact, and the repo's one real source asset (`assets/speak-summary.md`) is clone-resident
by design, which cannot work for a frozen EXE living in `%LOCALAPPDATA%` with no reliable
path back to the clone. The `_MEIPASS` lookup that would be needed degrades silently to a
default on OSError, and the same silent degrade here would mean a blank page served by a
healthy daemon. A string literal cannot be forgotten in a spec edit.

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
           border-bottom:1px solid var(--surface); position:sticky; top:0; z-index:2; }
  h1 { font-size:14px; margin:0; font-weight:600; letter-spacing:.02em; }
  .pill { padding:2px 8px; border-radius:10px; background:var(--surface);
          color:var(--subtext); font-size:11px; white-space:nowrap; }
  .pill b { color:var(--text); font-weight:600; }
  .pill.good { color:var(--green); } .pill.warn { color:var(--yellow); }
  .pill.bad { color:var(--red); } .pill.mute { color:var(--peach); }
  nav { display:flex; gap:2px; padding:0 16px; background:var(--mantle);
        border-bottom:1px solid var(--surface); position:sticky; top:41px; z-index:2; }
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
  .card .v { font-size:16px; }
  .card .n { color:var(--subtext); font-size:11px; margin-top:4px; }
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
  .tools input[type=search] { background:var(--mantle); border:1px solid var(--surface);
        color:var(--text); border-radius:4px; padding:4px 8px; font:inherit; min-width:200px; }
  .tools button { background:var(--surface); border:0; color:var(--text); font:inherit;
        border-radius:4px; padding:4px 10px; cursor:pointer; }
  .tools button[aria-pressed="true"] { background:var(--mauve); color:var(--mantle); }
  .note { color:var(--subtext); font-size:11px; }
  .empty { color:var(--overlay); padding:14px 12px; }
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
</nav>

<main>
  <section id="status">
    <div class="grid" id="cards"></div>
    <p class="note" id="status-note"></p>
  </section>

  <section id="timeline" hidden>
    <div class="tools">
      <input type="search" id="tl-filter" placeholder="filter (project, session, line)">
      <button id="tl-follow" aria-pressed="true">following</button>
      <span class="note" id="tl-note"></span>
    </div>
    <div class="stream" id="tl"></div>
  </section>

  <section id="log" hidden>
    <div class="tools">
      <input type="search" id="lg-filter" placeholder="filter">
      <button id="lg-follow" aria-pressed="true">following</button>
      <button id="lg-clear">clear</button>
      <span class="note" id="lg-note"></span>
    </div>
    <div class="stream" id="lg"></div>
  </section>
</main>

<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => (
  {"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

document.querySelectorAll('nav button').forEach((b) => b.onclick = () => {
  document.querySelectorAll('nav button').forEach((o) =>
    o.setAttribute('aria-selected', String(o === b)));
  for (const name of ['status', 'timeline', 'log']) $(name).hidden = name !== b.dataset.tab;
});

function follower(button) {
  let on = true;
  button.onclick = () => { on = !on; button.setAttribute('aria-pressed', String(on));
                           button.textContent = on ? 'following' : 'paused'; };
  return () => on;
}
const tlFollow = follower($('tl-follow'));
const lgFollow = follower($('lg-follow'));

function appendRow(box, html, following) {
  const near = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  box.insertAdjacentHTML('beforeend', html);
  while (box.childElementCount > 2000) box.firstElementChild.remove();
  if (following() && near) box.scrollTop = box.scrollHeight;
}

function applyFilter(box, input) {
  const q = input.value.trim().toLowerCase();
  for (const row of box.children)
    row.style.display = !q || row.textContent.toLowerCase().includes(q) ? '' : 'none';
}
$('tl-filter').oninput = () => applyFilter($('tl'), $('tl-filter'));
$('lg-filter').oninput = () => applyFilter($('lg'), $('lg-filter'));
$('lg-clear').onclick = () => { $('lg').innerHTML = ''; };

const card = (title, value, note) =>
  `<div class="card"><h2>${esc(title)}</h2><div class="v">${esc(value)}</div>` +
  (note ? `<div class="n">${esc(note)}</div>` : '') + `</div>`;

const secs = (n) => {
  if (n === null || n === undefined || n === '-') return 'never';
  if (n < 90) return Math.round(n) + 's ago';
  if (n < 5400) return Math.round(n / 60) + 'm ago';
  return (n / 3600).toFixed(1) + 'h ago';
};

async function get(url) {
  const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) throw new Error(url + ' -> ' + res.status);
  return res.json();
}

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
    $('p-silent').className = 'pill ' + (
      sum.daemon_silent_for === null ? 'warn' : '');

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
    if (st.summarizerDegraded) {
      cards.unshift(card('Summarizer degraded', st.summarizerDegraded + 'x',
                         st.summarizerLastDegrade || 'fell back to template'));
    }
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
      if (seen.has(r.id)) continue;                    // `since` is >=, so re-delivery happens
      seen.add(r.id);
      lastTs = Math.max(lastTs, r.ts);
      const when = new Date(r.ts * 1000).toLocaleTimeString();
      const ms = r.play_ms ? ` ${(r.play_ms / 1000).toFixed(1)}s` : '';
      appendRow($('tl'),
        `<div class="row"><span class="t">${esc(when)}</span>` +
        `<span class="d d-${esc(r.decision)}">${esc(r.decision)}</span>` +
        `<span class="who">${esc(r.project || r.session_key || '')}</span>` +
        `<span class="m">${esc(r.line || r.state || '')}${esc(ms)}</span></div>`, tlFollow);
      added++;
    }
    if (added) applyFilter($('tl'), $('tl-filter'));
    if (!$('tl').childElementCount) {
      // An empty result is ambiguous: history fails open and returns [] when its database
      // is unusable, so "all quiet" is not a safe thing to claim.
      $('tl').innerHTML = '<div class="empty">No decisions recorded yet. ' +
        'If this stays empty while audio plays, the history database is unreadable.</div>';
    }
    $('tl-note').textContent = seen.size + ' rows';
  } catch (err) {
    $('tl-note').textContent = String(err);
  }
}

function startLog() {
  const stream = new EventSource('/v1/logs/stream');
  stream.onopen = () => { $('lg-note').textContent = 'streaming'; };
  stream.onerror = () => { $('lg-note').textContent = 'stream dropped, retrying'; };
  stream.addEventListener('meta', (e) => { $('lg-note').textContent = e.data; });
  stream.addEventListener('line', (e) => {
    const p = JSON.parse(e.data);
    const html = p.ts
      ? `<div class="row lv-${esc(p.level)}"><span class="t">${esc(p.ts.slice(11, 19))}</span>` +
        `<span class="who">${esc(p.logger.replace(/^ttsd\\.?/, '') || 'ttsd')}</span>` +
        `<span class="m">${esc(p.message)}</span></div>`
      : `<div class="row cont">${esc(p.raw)}</div>`;
    appendRow($('lg'), html, lgFollow);
    if ($('lg-filter').value) applyFilter($('lg'), $('lg-filter'));
  });
}

refreshStatus(); refreshTimeline(); startLog();
setInterval(refreshStatus, 3000);
setInterval(refreshTimeline, 2000);
</script></body></html>
"""
