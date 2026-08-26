# 004 — Repo scaffolding + GitHub repo

**Status:** done (2026-08-26) · **Priority:** 2

## Goal

Minimal scaffolding (this stays a personal tool — no production dancing) and
a GitHub repo on the user's account so the project survives the machine.

## Scope

- `README.md`: what it is, quickstart (parse / detail / web), pointer to
  CONTEXT.md and docs/tickets.
- `CLAUDE.md` with `AGENTS.md` symlinked to it: conventions for agents.
- `.gitignore`: extended with Python caches and `.venv/`.
- Python tooling: ruff (lint + format) and mypy, pinned in
  `requirements-dev.txt`, configured in `pyproject.toml` (tool sections only —
  still no packaging), run by a versioned `.githooks/pre-push` and by
  GitHub Actions CI on 3.13 + 3.14.
- Create GitHub repo `context-insights` on the user's account
  (`gh repo create --private --source . --push`), push the default branch and
  `prototype/waterfall-variants`. Default branch renamed `master` → `main`
  on GitHub right after creation.

## Decisions

- **Private by default** — user stated this is not an open-source product.
  Flipping public later is a conscious decision.
- **MIT licensed anyway** (2026-08-26, user's instruction) — the repo stays
  private; the licence just settles the terms in advance if it is opened.
- **`main` is protected** — pull request required (0 approvals, so a solo dev
  is not deadlocked), linear history enforced, force-push and deletion blocked,
  admins included. GitHub has no literal fast-forward-only merge button, so
  "ff only" is implemented as: merge commits and squash disabled, rebase merge
  the only method, plus the linear-history rule. No required status checks yet
  — CI was mid-outage; add with
  `gh api -X PATCH repos/irodion/context-insights/branches/main/protection/required_status_checks -f 'contexts[]=lint (3.13)' -f 'contexts[]=lint (3.14)'`.
- **CI after all** — this ticket originally said "no CI, no pyproject".
  Reversed 2026-08-26 on the user's instruction: ruff + mypy on a pre-push hook
  and in Actions. `pyproject.toml` carries tool config only, no build backend,
  so this is not packaging.
- **mypy is not strict** — `check_untyped_defs` only. `parse_codex.py` is
  dict-shaped and predates the tooling; annotate it opportunistically instead
  of forcing TypedDicts now.
- **Commit identity** — local `user.email` is the GitHub noreply stub
  (`9167139+irodion@users.noreply.github.com`); the eight pre-existing commits
  were rewritten to it before the first push, so no work address is published.

## Acceptance

- Fresh clone + `python3 parse_codex.py --web` + open `waterfall.html` works
  by following README alone. ✓
- `ruff check`, `ruff format --check`, `mypy` are green on `main`. ✓
- CI green on 3.13 and 3.14. ✓ (GitHub does not register a workflow added in
  the push that creates a repo — it took a later commit touching `ci.yml`.)
