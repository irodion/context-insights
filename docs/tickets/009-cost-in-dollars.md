# 009 — Cost in dollars

**Status:** open · **Priority:** 2 (cheap; multiplies persuasiveness of
everything else)

## Context

Deselected in the first backlog pass, revived 2026-08-26: "21.7M tokens
re-billed" lands differently as "$X wasted". Every headline number (re-billed,
failed-call waste from 007, untrusted share from 008) gains from a $ column.

## Sketch

- Static pricing dict in `parse_codex.py`: model → $/1M for input, cached
  input, output. Cut-corners precision; unknown models fall back to a
  configurable default with a "~" marker.
- Re-billed cost = rebilled × (input rate − cached rate) — the delta actually
  overpaid, not the full input rate.
- Show $ alongside tokens in: summary table, session detail, waterfall header
  and tooltips (`--web` data gains a per-session cost field).
- Subscription caveat printed once: for plan users these are API-equivalent
  costs (what the usage would bill at API rates), not actual charges — same
  framing ccusage uses.

## Acceptance

- Summary prints total and per-session $ waste; easycall 2026-03-20 shows a
  plausible dollar figure for its 4.3M re-billed tokens.
- Pricing table is one obvious dict a human can update in 30 seconds.
