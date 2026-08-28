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
- `turn_index` is actually populated, since it is the only join key back to
  `events.jsonl` for Break Cause attribution;
- whether `input_tokens` already includes cache-write tokens, which would break
  Expected Cache arithmetic if assumed otherwise;
- `cache_read_tokens` is non-zero on a repeat Turn — the 2026-04-14 fix landed.

**Record the Copilot CLI version and the model used** alongside the results. The
`cache_read_tokens` claim is version-gated on a specific fix date, so a result
that does not name the version it was taken on cannot be compared against the
2026-04-14 boundary or re-checked later.

**The repeat Turn has to be cache-eligible to mean anything.** Second Turns
differing in their prefix cannot hit the cache whatever the ledger records, so
send a second Turn that re-sends a substantial identical prefix — same session,
same system context, an appended question rather than a new topic — and keep the
prefix well above any provider minimum.

**A zero is only evidence when the Turn was eligible.** If limits, a short
prefix, or a model swap prevented a cache-eligible repeat, record
`cache_read_tokens = 0` as **inconclusive**, not as a failed check: it cannot
distinguish "the fix is absent" from "there was nothing to hit". A firm negative
needs an eligible repeat Turn that still reads zero.

**This does not block [07](07-the-matrix.md).** If it goes unresolved, the matrix
records Copilot as *log: not viable (schema-confirmed); ledger: unverified* and
says so. Resolving it upgrades that cell to a firm viable or not-viable.

Caveat from 05: this account is `free_limited_copilot`, so a meaningful
multi-turn session may hit limits before producing a repeat-Turn cache read —
which is exactly the case that must be booked inconclusive rather than negative.
The other four checks do not need a cache hit and stand on their own, so the
experiment is still worth running if only they can be answered.

Human-in-the-loop: installation and an interactive session need the user.
