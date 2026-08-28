# 015 — A tool-set change is a Break Cause we can already see

**Status:** open · **Priority:** 2

## Context

`.scratch/agent-source-capability`
[ticket 09](../../.scratch/agent-source-capability/issues/09-grade-the-heuristic.md)
graded `explain_breaks()` against Claude Code's server-reported Break Cause. The
two worst-scoring buckets were *mid-turn history change* (0 of 11) and *unknown*
(0 of 12) — and **all 23 were server-reported config changes**, 19 of them
`tools_changed`.

Our heuristic identifies **0 of 19** tool-set changes, because the
`turn_context` fingerprint has nothing to diff: neither source records the tool
set in a per-Turn context object.

## Why this is not blocked

The obvious fix — read the server's `cache_miss_reason` — is `012`, blocked on a
vocabulary decision about whether analysis may know a source reported the answer.

**This ticket needs none of that.** 09 found that **16 of the 19** `tools_changed`
Requests are immediately preceded by a tool result carrying `total_deferred_tools`
/ `matches` / `query` — a deferred-tool load. The cause is already in the log; it
is simply not in anything `explain_breaks()` currently reads. Deriving a Break
Cause from surrounding log events is exactly what `001` built the forensics for,
and it stays inside `CONTEXT.md`'s agent-agnostic rule.

It is also the more general fix: the server signal is **main-session-only** —
80 of 82 subagent Breaks carry no reason, and subagents are 38.7% of all Breaks —
whereas a log-derived signal works everywhere.

## Scope

- A new Break Cause for a changed tool set, named in `CONTEXT.md` first.
- Detect it from the events around the Break rather than from a context diff.
  Claude Code's marker is the deferred-tool-load record; **Codex's equivalent is
  an open question this ticket must answer before writing the detector** — a
  Codex rollout may show MCP server connections or tool-list changes, or may show
  nothing, in which case the cause is Claude-Code-only and that is a finding
  worth recording.
- Place it in the `explain_breaks()` chain deliberately. It competes with
  *mid-turn history change* and *unknown*, which are where these Breaks land
  today; per `010`, the ordering is a vocabulary fact and goes in `CONTEXT.md`.

## Acceptance

- The 19 `tools_changed` Breaks in the Claude Code corpus are attributed to the
  new cause rather than to *mid-turn history change* or *unknown*, and this is
  verified **against the server field as ground truth without consuming it** —
  the detector must not read `cache_miss_reason`, only be graded by it.
- The *unknown* bucket shrinks and nothing that was correctly attributed moves.
- Re-run ticket 09's confusion matrix and record the new agreement rate.
- Tests at the agreed seam.

## Note

If this lands well it reduces what `012` has left to buy, and it is evidence for
[map ticket 06](../../.scratch/agent-source-capability/issues/06-agent-agnostic-contract.md):
a cause thought to need the source's answer turned out to be derivable from the
log. That argues for keeping the agent-agnostic rule and reading more of the log,
rather than branching on source capability.
