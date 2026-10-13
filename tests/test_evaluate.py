import itertools

from helpers import T0, rule, series
from hypothesis import given, settings
from hypothesis import strategies as st

from slo_proof.evaluate import Alert, evaluate
from slo_proof.rules import Rule, When
from slo_proof.series import Series


def at(k: int) -> int:
    return T0 + 60 * k


def test_fires_at_once_without_for():
    # Minute 3 is bad; the evaluation at the end of minute 3 (k=4) fires, k=5 resolves.
    s = series([0, 0, 0, 50, 0, 0])
    assert evaluate(s, rule(0.1)) == [Alert(at(4), at(5))]


def test_for_needs_every_evaluation_in_between():
    s = series([0, 50, 50, 50, 0, 50, 50, 0])
    # Holds at k=2,3,4 and k=6,7. With for=2m only the first run lasts long enough.
    assert evaluate(s, rule(0.1, for_minutes=2)) == [Alert(at(4), at(5))]
    # With for=1m both runs fire: a false evaluation resets the pending clock.
    assert evaluate(s, rule(0.1, for_minutes=1)) == [Alert(at(3), at(5)), Alert(at(7), at(8))]


def test_still_firing_at_the_end():
    assert evaluate(series([0, 50, 50]), rule(0.1)) == [Alert(at(2), None)]


def test_no_traffic_never_fires():
    # Even a threshold every ratio exceeds: a window with no events has no
    # ratio, as PromQL's 0/0 is NaN and NaN > x is false.
    s = series([0, 0, 0], total=[100, 0, 0])
    assert evaluate(s, rule(-1.0)) == [Alert(at(1), at(2))]


def test_all_windows_must_hold():
    # Short window high, long window low: no fire.
    s = series([0] * 59 + [10])
    assert evaluate(s, rule(0.05, windows=(60, 1))) == []
    assert evaluate(s, rule(0.05, windows=(1,))) == [Alert(at(60), None)]


def test_any_when_may_hold():
    s = series([0, 50, 0])
    r = Rule("r", 0, (When(0.9, (1,), None), When(0.1, (1,), None)))
    assert evaluate(s, r) == [Alert(at(2), at(3))]


# The evaluator against a reference written another way: sum the window by
# hand at every evaluation, and fire wherever the expression held at every
# evaluation of the last `for` minutes.
def reference(s: Series, r: Rule) -> list[Alert]:
    n = len(s)
    bad = [t - g for g, t in zip(s.good, s.total, strict=True)]

    def holds(k: int) -> bool:
        for w in r.when:
            ok = True
            for m in w.windows:
                lo = max(0, k - m)
                tot = sum(s.total[lo:k])
                if tot == 0 or not sum(bad[lo:k]) / tot > w.threshold:
                    ok = False
            if ok:
                return True
        return False

    h = {k: holds(k) for k in range(1, n + 1)}
    firing = [k - r.for_minutes >= 1 and all(h[j] for j in range(k - r.for_minutes, k + 1)) for k in range(1, n + 1)]
    out, start = [], None
    for k, f in enumerate(firing, start=1):
        if f and start is None:
            start = k
        if not f and start is not None:
            out.append(Alert(at(start), at(k)))
            start = None
    if start is not None:
        out.append(Alert(at(start), None))
    return out


@st.composite
def cases(draw):
    n = draw(st.integers(1, 80))
    total = draw(st.lists(st.integers(0, 20), min_size=n, max_size=n))
    bad = [draw(st.integers(0, t)) for t in total]
    whens = draw(
        st.lists(
            st.tuples(st.sampled_from([0.0, 0.05, 0.2, 0.5]), st.lists(st.integers(1, 30), min_size=1, max_size=3)),
            min_size=1,
            max_size=3,
        )
    )
    r = Rule("r", draw(st.integers(0, 6)), tuple(When(th, tuple(ws), None) for th, ws in whens))
    return Series(T0, [t - b for t, b in zip(total, bad, strict=True)], total), r


@settings(max_examples=400, deadline=None)
@given(cases())
def test_matches_reference(case):
    s, r = case
    assert evaluate(s, r) == reference(s, r)


@settings(max_examples=200, deadline=None)
@given(cases())
def test_alerts_are_ordered_and_disjoint(case):
    s, r = case
    alerts = evaluate(s, r)
    for a, b in itertools.pairwise(alerts):
        assert a.resolved is not None and a.fired < a.resolved <= b.fired
    # A longer `for` never fires earlier or more often.
    longer = evaluate(s, Rule(r.name, r.for_minutes + 3, r.when))
    assert len(longer) <= len(alerts)
