# 005 — Claude Code adapter (second Agent Source)

**Status:** open · **Priority:** 2 (the highest-value unblocked work; every
open question is now answered with evidence)

## Context

Originally ruled out ("this is not for Claude Code"), scope changed 2026-08-26,
and re-scoped again 2026-08-28 after `.scratch/agent-source-capability`
[ticket 02](../../.scratch/agent-source-capability/issues/02-claude-code-telemetry.md)
measured the format across **563 transcripts, 95,131 records, 78 project
directories, 10 Claude Code versions**.

That research changes this ticket's premise. Claude Code is not the *third*
Agent Source rounding out the set — on the cache-forensics axis it is a **better
reference source than Codex**, and it is the cheapest adapter to build because
everything the existing analysis needs is present at 100% coverage across every
version measured.

Both of this ticket's former open questions are answered below and removed.

## Why it is the low-hanging fruit

`~/.claude/projects/<project-slug>/<session-id>.jsonl`, append-only, read-only,
no hooks — the same shape as the Codex adapter. Every field `analyze()` needs is
present on **100%** of the 41,173 assistant records measured:

| Claude Code | our Request field |
|---|---|
| `message.usage.input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens` | `input` (total prompt) |
| `message.usage.cache_read_input_tokens` | `cached` |
| `message.usage.cache_creation_input_tokens` | cache write |
| `message.usage.output_tokens` | `output` |

Expected Cache and Retention derive exactly as `CONTEXT.md` defines them, so
`analyze()`, `explain_breaks()`, `idle_gap_advice()` and the Waterfall work
**unchanged**. This ticket ships the adapter and nothing else.

## The one thing that must be right: Replayed Request has an analogue

Claude Code writes **one JSONL record per content block**, not per API call.
41,173 assistant records collapse to **20,946 Requests** grouped by `requestId`.

**Group by `requestId` and take the last record of the group** — it carries the
final `output_tokens` in 13,605 of 13,605 multi-record groups, and `message.id`
is 1:1 with `requestId` (0 of 20,864 map to more than one).

Skip this and the corpus reports **1,055 Cache Breaks instead of 155 — a 6.8x
phantom inflation.** This is Claude Code's Replayed Request: same class of
defect, different mechanism, different fix. It belongs in `CONTEXT.md` as
vocabulary before it appears in code.

Also: **82 of 20,864 `requestId`s appear in more than one file** (session forks
and resumes copy history), so cross-Session aggregation needs a global dedupe,
not just a per-file one.

## Scope

- `load_claude_session(path)` → the normalized session dict, `agent_source:
  "claude-code"`. Dedupe by `requestId` within the file. The cross-file dedupe
  above cannot live inside a per-path loader: the caller that walks a corpus
  keeps **one** `requestId` set across every file it loads and drops Requests
  already seen in an earlier Session, so `--source all` counts the 82 shared ids
  once. The normalized output and `agent_source` are unchanged either way.
- **Turns** from `promptId` — present on 98.97% of `user` records and **0%** of
  assistant records; tool-result records carry the originating prompt's id.
  Attribution yields 17,004 Requests placed and 1 orphan. There is also an
  explicit end marker: `system` records with `subtype: "turn_duration"`.
- **Thread Source** from `isSidechain`, present on 100% of records and
  partitioning perfectly with the directory layout (0 mixed files; 59.1% of files
  are sidechains). Every sidechain also carries `agentId`, so parentage is
  recoverable.
- **Compaction** from `system` records with `subtype: "compact_boundary"`,
  carrying `compactMetadata` with `preTokens` / `postTokens` /
  `cumulativeDroppedTokens` / `trigger`. Classify as Compaction, never as a
  Cache Break.
- `--source codex|claude-code|cursor|all` — one enum shared across adapters, so
  ticket 003's `cursor` and this ticket's `claude-code` are values of the same
  flag rather than two separate scopes. Whichever adapter lands first adds its
  value; `all` means every adapter present.
- Treat unknown `usage` keys as **additive**: 10 versions appeared in a ~4-month
  corpus, `output_tokens_details` arriving at 2.1.239. Never require an optional
  key.

## Answers to the questions this ticket used to hold open

- **Compaction** — announced, not inferred. `compact_boundary` +
  `compactMetadata`, verified against the numeric signature (`292,982 → 55,964`
  against `preTokens 293,839 / postTokens 15,474`). Strictly better than Codex,
  where it must be detected by ratio.
- **API-key vs subscription sessions** — no usage-field difference.
  `service_tier` is `"standard"` on 41,075 of 41,173 records and is an API tier,
  not a plan. There is no plan, quota or rate-limit signal anywhere in the
  format, so there is nothing to branch on. (See ticket 009: this source cannot
  report cost at all.)
- **Subagents do not replay.** First-Request `cache_read` median is 20,677 for
  main sessions and **0** for subagent transcripts, so `strip_replay()` has no
  analogue to implement here. Mark them, do not strip them.

## Acceptance

Numbers to reproduce — these are what the research measured over 156 main
sessions / 16,933 deduped Requests, so a correct adapter should land on them:

- **155 Cache Breaks (0.92% of non-first Requests)**, 70 cold and 85 partial —
  *not* 1,055.
- **30,566,765 Re-billed Tokens**, Session-wide **Hit Rate 98.43%**.
- Idle-Gap correlation **0.2% / 2.3% / 3.0% / 88.2%** across <2m / 2–10m /
  10–60m / >1h — the cliff at 1h corroborating the recorded TTL.
- This project's own Claude Code sessions render in the Waterfall with those
  hit rates and breaks.
- Tests at the agreed seam: a synthetic transcript whose Requests span multiple
  content-block records must yield one Request per `requestId`, not one per
  record.

## Out of scope

The server-reported Break Cause, Re-billed figure and cache TTL — ticket `012`.
They require deciding whether analysis may know that a source reported the
answer, which is a vocabulary change this adapter does not need.
