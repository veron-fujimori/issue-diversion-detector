from db.connection import get_cursor
from utils.logger import logger

def get_unique_topics_by_date(date: str) -> list[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT hashtag
            FROM trending
            WHERE date = %s
            ORDER BY hashtag
            """,
            (date,),
        )
        rows = cur.fetchall()
        topics = [row["hashtag"] for row in rows]

    logger.debug(f"trending_repo | date={date} | found {len(topics)} unique topics")
    return topics


def get_all_dates() -> list[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT date
            FROM trending
            ORDER BY date
            """
        )
        rows = cur.fetchall()
        dates = [str(row["date"]) for row in rows]

    logger.debug(f"trending_repo | found {len(dates)} dates")
    return dates