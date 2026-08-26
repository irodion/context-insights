# 004 — Repo scaffolding + GitHub repo

**Status:** open · **Priority:** 2

## Goal

Minimal scaffolding (this stays a personal tool — no production dancing) and
a GitHub repo on the user's account so the project survives the machine.

## Scope

- `README.md`: what it is, the waterfall screenshot, 3-command quickstart
  (parse / detail / web), pointer to CONTEXT.md and docs/tickets.
- `.gitignore`: already exists — extend if scaffolding adds artifacts.
- No packaging (no pyproject), no CI, no license file unless going public.
- Create GitHub repo `context-insights` on the user's account
  (`gh repo create --private --source . --push`), push `master` and
  `prototype/waterfall-variants`.

## Decisions

- **Private by default** — user stated this is not an open-source product.
  Flipping public later is a conscious decision (then add a license).

## Acceptance

- Fresh clone + `python3 parse_codex.py --web` + open `waterfall.html` works
  by following README alone.
