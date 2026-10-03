#!/usr/bin/env python3
"""Capture user-authored plugin context before compaction and at session end.

Capture is opt-in (YANTRIKDB_HOOKS_CAPTURE=1): in practice the drafts stayed
near-verbatim user prompts, and consolidation later relabeled them as
user-sourced facts. Closing the tracked session and the hygiene pass still run.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import redact  # noqa: E402
import transcript  # noqa: E402
import ydb  # noqa: E402

MIN_DRAFT_CHARS = 200


def _mark(line: str) -> str:
    return hashlib.sha1(line.encode()).hexdigest()[:16]


def capture(db, event: dict, state: dict, session_id: str, namespace: str, which: str) -> None:
    if transcript.is_headless(event.get("transcript_path")):
        ydb.log(f"capture({which}) skipped: headless run")
        return
    rows = transcript.lines(
        event.get("transcript_path"),
        max_turns=ydb.env_int("YANTRIKDB_HOOKS_CAPTURE_TURNS", 40),
        roles=os.environ.get("YANTRIKDB_HOOKS_CAPTURE_ROLES", "user"),
    )
    done = set(state.get("captured") or [])
    fresh = [row for row in rows if _mark(row) not in done]
    text = redact.redact(
        transcript.clamp(fresh, ydb.env_int("YANTRIKDB_HOOKS_CAPTURE_CHARS", 6000))
    )
    if len(text) < MIN_DRAFT_CHARS:
        ydb.log(f"capture({which}) skipped: {len(text)} new chars")
        return
    try:
        result = ydb.flex(
            lambda **kwargs: db.draft_memories_from_summary(text, **kwargs),
            namespace=namespace,
            domain="work",
        )
        ydb.log(f"capture({which}) drafted: {result}")
        marks = list(done | {_mark(row) for row in fresh})[-600:]
        ydb.write_state(session_id, captured=marks)
    except Exception as error:
        ydb.log(f"draft failed: {error}")


def finish_session(db, state: dict) -> None:
    tracked = state.get("ydb_session_id")
    if tracked:
        try:
            db.session_end(tracked)
        except Exception as error:
            ydb.log(f"session_end failed: {error}")
    if not ydb.env_flag("YANTRIKDB_HOOKS_MAINTENANCE", True):
        return
    if not ydb.is_http(db):
        try:
            ydb.flex(db.run_maintenance_cycle)
            return
        except Exception as error:
            ydb.log(f"maintenance failed: {error}")
    try:
        db.think()
    except Exception as error:
        ydb.log(f"think failed: {error}")


def should_detach(which: str) -> bool:
    """Codex clamps SessionEnd hooks to 3 s, which kills closing the tracked
    session and the consolidation pass, so that work moves to a child process."""
    return (
        which == "SessionEnd"
        and not ydb.env_flag("YANTRIKDB_HOOKS_DETACHED", False)
        and ydb.env_flag("YANTRIKDB_HOOKS_DETACH_SESSION_END", True)
    )


def detach(event: dict, which: str) -> None:
    log = (ydb.state_dir() / "session-end.log").open("ab") if ydb.env_flag("YANTRIKDB_HOOKS_DEBUG", False) \
        else subprocess.DEVNULL
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), which],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=log,
        env={**os.environ, "YANTRIKDB_HOOKS_DETACHED": "1"},
        start_new_session=True,
        close_fds=True,
    )
    child.stdin.write(json.dumps(event).encode())
    child.stdin.close()


def main() -> None:
    ydb.guard(ydb.env_int("YANTRIKDB_HOOKS_CAPTURE_TIMEOUT", 110))
    event = ydb.read_event()
    which = (sys.argv[1] if len(sys.argv) > 1 else event.get("hook_event_name") or "").strip()
    if should_detach(which):
        try:
            detach(event, which)
            ydb.log(f"{which} work detached")
            ydb.emit()
        except Exception as error:
            ydb.log(f"detach failed, running inline: {error}")
    cwd = event.get("cwd")
    ydb.adopt_mcp_env(cwd)
    session_id = event.get("session_id") or ""
    namespace = ydb.namespace_for(cwd)
    state = ydb.read_state(session_id)
    db = ydb.open_db()
    if db is None:
        if which == "SessionEnd":
            ydb.drop_state(session_id)
        ydb.emit()

    if ydb.capture_enabled():
        capture(db, event, state, session_id, namespace, which)
    else:
        ydb.log(f"capture({which}) disabled")
    if which == "SessionEnd":
        finish_session(db, state)
        ydb.drop_state(session_id)
    ydb.close_db(db)
    ydb.emit()


if __name__ == "__main__":
    ydb.run(main)
