from pathlib import Path

import pytest

from slo_proof.errors import InputError
from slo_proof.rules import parse

EXAMPLE = Path(__file__).parent.parent / "examples" / "rules.toml"


def test_example_rules():
    cfg = parse(EXAMPLE.read_text())
    assert cfg.target == 0.999 and cfg.period_days == 30
    wb = cfg.rule("workbook-multiwindow")
    assert [w.windows for w in wb.when] == [(60, 5), (360, 30)]
    assert wb.when[0].threshold == pytest.approx(0.0144)
    static = cfg.rule("static-1pct")
    assert static.for_minutes == 5 and static.when[0].threshold == 0.01
    assert wb.describe() == "burn > 14.4x over 1h & 5m OR burn > 6x over 6h & 30m"


GOOD_SLO = "[slo]\ntarget = 0.999\n"


def rule(body: str) -> str:
    return GOOD_SLO + '[[rule]]\nname = "r"\n' + body


@pytest.mark.parametrize(
    "text,needle",
    [
        ("not toml [", "not valid TOML"),
        ("[slo]\ntarget = 0.999\n", "missing 'rule'"),
        ('[slo]\ntarget = 1.5\n[[rule]]\nname="r"\n[[rule.when]]\nburn=1\nwindows=["1h"]\n', "between 0 and 1"),
        ('[slo]\ntarget = 0.999\ntargte = 1\n[[rule]]\nname="r"\n', "unknown key 'targte'"),
        (rule('[[rule.when]]\nburn = 2\nwindow = ["1h"]\n'), "unknown key 'window'"),
        (rule('[[rule.when]]\nburn = 2\nerror_ratio = 0.1\nwindows = ["1h"]\n'), "exactly one of burn or error_ratio"),
        (rule('[[rule.when]]\nwindows = ["1h"]\n'), "exactly one of burn or error_ratio"),
        (rule('[[rule.when]]\nburn = 2\nwindows = ["90s"]\n'), "whole number of minutes"),
        (rule('[[rule.when]]\nburn = 2\nwindows = ["1 hour"]\n'), "not a duration"),
        (rule("[[rule.when]]\nburn = 2\nwindows = []\n"), "non-empty list"),
        (rule('[[rule.when]]\nburn = 2000\nwindows = ["1h"]\n'), "impossible"),
        (rule('[[rule.when]]\nburn = -1\nwindows = ["1h"]\n'), "positive"),
        (rule('for = 5\n[[rule.when]]\nburn = 2\nwindows = ["1h"]\n'), "duration string"),
        (rule(""), "missing 'when'"),
        (
            rule('[[rule.when]]\nburn = 1\nwindows = ["1h"]\n')
            + '[[rule]]\nname = "r"\n[[rule.when]]\nburn = 1\nwindows = ["1h"]\n',
            "defined twice",
        ),
    ],
)
def test_rejects(text, needle):
    with pytest.raises(InputError) as e:
        parse(text, "rules.toml")
    assert needle in str(e.value), str(e.value)
