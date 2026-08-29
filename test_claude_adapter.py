"""Tests for the Claude Code adapter, the second Agent Source (ticket 005).

Seams under test:

- `load_claude_session()` — one Claude Code transcript in, the normalized Session out.
  What counts as a Request is the whole question for this adapter.
- `analyze()` on a Claude Code Session — the agent-agnostic seam: the second source has
  to reach the same analysis without the analysis knowing it arrived.
- `explain_breaks()` on a Claude Code Session — the same Break Causes, reached from a
  different log format.
- `load_corpus()` and `owned_session()` — the Agent Sources to walk in, their Sessions
  out, with one request-id set spanning the walk so a Copied Request is counted once.

Fixtures are synthetic transcripts written to a temp file and read back through the real
adapter, so the tests exercise the public path (`load_claude_session` -> `analyze` ->
...) rather than internals. `SourceSelectionTest` is the one test that needs both log
grammars, so it borrows the Codex fixtures from `test_parse_codex.py`.
"""

import unittest
from pathlib import Path
from typing import Any

import parse_codex
from support import at, temp_dir, write_jsonl
from test_parse_codex import RolloutFixture, a_turn

CLAUDE_VERSION = "2.1.246"
UNCACHED_TAIL = 2  # tokens of a prompt neither read from nor written to the cache


def claude_ts(seconds: float) -> str:
    """Timestamp `seconds` after the session start, in Claude Code's log format."""
    return at(seconds, timespec="milliseconds")


def claude_record(ts: str, type_: str, uuid: str, **fields: Any) -> dict:
    """The envelope every Claude Code record carries, whatever its type. `isSidechain`
    is stamped by TranscriptFixture, which owns that fact for the whole transcript."""
    return {
        "type": type_,
        "timestamp": ts,
        "uuid": uuid,
        "version": CLAUDE_VERSION,
        "sessionId": "session-fixture",
        "cwd": "/tmp/proj",
        **fields,
    }


def a_claude_request(
    ts: str,
    request_id: str,
    *,
    prompt: int,
    cached: int,
    output: int = 100,
    blocks: int = 1,
    model: str = "claude-opus-5",
    effort: str = "medium",
    cwd: str = "/tmp/proj",
) -> list[dict]:
    """One API call as Claude Code writes it: `blocks` `assistant` records sharing a
    `requestId`, each repeating the same usage because the call was billed once. The
    prompt is spelled in the three parts that sum to it, the way the provider bills."""
    write = prompt - cached - UNCACHED_TAIL
    return [
        claude_record(
            ts,
            "assistant",
            f"{request_id}-block{i}",
            requestId=request_id,
            cwd=cwd,
            effort=effort,
            message={
                "id": f"msg-{request_id}",
                "model": model,
                "content": [{"type": "text"}],
                "usage": {
                    "input_tokens": UNCACHED_TAIL,
                    "cache_read_input_tokens": cached,
                    "cache_creation_input_tokens": write,
                    "output_tokens": output,
                    "service_tier": "standard",
                    "cache_creation": {
                        "ephemeral_1h_input_tokens": write,
                        "ephemeral_5m_input_tokens": 0,
                    },
                },
            },
        )
        for i in range(blocks)
    ]


def compact_boundary(ts: str, pre: int, post: int) -> dict:
    """The record announcing a Compaction, with the token counts either side of it."""
    return claude_record(
        ts,
        "system",
        f"compact-{ts}",
        subtype="compact_boundary",
        content="",
        compactMetadata={
            "trigger": "manual",
            "preTokens": pre,
            "postTokens": post,
            "cumulativeDroppedTokens": pre - post,
        },
    )


def rejected_call(ts: str, request_id: str, status: int = 429) -> dict:
    """A call the provider turned away: an `assistant` record with an error status and
    a `usage` block of zeros. Measured over the corpus, 38 of 38 carry no usage."""
    [rec] = a_claude_request(ts, request_id, prompt=UNCACHED_TAIL, cached=0, output=0)
    rec["apiErrorStatus"] = status
    rec["isApiErrorMessage"] = True
    rec["message"]["usage"] = {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "service_tier": None,
        "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
    }
    return rec


def user_prompt(ts: str, prompt_id: str) -> dict:
    """A person's message, opening a Turn. Only `user` records carry `promptId`."""
    return claude_record(
        ts,
        "user",
        f"{prompt_id}-prompt",
        promptId=prompt_id,
        message={"role": "user", "content": "do a thing"},
    )


def tool_result(ts: str, prompt_id: str) -> dict:
    """A tool result inside a Turn: also a `user` record, and it carries the
    originating prompt's id rather than a new one."""
    return claude_record(
        ts,
        "user",
        f"{prompt_id}-result-{ts}",
        promptId=prompt_id,
        message={
            "role": "user",
            "content": [{"type": "tool_result", "content": "ok", "tool_use_id": "tu-1"}],
        },
    )


class TranscriptFixture:
    """Builds a synthetic Claude Code transcript and loads it through the adapter."""

    def __init__(
        self,
        testcase: unittest.TestCase,
        directory: Path | None = None,
        name: str = "session-fixture.jsonl",
        sidechain: bool = False,
        agent_id: str = "agent-1",
    ) -> None:
        root = directory or temp_dir(testcase)
        self.path = root / "-tmp-proj" / name
        self.sidechain = sidechain
        self.agent_id = agent_id
        self.records: list[dict] = []

    def add(self, *records: dict | list[dict]) -> "TranscriptFixture":
        for r in records:
            self.records.extend(r if isinstance(r, list) else [r])
        return self

    def write(self) -> Path:
        for r in self.records:  # a transcript is all sidechain or none of it
            r["isSidechain"] = self.sidechain
            if self.sidechain:  # written alongside the *parent's* sessionId
                r["agentId"] = self.agent_id
        return write_jsonl(self.path, self.records)

    def loaded(self) -> parse_codex.Session:
        session = parse_codex.load_claude_session(self.write())
        assert session is not None, "fixture wrote no Session"
        return session

    def analyzed(self) -> parse_codex.Session:
        return parse_codex.analyze(self.loaded())


class ContentBlockRecordTest(unittest.TestCase):
    """Claude Code writes one record per content block, so one API call leaves several
    records behind sharing a `requestId`. Counting records instead of groups reported
    1,055 Cache Breaks over a corpus that holds 155."""

    def test_records_sharing_a_request_id_are_one_request(self):
        """Two API calls written as five records are two Requests, and each Request's
        input is the whole prompt: the cached part, the part being written to cache,
        and the uncached tail."""
        session = (
            TranscriptFixture(self)
            .add(a_claude_request(claude_ts(0), "req-1", prompt=30_000, cached=0, blocks=3))
            .add(a_claude_request(claude_ts(10), "req-2", prompt=32_000, cached=30_000, blocks=2))
            .loaded()
        )

        self.assertEqual(
            [(r["input"], r["cached"]) for r in session["requests"]],
            [(30_000, 0), (32_000, 30_000)],
        )

    def test_a_multi_block_reply_does_not_invent_a_cache_break(self):
        """The defect the collapse exists to prevent. A Request that writes a lot of new
        context reads back less than 80% of its own prompt, so a repeated record looks
        like a prefix that died — against a previous Request that was never re-sent."""
        session = (
            TranscriptFixture(self)
            .add(a_claude_request(claude_ts(0), "req-1", prompt=20_000, cached=0))
            .add(a_claude_request(claude_ts(10), "req-2", prompt=60_000, cached=20_000, blocks=3))
            .add(a_claude_request(claude_ts(20), "req-3", prompt=62_000, cached=60_000))
            .analyzed()
        )

        self.assertEqual(session["analysis"]["requests"], 3)
        self.assertEqual(session["analysis"]["breaks"], 0)


class TurnAttributionTest(unittest.TestCase):
    """Turns come from `promptId`, which only `user` records carry. A tool result is
    written as a `user` record too, but it repeats the prompt id it is answering, so
    the agentic loop stays inside one Turn."""

    def test_requests_belong_to_the_turn_whose_prompt_they_answer(self):
        session = (
            TranscriptFixture(self)
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0))
            .add(tool_result(claude_ts(6), "prompt-a"))
            .add(a_claude_request(claude_ts(9), "req-2", prompt=22_000, cached=20_000))
            .add(user_prompt(claude_ts(30), "prompt-b"))
            .add(a_claude_request(claude_ts(35), "req-3", prompt=24_000, cached=22_000))
            .loaded()
        )

        self.assertEqual([r["turn"] for r in session["requests"]], [1, 1, 2])
        self.assertEqual([r["first_in_turn"] for r in session["requests"]], [True, False, True])


class ThreadSourceTest(unittest.TestCase):
    """`isSidechain` is on every record and partitions by file: a transcript is a
    subagent's or a person's, never both."""

    def test_a_sidechain_transcript_is_a_subagent_session(self):
        def load(sidechain: bool) -> parse_codex.Session:
            return (
                TranscriptFixture(self, sidechain=sidechain)
                .add(user_prompt(claude_ts(0), "prompt-a"))
                .add(a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0))
                .loaded()
            )

        self.assertEqual(load(sidechain=True)["thread_source"], "subagent")
        self.assertEqual(load(sidechain=False)["thread_source"], "user")

    def test_a_subagent_that_answers_fast_keeps_its_cold_start(self):
        """Codex strips a subagent's replayed prefix by finding Requests within 200ms of
        each other. Claude Code subagents open cold — median first-Request cache_read is
        0 across 318 sidechain Sessions — so there is nothing to strip, and a fast pair
        of the child's own Requests must not be mistaken for a replay. The Request at
        risk is the cold start, which CONTEXT.md needs as the smallest rebuild a Session
        can have."""
        session = (
            TranscriptFixture(self, sidechain=True)
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0))
            .add(a_claude_request(claude_ts(5.1), "req-2", prompt=22_000, cached=20_000))
            .add(a_claude_request(claude_ts(9), "req-3", prompt=24_000, cached=22_000))
            .analyzed()
        )

        self.assertEqual([r["kind"] for r in session["requests"]], ["first", "hit", "hit"])

    def test_a_subagent_session_is_identified_by_its_own_id(self):
        """A sidechain transcript records the *parent's* `sessionId`, so every subagent
        of one Session answers to the same name — 26 of them collided over the corpus,
        one name covering 130 files. The Waterfall holds a row's selection by that name
        and Watch Mode recognizes a Session by it, so the subagent's own `agentId` is
        the identity."""
        parent, child = (
            TranscriptFixture(self, name=f"{label}.jsonl", sidechain=sidechain, agent_id="agent-7")
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0))
            .loaded()
            for label, sidechain in (("main", False), ("sub", True))
        )

        self.assertEqual(parent["session_id"], "session-fixture")
        self.assertEqual(child["session_id"], "agent-7")


class RejectedCallTest(unittest.TestCase):
    """A rejection is written like a reply but billed like nothing: an error status and
    a `usage` block of zeros."""

    def test_a_rejected_call_does_not_hide_the_cache_break_behind_it(self):
        """Counted as a Request, its zero prompt becomes the next Request's Expected
        Cache — and the Break that followed the rejection reads as a clean hit."""
        session = (
            TranscriptFixture(self)
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=40_000, cached=0))
            .add(rejected_call(claude_ts(6), "req-2"))
            .add(a_claude_request(claude_ts(8), "req-3", prompt=42_000, cached=0))
            .analyzed()
        )

        self.assertEqual(session["analysis"]["requests"], 2)
        self.assertEqual(session["analysis"]["breaks"], 1)
        self.assertEqual(session["analysis"]["rebilled_tokens"], 40_000)


class AnnouncedCompactionTest(unittest.TestCase):
    """Claude Code says when it compacts, so the classification does not rest on the
    size of the drop. On the corpus the ratio happens to catch every announced
    Compaction too; the announcement is what makes that agreement checkable rather
    than a threshold to tune."""

    def test_a_compaction_the_log_announces_is_not_a_cache_break(self):
        """A shallow Compaction — the prompt falls to 70% of the previous one, short of
        the ratio's 60%. Inferred, this is a cold Cache Break re-billing the whole
        previous prompt; announced, it is a Compaction and re-bills nothing."""
        session = (
            TranscriptFixture(self)
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=60_000, cached=0))
            .add(a_claude_request(claude_ts(10), "req-2", prompt=100_000, cached=60_000))
            .add(compact_boundary(claude_ts(20), pre=100_000, post=12_000))
            .add(user_prompt(claude_ts(25), "prompt-b"))
            .add(a_claude_request(claude_ts(30), "req-3", prompt=70_000, cached=0))
            .analyzed()
        )

        self.assertEqual([r["kind"] for r in session["requests"]], ["first", "hit", "compaction"])
        self.assertEqual(session["analysis"]["rebilled_tokens"], 0)


class ClaudeCodeBreakCauseTest(unittest.TestCase):
    """Claude Code has no `turn_context` object; the settings that travel with a Request
    sit at the top level of its records. Which of them the fingerprint may hold is an
    evidence question (ticket 010): a field that is not in the prompt cannot explain a
    Cache Break, and fingerprinting it invents attributions."""

    def a_session_that_breaks_when_the_settings_move(
        self, **second_turn: Any
    ) -> parse_codex.Session:
        return (
            TranscriptFixture(self)
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=60_000, cached=0))
            .add(a_claude_request(claude_ts(10), "req-2", prompt=80_000, cached=60_000))
            .add(user_prompt(claude_ts(20), "prompt-b"))
            .add(a_claude_request(claude_ts(25), "req-3", prompt=82_000, cached=0, **second_turn))
            .analyzed()
        )

    def test_a_model_switch_is_named_as_the_cause(self):
        """13 model switches over the corpus, 11 of them Cache Breaks, and the server
        calls 8 of those `model_changed`. A different model does not share a cache."""
        session = self.a_session_that_breaks_when_the_settings_move(model="claude-sonnet-5")

        [diagnosis] = parse_codex.explain_breaks(session)

        self.assertEqual(diagnosis["cause"], parse_codex.CAUSE_TURN_CONTEXT)
        self.assertIn("claude-opus-5 -> claude-sonnet-5", diagnosis["detail"])

    def test_a_changed_working_directory_is_not_a_cause(self):
        """Guards the exclusion. `cwd` moved 569 times over the corpus for a 0.7% break
        rate, under the 0.99% base rate, so it is not in the cached prefix. In the
        fingerprint it would hand this Break a confident wrong answer in place of the
        right one, which is how ticket 010 lost a seventh of the corpus."""
        session = self.a_session_that_breaks_when_the_settings_move(cwd="/tmp/elsewhere")

        [diagnosis] = parse_codex.explain_breaks(session)

        self.assertEqual(diagnosis["cause"], parse_codex.CAUSE_HISTORY_REWRITE)
        self.assertNotIn("cwd", diagnosis["detail"])


class CopiedRequestTest(unittest.TestCase):
    """Forking or resuming a Session copies the history it inherits, request ids and
    all — 82 of 20,864 ids appear in more than one file. The copies were billed in the
    Session that made them, so a corpus walk does not bill them again. What it must not
    do is forget they were there: the Request behind a copy was built on top of it."""

    def test_a_copied_block_is_not_billed_to_the_fork_twice(self):
        """Only the last of the copied run stays, as the baseline for the Request that
        follows it. The rest belong to the Session that made them."""
        root = temp_dir(self)
        shared = [
            a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0),
            a_claude_request(claude_ts(10), "req-2", prompt=22_000, cached=20_000),
        ]
        original = TranscriptFixture(self, directory=root, name="a.jsonl")
        original.add(user_prompt(claude_ts(0), "prompt-a")).add(*shared)
        original.add(a_claude_request(claude_ts(15), "req-3", prompt=24_000, cached=22_000))
        original.write()
        fork = TranscriptFixture(self, directory=root, name="b.jsonl")
        fork.add(user_prompt(claude_ts(0), "prompt-a")).add(*shared)
        fork.add(a_claude_request(claude_ts(600), "req-4", prompt=24_000, cached=22_000))
        fork.write()

        sessions = parse_codex.load_corpus(
            ["claude-code"], min_requests=1, include_all=True, roots={"claude-code": root}
        )

        self.assertEqual([len(s["requests"]) for s in sessions], [3, 2])
        self.assertEqual([r["id"] for r in sessions[1]["requests"]], ["req-2", "req-4"])

    def test_the_session_that_was_already_running_keeps_the_request(self):
        """ "First" is first in time, not first in the directory listing. The shape is
        the one the corpus actually holds: a Session 641 Requests deep, and a second
        that opens *on* the shared block and carries it as its leading history. The
        older Session made those calls; the younger inherited them — but the file that
        sorts first is the 8-hours-younger one, which would otherwise claim them."""
        root = temp_dir(self)
        shared = a_claude_request(claude_ts(100), "req-shared", prompt=40_000, cached=20_000)
        younger = TranscriptFixture(self, directory=root, name="a-younger.jsonl")
        younger.add(shared)
        younger.add(a_claude_request(claude_ts(200), "req-y", prompt=42_000, cached=40_000))
        younger.write()
        older = TranscriptFixture(self, directory=root, name="z-older.jsonl")
        older.add(user_prompt(claude_ts(0), "prompt-a"))
        older.add(a_claude_request(claude_ts(5), "req-o", prompt=20_000, cached=0))
        older.add(shared)
        older.write()

        sessions = parse_codex.load_corpus(
            ["claude-code"], min_requests=1, include_all=True, roots={"claude-code": root}
        )
        owns = {Path(s["file"]).name: [r["id"] for r in s["requests"]] for s in sessions}

        self.assertEqual(owns["z-older.jsonl"], ["req-o", "req-shared"])
        # The younger Session keeps it only as the baseline for the Request after it.
        self.assertEqual(owns["a-younger.jsonl"], ["req-shared", "req-y"])

    def test_a_copy_still_sets_the_expected_cache_of_the_request_after_it(self):
        """A Copied Request is another Session's spend but this Session's history: the
        next prompt sits on top of it. Removed outright, the Request behind it inherits
        an older, smaller prompt as its Expected Cache, and a Cache Break becomes a hit
        — here 50k of Re-billed Tokens that were really paid."""
        root = temp_dir(self)
        shared = a_claude_request(claude_ts(10), "req-shared", prompt=80_000, cached=60_000)
        original = TranscriptFixture(self, directory=root, name="a.jsonl")
        original.add(user_prompt(claude_ts(0), "prompt-a"))
        original.add(a_claude_request(claude_ts(5), "req-a1", prompt=20_000, cached=0))
        original.add(shared)
        original.write()
        fork = TranscriptFixture(self, directory=root, name="b.jsonl")
        fork.add(shared)
        fork.add(a_claude_request(claude_ts(20), "req-b", prompt=90_000, cached=30_000))
        fork.write()

        _, forked = parse_codex.load_corpus(
            ["claude-code"], min_requests=1, include_all=True, roots={"claude-code": root}
        )

        self.assertEqual([r["kind"] for r in forked["requests"]], ["copied", "break"])
        self.assertEqual(forked["requests"][-1]["rebilled"], 50_000)

    def test_a_retained_baseline_is_not_billed_against_the_history_it_left(self):
        """The baseline is context, not a Request of this Session — so it must not be
        classified either. Two Sessions record the same two calls; the older one keeps
        them, and the younger drops the Compaction among them but keeps the Request
        after it as its baseline. Measured against the prompt that now precedes it —
        the one the Compaction shrank — that baseline scores a Cache Break neither
        transcript contains."""
        root = temp_dir(self)
        shared = [
            a_claude_request(claude_ts(100), "req-c1", prompt=40_000, cached=0),
            a_claude_request(claude_ts(110), "req-c2", prompt=60_000, cached=40_000),
        ]
        older = TranscriptFixture(self, directory=root, name="x.jsonl")
        older.add(user_prompt(claude_ts(0), "prompt-x"))
        older.add(a_claude_request(claude_ts(1), "req-x", prompt=80_000, cached=0))
        older.add(*shared)
        older.write()
        younger = TranscriptFixture(self, directory=root, name="y.jsonl")
        younger.add(user_prompt(claude_ts(50), "prompt-y"))
        younger.add(a_claude_request(claude_ts(51), "req-y", prompt=80_000, cached=0))
        younger.add(*shared)
        younger.add(a_claude_request(claude_ts(200), "req-y2", prompt=62_000, cached=60_000))
        younger.write()

        loaded = parse_codex.load_corpus(
            ["claude-code"], min_requests=1, include_all=True, roots={"claude-code": root}
        )
        by_file = {Path(s["file"]).name: s for s in loaded}

        self.assertEqual(by_file["x.jsonl"]["analysis"]["breaks"], 0)
        self.assertEqual(by_file["y.jsonl"]["analysis"]["breaks"], 0)
        self.assertEqual(by_file["y.jsonl"]["analysis"]["rebilled_tokens"], 0)

    def test_a_fork_resumed_after_the_cache_expired_reports_what_it_re_paid(self):
        """Picking a Session up two hours later re-sends the inherited history at full
        price. Those tokens are this fork's own bill even though the Request they were
        cached from belongs to another Session — dropping the copy outright would leave
        the resumed Request looking like a Session's first, costing nothing."""
        root = temp_dir(self)
        shared = a_claude_request(claude_ts(5), "req-1", prompt=80_000, cached=60_000)
        original = TranscriptFixture(self, directory=root, name="a.jsonl")
        original.add(user_prompt(claude_ts(0), "prompt-a")).add(shared)
        original.add(a_claude_request(claude_ts(10), "req-2", prompt=82_000, cached=80_000))
        original.write()
        fork = TranscriptFixture(self, directory=root, name="b.jsonl")
        fork.add(user_prompt(claude_ts(0), "prompt-a")).add(shared)
        fork.add(a_claude_request(claude_ts(7_200), "req-3", prompt=82_000, cached=0))
        fork.write()

        _, forked = parse_codex.load_corpus(
            ["claude-code"], min_requests=1, include_all=True, roots={"claude-code": root}
        )

        [diagnosis] = parse_codex.explain_breaks(forked)

        self.assertEqual(diagnosis["cause"], parse_codex.CAUSE_TTL_EXPIRY)
        self.assertEqual(forked["analysis"]["rebilled_tokens"], 80_000)

    def test_a_single_file_reading_does_not_claim_the_copies_it_inherited(self):
        """`--session` and `--explain` name one file, but which Session owns a Copied
        Request is not a question one file can answer. Read alone, the fork counts the
        history it inherited as its own spend; asked for through the source root, it
        reports what the corpus reports."""
        root = temp_dir(self)
        shared = [
            a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0),
            a_claude_request(claude_ts(10), "req-2", prompt=22_000, cached=20_000),
        ]
        original = TranscriptFixture(self, directory=root, name="a.jsonl")
        original.add(user_prompt(claude_ts(0), "prompt-a")).add(*shared).write()
        fork = TranscriptFixture(self, directory=root, name="b.jsonl")
        fork.add(user_prompt(claude_ts(0), "prompt-a")).add(*shared)
        fork.add(a_claude_request(claude_ts(600), "req-3", prompt=24_000, cached=22_000))
        fork.write()

        read_alone = parse_codex.load_session_file(fork.path)
        owned = parse_codex.owned_session(fork.path, root)
        assert read_alone is not None and owned is not None
        alone = parse_codex.analyze(read_alone)

        self.assertEqual(alone["analysis"]["requests"], 3)
        self.assertEqual(owned["analysis"]["requests"], 1)
        # And it is the same answer the corpus walk gives for that Session.
        corpus = parse_codex.load_corpus(
            ["claude-code"], min_requests=1, include_all=True, roots={"claude-code": root}
        )
        by_file = {Path(s["file"]).name: s for s in corpus}
        self.assertEqual(owned["analysis"], by_file["b.jsonl"]["analysis"])

    def test_a_session_file_outside_its_source_root_cannot_be_owned(self):
        """Nothing to settle ownership against, so the caller is told rather than given
        a per-file reading dressed up as a Session's spend."""
        root, elsewhere = temp_dir(self), temp_dir(self)
        stray = TranscriptFixture(self, directory=elsewhere, name="stray.jsonl")
        stray.add(user_prompt(claude_ts(0), "prompt-a"))
        stray.add(a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0))
        stray.write()

        self.assertIsNone(parse_codex.owned_session(stray.path, root))
        self.assertIsNotNone(parse_codex.load_session_file(stray.path))


class SourceSelectionTest(unittest.TestCase):
    """`--source` names which Agent Sources a corpus walk reads. Each keeps its own
    root and its own file pattern; `all` is every adapter present.

    The one test that has to speak both log grammars, so it borrows the Codex fixtures
    from the other suite. It lives here because Claude Code is the source that made
    `--source` necessary."""

    def roots(self) -> dict[str, Path]:
        codex, claude = temp_dir(self), temp_dir(self)
        a_turn(RolloutFixture(self, directory=codex)).write()
        (
            TranscriptFixture(self, directory=claude)
            .add(user_prompt(claude_ts(0), "prompt-a"))
            .add(a_claude_request(claude_ts(5), "req-1", prompt=20_000, cached=0))
            .add(a_claude_request(claude_ts(10), "req-2", prompt=22_000, cached=20_000))
            .add(a_claude_request(claude_ts(15), "req-3", prompt=24_000, cached=22_000))
            .write()
        )
        return {"codex": codex, "claude-code": claude}

    def test_one_source_reads_only_its_own_sessions(self):
        roots = self.roots()

        for source in ("codex", "claude-code"):
            sessions = parse_codex.load_corpus([source], 2, include_all=True, roots=roots)

            self.assertEqual([s["agent_source"] for s in sessions], [source])

    def test_all_sources_read_together(self):
        sessions = parse_codex.load_corpus(
            ["codex", "claude-code"], 2, include_all=True, roots=self.roots()
        )

        self.assertEqual([s["agent_source"] for s in sessions], ["codex", "claude-code"])


if __name__ == "__main__":
    unittest.main()
