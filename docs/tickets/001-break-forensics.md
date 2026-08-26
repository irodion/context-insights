# 001 — Break forensics: show *what* invalidated the cache

**Status:** open · **Priority:** 1

## Context

The parser detects *that* a Cache Break happened and what it cost (Re-billed
Tokens), but not *why*. The rollout JSONL stores the full event stream
(`response_item`, `turn_context`, `event_msg`) around each break, so the cause
is usually recoverable without proxying requests.

## Goal

For a given session + break request index, print a short diagnosis of what
changed in the prompt prefix, e.g.:

- `turn_context` changed between requests (model, effort, sandbox config
  swap → full prefix invalidation)
- history mutation (an earlier item edited/removed — compare `response_item`
  ids before vs after)
- session restart / resume (new `session_meta`)
- unknown (fall back to dumping the surrounding events)

## Sketch

- `parse_codex.py --explain <file> <request-idx>` (or `--explain-all <file>`).
- Correlate `token_count` events with the `response_item`s between them;
  diff the id-sequence of items before the break against the prior request.
- Surface the verdict in the waterfall tooltip later (separate ticket if big).

## Acceptance

- Running `--explain` on the easycall 2026-03-20 session (requests 16–19,
  4× ~80k re-billed) names a concrete cause, not "unknown".
- No change to existing summary/detail output.

## Resolved research (2026-08-26)

Investigated the easycall 2026-03-20 session timeline. **The rollout carries
enough to attribute breaks.** Every break sits at a turn boundary; three
detectable cause categories:

1. **TTL expiry** — long idle gap (`task_complete` → next `task_started`),
   then cached ≈ 0. Easycall requests 18 (1h40m gap) and 27 (15m gap).
2. **Turn-boundary history rewrite** — partial cache retention (request 23
   kept 80k of 111k): prefix diverged mid-history, consistent with reasoning
   items being dropped/re-serialized at turn start. Distinguish from TTL by
   partial survival + short gap.
3. **turn_context change** — model/effort/sandbox logged per turn; diff it.

Parser fixes to fold into this ticket:
- **Duplicate token_count events**: identical last_token_usage replayed
  across a turn boundary (easycall requests 16/17) — dedupe before analysis,
  currently inflates break counts.
- Turn boundaries are explicit (`task_started`/`task_complete` +
  `user_message`) — record turn index per request; `--explain` should report
  the idle gap preceding a break.
