# 005 — Claude Code adapter (third Agent Source)

**Status:** open · **Priority:** 3

## Context

Originally ruled out ("this is not for Claude Code") — scope consciously
changed 2026-08-26: with Codex working and Cursor planned, Claude Code
rounds out the user's daily agents.

## Why it's easy

Claude Code writes session transcripts to
`~/.claude/projects/<project-slug>/<session-id>.jsonl`; assistant messages
carry per-request `usage` with `input_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`, `output_tokens` — a direct mapping to our
Request fields (cache_read → cached, cache_creation → cache_write). Same
read-only local-file pattern as Codex; no hooks needed.

## Sketch

- `load_claude_session(path)` → normalized session dict per CONTEXT.md.
- Map fields; turn boundaries from message roles; detect subagent/sidechain
  files (verify: `isSidechain` flag) and strip or mark like Codex subagents.
- `--source codex|claude|all` flag (shared with ticket 003's `cursor`).
- Verify against ccusage's numbers for a sanity check on a few sessions.

## Open questions

- Compaction in Claude Code (auto-compact) — how does it appear in the
  transcript? Classify like Codex compaction, don't count as break.
- API-key vs subscription sessions — any usage-field differences?

## Acceptance

- This project's own Claude Code sessions render in the waterfall with
  plausible hit rates and breaks.
