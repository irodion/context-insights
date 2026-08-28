# 08 — Verify Copilot's session-store.db against a real install

Type: task
Status: open
Blocked by: —

## Question

[05](05-copilot-telemetry.md) established from GitHub's own schema that Copilot's
session **log** cannot support Cache Break detection, and from four third-party
parsers that a SQLite **ledger** at `~/.copilot/session-store.db` probably can.
The ledger claim rests entirely on documentation and other people's code — the
Copilot CLI has never run on this machine, so the evidence rule marks that cell
unverified.

One experiment closes it, roughly ten minutes. Install the Copilot CLI, run one
throwaway multi-turn session, then read the DB and confirm:

- `assistant_usage_events` exists, with the columns 05 lists;
- rows are one per API call, not per Turn;
- `cache_read_tokens` is non-zero on a repeat Turn — the 2026-04-14 fix landed;
- `turn_index` is actually populated, since it is the only join key back to
  `events.jsonl` for Break Cause attribution;
- whether `input_tokens` already includes cache-write tokens, which would break
  Expected Cache arithmetic if assumed otherwise.

**This does not block [07](07-the-matrix.md).** If it goes unresolved, the matrix
records Copilot as *log: not viable (schema-confirmed); ledger: unverified* and
says so. Resolving it upgrades that cell to a firm viable or not-viable.

Caveat from 05: this account is `free_limited_copilot`, so a meaningful
multi-turn session may hit limits before producing a repeat-Turn cache read.

Human-in-the-loop: installation and an interactive session need the user.
