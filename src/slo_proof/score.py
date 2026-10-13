"""Scoring a rule's pages against what actually happened.

A page is:

- **true** if it fires while an incident is open (start <= fire <= end);
- **late** if it fires after an incident ended, within ``late_after`` (an
  hour by default). It was about something real, but nobody could act on it;
- **false** otherwise: someone was woken for nothing.

An incident is **detected** if the rule is firing at any moment while it is
open. Detection delay runs from the incident's start to the first such
moment: zero if the rule was already firing when it began. A late page does
not detect anything.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .evaluate import Alert, evaluate
from .incidents import Incident
from .rules import Config, Rule
from .series import Series

LATE_AFTER = 3600


@dataclass(frozen=True)
class IncidentResult:
    incident: Incident
    detected_at: int | None
    # Bad events from the incident's start to detection (or its end, if missed),
    # as a fraction of the SLO period's error budget.
    budget_before_detection: float
    budget_total: float

    @property
    def delay(self) -> int | None:
        return None if self.detected_at is None else self.detected_at - self.incident.start


@dataclass
class RuleResult:
    rule: Rule
    alerts: list[Alert]
    incidents: list[IncidentResult]
    true_pages: list[Alert] = field(default_factory=list)
    late_pages: list[Alert] = field(default_factory=list)
    false_pages: list[Alert] = field(default_factory=list)
    days: float = 0.0
    # Seconds spent firing while no incident was open: pages that should
    # have cleared, or never started.
    firing_outside: int = 0

    @property
    def page_incidents(self) -> list[IncidentResult]:
        return [r for r in self.incidents if r.incident.pages]

    @property
    def detected(self) -> int:
        return sum(1 for r in self.page_incidents if r.detected_at is not None)

    @property
    def recall(self) -> float | None:
        n = len(self.page_incidents)
        return self.detected / n if n else None

    @property
    def median_delay(self) -> float | None:
        d = [r.delay for r in self.page_incidents if r.delay is not None]
        return statistics.median(d) if d else None

    @property
    def pages(self) -> int:
        return len(self.alerts)

    @property
    def precision(self) -> float | None:
        return len(self.true_pages) / self.pages if self.pages else None

    @property
    def false_per_week(self) -> float:
        return len(self.false_pages) / (self.days / 7) if self.days else 0.0


def budget_events(series: Series, target: float, period_days: int) -> float:
    """The error budget for one SLO period, in bad events, at the data's
    average traffic."""
    per_minute = series.total_in(0, len(series)) / len(series)
    return (1 - target) * per_minute * period_days * 1440


def score(series: Series, incidents: list[Incident], cfg: Config, rule: Rule) -> RuleResult:
    alerts = evaluate(series, rule)
    budget = budget_events(series, cfg.target, cfg.period_days)
    results = []
    for inc in incidents:
        detected: int | None = None
        for a in alerts:
            if a.fired <= inc.end and (a.resolved is None or a.resolved > inc.start):
                at = max(a.fired, inc.start)
                if detected is None or at < detected:
                    detected = at
        a_i, e_i = series.index(inc.start), series.index(inc.end)
        until = e_i if detected is None else series.index(detected)
        results.append(
            IncidentResult(
                inc,
                detected,
                series.bad_in(a_i, until) / budget if budget else 0.0,
                series.bad_in(a_i, e_i) / budget if budget else 0.0,
            )
        )
    rr = RuleResult(rule, alerts, results, days=len(series) / 1440)
    for a in alerts:
        end = series.end if a.resolved is None else a.resolved
        inside = sum(max(0, min(end, i.end) - max(a.fired, i.start)) for i in incidents)
        rr.firing_outside += end - a.fired - inside
    for a in alerts:
        if any(i.start <= a.fired <= i.end for i in incidents):
            rr.true_pages.append(a)
        elif any(i.end < a.fired <= i.end + LATE_AFTER for i in incidents):
            rr.late_pages.append(a)
        else:
            rr.false_pages.append(a)
    return rr


def rank(results: list[RuleResult]) -> list[RuleResult]:
    """Best first: catch the most page incidents, then wake people least for
    nothing, then catch them soonest."""
    return sorted(
        results,
        key=lambda r: (
            -(r.recall or 0.0),
            r.false_per_week,
            r.median_delay if r.median_delay is not None else float("inf"),
            r.rule.name,
        ),
    )
