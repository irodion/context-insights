# 05 — Copilot: is there any local session telemetry at all?

Type: research
Status: resolved
Blocked by: —

## Question

Copilot is in scope for this effort but has no ticket in `docs/tickets` and no
known log format. Establish whether GitHub Copilot writes any local session
telemetry Context Insights could parse.

Establish: which Copilot surface is even a candidate (Copilot CLI, the coding
agent, IDE chat); whether any of them persist a session log locally; whether token
usage with a **cached-input split** is recorded — without that there is no Cache
Break detection; whether premium-request or quota consumption is exposed locally;
and if nothing is local, whether a pull-from-cloud path exists comparable to
Cursor's usage CSV export.

**"No usable local telemetry" is a valid and useful verdict** — it retires Copilot
from the roadmap with evidence instead of leaving it as an open maybe.

## Answer

Resolved 2026-08-28. The premise of the question was wrong in both directions:
"Copilot has no local telemetry" is false, and "Copilot has a parseable session
log" is also false. The split is precise.

### A. Local, verified on this machine

The **Copilot CLI has never run a session here.** `gh` 2.87.2 is installed with
**no** `gh-copilot` extension; no `copilot` binary in PATH; no global npm
`@github/copilot`. `~/.copilot/` exists but holds only a 131-byte
`config.json` (`firstLaunchAt` and nothing else), an empty `ide/`, 2.4 MB of
unrelated skill markdown, and one lifecycle log whose last line is
`Destroying 0 active sessions`. **`~/.copilot/session-state/` and
`~/.copilot/session-store.db` do not exist.**

**VS Code Copilot Chat writes no usage to disk.** 23 chat session files grepped
for `token|cache|usage|premium|quota`: the only hits are `maxInputTokens` /
`maxOutputTokens` — model *capability* limits, not consumption. Extension logs'
only token hits are auth (`copilot token sku: free_limited_copilot`).
`state.vscdb` scanned for `cached_tokens|cache_read_input_tokens|premium_request`:
no hits.

**And the client demonstrably has the data — it just ships it away.** The bundled
extension's `telemetry.json` declares `response.success` with measurements
`promptcachetokencount` ("prompt tokens hitting cache as reported by server") and
`promptcachecreation5mtokencount` / `promptcachecreation1htokencount`, built in
`extension.js` from `usage.prompt_tokens_details.cached_tokens` and
`cache_read_input_tokens`, tagged for Microsoft telemetry. Copilot Chat measures
exactly what this tool needs and persists none of it locally.

### B. Documentation — UNVERIFIED (no Copilot session data exists here to check)

**The session log cannot support Cache Break detection — a firm negative from
GitHub's own schema.** `github/copilot-sdk`'s streaming-events doc classifies
`assistant.usage` — the event carrying `cacheReadTokens`, `cacheWriteTokens` and
`cacheExpiresAt` — as **Ephemeral: "streamed in real time but not persisted to
the session log."** The one event with the per-request cached split is the one
event that never reaches `events.jsonl`. What does persist is output tokens per
message, a compaction record, and per-model *session totals* — enough for a
session Hit Rate, not for a Waterfall.

**But a SQLite ledger appears to hold exactly the right shape.** GitHub Docs
describe `~/.copilot/session-store.db`, and four independent third-party parsers
written against real installs agree on a table `assistant_usage_events` with
`session_id, turn_index, model, input_tokens, output_tokens, cache_read_tokens,
cache_write_tokens, total_nano_aiu, created_at` — one row per API call.
`copilot-cli` issue #4351 corroborates from a real install: 158 request rows, and
"the local ledger's total is the one that matches actual billed usage."

Unverified caveats attached: `input_tokens` reportedly already includes
cache-write tokens (an Expected Cache arithmetic trap); `cacheReadTokens` was
hard-`0` for all providers until a 2026-04-14 fix, so older rows are likely
zeroed; GitHub reserves the right to change the schema and calls it an internal
implementation detail.

**Quota:** `total_nano_aiu` per row is a *real billed cost*, not a price-table
estimate — better than Codex's quantized percentage. The cloud path is useless:
the premium-request CSV export is enterprise-only and carries request counts, no
tokens and no cached split. **There is no Copilot equivalent of Cursor's
token-level usage CSV.**

### Verdict

- **Session log: NOT VIABLE** — schema-confirmed, per-request usage is ephemeral
  by design.
- **SQLite ledger: UNVERIFIED, plausibly viable** — and one ~10-minute experiment
  from a decision. See [08](08-verify-copilot-ledger.md).
- **Cost/quota: potentially better than any other source**, if the ledger holds.

Even in the good case a Copilot adapter is architecturally heavier than every
other source: Break *Cause* attribution needs prompt content from `events.jsonl`
while tokens live in the ledger, so it is a two-source join on
`session_id` + `turn_index`. `sqlite3` is stdlib, so no dependency argument
arises — but `CLAUDE.md`'s "no abstraction bought on credit" does.

**Recommendation: no adapter ticket in `docs/tickets`.** The account here is
`free_limited_copilot`, and GitHub reserves schema changes, which makes an
adapter a maintenance liability for a personal tool.
