from datetime import datetime, timedelta
from db.connection import get_cursor
from utils.logger import logger

def get_volume_by_topics_and_slot(topics: list[str], slot_start: datetime) -> int:
    slot_end = slot_start + timedelta(hours=4)

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS tweet_count
            FROM tweet
            WHERE collected_for_hashtag = ANY(%s)
              AND "timestamp" >= %s
              AND "timestamp" <  %s
            """,
            (topics, slot_start, slot_end),
        )
        row = cur.fetchone()

    count = int(row["tweet_count"]) if row else 0
    logger.debug(
        f"tweet_repo | slot={slot_start.strftime('%Y-%m-%d %H:%M')} | "
        f"topics={len(topics)} | count={count}"
    )
    return count