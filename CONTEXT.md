# Context Insights — Ubiquitous Language

## Core concepts

**Agent Source** — a CLI AI agent whose logs we can parse. Currently: Codex CLI (`~/.codex/sessions`). Planned: Cursor CLI Agent (no local install yet, adapter deferred). Each Agent Source gets an adapter that normalizes its logs into Sessions and Requests.

**Session** — one conversation thread of an agent, backed by one rollout file (Codex: `rollout-*.jsonl`). Has a Thread Source.

**Thread Source** — who initiated the Session: `user` (a person in the TUI/Desktop), `subagent` (spawned by another Session), or other (`realtime_voice`, ...). Subagent Sessions replay the parent's token history into their own log; their replayed prefix must not be counted as this Session's own spend.

**Request** — one API call to the model, the atomic unit of measurement. In Codex logs it is a `token_count` event; its `last_token_usage` gives this Request's own tokens: input, cached input, cache-write input, output, reasoning output.

**Turn** — one user-prompt-to-final-answer exchange; contains one or more Requests (the agentic loop).

## Cache vocabulary

**Cached Input** — the portion of a Request's input tokens served from the provider's prompt cache (billed at the discounted rate).

**Expected Cache** — what *should* have been cached on a Request in a healthy linear agent loop: approximately the full prompt of the previous Request (its input tokens). The first Request of a Session has no Expected Cache.

**Cache Break** — a Request whose Cached Input falls materially below its Expected Cache: the prompt prefix changed and the cache was invalidated from that point on.

**Re-billed Tokens** — the tokens a Cache Break cost: Expected Cache minus Cached Input. These were paid at the full input rate although they had been processed (and cached) before.

**Compaction** — the agent summarizes history to shrink context; input tokens drop sharply. Looks like a Cache Break in the numbers but is deliberate; classified separately.

**Hit Rate** — Cached Input / total input tokens, per Request or aggregated over a Session.

**Prefix Floor** — the head of the prompt that is re-sent identically on every
Request and so re-caches immediately after any Cache Break: system header, tool
definitions, instructions. It is not conversation, so it must not count as
surviving conversation. Derived per Session as the smallest non-zero Cached Input
across the Requests that *rebuilt* the prefix — the first Request, every Cache
Break and every Compaction; a Hit continues an existing prefix, and its Cached Input
is the whole previous prompt, which bounds the head from above rather than locating
it. The smallest such value is the Prefix Floor **only when a second rebuild lands
within 10% of it**; otherwise the Prefix Floor is zero and Retention stays
unadjusted.

Corroboration is what makes the value a floor at all: the smallest Cached Input is
the re-cached head only if the cache ever came back head-only, and on a Session
where it never does it is just the deepest Cache Break — subtracting it would force
that Break's own Retention to zero by construction. **Only the smallest rebuild is
eligible.** A Cache Break can be a partial divergence that kept most of the
conversation, so two Breaks landing near each other agree on nothing; looking past
an uncorroborated smallest value to the next pair cannot be told apart from a
Session whose deepest Break came back under the head, and would invent a floor above
surviving conversation. Under-stating the floor leaves Retention over-reported;
over-stating it invents coldness. Under-stating is the safe direction.

On a Session still being written the floor is provisional: a later, colder rebuild
can lower it, and lower every Retention already reported for that Session.

**Retention** — on a Cache Break, the share of the *recoverable* prefix that
survived, measured above the Prefix Floor: (Cached Input − Prefix Floor) /
(Expected Cache − Prefix Floor), clamped to zero. Near zero means the cache was
*cold* — nothing but the re-sent head came back; a middling value means the prompt
*diverged* part-way through while the cache was still alive. The two call for
different fixes, so they are diagnosed separately. Measured against zero rather
than against the floor, a Break that kept no conversation at all still reports
Prefix Floor / Expected Cache, which on a short Session is a large number.

**Idle Gap** — seconds between a Request and the Request before it. The dominant
predictor of a Cache Break: measured over this corpus, under 2 minutes 3% of
Requests break, beyond an hour 86% do.

**Replayed Request** — a `token_count` event the agent re-emits without a new API
call having happened (Codex does this twice within a Turn and again when the next
Turn opens). Its usage is byte-identical to the Request before it. Not a Request:
counting it invents Cache Breaks that never occurred.

## Watching

**Live Session** — the Session being written to right now: the most recently
modified rollout with Thread Source `user`. Subagent Sessions are skipped — the
one you are sitting in front of is the one worth watching.

**Watch Mode** — follow the Live Session and rebuild the Waterfall every few
seconds, so a Cache Break shows up while you are still in the Turn that caused
it. The Live Session is pinned first in the Waterfall; the rest keep their
re-billed ranking.

## Break Cause

**Break Cause** — what invalidated the prefix, attributed to each Cache Break from
the surrounding log events. One of the following, tested in the order listed: the
first that fits wins, so a Break Cause is what best explains the break rather than
the only thing that changed. `--explain` names the others alongside it.

- **TTL expiry** — a long Idle Gap, and the cache came back cold. The prefix simply
  aged out provider-side. Tested before any context difference: a Session resumed
  days later almost always shows a different `current_date` too.
- **turn_context change** — one or more tracked `turn_context` fields differ from
  the previous Turn (model, effort, sandbox and instructions among them), so the
  prompt header changed and the whole prefix died — and TTL expiry did not already
  explain it. (`turn_id` is fresh every Turn by design and never counts as a
  change.)
- **cache warm-up** — a miss seconds after a cold Request, whose cache write had not
  landed yet. Attributable to the *preceding* break, not to a new cause.
- **turn-boundary history rewrite** — the first Request of a new Turn, cache still
  warm, prefix diverged anyway: history was re-serialized between Turns.
- **mid-turn history change** — a partial-Retention break inside a Turn; the prompt
  changed part-way through while the cache was alive.
- **unknown** — a cold break with no Idle Gap and no context change. Nothing in the
  log accounts for it; say so rather than inventing a cause.

## Visualization

**Waterfall** — the target visual: Requests on the x-axis over time, each drawn as a stacked bar of Cached Input (cool) vs uncached input (hot), like an RF spectrum waterfall. Cache Breaks show as hot spikes.
