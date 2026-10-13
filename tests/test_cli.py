from pathlib import Path

from slo_proof.cli import main

ROOT = Path(__file__).parent.parent
EX = [str(ROOT / "examples" / f) for f in ("sli.csv", "incidents.csv", "rules.toml")]


def test_compare_ranks_and_lists_misses(capsys):
    assert main(["compare", *EX]) == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line[:1].isdigit() and "/" in line]
    assert lines[0].split()[1] == "workbook-multiwindow"
    assert "fast-burn-only: slow burn" in out


def test_fail_on_miss(capsys):
    assert main(["compare", *EX, "--fail-on-miss"]) == 1
    assert main(["replay", *EX, "--rule", "workbook-multiwindow", "--fail-on-miss"]) == 0
    assert main(["replay", *EX, "--rule", "fast-burn-only", "--fail-on-miss"]) == 1
    assert "MISSED" in capsys.readouterr().out


def test_bad_input_names_the_line(tmp_path, capsys):
    bad = tmp_path / "sli.csv"
    bad.write_text("timestamp,good,total\n2026-03-02T00:00:00Z,1,1\n2026-03-02T00:05:00Z,1,1\n")
    assert main(["compare", str(bad), EX[1], EX[2]]) == 2
    assert "line 3: gap of 4 minutes" in capsys.readouterr().err


def test_replay_names_the_budget_period(tmp_path, capsys):
    rules = tmp_path / "rules.toml"
    rules.write_text(Path(EX[2]).read_text().replace('period = "30d"', 'period = "7d"'))
    assert main(["replay", EX[0], EX[1], str(rules), "--rule", "fast-burn-only"]) == 0
    assert "share of the 7-day error budget" in capsys.readouterr().out


def test_unknown_rule(capsys):
    assert main(["replay", *EX, "--rule", "nope"]) == 2
    assert "no rule named 'nope'" in capsys.readouterr().err


def test_plot_and_check(tmp_path, capsys):
    out = tmp_path / "t.svg"
    assert main(["plot", *EX, "--from", "2026-03-18T00:00:00Z", "--to", "2026-03-19T00:00:00Z", "-o", str(out)]) == 0
    assert out.read_text().startswith("<svg")
    assert main(["check", EX[2]]) == 0
    assert "workbook-multiwindow: burn > 14.4x" in capsys.readouterr().out


def test_synth_writes_files(tmp_path):
    assert main(["synth", "--seed", "2", "--days", "3", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "sli.csv").read_text().count("\n") == 3 * 1440 + 2
