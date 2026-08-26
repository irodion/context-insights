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

## Notes

- Keep adapter self-contained like the Codex one; no shared parsing helpers
  until a third source forces it.
