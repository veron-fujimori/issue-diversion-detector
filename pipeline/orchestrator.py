from config.settings import settings
from utils.logger import logger
from db.repositories.trending_repo import get_all_dates
from db.repositories.alert_repo import get_alerts_pending_scoring
from db.repositories.cluster_repo import get_cluster_by_id
from pipeline.collection import trends_collector, tweets_collector, users_collector
from pipeline.clustering import clusterer
from pipeline.timeseries import timeseries
from pipeline.detection import detector
from pipeline.analysis import analyzer
from pipeline.scoring import scorer

def run_collection(
    date_start: str | None = None,
    date_end: str | None = None,
    include_users: bool = True,
) -> None:
    start = date_start or settings.DATE_START
    end   = date_end   or settings.DATE_END
 
    logger.info(f"orchestrator | ===== COLLECTION {start} → {end} =====")
 
    logger.info("orchestrator | [collect 1/3] trends")
    trends_collector.run(start, end)
 
    logger.info("orchestrator | [collect 2/3] tweets")
    tweets_collector.run(start, end)
 
    if include_users:
        logger.info("orchestrator | [collect 3/3] users")
        users_collector.run(start, end)
    else:
        logger.info("orchestrator | [collect 3/3] users — skipped (--skip-users)")
 
    logger.info(f"orchestrator | ===== COLLECTION DONE {start} → {end} =====")


def run_for_date(date: str) -> None:
    logger.info(f"orchestrator | ===== START {date} =====")
    try:
        logger.info(f"orchestrator | [1/4] clustering")
        clusterer.run(date)

        logger.info(f"orchestrator | [2/4] timeseries")
        timeseries.run(date)

        logger.info(f"orchestrator | [3/4] detection")
        detector.run(date)
        
        logger.info(f"orchestrator | [4/4] analysis and scoring")
        _run_analysis_and_scoring(date)
    except Exception as e:
        logger.error(f"orchestrator | FAILED at date={date} | {e}")
        raise

    logger.info(f"orchestrator | ===== DONE {date} =====")

def run_analysis_range(date_start: str | None = None, date_end: str | None = None) -> None:
    all_dates = get_all_dates()
    if not all_dates:
        logger.warning("orchestrator | no dates found in trending table")
        return
 
    start = date_start or settings.DATE_START
    end   = date_end   or settings.DATE_END
 
    dates = [d for d in all_dates if start <= d <= end]
    if not dates:
        logger.warning(
            f"orchestrator | no trending dates within {start} → {end} "
            f"(table has {len(all_dates)} date(s))"
        )
        return
 
    logger.info(f"orchestrator | analysis over {len(dates)} date(s) in {start} → {end}")
    for i, date in enumerate(dates, 1):
        logger.info(f"orchestrator | [{i}/{len(dates)}] {date}")
        run_for_date(date)
 
    logger.info(f"orchestrator | analysis complete — {len(dates)} date(s) processed")

def _run_analysis_and_scoring(date: str) -> None:
    alerts = get_alerts_pending_scoring(date)

    if not alerts:
        logger.info(f"orchestrator | no alerts pending scoring for date={date}")
        return

    logger.info(f"orchestrator | scoring {len(alerts)} alerts")

    succeeded = 0
    failed    = 0

    for alert in alerts:
        try:
            rising_cluster = get_cluster_by_id(alert.rising_cluster_id)

            if rising_cluster is None:
                logger.warning(
                    f"orchestrator | alert_id={alert.id} | "
                    f"rising cluster_id={alert.rising_cluster_id} not found, skipping"
                )
                failed += 1
                continue

            analysis = analyzer.run(alert, rising_cluster.topics)
            scorer.run(alert, analysis)
            succeeded += 1

        except Exception as e:
            logger.error(
                f"orchestrator | alert_id={alert.id} | "
                f"FAILED during analysis/scoring | {e}"
            )
            failed += 1
            continue

    logger.info(
        f"orchestrator | analysis & scoring done | "
        f"succeeded={succeeded} failed={failed}"
    )

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

def run_full(
    date_start: str | None = None,
    date_end: str | None = None,
    include_users: bool = True,
) -> None:
    run_collection(date_start, date_end, include_users=include_users)
    run_analysis_range(date_start, date_end)