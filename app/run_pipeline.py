import argparse
from db.connection import init_pool, close_pool
from pipeline.orchestrator import run_for_date, run_all
from utils.logger import logger

def main() -> None:
    parser = argparse.ArgumentParser(description="Issue diversion detection pipeline")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    args = parser.parse_args()

    init_pool()
    try:
        if args.date:
            logger.info(f"run_pipeline | date={args.date}")
            run_for_date(args.date)
        else:
            logger.info("run_pipeline | processing all dates")
            run_all()
    finally:
        close_pool()

if __name__ == "__main__":
    main()