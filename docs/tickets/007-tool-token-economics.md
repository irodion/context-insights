# 007 — Tool token economics: which tools eat context, what failures cost

**Status:** open · **Priority:** 2 (after 001 — reuses its event-correlation
machinery)

## Context

Tool outputs are the dominant driver of context growth (the "fresh input" band
in the waterfall). The rollout stream has `function_call` / `function_call_output`
items between `token_count` events, so per-request input growth can be
attributed to the tool calls that landed in it. Merged proposal from
2026-08-26: general tool usage + errored calls, one parsing pass, two views.

## Goal

Two analyses on top of the existing parser:

1. **Cost by tool** — for each tool (exec_command, write_stdin, MCP tools…):
   how many input tokens its outputs added to context, and — because context
   is linear — the carried cost: tokens added × requests remaining in session.
   Answers "which tools eat your context window".
2. **Cost of failures** — tool calls that returned errors: the context growth
   from error output + retry chains (same/similar call re-issued after a
   failure). Headline number: "N tokens spent on failed tool calls", peer to
   the re-billed total.

## Sketch

- Correlate items between consecutive `token_count` events (001 builds this).
- Attribute that request's input delta across the `function_call_output`s in
  the window, proportional to their content size (estimate ~4 chars/token —
  precision is not the point, ranking is).
- Failure detection: exit codes / error markers in `function_call_output`
  payloads — inspect real payload shape first.
- Retry chain: same tool + similar arguments within K subsequent calls after
  a failure.
- Output: new sections in the CLI summary + a per-session table; waterfall
  integration (e.g. tooltip showing top context-eaters) only if cheap.

## Acceptance

- Summary over all sessions names top 5 context-eating tools with token
  totals, and a failed-call waste total with the worst offenders listed.

## Non-goals

- Generic call-count analytics with no token dimension.
