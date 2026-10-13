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

import re
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


_HEADER = re.compile(r"\[\[?\s*([A-Za-z0-9_.\s-]+?)\s*\]\]?\s*(#.*)?$")
_KEY = re.compile(r"([A-Za-z0-9_-]+)\s*=")
_AT = re.compile(r"\s*\(at (?:line (\d+), column \d+|end of document)\)$")


class _Lines:
    """Where each table and key starts, so an error can name a line.

    tomllib keeps no positions, so this scans the text for table headers and
    ``key =`` lines. It understands the layout rules files use; anything it
    can't place falls back to the enclosing table, or to no line at all.
    """

    def __init__(self, text: str) -> None:
        self.at: dict[tuple[str | int, ...], int] = {}
        table: tuple[str | int, ...] = ()
        counts: dict[tuple[str | int, ...], int] = {}
        in_string = False
        for n, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            quotes = line.count('"""') + line.count("'''")
            if in_string or not line or line.startswith("#"):
                in_string ^= quotes % 2 == 1
                continue
            in_string = quotes % 2 == 1
            if m := _HEADER.match(line):
                names = [p.strip() for p in m.group(1).split(".")]
                if line.startswith("[["):
                    # [[rule.when]] belongs to the latest [[rule]]: ("rule", i, "when", j)
                    parent = table[: 2 * (len(names) - 1)]
                    key = (*parent, names[-1])
                    counts[key] = counts.get(key, 0) + 1
                    table = (*key, counts[key])
                else:
                    table = tuple(names)
                self.at.setdefault(table, n)
            elif m := _KEY.match(line):
                self.at.setdefault((*table, m.group(1)), n)

    def line(self, *path: str | int) -> int:
        while path:
            if path in self.at:
                return self.at[path]
            path = path[:-1]
        return 0


def _keys(
    source: str,
    lines: _Lines,
    path: tuple[str | int, ...],
    where: str,
    table: dict[str, Any],
    allowed: set[str],
    required: set[str],
) -> None:
    for k in table:
        if k not in allowed:
            raise InputError(
                source, lines.line(*path, k), f"{where}: unknown key '{k}' (allowed: {', '.join(sorted(allowed))})"
            )
    for k in required:
        if k not in table:
            raise InputError(source, lines.line(*path), f"{where}: missing '{k}'")


def _minutes(source: str, line: int, where: str, text: Any) -> int:
    if not isinstance(text, str):
        raise InputError(source, line, f'{where}: expected a duration string like "5m", got {text!r}')
    try:
        s = parse_duration(text)
    except ValueError as e:
        raise InputError(source, line, f"{where}: {e}") from None
    if s % 60:
        raise InputError(source, line, f"{where}: '{text}' is not a whole number of minutes")
    return s // 60


def _number(source: str, line: int, where: str, v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise InputError(source, line, f"{where}: expected a number, got {v!r}")
    return float(v)


def parse(text: str, source: str = "rules") -> Config:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        m = _AT.search(str(e))
        msg = str(e)[: m.start()] if m else str(e)
        line = (int(m.group(1)) if m.group(1) else max(len(text.splitlines()), 1)) if m else 0
        raise InputError(source, line, f"not valid TOML: {msg}") from None
    lines = _Lines(text)
    _keys(source, lines, (), "top level", doc, {"slo", "rule"}, {"slo", "rule"})
    slo = doc["slo"]
    if not isinstance(slo, dict):
        raise InputError(source, lines.line("slo"), "[slo] must be a table")
    _keys(source, lines, ("slo",), "[slo]", slo, {"target", "period"}, {"target"})
    target = _number(source, lines.line("slo", "target"), "[slo] target", slo["target"])
    if not 0 < target < 1:
        raise InputError(
            source, lines.line("slo", "target"), f"[slo] target must be between 0 and 1 (e.g. 0.999), got {target}"
        )
    period = _minutes(source, lines.line("slo", "period"), "[slo] period", slo.get("period", "30d"))
    if period % 1440:
        raise InputError(source, lines.line("slo", "period"), "[slo] period must be whole days")
    budget = 1 - target

    raw = doc["rule"]
    if not isinstance(raw, list) or not raw:
        raise InputError(source, lines.line("rule"), "define at least one [[rule]]")
    rules: list[Rule] = []
    for i, r in enumerate(raw, start=1):
        where = f"rule {i}"
        at = ("rule", i)
        if not isinstance(r, dict):
            raise InputError(source, lines.line(*at), f"{where}: must be a table")
        _keys(source, lines, at, where, r, {"name", "for", "when"}, {"name", "when"})
        name = r["name"]
        if not isinstance(name, str) or not name.strip():
            raise InputError(source, lines.line(*at, "name"), f"{where}: name must be a non-empty string")
        where = f"rule '{name}'"
        if any(x.name == name for x in rules):
            raise InputError(source, lines.line(*at, "name"), f"{where}: defined twice")
        for_minutes = _minutes(source, lines.line(*at, "for"), f"{where} for", r["for"]) if "for" in r else 0
        whens = r["when"]
        if not isinstance(whens, list) or not whens:
            raise InputError(source, lines.line(*at, "when"), f"{where}: needs at least one [[rule.when]]")
        parsed: list[When] = []
        for j, w in enumerate(whens, start=1):
            ww = f"{where} when {j}"
            wat = (*at, "when", j)
            if not isinstance(w, dict):
                raise InputError(source, lines.line(*wat), f"{ww}: must be a table")
            _keys(source, lines, wat, ww, w, {"burn", "error_ratio", "windows"}, {"windows"})
            if ("burn" in w) == ("error_ratio" in w):
                raise InputError(source, lines.line(*wat), f"{ww}: give exactly one of burn or error_ratio")
            if "burn" in w:
                line = lines.line(*wat, "burn")
                burn: float | None = _number(source, line, f"{ww} burn", w["burn"])
                assert burn is not None
                if burn <= 0:
                    raise InputError(source, line, f"{ww}: burn must be positive")
                threshold = burn * budget
            else:
                burn = None
                line = lines.line(*wat, "error_ratio")
                threshold = _number(source, line, f"{ww} error_ratio", w["error_ratio"])
                if not 0 <= threshold < 1:
                    raise InputError(source, line, f"{ww}: error_ratio must be in [0, 1)")
            if threshold >= 1:
                raise InputError(
                    source, line, f"{ww}: burn {burn:g}x needs an error ratio of {threshold:.3g}, which is impossible"
                )
            wins = w["windows"]
            line = lines.line(*wat, "windows")
            if not isinstance(wins, list) or not wins:
                raise InputError(source, line, f'{ww}: windows must be a non-empty list like ["1h", "5m"]')
            minutes = tuple(_minutes(source, line, f"{ww} windows", x) for x in wins)
            if any(m <= 0 for m in minutes):
                raise InputError(source, line, f"{ww}: windows must be at least 1m")
            parsed.append(When(threshold, minutes, burn))
        rules.append(Rule(name, for_minutes, tuple(parsed)))
    return Config(target, period // 1440, tuple(rules))
