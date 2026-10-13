import pytest
from helpers import series

from slo_proof.errors import InputError
from slo_proof.incidents import parse, to_csv

HEAD = "start,end,severity,name\n"


def test_parses_sorted_and_round_trips():
    s = series([0] * 600)
    inc = parse(
        HEAD + "2026-03-02T05:00:00Z,2026-03-02T06:00:00Z,ticket,b\n2026-03-02T01:00:00Z,2026-03-02T01:05:00Z,page,a\n",
        s,
    )
    assert [i.name for i in inc] == ["a", "b"]
    assert inc[0].pages and not inc[1].pages
    assert parse(to_csv(inc), s) == inc


@pytest.mark.parametrize(
    "row,needle",
    [
        ("2026-03-02T01:00:00Z,2026-03-02T01:00:00Z,page,x", "not after start"),
        ("2026-03-02T01:00:00Z,2026-03-02T02:00:00Z,sev1,x", "not one of page, ticket"),
        ("2026-03-02T01:00:00Z,2026-03-02T02:00:00Z,page,", "no name"),
        ("2026-03-02T01:00:00Z,2026-03-09T02:00:00Z,page,x", "outside the data"),
        ("2026-03-02T01:00:00,2026-03-02T02:00:00Z,page,x", "no timezone"),
        ("2026-03-02T01:00:00Z,2026-03-02T02:00:00Z,page", "4 fields"),
    ],
)
def test_rejects(row, needle):
    with pytest.raises(InputError) as e:
        parse(HEAD + row + "\n", series([0] * 600))
    assert e.value.line == 2 and needle in e.value.message, str(e.value)


def test_rejects_overlap():
    with pytest.raises(InputError, match="overlaps 'a'") as e:
        parse(
            HEAD
            + "2026-03-02T01:00:00Z,2026-03-02T02:00:00Z,page,a\n2026-03-02T01:30:00Z,2026-03-02T03:00:00Z,page,b\n"
        )
    assert e.value.line == 3, str(e.value)
