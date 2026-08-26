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

## Open questions

- Do rollout files carry enough to distinguish "history edited" from
  "parallel tool calls raced"? Investigate on real breaks first; timebox it.
