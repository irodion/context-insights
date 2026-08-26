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
import json
import sys
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# Thresholds (heuristics, tune freely)
BREAK_RATIO = 0.8       # cached < 80% of expected cache => cache break
COMPACTION_RATIO = 0.6  # input < 60% of previous input => compaction, not break
REPLAY_BURST_MS = 200   # subagent replay: consecutive events closer than this


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_codex_session(path):
    """Codex adapter: rollout-*.jsonl -> normalized session dict."""
    meta = {}
    model = None
    requests = []
    with open(path, errors="replace") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            payload = ev.get("payload") or {}
            if t == "session_meta" and not meta:
                meta = payload
            elif t == "turn_context":
                model = payload.get("model") or model
            elif t == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                last = info.get("last_token_usage")
                if not last:
                    continue
                requests.append({
                    "ts": ev.get("timestamp"),
                    "input": last.get("input_tokens", 0),
                    "cached": last.get("cached_input_tokens", 0),
                    "cache_write": last.get("cache_write_input_tokens", 0),
                    "output": last.get("output_tokens", 0),
                    "total_input": (info.get("total_token_usage") or {}).get("input_tokens", 0),
                    "context_window": info.get("model_context_window"),
                })
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


def fmt_tokens(n):
    return f"{n/1_000_000:.1f}M" if n >= 1_000_000 else f"{n/1000:.0f}k" if n >= 1000 else str(n)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=str(SESSIONS_DIR))
    ap.add_argument("--all", action="store_true", help="include subagent/other sessions")
    ap.add_argument("--session", help="analyze a single rollout file in detail")
    ap.add_argument("--json", help="write normalized+analyzed sessions to this file")
    ap.add_argument("--web", action="store_true",
                    help="write waterfall_data.js next to waterfall.html")
    ap.add_argument("--min-requests", type=int, default=3)
    args = ap.parse_args()

    if args.session:
        s = analyze(load_codex_session(Path(args.session)))
        a = s["analysis"]
        print(f"{s['session_id']}  {s['model'] or '?'}  {s['thread_source']}  {s['cwd']}")
        print(f"requests={a['requests']} breaks={a['breaks']} compactions={a['compactions']} "
              f"hit_rate={a['hit_rate']:.0%} rebilled={fmt_tokens(a['rebilled_tokens'])}")
        for i, r in enumerate(s["requests"]):
            mark = {"first": " ", "hit": " ", "break": "!", "compaction": "~"}[r["kind"]]
            bar_n = min(60, r["input"] // 5000)
            cached_n = min(bar_n, int(bar_n * (r["cached"] / r["input"])) if r["input"] else 0)
            bar = "█" * cached_n + "░" * (bar_n - cached_n)
            print(f"{i:3d} {mark} {r['kind']:<10} in={fmt_tokens(r['input']):>7} "
                  f"cached={fmt_tokens(r['cached']):>7} rebilled={fmt_tokens(r['rebilled']):>7} {bar}")
        return

    sessions = []
    for path in sorted(Path(args.dir).rglob("rollout-*.jsonl")):
        s = load_codex_session(path)
        if not s or len(s["requests"]) < args.min_requests:
            continue
        if not args.all and s["thread_source"] != "user":
            continue
        sessions.append(analyze(s))

    if args.web:
        kind_code = {"first": 0, "hit": 1, "break": 2, "compaction": 3}
        by_rebilled = sorted(sessions, key=lambda s: -s["analysis"]["rebilled_tokens"])
        compact = [{
            "date": (s["started"] or "")[:10],
            "model": s["model"],
            "cwd": ((s["cwd"] or "").rstrip("/").split("/")[-1]) or s["cwd"],
            "a": s["analysis"],
            "r": [[r["input"], r["cached"], r["rebilled"], kind_code[r["kind"]],
                   (r["ts"] or "")[11:16]] for r in s["requests"]],
        } for s in by_rebilled]
        out = Path(__file__).parent / "waterfall_data.js"
        out.write_text("// generated by parse_codex.py --web; regenerate, don't edit\n"
                       "const SESSIONS = " + json.dumps(compact, separators=(",", ":")) + ";\n")
        print(f"wrote {len(compact)} sessions to {out}", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(json.dumps(sessions, indent=1))
        print(f"wrote {len(sessions)} sessions to {args.json}", file=sys.stderr)

    tot = {"input": 0, "cached": 0, "rebilled": 0, "breaks": 0, "requests": 0}
    rows = []
    for s in sessions:
        a = s["analysis"]
        tot["input"] += a["input_tokens"]; tot["cached"] += a["cached_tokens"]
        tot["rebilled"] += a["rebilled_tokens"]; tot["breaks"] += a["breaks"]
        tot["requests"] += a["requests"]
        rows.append(s)
    rows.sort(key=lambda s: -s["analysis"]["rebilled_tokens"])

    print(f"{'date':<12} {'model':<16} {'reqs':>5} {'breaks':>6} {'hit%':>5} {'rebilled':>9}  cwd")
    for s in rows[:25]:
        a = s["analysis"]
        date = (s["started"] or "")[:10]
        cwd = (s["cwd"] or "").replace(str(Path.home()), "~")
        print(f"{date:<12} {(s['model'] or '?'):<16} {a['requests']:>5} {a['breaks']:>6} "
              f"{a['hit_rate']:>5.0%} {fmt_tokens(a['rebilled_tokens']):>9}  {cwd[-40:]}")
    if tot["input"]:
        print(f"\n{len(rows)} sessions, {tot['requests']} requests, "
              f"overall hit rate {tot['cached']/tot['input']:.0%}, "
              f"{tot['breaks']} cache breaks, {fmt_tokens(tot['rebilled'])} tokens re-billed")


if __name__ == "__main__":
    main()
