# 008 — Untrusted context share: how much of the context came from the internet

**Status:** open · **Priority:** 5 (experimental; depends on 007's attribution
mechanics)

## Context

Once web content enters the conversation, every later request carries it —
it is prompt-injection surface riding in the prefix. Framed in this tool's
native language: what share of the current context window originated from
untrusted sources, measured in tokens over time.

## Known limitation (accepted up front)

Detection is heuristic and leaky — a **lower bound**, never a guarantee.
Classifying tool calls catches the obvious network paths; any shell command
can touch the network in ways we cannot see. The UI must say "at least",
never "only".

## Sketch

- Classifier over `function_call` items: web/search/fetch tool names, MCP
  tools known to hit the network, `exec_command` payloads matching
  curl/wget/URLs/git-clone-of-remote/package installs.
- Reuse 007's output-size attribution: tokens contributed by calls classified
  untrusted, accumulated over the session (content persists in context once
  it enters — until compaction, which resets accounting like elsewhere).
- Waterfall: shade or hatch the untrusted share of each bar; per-session
  "untrusted context: ≥N tokens (M% of final context)" stat.

## Acceptance

- A session that fetched web pages shows a nonzero, plausible untrusted share
  climbing from the fetch onward; a purely local session shows zero.
- Wording everywhere communicates lower-bound semantics.

## Non-goals

- Actual security scanning/detection of injection content; verdicts about
  whether untrusted content was malicious. This measures exposure, nothing
  else.
