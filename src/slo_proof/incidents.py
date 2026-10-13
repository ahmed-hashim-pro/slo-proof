"""Incidents: what actually happened, and which of it deserved a page.

```
start,end,severity,name
2026-03-02T14:00:00Z,2026-03-02T14:04:00Z,page,checkout outage
2026-03-20T00:00:00Z,2026-03-21T12:00:00Z,ticket,slow disk on one shard
```

``page`` incidents are the ones a rule must catch: they count toward recall.
``ticket`` incidents are real but could wait for working hours; a page
during one is not counted as false, and a miss is reported but not counted
against the rule.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

from .errors import InputError
from .series import Series
from .timeutil import format_time, parse_time

HEADER = ["start", "end", "severity", "name"]
SEVERITIES = ("page", "ticket")


@dataclass(frozen=True)
class Incident:
    start: int
    end: int
    severity: str
    name: str

    @property
    def pages(self) -> bool:
        return self.severity == "page"


def parse(text: str, series: Series | None = None, source: str = "incidents") -> list[Incident]:
    rows = []
    for n, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if s and not s.startswith("#"):
            rows.append((n, next(csv.reader([s]))))
    if not rows:
        raise InputError(source, 0, "no header")
    n, header = rows[0]
    if [h.strip() for h in header] != HEADER:
        raise InputError(source, n, f"expected header '{','.join(HEADER)}', got '{','.join(header)}'")
    out: list[Incident] = []
    for n, f in rows[1:]:
        if len(f) != 4:
            raise InputError(source, n, f"expected 4 fields, got {len(f)}")
        try:
            start, end = parse_time(f[0]), parse_time(f[1])
        except ValueError as e:
            raise InputError(source, n, str(e)) from None
        if end <= start:
            raise InputError(source, n, "end is not after start")
        severity = f[2].strip()
        if severity not in SEVERITIES:
            raise InputError(source, n, f"severity '{severity}' is not one of {', '.join(SEVERITIES)}")
        name = f[3].strip()
        if not name:
            raise InputError(source, n, "incident has no name")
        if series is not None and (start < series.start or end > series.end):
            raise InputError(
                source,
                n,
                f"'{name}' ({format_time(start)} to {format_time(end)}) is outside the data "
                f"({format_time(series.start)} to {format_time(series.end)})",
            )
        inc = Incident(start, end, severity, name)
        for other in out:
            if inc.start < other.end and other.start < inc.end:
                raise InputError(source, n, f"'{name}' overlaps '{other.name}'; a page could not be attributed")
        out.append(inc)
    out.sort(key=lambda i: i.start)
    return out


def to_csv(incidents: list[Incident]) -> str:
    def iso(ts: int) -> str:
        return format_time(ts).replace(" ", "T") + ":00Z"

    lines = [",".join(HEADER)]
    lines += [f"{iso(i.start)},{iso(i.end)},{i.severity},{i.name}" for i in incidents]
    return "\n".join(lines) + "\n"
