"""Secret redaction for anything written to reports, logs or terminal output."""

from __future__ import annotations

import os
import re

REDACTED = "[REDACTED]"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("anthropic-api-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{20,}=*")),
    (
        "generic-assignment",
        re.compile(
            r"(?i)(?:\b|_)(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b"
            r"\s*[:=]\s*['\"]?([^\s'\"]{8,})"
        ),
    ),
]

_SENSITIVE_ENV = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)")


def _env_secret_values() -> list[str]:
    return [v for k, v in os.environ.items() if _SENSITIVE_ENV.search(k) and len(v) >= 8]


def redact(text: str, generic: bool = True) -> str:
    """Redact secrets. generic=False skips the heuristic `name = value` rule, for content (like
    patches) where a false positive would corrupt the artifact."""
    if not text:
        return text
    for value in _env_secret_values():
        text = text.replace(value, REDACTED)
    for name, pattern in SECRET_PATTERNS:
        if name == "generic-assignment":
            if not generic:
                continue
            text = pattern.sub(lambda m: m.group(0).replace(m.group(1), REDACTED), text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n…[truncated {len(text) - limit} chars]…\n{text[-half:]}"
