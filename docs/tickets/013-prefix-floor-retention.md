# 013 — Retention is measured against zero, but the prefix never falls to zero

**Status:** open · **Priority:** 1 (a shipped mis-classification, and it closes
`010`'s residual without needing `010`'s blocked half)

## Context

`analyze()` computes Retention as `cached / expected_cache`, and
`COLD_RETENTION = 0.25` calls a Break "cold" below 25%. That assumes a total
cache expiry drives `cached` toward zero.

It does not. Every prompt re-sends an identical head — system header, tool
definitions, instructions — which the provider re-caches immediately. So a Break
that kept **nothing of the conversation** still reports a Retention of
`floor / expected`, and on a short Session that is a large number.

`001` already noticed the symptom without naming the cause: the easycall req-16
pattern, "surviving prefix ≈ the session's static header exactly".

## Evidence

Measured 2026-08-28. **Both sources have it.**

Claude Code (`.scratch/agent-source-capability` ticket 09, 130 graded Breaks):
`cached` clusters at ~21k on **94 of 130** Breaks, and equals the Session's own
first-Request `cache_read` within ±10% on **88 of 120**. **9 confirmed expiries**
— server-labelled `previous_message_not_found` at gaps of 1h 52m to 4.4 days —
are misclassified because their Retention lands at 0.26–0.54, just above the cut.

Codex (this corpus, 478 Breaks): median `cached` / floor ratio is **1.00**, and
**258 of 478 (54%)** sit within 10% of the floor.

**And it explains `010`'s leftovers exactly.** The four `current_date`-only Breaks
that `010`'s reorder could not reach, with Retention recomputed above the floor:

| Idle Gap | Retention today | above the floor | Re-billed |
|---:|---:|---:|---:|
| 44.8h | 50% | **0%** | 21,423 |
| 44.8h | 36% | **0%** | 37,754 |
| 7.4h | 27% | **0%** | 56,155 |
| 81.2h | 26% | **0%** | 14,169 |

All four kept **nothing** above the static header, and all four would correctly
read *TTL expiry*. `010` attributed them to *the date is different* and could not
fix it, because fixing it looked like it needed `010`'s change 2 — the
prefix-bearing allow-list, still blocked on Codex's prompt-assembly source. **It
does not. This ticket closes them without that evidence.**

## Vocabulary (add to `CONTEXT.md` before the code)

**Prefix Floor** — the head of the prompt that is re-sent identically on every
Request and so re-caches immediately after any Cache Break: system header, tool
definitions, instructions. It is not conversation, so it must not count as
surviving conversation. **Retention** is redefined as the share of the
*recoverable* prefix that survived, measured above the Prefix Floor.

## Scope

- Derive the Prefix Floor per Session and subtract it from both sides:
  `retention = (cached − floor) / (expected − floor)`, clamped at 0.
- **Decide how the floor is derived and write down why.** Candidates: the
  Session's first-Request `cached`; the minimum non-zero `cached` across the
  Session; the modal value. The first is the most defensible (it is literally the
  cold-start prefix) but is 0 on Sessions that begin cold — the fallback needs
  stating, not improvising.
- **Re-tune `COLD_RETENTION` after the change, or justify keeping 0.25.** The
  constant was chosen against unadjusted Retention; its meaning changes here.
- Re-run the census and correct anything that moves in `001`, `010`,
  `CONTEXT.md` or `README.md`.

## Acceptance

- The four Breaks in the table above read *TTL expiry*, and `010`'s Decisions
  gains a line saying which ticket closed its residual.
- No Break that legitimately kept conversation prefix is newly called cold —
  check the count of `mid-turn history change` does not collapse.
- Tests at the agreed `explain_breaks()` seam: a synthetic rollout whose Break
  retains exactly the Prefix Floor reads as *TTL expiry*, and one that retains
  the floor plus half the conversation does not.
- Corrected corpus figures recorded in Decisions.

## Note on a number not to trust

Ticket 09 measured that floor-adjusting lifts Claude Code agreement from 70.8% to
**74.6%** — but that was fitted on the same data that motivated it. Treat it as a
lead, not as an acceptance target.
