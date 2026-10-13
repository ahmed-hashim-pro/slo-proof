"""Alert rules, in TOML.

```toml
[slo]
target = 0.999            # 99.9% of events good

[[rule]]
name = "workbook"
for = "2m"                # optional; as Prometheus `for:`
  [[rule.when]]           # the rule fires if ANY `when` holds...
  burn = 14.4             # ...and a `when` holds if the error ratio is above
  windows = ["1h", "5m"]  # the threshold over EVERY one of its windows
  [[rule.when]]
  burn = 6
  windows = ["6h", "30m"]
```

A ``when`` takes ``burn`` (a multiple of the error budget rate, ``1 -
target``) or ``error_ratio`` (an absolute fraction), never both. That covers
a static threshold (one window, ``error_ratio``), a single-window burn rate,
and the SRE Workbook's multiwindow, multi-burn-rate alerts.

Unknown keys are errors: a misspelt ``windows`` would otherwise leave a rule
that silently never fires.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Any

from .errors import InputError
from .timeutil import format_duration, parse_duration


@dataclass(frozen=True)
class When:
    threshold: float  # error ratio the windows must exceed
    windows: tuple[int, ...]  # minutes
    burn: float | None  # as written, for display

    def describe(self) -> str:
        what = f"burn > {self.burn:g}x" if self.burn is not None else f"error ratio > {self.threshold:.4g}"
        return f"{what} over {' & '.join(format_duration(w * 60) for w in self.windows)}"


@dataclass(frozen=True)
class Rule:
    name: str
    for_minutes: int
    when: tuple[When, ...]

    def describe(self) -> str:
        s = " OR ".join(w.describe() for w in self.when)
        return s + (f", for {format_duration(self.for_minutes * 60)}" if self.for_minutes else "")


@dataclass(frozen=True)
class Config:
    target: float
    period_days: int
    rules: tuple[Rule, ...]

    def rule(self, name: str) -> Rule:
        for r in self.rules:
            if r.name == name:
                return r
        raise KeyError(name)


def _keys(source: str, where: str, table: dict[str, Any], allowed: set[str], required: set[str]) -> None:
    for k in table:
        if k not in allowed:
            raise InputError(source, 0, f"{where}: unknown key '{k}' (allowed: {', '.join(sorted(allowed))})")
    for k in required:
        if k not in table:
            raise InputError(source, 0, f"{where}: missing '{k}'")


def _minutes(source: str, where: str, text: Any) -> int:
    if not isinstance(text, str):
        raise InputError(source, 0, f'{where}: expected a duration string like "5m", got {text!r}')
    try:
        s = parse_duration(text)
    except ValueError as e:
        raise InputError(source, 0, f"{where}: {e}") from None
    if s % 60:
        raise InputError(source, 0, f"{where}: '{text}' is not a whole number of minutes")
    return s // 60


def _number(source: str, where: str, v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise InputError(source, 0, f"{where}: expected a number, got {v!r}")
    return float(v)


def parse(text: str, source: str = "rules") -> Config:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise InputError(source, 0, f"not valid TOML: {e}") from None
    _keys(source, "top level", doc, {"slo", "rule"}, {"slo", "rule"})
    slo = doc["slo"]
    if not isinstance(slo, dict):
        raise InputError(source, 0, "[slo] must be a table")
    _keys(source, "[slo]", slo, {"target", "period"}, {"target"})
    target = _number(source, "[slo] target", slo["target"])
    if not 0 < target < 1:
        raise InputError(source, 0, f"[slo] target must be between 0 and 1 (e.g. 0.999), got {target}")
    period = _minutes(source, "[slo] period", slo.get("period", "30d"))
    if period % 1440:
        raise InputError(source, 0, "[slo] period must be whole days")
    budget = 1 - target

    raw = doc["rule"]
    if not isinstance(raw, list) or not raw:
        raise InputError(source, 0, "define at least one [[rule]]")
    rules: list[Rule] = []
    for i, r in enumerate(raw, start=1):
        where = f"rule {i}"
        if not isinstance(r, dict):
            raise InputError(source, 0, f"{where}: must be a table")
        _keys(source, where, r, {"name", "for", "when"}, {"name", "when"})
        name = r["name"]
        if not isinstance(name, str) or not name.strip():
            raise InputError(source, 0, f"{where}: name must be a non-empty string")
        where = f"rule '{name}'"
        if any(x.name == name for x in rules):
            raise InputError(source, 0, f"{where}: defined twice")
        for_minutes = _minutes(source, f"{where} for", r.get("for", "0m")) if "for" in r else 0
        whens = r["when"]
        if not isinstance(whens, list) or not whens:
            raise InputError(source, 0, f"{where}: needs at least one [[rule.when]]")
        parsed: list[When] = []
        for j, w in enumerate(whens, start=1):
            ww = f"{where} when {j}"
            if not isinstance(w, dict):
                raise InputError(source, 0, f"{ww}: must be a table")
            _keys(source, ww, w, {"burn", "error_ratio", "windows"}, {"windows"})
            if ("burn" in w) == ("error_ratio" in w):
                raise InputError(source, 0, f"{ww}: give exactly one of burn or error_ratio")
            if "burn" in w:
                burn: float | None = _number(source, f"{ww} burn", w["burn"])
                assert burn is not None
                if burn <= 0:
                    raise InputError(source, 0, f"{ww}: burn must be positive")
                threshold = burn * budget
            else:
                burn = None
                threshold = _number(source, f"{ww} error_ratio", w["error_ratio"])
                if not 0 <= threshold < 1:
                    raise InputError(source, 0, f"{ww}: error_ratio must be in [0, 1)")
            if threshold >= 1:
                raise InputError(
                    source, 0, f"{ww}: burn {burn:g}x needs an error ratio of {threshold:.3g}, which is impossible"
                )
            wins = w["windows"]
            if not isinstance(wins, list) or not wins:
                raise InputError(source, 0, f'{ww}: windows must be a non-empty list like ["1h", "5m"]')
            minutes = tuple(_minutes(source, f"{ww} windows", x) for x in wins)
            if any(m <= 0 for m in minutes):
                raise InputError(source, 0, f"{ww}: windows must be at least 1m")
            parsed.append(When(threshold, minutes, burn))
        rules.append(Rule(name, for_minutes, tuple(parsed)))
    return Config(target, period // 1440, tuple(rules))
