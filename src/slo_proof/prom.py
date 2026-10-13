"""Turning Prometheus range-query exports into the per-minute CSV.

Export two range queries at a 60 s step, e.g. from ``/api/v1/query_range``:

    sum(increase(http_requests_total[1m]))
    sum(increase(http_requests_total{code=~"5.."}[1m]))

Each value at time t is the increase over the minute ending at t, so it
becomes the row for the minute starting at t - 60. Several series in one
result are summed. ``increase()`` extrapolates, so values are fractional;
they are rounded to whole events.
"""

from __future__ import annotations

import itertools
import json
import math

from .errors import InputError
from .series import Series


def _load(text: str, source: str) -> dict[int, float]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise InputError(source, e.lineno, f"not JSON: {e.msg}") from None
    try:
        if doc["status"] != "success":
            raise InputError(source, 0, f"query status is {doc['status']!r}")
        data = doc["data"]
        if data["resultType"] != "matrix":
            raise InputError(source, 0, f"expected a range query (matrix), got {data['resultType']!r}")
        result = data["result"]
    except (KeyError, TypeError):
        raise InputError(source, 0, "not a Prometheus query_range response") from None
    if not result:
        raise InputError(source, 0, "the query returned no series")
    out: dict[int, float] = {}
    for series in result:
        for pair in series.get("values", []):
            try:
                ts, v = float(pair[0]), float(pair[1])
            except (TypeError, ValueError, IndexError):
                raise InputError(source, 0, f"bad sample {pair!r}") from None
            if not math.isfinite(v) or v < 0:
                raise InputError(source, 0, f"sample at {ts} is {pair[1]}; increases must be finite and non-negative")
            if ts != int(ts) or int(ts) % 60:
                raise InputError(source, 0, f"sample time {ts} is not on a minute; query with step=60")
            out[int(ts)] = out.get(int(ts), 0.0) + v
    return out


def to_series(total_text: str, bad_text: str, total_source: str = "total", bad_source: str = "bad") -> Series:
    total = _load(total_text, total_source)
    bad = _load(bad_text, bad_source)
    if set(total) != set(bad):
        missing = sorted(set(total) ^ set(bad))[:3]
        raise InputError(
            bad_source, 0, f"the two queries cover different times (e.g. {missing}); use the same start, end and step"
        )
    times = sorted(total)
    for a, b in itertools.pairwise(times):
        if b != a + 60:
            raise InputError(
                total_source,
                0,
                f"samples at {a} and {b} are not one minute apart; Prometheus omits steps with no data, so fill the gap",
            )
    t_counts = [round(total[t]) for t in times]
    b_counts = [min(round(bad[t]), tc) for t, tc in zip(times, t_counts, strict=True)]
    return Series(times[0] - 60, [t - b for t, b in zip(t_counts, b_counts, strict=True)], t_counts)
