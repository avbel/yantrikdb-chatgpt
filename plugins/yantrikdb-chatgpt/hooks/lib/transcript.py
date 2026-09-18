"""Bounded reader for Codex, ChatGPT, and compatible JSONL transcripts.

Codex documents transcript paths but not the transcript format as a stable
hook API. Unknown records are therefore ignored rather than treated as errors.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_MAX_BYTES = 4 * 1024 * 1024
_TEXT_BLOCKS = {"text", "input_text", "output_text"}
_META_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-caveat>",
    "<system-reminder>",
    "<task-notification>",
    "<user-prompt-submit-hook>",
    "<ide_",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<antml",
)
_META_SPANS = re.compile(
    r"<(system-reminder|task-notification|local-command-stdout|local-command-caveat)>"
    r".*?</\1>",
    re.S,
)


def is_meta(text: str) -> bool:
    return text.lstrip().startswith(_META_PREFIXES)


def clean_text(text: str) -> str:
    return " ".join(_META_SPANS.sub(" ", text or "").split())


def _blocks_text(content, kinds: list[str] | None = None, role: str = "") -> str:
    if isinstance(content, str):
        return "" if is_meta(content) else content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    aligned = isinstance(kinds, list) and len(kinds) == len(content)
    for index, block in enumerate(content):
        if not isinstance(block, dict) or block.get("type") not in _TEXT_BLOCKS:
            continue
        if role == "user" and aligned and not str(kinds[index]).startswith("user."):
            continue
        text = block.get("text")
        if isinstance(text, str) and not is_meta(text):
            parts.append(text)
    return "\n".join(parts)


def _codex_turn(record: dict) -> tuple[str, str] | None:
    if record.get("type") != "response_item":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role = payload.get("role")
    if role not in ("user", "assistant"):
        return None

    metadata = payload.get("internal_chat_message_metadata_passthrough")
    kinds = metadata.get("content_item_kinds") if isinstance(metadata, dict) else None
    if role == "user" and isinstance(kinds, list) and not any(
        str(kind).startswith("user.") for kind in kinds
    ):
        return None
    return role, _blocks_text(payload.get("content"), kinds, role)


def _legacy_turn(record: dict) -> tuple[str, str] | None:
    if record.get("isMeta") or record.get("isSidechain"):
        return None
    message = record.get("message")
    if isinstance(message, dict):
        role = message.get("role") or record.get("type")
        content = message.get("content")
    elif record.get("type") in ("user", "assistant"):
        role = record.get("type")
        content = record.get("content")
    else:
        return None
    if role not in ("user", "assistant"):
        return None
    return role, _blocks_text(content, role=role)


def turns(path: str | None, limit: int = 40) -> list[tuple[str, str]]:
    if not path:
        return []
    source = Path(path)
    if not source.is_file():
        return []
    try:
        size = source.stat().st_size
        with source.open("rb") as handle:
            if size > _MAX_BYTES:
                handle.seek(size - _MAX_BYTES, os.SEEK_SET)
                handle.readline()
            raw = handle.read().decode("utf-8", "replace")
    except Exception:
        return []

    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        turn = _codex_turn(record) or _legacy_turn(record)
        if not turn:
            continue
        role, text = turn
        text = clean_text(text)
        if text:
            out.append((role, text))
    return out[-limit:]


def lines(path: str | None, *, max_turns: int = 40, roles: str = "user") -> list[str]:
    wanted = ("user", "assistant") if roles.strip().lower() == "all" else ("user",)
    out: list[str] = []
    for role, text in turns(path, limit=max_turns):
        if role not in wanted or len(text) < 12:
            continue
        out.append(text if text.endswith((".", "!", "?")) else text + ".")
    return out


def clamp(rows: list[str], max_chars: int = 6000) -> str:
    blob = "\n".join(rows)
    if len(blob) <= max_chars:
        return blob
    blob = blob[-max_chars:]
    newline = blob.find("\n")
    return blob[newline + 1 :] if newline >= 0 else blob


def summary(
    path: str | None,
    *,
    max_turns: int = 40,
    max_chars: int = 6000,
    roles: str = "user",
) -> str:
    return clamp(lines(path, max_turns=max_turns, roles=roles), max_chars)
