# 012 — Break Cause reported by the source, not inferred

**Status:** blocked on a vocabulary decision — see
`.scratch/agent-source-capability` ticket 06 · **Priority:** 2 (after 005)

## Context

`explain_breaks()` reconstructs a Break Cause from gaps, Retention and a
`turn_context` diff. Ticket `010` has just spent four commits refining that
reconstruction.

Claude Code's server **states the answer outright.**
`message.diagnostics.cache_miss_reason` appears on 221 deduped Requests across
80 files, with six types that map almost one-to-one onto `CONTEXT.md`'s six
Break Causes:

| `cache_miss_reason.type` | Requests | our Break Cause |
|---|---:|---|
| `previous_message_not_found` | 126 | **TTL expiry** — 104 of 105 breaks at >1h |
| `unavailable` | 53 | **cache warm-up** |
| `tools_changed` | 19 | **turn_context change** — all at <2m |
| `model_changed` | 10 | **turn_context change** |
| `messages_changed` | 10 | **history rewrite / Compaction** |
| `system_changed` | 3 | **turn_context change** |

The four `*_changed` types also carry **`cache_missed_input_tokens`** —
Re-billed Tokens, from the server. Validated against our arithmetic over 42
samples the median ratio is 1.169, and **the outliers are exactly the compaction
cases where naive Expected Cache over-counts by 6–14x**. Where the two disagree
most, the server is right and we are wrong.

Claude Code also records the cache TTL per Request (`cache_creation.ephemeral_1h`
/ `ephemeral_5m`), which `TTL_GAP_S = 300` exists to approximate.

## Why this is blocked

`CONTEXT.md` says analysis must not know which agent produced a Session. Acting
on any of the above breaks that rule: it means the analysis layer branches on
whether the source supplied an answer.

The decision — does the rule survive, become "agent-agnostic but
capability-aware", or break — is
[map ticket 06](../../.scratch/agent-source-capability/issues/06-agent-agnostic-contract.md).
This ticket implements whatever 06 decides; it must not pre-empt it.

## The hard part, once unblocked

**Neither signal subsumes the other**, so "prefer the server" is not the whole
rule:

- **92 arithmetic breaks carry no server reason** — 69 at a 10–60m Idle Gap, 10
  where the model differs from the previous Request (a Haiku title-generation
  call is not a break in the Opus prefix), and 13 with no gap and nothing
  changed, which is `CONTEXT.md`'s honest *unknown*.
- **72 Requests carry a server reason without an arithmetic break.**

So the design question is not "which source of truth wins" but how two partial,
overlapping signals compose — and what `explain_breaks()`, which `CLAUDE.md`
names as this project's agreed test seam, becomes when one source needs it and
another does not.

## Scope

- Whatever 06 decides, expressed in `CONTEXT.md` before any code.
- Break Cause, Re-billed Tokens and cache TTL sourced from the transcript where
  present, from the heuristic where not.
- `--explain` must make clear which it is showing. A server-reported cause and an
  inferred one are not the same kind of claim and should not read alike.

## Acceptance

- The 155 Claude Code Cache Breaks keep their causes, with the 63 that carry a
  server reason labelled as reported rather than inferred.
- Re-billed Tokens at compaction boundaries stop over-counting by 6–14x.
- Codex output is byte-identical — this ticket adds a capability, it does not
  change the heuristic for a source that has no server signal.
