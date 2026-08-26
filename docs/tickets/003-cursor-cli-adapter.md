# 003 — Cursor CLI Agent adapter (second Agent Source)

**Status:** blocked — Cursor CLI not installed on this machine, no sample logs
**Priority:** 3

## Context

CONTEXT.md defines Agent Source with Codex as the first adapter
(`load_codex_session`). Cursor CLI Agent is the wanted second source. Nothing
can be built until we can look at its on-disk session/log format.

## Unblock first (user action)

- Install Cursor CLI (`cursor-agent`) or obtain a sample session log from a
  machine that has it.
- Then: locate its session storage (likely under `~/.cursor/…`), confirm it
  records per-request token usage with a cached-input split. If it does not
  expose cached tokens, this ticket collapses to "context growth only, no
  cache-break detection for Cursor" — decide then.

## Goal

- `load_cursor_session(path)` returning the same normalized session dict
  (Session/Request per CONTEXT.md); analysis + waterfall work unchanged.
- CLI flag `--source codex|cursor|all` (default codex).

## Acceptance

- A real Cursor session renders in the waterfall with breaks/hit-rate, or a
  documented finding that Cursor logs lack the needed fields.

## Research findings (2026-08-26, web only — no local install)

- Local storage is `~/.cursor/chats/<chat-id>/<uuid>/store.db` — undocumented
  SQLite with opaque blobs; no confirmed token data. tokscale explicitly does
  NOT parse local Cursor state and uses the web API instead.
- Cursor's usage CSV export (cursor.com/dashboard/usage) has per-request rows
  **with cache read/write token columns** → break detection ports over.
- Degradations vs Codex: no event stream → only idle-gap/TTL attribution, no
  history-rewrite/config forensics; sessions must be inferred from timestamp
  gaps; acquisition is pull-from-cloud (manual CSV or session token), so no
  live tail for Cursor.
- Open: inspect store.db blobs on a machine with Cursor installed — if they
  hold serialized usage, a first-class local adapter is back on the table.

## Decision (2026-08-26): hooks-based capture — preferred approach

Cursor hooks (`~/.cursor/hooks.json`) solve the data problem: in interactive
mode the `afterAgentResponse` payload carries **input_tokens, output_tokens,
cache_read_tokens, cache_write_tokens**; `beforeSubmitPrompt` / `sessionStart`
/ `stop` give turn boundaries. Plan:

- Ship a hook script that appends one JSON line per response to
  `~/.context-insights/cursor-sessions.jsonl` (our own rollout-equivalent).
- `load_cursor_session` reads that file; analysis/waterfall unchanged.
- Live tail (ticket 002) works for Cursor too — hooks fire in real time.

Caveats:
- Known bug: non-interactive CLI (`cursor-agent -p`) omits the token-carrying
  hooks entirely (forum #169059). Interactive-only until Cursor fixes it.
- No history before hook install; forensics stays gap-based (no prompt bytes).
- Verify empirically: does afterAgentResponse fire per API request (loop
  step) or per turn? Determines waterfall resolution.

Fallbacks, in order: store.db blob inspection → cloud CSV export.

## Notes

- Keep adapter self-contained like the Codex one; no shared parsing helpers
  until a third source forces it.
