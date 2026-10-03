"""End-to-end lifecycle test against a throwaway embedded YantrikDB store."""

import json
import os
import subprocess
import time
import unittest
from pathlib import Path

from _helpers import ROOT, RUN_SH, env, sandbox, write_transcript


def run_hook(script: str, payload: dict, *args: str):
    result = subprocess.run(
        [str(RUN_SH), script, *args],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=180,
    )
    output = result.stdout.strip()
    return (json.loads(output) if output else None), result.stderr


class LifecycleTests(unittest.TestCase):
    def test_session_recall_capture_and_close(self):
        with sandbox() as root, env(
            YANTRIKDB_SERVER_URL=None,
            YANTRIKDB_TOKEN=None,
            YANTRIKDB_HOOKS_ADOPT_MCP_ENV="0",
            YANTRIKDB_DB_PATH=str(root / "memory.db"),
            YANTRIKDB_EMBEDDER="bundled",
            YANTRIKDB_HOOKS_NAMESPACE="default",
            YANTRIKDB_HOOKS_DEBUG="1",
            YANTRIKDB_HOOKS_CAPTURE=None,
            YANTRIKDB_HOOKS_MIN_SIMILARITY=None,
            YANTRIKDB_HOOKS_DETACH_SESSION_END=None,
        ):
            transcript = root / "rollout.jsonl"
            write_transcript(transcript)
            base = {
                "session_id": "thread-1",
                "cwd": str(ROOT),
                "transcript_path": str(transcript),
            }

            output, error = run_hook("session_start.py", {**base, "source": "startup"})
            if "engine unavailable" in error:
                self.skipTest("yantrikdb-mcp runtime unavailable: " + error[-300:])
            self.assertIsNone(output)
            self.assertTrue((Path(os.environ["PLUGIN_DATA"]) / "thread-1.json").exists())

            pre_compact = {**base, "hook_event_name": "PreCompact", "trigger": "auto"}
            output, error = run_hook("capture.py", pre_compact, "PreCompact")
            self.assertIsNone(output)
            self.assertIn("capture(PreCompact) disabled", error, "capture is opt-in")

            os.environ["YANTRIKDB_HOOKS_CAPTURE"] = "1"
            # A two-record store is matched through the keyword lane only; the
            # engine annotates no semantic similarity, so the gate is off here.
            os.environ["YANTRIKDB_HOOKS_MIN_SIMILARITY"] = "0"
            output, error = run_hook("capture.py", pre_compact, "PreCompact")
            self.assertIsNone(output)
            self.assertIn("drafted", error)
            self.assertNotIn("Repository instructions", error)

            output, error = run_hook(
                "user_prompt_submit.py",
                {**base, "prompt": "Which database and deployment process did we choose?"},
            )
            self.assertIsNotNone(output, error)
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertTrue("Postgres" in context or "Dokploy" in context, context)

            state = Path(os.environ["PLUGIN_DATA"]) / "thread-1.json"
            started = time.monotonic()
            output, error = run_hook(
                "capture.py", {**base, "hook_event_name": "SessionEnd", "reason": "other"}, "SessionEnd"
            )
            self.assertIsNone(output)
            self.assertIn("SessionEnd work detached", error)
            self.assertLess(time.monotonic() - started, 3.0, "must return inside the Codex 3 s clamp")
            deadline = time.monotonic() + 60
            while state.exists() and time.monotonic() < deadline:
                time.sleep(0.2)
            self.assertFalse(state.exists(), "the detached child closes the session and drops state")
            log = (Path(os.environ["PLUGIN_DATA"]) / "session-end.log").read_text()
            self.assertIn("skipped: 0 new chars", log, "watermark prevents re-drafting")


if __name__ == "__main__":
    unittest.main()
