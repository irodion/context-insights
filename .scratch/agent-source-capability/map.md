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
  Two instances measured since, both of which would have produced a wrong answer:
  (a) across the *clean* Claude Code corpus, substring search finds `quota` on 186
  lines and `rate_limit` on 111 — **all string content, zero structural keys**, so
  match parsed JSON keys, never text; (b) VS Code ships
  `extensions/copilot/dist/cli.js`, which is **Claude Code, not Copilot** — 137
  references to `@anthropic-ai/claude-code`, zero to `@github/copilot`. A path
  named for a vendor is not evidence of that vendor.

## Decisions so far

<!-- one line per resolved ticket: gist + link -->

- [01 — Codex: can quota consumption be attributed to a Session?](issues/01-codex-quota-attribution.md)
  — **No at Cache Break granularity, and only a coarse band at Session
  granularity.** Zero of 478 Breaks can move the 1pp-quantized counter; the
  largest Break in six months is 0.250pp. 43.7% of Sessions end on the
  `used_percent` they started with, and not one clean-window Session supports a
  ±10% claim. The logs are also not a closed ledger — usage rose off-log in 16
  measured gaps. Codex cost/quota = **degraded**, Session-level only.
- [02 — Claude Code: what cache and cost telemetry do transcripts carry?](issues/02-claude-code-telemetry.md)
  — **Cache forensics FULL and better than Codex; cost/quota NOT VIABLE.** The
  server reports the Break Cause directly (`diagnostics.cache_miss_reason`, six
  types mapping almost 1:1 onto ours) and the Re-billed figure with it; TTL is
  recorded, Compaction is labelled, subagents do not replay. Quota refuted
  structurally across 563 files / 95,131 records. One trap: dedupe by
  `requestId` or phantom breaks inflate 6.8x.
- [05 — Copilot: is there any local session telemetry at all?](issues/05-copilot-telemetry.md)
  — **Session log NOT VIABLE (schema-confirmed: per-request usage is ephemeral
  by design); SQLite ledger plausibly viable but UNVERIFIED.** VS Code Copilot
  Chat measures the cached split and ships 100% of it to Microsoft telemetry,
  keeping none on disk. [08](issues/08-verify-copilot-ledger.md) closes the cell.
- [09 — Grade `explain_breaks()` against the first ground truth we have ever had](issues/09-grade-the-heuristic.md)
  — **70.8% agreement by count, 81.6% by Re-billed Tokens: right about how much,
  wrong about why.** TTL expiry 94.7% correct and carrying 85.1% of re-billed;
  `mid-turn history change` 0/11 and `unknown` 0/12. Break *detection* has zero
  false positives and `BREAK_RATIO` is vindicated. Ticket 010's reorder measured
  **+5.4pp** against the order it replaced. Three shipped defects surfaced —
  see Out of scope.

## Not yet specified

<!-- 09 was a hole found by the user 2026-08-28: 06 asks whether to trust the
     server over the heuristic, but nobody had measured how often they disagree.
     Ground truth existed and went unused. Worth remembering as a charting
     failure mode: a decision ticket whose premise is an unmeasured fact. -->

- What a dollar figure means for a user actually on API billing, and whether a
  pricing table earns its maintenance for them. Parked alongside `009`.
- Whether any source other than Codex can support Watch Mode. **Claude Code:
  yes** — append-only JSONL on a stable path, one file per Session, with
  `isSidechain` marking subagents, so CONTEXT.md's Live Session rule ports
  directly ([02](issues/02-claude-code-telemetry.md)). Cursor's pull-from-cloud
  fallback could not; a hooks-based Cursor path might. Copilot unknown. Becomes a
  matrix row rather than a ticket once 04 reports.
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
  `docs/tickets/003` and `005` do the building. Acted on 2026-08-28:
  [02](issues/02-claude-code-telemetry.md) resolved the open fog about whether
  `005` changes shape — it does. `005` was rewritten around the measured format
  and is now the highest-value unblocked repo ticket, and the part of it that
  needs [06](issues/06-agent-agnostic-contract.md) was split out as
  `docs/tickets/012` rather than left to pre-empt that decision.
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
- **Three defects in shipped behaviour, found by [09](issues/09-grade-the-heuristic.md)**
  and ticketed in `docs/tickets` on 2026-08-28. None is a question about source
  capability, so all three sit past this map's destination.
  - `013` — **Prefix Floor.** Retention is measured against zero, but a total
    expiry retains the re-sent head. Confirmed on both sources: Codex's median
    `cached`/floor ratio is 1.00 and 54% of Breaks sit within 10% of it. It also
    **closes `010`'s four residual Breaks** — all four have 0% Retention above
    the floor — without `010`'s blocked change 2.
  - `014` — **Compaction booked as free.** 12 confirmed expiries at
    `rebilled = 0`; and the formula that would replace the zero over-counts
    5–14x, so both halves need fixing together.
  - `015` — **Tool-set change as a Break Cause.** Reachable from the log alone,
    so it is not blocked on [06](issues/06-agent-agnostic-contract.md) — and it
    is evidence *for* keeping the agent-agnostic rule.
- **Claude Code's `requestId` dedupe rule as vocabulary.** Surfaced by
  [02](issues/02-claude-code-telemetry.md): it is the analogue of Replayed
  Request with a different mechanism and a different fix, and getting it wrong
  inflates breaks 6.8x. It belongs in `CONTEXT.md` before the adapter is
  written — but that is `docs/tickets/005`'s job, not this map's.
