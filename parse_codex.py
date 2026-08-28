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
import functools
import hashlib
import http.server
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# Watch Mode: how often the Live Session is re-read. A few seconds of lag is fine —
# the point is seeing a break within the Turn that caused it, not sub-second latency.
WATCH_INTERVAL_S = 3.0
WATCH_HOST = "127.0.0.1"  # local single-user tool: never bind a routable interface
WATCH_PORT = 8787

# Thresholds (heuristics, tune freely)
BREAK_RATIO = 0.8  # cached < 80% of expected cache => cache break
COMPACTION_RATIO = 0.6  # input < 60% of previous input => compaction, not break
REPLAY_BURST_MS = 200  # subagent replay: consecutive events closer than this
# Idle seconds after which a cold prefix is read as expired rather than rewritten.
# Providers keep a prefix ~5-10 min; cold Turn openings in this corpus cluster at
# 5-10 min, so the low end is the honest cut — above it, expiry explains the miss.
TTL_GAP_S = 300
COLD_RETENTION = 0.25  # cached < 25% of expected cache => the cache went cold, not diverged
WARMUP_GAP_S = 60  # a cold Request's cache write can still be in flight this long after

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


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gap_seconds(earlier, later):
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


def load_codex_session(path):
    """Codex adapter: rollout-*.jsonl -> normalized session dict."""
    meta: dict[str, Any] = {}
    model = None
    requests: list[dict[str, Any]] = []
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
                    }
                )
    if not meta and not requests:
        return None
    return {
        "file": str(path),
        "agent_source": "codex",
        "session_id": meta.get("id") or meta.get("session_id"),
        "thread_source": meta.get("thread_source") or "user",
        "cwd": meta.get("cwd"),
        "started": meta.get("timestamp"),
        "model": model,
        "turn_contexts": turn_contexts,
        "requests": requests,
    }


def strip_replay(session):
    """Subagent rollouts replay parent history as a leading burst of
    token_count events with near-identical timestamps. Drop that prefix,
    keeping the last replayed event as the baseline for the child's own turns."""
    reqs = session["requests"]
    if session["thread_source"] != "subagent" or len(reqs) < 2:
        return reqs
    i = 0
    while i + 1 < len(reqs):
        try:
            delta = (parse_ts(reqs[i + 1]["ts"]) - parse_ts(reqs[i]["ts"])).total_seconds() * 1000
        except (TypeError, ValueError):
            break
        if delta > REPLAY_BURST_MS:
            break
        i += 1
    return reqs[i:] if i else reqs


def analyze(session):
    """Classify each request: first / hit / break / compaction. Adds per-request
    `kind`, `expected_cache`, `rebilled` and session-level aggregates."""
    reqs = strip_replay(session)
    prev = None
    total_input = total_cached = rebilled = breaks = compactions = 0
    for r in reqs:
        if prev is None:
            r["kind"] = "first"
            r["expected_cache"] = 0
            r["rebilled"] = 0
        else:
            expected = prev["input"]
            r["expected_cache"] = expected
            if r["input"] < COMPACTION_RATIO * prev["input"]:
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
    session["analysis"] = {
        "requests": len(reqs),
        "breaks": breaks,
        "compactions": compactions,
        "rebilled_tokens": rebilled,
        "input_tokens": total_input,
        "cached_tokens": total_cached,
        "hit_rate": total_cached / total_input if total_input else 0.0,
    }
    session["requests"] = reqs
    return session


def ran_cold(request: dict[str, Any] | None) -> bool:
    """True when this Request was itself a Cache Break that kept almost nothing —
    the cache was empty for it, rather than merely diverging part-way through."""
    if request is None or request.get("kind") != "break":
        return False
    expected = request["expected_cache"]
    return bool(expected) and request["cached"] / expected < COLD_RETENTION


def turn_context_changes(
    session: dict[str, Any], previous: dict[str, Any] | None, request: dict[str, Any]
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


def explain_breaks(session):
    """Diagnose every Cache Break in an analyzed session.

    Returns one dict per break: index, cause, gap_s, retention, rebilled, detail.
    """
    diagnoses = []
    reqs = session["requests"]
    for i, r in enumerate(reqs):
        if r["kind"] != "break":
            continue
        expected = r["expected_cache"]
        retention = r["cached"] / expected if expected else 0.0
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
                f"first Request of a new Turn after only {fmt_duration(gap)} idle; "
                f"history was re-serialized and {1 - retention:.0%} of the prefix diverged"
            )
        elif retention >= COLD_RETENTION:
            cause = CAUSE_HISTORY_CHANGE
            detail = (
                f"the cache was still warm ({retention:.0%} of the prefix survived) but "
                f"the prompt diverged part-way through, mid-Turn"
            )
        else:
            cause = CAUSE_UNKNOWN
            detail = (
                f"cold cache with no idle gap and no turn_context change; "
                f"kept {retention:.0%} of the expected prefix"
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


def idle_gap_advice(sessions):
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


KIND_CODE = {"first": 0, "hit": 1, "break": 2, "compaction": 3}


def session_key(session: dict[str, Any]) -> str:
    """Stable identity for a Session across rewrites: the viewer holds its selection
    by this rather than by row number, and Watch Mode uses it to recognize a Session
    it has already seen."""
    return session["session_id"] or session["file"]


def waterfall_payload(
    sessions: list[dict[str, Any]], live: Path | None = None
) -> list[dict[str, Any]]:
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


def load_sessions(sessions_dir: Path, min_requests: int, include_all: bool) -> list[dict[str, Any]]:
    """Every rollout under `sessions_dir`, normalized and analyzed. Sessions too short
    to say anything are dropped, as are subagent ones unless `include_all`."""
    sessions = []
    for path in sorted(sessions_dir.rglob("rollout-*.jsonl")):
        s = load_codex_session(path)
        if not s or len(s["requests"]) < min_requests:
            continue
        if not include_all and s["thread_source"] != "user":
            continue
        sessions.append(analyze(s))
    return sessions


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
    rollouts = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda p: -p.stat().st_mtime)
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
            session_key(s): s for s in load_sessions(sessions_dir, min_requests, include_all)
        }
        self.live: Path | None = None
        self._signal: tuple[str, dict[str, Any]] | None = None
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


def fmt_duration(seconds):
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.0f}m"
    return f"{seconds:.0f}s"


def fmt_tokens(n):
    return (
        f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.0f}k" if n >= 1000 else str(n)
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=str(SESSIONS_DIR))
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
        watch(
            Path(args.dir),
            port=args.port,
            min_requests=args.min_requests,
            include_all=args.all,
        )
        return

    if args.explain:
        s = analyze(load_codex_session(Path(args.explain)))
        a = s["analysis"]
        diagnoses = explain_breaks(s)
        if args.request is not None:
            diagnoses = [d for d in diagnoses if d["index"] == args.request]
        print(f"{s['session_id']}  {s['model'] or '?'}  {s['thread_source']}  {s['cwd']}")
        print(
            f"{a['breaks']} cache breaks over {a['requests']} requests, "
            f"{fmt_tokens(a['rebilled_tokens'])} tokens re-billed"
        )
        if not diagnoses:
            print("\nno cache breaks to explain")
            return
        for d in diagnoses:
            print(
                f"\n{d['index']:>4}  {d['cause']}  "
                f"(rebilled {fmt_tokens(d['rebilled'])}, {fmt_duration(d['gap_s'])} since "
                f"the previous request, {d['retention']:.0%} of the prefix kept)"
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
        s = analyze(load_codex_session(Path(args.session)))
        a = s["analysis"]
        print(f"{s['session_id']}  {s['model'] or '?'}  {s['thread_source']}  {s['cwd']}")
        print(
            f"requests={a['requests']} breaks={a['breaks']} compactions={a['compactions']} "
            f"hit_rate={a['hit_rate']:.0%} rebilled={fmt_tokens(a['rebilled_tokens'])}"
        )
        for i, r in enumerate(s["requests"]):
            mark = {"first": " ", "hit": " ", "break": "!", "compaction": "~"}[r["kind"]]
            bar_n = min(60, r["input"] // 5000)
            cached_n = min(bar_n, int(bar_n * (r["cached"] / r["input"])) if r["input"] else 0)
            bar = "█" * cached_n + "░" * (bar_n - cached_n)
            print(
                f"{i:3d} {mark} {r['kind']:<10} in={fmt_tokens(r['input']):>7} "
                f"cached={fmt_tokens(r['cached']):>7} "
                f"rebilled={fmt_tokens(r['rebilled']):>7} {bar}"
            )
        return

    sessions = load_sessions(Path(args.dir), args.min_requests, args.all)

    if args.web:
        compact = waterfall_payload(sessions)
        out = write_waterfall_data(compact)
        print(f"wrote {len(compact)} sessions to {out}", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(json.dumps(sessions, indent=1))
        print(f"wrote {len(sessions)} sessions to {args.json}", file=sys.stderr)

    tot = {"input": 0, "cached": 0, "rebilled": 0, "breaks": 0, "requests": 0}
    rows = []
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
