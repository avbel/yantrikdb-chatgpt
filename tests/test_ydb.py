import os
import time
import unittest

from _helpers import env, load, sandbox, write_json


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.ydb = load("ydb")

    def test_client_id_is_scoped_to_codex_session(self):
        with env(YANTRIKDB_HOOKS_CLIENT_ID=None):
            self.assertEqual(self.ydb.client_id_for("THR/ABC"), "codex-thr-abc")
            self.assertNotEqual(
                self.ydb.client_id_for("thread-a"), self.ydb.client_id_for("thread-b")
            )
            self.assertEqual(self.ydb.client_id_for(None), "codex")

    def test_explicit_client_id_wins(self):
        with env(YANTRIKDB_HOOKS_CLIENT_ID="workstation"):
            self.assertEqual(self.ydb.client_id_for("ignored"), "workstation")

    def test_namespace_auto_uses_path_when_no_remote(self):
        with sandbox() as root, env(YANTRIKDB_HOOKS_NAMESPACE="auto"):
            first = root / "one" / "api"
            second = root / "two" / "api"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            self.assertRegex(self.ydb.namespace_for(str(first)), r"^api-[0-9a-f]{6}$")
            self.assertNotEqual(
                self.ydb.namespace_for(str(first)), self.ydb.namespace_for(str(second))
            )

    def test_state_round_trip_and_sweep(self):
        with sandbox(), env(YANTRIKDB_HOOKS_STATE_MAX_AGE_DAYS="7"):
            self.ydb.write_state("session/1", a=1)
            self.ydb.write_state("session/1", b=2)
            self.assertEqual(self.ydb.read_state("session/1"), {"a": 1, "b": 2})
            path = self.ydb.state_path("session/1")
            stale = time.time() - 30 * 86400
            os.utime(path, (stale, stale))
            self.ydb.sweep_state()
            self.assertFalse(path.exists())

    def test_merge_rids_deduplicates_and_trims_oldest(self):
        self.assertEqual(
            self.ydb.merge_rids(["a", "b", "c"], ["c", "d", "e"], cap=4),
            ["b", "c", "d", "e"],
        )

    def test_reads_json_and_toml_mcp_env(self):
        with sandbox() as root:
            json_path = root / ".mcp.json"
            write_json(
                json_path,
                {
                    "mcpServers": {
                        "yantrikdb": {
                            "env": {"YANTRIKDB_DB_PATH": "/tmp/db", "IGNORED": "x"}
                        }
                    }
                },
            )
            self.assertEqual(
                self.ydb.mcp_env_from_json(json_path, "yantrikdb"),
                {"YANTRIKDB_DB_PATH": "/tmp/db"},
            )

            toml_path = root / "config.toml"
            toml_path.write_text(
                '[mcp_servers.yantrikdb.env]\nYANTRIKDB_SERVER_URL = "http://db:7438"\n'
            )
            self.assertEqual(
                self.ydb.mcp_env_from_toml(toml_path, "yantrikdb"),
                {"YANTRIKDB_SERVER_URL": "http://db:7438"},
            )

    def test_project_mcp_env_requires_explicit_opt_in(self):
        with sandbox() as root:
            write_json(
                root / ".mcp.json",
                {
                    "mcpServers": {
                        "yantrikdb": {
                            "env": {"YANTRIKDB_SERVER_URL": "http://project:7438"}
                        }
                    }
                },
            )
            with env(
                PLUGIN_ROOT=None,
                CLAUDE_PLUGIN_ROOT=None,
                YANTRIKDB_SERVER_URL=None,
                YANTRIKDB_HOOKS_ADOPT_MCP_ENV="1",
                YANTRIKDB_HOOKS_ADOPT_PROJECT_MCP_ENV=None,
                YANTRIKDB_HOOKS_ADOPT_USER_MCP_ENV=None,
            ):
                self.ydb.adopt_mcp_env(str(root))
                self.assertNotIn("YANTRIKDB_SERVER_URL", os.environ)
                os.environ["YANTRIKDB_HOOKS_ADOPT_PROJECT_MCP_ENV"] = "1"
                self.ydb.adopt_mcp_env(str(root))
                self.assertEqual(os.environ["YANTRIKDB_SERVER_URL"], "http://project:7438")

    def test_unreachable_marker_is_url_specific(self):
        with sandbox(), env(YANTRIKDB_HOOKS_UNREACHABLE_TTL="60"):
            self.ydb.mark_cluster_down("http://one:7438")
            self.assertTrue(self.ydb.cluster_marked_down("http://one:7438"))
            self.assertFalse(self.ydb.cluster_marked_down("http://two:7438"))


if __name__ == "__main__":
    unittest.main()
