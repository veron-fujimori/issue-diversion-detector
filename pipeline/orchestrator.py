from utils.logger import logger
from db.repositories.trending_repo import get_all_dates
from pipeline.clustering import clusterer
from pipeline.timeseries import timeseries
from pipeline.detection import detector

def run_for_date(date: str) -> None:
    logger.info(f"orchestrator | ===== START {date} =====")
    try:
        # logger.info(f"orchestrator | [1/4] clustering")
        # clusterer.run(date)

        # logger.info(f"orchestrator | [2/4] timeseries")
        # timeseries.run(date)

        logger.info(f"orchestrator | [3/4] detection")
        detector.run(date)
    except Exception as e:
        logger.error(f"orchestrator | FAILED at date={date} | {e}")
        raise

    logger.info(f"orchestrator | ===== DONE {date} =====")

def run_all() -> None:
    dates = get_all_dates()
    if not dates:
        logger.warning("orchestrator | no dates found in trending table")
        return

    logger.info(f"orchestrator | found {len(dates)} dates to process")
    for i, date in enumerate(dates, 1):
        logger.info(f"orchestrator | [{i}/{len(dates)}] {date}")
        run_for_date(date)

    logger.info(f"orchestrator | all {len(dates)} dates processed")