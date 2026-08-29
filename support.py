"""Fixture helpers shared by both Agent Source test suites.

Only what neither log grammar owns: where a synthetic Session starts in time, how a
record file reaches disk, and a temp directory that cleans itself up. The grammars
themselves live next to the tests that speak them — `test_parse_codex.py` for Codex
rollouts, `test_claude_adapter.py` for Claude Code transcripts.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BASE = datetime.fromisoformat("2026-03-20T18:00:00+00:00")


def at(seconds: float, timespec: str = "auto") -> str:
    """Timestamp `seconds` after the session start. `timespec` is the one thing the two
    log formats spell differently: Claude Code writes milliseconds, Codex does not."""
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec=timespec).replace("+00:00", "Z")


def write_jsonl(path: Path, records: list[dict], modified: float | None = None) -> Path:
    """A log file on disk, one JSON record per line. `modified` backdates the mtime,
    which is how Watch Mode decides which Session is live."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    if modified is not None:
        os.utime(path, (modified, modified))
    return path


def temp_dir(testcase: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    return Path(tmp.name)
