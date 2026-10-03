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


def hit(rid, text, sim=0.75, **kw):
    row = {"rid": rid, "text": text, "score": 0.5, "source": "user", "namespace": "default",
           "metadata": {}, "why_retrieved": [f"semantically similar ({sim})"]}
    row.update(kw)
    return row


DEFAULTS = dict(YANTRIKDB_HOOKS_TOP_K=None, YANTRIKDB_HOOKS_MIN_SIMILARITY=None, YANTRIKDB_HOOKS_CAPTURE=None,
                YANTRIKDB_HOOKS_RECALL_CAPTURED=None, YANTRIKDB_HOOKS_EXCLUDE_NAMESPACES=None,
                YANTRIKDB_HOOKS_MIN_SCORE=None, YANTRIKDB_HOOKS_DIGEST_MAINTENANCE=None,
                YANTRIKDB_HOOKS_DIGEST_DECISIONS=None)


class RelevanceGateTests(unittest.TestCase):
    def test_noise_is_dropped_and_injection_capped(self):
        hook = load_hook("user_prompt_submit")
        hits = [
            hit("auto", "commit and push", source="session_auto_capture"),
            hit("merge", "yes. push | review with fable", metadata={"consolidated_from": ["a", "b"]}),
            hit("hermes", "Sorry, something went wrong there.", namespace="hermes:hermes:default"),
            hit("graph", "Docker Swarm DNS names contain an underscore.", why_retrieved=["keyword_match"]),
            hit("weak", "Ghost CMS logger crashes on array env vars.", sim=0.41),
            hit("seen", "Postgres 16 is the indexer database."),
            *[hit(r, f"fluidd convention {r}") for r in ("a", "b", "c", "d")],
        ]
        with env(**{**DEFAULTS, "YANTRIKDB_HOOKS_EXCLUDE_NAMESPACES": "hermes:"}):
            lines, fresh = hook.select_lines(hits, ["seen"])
        self.assertEqual(fresh, ["a", "b", "c"])
        self.assertEqual(len(lines), 3)

    def test_digest_keeps_only_live_decisions(self):
        hook = load_hook("session_start")
        digest = {
            "top_decisions": [
                {"rid": "old", "snippet": "BOTS MIGRATION PAUSED", "superseded_by": "new"},
                {"rid": "chat", "snippet": "hey. unlock the laptop", "namespace": "hermes:hermes:default"},
                *[{"rid": f"d{i}", "snippet": f"decision {i}", "namespace": "default"} for i in range(8)],
            ],
            "open_conflicts": [{"summary": "a vs b"}],
            "pending_triggers": [{"reason": "128 open conflicts need attention"}],
            "knowledge_gaps": [{"query": "just logged in in gcloud cli"}],
        }
        with env(**{**DEFAULTS, "YANTRIKDB_HOOKS_EXCLUDE_NAMESPACES": "hermes:"}):
            text = hook.render(digest)
        self.assertIn("decision 4", text)
        self.assertNotIn("decision 5", text)
        for noise in ("PAUSED", "unlock the laptop", "a vs b", "need attention", "gcloud cli"):
            self.assertNotIn(noise, text)
        with env(**{**DEFAULTS, "YANTRIKDB_HOOKS_DIGEST_MAINTENANCE": "1"}):
            self.assertIn("need attention", hook.render(digest))


class NamespaceDefaultTests(unittest.TestCase):
    def test_other_agent_namespaces_are_included_by_default(self):
        hook = load_hook("user_prompt_submit")
        with env(**DEFAULTS):
            _, fresh = hook.select_lines([hit("hermes", "NAS runs parent-control as a systemd unit.",
                                              namespace="hermes:hermes:default")], [])
        self.assertEqual(fresh, ["hermes"])


class SessionEndDetachTests(unittest.TestCase):
    def test_session_end_detaches_unless_already_detached_or_disabled(self):
        hook = load_hook("capture")
        with env(YANTRIKDB_HOOKS_DETACHED=None, YANTRIKDB_HOOKS_DETACH_SESSION_END=None):
            self.assertTrue(hook.should_detach("SessionEnd"))
            self.assertFalse(hook.should_detach("PreCompact"))
        with env(YANTRIKDB_HOOKS_DETACHED="1"):
            self.assertFalse(hook.should_detach("SessionEnd"))
        with env(YANTRIKDB_HOOKS_DETACHED=None, YANTRIKDB_HOOKS_DETACH_SESSION_END="0"):
            self.assertFalse(hook.should_detach("SessionEnd"))


if __name__ == "__main__":
    unittest.main()
