# agentmemory-console — the proxy and UI in front of memory

Four ports, and knowing which is which is the whole page. Long-form reference:
`services/console/README.md`; the in-app help is at `#/help`.

## Which port is which

| port | what | who talks to it |
|---|---|---|
| 3110 | the memory server itself — **the bypass** | you, when diagnosing |
| 3111 | the console's transparent proxy | **every wired agent** |
| 3112 | the server's event stream | the console |
| 3113 | the stock viewer that ships with the server | you |
| 3114 | the console UI, `/api`, `/ws`, `/healthz` | your browser |

The console sits *in front of* the memory server: agents point at 3111, the
console forwards to 3110, and it records metadata about each request on the way
past so the UI can show what happened.

## The diagnostic that follows from that

If **3110 answers and 3111 does not**, the console is down — not agentmemory.
That is a different fix, and it is the mistake worth avoiding because 3111 is the
port everything is configured to use.

```sh
ts-stack status            # shows all of them
ts-stack logs agentmemory  # both containers
```

## Making it fit: the console's own zoom

The console scales itself, so you do not have to use the browser's zoom.

| | |
|---|---|
| sidebar `-  100%  +` | 5% a step, 50% to 200% |
| click the number | back to 100% |
| Customize drawer -> UI scale | the same value, as a slider |

Saved in `localStorage` with the rest of your preferences, and **global** rather
than per page: a zoom that resets when you change page is not a zoom.

Why it exists rather than telling you to press Ctrl+-: the browser's zoom shrinks
the *viewport*, so the app frame gets shorter and the SystemBar pinned at its
bottom goes off the end of the window. The console's zoom scales the content
inside a frame that stays exactly the size of the window, so nothing can fall off
it however far you go, and the content scrolls in its own pane instead. If the
page itself ever scrolls under the window, that is a bug -- the frame is sized in
measured pixels for exactly that reason, and `html`/`body` are `overflow: hidden`
as a second guard.

Layout follows the content too: the project cards and the metric tiles fit as
many columns of a readable width as there is room for, and share what is left
over. Six projects wrap to two rows; three spread across the full width; hiding a
widget reflows the rest instead of leaving a gap.

## What it stores

Its own SQLite database (`ts-agentmemory-console-history`), holding **minute
aggregates only** — counts, gauges, a salted session hash, a latency histogram.
No paths, no bodies, no prompts, no memory content, no raw session IDs. Retention
defaults to 365 days.

That volume is `external: true`, like the memory volume, so `down -v` cannot
remove it.

## It builds from this repo

The console's source is `services/console/`, and the compose build context is a
relative path to it. Before, it was a pinned commit SHA of a separate repository,
so every console change was push → re-pin → rebuild. The trade: a dirty working
tree builds a dirty image, so `git status` before `ts-stack up` is the discipline.

```sh
ts-stack up agentmemory     # rebuilds the console when its source changed
cd services/console && npm ci && npm test    # its own suite, no Docker needed
```

It needs Node 24 (`node:sqlite`'s `DatabaseSync`), pinned in
`services/console/.node-version` so fnm selects it on `cd` without prompting.

See also: `doc agentmemory` · `doc services`
