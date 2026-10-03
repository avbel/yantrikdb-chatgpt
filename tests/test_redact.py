import unittest

from _helpers import env, load


class RedactTests(unittest.TestCase):
    def setUp(self):
        self.redact = load("redact")

    def test_known_secrets_are_masked(self):
        cases = (
            "token=ydb_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "postgres://user:s3cretpassword@db.example.com/app",
            "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        )
        for value in cases:
            self.assertIn("[redacted", self.redact.redact(value), value)

    def test_oauth_codes_and_tokens_are_masked(self):
        cases = {
            "http://localhost:1/?state=BKZmldtWuKQARBVuymiy&iss=https://accounts.google.com&code=4/0AXlqoi6mfZ8khB6jehDKnWG&scope=email":
                ("BKZmldtWuKQARBVuymiy", "0AXlqoi6mfZ8khB6jehDKnWG"),
            "paste the code 4/0AVGzR1Bc3dEfGhIjKlMnOpQrStUvWxYz here": ("0AVGzR1Bc3dEfGhIjKlMnOpQrStUvWxYz",),
            "access_token=ya29.a0AfH6SMBx3yZ9QWERTYuiopasdfgh refresh_token: 1//0gLmNoPqRsTuVwXyZ12345":
                ("ya29.a0AfH6SMBx3yZ9QWERTYuiopasdfgh", "1//0gLmNoPqRsTuVwXyZ12345"),
            "client_secret=GOCSPX-abcdefghijklmnop": ("GOCSPX-abcdefghijklmnop",),
        }
        for text, secrets in cases.items():
            out = self.redact.redact(text)
            for secret in secrets:
                self.assertNotIn(secret, out, text)
        self.assertIn("accounts.google.com", self.redact.redact(next(iter(cases))))

    def test_normal_text_and_git_sha_survive(self):
        text = "Postgres 16 at commit 3f786850e387550fdab836ed7e6dc881de23001b."
        self.assertEqual(self.redact.redact(text), text)

    def test_can_be_disabled(self):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        with env(YANTRIKDB_HOOKS_REDACT="0"):
            self.assertEqual(self.redact.redact(secret), secret)


if __name__ == "__main__":
    unittest.main()
