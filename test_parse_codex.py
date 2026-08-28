"""Tests for Cache Break forensics (ticket 001) and the Live Session tail (002).

Seams under test:

- `explain_breaks()` — an analyzed Session in, one diagnosis per Cache Break out.
- `find_live_session()` — a sessions directory in, the rollout Watch Mode should
  follow out.
- `waterfall_payload()` — analyzed Sessions in, the rows the Waterfall renders out.
- `WatchMode.tick()` — one Watch Mode iteration in, the rows to render out (or None
  when nothing moved). What survives across ticks is the point: a Session must keep
  what it accrued while live once Watch Mode moves on to a newer one.

Fixtures are synthetic Codex rollouts written to a temp file and read back through
the real adapter, so the tests exercise the public path (`load_codex_session` ->
`analyze` -> ...) rather than internals.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import parse_codex

BASE = datetime.fromisoformat("2026-03-20T18:00:00+00:00")


def at(seconds: float) -> str:
    """Timestamp `seconds` after the session start, in Codex's log format."""
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def event(ts: str, type_: str, payload: dict) -> dict:
    return {"timestamp": ts, "type": type_, "payload": payload}


def token_count(
    ts: str, input_: int, cached: int, output: int = 100, total: int | None = None
) -> dict:
    """An `event_msg`/`token_count` event: one Request. `total` is the Session's
    cumulative input, which only advances when an API call actually happened."""
    return event(
        ts,
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_,
                    "cached_input_tokens": cached,
                    "cache_write_input_tokens": 0,
                    "output_tokens": output,
                    "reasoning_output_tokens": 0,
                },
                "total_token_usage": {"input_tokens": input_ if total is None else total},
                "model_context_window": 272_000,
            },
        },
    )


def turn_start(ts: str, **context) -> list[dict]:
    """The `task_started` + `turn_context` + `user_message` trio opening a Turn."""
    ctx = {"turn_id": f"turn-{ts}", "model": "gpt-5.4", "effort": "medium", "cwd": "/tmp/proj"}
    ctx.update(context)
    return [
        event(ts, "event_msg", {"type": "task_started"}),
        event(ts, "turn_context", ctx),
        event(ts, "event_msg", {"type": "user_message", "message": "do a thing"}),
    ]


def turn_end(ts: str) -> dict:
    return event(ts, "event_msg", {"type": "task_complete"})


def temp_dir(testcase: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    return Path(tmp.name)


class RolloutFixture:
    """Builds a synthetic rollout-*.jsonl and loads it through the adapter."""

    def __init__(
        self,
        testcase: unittest.TestCase,
        directory: Path | None = None,
        name: str = "rollout-2026-03-20T18-00-00-fixture.jsonl",
        thread_source: str = "user",
        cwd: str = "/tmp/proj",
    ) -> None:
        self.path = (directory or temp_dir(testcase)) / name
        self.events: list[dict] = [
            event(
                at(0),
                "session_meta",
                {
                    "id": name,
                    "timestamp": at(0),
                    "cwd": cwd,
                    "source": "vscode",
                    "thread_source": thread_source,
                },
            )
        ]

    def add(self, *events: dict | list[dict]) -> "RolloutFixture":
        for e in events:
            self.events.extend(e if isinstance(e, list) else [e])
        return self

    def write(self, modified: float | None = None) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
        if modified is not None:
            os.utime(self.path, (modified, modified))
        return self.path

    def analyzed(self) -> dict:
        return parse_codex.analyze(parse_codex.load_codex_session(self.write()))


def a_turn(fixture: RolloutFixture, **context) -> RolloutFixture:
    """The smallest believable Turn: two clean Requests. `context` overrides
    turn_context fields, so a later Turn can be made to differ from this one."""
    return (
        fixture.add(turn_start(at(0), **context))
        .add(token_count(at(10), input_=60_000, cached=40_000))
        .add(token_count(at(20), input_=80_000, cached=60_000))
        .add(turn_end(at(25)))
    )


class TTLExpiryTest(unittest.TestCase):
    def test_break_after_a_long_idle_gap_is_diagnosed_as_ttl_expiry(self):
        """A Turn resumed after an hour idle comes back with a cold cache."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=20_000, cached=9_600))
            .add(token_count(at(20), input_=40_000, cached=20_000))
            .add(turn_end(at(25)))
            # An hour of idle: the provider's prompt cache has expired.
            .add(turn_start(at(3625)))
            .add(token_count(at(3630), input_=41_000, cached=9_600))
            .add(turn_end(at(3635)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["index"], 2)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TTL_EXPIRY)
        self.assertAlmostEqual(diagnoses[0]["gap_s"], 3610, delta=1)

    def test_a_cold_resume_days_later_is_ttl_expiry_even_though_the_date_moved(self):
        """Picking a Session back up days later also moves `current_date`. The prefix
        expired long before the date did, so the cause is the idle gap — with the
        fields that moved alongside it named, not dropped."""
        fixture = (
            a_turn(RolloutFixture(self), current_date="2026-03-20")
            # Two days idle, then the same Session is resumed.
            .add(turn_start(at(172_800), current_date="2026-03-22"))
            .add(token_count(at(172_810), input_=90_000, cached=9_600))
            .add(turn_end(at(172_815)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TTL_EXPIRY)
        self.assertIn("current_date", diagnoses[0]["detail"])


class PrefixFloorTest(unittest.TestCase):
    """Every prompt re-sends an identical head — system header, tool definitions,
    instructions — which the provider re-caches immediately. Retention is measured
    above that Prefix Floor, so a Break that kept nothing of the conversation reads
    as cold rather than as `floor / expected`."""

    def test_a_resume_that_kept_only_the_prefix_floor_is_ttl_expiry(self):
        """The corpus shape ticket 010 could not reach: a multi-day resume whose
        `current_date` moved and whose cache came back holding exactly the static
        header. Measured against zero it looks like 38% of the prefix survived; above
        the floor it kept nothing, and the expired prefix is the cause."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0), current_date="2026-03-20"))
            # The Session opens on the static header alone: 21k is the Prefix Floor.
            .add(token_count(at(10), input_=30_000, cached=21_000))
            .add(token_count(at(20), input_=55_000, cached=30_000))
            .add(turn_end(at(35)))
            # Two days idle, and the cache comes back holding the header and nothing else.
            .add(turn_start(at(172_800), current_date="2026-03-22"))
            .add(token_count(at(172_810), input_=60_000, cached=21_000))
            .add(turn_end(at(172_815)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TTL_EXPIRY)
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.0, places=2)

    def test_a_break_that_alone_sets_the_floor_does_not_zero_its_own_retention(self):
        """The smallest Cached Input is only the static header if the cache actually
        came back header-only. On a Session that never does, the lowest value is just
        the deepest Break — and letting it set the floor forces its own Retention to
        zero by construction. Uncorroborated, the floor is not used."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            # Nothing here ever returns header-only: 40k is one Break, not a floor.
            .add(token_count(at(10), input_=60_000, cached=0))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(token_count(at(30), input_=90_000, cached=40_000))
            .add(turn_end(at(35)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_HISTORY_CHANGE)
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.5, places=2)

    def test_two_partial_breaks_near_each_other_do_not_establish_a_floor(self):
        """A Cache Break is not evidence of a head-only return — it can be a partial
        divergence that kept most of the conversation. Two of those landing near each
        other agree on nothing, and the head here is the 20k the Session opened on,
        far below them. Only the *smallest* rebuild can be the floor: when nothing
        corroborates it, Retention stays unadjusted rather than measured against a
        baseline invented higher up."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            # The head is 20k, and no later Request ever returns to it.
            .add(token_count(at(10), input_=30_000, cached=20_000))
            .add(token_count(at(20), input_=80_000, cached=30_000))
            # Two partial Breaks, 50k and 52k: close to each other, nowhere near the head.
            .add(token_count(at(30), input_=90_000, cached=50_000))
            .add(token_count(at(40), input_=100_000, cached=52_000))
            .add(turn_end(at(45)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(
            [d["cause"] for d in diagnoses],
            [parse_codex.CAUSE_HISTORY_CHANGE, parse_codex.CAUSE_HISTORY_CHANGE],
        )
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.625, places=2)

    def test_a_cold_start_outranks_two_partial_breaks_above_it(self):
        """A Session that opened with nothing cached has a rebuild at zero, and that is
        the smallest one. Two partial Breaks higher up cannot corroborate it, so there
        is no floor — the zero must not be dropped before the smallest rebuild is
        chosen, or those two Breaks become the bottom and invent a floor above the
        conversation they kept."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            # A genuinely cold start: the cache returned nothing at all.
            .add(token_count(at(10), input_=60_000, cached=0))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            # Two partial Breaks, 40k and 41k, both still holding conversation.
            .add(token_count(at(30), input_=90_000, cached=40_000))
            .add(token_count(at(40), input_=95_000, cached=41_000))
            .add(turn_end(at(45)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(
            [d["cause"] for d in diagnoses],
            [parse_codex.CAUSE_HISTORY_CHANGE, parse_codex.CAUSE_HISTORY_CHANGE],
        )
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.5, places=2)

    def test_a_cold_start_outranks_a_compaction_that_would_otherwise_corroborate(self):
        """The zero rebuild has to survive into the comparison, not just into the list.
        Here a Compaction and a Break agree at 25k and would pass the non-Break test on
        their own — but the Session opened with nothing cached, and that zero is the
        smallest rebuild. Nothing corroborates it, so there is no floor."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=0))
            # A Compaction at 25k, and a Break that later lands beside it at 25.5k.
            .add(token_count(at(20), input_=30_000, cached=25_000))
            .add(token_count(at(30), input_=80_000, cached=28_000))
            .add(token_count(at(40), input_=90_000, cached=25_500))
            .add(turn_end(at(45)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_HISTORY_CHANGE)
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.319, places=2)

    def test_two_breaks_alone_cannot_corroborate_a_floor_on_a_warm_Session(self):
        """A Cache Break's Cached Input is whatever survived a divergence, so it can be
        any fraction of the prefix. Two Breaks agreeing tells you they diverged at
        similar points, never that either came back on the head. On a Session that
        opened warm there is nothing below them, and the pair must not become a floor
        on its own — the corroboration has to come from outside the Breaks being
        classified."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            # Opens warm: 60k already carries conversation, and nothing ever
            # comes back on the head.
            .add(token_count(at(10), input_=70_000, cached=60_000))
            .add(token_count(at(20), input_=80_000, cached=70_000))
            # Two partial Breaks that merely landed near each other.
            .add(token_count(at(30), input_=90_000, cached=40_000))
            .add(token_count(at(40), input_=95_000, cached=41_000))
            .add(turn_end(at(45)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(
            [d["cause"] for d in diagnoses],
            [parse_codex.CAUSE_HISTORY_CHANGE, parse_codex.CAUSE_HISTORY_CHANGE],
        )
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.5, places=2)

    def test_a_hit_is_not_evidence_of_where_the_head_is(self):
        """A Hit's Cached Input is the whole previous prompt, so it bounds the head from
        *above*: the head is at most that, never exactly it. Letting a low Hit
        corroborate the floor therefore over-states it, and over-stating invents
        coldness on a Break that kept conversation."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=22_000, cached=20_000))
            # A Hit early on, while the whole prompt is barely more than the head.
            .add(token_count(at(20), input_=80_000, cached=21_000))
            .add(token_count(at(30), input_=90_000, cached=30_000))
            .add(turn_end(at(35)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_HISTORY_CHANGE)
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.375, places=2)

    def test_a_warm_resume_does_not_set_the_floor_above_surviving_conversation(self):
        """The floor is the smallest non-zero Cached Input, not the first one. A Session
        resumed warm opens with conversation already cached, so reading the floor off its
        first Request would over-state it and call a Break that kept half the
        conversation cold."""
        fixture = (
            RolloutFixture(self)
            # Resumed warm: this Request's 60k already carries conversation, not a floor.
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=70_000, cached=60_000))
            # A Compaction rebuilds the prompt down onto the head: 21.5k, and not a
            # Break, so it is evidence from outside the Breaks below.
            .add(token_count(at(20), input_=30_000, cached=21_500))
            .add(token_count(at(30), input_=80_000, cached=30_000))
            .add(turn_end(at(35)))
            # An hour idle; the cache comes back on that same head.
            .add(turn_start(at(3_600)))
            .add(token_count(at(3_625), input_=90_000, cached=21_000))
            # Mid-Turn: the floor plus half of the 69k recoverable prefix.
            .add(token_count(at(3_700), input_=95_000, cached=55_500))
            .add(turn_end(at(3_705)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(
            [d["cause"] for d in diagnoses],
            [parse_codex.CAUSE_TTL_EXPIRY, parse_codex.CAUSE_HISTORY_CHANGE],
        )
        self.assertAlmostEqual(diagnoses[1]["retention"], 0.5, places=2)


class HistoryRewriteTest(unittest.TestCase):
    def test_a_cold_turn_opening_within_the_ttl_window_is_ttl_expiry_not_a_rewrite(self):
        """A Turn opening cold after minutes of idle is the prefix ageing out, not
        re-serialization: the provider keeps a prefix for only 5-10 minutes."""
        fixture = (
            a_turn(RolloutFixture(self))
            .add(turn_start(at(440)))  # 7 minutes idle
            .add(token_count(at(445), input_=80_000, cached=9_600))
            .add(turn_end(at(450)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TTL_EXPIRY)

    def test_break_opening_a_turn_after_a_short_gap_is_diagnosed_as_history_rewrite(self):
        """Codex re-serializes history at a Turn boundary; the cache was still warm,
        so the prefix diverged rather than expired."""
        fixture = (
            a_turn(RolloutFixture(self))
            # 90s idle: well inside the cache TTL, yet most of the prefix is gone.
            .add(turn_start(at(110)))
            .add(token_count(at(115), input_=80_000, cached=13_000))
            .add(turn_end(at(120)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["index"], 2)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_HISTORY_REWRITE)

    def test_mid_turn_break_is_not_diagnosed_as_a_history_rewrite(self):
        """The rewrite happens at Turn boundaries; a break inside a Turn is something else."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(token_count(at(30), input_=90_000, cached=30_000))
            .add(turn_end(at(35)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertNotEqual(diagnoses[0]["cause"], parse_codex.CAUSE_HISTORY_REWRITE)


class TurnContextChangeTest(unittest.TestCase):
    def test_changed_reasoning_effort_is_named_as_the_cause(self):
        """Switching effort rewrites the prompt header, invalidating the whole prefix."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0), effort="medium"))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
            .add(turn_start(at(110), effort="high"))
            .add(token_count(at(115), input_=80_000, cached=13_000))
            .add(turn_end(at(120)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TURN_CONTEXT)
        self.assertIn("effort", diagnoses[0]["detail"])
        self.assertIn("medium", diagnoses[0]["detail"])
        self.assertIn("high", diagnoses[0]["detail"])

    def test_a_config_change_survives_a_long_gap_when_the_prefix_did_not_expire(self):
        """TTL expiry is tested first, but it needs both a long gap and a cold cache.
        This Session gets no Prefix Floor — its first Request cached 40k and the Break
        cached 56k, too far apart to corroborate — so Retention is the unadjusted
        56k/80k, 70%. That is far too warm to have expired, so the gap does not explain
        the break. The sandbox flip does."""
        fixture = (
            a_turn(RolloutFixture(self), file_system_sandbox_policy="read-only")
            .add(turn_start(at(86_400), file_system_sandbox_policy="workspace-write"))
            # 56k against an 80k Expected Cache: 70% survived, and no floor is
            # corroborated, so nothing rescales it.
            .add(token_count(at(86_410), input_=90_000, cached=56_000))
            .add(turn_end(at(86_415)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TURN_CONTEXT)
        self.assertIn("file_system_sandbox_policy", diagnoses[0]["detail"])

    def test_a_new_turn_id_alone_is_not_a_turn_context_change(self):
        """`turn_id` is fresh on every Turn by definition, so it can never be a cause."""
        fixture = (
            a_turn(RolloutFixture(self))
            .add(turn_start(at(110)))
            .add(token_count(at(115), input_=80_000, cached=13_000))
            .add(turn_end(at(120)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertNotEqual(diagnoses[0]["cause"], parse_codex.CAUSE_TURN_CONTEXT)


class DuplicateTokenCountTest(unittest.TestCase):
    """Codex replays a Request's token_count without a new API call having happened:
    twice within a Turn (sub-second apart) and again when the next Turn opens. Counting
    those as Requests invents Cache Breaks that never occurred."""

    def test_usage_replayed_at_the_next_turn_does_not_invent_a_break(self):
        fixture = (
            a_turn(RolloutFixture(self))
            .add(turn_start(at(110)))
            # Byte-identical to the Request above: the last Turn's usage, re-broadcast.
            .add(token_count(at(112), input_=80_000, cached=60_000))
            .add(token_count(at(115), input_=80_000, cached=13_000))
            .add(turn_end(at(120)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual([d["index"] for d in diagnoses], [2])

    def test_a_repeat_that_advanced_the_cumulative_total_is_a_real_request(self):
        """Matching per-request counts alone do not prove a replay: two genuine calls
        can bill the same tokens. The Session's cumulative total is what settles it —
        it only moves when an API call actually happened."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000, total=60_000))
            .add(token_count(at(20), input_=60_000, cached=40_000, total=120_000))
            .add(turn_end(at(25)))
        )

        session = fixture.analyzed()

        self.assertEqual(session["analysis"]["requests"], 2)

    def test_usage_emitted_twice_within_a_turn_does_not_invent_a_break(self):
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(10.5), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
        )

        session = fixture.analyzed()

        self.assertEqual(session["analysis"]["requests"], 2)
        self.assertEqual(parse_codex.explain_breaks(session), [])


class CacheWarmupTest(unittest.TestCase):
    def test_break_seconds_after_a_cold_start_is_diagnosed_as_cache_warmup(self):
        """The cold Request's cache write has not landed yet, so the next Request
        misses too. Blaming the idle gap twice would double-count one root cause."""
        fixture = (
            a_turn(RolloutFixture(self))
            .add(turn_start(at(6000)))
            .add(token_count(at(6010), input_=81_000, cached=5_500))
            .add(token_count(at(6020), input_=87_000, cached=13_000))
            .add(token_count(at(6030), input_=92_000, cached=87_000))
            .add(turn_end(at(6035)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(
            [(d["index"], d["cause"]) for d in diagnoses],
            [(2, parse_codex.CAUSE_TTL_EXPIRY), (3, parse_codex.CAUSE_CACHE_WARMUP)],
        )

    def test_break_following_a_cache_hit_is_not_a_warmup(self):
        """Warm-up only explains a miss that trails a *cold* Request."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(token_count(at(30), input_=90_000, cached=30_000))
            .add(turn_end(at(35)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertNotEqual(diagnoses[0]["cause"], parse_codex.CAUSE_CACHE_WARMUP)


class MidTurnBreakTest(unittest.TestCase):
    def test_partial_retention_mid_turn_is_diagnosed_as_a_history_change(self):
        """Half the *recoverable* prefix survived, so the cache was alive and the prompt
        itself diverged part-way through — history was truncated or rewritten inside the
        Turn. Retaining the Prefix Floor plus half the conversation is not cold."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            # The Session opens on the static header alone: 20k.
            .add(token_count(at(10), input_=30_000, cached=20_000))
            .add(token_count(at(20), input_=80_000, cached=30_000))
            # 50k is the floor plus half of the 60k recoverable prefix.
            .add(token_count(at(30), input_=90_000, cached=50_000))
            .add(turn_end(at(35)))
            # A resume comes back on that same head, corroborating it as the floor.
            .add(turn_start(at(3_600)))
            .add(token_count(at(3_625), input_=95_000, cached=20_000))
            .add(turn_end(at(3_630)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(
            [d["cause"] for d in diagnoses],
            [parse_codex.CAUSE_HISTORY_CHANGE, parse_codex.CAUSE_TTL_EXPIRY],
        )
        self.assertAlmostEqual(diagnoses[0]["retention"], 0.5, places=2)

    def test_a_cold_break_with_no_gap_and_no_context_change_stays_unknown(self):
        """Nothing in the log accounts for it; say so rather than inventing a cause."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(token_count(at(30), input_=90_000, cached=1_000))
            .add(turn_end(at(35)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_UNKNOWN)


class FindLiveSessionTest(unittest.TestCase):
    """Watch Mode follows the Live Session: the rollout being written to right now."""

    def test_the_live_session_is_the_most_recently_modified_rollout(self):
        sessions = temp_dir(self)
        stale = RolloutFixture(self, sessions, name="rollout-2026-03-20T09-00-00-stale.jsonl")
        a_turn(stale).write(modified=1_000_000)
        current = a_turn(
            RolloutFixture(self, sessions, name="rollout-2026-03-20T18-00-00-current.jsonl")
        ).write(modified=2_000_000)

        self.assertEqual(parse_codex.find_live_session(sessions), current)

    def test_a_subagent_rollout_touched_more_recently_is_not_the_live_session(self):
        """A subagent spawned mid-Turn writes last, but the Session you are sitting in
        front of is the one worth watching."""
        sessions = temp_dir(self)
        mine = a_turn(
            RolloutFixture(self, sessions, name="rollout-2026-03-20T18-00-00-mine.jsonl")
        ).write(modified=2_000_000)
        a_turn(
            RolloutFixture(
                self,
                sessions,
                name="rollout-2026-03-20T18-05-00-child.jsonl",
                thread_source="subagent",
            )
        ).write(modified=2_000_100)

        self.assertEqual(parse_codex.find_live_session(sessions), mine)


def a_costly_turn(fixture: RolloutFixture, input_: int, cached: int) -> RolloutFixture:
    """A Turn that opens with a Cache Break, re-billing `input_ - cached` tokens."""
    return (
        a_turn(fixture)
        .add(turn_start(at(110)))
        .add(token_count(at(115), input_=input_, cached=cached))
        .add(turn_end(at(120)))
    )


class WaterfallPayloadTest(unittest.TestCase):
    def test_the_live_session_is_pinned_first_and_the_rest_rank_by_rebilled(self):
        """Watch Mode wants the Session you are in on screen, whatever it has cost
        so far; the others still compete on Re-billed Tokens."""
        sessions = temp_dir(self)
        live = a_turn(RolloutFixture(self, sessions, name="rollout-a.jsonl", cwd="/tmp/live"))
        costly = a_costly_turn(
            RolloutFixture(self, sessions, name="rollout-b.jsonl", cwd="/tmp/costly"),
            input_=80_000,
            cached=13_000,
        )
        middling = a_costly_turn(
            RolloutFixture(self, sessions, name="rollout-c.jsonl", cwd="/tmp/middling"),
            input_=80_000,
            cached=50_000,
        )

        payload = parse_codex.waterfall_payload(
            [costly.analyzed(), live.analyzed(), middling.analyzed()], live=live.path
        )

        self.assertEqual([row["cwd"] for row in payload], ["live", "costly", "middling"])

    def test_a_row_keeps_its_id_when_the_ranking_moves_it(self):
        """Watch Mode rewrites the payload every few seconds and a Session can change
        rank as it accrues Re-billed Tokens. Rows carry a Session id so the viewer can
        hold its selection on the same Session rather than on a row number."""
        sessions = temp_dir(self)
        live = a_turn(RolloutFixture(self, sessions, name="rollout-a.jsonl", cwd="/tmp/live"))
        costly = a_costly_turn(
            RolloutFixture(self, sessions, name="rollout-b.jsonl", cwd="/tmp/costly"),
            input_=80_000,
            cached=13_000,
        )
        analyzed = [costly.analyzed(), live.analyzed()]

        pinned = parse_codex.waterfall_payload(analyzed, live=live.path)
        unpinned = parse_codex.waterfall_payload(analyzed)

        self.assertEqual(pinned[0]["id"], unpinned[1]["id"])
        self.assertEqual(pinned[1]["id"], unpinned[0]["id"])

    def test_only_the_live_session_is_flagged_live(self):
        """The Waterfall badges the Session it is tailing, so a break you are watching
        for is distinguishable from history. Without Watch Mode nothing is live."""
        sessions = temp_dir(self)
        live = a_turn(RolloutFixture(self, sessions, name="rollout-a.jsonl", cwd="/tmp/live"))
        other = a_turn(RolloutFixture(self, sessions, name="rollout-b.jsonl", cwd="/tmp/other"))
        analyzed = [other.analyzed(), live.analyzed()]

        pinned = parse_codex.waterfall_payload(analyzed, live=live.path)
        unpinned = parse_codex.waterfall_payload(analyzed)

        self.assertEqual([row.get("live", False) for row in pinned], [True, False])
        self.assertEqual([row.get("live", False) for row in unpinned], [False, False])


class WatchModeTest(unittest.TestCase):
    """Seam: `WatchMode.tick()` — one Watch Mode iteration in, the rows the Waterfall
    should render out, or None when nothing moved and the file need not be rewritten."""

    def test_a_session_seen_live_survives_a_switch_to_a_newer_one(self):
        """alpha opens too short to make the startup cut, then does real work while it
        is the Live Session. Once beta takes over, alpha must still be on the chart
        with everything it accrued: a Waterfall whose bars and totals roll *backward*
        is worse than one that never updated."""
        sessions = temp_dir(self)
        alpha = RolloutFixture(self, sessions, name="rollout-a.jsonl", cwd="/tmp/alpha")
        alpha.add(turn_start(at(0)), token_count(at(10), input_=60_000, cached=40_000))
        alpha.write(modified=2_000_000)
        watcher = parse_codex.WatchMode(sessions, min_requests=3, include_all=False)
        watcher.tick()

        alpha.add(
            token_count(at(20), input_=80_000, cached=60_000),
            turn_end(at(25)),
            turn_start(at(1_300)),
            token_count(at(1_310), input_=92_000, cached=6_000),
        ).write(modified=2_000_100)
        watcher.tick()

        a_turn(RolloutFixture(self, sessions, name="rollout-b.jsonl", cwd="/tmp/beta")).write(
            modified=2_000_500
        )
        rows = {row["cwd"]: row for row in watcher.tick() or []}

        self.assertEqual(len(rows["alpha"]["r"]), 3)
        self.assertEqual(rows["alpha"]["a"]["breaks"], 1)
        self.assertEqual(rows["alpha"]["a"]["rebilled_tokens"], 74_000)
        self.assertEqual([row["cwd"] for row in rows.values() if row["live"]], ["beta"])

    def test_a_tick_that_found_nothing_new_asks_for_no_rewrite(self):
        """The page re-renders whenever the data file changes, so a tick with nothing
        to report must not cause a rewrite."""
        sessions = temp_dir(self)
        a_turn(RolloutFixture(self, sessions, name="rollout-a.jsonl")).write(modified=2_000_000)
        watcher = parse_codex.WatchMode(sessions, min_requests=3, include_all=False)

        self.assertIsNotNone(watcher.tick())
        self.assertIsNone(watcher.tick())

    def test_a_rollout_caught_before_its_first_record_is_not_a_session_yet(self):
        """Codex creates the rollout file before writing to it, so a tick can catch it
        empty or mid-line. That is not a Session yet: wait for the next tick rather
        than taking Watch Mode down with it."""
        sessions = temp_dir(self)
        a_turn(RolloutFixture(self, sessions, name="rollout-a.jsonl", cwd="/tmp/alpha")).write(
            modified=2_000_000
        )
        watcher = parse_codex.WatchMode(sessions, min_requests=3, include_all=False)
        watcher.tick()

        # A newer rollout appears, but the opening record is still being written.
        partial = sessions / "rollout-b.jsonl"
        partial.write_text('{"timestamp":"2026-03-20T18:30:00Z","type":"session_me')
        os.utime(partial, (2_000_500, 2_000_500))

        rows = {row["cwd"]: row for row in watcher.tick() or []}

        self.assertEqual(len(rows["alpha"]["r"]), 2)
        self.assertEqual([row["cwd"] for row in rows.values() if row["live"]], [])

    def test_the_first_tick_renders_even_with_nothing_to_watch(self):
        """Watching an empty directory still has to render: skipping the first tick
        would leave whatever a previous `--web` run wrote on screen, and the stale
        corpus would read as live."""
        watcher = parse_codex.WatchMode(temp_dir(self), min_requests=3, include_all=False)

        self.assertEqual(watcher.tick(), [])


if __name__ == "__main__":
    unittest.main()
