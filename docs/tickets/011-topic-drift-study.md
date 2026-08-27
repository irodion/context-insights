# 011 — Does Topic Drift predict anything? (a measurement, not a feature)

**Status:** open · **Priority:** 3 (speculative; may close as "not adopted")

## Context

Proposed 2026-08-26: measure how far each Request drifts in subject matter from
the one before, and when a large Cache Break appears, report the drift as the
root cause — *this break is you switching topic*.

**That framing does not survive contact with the mechanism.** Prompt caching is
prefix-mechanical: a cache is invalidated when the literal token prefix changes.
Switching topic *appends* tokens; it does not touch the prefix. And after 010
there is no unexplained mass for it to claim — every one of the 25.8M Re-billed
Tokens in the corpus is already attributed to a mechanical cause, ~64% of it to
idle expiry and resume. Topic Drift cannot be a Break Cause and this ticket does
not add one.

What is left is a weaker but honest claim, and it is worth exactly one session
to find out whether it holds.

## Goal

Answer one question with a number: **does Topic Drift predict the behaviors that
do break caches** — Compaction, a Cache Break, abandoning the Session — *after
controlling for elapsed time*?

Idle Gap is deliberately absent from that list. It is a control, and the same
quantity cannot serve as both the thing held fixed and the thing predicted.

Resolve the ticket either way. A null result is a real result and closes it.

## The confound that decides the ticket

Drift will correlate with breaks even if it is causally inert, because both
correlate with time. A raw correlation is therefore worthless. There are **two**
distinct time confounds, and Idle Gap only handles one of them:

- **Idle Gap** — the longer the pause, the likelier the prefix expired, and
  pauses also tend to fall where the subject moves.
- **Session Age** — drift accumulates monotonically as a Session grows, and so
  does Compaction risk, because Compaction is triggered by context *size*. Over
  a long enough Session both approach certainty regardless of any relationship
  between them. For the Compaction outcome this is the *stronger* confound, and
  stratifying by Idle Gap alone leaves it entirely uncontrolled.

**Pre-registered controls: both.** Cells are Idle Gap band × Session Age band,
and drift is compared only *within* a cell. Session Age is measured as cumulative
input tokens at that Turn — the quantity that actually drives Compaction — with
Turn index reported alongside as a cross-check that the two agree.

If drift stops separating the buckets once both are held fixed, it is a proxy for
elapsed time and the ticket closes.

**Two-way stratification may leave the study underpowered**, and that is an
allowed outcome. If no cell meets the minimum observations below, the answer is
"this corpus cannot settle it" — recorded as such, with the cell counts. That is
a null result, not a licence to drop a control and re-run.

## Method

Stdlib only — no embedding model, no dependency. For this corpus a lexical
signal is likely *better* than prose similarity anyway: what the Session is
about is the set of files it is touching, not the phrasing of the prose.

- **Topic signal** for a Turn: the set of workspace-relative file paths and
  identifiers appearing in that Turn's `user_message` and `function_call`
  arguments. Regex extraction; no parsing of tool semantics.
- **Topic Drift** between consecutive Turns: `1 − Jaccard(signal_n, signal_n-1)`.
  Turns with an empty signal on either side are excluded, not scored zero.
- **Outcome** per Turn, over a fixed observation window **W = 24h** of wall-clock
  after that Turn's last Request. One of:
  - *break* — a Cache Break or Compaction on the next Turn of the Session;
  - *clean* — a next Turn arrives within W with neither;
  - *abandoned* — no further Turn in the Session within W, **and** the corpus was
    captured at least W after that Turn. Abandonment is an outcome, not a gap in
    the data: it is one of the three behaviors the Goal names.
  - *censored* — the Session's last Turn falls within W of capture time, so
    abandonment cannot yet be distinguished from an ongoing Session. The Live
    Session is always censored. Censored Turns are excluded from rate
    denominators and their count is reported, so the exclusion is visible rather
    than silent.

  Without this, every Session's final Turn — the only place abandonment is
  observable — would drop out of the study, and the Method would not answer the
  Goal it states.

- **Drift buckets, pre-registered**: fixed boundaries on `[0, 1]`, chosen before
  looking because drift is a bounded metric and data-derived quantiles would let
  the boundaries be tuned to the result: `[0, 0.25)`, `[0.25, 0.5)`,
  `[0.5, 0.75)`, `[0.75, 1.0]`. The comparison is always top bucket vs bottom
  bucket; the middle two are reported for monotonicity, which is weak evidence
  either way and never decides adoption.

- **Analysis**: within each Idle Gap band × Session Age band cell, compute the
  outcome rate per drift bucket. Ladder shape follows `idle_gap_advice()`, whose
  derive-the-threshold-from-the-corpus discipline this ticket keeps.

## Deliberately out of scope

- Any change to `parse_codex.py`. This is a throwaway script run against the
  corpus; only a positive result earns code, in a follow-up ticket.
- Embeddings and any third-party dependency. If the measurement says drift
  matters *and* the lexical signal is visibly too crude to act on, that is the
  ticket that gets to argue for a dependency — with this study as its evidence.
- Reporting drift as a Break Cause. See Context.

## Pre-registered decision rule

Set before looking, so the result cannot be talked into significance.

**A cell qualifies** when both compared drift buckets — top and bottom — hold
**≥20 non-censored Turns each**. The threshold is per compared bucket, not per
cell: a cell of 40 Turns split 38/2 settles nothing, and would otherwise sneak in
under a cell-level minimum.

**Lift** is computed with a Haldane–Anscombe correction —
`((a + 0.5) / (n_top + 1)) ÷ ((b + 0.5) / (n_bottom + 1))` — so a bottom bucket
with zero events yields a finite number instead of a division by zero or an
automatic "adopt". Additionally the top bucket must hold **≥5 outcome events in
absolute terms**: 2-of-20 against 0-of-20 is noise wearing a large ratio.

**The decision statistic is the pooled lift across all qualifying cells**
(Mantel–Haenszel), not the best cell. Per-cell lifts are reported for inspection,
but no single cell can trigger adoption — "≥1.5× in at least one band" is
multiple comparisons by another name, and testing enough bands guarantees a
winner. That would be precisely the significance-shopping this ticket exists to
prevent.

- **Adopt** if the pooled lift is **≥1.5×** across qualifying cells.
- **Close as not adopted** if it is below that, recording the observed pooled and
  per-cell lifts in Decisions so the question is not reopened from scratch.
- **Close as underpowered** if no cell qualifies, recording the cell counts.
  Dropping a control to manufacture a qualifying cell is not an option.

## If adopted — the shape the feature would take

Prescription, not diagnosis. Not *"this break was a topic switch"* but
*"from Turn N you were carrying ~X tokens of context nothing since has touched;
a fresh Session was cheaper"*. That advice is useful even where no break
occurred, which is the point.

Vocabulary at that point, not before: **Topic Drift** would enter `CONTEXT.md`
only if it enters the code.

## Acceptance

- A drift × (Idle Gap band × Session Age band) table over the corpus in
  Decisions, with per-bucket counts, which cells qualified, and how many Turns
  were censored.
- The pooled lift, the per-cell lifts, and an explicit verdict —
  adopted / not adopted / underpowered — against the rule above.
- If not adopted or underpowered: the ticket closes and no code ships. That is a
  success.

## Decisions

_(fill in with the study)_
