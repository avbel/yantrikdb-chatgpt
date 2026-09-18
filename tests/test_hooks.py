import importlib.util
import sys
import unittest

from _helpers import HOOKS, env


def load_hook(name: str):
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class HookLogicTests(unittest.TestCase):
    def test_recall_filters_seen_and_low_score_hits(self):
        hook = load_hook("user_prompt_submit")
        lines, fresh = hook.render_hits(
            [
                {"rid": "seen", "text": "already shown", "score": 0.9},
                {"rid": "low", "text": "too weak", "score": 0.01},
                {"rid": "new", "text": "use Postgres 16", "score": 0.8},
            ],
            ["seen"],
            0.1,
        )
        self.assertEqual(lines, ["- use Postgres 16"])
        self.assertEqual(fresh, ["new"])

    def test_digest_labels_memory_as_untrusted_background(self):
        hook = load_hook("session_start")
        text = hook.render({"top_decisions": [{"snippet": "Use Postgres 16."}]})
        self.assertIn("untrusted background context", text)
        self.assertIn("Use Postgres 16", text)

    def test_tracking_uses_codex_client_id_and_retries_conflicts(self):
        hook = load_hook("session_start")
        seen = []

        class Response:
            text = "session conflict: already active"

        class Conflict(Exception):
            response = Response()

        class DB:
            def session_start(self, **kwargs):
                seen.append(kwargs)
                if len(seen) == 1:
                    raise Conflict("500")
                return {"session_id": "tracked"}

        self.assertEqual(hook.start_tracking(DB(), "project", "codex-thread"), "tracked")
        self.assertEqual(seen[0], {"namespace": "project", "client_id": "codex-thread"})
        self.assertTrue(seen[1]["client_id"].startswith("codex-thread-"))

    def test_explicit_redaction_disable_does_not_change_hook_logic(self):
        hook = load_hook("user_prompt_submit")
        with env(YANTRIKDB_HOOKS_REDACT="0"):
            lines, _ = hook.render_hits([{"text": "normal", "score": 1}], [], 0)
        self.assertEqual(lines, ["- normal"])


if __name__ == "__main__":
    unittest.main()
