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

The minimum under-states the floor rather than over-stating it *within the values
the Session actually shows*, which is the same error preference `010` wrote down
for its allow-list. The modal value is worst of the three: floor > cached on 98
Breaks, floor ≥ Expected Cache on 34.

**Corrected: "can never over-state it" was false. The floor now needs corroboration,
and only cache rebuilds may supply it.** The minimum Cached Input is the re-cached
head only if the cache ever came back head-only. On a Session where it never does —
`60k/0 → 80k/60k → 90k/40k` through the adapter — the smallest value is simply the
deepest Cache Break, and subtracting it forces *that Break's own* Retention to zero
by construction: 50% becomes 0%, and a partial Break behind it is then misread as
*cache warm-up* because `ran_cold()` sees a fabricated cold Request. **36 Breaks in
the corpus were defining their own floor alone.**

Two conditions fix it, and both were needed:

1. **Corroboration, and only for the smallest rebuild.** The floor is the smallest
   candidate, used only when a *second* rebuild lands within `FLOOR_CORROBORATION`
   (10%) of it; otherwise it is zero and Retention stays unadjusted.

   An intermediate version climbed past an uncorroborated smallest value to the next
   pair, to rescue a Session whose deepest Break came back *under* the head — the
   easycall shape in `001`, a lone 5,504 beneath a 9,600 head seen twice. **That was
   wrong, and the shape that refutes it is indistinguishable from easycall's:**
   `30k/20k → 80k/30k → 90k/50k → 100k/52k` opens on a 20k head that nothing ever
   returns to, and the climb pairs the two partial Breaks at 50k and 52k into a
   fabricated 50k floor — reading two warm Breaks as *unknown* and *cache warm-up*.
   A Cache Break can be a partial divergence; two Breaks near each other agree on
   nothing. Since no rule on these values can separate the two shapes, the tie goes
   to the stated error preference: under-stating the floor leaves Retention
   over-reported, over-stating it invents coldness. **Not climbing costs easycall its
   floor and changes none of its Break Causes** — and on the corpus it is strictly
   better, moving 18 Breaks out of *unknown* and *cache warm-up* back into
   *mid-turn history change*.

   The same reasoning reaches a cold start. A Request with Cached Input of **zero**
   is a rebuild that returned nothing, and it is the smallest rebuild a Session can
   have; filtering it out before choosing the smallest lets two partial Breaks above
   it become the bottom. `60k/0 → 80k/60k → 90k/40k → 95k/41k` did exactly that —
   the zero was dropped, 40k and 41k paired, and two warm Breaks read *unknown* and
   *cache warm-up*. 17 of 401 Sessions have a zero rebuild and 10 of them lose a
   floor by counting it, which is again the safe direction and again strictly better
   on the corpus: *unknown* falls by 8 Breaks and *mid-turn history change* gains 9.

   Nor can two Cache Breaks corroborate each other, which is the same defect a
   fourth time. A Break's Cached Input is whatever survived a divergence — any
   fraction of the prefix — so two Breaks agreeing say they diverged at similar
   points, not that either came back on the head. On a Session that opened warm
   there is nothing beneath them to out-rank the pair: `70k/60k → 80k/70k →
   90k/40k → 95k/41k` set a 40k floor from two Breaks that each kept half. **The
   agreeing group must contain a non-Break rebuild** — the first Request, whose
   prompt is the head plus one message, or a Compaction, which rebuilds the prompt
   deliberately rather than losing it. Over the corpus that corroborator is the
   first Request on 123 Sessions and a Compaction on 4. A Compaction's Cached Input
   can still carry summary text, so the floor is an estimate rather than a reading;
   taking the smallest agreeing value bounds the error.

2. **Only rebuilds are candidates** — the first Request, Cache Breaks, Compactions.
   A Hit's Cached Input is the whole previous prompt, so it bounds the head from
   *above* rather than locating it, and corroborating with Hits can only over-state.
   Under the no-climb rule this changes no Break Cause on the corpus (a floor on 192
   Sessions instead of 141, identical classifications); it is kept for the direction
   of the error, not for a count. The earlier 1.24x / 45% figures for admitting Hits
   were measured under the climbing rule and no longer apply.

Compactions are candidates because a Compaction *is* a cache rebuild, deliberate
rather than accidental. Excluding them costs 3 of the 20 `current_date`-only
Breaks, each of which has a Compaction sitting on the head at 21,248–23,296.

274 of 401 Sessions have no corroborated floor and report the un-floored ratio —
the honest reading, since nothing in those logs shows a head-only return. The 10%
tolerance is not a fresh constant: it is the one this ticket's Evidence measured
the floor with.

The fallback Scope asked to have stated: the floor is 0 whenever nothing
corroborates one, which restores exactly today's unadjusted ratio. Prefix Floor
across the 127 Sessions that have one: median 11,008 tokens, range 2,432–24,320.

**`COLD_RETENTION` stays 0.25, re-read rather than inherited.** The adjusted
distribution is sharply bimodal: 284 of 478 Breaks retain *exactly nothing* above
the floor, and the rest bulge between 0.3 and 0.7. Between them is a density
trough spanning roughly 0.20–0.40. 0.25 sits inside it, so the constant survives
on the new measure for a new reason. It was not tuned to a bucket count — the
sweep below shows tuning cannot buy what the acceptance asked for anyway.

**Corrected census** (401 Sessions, 481 Cache Breaks, 26.28M Re-billed, subagents
included — nominally `010`'s basis, over a corpus that is live and has grown by a
Session and six Breaks while this ticket was being worked):

| Break Cause | breaks | re-billed | share | was |
|---|---:|---:|---:|---:|
| TTL expiry | 167 | 17.13M | 65.2% | 64.3% |
| unknown | 145 | 3.90M | 14.8% | 8.1% |
| turn-boundary history rewrite | 50 | 2.30M | 8.8% | 9.6% |
| mid-turn history change | 71 | 1.27M | 4.8% | 11.8% |
| cache warm-up | 26 | 0.99M | 3.8% | 2.9% |
| turn_context change | 22 | 0.69M | 2.6% | 3.3% |

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

(Swept before the corroboration requirement, which moves the 0.25 column to 71.
The shape of the argument is unchanged: no threshold reaches 195.)

The floor is why, not the threshold. **Of the 125 Breaks that left, 97 retain
literally nothing above a corroborated floor** — no threshold above zero can call
them warm, and two independent rebuilds agreed on where that floor is. Those were
mis-labelled *diverged part-way through* when they were cold, which is the defect
this ticket names. The remaining 28 are the genuine judgment call: they kept a
median of 6,400 tokens (max 23,040) above the floor, below the trough, and are now
called cold. **What the criterion was actually
guarding is met** — no Break that kept real conversation is newly cold, and the
`explain_breaks()` guards below pin that.

**The cost is a large *unknown* bucket: 37 → 145 Breaks, 8.1% → 14.8% of
Re-billed.** That is honest rather than good — the log genuinely does not account
for them, and `CONTEXT.md` already says to prefer saying so over inventing a
cause. `015` is where the mass goes next: it identifies 0 of 19 tool-set changes
today, and those land in exactly this bucket. `001`'s 82% / 18% mid-Turn split
inverts to 29% *mid-turn history change* / 60% *unknown* / 10% *cache warm-up*
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
