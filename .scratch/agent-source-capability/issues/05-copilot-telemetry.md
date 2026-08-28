# 05 — Copilot: is there any local session telemetry at all?

Type: research
Status: claimed
Blocked by: —

## Question

Copilot is in scope for this effort but has no ticket in `docs/tickets` and no
known log format. Establish whether GitHub Copilot writes any local session
telemetry Context Insights could parse.

Establish: which Copilot surface is even a candidate (Copilot CLI, the coding
agent, IDE chat); whether any of them persist a session log locally; whether token
usage with a **cached-input split** is recorded — without that there is no Cache
Break detection; whether premium-request or quota consumption is exposed locally;
and if nothing is local, whether a pull-from-cloud path exists comparable to
Cursor's usage CSV export.

**"No usable local telemetry" is a valid and useful verdict** — it retires Copilot
from the roadmap with evidence instead of leaving it as an open maybe.
