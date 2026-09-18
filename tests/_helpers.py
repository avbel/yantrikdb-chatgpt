"""Standard-library-only fixtures for the plugin tests."""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "yantrikdb-chatgpt"
HOOKS = PLUGIN / "hooks"
LIB = HOOKS / "lib"
RUN_SH = HOOKS / "run.sh"

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))


def load(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


@contextlib.contextmanager
def env(**overrides: str | None):
    saved = {key: os.environ.get(key) for key in overrides}
    for key, value in overrides.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def sandbox():
    root = Path(tempfile.mkdtemp(prefix="yantrikdb-codex-test-"))
    home = root / "home"
    data = root / "data"
    home.mkdir()
    data.mkdir()
    with env(HOME=str(home), PLUGIN_DATA=str(data), CLAUDE_PLUGIN_DATA=None):
        try:
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def codex_transcript() -> list[dict]:
    return [
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Repository instructions that are not a user memory."}
                ],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["agents_md.instructions"]
                },
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "We chose Postgres 16 for the indexer because the ClickHouse mirror lagged.",
                    }
                ],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["user.text"]
                },
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "I will migrate the schema."}
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Deploy to indexer-prod-1 through Dokploy, never with manual docker run.",
                    }
                ],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["user.text"]
                },
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Keep the command-line flag names stable because downstream automation parses them, and prefer descriptive names over abbreviations in this repository.",
                    }
                ],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["user.text"]
                },
            },
        },
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec"}},
    ]


def write_transcript(path: Path) -> None:
    path.write_text("\n".join(json.dumps(row) for row in codex_transcript()) + "\n")
