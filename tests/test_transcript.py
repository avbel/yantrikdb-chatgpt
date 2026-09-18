import json
import unittest

from _helpers import load, sandbox, write_transcript


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.transcript = load("transcript")

    def test_codex_user_prompts_are_kept_but_injected_config_is_not(self):
        with sandbox() as root:
            path = root / "rollout.jsonl"
            write_transcript(path)
            rows = self.transcript.lines(str(path))
        text = "\n".join(rows)
        self.assertIn("Postgres 16", text)
        self.assertIn("indexer-prod-1", text)
        self.assertNotIn("Repository instructions", text)
        self.assertNotIn("migrate the schema", text)

    def test_roles_all_includes_assistant(self):
        with sandbox() as root:
            path = root / "rollout.jsonl"
            write_transcript(path)
            rows = self.transcript.lines(str(path), roles="all")
        self.assertTrue(any("migrate the schema" in row for row in rows))

    def test_legacy_transcript_is_still_tolerated(self):
        rows = [
            {
                "type": "user",
                "message": {"role": "user", "content": "Keep the API flag names stable."},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Understood."}],
                },
            },
        ]
        with sandbox() as root:
            path = root / "legacy.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows))
            captured = self.transcript.lines(str(path))
        self.assertEqual(captured, ["Keep the API flag names stable."])

    def test_missing_file_is_empty(self):
        self.assertEqual(self.transcript.lines(None), [])
        self.assertEqual(self.transcript.lines("/does/not/exist"), [])


if __name__ == "__main__":
    unittest.main()
