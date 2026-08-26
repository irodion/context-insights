# 001 — Break forensics: show *what* invalidated the cache

**Status:** done (2026-08-26) · **Priority:** 1

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

## Also in scope (added 2026-08-26)

- **Idle-gap advisor**: one summary line converting the diagnosis into
  behavior — "sessions resumed after >X min idle cost you N tokens
  (re-billed); a fresh session would have been cheaper or equal." Compute
  from TTL-expiry breaks; X derived from observed gap/break correlation,
  not hardcoded.
- **Reading**: skim "Don't Break the Cache" (arXiv, 500+ agent sessions,
  41-80% cost reduction) before building — steal their break-cause taxonomy
  if richer than our three categories; note their 7-15% typical hit rate as
  a comparison baseline for our output.

## Acceptance

- Running `--explain` on the easycall 2026-03-20 session (requests 16–19,
  4× ~80k re-billed) names a concrete cause, not "unknown". ✅ Those four were
  three real Requests plus one replay; post-dedupe they are requests 16, 17, 18
  and come back as *turn-boundary history rewrite*, *TTL expiry* and
  *cache warm-up*. All five breaks in the session are named; none is "unknown".
- No change to existing summary/detail output. ✅ Format unchanged; counts move
  where the dedupe fix removes phantom Requests (see Decisions).

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

## Decisions (2026-08-26)

**Six Break Causes, not three.** The three from the research split once the data
was in; all six are defined in `CONTEXT.md`. Two additions earned their place:

- *cache warm-up* — after a cold Request, the next Request misses too because the
  cache write has not landed (easycall req 18, 10s later, still cold). Without it
  that Request reads as a second, unrelated break and double-counts one root cause.
- *mid-turn history change* — 82% of mid-Turn breaks keep partial prefix, spread
  evenly across retention rather than clustering at the 0.8 threshold, so they are
  real divergences and not artifacts of `BREAK_RATIO`.

*unknown* survives for cold mid-Turn breaks with no gap and no context change
(~18% of mid-Turn breaks). Nothing in the log accounts for those; the fallback
says so instead of guessing.

**`turn_id` must be excluded from the `turn_context` diff.** It is fresh on every
Turn, so a naive diff blames every single turn-boundary break on a context change.
In the easycall session all five `turn_context`s are identical but for `turn_id`.
Large fields (developer instructions, sandbox policy) are stored as digests, so
`--json` does not grow by ~40KB per Turn.

**The ticket's "compare `response_item` ids" sketch is not available** — Codex
`response_item`s carry no `id`, and the rollout is append-only, so a history
rewrite never appears in the log directly. It is inferred instead from position
(first Request of a Turn), Idle Gap, and Retention.

**Duplicate `token_count` fix is broader than the ticket assumed.** Two replay
shapes, not one: sub-second double-emit *within* a Turn (205 in the corpus) and
the cross-Turn replay the ticket found (69). One rule covers both — usage
byte-identical to the previous Request is a replay, not a Request. Corpus effect:
7844 → 7628 requests, 418 → 390 breaks, 21.7M → 19.3M re-billed. 11% of the
re-billed total was phantom.

Matching per-request counts alone are *not* proof of a replay — two genuine calls
could bill identically — so the rule also requires `total_token_usage` to have
stood still, which only a replay does (review of PR #2). No behaviour change on
today's corpus: all 274 replays have the cumulative total unchanged and zero
Requests would have been wrongly dropped, so the two rules agree request-for-request.
It closes a latent hole rather than fixing a live symptom.

**Idle threshold is derived, not hardcoded.** `idle_gap_advice()` walks a ladder
of gaps and reports the shortest at which ≥50% of resumed Requests broke. On this
corpus that is 10m, covering 10.8M of 19.3M re-billed tokens. The gap/break
correlation behind it: <2m 3%, 2–5m 15%, 5–10m 28%, 10–20m 35%, 20–60m 69%,
>1h 86%. `TTL_GAP_S` stays a constant for *classification* (600s, matching the
documented provider TTL); the advisor's threshold is the empirical one.

**Reading — "Don't Break the Cache" (arXiv 2601.06007).** Its taxonomy is about
prompt *construction* (dynamic content late in the system prompt, avoid dynamic
tool definitions, exclude dynamic tool results), not about attributing a break
from a log — not richer than ours for this purpose, so ours stands. Their 41–80%
cost reduction is a savings range, not a hit rate; our corpus sits at 92% hit
rate, so the 7–15% baseline in the ticket is not a like-for-like comparison and
was not adopted.

**Testing.** Seam under test is `explain_breaks()` only, agreed up front;
synthetic rollouts run through the real adapter, so no private session data
enters the repo. The acceptance run against the real easycall session stays a
manual check. Runner is stdlib `unittest` — no new dependency — wired into the
pre-push hook and CI.

**Scope note.** "No change to existing summary/detail output" holds for format,
but the *numbers* move: the dedupe fix removes phantom requests and breaks, which
is the point of the fix. The advisor adds one trailing line to the summary.
