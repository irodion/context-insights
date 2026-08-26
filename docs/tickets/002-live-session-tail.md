# 002 — Live session tail: waterfall for the session you're in

**Status:** open · **Priority:** 2

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
  poll interval.
- Ctrl-C leaves no stray processes.

## Non-goals

- Multi-machine, auth, packaging. Local single-user only.
