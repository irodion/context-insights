# 01 — Codex: can quota consumption be attributed to a Session?

Type: research
Status: resolved
Blocked by: —

## Question

Codex records a `rate_limits` block on every `token_count` event: `plan_type`,
`credits`, and two windows (`primary`, 300 min; `secondary`, 10080 min) each with
`used_percent` and `resets_at`. That is a directly observed cost signal needing no
pricing table. Can it be attributed soundly enough to report?

Two obstacles were observed on 2026-08-28 and must be settled, not assumed:

- `used_percent` looks integer-quantized — 1% resolution, so a short Session may
  show no movement at all.
- The windows are **account-global**. Two concurrent rollouts that morning
  (10:45:05 and 10:45:48) yielded 433k and 798k cumulative input tokens per 1% of
  the weekly window — a 2x spread that is contamination, not a rate.

Establish across the whole corpus: does every Session carry `rate_limits`; has the
shape changed over time; does `plan_type` ever vary; is any resolution finer than
1% available anywhere; and can concurrent Sessions be detected from timestamps
well enough to exclude them.

Deliver a verdict on what can be honestly reported at **Session** granularity and
at **Cache Break** granularity — they may differ, and "not at break granularity"
is a useful answer.

## Answer

Resolved 2026-08-28. Corpus: 414 rollouts, 2026-03-20 → 2026-08-28, 11,150
`token_count` events, 411 Sessions / 9,376 Requests via the repo's own parser.
Aligned to the parser's Requests with 0 mismatches across all 400 multi-Request
Sessions.

**1. Coverage — effectively total, not date-dependent.** 11,130/11,150 events
(99.82%) carry `rate_limits`; the key is never absent, the 20 exceptions are an
explicit `null`. 397/400 Sessions fully covered, 0 with no coverage. The block is
present in the first file of the corpus, so its introduction predates it.

**2. Shape changed four times — and once *semantically*, which the key-sets hide.**
`primary` is not a stable referent:

| Era | Range | `primary.window_minutes` | `secondary` | Requests |
|---|---|---|---|---|
| A | 2026-03-20 → 2026-07-11 | 300 (5h) | window, 10080 | 4,416 |
| B | 2026-07-13 → 2026-08-22 | **10080 (weekly)** | **null** | 4,940 |
| C | 2026-08-26 → present | 300 (5h) | window, 10080 | 326 |

In era B the 5-hour window does not exist and the weekly figure occupies the
`primary` slot. **Server-side, not a client upgrade** — CLI `0.148.0-alpha.9`
emitted era-B shape on 08-21 and era-C shape on 08-26. Reading `primary`
positionally silently compares a 5-hour reading against a weekly one.

**3. `plan_type` never varies usefully** — `"plus"` ×11,016, `null` ×114 (all one
session, the corpus's first). Caveat: one account, one plan, six months —
invariance is untested, not established.

**4. Integer-quantized, and nothing finer exists.** All 16,405 `used_percent`
samples are integral, confirmed by raw-text grep (zero non-`.0` decimals). Every
finer candidate is dead: `credits.balance` never moves; `individual_limit`,
`spend_control_reached`, `rate_limit_reached_type` are null in 11,130/11,130;
`resets_at` moves ±1s (clock jitter) on 697 of its 740 changes. At the median
~870k input tokens per percentage point, the median Request buys 0.077pp — so the
weekly counter is **flat on 90.1% of consecutive Request pairs**, and 43.7% of
Sessions end on the exact `used_percent` they started with.

**5. Concurrency is pervasive — and the ticket's own example was misdiagnosed.**
33.3% of Sessions have a foreign Request inside their window; 36.9% of active
wall-clock has ≥2 Sessions open; peak concurrency 6. **The 433k-vs-798k spread
that motivated this ticket was subagent fan-out, not two users** — 10:45:48 is a
`subagent` of the 10:45:05 `user` Session, along with three more.

Two harder findings:

- **The logs are not a closed ledger.** In 16 of 370 idle gaps ≥10 min, weekly
  `used_percent` rose by ≥1pp more than the bounding Request could account for —
  including **+2pp across a 45.6h gap**. Either the account was used elsewhere or
  server accounting lags; one client's logs cannot distinguish them, and either
  defeats "delta over my window = my spend".
- **Quota per token is not constant.** 306,756 → 2,280,398 tokens/pp (7.4x) across
  clean Sessions; it tracks the model (`gpt-5.5` 680k, `gpt-5.6-sol` 1.02M,
  `gpt-5.4` 1.53M) and the era. Quota is not a linear function of input tokens.

**6. VERDICT.**

*(a) Session granularity — a coarse, caveated **observation**, never an attribution.*
Over the 387 Sessions whose weekly window contains no reset:

| End-to-end delta | Quantization error | Sessions | of which clean-window |
|---|---|---|---|
| 0pp (no signal) | — | **169 (43.7%)** | — |
| ≥1pp | ±100% | 218 | 97 |
| ≥4pp | ±25% | 45 | **3 (0.8%)** |
| ≥10pp | ±10% | 13 | **0** |

Not one Session in six months is simultaneously uncontaminated and quantized
finely enough for a ±10% claim. 51% of Sessions cannot in principle move the
counter by a resolvable amount. The honest form, for the 246 clean `user`
Sessions only: *"while this Session ran, N pp of your weekly allowance was
consumed"* — with an explicit ±1pp and an open-account caveat. It must not be
divided, ranked, or converted to a rate.

*(b) Cache Break granularity — **flat no**, a physical bound.* Median Re-billed on
a Break is 31,798 tokens = 0.037pp; the **largest Break in the corpus** is
0.250pp. **Zero of 478 Breaks can move a 1pp counter**, so no refinement helps —
the signal is quantized ~4x coarser than the largest possible event. The 120
Breaks that coincide with a tick are boundary-crossing coincidence, not
attribution.

**Matrix row: Codex cost/quota = DEGRADED — Session-level coarse band only, ±1pp,
open-account caveat; NOT VIABLE at Break granularity.** Independent of the
cache-forensics axis, which the corpus supports well.
