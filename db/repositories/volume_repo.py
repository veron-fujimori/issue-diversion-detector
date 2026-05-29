from dataclasses import dataclass
from datetime import datetime
from db.connection import get_cursor
from utils.logger import logger

@dataclass
class ClusterVolume:
    cluster_id: int
    slot_start: datetime
    tweet_count: int

def save_volumes(cluster_id: int, volumes: dict[datetime, int]) -> None:
    rows = [(cluster_id, slot, count) for slot, count in volumes.items()]

    with get_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO cluster_volumes (cluster_id, slot_start, tweet_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (cluster_id, slot_start)
            DO UPDATE SET tweet_count = EXCLUDED.tweet_count
            """,
            rows,
        )

    logger.debug(f"volume_repo | cluster_id={cluster_id} | saved {len(rows)} slots")

def get_volumes_grouped_by_cluster(start: datetime, end: datetime) -> dict[int, list[ClusterVolume]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, slot_start, tweet_count
            FROM cluster_volumes
            WHERE slot_start >= %s AND slot_start < %s
            ORDER BY cluster_id, slot_start
            """,
            (start, end),
        )
        rows = cur.fetchall()

    grouped: dict[int, list[ClusterVolume]] = {}
    for row in rows:
        v = ClusterVolume(
            cluster_id=row["cluster_id"],
            slot_start=row["slot_start"],
            tweet_count=row["tweet_count"],
        )
        grouped.setdefault(v.cluster_id, []).append(v)

    logger.debug(f"volume_repo | {start} → {end} | {len(grouped)} clusters")
    return grouped