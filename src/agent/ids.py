from __future__ import annotations
import re

_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


def safe_identifier(value: str, label: str = "identifier") -> str:
    value = str(value or "")
    if not _SAFE.fullmatch(value):
        raise ValueError(f"unsafe {label}: expected 1-160 chars [A-Za-z0-9_-]")
    return value
