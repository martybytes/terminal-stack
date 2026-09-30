"""The HTML shell: one string, inline CSS and JS, no assets, ASCII only.

Same reasoning as the TTS daemon's dashboard page: nothing to bundle, nothing
to serve separately, and it renders from a PyInstaller exe or a static folder
opened from disk alike. The palette is Catppuccin (Mocha dark, Latte light),
the same one docs/kb/_style/*.json gives glow.
"""

from __future__ import annotations

import html
from collections.abc import Callable

from .index import GROUP_TITLES, Topic

CSS = """
:root{--bg:#1e1e2e;--bg2:#181825;--surface:#313244;--text:#cdd6f4;--muted:#a6adc8;--dim:#6c7086;
--accent:#89b4fa;--accent2:#cba6f7;--code:#fab387;--ok:#a6e3a1;--border:#45475a;--sel:#585b70}
html[data-theme=light]{--bg:#eff1f5;--bg2:#e6e9ef;--surface:#dce0e8;--text:#4c4f69;--muted:#6c6f85;--dim:#9ca0b0;
--accent:#1e66f5;--accent2:#8839ef;--code:#fe640b;--ok:#40a02b;--border:#bcc0cc;--sel:#ccd0da}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;display:grid;grid-template-columns:280px 1fr;grid-template-rows:auto 1fr;grid-template-areas:"top top" "nav main";height:100vh}
header{grid-area:top;display:flex;gap:12px;align-items:center;padding:10px 16px;background:var(--bg2);border-bottom:1px solid var(--border)}
header .brand{font-weight:700;color:var(--accent);text-decoration:none;white-space:nowrap}
header input{flex:1;max-width:560px;padding:7px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text);font:inherit}
header button{padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font:inherit}
nav{grid-area:nav;overflow:auto;padding:12px 8px 24px;background:var(--bg2);border-right:1px solid var(--border)}
nav h3{margin:14px 10px 4px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}
nav a{display:block;padding:4px 10px;border-radius:5px;color:var(--muted);text-decoration:none;font-size:14px}
nav a:hover{background:var(--surface);color:var(--text)}nav a.here{background:var(--surface);color:var(--accent)}
main{grid-area:main;overflow:auto;padding:24px 40px 60px}
article{max-width:900px;margin:0 auto}
h1,h2,h3,h4{color:var(--accent);line-height:1.25;position:relative}h1{font-size:28px;margin-top:0}h2{font-size:21px;margin-top:34px;padding-top:10px;border-top:1px solid var(--border)}h3{font-size:17px;color:var(--accent2)}
a{color:var(--accent)}a.hl{opacity:0;margin-left:8px;text-decoration:none;font-weight:400;color:var(--dim)}h1:hover a.hl,h2:hover a.hl,h3:hover a.hl{opacity:1}
code{font:13px/1.45 ui-monospace,"JetBrainsMono Nerd Font","JetBrains Mono",Consolas,monospace;background:var(--surface);color:var(--code);padding:1px 5px;border-radius:4px}
a.ref code{color:var(--accent);text-decoration:underline dotted}
.codeblock{position:relative;margin:14px 0}pre{margin:0;padding:12px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;overflow:auto}
pre code{background:none;color:var(--text);padding:0;display:block}
.ln{display:block;padding:0 4px;border-radius:3px;cursor:pointer}.ln:hover{background:var(--surface)}.ln.copied{background:var(--sel)}
.copy{position:absolute;top:6px;right:6px;font-size:11px;padding:3px 8px;border-radius:5px;border:1px solid var(--border);background:var(--surface);color:var(--muted);cursor:pointer;opacity:0}
.codeblock:hover .copy{opacity:1}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:top}th{color:var(--muted);font-weight:600;background:var(--bg2)}
blockquote{margin:14px 0;padding:8px 14px;border-left:3px solid var(--accent2);background:var(--bg2);color:var(--muted)}
hr{border:0;border-top:1px solid var(--border);margin:24px 0}
.pn{display:flex;justify-content:space-between;gap:12px;margin-top:48px;padding-top:14px;border-top:1px solid var(--border);font-size:14px}
.pn a{text-decoration:none}.pn span{color:var(--dim)}
#results{position:absolute;left:0;right:0;top:52px;margin:0 auto;max-width:900px;max-height:70vh;overflow:auto;background:var(--bg2);border:1px solid var(--border);border-radius:8px;box-shadow:0 12px 40px rgba(0,0,0,.35);display:none;z-index:9}
#results a{display:block;padding:10px 14px;border-bottom:1px solid var(--border);text-decoration:none;color:var(--text)}
#results a:hover,#results a.sel{background:var(--surface)}#results .t{color:var(--accent);font-weight:600}#results .g{color:var(--dim);font-size:12px;margin-left:8px}#results .s{color:var(--muted);font-size:13px;margin-top:2px}
#results mark{background:transparent;color:var(--code);font-weight:600}
.toast{position:fixed;bottom:18px;right:18px;background:var(--surface);color:var(--ok);padding:8px 14px;border-radius:6px;border:1px solid var(--border);opacity:0;transition:opacity .2s}
.toast.show{opacity:1}
kbd{font:12px ui-monospace,monospace;background:var(--surface);padding:1px 5px;border-radius:4px;border:1px solid var(--border)}
@media (max-width:900px){body{grid-template-columns:1fr;grid-template-areas:"top" "main"}nav{display:none}main{padding:16px}}
"""

JS = """
(function(){
var base=document.body.getAttribute('data-base');
var input=document.getElementById('q'),box=document.getElementById('results'),corpus=null,sel=-1;
function theme(t){document.documentElement.setAttribute('data-theme',t);try{localStorage.setItem('kb-theme',t)}catch(e){}}
try{var saved=localStorage.getItem('kb-theme');if(saved)theme(saved)}catch(e){}
document.getElementById('theme').onclick=function(){theme(document.documentElement.getAttribute('data-theme')==='light'?'dark':'light')};
function toast(msg){var t=document.getElementById('toast');t.textContent=msg;t.className='toast show';setTimeout(function(){t.className='toast'},1200)}
function copyText(s){if(navigator.clipboard){navigator.clipboard.writeText(s).then(function(){toast('copied')})}else{var ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('copied')}}
document.addEventListener('click',function(e){
  var ln=e.target.closest('.ln');if(ln){copyText(ln.textContent.replace(/\\n$/,''));ln.classList.add('copied');setTimeout(function(){ln.classList.remove('copied')},600);return}
  var cp=e.target.closest('.copy');if(cp){var pre=cp.parentNode.querySelector('pre code');copyText(pre.textContent.replace(/\\n$/,''));return}
  if(!e.target.closest('#results')&&e.target!==input){hide()}
});
function hide(){box.style.display='none';sel=-1}
function esc(s){return s.replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function mark(s,q){var i=s.toLowerCase().indexOf(q);if(i<0)return esc(s);return esc(s.slice(0,i))+'<mark>'+esc(s.slice(i,i+q.length))+'</mark>'+esc(s.slice(i+q.length))}
function snippet(text,q){var i=text.toLowerCase().indexOf(q);if(i<0)return'';var a=Math.max(0,i-60),b=Math.min(text.length,i+q.length+90);return(a>0?'... ':'')+mark(text.slice(a,b),q)+(b<text.length?' ...':'')}
function score(row,q){var s=0,t=row.title.toLowerCase(),l=row.label.toLowerCase();
  if(t===q||l===q||l.split('/').pop()===q)s+=100;else if(t.indexOf(q)>=0)s+=40;else if(l.indexOf(q)>=0)s+=30;
  for(var i=0;i<row.headings.length;i++){if(row.headings[i].toLowerCase().indexOf(q)>=0){s+=15;break}}
  if(row.text.toLowerCase().indexOf(q)>=0)s+=5;return s}
function search(){var q=input.value.trim().toLowerCase();if(!q){hide();return}
  if(!corpus){fetch(base+'search.json').then(function(r){return r.json()}).then(function(d){corpus=d;search()});return}
  var hits=[];for(var i=0;i<corpus.length;i++){var sc=score(corpus[i],q);if(sc>0)hits.push([sc,corpus[i]])}
  hits.sort(function(a,b){return b[0]-a[0]});hits=hits.slice(0,30);
  if(!hits.length){box.innerHTML='<a><span class="s">no matches</span></a>';box.style.display='block';return}
  box.innerHTML=hits.map(function(h){var r=h[1];var hd=r.headings.filter(function(x){return x.toLowerCase().indexOf(q)>=0})[0];
    return'<a href="'+base+'kb/'+r.label+'.html"><span class="t">'+mark(r.title,q)+'</span><span class="g">'+esc(r.group)+'</span><div class="s">'+(hd?mark(hd,q):snippet(r.text,q))+'</div></a>'}).join('');
  box.style.display='block';sel=-1}
input.addEventListener('input',search);input.addEventListener('focus',function(){if(input.value)search()});
document.addEventListener('keydown',function(e){
  if(e.key==='/'&&document.activeElement!==input){e.preventDefault();input.focus();input.select();return}
  if(e.key==='Escape'){hide();input.blur();return}
  if(box.style.display==='block'){var items=box.querySelectorAll('a[href]');
    if(e.key==='ArrowDown'){e.preventDefault();sel=Math.min(items.length-1,sel+1)}else if(e.key==='ArrowUp'){e.preventDefault();sel=Math.max(0,sel-1)}
    else if(e.key==='Enter'&&sel>=0){items[sel].click();return}else return;
    for(var i=0;i<items.length;i++)items[i].classList.toggle('sel',i===sel);if(items[sel])items[sel].scrollIntoView({block:'nearest'})}
  else if(!e.ctrlKey&&!e.metaKey&&document.activeElement!==input){var pn=document.querySelector('.pn');if(!pn)return;
    if(e.key==='['&&pn.children[0].href)location=pn.children[0].href;if(e.key===']'&&pn.children[1].href)location=pn.children[1].href}
});
var here=document.querySelector('nav a.here');if(here)here.scrollIntoView({block:'center'});
})();
"""


def _nav(all_topics: list[Topic], current: str, href: Callable[[str], str]) -> str:
    groups: dict[str, list[Topic]] = {}
    for t in all_topics:
        if t.label == "_index":
            continue
        groups.setdefault(t.group, []).append(t)
    parts: list[str] = [
        f'<a href="{href("_index")}" class="{"here" if current == "_index" else ""}">Start here</a>'
    ]
    for group, items in groups.items():
        parts.append(f"<h3>{html.escape(GROUP_TITLES.get(group, group))}</h3>")
        for t in items:
            cls = ' class="here"' if t.label == current else ""
            parts.append(
                f'<a href="{href(t.label)}"{cls} title="{html.escape(t.label)}">{html.escape(t.title)}</a>'
            )
    return "\n".join(parts)


def page(
    *,
    topic: Topic,
    body: str,
    all_topics: list[Topic],
    href: Callable[[str], str],
    base: str,
    theme: str,
    prev_topic: Topic | None,
    next_topic: Topic | None,
) -> str:
    """One complete page. `href(label)` makes a link for this page's location
    (a server path or a relative static path); `base` is the same prefix for
    the JS (search.json, results)."""
    prev_html = (
        f'<a href="{href(prev_topic.label)}">&larr; {html.escape(prev_topic.title)}</a>'
        if prev_topic
        else "<span></span>"
    )
    next_html = (
        f'<a href="{href(next_topic.label)}">{html.escape(next_topic.title)} &rarr;</a>'
        if next_topic
        else "<span></span>"
    )
    return f"""<!doctype html>
<html lang="en" data-theme="{html.escape(theme)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(topic.title)} - terminal-stack docs</title>
<style>{CSS}</style>
</head>
<body data-base="{html.escape(base)}">
<header>
<a class="brand" href="{href("_index")}">terminal-stack docs</a>
<input id="q" type="search" placeholder="search topics, headings, commands  (press /)" autocomplete="off" spellcheck="false">
<button id="theme" type="button" title="dark / light">theme</button>
<div id="results"></div>
</header>
<nav>{_nav(all_topics, topic.label, href)}</nav>
<main><article>
{body}
<div class="pn">{prev_html}{next_html}</div>
<p><small>keys: <kbd>/</kbd> search &middot; <kbd>[</kbd> <kbd>]</kbd> previous / next &middot; click a code line to copy it</small></p>
</article></main>
<div id="toast" class="toast"></div>
<script>{JS}</script>
</body>
</html>
"""
