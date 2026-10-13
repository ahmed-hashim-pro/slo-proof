"""The slo-proof command line."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from . import __version__, incidents, prom, rules, series, svg, synth
from .errors import InputError
from .score import RuleResult, budget_events, rank, score
from .timeutil import format_duration, format_time, parse_time


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError as e:
        raise InputError(path, 0, e.strerror or str(e)) from None


def _load(args: argparse.Namespace) -> tuple[series.Series, list[incidents.Incident], rules.Config, list[RuleResult]]:
    s = series.parse(_read(args.sli), args.sli)
    inc = incidents.parse(_read(args.incidents), s, args.incidents)
    cfg = rules.parse(_read(args.rules), args.rules)
    chosen = cfg.rules
    if args.rule:
        try:
            chosen = tuple(cfg.rule(n) for n in args.rule)
        except KeyError as e:
            names = ", ".join(r.name for r in cfg.rules)
            raise InputError(args.rules, 0, f"no rule named {e.args[0]!r} (rules: {names})") from None
    return s, inc, cfg, [score(s, inc, cfg, r) for r in chosen]


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def _delay(v: float | None) -> str:
    return "-" if v is None else format_duration(v)


def cmd_replay(args: argparse.Namespace) -> int:
    s, inc, cfg, results = _load(args)
    print(f"{len(s) / 1440:.1f} days of data, {len(inc)} incidents, SLO {100 * cfg.target:g}%")
    missed_any = False
    for rr in results:
        print(f"\n{rr.rule.name}: {rr.rule.describe()}")
        print(f"  {'incident':<22} {'severity':<8} {'started':<17} {'paged after':<12} budget spent before / in all")
        for ir in rr.incidents:
            if ir.delay is None:
                when = "MISSED" if ir.incident.pages else "not paged"
                missed_any |= ir.incident.pages
            else:
                when = format_duration(ir.delay)
            print(
                f"  {ir.incident.name:<22} {ir.incident.severity:<8} {format_time(ir.incident.start):<17} {when:<12} "
                f"{100 * ir.budget_before_detection:5.1f}% / {100 * ir.budget_total:5.1f}%"
            )
        print(
            f"  {rr.pages} pages: {len(rr.true_pages)} during incidents, {len(rr.late_pages)} after one ended, "
            f"{len(rr.false_pages)} with no incident; firing {format_duration(rr.firing_outside)} with no incident open"
        )
    print("\nbudget spent is a share of the 30-day error budget at this traffic.")
    return 1 if args.fail_on_miss and missed_any else 0


def cmd_compare(args: argparse.Namespace) -> int:
    s, inc, cfg, results = _load(args)
    pages = sum(1 for i in inc if i.pages)
    print(f"{len(s) / 1440:.1f} days, {pages} incidents that deserved a page, SLO {100 * cfg.target:g}%\n")
    head = f"{'':<4}{'rule':<24} {'caught':>7} {'median delay':>13} {'false/week':>11} {'late':>5} {'precision':>10} {'firing, no incident':>20}"
    print(head)
    for i, rr in enumerate(rank(results), start=1):
        print(
            f"{i:<4}{rr.rule.name:<24} {f'{rr.detected}/{len(rr.page_incidents)}':>7} {_delay(rr.median_delay):>13} "
            f"{rr.false_per_week:>11.1f} {len(rr.late_pages):>5} {_pct(rr.precision):>10} {format_duration(rr.firing_outside):>20}"
        )
    print("\nranked by incidents caught, then false pages per week, then median delay.")
    missed = [
        f"{rr.rule.name}: {', '.join(ir.incident.name for ir in rr.page_incidents if ir.detected_at is None)}"
        for rr in results
        if rr.detected < len(rr.page_incidents)
    ]
    if missed:
        print("missed:\n  " + "\n  ".join(missed))
    return 1 if args.fail_on_miss and missed else 0


def cmd_plot(args: argparse.Namespace) -> int:
    s, inc, cfg, results = _load(args)
    try:
        start = parse_time(args.start) if args.start else s.start
        end = parse_time(args.end) if args.end else s.end
    except ValueError as e:
        raise InputError("--from/--to", 0, str(e)) from None
    start, end = max(start, s.start), min(end, s.end)
    if end - start < 3600:
        raise InputError("--from/--to", 0, "the range must cover at least an hour of the data")
    title = args.title or f"{len(results)} alert rules replayed against {(end - start) / 86400:.1f} days"
    out = svg.timeline(s, inc, results, cfg.target, budget_events(s, cfg.target, cfg.period_days), start, end, title)
    _write(args.output, out)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = rules.parse(_read(args.rules), args.rules)
    print(f"SLO {100 * cfg.target:g}% over {cfg.period_days} days; budget rate {100 * (1 - cfg.target):g}% errors")
    for r in cfg.rules:
        print(f"  {r.name}: {r.describe()}")
    return 0


def cmd_synth(args: argparse.Namespace) -> int:
    s, inc = synth.generate(args.seed, args.days)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    header = f"# synthetic: slo-proof synth --seed {args.seed} --days {args.days}\n"
    (out / "sli.csv").write_text(header + s.to_csv())
    (out / "incidents.csv").write_text(header + incidents.to_csv(inc))
    print(f"wrote {out / 'sli.csv'} ({len(s)} minutes) and {out / 'incidents.csv'} ({len(inc)} incidents)")
    return 0


def cmd_from_prom(args: argparse.Namespace) -> int:
    s = prom.to_series(_read(args.total), _read(args.bad), args.total, args.bad)
    _write(args.output, s.to_csv())
    return 0


def _write(path: str | None, text: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(text)
    else:
        try:
            Path(path).write_text(text)
        except OSError as e:
            raise InputError(path, 0, e.strerror or str(e)) from None


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="slo-proof",
        description="Replay past SLI data against alert rules: which incidents would they have caught, how late, "
        "and how often would they have paged for nothing?",
        epilog="exit codes: 0 ok; 1 a page-worthy incident was missed (with --fail-on-miss); 2 bad input",
    )
    p.add_argument("--version", action="version", version=f"slo-proof {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def data_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("sli", help="per-minute CSV: timestamp,good,total")
        sp.add_argument("incidents", help="CSV: start,end,severity,name")
        sp.add_argument("rules", help="TOML rules file")
        sp.add_argument("--rule", action="append", help="only this rule (repeatable)")

    sp = sub.add_parser("replay", help="per-incident detail for each rule")
    data_args(sp)
    sp.add_argument("--fail-on-miss", action="store_true", help="exit 1 if any rule misses a page incident")
    sp.set_defaults(func=cmd_replay)

    sp = sub.add_parser("compare", help="rank rules by incidents caught, false pages, delay")
    data_args(sp)
    sp.add_argument("--fail-on-miss", action="store_true", help="exit 1 if any rule misses a page incident")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("plot", help="SVG timeline of error ratio, budget, incidents and alerts")
    data_args(sp)
    sp.add_argument("--from", dest="start", help="start time (ISO 8601 with timezone)")
    sp.add_argument("--to", dest="end", help="end time")
    sp.add_argument("--title")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_plot)

    sp = sub.add_parser("check", help="validate a rules file and print what each rule means")
    sp.add_argument("rules")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("synth", help="write a synthetic month with known incidents")
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--days", type=int, default=28, choices=range(1, 366), metavar="DAYS")
    sp.add_argument("--out", default=".")
    sp.set_defaults(func=cmd_synth)

    sp = sub.add_parser("from-prom", help="convert two Prometheus range-query exports to the CSV")
    sp.add_argument("--total", required=True, help="JSON: sum(increase(requests_total[1m])), step 60")
    sp.add_argument("--bad", required=True, help="JSON: the same for failed requests")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_from_prom)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `slo-proof ... | head` exits quietly
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except InputError as e:
        print(f"slo-proof: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
