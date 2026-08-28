# 013 — Retention is measured against zero, but the prefix never falls to zero

**Status:** done 2026-08-28 · **Priority:** 1 (a shipped mis-classification, and it closes
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


## Decisions

**The Prefix Floor is the smallest non-zero Cached Input in the Session, not the
first.** Scope leaned toward the first Request's `cached` as "the most defensible
— it is literally the cold-start prefix". It is only that when the Session began
cold, and the corpus says they often do not: the first Request's `cached` exceeds
a later Break's own `cached` on **85 of 478 Breaks**, and exceeds that Break's
whole Expected Cache on **9**. Three of the four Breaks this ticket exists to fix
are in that group — their Sessions open at 79,616 / 84,736 / 30,464 cached while
the floor those Sessions actually settle on is 21,248. On those three the
first-Request rule gives a floor larger than the number it is subtracted from, and
only lands on 0% by being clamped.

The minimum is a *lower bound* on the floor. It can under-state the floor, leaving
some of today's inflation in place; it can never over-state it, so it can never
invent coldness on a Break that really did keep conversation. That is the safe
direction, and the same error preference `010` wrote down for its allow-list.
The modal value is worst of the three: floor > cached on 98 Breaks, floor ≥
Expected Cache on 34.

The stated fallback Scope asked for: floor is 0 when the Session never cached
anything, which restores exactly today's unadjusted ratio. **No Session in the
corpus needs it** — all 400 cached something. Prefix Floor across the corpus:
median 11,008 tokens, range 2,432–50,944.

**`COLD_RETENTION` stays 0.25, re-read rather than inherited.** The adjusted
distribution is sharply bimodal: 284 of 478 Breaks retain *exactly nothing* above
the floor, and the rest bulge between 0.3 and 0.7. Between them is a density
trough spanning roughly 0.20–0.40. 0.25 sits inside it, so the constant survives
on the new measure for a new reason. It was not tuned to a bucket count — the
sweep below shows tuning cannot buy what the acceptance asked for anyway.

**Corrected census** (400 Sessions, 478 Cache Breaks, 25.97M Re-billed, subagents
included — the same basis as `010`'s table):

| Break Cause | breaks | re-billed | share | was |
|---|---:|---:|---:|---:|
| TTL expiry | 169 | 17.09M | 65.8% | 64.3% |
| unknown | 163 | 4.15M | 16.0% | 8.1% |
| turn-boundary history rewrite | 47 | 2.22M | 8.5% | 9.6% |
| cache warm-up | 27 | 1.02M | 3.9% | 2.9% |
| mid-turn history change | 51 | 0.88M | 3.4% | 11.8% |
| turn_context change | 21 | 0.61M | 2.4% | 3.3% |

**Acceptance met: all 20 `current_date`-only Breaks read *TTL expiry*.** The four
in the table above land at 0% Retention (they retain the floor exactly, to the
token) and the TTL branch claims them. `010`'s residual is closed and `010`'s
Decisions says so — and says that this does *not* unblock its change 2, because
nothing was learned about whether `current_date` is prefix-bearing.

**Acceptance not met, and it cannot be: *mid-turn history change* does collapse,
195 → 51.** The criterion was written as a guard against over-subtracting the
floor. It does not detect that, and no setting satisfies it:

| `COLD_RETENTION` | 0.25 | 0.20 | 0.15 | 0.10 | 0.05 | 0.01 |
|---|---:|---:|---:|---:|---:|---:|
| mid-turn history change | 51 | 56 | 65 | 71 | 74 | 83 |

The floor is why, not the threshold. **Of the 145 Breaks that left, 111 retain
literally nothing above the floor** — no threshold above zero can call them warm,
and since the floor is a lower bound, "nothing above it" means they kept no
conversation at all. Those were mis-labelled *diverged part-way through* when they
were cold, which is the defect this ticket names. The remaining 34 are the genuine
judgment call: they kept a median of 6,848 tokens (max 23,040) above the floor,
below the trough, and are now called cold. **What the criterion was actually
guarding is met** — no Break that kept real conversation is newly cold, and the
`explain_breaks()` guards below pin that.

**The cost is a large *unknown* bucket: 37 → 163 Breaks, 8.1% → 16.0% of
Re-billed.** That is honest rather than good — the log genuinely does not account
for them, and `CONTEXT.md` already says to prefer saying so over inventing a
cause. `015` is where the mass goes next: it identifies 0 of 19 tool-set changes
today, and those land in exactly this bucket. `001`'s 82% / 18% mid-Turn split
inverts to 21% *mid-turn history change* / 68% *unknown* / 11% *cache warm-up*
over 241 mid-Turn breaks; `001` is corrected in place.

**The lead from map ticket 09 was not used as a target.** The 70.8% → 74.6%
Claude Code agreement figure was fitted on the data that motivated it, and this
ticket shipped without re-measuring against it. Nothing here was tuned to it.

**Tests at the agreed `explain_breaks()` seam, one driving and two guarding.**
The driving test is the corpus shape `010` could not reach: a two-day resume whose
`current_date` moved, retaining exactly the floor. It failed red with
`'turn_context change' != 'TTL expiry'` — the same signature as the four
survivors. The first guard is a mid-Turn Break retaining the floor plus half the
conversation, which must stay *mid-turn history change*. The second guard encodes
the floor-derivation decision as behaviour: a Session resumed warm, whose first
Request already carries conversation, whose later mid-Turn Break keeps half the
recoverable prefix. It was checked against the rejected candidate — swapping the
derivation to the first Request's `cached` fails it with
`['TTL expiry', 'unknown'] != ['TTL expiry', 'mid-turn history change']` — so the
guard discriminates rather than merely passing.

**Two existing fixtures had to be re-expressed, not re-asserted.** `010`'s guard
(a day-long gap plus a sandbox flip, "kept 40% of the prefix") and the mid-Turn
history-change test both set `cached` *equal to* the floor their own fixture
established, so the 40% and 50% they asserted were the static header — the very
thing this ticket says is not conversation. Their intent is unchanged and their
assertions are unchanged; the token counts now put real conversation above the
floor. `010`'s guard docstring said "whose static header survived" in as many
words, which is how they were caught.

**`--explain` names the floor it measures against.** The Prefix Floor rescales
every percentage in that output, so the header line reports it — otherwise a Break
reading "0% of the recoverable prefix kept" cannot be checked without re-deriving
the floor by hand, which is the reading this ticket's own evidence table rests on.

**`README.md` is corrected; the `--explain` sample is real output, not
illustrative.** Retention is now reported as a share "of the recoverable prefix"
wherever it is printed. On easycall, req 16 moves 16% → 10% and req 17 — the TTL
expiry — moves 7% → 0%, which is `001`'s "surviving prefix ≈ the session's static
header exactly" reading as what it always was.
