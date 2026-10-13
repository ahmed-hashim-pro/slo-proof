from slo_proof.rules import Rule, When
from slo_proof.series import Series

T0 = 1772409600  # 2026-03-02T00:00:00Z


def series(bad: list[int], total: int | list[int] = 100) -> Series:
    totals = total if isinstance(total, list) else [total] * len(bad)
    return Series(T0, [t - b for t, b in zip(totals, bad, strict=True)], totals)


def rule(threshold: float, windows: tuple[int, ...] = (1,), for_minutes: int = 0, name: str = "r") -> Rule:
    return Rule(name, for_minutes, (When(threshold, windows, None),))
