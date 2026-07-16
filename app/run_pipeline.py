import argparse
from db.connection import init_pool, close_pool
from pipeline.orchestrator import (
    run_collection,
    run_for_date,
    run_analysis_range,
    run_full,
)
from utils.logger import logger

def _resolve_date_range(date: str | None, start: str | None, end: str | None) -> tuple[str, str]:
    if date:
        if start or end:
            raise SystemExit("Use either --date, or --start/--end together — not both.")
        return date, date

    if bool(start) != bool(end):
        raise SystemExit("--start and --end must be provided together.")

    if not start:
        raise SystemExit("Provide --date, or both --start and --end.")

    return start, end

def _maybe_migrate(do_migrate: bool) -> None:
    if not do_migrate:
        return
    logger.info("run_pipeline | applying migrations (--migrate)")
    from db.migrate import run as migrate_run
    migrate_run()

def _cmd_collect(args) -> None:
    start, end = _resolve_date_range(args.date, args.start, args.end)
    _maybe_migrate(args.migrate)
    run_collection(
        date_start=start,
        date_end=end,
        include_users=not args.skip_users,
    )

def _cmd_analyze(args) -> None:
    start, end = _resolve_date_range(args.date, args.start, args.end)
    _maybe_migrate(args.migrate)
    if start == end:
        run_for_date(start)
    else:
        run_analysis_range(date_start=start, date_end=end)

def _cmd_all(args) -> None:
    start, end = _resolve_date_range(args.date, args.start, args.end)
    _maybe_migrate(args.migrate)
    run_full(
        date_start=start,
        date_end=end,
        include_users=not args.skip_users,
    )

def _add_date_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--date", type=str, default=None, help="Single date YYYY-MM-DD")
    subparser.add_argument("--start", type=str, default=None, help="Range start YYYY-MM-DD (use with --end)")
    subparser.add_argument("--end", type=str, default=None, help="Range end YYYY-MM-DD (use with --start)")

def _add_migrate_argument(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--migrate", action="store_true", help="Apply DB migrations before running")

def _add_skip_users_argument(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--skip-users", action="store_true",
        help="Skip user-profile collection (faster, weaker detection)",
    )

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Issue diversion detection pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Collect trends + tweets (+ users)")
    _add_date_arguments(p_collect)
    _add_skip_users_argument(p_collect)
    _add_migrate_argument(p_collect)
    p_collect.set_defaults(func=_cmd_collect)

    p_analyze = sub.add_parser("analyze", help="Cluster → timeseries → detect")
    _add_date_arguments(p_analyze)
    _add_migrate_argument(p_analyze)
    p_analyze.set_defaults(func=_cmd_analyze)

    p_all = sub.add_parser("all", help="Collect the range, then analyze every date")
    _add_date_arguments(p_all)
    _add_skip_users_argument(p_all)
    _add_migrate_argument(p_all)
    p_all.set_defaults(func=_cmd_all)

    return parser

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    init_pool()
    try:
        args.func(args)
    finally:
        close_pool()

if __name__ == "__main__":
    main()