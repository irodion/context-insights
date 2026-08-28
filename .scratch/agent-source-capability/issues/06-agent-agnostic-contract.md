# 06 — Does the agent-agnostic analysis contract survive?

Type: grilling
Status: open
Blocked by: 01, 02, 09

## Question

`CONTEXT.md` says analysis code must not know which agent produced a Session, and
`CLAUDE.md` repeats it: adapters normalize into one session dict.

[01](01-codex-quota-attribution.md) and [02](02-claude-code-telemetry.md) have now
established that the sources differ **in kind**, and the gap is wider than the
chart-time recon suggested. It is not that one source is missing a field. It is
that **Claude Code's server reports the answer this project's analysis layer
exists to compute.**

`message.diagnostics.cache_miss_reason` carries six types —
`previous_message_not_found`, `unavailable`, `tools_changed`, `model_changed`,
`messages_changed`, `system_changed` — which map almost one-to-one onto the six
Break Causes in `CONTEXT.md`, and 104 of the 105 `previous_message_not_found`
breaks sit beyond a 1h Idle Gap, exactly where our TTL heuristic puts them. The
`*_changed` types additionally carry `cache_missed_input_tokens`: Re-billed
Tokens, from the server.

So `explain_breaks()` — which `CLAUDE.md` names as this project's agreed test
seam, and which `docs/tickets/010` has just spent four commits refining — is a
*reconstruction* of something one source states outright, and an inferior one:
at compaction boundaries the naive Expected Cache over-counts by 6–14x while the
server figure stays honest.

[09](09-grade-the-heuristic.md) measures how often our heuristic already agrees
with the server. Do not decide 1 or 2 below without that number: if agreement is
near-total the server signal buys precision at compaction and little else, and if
it is poor the rule has been hiding real errors.

Two constraints [09](09-grade-the-heuristic.md) added that any answer must respect:

- **The server signal is main-session-only.** 80 of 82 subagent Breaks carry no
  reason, and subagents are **38.7% of all Breaks**. A design leaning on it
  degrades on more than a third of the corpus.
- **There is a third option.** 16 of the 19 `tools_changed` Breaks are preceded
  by a tool result carrying `total_deferred_tools` / `matches` / `query`. The
  cause is **in the log**, just not in anything `explain_breaks()` reads —
  reachable *without* breaking the agent-agnostic rule.

And the measured answer to the question this ticket was going to turn on:
**70.8% agreement by count, 81.6% by Re-billed Tokens.** The heuristic is right
about how much and wrong about why, so this is not a single yes/no.

Decide three things.

1. **Does the rule survive as-is, become "agent-agnostic but capability-aware"
   with each adapter declaring what it can supply, or break?** A strictly
   agent-agnostic layer can only express the *intersection* of its sources — for
   Break Cause that means discarding a server-reported answer to keep using a
   heuristic, and for TTL it means keeping `TTL_GAP_S` when one source records
   the real value.

2. **When both a source-provided and a computed value exist, which wins?**
   Concretely: Break Cause, Re-billed Tokens (median ratio computed/server 1.169,
   diverging 6–14x at compaction), and cache TTL. Note the two Break Cause signals
   do not subsume each other — 92 arithmetic breaks carry no server reason and 72
   server reasons carry no arithmetic break — so "prefer the server" is not the
   whole rule.

3. **What happens to `explain_breaks()` as a test seam** if Break Cause becomes
   source-provided for some sources and inferred for others?

Whatever is decided becomes vocabulary in `CONTEXT.md` before it appears in code.
This is the decision that most affects `docs/tickets/005`.
