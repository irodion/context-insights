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
evaluates it in a `Function` and re-renders only when the bytes changed. Writes
are atomic (`tmp.replace`) so a fetch cannot catch a half-written file; a parse
failure is swallowed and retried next tick. Over `file://` nothing polls, so the
static path is unchanged.

**Scroll and focus survive the re-render.** `render()` still swaps `innerHTML`
wholesale, so it now captures scroll/focus/caret first and restores after. Bars
scrolled to the right edge stay pinned there, so new Requests appear as they are
billed. This also retires the old re-focus hack in the filter handler.

**Testing.** Seams agreed up front: `find_live_session()` and
`waterfall_payload()`. The loop, the http server and the browser polling stay
untested wiring, verified once by hand (see Acceptance) rather than by a test
that would mostly assert `time.sleep`.
