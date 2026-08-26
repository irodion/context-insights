# Context Insights — Ubiquitous Language

## Core concepts

**Agent Source** — a CLI AI agent whose logs we can parse. Currently: Codex CLI (`~/.codex/sessions`). Planned: Cursor CLI Agent (no local install yet, adapter deferred). Each Agent Source gets an adapter that normalizes its logs into Sessions and Requests.

**Session** — one conversation thread of an agent, backed by one rollout file (Codex: `rollout-*.jsonl`). Has a Thread Source.

**Thread Source** — who initiated the Session: `user` (a person in the TUI/Desktop), `subagent` (spawned by another Session), or other (`realtime_voice`, ...). Subagent Sessions replay the parent's token history into their own log; their replayed prefix must not be counted as this Session's own spend.

**Request** — one API call to the model, the atomic unit of measurement. In Codex logs it is a `token_count` event; its `last_token_usage` gives this Request's own tokens: input, cached input, cache-write input, output, reasoning output.

**Turn** — one user-prompt-to-final-answer exchange; contains one or more Requests (the agentic loop).

## Cache vocabulary

**Cached Input** — the portion of a Request's input tokens served from the provider's prompt cache (billed at the discounted rate).

**Expected Cache** — what *should* have been cached on a Request in a healthy linear agent loop: approximately the full prompt of the previous Request (its input tokens). The first Request of a Session has no Expected Cache.

**Cache Break** — a Request whose Cached Input falls materially below its Expected Cache: the prompt prefix changed and the cache was invalidated from that point on.

**Re-billed Tokens** — the tokens a Cache Break cost: Expected Cache minus Cached Input. These were paid at the full input rate although they had been processed (and cached) before.

**Compaction** — the agent summarizes history to shrink context; input tokens drop sharply. Looks like a Cache Break in the numbers but is deliberate; classified separately.

**Hit Rate** — Cached Input / total input tokens, per Request or aggregated over a Session.

## Visualization

**Waterfall** — the target visual: Requests on the x-axis over time, each drawn as a stacked bar of Cached Input (cool) vs uncached input (hot), like an RF spectrum waterfall. Cache Breaks show as hot spikes.
