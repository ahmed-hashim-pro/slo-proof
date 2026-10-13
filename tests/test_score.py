from helpers import T0, rule, series

from slo_proof.incidents import Incident
from slo_proof.rules import Config
from slo_proof.score import rank, score


def cfg(r):
    return Config(0.99, 30, (r,))


def mins(k: int) -> int:
    return T0 + 60 * k


def test_true_late_and_false_pages():
    bad = [0] * 300
    for k in (10, 11, 100, 200):
        bad[k] = 50
    s = series(bad)
    incs = [
        Incident(mins(9), mins(20), "page", "real"),
        Incident(mins(150), mins(170), "page", "missed"),
        Incident(mins(195), mins(199), "ticket", "over"),
    ]
    r = rule(0.1)
    rr = score(s, incs, cfg(r), r)
    assert len(rr.true_pages) == 1  # fires at k=11
    assert len(rr.late_pages) == 1  # k=201, within an hour of "over" ending
    assert len(rr.false_pages) == 1  # k=101
    real, missed, _ = rr.incidents
    assert real.delay == 120 and missed.delay is None
    assert rr.recall == 0.5 and rr.detected == 1
    assert rr.precision == 1 / 3
    assert rr.firing_outside == 2 * 60  # the false and the late page, a minute each


def test_already_firing_at_start_is_detected_with_no_delay():
    bad = [0] * 50
    for k in range(5, 20):
        bad[k] = 50
    s = series(bad)
    r = rule(0.1)
    rr = score(s, [Incident(mins(10), mins(15), "page", "x")], cfg(r), r)
    assert rr.incidents[0].delay == 0


def test_budget_shares():
    s = series([0, 10, 10, 0], total=100)
    r = rule(0.5)
    rr = score(s, [Incident(mins(1), mins(3), "page", "x")], cfg(r), r)
    # Budget for 30 days at 100/min, 1%: 43200 events.
    assert abs(rr.incidents[0].budget_total - 20 / 43200) < 1e-12
    assert rr.incidents[0].budget_before_detection == rr.incidents[0].budget_total  # never fired


def test_rank_prefers_recall_then_quiet_then_fast():
    s = series([0] * 20 + [50] * 3 + [0] * 20)
    inc = [Incident(mins(20), mins(23), "page", "x")]
    good = rule(0.1, name="good")
    slow = rule(0.1, for_minutes=2, name="slow")
    blind = rule(0.9, name="blind")
    ranked = rank([score(s, inc, cfg(r), r) for r in (blind, slow, good)])
    assert [r.rule.name for r in ranked] == ["good", "slow", "blind"]
