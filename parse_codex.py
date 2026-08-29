#!/usr/bin/env python3
"""Codex CLI rollout parser: normalize sessions/requests and detect cache breaks.

Vocabulary: see CONTEXT.md. Output feeds the future Waterfall visualization.

Usage:
  ./parse_codex.py                        # summary of all `user` sessions
  ./parse_codex.py --all                  # include subagent/other sessions
  ./parse_codex.py --session <file>       # per-request detail for one rollout
  ./parse_codex.py --json out.json        # dump normalized sessions as JSON
"""

import argparse
import collections
import fnmatch
import functools
import hashlib
import http.server
import json
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict

SESSIONS_DIR = Path.home() / ".codex" / "sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Watch Mode: how often the Live Session is re-read. A few seconds of lag is fine —
# the point is seeing a break within the Turn that caused it, not sub-second latency.
WATCH_INTERVAL_S = 3.0
WATCH_HOST = "127.0.0.1"  # local single-user tool: never bind a routable interface
WATCH_PORT = 8787
# The one Agent Source Watch Mode can follow. Its tail is Codex-shaped end to end — the
# `rollout-*.jsonl` glob, `load_codex_session()`, and `peek_thread_source()` reading an
# opening `session_meta` line, which no other source writes. Naming what *is* supported
# means a new adapter is refused rather than silently handed the Codex watcher; wiring a
# second one is ticket 002's remaining work, not a matter of listing it here.
WATCHABLE_SOURCE = "codex"

# Thresholds (heuristics, tune freely)
# Billing ratios measure against zero; Retention (below) measures above the Prefix
# Floor. Different denominators, so the two do not compose into a warm-break band.
BREAK_RATIO = 0.8  # cached < 80% of expected cache => cache break
COMPACTION_RATIO = 0.6  # input < 60% of previous input => compaction, not break
REPLAY_BURST_MS = 200  # subagent replay: consecutive events closer than this
# Idle seconds after which a cold prefix is read as expired rather than rewritten.
# Providers keep a prefix ~5-10 min; cold Turn openings in this corpus cluster at
# 5-10 min, so the low end is the honest cut — above it, expiry explains the miss.
TTL_GAP_S = 300
COLD_RETENTION = 0.25  # retention above the Prefix Floor below this => cold, not diverged
# Kept at 0.25 after the floor adjustment rather than inherited: re-read off the adjusted
# distribution, which is bimodal — 284 of 478 Breaks retain exactly nothing above the floor,
# and the density trough separating them from the 0.3-0.7 bulge spans 0.20-0.40.
WARMUP_GAP_S = 60  # a cold Request's cache write can still be in flight this long after
# Two cache rebuilds coming back this close to the same low value are agreeing on a
# re-cached head, provided they are not both Cache Breaks; one Request alone is just
# the deepest Break. The tolerance is the one
# ticket 013 measured the floor with (Claude Code matched its own first Request within
# 10% on 88 of 120 Breaks), not a fresh constant.
FLOOR_CORROBORATION = 0.10

# Idle-gap advisor: the ladder of gaps it tests, and the break rate at which resuming
# a Session stops paying off. The reported threshold is whichever rung the data picks.
IDLE_ADVICE_LADDER_S = (120, 300, 600, 1200, 3600)
IDLE_BREAK_RATE = 0.5
IDLE_ADVICE_MIN_SAMPLES = 20

# Cache Break causes, as reported by explain_breaks()
CAUSE_TURN_CONTEXT = "turn_context change"
CAUSE_TTL_EXPIRY = "TTL expiry"
CAUSE_CACHE_WARMUP = "cache warm-up"
CAUSE_HISTORY_REWRITE = "turn-boundary history rewrite"
CAUSE_HISTORY_CHANGE = "mid-turn history change"
CAUSE_UNKNOWN = "unknown"

# turn_context fields that change every Turn by design, so can never explain a break
TURN_CONTEXT_VOLATILE = {"turn_id"}
FINGERPRINT_SCALAR_LEN = 40  # longer values are digested rather than shown verbatim


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gap_seconds(earlier: str | None, later: str | None) -> float:
    """Seconds between two log timestamps; 0.0 when either is missing or unparseable."""
    if not earlier or not later:
        return 0.0
    try:
        return (parse_ts(later) - parse_ts(earlier)).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return 0.0


def turn_context_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    """Comparable form of a `turn_context`: short scalars verbatim, anything larger
    (developer instructions, sandbox policy) digested so sessions stay cheap to keep
    in memory and to dump. Volatile fields are dropped so they never look like a cause."""
    fingerprint: dict[str, Any] = {}
    for key, value in payload.items():
        if key in TURN_CONTEXT_VOLATILE:
            continue
        if (value is None or isinstance(value, str | int | float | bool)) and (
            len(str(value)) <= FINGERPRINT_SCALAR_LEN
        ):
            fingerprint[key] = value
        else:
            blob = json.dumps(value, sort_keys=True, default=str).encode()
            fingerprint[key] = "#" + hashlib.sha1(blob).hexdigest()[:8]
    return fingerprint


# The seam between an Agent Source and everything downstream: what an adapter must
# produce, and all that analysis, the Waterfall and the CLI are allowed to know. An
# adapter fills these fields from whatever its own source happens to record; nothing
# below this point may ask which agent produced them. Adding an Agent Source is
# writing one function that returns a `Session`, and it is the type checker rather
# than a reviewer that says whether it conforms.


class Request(TypedDict):
    """One API call (CONTEXT.md: Request), as every adapter must report it."""

    ts: str | None
    input: int  # the whole prompt: cached, newly written and fresh parts together
    cached: int
    cache_write: int
    output: int
    gap_s: float
    turn: int
    first_in_turn: bool
    announced_compaction: bool  # the source said so, rather than the ratio guessing
    ctx: int  # index into the Session's turn_contexts
    # Only some sources record these. `id` is what makes a Copied Request findable at
    # all, so a source that stamps its Requests with nothing cannot have one detected.
    id: NotRequired[str]
    total_input: NotRequired[int]  # Codex reports it; nothing downstream reads it yet
    context_window: NotRequired[int | None]  # likewise
    # Added after the adapter: `copied` by the corpus walk, the rest by analyze(),
    # which classifies Requests in place rather than building a parallel list.
    copied: NotRequired[bool]
    kind: NotRequired[str]
    expected_cache: NotRequired[int]
    rebilled: NotRequired[int]
    retention: NotRequired[float]


class Analysis(TypedDict):
    """What analyze() totals over a Session, counting its own Requests and not copies."""

    requests: int
    prefix_floor: int
    breaks: int
    compactions: int
    rebilled_tokens: int
    input_tokens: int
    cached_tokens: int
    hit_rate: float


class Session(TypedDict):
    """One Session file (CONTEXT.md: Session), normalized."""

    file: str
    agent_source: str
    replays_parent: bool  # whether its subagents open by re-sending the parent history
    session_id: str | None
    thread_source: str  # "user" or "subagent"
    cwd: str | None
    started: str | None
    model: str | None
    turn_contexts: list[dict[str, Any]]
    requests: list[Request]
    analysis: NotRequired[Analysis]


SessionLoader = Callable[[Path], Session | None]


def load_codex_session(path: Path) -> Session | None:
    """Codex adapter: rollout-*.jsonl -> normalized session dict."""
    meta: dict[str, Any] = {}
    model = None
    requests: list[Request] = []
    turn_contexts: list[dict[str, Any]] = []
    prev_usage: tuple[dict[str, Any], dict[str, Any]] | None = None
    turn = 0
    with open(path, errors="replace") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            ts = ev.get("timestamp")
            payload = ev.get("payload") or {}
            if t == "session_meta" and not meta:
                meta = payload
            elif t == "turn_context":
                model = payload.get("model") or model
                fingerprint = turn_context_fingerprint(payload)
                if not turn_contexts or turn_contexts[-1] != fingerprint:
                    turn_contexts.append(fingerprint)
            elif t == "event_msg" and payload.get("type") == "task_started":
                turn += 1
            elif t == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                last = info.get("last_token_usage")
                if not last:
                    continue
                # Codex re-emits a Request's usage without a new API call: twice within
                # a Turn, and again when the next Turn opens. Counting those invents Cache
                # Breaks. Matching per-request counts alone would not prove a replay —
                # two genuine calls can bill identically — so require the Session's
                # cumulative total to have stood still too, which only a replay does.
                total = info.get("total_token_usage") or {}
                if (last, total) == prev_usage:
                    continue
                prev_usage = (last, total)
                requests.append(
                    {
                        "ts": ev.get("timestamp"),
                        "input": last.get("input_tokens", 0),
                        "cached": last.get("cached_input_tokens", 0),
                        "cache_write": last.get("cache_write_input_tokens", 0),
                        "output": last.get("output_tokens", 0),
                        "total_input": total.get("input_tokens", 0),
                        "context_window": info.get("model_context_window"),
                        "gap_s": gap_seconds(requests[-1]["ts"] if requests else None, ts),
                        "turn": turn,
                        "first_in_turn": not requests or requests[-1]["turn"] != turn,
                        "ctx": len(turn_contexts) - 1,
                        "announced_compaction": False,  # Codex announces nothing
                    }
                )
    if not meta and not requests:
        return None
    return {
        "file": str(path),
        "agent_source": "codex",
        "replays_parent": True,
        "session_id": meta.get("id") or meta.get("session_id"),
        "thread_source": meta.get("thread_source") or "user",
        "cwd": meta.get("cwd"),
        "started": meta.get("timestamp"),
        "model": model,
        "turn_contexts": turn_contexts,
        "requests": requests,
    }


def claude_turn_context(record: dict[str, Any]) -> dict[str, Any]:
    """The prefix-bearing settings a Claude Code record carries, in the comparable form
    `turn_context_changes()` diffs.

    Claude Code has no turn_context object, so these two are chosen rather than
    inherited, and they are chosen on evidence: over the corpus `model` moved 13 times
    and broke the cache 11 (the server calls 8 of them `model_changed`), `effort` moved
    7 and broke it 5. The tempting third, `cwd`, moved 569 times for a 0.7% break rate —
    under the 0.99% base rate, so it is not in the prompt; `permissionMode` and
    `entrypoint` never moved at all."""
    message = record.get("message") or {}
    return turn_context_fingerprint({"model": message.get("model"), "effort": record.get("effort")})


def load_claude_session(path: Path) -> Session | None:
    """Claude Code adapter: <session-id>.jsonl -> normalized session dict.

    One `assistant` record per content block, so a Request is a group of records
    sharing a `requestId` (see Content-Block Record in CONTEXT.md). Every record of a
    group repeats the same usage; the last is taken, which is the one measured to
    carry the final output count."""
    groups: dict[str, dict[str, Any]] = {}
    turn_contexts: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    prompt_id = None
    turn = 0
    sidechain = False
    agent_id = None
    compacted = False
    with open(path, errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("type")
            sidechain = sidechain or bool(rec.get("isSidechain"))
            agent_id = agent_id or rec.get("agentId")
            if kind == "system" and rec.get("subtype") == "compact_boundary":
                # Claude Code announces a Compaction; the next Request is the compacted
                # prompt, whatever the size of the drop turns out to be.
                compacted = True
            elif kind == "user":
                # Only `user` records carry `promptId`, and a tool result repeats the
                # id of the prompt it is answering, so the agentic loop stays in one
                # Turn. A new id is a new Turn.
                pid = rec.get("promptId")
                if pid and pid != prompt_id:
                    prompt_id, turn = pid, turn + 1
            elif kind == "assistant":
                if rec.get("isApiErrorMessage") or rec.get("apiErrorStatus"):
                    continue  # a Rejected Call is not a Request: it was billed nothing
                if not meta:
                    meta = rec
                rid = rec.get("requestId")
                if not rid:
                    continue
                if rid not in groups:
                    context = claude_turn_context(rec)
                    if not turn_contexts or turn_contexts[-1] != context:
                        turn_contexts.append(context)
                    groups[rid] = {
                        "turn": turn,
                        "compaction": compacted,
                        "ctx": len(turn_contexts) - 1,
                    }
                    compacted = False
                # Every record of the group repeats the usage; the last is the one
                # measured to carry the final output count.
                groups[rid]["rec"] = rec
    requests: list[Request] = []
    for rid, group in groups.items():
        rec = group["rec"]
        usage = (rec.get("message") or {}).get("usage") or {}
        cached = usage.get("cache_read_input_tokens") or 0
        cache_write = usage.get("cache_creation_input_tokens") or 0
        ts = rec.get("timestamp")
        requests.append(
            {
                "ts": ts,
                # The provider bills a prompt in three parts; their sum is the prompt.
                "input": (usage.get("input_tokens") or 0) + cached + cache_write,
                "cached": cached,
                "cache_write": cache_write,
                "output": usage.get("output_tokens") or 0,
                "gap_s": gap_seconds(requests[-1]["ts"] if requests else None, ts),
                "turn": group["turn"],
                "first_in_turn": not requests or requests[-1]["turn"] != group["turn"],
                "announced_compaction": group["compaction"],
                "ctx": group["ctx"],
                "id": rid,
            }
        )
    if not requests:
        return None
    return {
        "file": str(path),
        "agent_source": "claude-code",
        # Measured over 318 sidechain Sessions: median first-Request cache_read is 0,
        # 172 start at exactly zero. A Claude Code subagent opens cold, with nothing
        # replayed to strip.
        "replays_parent": False,
        # A sidechain records the *parent's* sessionId, so a subagent has to be named
        # by its own `agentId` or every child of one Session shares an identity.
        "session_id": agent_id or meta.get("sessionId") or Path(path).stem,
        "thread_source": "subagent" if sidechain else "user",
        "cwd": meta.get("cwd"),
        "started": requests[0]["ts"],
        "model": (meta.get("message") or {}).get("model"),
        "turn_contexts": turn_contexts,
        "requests": requests,
    }


# Each Agent Source: where its Sessions live, what its files are called, and the
# adapter that reads one. Claude Code's `*.jsonl` matches anything, so it stays last —
# a source with a distinctive name must be listed above it to be recognized.
ADAPTERS: dict[str, tuple[Path, str, SessionLoader]] = {
    "codex": (SESSIONS_DIR, "rollout-*.jsonl", load_codex_session),
    "claude-code": (CLAUDE_PROJECTS_DIR, "*.jsonl", load_claude_session),
}


def source_of(path: Path) -> str | None:
    """The Agent Source whose file pattern this file's name matches, or None."""
    for source, (_, pattern, _) in ADAPTERS.items():
        if fnmatch.fnmatch(path.name, pattern):
            return source
    return None


def load_session_file(path: Path) -> Session | None:
    """One Session file through the adapter that recognizes its name. The Requests are
    as the file records them, copies included: see `owned_session()` for the other
    reading."""
    source = source_of(path)
    return ADAPTERS[source][2](path) if source else None


def strip_replay(session: Session) -> list[Request]:
    """Subagent rollouts replay parent history as a leading burst of
    token_count events with near-identical timestamps. Drop that prefix,
    keeping the last replayed event as the baseline for the child's own turns.

    Only for an Agent Source that replays: a source whose subagents open cold has no
    prefix to strip, and the burst window would eventually eat a fast pair of its own
    Requests — including the cold start the Prefix Floor is measured from."""
    reqs = session["requests"]
    if not session["replays_parent"] or session["thread_source"] != "subagent":
        return reqs
    if len(reqs) < 2:
        return reqs
    i = 0
    while i + 1 < len(reqs):
        try:
            here = parse_ts(reqs[i]["ts"] or "")
            following = parse_ts(reqs[i + 1]["ts"] or "")
        except (TypeError, ValueError):
            break
        delta = (following - here).total_seconds() * 1000
        if delta > REPLAY_BURST_MS:
            break
        i += 1
    return reqs[i:] if i else reqs


def prefix_floor(requests: list[Request]) -> int:
    """The Session's Prefix Floor (see CONTEXT.md): the smallest Cached Input that two
    cache rebuilds agree on, or zero when nothing corroborates one.

    Only a Request that (re)built the prefix from the head is evidence about the head:
    the first Request, every Cache Break, and every Compaction. A hit is the one kind
    that continues an existing prefix, and its Cached Input is the whole previous
    prompt — which bounds the head from *above*, never locates it. Corroborating with
    hits therefore over-states the floor. (On this corpus it changes no Break Cause:
    admitting hits finds a floor on 192 Sessions rather than 141, with identical
    classifications. It is excluded for the direction of the error, not for a count.)

    Corroboration is what makes the value a floor at all. The smallest Cached Input is
    the re-cached head *if the cache ever came back head-only*; on a Session where it
    never does, the smallest value is simply the deepest Cache Break, and subtracting
    it would force that Break's own Retention to zero by construction.

    **Cache Breaks cannot corroborate each other.** A Break's Cached Input is whatever
    survived a divergence, so it can be any fraction of the prefix; two Breaks landing
    near each other agree that they diverged at similar points, never that either came
    back on the head. The agreeing group must therefore contain a Request that is not a
    Break — the first Request, whose prompt is the head plus one message, or a
    Compaction, which rebuilds the prompt deliberately rather than losing it. That is
    evidence from outside the Breaks being classified. (A Compaction's Cached Input can
    still carry summary text, so the floor it corroborates is an estimate, not a
    reading; taking the *smallest* agreeing value bounds how far it can be wrong.)

    Only the *smallest* rebuild is eligible, and a rebuild that returned nothing counts
    as one — a cold start is the smallest rebuild a Session can have, and dropping it
    would let two partial Breaks above it become the bottom and invent a floor over the
    conversation they kept. Climbing to the next pair when the smallest is
    uncorroborated looks like it recovers a floor from a Session whose deepest Break
    came back under the head, but it cannot be told apart from two partial Breaks that
    merely landed near each other well above the head — the same data shape, opposite
    answers. Refusing to climb under-states the floor on the first shape and never
    over-states it on the second, which is the safe direction: an over-stated floor
    invents coldness on a Break that really did keep conversation. Uncorroborated, the
    floor is zero and Retention stays unadjusted — the honest reading when no Request
    ever showed the head.

    The minimum is preferred over the Session's *first* Cached Input, which reads as
    the more literal cold-start prefix but is only that when the Session began cold —
    on resumed Sessions it carries conversation too, and over the corpus it exceeds a
    later Break's Cached Input on 85 of 478 Breaks and its whole Expected Cache on 9.

    On a Session still being written, the floor is provisional: a later, colder rebuild
    can lower it, which lowers every Retention already reported for that Session.
    """
    rebuilds = sorted(
        (r["cached"], r["kind"]) for r in requests if r["kind"] not in ("hit", "copied")
    )
    if not rebuilds:
        return 0
    lowest = rebuilds[0][0]
    agreeing = [kind for cached, kind in rebuilds if cached <= lowest * (1 + FLOOR_CORROBORATION)]
    if len(agreeing) < 2 or all(kind == "break" for kind in agreeing):
        return 0
    return lowest


def analyze(session: Session) -> Session:
    """Classify each request: first / hit / break / compaction, or `copied` for a
    Copied Request kept only as the next Request's Expected Cache. Adds per-request
    `kind`, `expected_cache`, `rebilled`, `retention` and session-level aggregates,
    which count this Session's own Requests and not the copies."""
    reqs = strip_replay(session)
    prev = None
    total_input = total_cached = rebilled = breaks = compactions = 0
    own_requests = 0
    for r in reqs:
        if r.get("copied"):
            # Another Session's Request, kept only so the Request behind it has an
            # Expected Cache. Not this Session's spend, so it is neither classified
            # against this Session's history nor billed to it.
            r["kind"] = "copied"
            r["expected_cache"] = 0
            r["rebilled"] = 0
            prev = r
            continue
        own_requests += 1
        if prev is None:
            r["kind"] = "first"
            r["expected_cache"] = 0
            r["rebilled"] = 0
        else:
            expected = prev["input"]
            r["expected_cache"] = expected
            if r["announced_compaction"] or r["input"] < COMPACTION_RATIO * prev["input"]:
                r["kind"] = "compaction"
                r["rebilled"] = 0
                compactions += 1
            elif r["cached"] < BREAK_RATIO * expected:
                r["kind"] = "break"
                r["rebilled"] = max(0, expected - r["cached"])
                rebilled += r["rebilled"]
                breaks += 1
            else:
                r["kind"] = "hit"
                r["rebilled"] = 0
        total_input += r["input"]
        total_cached += r["cached"]
        prev = r
    # Needs `kind` from the loop above: only cache rebuilds are evidence about the head.
    floor = prefix_floor(reqs)
    for r in reqs:
        recoverable = r["expected_cache"] - floor
        r["retention"] = max(0.0, (r["cached"] - floor) / recoverable) if recoverable > 0 else 0.0
    session["analysis"] = {
        "requests": own_requests,
        "prefix_floor": floor,
        "breaks": breaks,
        "compactions": compactions,
        "rebilled_tokens": rebilled,
        "input_tokens": total_input,
        "cached_tokens": total_cached,
        "hit_rate": total_cached / total_input if total_input else 0.0,
    }
    session["requests"] = reqs
    return session


def ran_cold(request: Request | None) -> bool:
    """True when this Request was itself a Cache Break that kept almost nothing —
    the cache was empty for it, rather than merely diverging part-way through."""
    if request is None or request.get("kind") != "break":
        return False
    return request["retention"] < COLD_RETENTION


def turn_context_changes(
    session: Session, previous: Request | None, request: Request
) -> list[tuple[str, Any, Any]]:
    """Fields whose value differs between the turn_context of `previous` and of
    `request`. Empty when nothing changed, or when either context is unknown."""
    contexts = session.get("turn_contexts") or []
    if previous is None:
        return []
    before_idx, after_idx = previous.get("ctx", -1), request.get("ctx", -1)
    if before_idx == after_idx or not (0 <= before_idx < len(contexts)):
        return []
    if not 0 <= after_idx < len(contexts):
        return []
    before, after = contexts[before_idx], contexts[after_idx]
    return [
        (key, before.get(key), after.get(key))
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


def explain_breaks(session: Session) -> list[dict[str, Any]]:
    """Diagnose every Cache Break in an analyzed session.

    Returns one dict per break: index, cause, gap_s, retention, rebilled, detail.
    """
    diagnoses = []
    reqs = session["requests"]
    for i, r in enumerate(reqs):
        if r["kind"] != "break":
            continue
        retention = r["retention"]
        gap = r.get("gap_s", 0.0)
        previous = reqs[i - 1] if i else None
        ctx_changes = turn_context_changes(session, previous, r)
        # A resume that also moved `current_date` or a sandbox setting is still a
        # resume: the expired prefix is the better explanation, so TTL goes first.
        # What else moved is named in the detail rather than lost.
        if gap >= TTL_GAP_S and retention < COLD_RETENTION:
            cause = CAUSE_TTL_EXPIRY
            detail = (
                f"{fmt_duration(gap)} idle before this Request; the cached prefix "
                f"had expired, so the whole prompt was re-billed"
            )
            if ctx_changes:
                moved = ", ".join(key for key, _, _ in ctx_changes)
                detail += f" ({moved} also changed)"
        elif ctx_changes:
            cause = CAUSE_TURN_CONTEXT
            detail = "changed between Turns: " + ", ".join(
                f"{key} {before} -> {after}" for key, before, after in ctx_changes
            )
        elif gap <= WARMUP_GAP_S and ran_cold(previous):
            cause = CAUSE_CACHE_WARMUP
            detail = (
                f"{fmt_duration(gap)} after a cold Request, whose cache write "
                f"had not landed yet; the same idle gap is billed twice"
            )
        elif r.get("first_in_turn"):
            cause = CAUSE_HISTORY_REWRITE
            detail = (
                f"first Request of a new Turn after only {fmt_duration(gap)} idle; history was "
                f"re-serialized and {1 - retention:.0%} of the recoverable prefix diverged"
            )
        elif retention >= COLD_RETENTION:
            cause = CAUSE_HISTORY_CHANGE
            detail = (
                f"the cache was still warm ({retention:.0%} of the recoverable prefix survived) "
                "but the prompt diverged part-way through, mid-Turn"
            )
        else:
            cause = CAUSE_UNKNOWN
            detail = (
                f"cold cache with no idle gap and no turn_context change; "
                f"kept {retention:.0%} of the recoverable prefix"
            )
        diagnoses.append(
            {
                "index": i,
                "cause": cause,
                "gap_s": gap,
                "retention": retention,
                "rebilled": r["rebilled"],
                "detail": detail,
            }
        )
    return diagnoses


def idle_gap_advice(sessions: list[Session]) -> dict[str, Any] | None:
    """Correlate idle gap with Cache Break rate across sessions and derive the gap
    beyond which resuming a Session stops being worth it. The threshold comes from
    the observed data, not from a constant: it is the shortest gap on the ladder at
    which at least IDLE_BREAK_RATE of resumed Requests broke the cache."""
    graded = [
        (r.get("gap_s", 0.0), r["kind"] == "break", r["rebilled"])
        for s in sessions
        for r in s["requests"]
        if r["kind"] in ("break", "hit")
    ]
    for threshold in IDLE_ADVICE_LADDER_S:
        beyond = [g for g in graded if g[0] >= threshold]
        if len(beyond) < IDLE_ADVICE_MIN_SAMPLES:
            continue
        breaks = [g for g in beyond if g[1]]
        if len(breaks) / len(beyond) >= IDLE_BREAK_RATE:
            return {
                "threshold_s": threshold,
                "requests": len(beyond),
                "breaks": len(breaks),
                "break_rate": len(breaks) / len(beyond),
                "rebilled": sum(g[2] for g in breaks),
            }
    return None


KIND_CODE = {"first": 0, "hit": 1, "break": 2, "compaction": 3, "copied": 4}


def session_key(session: Session) -> str:
    """Stable identity for a Session across rewrites: the viewer holds its selection
    by this rather than by row number, and Watch Mode uses it to recognize a Session
    it has already seen."""
    return session["session_id"] or session["file"]


def waterfall_payload(sessions: list[Session], live: Path | None = None) -> list[dict[str, Any]]:
    """The rows waterfall.html renders: Sessions ranked by Re-billed Tokens, with
    the Live Session — the one Watch Mode is following — pinned first."""
    live_file = str(live) if live else None
    ranked = sorted(
        sessions,
        key=lambda s: (s["file"] != live_file, -s["analysis"]["rebilled_tokens"]),
    )
    return [
        {
            "id": session_key(s),
            "date": (s["started"] or "")[:10],
            "model": s["model"],
            "cwd": ((s["cwd"] or "").rstrip("/").split("/")[-1]) or s["cwd"],
            "live": s["file"] == live_file,
            "a": s["analysis"],
            "r": [
                [
                    r["input"],
                    r["cached"],
                    r["rebilled"],
                    KIND_CODE[r["kind"]],
                    (r["ts"] or "")[11:16],
                ]
                for r in s["requests"]
            ],
        }
        for s in ranked
    ]


def write_waterfall_data(payload: list[dict[str, Any]]) -> Path:
    """Write waterfall_data.js next to waterfall.html. Returns the path. The write is
    atomic: Watch Mode rewrites this file while the page is fetching it."""
    out = Path(__file__).parent / "waterfall_data.js"
    tmp = out.with_suffix(".js.tmp")
    tmp.write_text(
        "// generated by parse_codex.py --web/--watch; regenerate, don't edit\n"
        "const SESSIONS = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    )
    tmp.replace(out)
    return out


def drop_copied_requests(requests: list[Request], seen: set[str]) -> list[Request]:
    """This Session's Requests, with the Copied ones removed — except a copy that one of
    its own Requests follows, which stays behind as that Request's baseline.

    A Copied Request is another Session's spend but this Session's history: the next
    prompt is built on top of it. Removed outright, the Request behind it inherits an
    older, smaller prompt as its Expected Cache, and a Cache Break silently becomes a
    hit. The baseline that stays is marked `copied`, because it is context and not this
    Session's Request: classifying it would measure it against a history it is no longer
    part of, which invents a Cache Break neither Session recorded."""
    kept: list[Request] = []
    for i, r in enumerate(requests):
        own = r.get("id") not in seen
        follower_is_own = i + 1 < len(requests) and requests[i + 1].get("id") not in seen
        if own:
            kept.append(r)
        elif follower_is_own:
            kept.append({**r, "copied": True})
    return kept


def load_sessions(
    sessions_dir: Path,
    min_requests: int,
    include_all: bool,
    source: str,
    seen: set[str],
) -> list[Session]:
    """Every Session file under `sessions_dir`, normalized and analyzed. Sessions too
    short to say anything are dropped, as are subagent ones unless `include_all`.

    `seen` carries request ids across files: a Request already met in an earlier
    Session is a Copied Request and belongs to that Session, not to this one."""
    _, pattern, load = ADAPTERS[source]
    loaded = [s for s in map(load, sorted(sessions_dir.rglob(pattern))) if s]
    # Oldest first, so a Copied Request is kept by the Session that made it rather than
    # by whichever file sorts earlier: a fork inherits history, so the Session it forked
    # from started before it. A fork copies record timestamps verbatim (80 of 80 shared
    # Requests here), so one inheriting from its parent's *first* Request would tie and
    # fall back to path order. None does — 0 of 529 transcripts share a `started` — and
    # a tie is undecidable anyway: the two files would share their whole leading block,
    # and the format records nothing that says which of them placed the calls.
    loaded.sort(key=lambda s: s["started"] or "")
    sessions = []
    for s in loaded:
        s["requests"] = drop_copied_requests(s["requests"], seen)
        seen.update(r["id"] for r in s["requests"] if r.get("id"))
        if len(s["requests"]) < min_requests:
            continue
        if not include_all and s["thread_source"] != "user":
            continue
        sessions.append(analyze(s))
    return sessions


def load_corpus(
    sources: list[str],
    min_requests: int,
    include_all: bool,
    roots: dict[str, Path],
) -> list[Session]:
    """Every Session of every named Agent Source, with one request-id set spanning the
    walk so a Copied Request is counted once, in the first Session that holds it."""
    seen: set[str] = set()
    sessions: list[Session] = []
    for source in sources:
        root = roots.get(source) or ADAPTERS[source][0]
        if not root.exists():
            continue
        sessions.extend(load_sessions(root, min_requests, include_all, source, seen))
    return sessions


def owned_session(path: Path, root: Path) -> Session | None:
    """One Session file, analyzed as the corpus analyzes it — the single-file answer
    that agrees with what `--web` reports for the same Session.

    A Copied Request is recorded in this file but was billed to another Session, and
    no single file can say which: that needs every Session of the same Agent Source,
    walked oldest first. So `root` is walked exactly as the corpus walk walks it and
    the requested Session is picked out of the result. Reading the file alone counts
    the copies as this Session's own — 80 Requests, a 5% over-count, on one transcript
    of this corpus.

    None when the file is not under `root`, or holds no Session at all; the caller
    then has to say that the figures it falls back to are per-file."""
    source = source_of(path)
    if source is None:
        return None
    target = path.resolve()
    # `min_requests` and `include_all` filter what comes back, never what enters the
    # ownership set, so ownership is settled here identically to the corpus walk.
    for session in load_sessions(root, 0, True, source, set()):
        if Path(session["file"]).resolve() == target:
            return session
    return None


def peek_thread_source(path: Path) -> str:
    """The Thread Source of a rollout, read from its opening `session_meta` line.
    Watch Mode asks this of several files every few seconds, so it must not pay for
    a full parse; Codex writes `session_meta` first, and anything else reads as
    `user`, matching load_codex_session()'s default."""
    try:
        with open(path, errors="replace") as f:
            ev = json.loads(f.readline())
    except (OSError, json.JSONDecodeError):
        return "user"
    if ev.get("type") != "session_meta":
        return "user"
    return (ev.get("payload") or {}).get("thread_source") or "user"


def find_live_session(sessions_dir: Path) -> Path | None:
    """The Live Session: the newest-modified rollout you are sitting in front of.
    Subagent rollouts are skipped — a child spawned mid-Turn writes last, but it is
    not the Session being worked in."""
    pattern = ADAPTERS["codex"][1]
    rollouts = sorted(sessions_dir.rglob(pattern), key=lambda p: -p.stat().st_mtime)
    for path in rollouts:
        if peek_thread_source(path) == "user":
            return path
    return None


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static files without the per-request logging, which would bury the watch output."""

    def log_message(self, format: str, *args: Any) -> None:
        pass


def serve_waterfall(directory: Path, port: int) -> tuple[http.server.HTTPServer, str]:
    """Serve `directory` on localhost from a daemon thread. Returns the server (so the
    caller can shut it down) and the URL of the Waterfall page."""
    handler = functools.partial(QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer((WATCH_HOST, port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    bound_port = httpd.socket.getsockname()[1]
    return httpd, f"http://{WATCH_HOST}:{bound_port}/waterfall.html"


class WatchMode:
    """The state Watch Mode carries between ticks: every Session it has seen, newest
    state per Session.

    The corpus is parsed once, at construction; a tick re-reads only the Live Session,
    so it costs one file read. Sessions are held by id and the latest state wins, so a
    Session keeps everything it accrued while live once a newer one takes over —
    including one that was too short to make the startup cut. Rebuilding from a frozen
    startup snapshot instead would roll bars and totals backward on every switch.
    """

    def __init__(self, sessions_dir: Path, min_requests: int, include_all: bool) -> None:
        self.sessions_dir = sessions_dir
        self.seen = {
            session_key(s): s
            for s in load_sessions(sessions_dir, min_requests, include_all, "codex", set())
        }
        self.live: Path | None = None
        self._signal: tuple[str, Analysis] | None = None
        self._ticked = False

    def tick(self) -> list[dict[str, Any]] | None:
        """One iteration: re-read the Live Session and fold it into what we have seen.
        Returns the rows to render, or None when nothing moved since the last tick."""
        self.live = find_live_session(self.sessions_dir)
        # Codex creates the rollout before writing to it, so a tick can catch it empty
        # or mid-line and the adapter hands back nothing. That is not a Session yet —
        # leave the Waterfall as it stands and look again next tick.
        loaded = load_codex_session(self.live) if self.live else None
        session = analyze(loaded) if loaded else None
        # Only the Live Session can have moved, so its totals are the whole change
        # signal; the payload is rebuilt only when they actually move. The first tick
        # always renders, so watching an empty directory clears any stale data file.
        signal = (str(self.live), session["analysis"]) if session else None
        if self._ticked and signal == self._signal:
            return None
        self._ticked, self._signal = True, signal
        if session:
            self.seen[session_key(session)] = session
        return waterfall_payload(list(self.seen.values()), live=self.live)


def watch(sessions_dir: Path, port: int, min_requests: int, include_all: bool) -> None:
    """Follow the Live Session and rebuild the Waterfall while you work."""
    watcher = WatchMode(sessions_dir, min_requests, include_all)
    print(f"parsed {len(watcher.seen)} sessions from {sessions_dir}", file=sys.stderr)

    httpd, url = serve_waterfall(Path(__file__).parent, port)
    print(url, flush=True)
    print("watching for cache breaks — Ctrl-C to stop", file=sys.stderr, flush=True)

    followed: Path | None = None
    try:
        while True:
            rows = watcher.tick()
            if watcher.live != followed:
                name = watcher.live.name if watcher.live else "(no session yet)"
                print(f"following {name}", file=sys.stderr, flush=True)
                followed = watcher.live
            if rows is not None:
                write_waterfall_data(rows)
            time.sleep(WATCH_INTERVAL_S)
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        httpd.shutdown()
        httpd.server_close()


def fmt_duration(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.0f}m"
    return f"{seconds:.0f}s"


def fmt_tokens(n: float) -> str:
    return (
        f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.0f}k" if n >= 1000 else str(n)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source",
        choices=[*ADAPTERS, "all"],
        default="all",
        help="which Agent Source to read (default: every adapter present)",
    )
    ap.add_argument(
        "--dir",
        help="read one source from here instead of its usual directory; with --session "
        "or --explain, the root Request ownership is settled against",
    )
    ap.add_argument("--all", action="store_true", help="include subagent/other sessions")
    ap.add_argument("--session", help="analyze a single rollout file in detail")
    ap.add_argument("--explain", help="diagnose what invalidated the cache in one rollout file")
    ap.add_argument("--request", type=int, help="with --explain, limit to one request index")
    ap.add_argument("--json", help="write normalized+analyzed sessions to this file")
    ap.add_argument(
        "--web", action="store_true", help="write waterfall_data.js next to waterfall.html"
    )
    ap.add_argument(
        "--watch", action="store_true", help="follow the live session and serve the waterfall"
    )
    ap.add_argument("--port", type=int, default=WATCH_PORT, help="port for --watch")
    ap.add_argument("--min-requests", type=int, default=3)
    args = ap.parse_args()
    if args.watch:
        if args.source not in (WATCHABLE_SOURCE, "all"):
            ap.error(
                f"watch mode follows a {WATCHABLE_SOURCE} Session, and --source "
                f"{args.source} is not one; read it with --web instead"
            )
        watch(
            Path(args.dir) if args.dir else ADAPTERS[WATCHABLE_SOURCE][0],
            port=args.port,
            min_requests=args.min_requests,
            include_all=args.all,
        )
        return

    def analyzed_file(arg: str) -> Session:
        """One named Session file, with its Copied Requests attributed to whichever
        Session paid for them, so that these commands and the Waterfall report the
        same Session the same way."""
        path = Path(arg)
        source = source_of(path)
        if source is None:
            ap.error(f"{arg}: no adapter recognizes this file name")
        root = Path(args.dir) if args.dir else ADAPTERS[source][0]
        owned = owned_session(path, root)
        if owned is not None:
            return owned
        loaded = load_session_file(path)
        if loaded is None:
            ap.error(f"{arg}: no Requests found — is it a Session file?")
        print(
            f"note: {path} is not under {root}, so a Copied Request cannot be told from "
            "this Session's own; the figures below count every Request in the file",
            file=sys.stderr,
        )
        return analyze(loaded)

    if args.explain:
        s = analyzed_file(args.explain)
        a = s["analysis"]
        diagnoses = explain_breaks(s)
        if args.request is not None:
            diagnoses = [d for d in diagnoses if d["index"] == args.request]
        print(f"{s['session_id']}  {s['model'] or '?'}  {s['thread_source']}  {s['cwd']}")
        floor_note = (
            f"above a {fmt_tokens(a['prefix_floor'])} prefix floor"
            if a["prefix_floor"]
            else "against zero — no two cache rebuilds agreed on a prefix floor"
        )
        print(
            f"{a['breaks']} cache breaks over {a['requests']} requests, "
            f"{fmt_tokens(a['rebilled_tokens'])} tokens re-billed; "
            f"retention is measured {floor_note}"
        )
        if not diagnoses:
            print("\nno cache breaks to explain")
            return
        for d in diagnoses:
            print(
                f"\n{d['index']:>4}  {d['cause']}  "
                f"(rebilled {fmt_tokens(d['rebilled'])}, {fmt_duration(d['gap_s'])} since "
                f"the previous request, {d['retention']:.0%} of the recoverable prefix kept)"
            )
            print(f"      {d['detail']}")
        by_cause = collections.Counter[str]()
        for d in diagnoses:
            by_cause[d["cause"]] += d["rebilled"]
        print("\nre-billed by cause:")
        for cause, cost in by_cause.most_common():
            print(f"  {fmt_tokens(cost):>7}  {cause}")
        return

    if args.session:
        s = analyzed_file(args.session)
        a = s["analysis"]
        print(f"{s['session_id']}  {s['model'] or '?'}  {s['thread_source']}  {s['cwd']}")
        print(
            f"requests={a['requests']} breaks={a['breaks']} compactions={a['compactions']} "
            f"hit_rate={a['hit_rate']:.0%} rebilled={fmt_tokens(a['rebilled_tokens'])}"
        )
        for i, r in enumerate(s["requests"]):
            mark = {"first": " ", "hit": " ", "break": "!", "compaction": "~", "copied": "="}[
                r["kind"]
            ]
            bar_n = min(60, r["input"] // 5000)
            cached_n = min(bar_n, int(bar_n * (r["cached"] / r["input"])) if r["input"] else 0)
            bar = "█" * cached_n + "░" * (bar_n - cached_n)
            print(
                f"{i:3d} {mark} {r['kind']:<10} in={fmt_tokens(r['input']):>7} "
                f"cached={fmt_tokens(r['cached']):>7} "
                f"rebilled={fmt_tokens(r['rebilled']):>7} {bar}"
            )
        return

    sources = list(ADAPTERS) if args.source == "all" else [args.source]
    if args.dir and args.source == "all":
        ap.error("--dir names the directory of one source; pass --source too")
    roots = {args.source: Path(args.dir)} if args.dir else {}
    sessions = load_corpus(sources, args.min_requests, args.all, roots)

    if args.web:
        compact = waterfall_payload(sessions)
        out = write_waterfall_data(compact)
        print(f"wrote {len(compact)} sessions to {out}", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(json.dumps(sessions, indent=1))
        print(f"wrote {len(sessions)} sessions to {args.json}", file=sys.stderr)

    tot = {"input": 0, "cached": 0, "rebilled": 0, "breaks": 0, "requests": 0}
    rows: list[Session] = []
    for s in sessions:
        a = s["analysis"]
        tot["input"] += a["input_tokens"]
        tot["cached"] += a["cached_tokens"]
        tot["rebilled"] += a["rebilled_tokens"]
        tot["breaks"] += a["breaks"]
        tot["requests"] += a["requests"]
        rows.append(s)
    rows.sort(key=lambda s: -s["analysis"]["rebilled_tokens"])

    print(f"{'date':<12} {'model':<16} {'reqs':>5} {'breaks':>6} {'hit%':>5} {'rebilled':>9}  cwd")
    for s in rows[:25]:
        a = s["analysis"]
        date = (s["started"] or "")[:10]
        cwd = (s["cwd"] or "").replace(str(Path.home()), "~")
        print(
            f"{date:<12} {(s['model'] or '?'):<16} {a['requests']:>5} {a['breaks']:>6} "
            f"{a['hit_rate']:>5.0%} {fmt_tokens(a['rebilled_tokens']):>9}  {cwd[-40:]}"
        )
    if tot["input"]:
        print(
            f"\n{len(rows)} sessions, {tot['requests']} requests, "
            f"overall hit rate {tot['cached'] / tot['input']:.0%}, "
            f"{tot['breaks']} cache breaks, {fmt_tokens(tot['rebilled'])} tokens re-billed"
        )
    advice = idle_gap_advice(sessions)
    if advice:
        print(
            f"idle advisor: requests resumed after >{fmt_duration(advice['threshold_s'])} idle "
            f"broke the cache {advice['break_rate']:.0%} of the time "
            f"({advice['breaks']}/{advice['requests']}), costing "
            f"{fmt_tokens(advice['rebilled'])} re-billed tokens — past that gap the cached "
            f"prefix is usually already gone, so resuming re-pays for the whole context"
        )


if __name__ == "__main__":
    main()
