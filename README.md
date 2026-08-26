# Context Insights

[![ci](https://github.com/irodion/context-insights/actions/workflows/ci.yml/badge.svg)](https://github.com/irodion/context-insights/actions/workflows/ci.yml)

Find out where your CLI coding agent burns tokens. It reads agent session logs,
detects **cache breaks** — requests whose prompt prefix changed, so the provider
re-billed context that had already been cached — and draws each session as a
waterfall of cached vs. freshly-billed input.

Today it reads Codex CLI rollouts (`~/.codex/sessions/**/rollout-*.jsonl`).
Cursor CLI and Claude Code adapters are planned; see `docs/tickets/`.

## Quickstart

Python 3.13+, standard library only — nothing to install.

```sh
git clone git@github.com:irodion/context-insights.git
cd context-insights

python3 parse_codex.py                              # all sessions, worst first
python3 parse_codex.py --session ~/.codex/sessions/2026/.../rollout-*.jsonl
python3 parse_codex.py --web && open waterfall.html # the waterfall view
```

`parse_codex.py` prints one row per session — requests, cache breaks, hit rate,
tokens re-billed — then an overall total. `--session` expands a single rollout
into per-request bars, marking each request `hit`, `break` (`!`) or
`compaction` (`~`). `--web` regenerates `waterfall_data.js`, which
`waterfall.html` reads directly from disk (no server).

Terms used throughout — Session, Request, Expected Cache, Cache Break,
Re-billed Tokens — are defined in [CONTEXT.md](CONTEXT.md).

## Development

```sh
git config core.hooksPath .githooks   # once per clone: ruff + mypy on push
```

The hook uses [uv](https://docs.astral.sh/uv) if present (otherwise `ruff` and
`mypy` on PATH) with the versions pinned in `requirements-dev.txt`; CI runs the
same checks on 3.13 and 3.14. Conventions for changes are in
[CLAUDE.md](CLAUDE.md) (`AGENTS.md` is a symlink to it); the backlog is
`docs/tickets/`.

`main` is protected: no direct pushes, changes land through a pull request,
and history stays linear (rebase merge only).

## License

[MIT](LICENSE) © 2026 Rodion Izotov
