# 06 — Does the agent-agnostic analysis contract survive?

Type: grilling
Status: open
Blocked by: 01, 02

## Question

`CONTEXT.md` says analysis code must not know which agent produced a Session, and
`CLAUDE.md` repeats it: adapters normalize into one session dict.

Recon on 2026-08-28 suggests the sources differ **in kind**, not merely in quality.
Claude Code records the cache TTL per Request but appears to carry no quota data;
Codex carries quota data but forces the TTL to be inferred through the
`TTL_GAP_S` heuristic. If that holds, a strictly agent-agnostic analysis layer can
only ever express the *intersection* of its sources — the worst of each.

Decide: does the rule survive as-is; does it become "agent-agnostic but
capability-aware", with each adapter declaring a capability set the analysis
branches on; or does it break, and analysis becomes per-source below some line?

Whatever is decided becomes vocabulary in `CONTEXT.md` before it appears in code.
