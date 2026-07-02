from datetime import datetime, timedelta
from db.connection import get_cursor
from config.settings import settings
from utils.logger import logger

def get_volume_by_topics_and_slot(topics: list[str], slot_start: datetime) -> int:
    slot_end = slot_start + timedelta(hours=settings.VOLUME_INTERVAL_HOURS)

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

def get_all_tweets_by_topics_and_date(topics: list[str], date: str) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.user_screen_name,
                t."timestamp",
                t.text,
                t.likes,
                t.retweets,
                t.view_count,
                NULL::timestamptz AS account_created_at,
                NULL::integer     AS followers_count
            FROM tweet t
            WHERE t.collected_for_hashtag = ANY(%s)
              AND t.collected_date = %s
            """,
            (topics, date),
        )
        rows = cur.fetchall()

    logger.debug(
        f"tweet_repo | date={date} | topics={len(topics)} | "
        f"fetched {len(rows)} tweets (no sampling)"
    )
    return rows