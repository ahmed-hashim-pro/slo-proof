"""A month of synthetic SLI data whose incidents are known exactly.

Real incident records are incomplete and their timestamps are approximate,
so they can only tell you how a rule did against what someone wrote down.
A synthetic month can tell you how it did against what happened. The
traffic has a daily and weekly rhythm and Poisson noise, the background error
ratio sits at a fifth of the budget, and the month holds one of each kind of
trouble that separates alert rules:

| kind | shape | severity |
| --- | --- | --- |
| hard outage | every request fails for 4 minutes | page |
| sharp spike | a quarter of requests fail for 10 minutes | page |
| partial outage | one shard in ten down (10% errors) for 40 minutes | page |
| flapping | 8% errors for 4 minutes in every 10, for an hour | page |
| slow burn | 0.7% errors (7x the budget rate) for 8 hours | page |
| very slow burn | 0.25% errors (2.5x) for 36 hours | ticket |
| short blip | half of requests fail for 2 minutes | page |
| traffic dips | traffic falls to ~1% at night while health checks fail | not an incident |

The traffic dips are the trap: a handful of failed health checks out of a
handful of requests is a huge error ratio, and almost no budget.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .incidents import Incident
from .series import Series

START = 1772409600  # 2026-03-02T00:00:00Z, a Monday
BASELINE_ERROR = 0.0002


@dataclass(frozen=True)
class _Spec:
    day: int
    minute: int  # of the day
    length: int  # minutes
    severity: str
    name: str
    kind: str


SPECS = (
    _Spec(2, 14 * 60, 4, "page", "hard outage", "outage"),
    _Spec(5, 10 * 60 + 30, 10, "page", "sharp spike", "spike"),
    _Spec(9, 3 * 60, 40, "page", "partial outage", "partial"),
    _Spec(12, 16 * 60, 60, "page", "flapping dependency", "flap"),
    _Spec(16, 8 * 60, 8 * 60, "page", "slow burn", "slow"),
    _Spec(20, 0, 36 * 60, "ticket", "very slow burn", "very_slow"),
    _Spec(25, 20 * 60, 2, "page", "short blip", "blip"),
)
DIPS = ((6, 2 * 60), (13, 2 * 60 + 30), (23, 3 * 60))
DIP_LENGTH = 40


def _error_ratio(kind: str, offset: int) -> float:
    match kind:
        case "outage":
            return 1.0
        case "spike":
            return 0.25
        case "partial":
            return 0.10
        case "flap":
            return 0.08 if offset % 10 < 4 else BASELINE_ERROR
        case "slow":
            return 0.007
        case "very_slow":
            return 0.0025
        case "blip":
            return 0.5
    raise ValueError(kind)


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30:
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def generate(seed: int = 7, days: int = 28, rate: float = 600.0) -> tuple[Series, list[Incident]]:
    """Per-minute traffic and the ground-truth incidents. Incident start times
    move by up to an hour with the seed; their kinds and order do not."""
    rng = random.Random(seed)
    n = days * 1440
    shifted = [
        _Spec(s.day, s.minute + rng.randint(-60, 60), s.length, s.severity, s.name, s.kind)
        for s in SPECS
        if s.day < days
    ]
    ratio = [BASELINE_ERROR * (0.5 + rng.random()) for _ in range(n)]
    for s in shifted:
        a = s.day * 1440 + s.minute
        for i in range(s.length):
            if 0 <= a + i < n:
                ratio[a + i] = max(ratio[a + i], _error_ratio(s.kind, i))
    dip = [False] * n
    for d, m in DIPS:
        for i in range(DIP_LENGTH):
            if d * 1440 + m + i < n:
                dip[d * 1440 + m + i] = True

    good, total = [], []
    for i in range(n):
        minute_of_day, day = i % 1440, i // 1440
        daily = 1 + 0.5 * math.sin(2 * math.pi * (minute_of_day - 9 * 60) / 1440)
        weekly = 0.7 if day % 7 >= 5 else 1.0
        if dip[i]:
            t = _poisson(rng, 6)
            bad = min(t, _poisson(rng, 1.2))  # failing health checks
        else:
            t = _poisson(rng, rate * daily * weekly)
            bad = min(t, _poisson(rng, t * ratio[i]))
        good.append(t - bad)
        total.append(t)
    incidents = [
        Incident(
            START + 60 * (s.day * 1440 + s.minute),
            START + 60 * (s.day * 1440 + s.minute + s.length),
            s.severity,
            s.name,
        )
        for s in shifted
    ]
    return Series(START, good, total), incidents
