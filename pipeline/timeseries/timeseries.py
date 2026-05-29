from datetime import datetime, timedelta, timezone
from utils.logger import logger
from db.repositories.cluster_repo import get_clusters_by_date
from db.repositories.tweet_repo import get_volume_by_topics_and_slot
from db.repositories.volume_repo import save_volumes

WIB = timezone(timedelta(hours=7))

def _generate_slots(start: datetime, end: datetime) -> list[datetime]:
    slot_hour = (start.astimezone(WIB).hour // 4) * 4
    current = start.astimezone(WIB).replace(
        hour=slot_hour, minute=0, second=0, microsecond=0
    )
    slots = []
    while current <= end:
        slots.append(current)
        current += timedelta(hours=4)
    return slots

def run(date: str) -> None:
    clusters = get_clusters_by_date(date)
    if not clusters:
        logger.warning(f"timeseries | date={date} | no clusters found, run clusterer first")
        return

    day_start = datetime.fromisoformat(date).replace(hour=0, minute=0, second=0, tzinfo=WIB)
    day_end   = day_start + timedelta(days=1)
    slots     = _generate_slots(day_start, day_end - timedelta(seconds=1))

    logger.info(f"timeseries | date={date} | {len(clusters)} clusters | {len(slots)} slots")

    for cluster in clusters:
        volumes: dict[datetime, int] = {
            slot: get_volume_by_topics_and_slot(topics=cluster.topics, slot_start=slot)
            for slot in slots
        }
        save_volumes(cluster_id=cluster.id, volumes=volumes)
        logger.debug(
            f"timeseries | cluster_id={cluster.id} | '{cluster.cluster_label}' | "
            f"total={sum(volumes.values())} tweets"
        )

    logger.info(f"timeseries | date={date} | done")