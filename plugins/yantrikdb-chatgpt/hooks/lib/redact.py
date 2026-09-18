"""Best-effort secret redaction before plugin text becomes long-term memory."""

from __future__ import annotations

import os
import re

_TOKEN = "[redacted token]"
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
        "[redacted private key]",
    ),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), r"\1[redacted]@"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{20,}"), rf"\1 {_TOKEN}"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "[redacted jwt]",
    ),
    (re.compile(r"\bydb_[0-9a-f]{32,}\b"), _TOKEN),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), _TOKEN),
    (re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}"), _TOKEN),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted aws key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), _TOKEN),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?([^\s'\",;]{8,})"
        ),
        r"\1=[redacted]",
    ),
    (re.compile(r"\b[A-Fa-f0-9]{48,}\b"), "[redacted hex]"),
)


def enabled() -> bool:
    return os.environ.get("YANTRIKDB_HOOKS_REDACT", "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def redact(text: str | None) -> str:
    if not text or not enabled():
        return text or ""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
