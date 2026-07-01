from datetime import datetime, timedelta
from db.connection import get_cursor
from config.settings import settings
from utils.logger import logger

def get_volume_by_topics_and_slot(topics: list[str], slot_start: datetime) -> int:
    slot_end = slot_start + timedelta(hours=settings.VOLUME_INTERVAL_HOURS)

    if not topics:
        return 0
    
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT tt.tweet_id) AS tweet_count
            FROM tweet_topic tt
            JOIN tweet t ON t.tweet_id = tt.tweet_id
            WHERE tt.topic = ANY(%s)
              AND t.timestamp_utc >= %s
              AND t.timestamp_utc <  %s
            """,
            (topics, slot_start, slot_end),
        )
        row = cur.fetchone()

    count = int(row["tweet_count"]) if row else 0
    logger.debug(
        f"tweet_repo | slot={slot_start.strftime('%Y-%m-%d %H:%M')} "
        f"({settings.VOLUME_INTERVAL_HOURS}h) | topics={len(topics)} | count={count}"
    )
    return count

def get_all_tweets_by_topics_and_date(topics: list[str], date: str) -> list[dict]:
    if not topics:
        return []
 
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (t.tweet_id)
                t.tweet_id,
                t.user_screen_name,
                t.timestamp_utc     AS timestamp,
                t.text,
                t.likes,
                t.retweets,
                t.view_count,
                u.created_at        AS account_created_at,
                u.followers_count   AS followers_count
            FROM tweet_topic tt
            JOIN tweet t          ON t.tweet_id = tt.tweet_id
            LEFT JOIN "user" u    ON u.screen_name = t.user_screen_name
            WHERE tt.topic = ANY(%s)
              AND t.collected_date = %s
            """,
            (topics, date),
        )
        rows = cur.fetchall()
 
    logger.debug(
        f"tweet_repo | date={date} | topics={len(topics)} | "
        f"fetched {len(rows)} tweets (with profiles)"
    )
    return rows