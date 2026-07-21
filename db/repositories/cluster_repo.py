from dataclasses import dataclass
from db.connection import get_cursor
from utils.logger import logger

@dataclass
class Cluster:
    id: int
    date: str
    cluster_label: str
    topics: list[str]

def _row_to_cluster(row: dict) -> Cluster:
    return Cluster(
        id=row["id"],
        date=str(row["date"]),
        cluster_label=row["cluster_label"],
        topics=list(row["topics"]),
    )

def save_clusters(date: str, clusters: list[dict]) -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM clusters WHERE date = %s", (date,))
        for cluster in clusters:
            cur.execute(
                """
                INSERT INTO clusters (date, cluster_label, topics)
                VALUES (%s, %s, %s)
                """,
                (date, cluster["label"], cluster["topics"]),
            )

    logger.info(f"cluster_repo | saved {len(clusters)} clusters for date={date}")

def get_clusters_by_date(date: str) -> list[Cluster]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, date, cluster_label, topics
            FROM clusters
            WHERE date = %s
            ORDER BY id
            """,
            (date,),
        )
        rows = cur.fetchall()

    return [_row_to_cluster(row) for row in rows]

def get_cluster_by_id(cluster_id: int) -> Cluster | None:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, date, cluster_label, topics
            FROM clusters
            WHERE id = %s
            """,
            (cluster_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    return _row_to_cluster(row)

def get_recent_clusters(date: str, days: int = 7) -> list[Cluster]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, date, cluster_label, topics
            FROM clusters
            WHERE date >= %s::date - %s
              AND date <  %s::date
            ORDER BY date, id
            """,
            (date, days, date),
        )
        rows = cur.fetchall()

    clusters = [_row_to_cluster(row) for row in rows]

    logger.debug(
        f"cluster_repo | recent context | {len(clusters)} clusters "
        f"from last {days} days before {date}"
    )
    return clusters