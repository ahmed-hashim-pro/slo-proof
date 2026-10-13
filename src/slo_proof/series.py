"""The SLI: good and total events per minute.

```
# comments and blank lines are ignored
timestamp,good,total
2026-03-01T00:00:00Z,598,600
2026-03-01T00:01:00Z,611,611
```

Each row counts the events in the minute starting at its timestamp. Rows
must be one minute apart with no gaps: a missing minute could mean "no
traffic" or "the exporter was down", and the answer changes what an alert
would have done, so the file has to say which (a row of zeros).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .errors import InputError
from .timeutil import format_time, parse_time

HEADER = ["timestamp", "good", "total"]


@dataclass
class Series:
    start: int  # unix seconds of the first minute
    good: list[int]
    total: list[int]
    _bad_ps: list[int] = field(init=False, repr=False)
    _total_ps: list[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.good) != len(self.total):
            raise ValueError("good and total differ in length")
        self._bad_ps = [0]
        self._total_ps = [0]
        for g, t in zip(self.good, self.total, strict=True):
            self._bad_ps.append(self._bad_ps[-1] + t - g)
            self._total_ps.append(self._total_ps[-1] + t)

    def __len__(self) -> int:
        return len(self.total)

    @property
    def end(self) -> int:
        """Unix seconds just after the last minute."""
        return self.start + 60 * len(self)

    def index(self, ts: int) -> int:
        """Minute index containing ``ts`` (may be out of range)."""
        return (ts - self.start) // 60

    def bad_in(self, a: int, b: int) -> int:
        """Bad events in minutes [a, b), clipped to the data."""
        a, b = max(0, a), min(len(self), b)
        return self._bad_ps[b] - self._bad_ps[a] if b > a else 0

    def total_in(self, a: int, b: int) -> int:
        a, b = max(0, a), min(len(self), b)
        return self._total_ps[b] - self._total_ps[a] if b > a else 0

    def ratio(self, a: int, b: int) -> float | None:
        """Error ratio over minutes [a, b); None when there was no traffic,
        as Prometheus would produce NaN, which compares false."""
        t = self.total_in(a, b)
        return None if t == 0 else self.bad_in(a, b) / t

    def to_csv(self) -> str:
        out = io.StringIO()
        out.write(",".join(HEADER) + "\n")
        for i, (g, t) in enumerate(zip(self.good, self.total, strict=True)):
            ts = self.start + 60 * i
            out.write(f"{format_time(ts).replace(' ', 'T')}:00Z,{g},{t}\n")
        return out.getvalue()


def _rows(text: str) -> list[tuple[int, list[str]]]:
    rows = []
    for n, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if s and not s.startswith("#"):
            rows.append((n, next(csv.reader([s]))))
    return rows


def parse(text: str, source: str = "series") -> Series:
    rows = _rows(text)
    if not rows:
        raise InputError(source, 0, "no data")
    n, header = rows[0]
    if [h.strip() for h in header] != HEADER:
        raise InputError(source, n, f"expected header '{','.join(HEADER)}', got '{','.join(header)}'")
    if len(rows) < 2:
        raise InputError(source, 0, "no data rows")
    good: list[int] = []
    total: list[int] = []
    start = prev = 0
    for n, f in rows[1:]:
        if len(f) != 3:
            raise InputError(source, n, f"expected 3 fields, got {len(f)}")
        try:
            ts = parse_time(f[0])
        except ValueError as e:
            raise InputError(source, n, str(e)) from None
        if ts % 60:
            raise InputError(source, n, f"{f[0].strip()} is not on a minute boundary")
        try:
            g, t = int(f[1]), int(f[2])
        except ValueError:
            raise InputError(source, n, f"counts must be whole numbers, got '{f[1]}', '{f[2]}'") from None
        if g < 0 or t < 0:
            raise InputError(source, n, "counts must not be negative")
        if g > t:
            raise InputError(source, n, f"good ({g}) exceeds total ({t})")
        if not good:
            start = ts
        elif ts != prev + 60:
            what = "duplicate or out of order" if ts <= prev else f"gap of {(ts - prev) // 60 - 1} minutes"
            raise InputError(
                source,
                n,
                f"{what} after {format_time(prev)}; write a row of zeros for a minute with no traffic",
            )
        prev = ts
        good.append(g)
        total.append(t)
    return Series(start, good, total)
