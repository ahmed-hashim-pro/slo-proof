"""Timestamps and durations, parsed strictly."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_DURATION = re.compile(r"^(\d+)(s|m|h|d|w)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_time(text: str) -> int:
    """ISO 8601 with a timezone (``2026-03-01T14:00:00Z``) or unix seconds.

    A timestamp without a timezone is refused: guessing UTC or local time is
    how an incident ends up an hour away from the data that shows it.
    """
    text = text.strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"'{text}' is not an ISO 8601 time or unix seconds") from e
    if dt.tzinfo is None:
        raise ValueError(f"'{text}' has no timezone; add Z or an offset")
    return int(dt.timestamp())


def format_time(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M")


def parse_duration(text: str) -> int:
    """``90s``, ``5m``, ``1h``, ``3d``, ``1w`` to seconds."""
    m = _DURATION.match(text.strip())
    if not m:
        raise ValueError(f"'{text}' is not a duration like 5m, 1h or 3d")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 3600:
        return f"{seconds // 60}m"
    h, m = divmod(seconds // 60, 60)
    if h < 48:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    d, h = divmod(h, 24)
    return f"{d}d{h}h" if h else f"{d}d"
