from __future__ import annotations

import logging
import re


_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)((?:api[-_ ]?key|token|password|cookie)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(https?://api\.telegram\.org/bot)[^/\s?]+"),
)


def redact(value: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: tuple[str, ...] = ()) -> None:
        super().__init__(fmt)
        self._secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self._secrets)


def configure_logging(level: str, secrets: tuple[str, ...] = ()) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", secrets))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
