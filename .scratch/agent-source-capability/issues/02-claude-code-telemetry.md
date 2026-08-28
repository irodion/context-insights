# 02 — Claude Code: what cache and cost telemetry do transcripts carry?

Type: research
Status: resolved
Blocked by: —

## Question

Claude Code writes JSONL transcripts under `~/.claude/projects/<slug>/<session>.jsonl`.
Sampling on 2026-08-28 showed a per-assistant-message `usage` object with
`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
`output_tokens`, `service_tier`, `requestId`, and `cache_creation` split into
`ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens` — meaning the cache TTL
is **recorded** rather than inferred as `parse_codex.py` must do.

A search for plan/quota/rate-limit data found only this session's own transcript
echoing Codex payloads back into the log. The working conclusion is that no quota
telemetry exists; confirm or refute it properly.

Establish: the full `usage` shape and whether it is stable across the `version`
field; whether Requests and Turns are separable; whether subagent sessions are
distinguishable (`isSidechain`); whether compaction is observable; and definitively
whether any plan, quota or cost signal exists anywhere in the file.

**Contamination guard:** exclude session `4a6c6158-95a0-4ee9-8cda-bdb2a011ea22`
and any transcript whose text contains this repo's own analysis output. A field
name appearing only inside a tool result is not that field existing.

## Answer

Resolved 2026-08-28. Corpus: **563 transcripts, 95,131 records, 78 project
directories, 0 unparseable lines**, across 10 Claude Code `version` values.

**The contamination guard worked, and it mattered.** Matching was structural
only — every line `json.loads()`-ed, only parsed dict keys matched, every hit
recorded with its dotted path. Inside the excluded guard session, naive substring
search hits `turn_context` ×162, `plan_type` ×34, `rate_limit` ×42 — and **zero
structural keys**. The trap is not confined to that session: across the *clean*
corpus, substring search finds `quota` on 186 lines in 69 files and `rate_limit`
on 111 lines in 42 files, again **all string content, zero structural keys**. A
grep-based answer to Q6 would have been wrong in either direction.

**1. `usage` shape — stable and version-independent.** 41,173 assistant records,
100% carry `message.usage`. `input_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`, `output_tokens`, `service_tier`, `cache_creation`
are all at 100% across all 10 versions. Only `output_tokens_details.thinking_tokens`
is version-linked (2.1.239+). Everything the analysis needs is universally present.

**2. TTL is genuinely recorded, and effectively single-valued.** `cache_creation`
splits 1h/5m on 100% of records; **both non-zero: 0**. Deduped to real Requests:
**1h 99.82%, 5m 0.01%**. Corroboration that it is real rather than decorative —
the Cache Break rate by Idle Gap is 0.2% (<2m) / 2.3% (2–10m) / 3.0% (10–60m) /
**88.2% (>1h)**: the cliff sits exactly at the recorded 1h TTL.

**3. Requests and Turns both separable.** Claude Code writes **one record per
content block**, so 41,173 assistant records collapse to **20,946 Requests** by
`requestId`; the last record of each group carries the final token counts in
13,605/13,605 cases. **This is load-bearing: counting per-record instead of per
`requestId` yields 1,055 Cache Breaks instead of 155 — a 6.8x phantom inflation.**
Turns come from `promptId` (on user records only), with an explicit
`turn_duration` end marker. No single `turn_context` object; its fields are
scattered top-level (`effort`, `model`, `cwd`, `gitBranch`, `permissionMode`).

**4. Subagents distinguishable — and they do not replay.** `isSidechain` on 100%
of records, partitioning perfectly with the directory layout (0 mixed files);
59.1% of files are sidechains. First-Request `cache_read` median is 20,677 for
main sessions but **0** for subagents, so CONTEXT.md's Replayed Request rule has
no work to do here.

**5. Compaction is announced, not inferred.** `system` records with
`subtype: "compact_boundary"` carry `compactMetadata` with `preTokens`,
`postTokens`, `cumulativeDroppedTokens`, `trigger`. Verified against the numeric
signature: `292,982 -> 55,964` against `preTokens 293,839 / postTokens 15,474`.

**6. Cost/quota — REFUTED, definitively.** Two structural searches (a permissive
key-name regex, then 57 explicit candidate names) across all 563 files. **Absent
as a structural key anywhere:** `plan_type`, `subscription`, `quota`,
`rate_limit`, `resets_at`, `usage_limit`, `credits`, `balance`, `tier`,
`organization`, `billing`, `spend`, `overage`, `weeklyLimit`, `percentUsed`, and
42 others. Three things exist and none is a quota signal: `service_tier` (always
`"standard"` — an API tier, not a plan); `apiErrorStatus` 429 ×19 with a
**plain-string** body (no `retry_after`, no reset, no remaining); and a
`cost-state` record present in **1 of 563 files** (2.1.246 only) whose own numbers
contradict the Session it summarises — it claims 27,792 cache-read against the
Session's actual 59,301,850.

**7. Cache Breaks computable — and the server reports the cause.** Over 156 main
sessions / 16,933 deduped Requests: **155 Cache Breaks (0.92%), 30.6M Re-billed,
Hit Rate 98.43%**, with the Idle-Gap correlation reproducing Codex's shape.

Then the finding that reshapes the effort: **`message.diagnostics.cache_miss_reason`**,
on 221 deduped Requests across 80 files — a **server-reported Break Cause**:

| `type` | Requests | maps to CONTEXT.md Break Cause |
|---|---:|---|
| `previous_message_not_found` | 126 | **TTL expiry** — 104 of 105 breaks at >1h |
| `unavailable` | 53 | ~~cache warm-up~~ — **REFUTED by [09](09-grade-the-heuristic.md)** |
| `tools_changed` | 19 | **turn_context change** — all at <2m gap |
| `model_changed` | 10 | **turn_context change** |
| `messages_changed` | 10 | **history rewrite / Compaction** |
| `system_changed` | 3 | **turn_context change** |

The four `*_changed` types also carry **`cache_missed_input_tokens`** — Re-billed
Tokens reported by the server. Against the computed figure over 42 samples the
median ratio is 1.169, and the outliers are exactly the compaction cases where
naive Expected Cache over-counts by 6–14x: **the server number is the honest one
there.** Neither signal subsumes the other — 92 arithmetic breaks carry no server
reason (69 at a 10–60m gap, 10 mixed-model, 13 genuine *unknown*), and 72
Requests carry a reason without an arithmetic break.

## Verdicts

**Cache forensics: FULL — and Claude Code is a better *reference* source than
Codex, not merely an equal one.** It supplies four things Codex cannot: a
recorded TTL (no `TTL_GAP_S` heuristic), a labelled Compaction boundary with
pre/post counts, a server-reported Break Cause taxonomy mapping almost 1:1 onto
CONTEXT.md's list, and a server-reported Re-billed figure that corrects the
arithmetic at compaction. The one thing that must be right is the `requestId`
dedupe.

**Cost / quota: NOT VIABLE.** Refuted structurally at 563 files / 95,131 records.

Note for whoever builds `docs/tickets/005`: 82 of 20,864 `requestId`s appear in
more than one file (session forks/resumes copying history), so cross-Session
aggregation needs a global dedupe. Treat unknown `usage` keys as additive —
10 versions in ~4 months, with `output_tokens_details` arriving at 2.1.239 and
`cost-state` at 2.1.246.

## Correction (2026-08-28, from [09](09-grade-the-heuristic.md))

Two claims above are wrong and are corrected here rather than left to propagate:

- **`unavailable` is not cache warm-up.** 45 of its 47 main-session occurrences
  sit on Requests we classify as *hits*, median Retention **1.0000**, none
  carrying `cache_missed_input_tokens`. It reads as "the reason is unavailable",
  not "the cache was unavailable".
- **"Maps almost one-to-one" was optimistic.** Measured, only **2 of 29**
  `*_changed` Breaks reach our `turn_context change`. Nothing in the transcript
  states the tool set, so all 19 `tools_changed` are invisible to the
  fingerprint. The mapping is a good *taxonomy* match and a poor *outcome* match.
