# 01 — Codex: can quota consumption be attributed to a Session?

Type: research
Status: claimed
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
