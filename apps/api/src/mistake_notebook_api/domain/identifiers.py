from __future__ import annotations

from uuid import uuid4

_ALLOWED_PREFIXES = {
    "asset",
    "candidate",
    "detection",
    "region",
    "ocr",
    "revision",
    "problem",
    "publication",
    "req",
}


def new_id(prefix: str) -> str:
    if prefix not in _ALLOWED_PREFIXES:
        raise ValueError(f"Unsupported identifier prefix: {prefix}")
    return f"{prefix}_{uuid4()}"
