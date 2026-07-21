from datetime import datetime, timedelta
from config.settings import settings
from db.connection import get_cursor
from utils.logger import logger

def get_volume_by_topics_and_slot(topics: list[str], slot_start: datetime) -> int:
    slot_end = slot_start + timedelta(hours=settings.VOLUME_INTERVAL_HOURS)

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT t.tweet_id) AS tweet_count
            FROM tweet t
            JOIN tweet_topic tt ON tt.tweet_id = t.tweet_id
            WHERE tt.topic = ANY(%s)
              AND t.timestamp_utc >= %s
              AND t.timestamp_utc <  %s
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

def get_all_tweets_by_topics_and_window(
    topics: list[str], window_start: datetime, window_end: datetime
) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (t.tweet_id)
                t.user_screen_name,
                t.timestamp_utc AS "timestamp",
                t.text,
                t.likes,
                t.retweets,
                t.view_count,
                u.created_at        AS account_created_at,
                u.followers_count   AS followers_count
            FROM tweet t
            JOIN tweet_topic tt ON tt.tweet_id = t.tweet_id
            LEFT JOIN "user" u ON u.screen_name = t.user_screen_name
            WHERE tt.topic = ANY(%s)
              AND t.timestamp_utc >= %s AND t.timestamp_utc < %s
            ORDER BY t.tweet_id
            """,
            (topics, window_start, window_end),
        )
        rows = cur.fetchall()

    logger.debug(
        f"tweet_repo | window={window_start}->{window_end} | topics={len(topics)} | "
        f"fetched {len(rows)} tweets (no sampling)"
    )
    return rows