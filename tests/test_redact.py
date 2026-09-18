import unittest

from _helpers import env, load


class RedactTests(unittest.TestCase):
    def setUp(self):
        self.redact = load("redact")

    def test_known_secrets_are_masked(self):
        cases = (
            "token=ydb_b427b6b03ee9bd45994180816bb2ebcae1b78f58293fb76cac41b6fd0d2303af",
            "key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "postgres://user:s3cretpassword@db.example.com/app",
            "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        )
        for value in cases:
            self.assertIn("[redacted", self.redact.redact(value), value)

    def test_normal_text_and_git_sha_survive(self):
        text = "Postgres 16 at commit 3f786850e387550fdab836ed7e6dc881de23001b."
        self.assertEqual(self.redact.redact(text), text)

    def test_can_be_disabled(self):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        with env(YANTRIKDB_HOOKS_REDACT="0"):
            self.assertEqual(self.redact.redact(secret), secret)


if __name__ == "__main__":
    unittest.main()
