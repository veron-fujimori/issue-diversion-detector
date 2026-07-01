from utils.logger import logger
from db.repositories.trending_repo import get_all_dates
from db.repositories.alert_repo import get_alerts_pending_scoring
from db.repositories.cluster_repo import get_cluster_by_id
from pipeline.clustering import clusterer
from pipeline.timeseries import timeseries
from pipeline.detection import detector
from pipeline.analysis import analyzer
from pipeline.scoring import scorer

def run_for_date(date: str) -> None:
    logger.info(f"orchestrator | ===== START {date} =====")
    try:
        # logger.info(f"orchestrator | [1/4] clustering")
        # clusterer.run(date)

        # logger.info(f"orchestrator | [2/4] timeseries")
        # timeseries.run(date)

        logger.info(f"orchestrator | [3/4] detection")
        detector.run(date)
        
        # logger.info(f"orchestrator | [4/4] analysis and scoring")
        # _run_analysis_and_scoring(date)

    except Exception as e:
        logger.error(f"orchestrator | FAILED at date={date} | {e}")
        raise

    logger.info(f"orchestrator | ===== DONE {date} =====")

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