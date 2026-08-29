# 005 — Claude Code adapter (second Agent Source)

**Status:** done 2026-08-28 · **Priority:** 2 (the highest-value unblocked work; every
open question is now answered with evidence)

## Context

Originally ruled out ("this is not for Claude Code"), scope changed 2026-08-26,
and re-scoped again 2026-08-28 after `.scratch/agent-source-capability`
[ticket 02](../../.scratch/agent-source-capability/issues/02-claude-code-telemetry.md)
measured the format across **563 transcripts, 95,131 records, 78 project
directories, 10 Claude Code versions**.

That research changes this ticket's premise. Claude Code is not the *third*
Agent Source rounding out the set — on the cache-forensics axis it is a **better
reference source than Codex**, and it is the cheapest adapter to build because
everything the existing analysis needs is present at 100% coverage across every
version measured.

Both of this ticket's former open questions are answered below and removed.

## Why it is the low-hanging fruit

`~/.claude/projects/<project-slug>/<session-id>.jsonl`, append-only, read-only,
no hooks — the same shape as the Codex adapter. Every field `analyze()` needs is
present on **100%** of the 41,173 assistant records measured:

| Claude Code | our Request field |
|---|---|
| `message.usage.input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens` | `input` (total prompt) |
| `message.usage.cache_read_input_tokens` | `cached` |
| `message.usage.cache_creation_input_tokens` | cache write |
| `message.usage.output_tokens` | `output` |

Expected Cache and Retention derive exactly as `CONTEXT.md` defines them, so
`analyze()`, `explain_breaks()`, `idle_gap_advice()` and the Waterfall work
**unchanged**. This ticket ships the adapter and nothing else.

## The one thing that must be right: Replayed Request has an analogue

Claude Code writes **one JSONL record per content block**, not per API call.
41,173 assistant records collapse to **20,946 Requests** grouped by `requestId`.

**Group by `requestId` and take the last record of the group** — it carries the
final `output_tokens` in 13,605 of 13,605 multi-record groups, and `message.id`
is 1:1 with `requestId` (0 of 20,864 map to more than one).

Skip this and the corpus reports **1,055 Cache Breaks instead of 155 — a 6.8x
phantom inflation.** This is Claude Code's Replayed Request: same class of
defect, different mechanism, different fix. It belongs in `CONTEXT.md` as
vocabulary before it appears in code.

Also: **82 of 20,864 `requestId`s appear in more than one file** (session forks
and resumes copy history), so cross-Session aggregation needs a global dedupe,
not just a per-file one.

## Scope

- `load_claude_session(path)` → the normalized session dict, `agent_source:
  "claude-code"`. Dedupe by `requestId` within the file. The cross-file dedupe
  above cannot live inside a per-path loader: the caller that walks a corpus
  keeps **one** `requestId` set across every file it loads and drops Requests
  already seen in an earlier Session, so `--source all` counts the 82 shared ids
  once. The normalized output and `agent_source` are unchanged either way.
- **Turns** from `promptId` — present on 98.97% of `user` records and **0%** of
  assistant records; tool-result records carry the originating prompt's id.
  Attribution yields 17,004 Requests placed and 1 orphan. There is also an
  explicit end marker: `system` records with `subtype: "turn_duration"`.
- **Thread Source** from `isSidechain`, present on 100% of records and
  partitioning perfectly with the directory layout (0 mixed files; 59.1% of files
  are sidechains). Every sidechain also carries `agentId`, so parentage is
  recoverable.
- **Compaction** from `system` records with `subtype: "compact_boundary"`,
  carrying `compactMetadata` with `preTokens` / `postTokens` /
  `cumulativeDroppedTokens` / `trigger`. Classify as Compaction, never as a
  Cache Break.
- `--source codex|claude-code|cursor|all` — one enum shared across adapters, so
  ticket 003's `cursor` and this ticket's `claude-code` are values of the same
  flag rather than two separate scopes. Whichever adapter lands first adds its
  value; `all` means every adapter present.
- Treat unknown `usage` keys as **additive**: 10 versions appeared in a ~4-month
  corpus, `output_tokens_details` arriving at 2.1.239. Never require an optional
  key.

## Answers to the questions this ticket used to hold open

- **Compaction** — announced, not inferred. `compact_boundary` +
  `compactMetadata`, verified against the numeric signature (`292,982 → 55,964`
  against `preTokens 293,839 / postTokens 15,474`). Strictly better than Codex,
  where it must be detected by ratio.
- **API-key vs subscription sessions** — no usage-field difference.
  `service_tier` is `"standard"` on 41,075 of 41,173 records and is an API tier,
  not a plan. There is no plan, quota or rate-limit signal anywhere in the
  format, so there is nothing to branch on. (See ticket 009: this source cannot
  report cost at all.)
- **Subagents do not replay.** First-Request `cache_read` median is 20,677 for
  main sessions and **0** for subagent transcripts, so `strip_replay()` has no
  analogue to implement here. Mark them, do not strip them.

## Acceptance

Numbers to reproduce — these are what the research measured over 156 main
sessions / 16,933 deduped Requests, so a correct adapter should land on them:

- **155 Cache Breaks (0.92% of non-first Requests)**, 70 cold and 85 partial —
  *not* 1,055.
- **30,566,765 Re-billed Tokens**, Session-wide **Hit Rate 98.43%**.
- Idle-Gap correlation **0.2% / 2.3% / 3.0% / 88.2%** across <2m / 2–10m /
  10–60m / >1h — the cliff at 1h corroborating the recorded TTL.
- This project's own Claude Code sessions render in the Waterfall with those
  hit rates and breaks.
- Tests at the agreed seam: a synthetic transcript whose Requests span multiple
  content-block records must yield one Request per `requestId`, not one per
  record.

## Out of scope

The server-reported Break Cause, Re-billed figure and cache TTL — ticket `012`.
They require deciding whether analysis may know that a source reported the
answer, which is a vocabulary change this adapter does not need.


## Decisions

**The cross-file dedupe has to keep the Request it drops as a baseline.** Removing a
Copied Request outright hands the Request behind it an older, smaller prompt as its
Expected Cache, which turns a Cache Break into a hit — and the Request behind a copy is
a resumed Session's first, the one most likely to have re-paid for its whole context.
Over the corpus that hid **1 Cache Break and 183,736 Re-billed Tokens**. The last copy
of a run now stays as that baseline.

It stays as *context*, not as a Request of this Session — the second half of the same
fix. A retained baseline that gets classified is measured against a history it is no
longer part of: drop a Compaction from between it and its new predecessor and it scores
a Cache Break neither Session recorded. So it sets the next Expected Cache and nothing
else — kind `copied`, no tokens in this Session's totals, no vote in the Prefix Floor.
It costs the real corpus nothing, the one live case having its baseline at position 0
with no predecessor to be measured against; it closes the interior case.

Ownership moved with it. "The first Session loaded keeps it" was first by *file path*,
and the corpus holds one case where that is wrong: 80 Requests shared between a Session
721 Requests deep and one that opens *on* the shared block as its leading history. The
inheritor sorts first alphabetically and began eight hours later, so it was claiming
calls the running Session made. Sessions are now walked oldest first.

**Two record kinds are not Requests, not one.** The ticket named the Content-Block
Record. The corpus holds a second: **38 Rejected Calls** — `assistant` records with
`apiErrorStatus` 429 (×19) or 529 (×19) and a `usage` block of zeros, 38 of 38
carrying no usage at all. Counted as Requests they do more than pad the count: a zero
prompt becomes the *next* Request's Expected Cache, so a genuine Cache Break behind a
rejection reads as a clean hit, and a zero Cached Input enters the Prefix Floor as a
cold rebuild that never happened. Both are in `CONTEXT.md`, alongside **Copied
Request** for the cross-file duplicates.

**The `turn_context` fingerprint is an allow-list, and this time it is sourced.**
Claude Code has no `turn_context` object, so the fields are chosen rather than
inherited — which is exactly the trap `010` fell into. Measured over 21,776 non-first
Requests (base Cache Break rate 0.99%):

| candidate field | changes | of those, Breaks | break rate |
|---|---:|---:|---:|
| `model` | 13 | 11 | **84.6%** |
| `effort` | 7 | 5 | **71.4%** |
| `gitBranch` | 39 | 3 | 7.7% |
| `cwd` | 569 | 4 | **0.7%** — *under* the base rate |
| `permissionMode`, `entrypoint` | 0 | 0 | never move |

The fingerprint is therefore `model` and `effort` alone. The server corroborates:
8 of the 13 model switches carry `cache_miss_reason.type = model_changed`, as do 2 of
the 7 effort changes — the provider files effort under model config too. `cwd` is the
field that would have been fingerprinted by reflex and would have manufactured
attributions on 569 moves that break nothing. A guard test pins the exclusion.

**`sessionId` does not identify a subagent Session.** A sidechain transcript records
the *parent's* `sessionId`, so 26 Waterfall keys collided over the corpus — one name
covering 130 files, which `WatchMode` would have folded into a single row. Sidechains
carry their own `agentId` (346 files, exactly one id each, 345 distinct), so that is
the Session identity. Collisions: 26 → 1.

**Turns come from `promptId` alone.** It places 11,416 of 11,416 Requests; only 5
arrive after a `turn_duration` marker before the next prompt. The end marker is in the
format but is not load-bearing, so it is not read.

**Compaction is announced but, on this corpus, never corrects.** The 60% ratio catches
22 of 22 announced Compactions that have a prior Request to be compared against. The
announcement is still what classifies them — a stated fact beats a threshold, and it
is what makes the agreement checkable — but no reclassification rides on it today.

**Whether a source replays is a fact each adapter states.** Claude Code subagents do
not replay: median first-Request `cache_read` is 0 across 318 sidechain Sessions (172
start at exactly zero), and none of 4,342 consecutive sidechain Request pairs fall
inside the 200ms burst window. The first cut relied on that — `strip_replay()` guards
only on Thread Source, which this adapter now also sets to `subagent`, so the Codex
burst scan ran on Claude Code Sessions and was inert by data luck alone. A sidechain
whose first two Requests land 100ms apart loses its cold start, which is exactly the
Request `CONTEXT.md` needs as the smallest rebuild a Session can have. Both adapters
now return `replays_parent`, and `strip_replay()` returns early on a source that does
not. A test pins it.

**`--source` defaults to `all`.** With two adapters the useful default is the whole
corpus; `--dir` now overrides the root of a single named source and is an error
without one. `--session` and `--explain` pick their adapter from the file name — only
Codex calls its Sessions `rollout-*.jsonl`. Watch Mode stays Codex-only: it follows a
`rollout-*.jsonl` by mtime, and extending it is its own ticket.

**The seam is a type, not a second file.** A review of this diff asked for the two
adapters and the registry to move into `agent_sources.py`, on the grounds that
`parse_codex.py` grew from 753 to 982 lines and now holds a second concern. The
concern is real but the split does not address it: adding the next adapter is a
function plus one `ADAPTERS` row either way, and it would *also* touch
`find_live_session()`, Watch Mode and the CLI, which stay behind — so extraction makes
ticket `003` a two-file change rather than a one-file one. `parse_ts()` is used by
`strip_replay()` on the analysis side, so the cut is not even clean.

What the review wanted protected is that analysis cannot see the Agent Source, and
that was enforced by nothing: the normalized session was an untyped `dict[str, Any]`
built by two functions and read by six, and a file boundary would not have checked it
either. It is now `Session` / `Request` / `Analysis` TypedDicts with a
`SessionLoader = Callable[[Path], Session | None]` on the registry, so a new adapter
that returns the wrong shape fails `mypy` rather than a reading. Source-specific keys
are `NotRequired` and say which source records them; `total_input` and
`context_window` are Codex-only and turn out to be read by nothing downstream.

The registry type alone did not close it: an *unannotated* loader is
`Callable[[Path], Any]` and satisfies `SessionLoader` while returning anything at all —
verified by feeding a deliberately wrong `load_cursor_session` through both shapes.
`parse_codex.py` therefore turns on `disallow_untyped_defs`, which cost six annotations
(`parse_ts`, `gap_seconds`, `idle_gap_advice`, `fmt_duration`, `fmt_tokens`, `main`).
Typing `parse_ts(s: str)` showed that `strip_replay()` passed it a `ts` that may be
`None`, where `.replace` raises an `AttributeError` the surrounding `except` does not
catch — `gap_seconds()` catches it, `strip_replay()` never did. It now parses `ts or ""`
and stops on the `ValueError`, which is what the loop already did for a bad timestamp.

Writing the contract down found one bug: `--session` and `--explain` passed the
adapter's `None` straight into `analyze()`, so a file that is not a Session died on
`TypeError: 'NoneType' object is not subscriptable`. Both now stop at an argparse
error. `003`'s standing rule is unchanged — no shared parsing helpers until a third
source forces it — and the file split waits for that source, when there will be
evidence about what belongs in the module.

**Ownership is settled for `--session` and `--explain` too.** They read the named file
through its adapter and analyzed that, so a transcript holding inherited history
counted it: **1,606 Requests where the corpus assigns 1,526**, 80 Copied Requests wide.
The blast radius is small — 6 of 529 transcripts hold a copy, 3 of them differ — and
narrower than it looked: Re-billed Tokens are identical in all six, and the same six
Cache Breaks are explained with the same causes either way, so a copy being *diagnosed*
as this Session's spend is a shape this corpus does not contain.

The Prefix Floor moved, though, which neither reading predicted. Copies enter it as
rebuild evidence, and on that transcript they broke corroboration: `--explain` reported
Retention "against zero — no two cache rebuilds agreed on a prefix floor", and now
reports it above a **21,972** floor. That changes every Retention figure the command
prints for the Session, which is what the forensics are read for.

`owned_session()` walks the file's source root exactly as the corpus walk does and
picks the Session out of the result. The two agree by construction rather than by
care: `load_sessions()` updates `seen` *before* it applies `min_requests` and
`include_all`, so ownership does not depend on the arguments those commands pass —
verified as identical `analysis` dicts on all six affected transcripts. The cost is
0.07s to ~1.1s per invocation, paid by Codex too for a guaranteed no-op, which is the
price of the two views never disagreeing again.

Scoping the walk to the transcript's own project slug would have made it cheap, and the
corpus does not forbid it: **0 of the 82 duplicate ids span two slugs** (2 span two
immediate parent directories, but only because a sidechain sits in a `subagents/`
subdirectory of the same project). It is rejected on risk rather than on evidence —
nothing makes a slug a boundary, and a Session resumed from a different working
directory is written under a different one — and ~1s is a price this tool can pay to
not depend on that. Outside its source root there is no corpus to settle against, so
the file is read alone and the command says so on stderr; `--dir` names the ownership
root, which is why these two commands now run before the `--dir`/`--source` check that
belongs to the corpus walk.

**One test suite per Agent Source.** The test file reached 1,401 lines holding two log
grammars, so the Claude Code half moved to `test_claude_adapter.py` and the four fixture
helpers neither grammar owns to `support.py` — deliberately not named `test_*`, so
`discover` does not import a helper module as a suite. The cut is one-way and was
checked rather than assumed: the Codex half uses nothing from the Claude half, and the
Claude half used exactly `at()`, `write_jsonl()` and `temp_dir()`. A pure move —
the same 51 tests, every method's source byte-identical, verified by comparing parsed
ASTs before and after. `discover` and CI need no change, and `python3 -m unittest
test_claude_adapter` now runs one adapter's 19 tests instead of all 51.

`SourceSelectionTest` is the exception: it is not a Claude Code test but the only one
that speaks both grammars, so it lives with the Claude suite and imports the two Codex
fixtures it needs. It is there because Claude Code is the source that made `--source`
necessary, and its docstring says so.

**This ticket broke CI, and three review passes did not catch it.** The smoke test runs
`parse_codex.py --dir "$RUNNER_TEMP/no-sessions"`, which used to be the whole CLI with a
different sessions directory. `--source` now defaults to `all`, and `--dir` names the
root of *one* source, so that command exits 2 on an argparse error instead of 0. Found
while checking whether the test split touched CI, not by any of the reviews. The
workflow now passes `--source codex` alongside `--dir`; the error itself is right, since
one directory cannot be the root of several sources.

**Watch Mode names the source it supports, not the one it refuses.** The guard read
`if args.source == "claude-code"`, which encodes the registry as it stands rather than
the contract. Adding a third adapter to a scratch copy showed what that costs, and it is
worse than refusing to run: with `--dir` the watcher globs `rollout-*.jsonl` in the new
source's directory and reports **"parsed 0 sessions"**, and *without* `--dir` it falls
back to `SESSIONS_DIR` and silently follows **299 Codex Sessions** while the user is
asking to watch something else — a successful-looking watch of the wrong Agent Source.

`WATCHABLE_SOURCE = "codex"` now names what works and every other `--source` is
refused. Watch Mode's tail is Codex-shaped end to end — the glob, `load_codex_session()`
and `peek_thread_source()` reading an opening `session_meta` line no other source writes
— so a `watchable` flag on the adapter spec was the tempting shape and the wrong one:
it gates entry without generalizing the watcher, so setting it on a second source would
open the gate onto the Codex tail and look deliberate while doing it. Wiring a second
source is ticket `002`'s remaining work; this only stops a new adapter being opted into
a command it does not implement.

## Acceptance, measured

Run over `~/.claude/projects` on 2026-08-28: **593 transcripts**, 165 main Sessions at
`--min-requests 3`, 17,537 deduped Requests.

| criterion | ticket | measured | verdict |
|---|---:|---:|---|
| Hit Rate | 98.43% | **98.42%** | ✅ |
| cross-file duplicate ids | 82 | **82** | ✅ |
| subagent share of Breaks | 38.7% | **38.4%** (83 of 216) | ✅ |
| Idle Gap >1h break rate | 88.2% | **90.9%** | ✅ the cliff is at 1h |
| Cache Breaks | 155 | **133** | ⚠️ see below |
| Re-billed Tokens | 30,566,765 | **23,817,221** | ⚠️ see below |

**The two headline numbers were measured without the Compaction rule this same ticket
mandates.** Adding the 21 announced Compactions back in as Cache Breaks — and
re-billing them the naive way — gives **154 Breaks and 30,367,759 Re-billed**, against
the ticket's 155 and 30,566,765, the remainder being four months of corpus that has
kept growing since. So the adapter reproduces the acceptance figure exactly when it
adopts the mistake the acceptance figure contains. Scope says "Classify as Compaction,
never as a Cache Break", so 133 / 23.8M is the honest number and the 6,550,538 tokens
of Compaction sit where they belong. `014` is where the question of whether *some* of
that is genuinely re-billed gets settled.

The cold/partial split moved for a second reason: the ticket says 70 cold / 85 partial,
the adapter reports 123 / 10. `013` landed the Prefix Floor after this ticket's numbers
were taken, and re-measuring Retention above the floor is precisely what turns a Break
that kept only the re-sent head from "partial" into "cold".

## Not done here

- The Waterfall renders both sources in one ranking, and a row still shows only its
  model — no Agent Source badge. Readable in practice (`claude-opus-5` against
  `gpt-5.6-sol`), but it is a gap.
- Watch Mode does not follow a Claude Code Session.
- `cache_creation.ephemeral_1h/5m` (the recorded TTL) and
  `message.diagnostics.cache_miss_reason` are parsed by nothing. `TTL_GAP_S` stays a
  heuristic; the server-reported cause stays `012`.
