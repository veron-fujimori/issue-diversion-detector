"""
app/run_pipeline.py — pipeline entry point.

Subcommands
-----------
  collect   Collect trends + tweets (+ users) for a date range.
  analyze   Run clustering → timeseries → detection for a date or range.
  all       Collect the range, then analyze every date in it.

Examples
--------
  python -m app.run_pipeline collect
  python -m app.run_pipeline collect --start 2026-05-24 --end 2026-05-26
  python -m app.run_pipeline collect --skip-users
  python -m app.run_pipeline analyze --date 2026-05-24
  python -m app.run_pipeline analyze --start 2026-05-24 --end 2026-05-26
  python -m app.run_pipeline all
  python -m app.run_pipeline all --migrate          # apply schema first

Ranges default to settings.DATE_START / DATE_END when not given.
Schema migrations are normally run separately (python -m db.migrate); the
optional --migrate flag is a convenience that applies them before running.
"""

import argparse

from db.connection import init_pool, close_pool
from pipeline.orchestrator import (
    run_collection,
    run_for_date,
    run_analysis_range,
    run_full,
)
from utils.logger import logger


def _maybe_migrate(do_migrate: bool) -> None:
    if not do_migrate:
        return
    logger.info("run_pipeline | applying migrations (--migrate)")
    from db.migrate import run as migrate_run
    migrate_run()


def _cmd_collect(args) -> None:
    _maybe_migrate(args.migrate)
    run_collection(
        date_start=args.start,
        date_end=args.end,
        include_users=not args.skip_users,
    )


def _cmd_analyze(args) -> None:
    _maybe_migrate(args.migrate)
    if args.date:
        run_for_date(args.date)
    else:
        run_analysis_range(date_start=args.start, date_end=args.end)


def _cmd_all(args) -> None:
    _maybe_migrate(args.migrate)
    run_full(
        date_start=args.start,
        date_end=args.end,
        include_users=not args.skip_users,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Issue diversion detection pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── collect ──────────────────────────────────────────────────────────
    p_collect = sub.add_parser("collect", help="Collect trends + tweets (+ users)")
    p_collect.add_argument("--start", type=str, default=None, help="Range start YYYY-MM-DD")
    p_collect.add_argument("--end",   type=str, default=None, help="Range end YYYY-MM-DD")
    p_collect.add_argument("--skip-users", action="store_true",
                           help="Skip user-profile collection (faster, weaker detection)")
    p_collect.add_argument("--migrate", action="store_true",
                           help="Apply DB migrations before running")
    p_collect.set_defaults(func=_cmd_collect)

    # ── analyze ──────────────────────────────────────────────────────────
    p_analyze = sub.add_parser("analyze", help="Cluster → timeseries → detect")
    p_analyze.add_argument("--date",  type=str, default=None, help="Single date YYYY-MM-DD")
    p_analyze.add_argument("--start", type=str, default=None, help="Range start YYYY-MM-DD")
    p_analyze.add_argument("--end",   type=str, default=None, help="Range end YYYY-MM-DD")
    p_analyze.add_argument("--migrate", action="store_true",
                           help="Apply DB migrations before running")
    p_analyze.set_defaults(func=_cmd_analyze)

    # ── all ──────────────────────────────────────────────────────────────
    p_all = sub.add_parser("all", help="Collect the range, then analyze every date")
    p_all.add_argument("--start", type=str, default=None, help="Range start YYYY-MM-DD")
    p_all.add_argument("--end",   type=str, default=None, help="Range end YYYY-MM-DD")
    p_all.add_argument("--skip-users", action="store_true",
                       help="Skip user-profile collection")
    p_all.add_argument("--migrate", action="store_true",
                       help="Apply DB migrations before running")
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