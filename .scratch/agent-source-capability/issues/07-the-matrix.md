# 07 — The matrix: a verdict per Agent Source

Type: grilling
Status: open
Blocked by: 01, 02, 04, 05, 06

## Question

Assemble the destination.

For each Agent Source — Codex, Claude Code, Cursor, Copilot — record a verdict on
both axes, cache forensics and cost/quota, drawn from the resolved research
tickets: **full**, **degraded and how**, or **not viable**. Every cell cites the
ticket that established it, and any cell resting on documentation rather than real
logs is marked unverified.

Carry forward two facts from [01](01-codex-quota-attribution.md) that constrain
any cross-source cost story: Codex's `rate_limits.primary` **changed meaning
twice, server-side** (2026-07-13 and 2026-08-26), so a window must be selected by
`window_minutes` and never by key position; and quota per input token is
model-weighted across a 7.4x range, so quota is not linear in tokens even within
one source. If the matrix needs a **common cost unit** row, this is where that
gets decided or declared impossible.

Then decide from it: which adapters are worth building and in what order; what
each one honestly promises and where it degrades; and what changes in
`docs/tickets/003`, `005` and `009` as a result — including whether Copilot earns
a ticket at all.
