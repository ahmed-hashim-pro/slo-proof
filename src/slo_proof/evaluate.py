"""Replaying a rule the way Prometheus would have evaluated it.

The rule is evaluated once a minute, at the end of each minute of data. At
evaluation time t (the end of minute k), a window of W minutes covers
minutes [k-W, k): the last W complete minutes. The error ratio over it is
bad events / total events, as a ``sum(increase(bad[W])) /
sum(increase(total[W]))`` over per-minute recording rules would give, with
three choices that match Prometheus:

- **No traffic in a window means no value.** Division by zero is NaN in
  PromQL, and NaN > x is false. A window with no events never fires.
- **Early on, a window uses the data there is**, as a range selector does
  when it reaches back past the first sample.
- **``for`` works like Prometheus's.** The first evaluation where the
  expression holds makes the alert pending; it fires at the first evaluation
  at least ``for`` later at which the expression still holds, and every
  evaluation in between must hold too. With ``for = 0`` it fires at once. It
  resolves at the first evaluation where the expression is false, and a later
  true evaluation starts a new pending period.

One simplification, stated: Prometheus's ``rate()`` and ``increase()``
extrapolate to the window's edges from the samples inside it; this sums
whole minutes exactly. With one-minute recording rules the difference is a
fraction of a minute's events at each edge.

Each transition to firing is one page. Alertmanager's grouping and repeat
intervals are not modelled: they change how often you are reminded, not
whether or when the first page goes out.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import Rule
from .series import Series


@dataclass(frozen=True)
class Alert:
    fired: int  # unix seconds of the evaluation that fired
    resolved: int | None  # of the evaluation that resolved; None if still firing at the end


def holds(series: Series, rule: Rule, k: int) -> bool:
    """Does the rule's expression hold at the evaluation ending minute k-1?"""
    for w in rule.when:
        ok = True
        for minutes in w.windows:
            r = series.ratio(k - minutes, k)
            if r is None or not r > w.threshold:
                ok = False
                break
        if ok:
            return True
    return False


def evaluate(series: Series, rule: Rule) -> list[Alert]:
    alerts: list[Alert] = []
    pending_since: int | None = None
    fired_at: int | None = None
    for k in range(1, len(series) + 1):
        t = series.start + 60 * k
        if holds(series, rule, k):
            if pending_since is None:
                pending_since = k
            if fired_at is None and k - pending_since >= rule.for_minutes:
                fired_at = t
        else:
            pending_since = None
            if fired_at is not None:
                alerts.append(Alert(fired_at, t))
                fired_at = None
    if fired_at is not None:
        alerts.append(Alert(fired_at, None))
    return alerts
