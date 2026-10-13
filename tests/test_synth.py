from pathlib import Path

from slo_proof import incidents, rules, series, synth
from slo_proof.score import score

ROOT = Path(__file__).parent.parent
CFG = rules.parse((ROOT / "examples" / "rules.toml").read_text())


def test_deterministic_and_valid():
    a, ia = synth.generate(3, days=10)
    b, ib = synth.generate(3, days=10)
    assert a == b and ia == ib
    assert len(a) == 10 * 1440
    assert series.parse(a.to_csv()) == a
    assert incidents.parse(incidents.to_csv(ia), a) == ia


def test_committed_example_is_what_synth_writes():
    s, inc = synth.generate(7, 28)
    head = "# synthetic: slo-proof synth --seed 7 --days 28\n"
    assert (ROOT / "examples" / "sli.csv").read_text() == head + s.to_csv(), "run `make examples`"
    assert (ROOT / "examples" / "incidents.csv").read_text() == head + incidents.to_csv(inc)


def test_the_readme_findings_hold_across_seeds():
    """The README's claims, on more months than the one it shows."""
    for seed in range(1, 9):
        s, inc = synth.generate(seed)
        res = {r.name: score(s, inc, CFG, r) for r in CFG.rules}
        missed = {n: {i.incident.name for i in rr.page_incidents if i.detected_at is None} for n, rr in res.items()}
        assert missed["workbook-multiwindow"] == set(), seed
        assert not res["workbook-multiwindow"].false_pages, seed
        assert missed["fast-burn-only"] == {"slow burn"}, (seed, missed)
        assert {"hard outage", "short blip", "slow burn"} <= missed["static-1pct"], (seed, missed)
        assert len(res["static-1pct"].false_pages) >= 2, seed  # the traffic dips
        assert res["6x-over-6h"].firing_outside > 8 * 3600, seed
