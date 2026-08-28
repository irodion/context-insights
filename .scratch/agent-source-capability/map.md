# Map — Can the Codex cost/cache pattern generalize across Agent Sources?

Label: `wayfinder:map`

## Destination

A decided, evidence-backed matrix: for each Agent Source — Codex, Claude Code,
Cursor, Copilot — what cache forensics and what cost/quota reporting Context
Insights can honestly deliver. Every source ends with a verdict on both axes:
**full**, **degraded and how**, or **not viable**. The matrix decides which
adapters are worth building and what each one promises; it does not build them.

## Notes

- Domain: CLI-agent session logs and prompt-cache economics. `CONTEXT.md` is the
  ubiquitous language — a new concept goes there before it appears in code.
- `CLAUDE.md` governs: personal tool, stdlib only, no abstraction bought on
  credit. A verdict of "not viable" is a good outcome, not a failure.
- **Evidence rule**, inherited from `docs/tickets/010`: a claim about what a log
  contains must come from reading real logs, not from vendor documentation.
  Where only docs are available, say so and mark that cell unverified.
- **Self-contamination is a live hazard.** This effort reads agent transcripts
  while writing about agent transcripts. A grep for `plan_type` across Claude
  Code transcripts on 2026-08-28 returned only this repo's own session echoing
  Codex payloads. Exclude this repo's sessions when searching for field names.

## Decisions so far

<!-- one line per resolved ticket: gist + link -->

- [01 — Codex: can quota consumption be attributed to a Session?](issues/01-codex-quota-attribution.md)
  — **No at Cache Break granularity, and only a coarse band at Session
  granularity.** Zero of 478 Breaks can move the 1pp-quantized counter; the
  largest Break in six months is 0.250pp. 43.7% of Sessions end on the
  `used_percent` they started with, and not one clean-window Session supports a
  ±10% claim. The logs are also not a closed ledger — usage rose off-log in 16
  measured gaps. Codex cost/quota = **degraded**, Session-level only.

## Not yet specified

- Whether Claude Code's **recorded** cache TTL should replace the `TTL_GAP_S`
  heuristic where a source provides it, and what that does to Break Cause
  attribution. Sharpens once 02 and 06 land.
- Whether `docs/tickets/005` changes shape if Claude Code turns out to be the
  better *reference* source rather than the third adapter.
- What a dollar figure means for a user actually on API billing, and whether a
  pricing table earns its maintenance for them. Parked alongside `009`.
- Whether any source other than Codex can support Watch Mode. Cursor's
  pull-from-cloud fallback could not; a hooks-based Cursor path might.
- Whether a **common cost unit** exists across sources at all. 01 found Codex's
  quota is model-weighted and unpublished (680k–1.53M input tokens per
  percentage point across three models), so even within one source the unit is
  not linear in tokens. Sharpens once 02 and 04 report what their sources
  expose; may become an extra axis on the matrix rather than a ticket.
- Whether off-log consumption and server accounting lag can be told apart. 01
  measured 16 instances but one client's logs cannot distinguish them; settling
  it needs a deliberate quiet-interval experiment. Contingent — only worth
  charting if any quota reporting survives 07.

## Out of scope

- **Building any adapter.** This map decides which are worth building;
  `docs/tickets/003` and `005` do the building.
- **Rewriting `docs/tickets/009`.** Parked by decision at chart time: it resumes
  once the matrix can give it a cross-source answer instead of a Codex-only one.
- **Any change to `parse_codex.py`.** This map produces a decision, not code.
- **Rolling a Session and its subagents up as one attributable unit.** Surfaced
  by [01](issues/01-codex-quota-attribution.md): subagent fan-out is the dominant
  concurrency source for a single user (109 of 411 Sessions), and a Session-tree
  rollup would lift clean `user` coverage from 82.0% to 87.7%. It touches
  `Thread Source` and how Re-billed Tokens are aggregated — a build decision for
  `docs/tickets`, not a question about source capability, so it sits past this
  map's destination. Worth a repo ticket regardless of the quota verdict.
