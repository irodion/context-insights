# 04 — Cursor: what telemetry is actually obtainable?

Type: research
Status: open
Blocked by: 03

## Question

With Cursor CLI installed (03), establish what is actually obtainable, against the
installed version rather than against documentation.

`docs/tickets/003`'s 2026-08-26 web research claims the `afterAgentResponse` hook
payload carries `input_tokens`, `output_tokens`, `cache_read_tokens` and
`cache_write_tokens`, and that `store.db` is undocumented SQLite with opaque blobs.
Verify both.

Establish: does `afterAgentResponse` fire per **Request** or per **Turn** — 003
lists this as the open question that determines waterfall resolution; does the
non-interactive bug (forum #169059, `cursor-agent -p` omitting token-carrying
hooks) still reproduce; is any plan/quota/rate-limit signal present; and do
`store.db` blobs hold usage data that would make a first-class local adapter
possible.
