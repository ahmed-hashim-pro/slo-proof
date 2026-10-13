import pytest

from slo_proof.errors import InputError
from slo_proof.series import parse

HEAD = "timestamp,good,total\n"


def test_parses_and_sums():
    s = parse(HEAD + "2026-03-02T00:00:00Z,9,10\n2026-03-02T00:01:00Z,5,10\n2026-03-02T00:02:00+00:00,10,10\n")
    assert len(s) == 3
    assert s.bad_in(0, 3) == 6 and s.total_in(0, 3) == 30
    assert s.ratio(1, 2) == 0.5
    assert s.bad_in(-5, 1) == 1, "windows reaching before the data use what there is"


def test_unix_seconds_and_round_trip():
    s = parse(HEAD + "1772409600,1,2\n1772409660,0,0\n")
    assert s.ratio(1, 2) is None, "no traffic is no value, not zero"
    assert parse(s.to_csv()) == s


@pytest.mark.parametrize(
    "body,line,needle",
    [
        ("", 0, "no data"),
        ("time,good,total\n", 1, "expected header"),
        (HEAD, 0, "no data rows"),
        (HEAD + "2026-03-02T00:00:00,1,1\n", 2, "no timezone"),
        (HEAD + "yesterday,1,1\n", 2, "not an ISO 8601"),
        (HEAD + "2026-03-02T00:00:30Z,1,1\n", 2, "minute boundary"),
        (HEAD + "2026-03-02T00:00:00Z,1\n", 2, "3 fields"),
        (HEAD + "2026-03-02T00:00:00Z,1.5,2\n", 2, "whole numbers"),
        (HEAD + "2026-03-02T00:00:00Z,-1,2\n", 2, "negative"),
        (HEAD + "2026-03-02T00:00:00Z,3,2\n", 2, "exceeds total"),
        (HEAD + "2026-03-02T00:00:00Z,1,1\n2026-03-02T00:03:00Z,1,1\n", 3, "gap of 2 minutes"),
        (HEAD + "2026-03-02T00:00:00Z,1,1\n2026-03-02T00:00:00Z,1,1\n", 3, "duplicate or out of order"),
    ],
)
def test_rejects(body, line, needle):
    with pytest.raises(InputError) as e:
        parse(body, "sli.csv")
    assert e.value.line == line, str(e.value)
    assert needle in e.value.message, str(e.value)
