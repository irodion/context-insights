"""Tests for Cache Break forensics (ticket 001).

Seam under test: `explain_breaks()` — an analyzed Session in, one diagnosis per
Cache Break out. Fixtures are synthetic Codex rollouts written to a temp file
and read back through the real adapter, so the tests exercise the public path
(`load_codex_session` -> `analyze` -> `explain_breaks`) rather than internals.
"""

import json
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


class RolloutFixture:
    """Builds a synthetic rollout-*.jsonl and loads it through the adapter."""

    def __init__(self, testcase: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "rollout-2026-03-20T18-00-00-fixture.jsonl"
        self.events: list[dict] = [
            event(
                at(0),
                "session_meta",
                {
                    "id": "019d0c8f-fixture",
                    "timestamp": at(0),
                    "cwd": "/tmp/proj",
                    "source": {"type": "user"},
                },
            )
        ]

    def add(self, *events: dict | list[dict]) -> "RolloutFixture":
        for e in events:
            self.events.extend(e if isinstance(e, list) else [e])
        return self

    def analyzed(self) -> dict:
        self.path.write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
        return parse_codex.analyze(parse_codex.load_codex_session(self.path))


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


class HistoryRewriteTest(unittest.TestCase):
    def test_a_cold_turn_opening_within_the_ttl_window_is_ttl_expiry_not_a_rewrite(self):
        """A Turn opening cold after minutes of idle is the prefix ageing out, not
        re-serialization: the provider keeps a prefix for only 5-10 minutes."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
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
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
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

    def test_a_new_turn_id_alone_is_not_a_turn_context_change(self):
        """`turn_id` is fresh on every Turn by definition, so it can never be a cause."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
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
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
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
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(turn_end(at(25)))
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
        """Part of the prefix survived, so the cache was alive and the prompt itself
        diverged part-way through — history was truncated or rewritten inside the Turn."""
        fixture = (
            RolloutFixture(self)
            .add(turn_start(at(0)))
            .add(token_count(at(10), input_=60_000, cached=40_000))
            .add(token_count(at(20), input_=80_000, cached=60_000))
            .add(token_count(at(30), input_=90_000, cached=40_000))
            .add(turn_end(at(35)))
        )

        diagnoses = parse_codex.explain_breaks(fixture.analyzed())

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["cause"], parse_codex.CAUSE_HISTORY_CHANGE)
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


if __name__ == "__main__":
    unittest.main()
