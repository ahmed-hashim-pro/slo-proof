import json

import pytest

from slo_proof.errors import InputError
from slo_proof.prom import to_series


def export(points, series_count=1):
    return json.dumps(
        {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {"metric": {"i": str(i)}, "values": [[t, str(v)] for t, v in points]} for i in range(series_count)
                ],
            },
        }
    )


def test_converts_and_sums_series():
    total = export([(1772409660, 100.4), (1772409720, 99.6)], series_count=2)
    bad = export([(1772409660, 1.2), (1772409720, 0)])
    s = to_series(total, bad)
    assert s.start == 1772409600, "a value at t is the minute ending at t"
    assert s.total == [201, 199] and s.good == [200, 199]


@pytest.mark.parametrize(
    "total,bad,line,needle",
    [
        ("{", export([(60, 1)]), 1, "not JSON"),
        (json.dumps({"status": "error"}), export([(60, 1)]), 0, "status"),
        (
            json.dumps({"status": "success", "data": {"resultType": "vector", "result": []}}),
            export([(60, 1)]),
            0,
            "range query",
        ),
        (export([(60, 1)]), export([(120, 1)]), 0, "different times"),
        (export([(60, 1), (180, 1)]), export([(60, 1), (180, 1)]), 0, "not one minute apart"),
        (export([(90, 1)]), export([(90, 1)]), 0, "step=60"),
        (export([(60, -1)]), export([(60, 0)]), 0, "non-negative"),
    ],
)
def test_rejects(total, bad, line, needle):
    with pytest.raises(InputError) as e:
        to_series(total, bad)
    assert e.value.line == line, str(e.value)
    assert needle in e.value.message, str(e.value)
