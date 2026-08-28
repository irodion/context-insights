# 014 — Compaction is booked as free, and sometimes it is not

**Status:** open · **Priority:** 2 (the tool under-reports its headline number)

## Context

`analyze()` classifies a Request whose input dropped below
`COMPACTION_RATIO × prev_input` as a Compaction and sets `rebilled = 0`. The
reasoning is sound as far as it goes: a Compaction shrinks the context on
purpose, so the smaller prompt is not a re-billing.

But a Compaction and a Cache Break are not mutually exclusive events, and the
classification is a single label. When a Session is resumed after days and the
first Request both compacts *and* finds an expired prefix, the tokens really were
re-billed — and the tool records zero.

## Evidence

From `.scratch/agent-source-capability`
[ticket 09](../../.scratch/agent-source-capability/issues/09-grade-the-heuristic.md),
graded against Claude Code's server-reported cause:

- **21 Compactions carry a server `cache_miss_reason`.** Twelve are labelled
  `previous_message_not_found` — genuine expiry — on Session resumes after gaps
  of **7 hours to 7.2 days**. Every one is booked at `rebilled = 0`.
- Where the server also reports `cache_missed_input_tokens`, it matches
  **`input − cached`** (ratio 1.08–1.15 on 8 of 9 cases). Our formula,
  `expected − cached`, over-counts by **5.0–13.8x** at these boundaries — which
  is why simply removing the zero and applying the normal formula would replace
  an under-count with a much worse over-count.

So there are two defects, and they pull in opposite directions: the cost is
recorded as zero when it should be positive, and the formula that would replace
it is wrong by an order of magnitude at exactly these Requests.

## Scope

- At a Compaction, Re-billed Tokens is **`input − cached`**, not
  `expected − cached`. The surviving prefix is measured against what was actually
  sent, not against a context that was deliberately discarded.
- Decide whether a Compaction that coincides with an expiry is reported as a
  Compaction, as a Cache Break, or as a Compaction carrying a Re-billed figure.
  `CONTEXT.md` currently implies the classification is exclusive; if it is not,
  the vocabulary says so before the code does.
- Distinguish the two cases in `--explain`: a Compaction that *saved* context
  reads very differently from one that coincided with an expired prefix, and
  today they are indistinguishable.

## Acceptance

- The 12 Claude Code Compactions labelled `previous_message_not_found` carry a
  non-zero Re-billed figure within ~15% of the server's
  `cache_missed_input_tokens`.
- A Compaction with a warm cache still reports Re-billed 0.
- The corpus headline total moves **up**, and by how much is recorded in
  Decisions — this ticket makes the tool report more waste, not less, so the
  change must be stated rather than absorbed.
- Tests at the agreed seam: a synthetic Compaction after a long idle gap, and one
  mid-Session with a warm cache.

## Note

Interacts with `013`. Both concern what the surviving prefix is measured against,
and `013` should land first — its Prefix Floor may change which Requests reach
this branch at all.
