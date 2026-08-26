# 002 — Live session tail: waterfall for the session you're in

**Status:** done (2026-08-26) · **Priority:** 2

## Context

The waterfall is post-hoc: run `parse_codex.py --web`, reload the page. The
original product idea is to *see the cache break as it happens* while working
in Codex.

## Goal

A watch mode that follows the newest active rollout file and updates the
waterfall in near-real-time (a few seconds of lag is fine).

## Sketch

Cut-corner architecture (no websockets, no server framework):

- `parse_codex.py --watch`: loop — find the most recently modified
  `rollout-*.jsonl` with `thread_source: user`, re-parse just that file,
  rewrite `waterfall_data.js` (live session first), sleep ~3s.
- `waterfall.html`: when served over http, poll `waterfall_data.js` every few
  seconds (fetch + eval or switch the data file to JSON) and re-render,
  keeping the current selection/scroll.
- `--watch` can also start the local http server (`http.server` thread) so
  the whole thing is one command: `python3 parse_codex.py --watch` → prints
  the URL.

## Acceptance

- Start a Codex session, run watch mode, prompt Codex a few times: new bars
  appear without manual reload; a provoked cache break shows red within one
  poll interval. ✅ Driven in Chrome against a synthetic rollout: appending a
  Request grew the chart from 3 → 4 → 5 bars with the break drawn red and the
  header totals updated, `performance.getEntriesByType("navigation").length`
  still 1 — no reload. Filter text, caret, focus and the selected row all
  survived the live re-render.
- Ctrl-C leaves no stray processes. ✅ SIGINT to the real CLI exits 0, prints
  `stopped`, and the port is free immediately after.
- A Session caught before it has billed anything renders sanely. ✅ A rollout
  caught empty or mid-line is not a Session yet and is skipped until the next
  tick; one whose `session_meta` has landed but has no Requests shows
  "no requests yet" rather than `hit rate NaN%` / `max -Infinity`.
- Switching rollouts does not roll the Waterfall backward. ✅ Session A opens
  below `--min-requests`, grows to 3 Requests and a 74k break while live, then
  Session B becomes newest: A keeps all 3 Requests and the break, and exactly one
  row is flagged live.

## Non-goals

- Multi-machine, auth, packaging. Local single-user only.

## Decisions (2026-08-26)

**The corpus is parsed once; only the Live Session is re-read.** A full parse of
295 sessions takes ~0.7s — fine at startup, wasteful every 3s. `watch()` keeps the
analyzed baseline in memory and each tick re-reads one file and splices it in,
replacing its stale copy. A tick costs one file read.

`find_live_session()` reads only the opening `session_meta` line via
`peek_thread_source()` — it needs one field, and full-parsing every candidate meant
parsing the winner twice per tick.

A tick's change signal is the Live Session's own totals (~0.2µs), and the payload
is rebuilt only when they actually move (~1.4ms over 296 sessions). Deep-comparing
the whole payload every 3s was work that scaled with corpus size to answer a
question only one Session could change the answer to.

**Sessions are held by id, latest state wins.** The first cut kept a frozen
startup snapshot of everything but the Live Session, which was wrong in two ways
the moment Watch Mode switched rollouts: a Session that had accrued Requests while
live reverted to its startup state, and one that started below `--min-requests`
vanished from the Waterfall entirely — bars and totals rolling *backward* while
watching. `watch()` now keeps a `{session_key: session}` map it updates each tick,
so anything seen live keeps what it accrued. `waterfall_payload()` stays the only
place that knows the ordering rule, and it re-ranks from current totals rather
than from a stale snapshot. `session_key()` gives the id rule one owner, shared
with the row identity the viewer selects by.

**The Live Session skips subagents.** Naive newest-mtime picks the wrong file: a
subagent spawned mid-Turn writes *after* the parent, so the chart would jump to a
Session you are not sitting in front of. `find_live_session()` walks rollouts in
mtime order and returns the first with Thread Source `user`.

**Selection is held by Session id, not row number.** The payload is re-ranked on
every rewrite as the Live Session accrues Re-billed Tokens, so a row index points
somewhere else a tick later. Rows now carry `id`, and the viewer resolves its
selection through it. Same reason the payload carries `live`: the page cannot
otherwise tell which row is being tailed, and pinning-to-first is not evidence.

**Polling, not websockets.** The page re-fetches `waterfall_data.js` every 3s,
parses it and re-renders only when the bytes changed. Writes are atomic
(`tmp.replace`) so a fetch cannot catch a half-written file; a parse failure is
swallowed and retried next tick. Over `file://` nothing polls, so the static path
is unchanged.

`setInterval` does not serialize its calls, so a slow fetch can land after a newer
one and overwrite the screen with an older payload. Each poll takes a sequence
number before awaiting and drops its response if a later poll has since started.
Reproduced by forcing the interleaving in the browser: without the guard the late,
older payload wins; with it, it is discarded.

**Scroll and focus survive the re-render.** `render()` still swaps `innerHTML`
wholesale, so it now captures scroll/focus/caret first and restores after. Bars
scrolled to the right edge stay pinned there, so new Requests appear as they are
billed. This also retires the old re-focus hack in the filter handler.

**Testing.** Seams agreed up front: `find_live_session()` and
`waterfall_payload()`. The http server and the browser polling stay untested
wiring, verified by hand (see Acceptance) rather than by a test that would mostly
assert `time.sleep`.

**A Session is not a Session until the log says so.** Watch Mode races the agent
writing the file, so a tick can catch a rollout that exists but holds nothing, or
half an opening line. The adapter already returned `None` for that; `tick()` was
testing the *path* rather than the loaded value and handed `None` to `analyze()`,
which took the watcher down. It now tests what came back. The state right after —
`session_meta` written, no Request billed yet — is a real Session with an empty
Waterfall, which the page has to render rather than divide by: an unguarded `max`
gave `-Infinity` and a zero-token corpus gave `NaN%`, in the first seconds of
every watched Session.

**A third seam, added after the loop shipped a bug.** Leaving the loop untested
cost exactly what the switch bug above describes — no unit test could see it,
because the defect was in what the loop carried *between* iterations. `WatchMode`
now holds that state and `tick()` is the seam: one iteration in, the rows to
render out, or None when nothing moved. `watch()` keeps only the parts worth
leaving untested — the server, the printing, the sleep. The retention test drove
the extraction red-first; the two contract tests around it (a quiet tick asks for
no rewrite, the first tick always renders) were written after and pin behaviour
that already worked. The first-tick guard is new: without it, watching an empty
directory rendered nothing and left a previous `--web` run's corpus on screen,
where a stale snapshot reads as live.
