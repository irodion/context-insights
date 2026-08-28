# 03 — Install Cursor CLI and capture a sample session

Type: task
Status: open
Blocked by: —

## Question

`docs/tickets/003` has been blocked since 2026-08-26 on Cursor CLI not being
installed; nothing about Cursor can be verified without it. This ticket is the
manual work that unblocks 04 — there is nothing to decide here.

Install `cursor-agent`, run a session of at least a few Turns, and record where
its state lands.

Deliver: confirmation the CLI runs and its version; the path to any local session
store (expected `~/.cursor/chats/<chat-id>/<uuid>/store.db`); whether
`~/.cursor/hooks.json` is honoured by the installed version; and a captured sample
session for 04 to analyze.

Human-in-the-loop: installation and an interactive session need the user.
