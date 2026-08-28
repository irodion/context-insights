# 02 — Claude Code: what cache and cost telemetry do transcripts carry?

Type: research
Status: claimed
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
