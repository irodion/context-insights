# 09 — Grade `explain_breaks()` against the first ground truth we have ever had

Type: research
Status: claimed
Blocked by: —

## Question

[02](02-claude-code-telemetry.md) found that Claude Code's server reports the
Break Cause (`message.diagnostics.cache_miss_reason`) and the Re-billed figure
(`cache_missed_input_tokens`). [06](06-agent-agnostic-contract.md) then asks
whether analysis should trust the source over our heuristic — but that is a
decision resting on a fact nobody has measured: **on the breaks where both
signals exist, how often does `explain_breaks()` already agree?**

This is the first external check this project has ever had. Every Break Cause
figure in `docs/tickets/001` and `010` — including the corrected census shipped
2026-08-28 — is unvalidated heuristic output. Measure the error rate.

**1. The confusion matrix.** Over Claude Code Sessions, run our arithmetic and
`explain_breaks()` logic and cross-tabulate our six Break Causes against the six
`cache_miss_reason` types, on the Requests where both exist. Report per-cause
agreement, and which of our causes is least reliable.

**2. Is the mapping actually one-to-one?** 02 called it "almost". Settle the
ambiguous cases with evidence rather than assertion: `messages_changed` was
mapped to *history rewrite* **or** *Compaction* — two of ours; `unavailable` was
mapped to *cache warm-up* on plausibility alone. Where a server type spans two of
our causes, say what separates them.

**3. Grade ticket 010's reorder directly.** The reorder made a long Idle Gap with
a cold cache outrank a `turn_context` diff. The server distinguishes exactly
these: `previous_message_not_found` (expiry) versus the four `*_changed` types
(config). **Does the server ever report a `*_changed` where our logic says TTL
expiry, or the reverse?** Each such case is a counter-example to a change already
shipped. Report them individually, not just as a rate.

**4. The non-overlapping populations.** 92 arithmetic breaks carry no server
reason and 72 server reasons carry no arithmetic break. For the second group: are
those Requests we classify as *hits*? If the server says the cache missed and we
say it did not, `BREAK_RATIO = 0.8` may be mis-set — check whether their
Retention clusters near the threshold.

**5. Does the verdict transfer to Codex?** Codex has no ground truth, so its
numbers inherit whatever error rate is measured here. Which of our six causes is
least reliable, and what share of Codex's corrected census (155 TTL expiry / 27
turn_context change / 194 mid-turn history change / 56 rewrite / 35 unknown / 8
warm-up) sits in it? State plainly how much confidence the Codex figures should
carry.

## Why this blocks 06

If the heuristic agrees with the server nearly always, the case for breaking the
agent-agnostic rule is weak — the server signal buys precision at compaction and
little else. If it disagrees often, the rule has been hiding real errors and the
case is strong. **06 cannot be decided honestly without this number.**

A finding that our heuristic is largely right is just as valuable as one that it
is wrong, and must not be argued away.
