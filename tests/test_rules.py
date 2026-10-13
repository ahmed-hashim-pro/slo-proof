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


def example_with(line: int, old: str, new: str) -> str:
    rows = EXAMPLE.read_text().splitlines(keepends=True)
    assert old in rows[line - 1]
    rows[line - 1] = rows[line - 1].replace(old, new)
    return "".join(rows)


@pytest.mark.parametrize(
    "text,line,needle",
    [
        ("not toml [", 1, "not valid TOML"),
        ("[slo]\ntarget = 0.999\n", 0, "missing 'rule'"),
        ('[slo]\ntarget = 1.5\n[[rule]]\nname="r"\n[[rule.when]]\nburn=1\nwindows=["1h"]\n', 2, "between 0 and 1"),
        ('[slo]\ntarget = 0.999\ntargte = 1\n[[rule]]\nname="r"\n', 3, "unknown key 'targte'"),
        (rule('[[rule.when]]\nburn = 2\nwindow = ["1h"]\n'), 7, "unknown key 'window'"),
        (
            rule('[[rule.when]]\nburn = 2\nerror_ratio = 0.1\nwindows = ["1h"]\n'),
            5,
            "exactly one of burn or error_ratio",
        ),
        (rule('[[rule.when]]\nwindows = ["1h"]\n'), 5, "exactly one of burn or error_ratio"),
        (rule('[[rule.when]]\nburn = 2\nwindows = ["90s"]\n'), 7, "whole number of minutes"),
        (rule('[[rule.when]]\nburn = 2\nwindows = ["1 hour"]\n'), 7, "not a duration"),
        (rule("[[rule.when]]\nburn = 2\nwindows = []\n"), 7, "non-empty list"),
        (rule('[[rule.when]]\nburn = 2000\nwindows = ["1h"]\n'), 6, "impossible"),
        (rule('[[rule.when]]\nburn = -1\nwindows = ["1h"]\n'), 6, "positive"),
        (rule('for = 5\n[[rule.when]]\nburn = 2\nwindows = ["1h"]\n'), 5, "duration string"),
        (rule(""), 3, "missing 'when'"),
        (
            rule('[[rule.when]]\nburn = 1\nwindows = ["1h"]\n')
            + '[[rule]]\nname = "r"\n[[rule.when]]\nburn = 1\nwindows = ["1h"]\n',
            9,
            "defined twice",
        ),
        (example_with(6, '"30d"', '"36h"'), 6, "whole days"),
        (example_with(39, "windows", "window"), 39, "workbook-multiwindow' when 2: unknown key 'window'"),
    ],
)
def test_rejects(text, line, needle):
    with pytest.raises(InputError) as e:
        parse(text, "rules.toml")
    assert e.value.line == line, str(e.value)
    assert needle in e.value.message, str(e.value)
