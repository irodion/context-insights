# 006 — Installation script

**Status:** open · **Priority:** 4 (after 002/003 exist to install)

## Goal

One command that sets the tool up on a machine: `./install.sh`.

## Scope

- Symlink a `context-insights` command onto PATH (`~/.local/bin` or
  `/usr/local/bin`, whichever exists and is writable) wrapping
  `parse_codex.py` (rename CLI entry if multi-source lands first).
- Create `~/.context-insights/` for generated data (waterfall_data.js moves
  here so the repo checkout stays clean).
- If Cursor is present (`~/.cursor` exists): register the hook script from
  ticket 003 into `~/.cursor/hooks.json` (merge, don't clobber; idempotent).
- Print what was done and how to undo it. `--uninstall` reverses everything.
- Plain bash + python3 stdlib; no package managers.

## Acceptance

- Running twice is a no-op the second time (idempotent).
- `--uninstall` removes symlink and hook registration, leaves user data.

## Non-goals

- Homebrew/pipx/npm packaging, auto-update, multi-user installs.
