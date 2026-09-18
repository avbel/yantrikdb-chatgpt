import json
import unittest

from _helpers import PLUGIN, ROOT


class PluginTests(unittest.TestCase):
    def test_manifest_and_mcp_server(self):
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        mcp = json.loads((PLUGIN / ".mcp.json").read_text())
        self.assertEqual(manifest["name"], PLUGIN.name)
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(mcp["mcpServers"]["yantrikdb"]["command"], "yantrikdb-mcp")

    def test_four_lifecycle_hooks_are_registered(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(
            set(hooks), {"SessionStart", "UserPromptSubmit", "PreCompact", "SessionEnd"}
        )
        commands = [
            handler["command"]
            for groups in hooks.values()
            for group in groups
            for handler in group["hooks"]
        ]
        self.assertTrue(all("${PLUGIN_ROOT}" in command for command in commands))

    def test_marketplace_points_to_packaged_plugin(self):
        marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
        self.assertEqual(marketplace["name"], "yantrikdb-chatgpt")
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "yantrikdb-chatgpt")
        self.assertEqual(entry["source"]["path"], "./plugins/yantrikdb-chatgpt")


if __name__ == "__main__":
    unittest.main()
