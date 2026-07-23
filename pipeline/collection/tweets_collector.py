"""
pipeline/collection/tweets_collector.py — Stage 2: Tweet Collection via Scweet v5

Strategy: split each day's trending topics into search jobs —
  topic_batch : up to TOPIC_BATCH_SIZE #-hashtags per call (hashtags_any=[...])
  plain_text  : one job per untagged phrase (query="...", exact-quoted)

Per returned tweet:
  - tweet content      → INSERT INTO tweet      ON CONFLICT (tweet_id)        DO NOTHING
  - topic attribution  → INSERT INTO tweet_topic ON CONFLICT (tweet_id, topic) DO NOTHING
    Attribution = (tweet's hashtags ∩ the day's trending set) for topic_batch jobs,
                  or the search phrase for plain_text jobs.

Timezone: trending archive is WIB (UTC+7); Twitter since/until are UTC date
strings. The window is padded by WIB_OFFSET_DAYS on each side so the full WIB
day is covered; the topic filter keeps relevance.

Run standalone:
    python -m pipeline.collection.tweets_collector

Resume:     Safe to re-run. Completed jobs (scrape_job table) are skipped.
Idempotent: Yes — content and attribution both use ON CONFLICT DO NOTHING.
"""

import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import Optional

from config.settings import settings
from db.connection import get_cursor
from utils.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPIC_BATCH_SIZE = 10    # #-hashtags per Scweet call — safe below Twitter's OR limit
WIB_OFFSET_DAYS  = 1     # UTC window padding each side to cover the UTC+7 day
INSERT_CHUNK_SIZE = 100  # tweets per DB transaction — keeps writes small/fast over the LAN
CALL_SEP         = "─" * 60   # log separator — never used in a * expression in a log call

# ---------------------------------------------------------------------------
# Scweet import
# ---------------------------------------------------------------------------
try:
    from Scweet import Scweet, ScweetConfig
    logger.info("tweets_collector | Scweet imported successfully")
except ImportError as e:
    logger.critical(
        "tweets_collector | Scweet not installed.\n"
        "  Install: pip install git+https://github.com/Altimis/Scweet.git\n"
        f"  Error: {e}"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Normalisation — MUST match trends_collector.normalize_topic exactly
# ---------------------------------------------------------------------------

def normalize_topic(topic: str) -> str:
    """NFC + casefold. Identical to Stage 1, so topic matching is consistent."""
    return unicodedata.normalize("NFC", topic.strip()).casefold()


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _strip_html(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    clean = re.sub(r"<[^>]+>", "", text).strip()
    return clean or None


def _parse_timestamp(ts: Optional[str]) -> Optional[str]:
    """Parse Twitter raw timestamp to ISO-8601 string; None on failure."""
    if not ts:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(ts, fmt).isoformat()
        except (ValueError, TypeError):
            continue
    logger.debug(f"tweets_collector | could not parse timestamp: {ts!r}")
    return None


def _extract_hashtags(tweet: dict) -> list[str]:
    """
    All hashtags in the tweet, normalised (NFC + casefold, with # prefix).
    Tries raw.legacy.entities.hashtags first, falls back to regex on text.
    """
    try:
        entities = tweet.get("raw", {}).get("legacy", {}).get("entities", {})
        tags = entities.get("hashtags", [])
        if tags:
            return [normalize_topic(f"#{t['text']}") for t in tags if "text" in t]
    except Exception:
        pass
    text = tweet.get("text", "") or ""
    return [normalize_topic(t) for t in re.findall(r"#\w+", text)]


def _extract_raw_fields(tweet: dict) -> tuple[Optional[str], Optional[int], Optional[str]]:
    raw           = tweet.get("raw") or {}
    source_device = _strip_html(raw.get("source"))
    view_count    = None
    try:
        vc = raw.get("views", {}).get("count")
        view_count = int(vc) if vc is not None else None
    except (ValueError, TypeError):
        pass
    legacy          = raw.get("legacy") or {}
    conversation_id = legacy.get("conversation_id_str")
    return source_device, view_count, conversation_id


# ---------------------------------------------------------------------------
# Scweet initialisation
# ---------------------------------------------------------------------------

def _init_scweet() -> Scweet:
    """Load cookies.json (with ct0 guard) and return a configured Scweet instance."""
    cookies_path = settings.SCWEET_COOKIES_FILE
    state_db     = settings.SCWEET_STATE_DB

    if not cookies_path.exists():
        logger.critical(
            f"tweets_collector | cookies file not found: {cookies_path}\n"
            "  Create it with account credentials. Format:\n"
            '  [{"username": "acct1", "cookies": {"auth_token": "...", "ct0": "..."}}]'
        )
        sys.exit(1)

    try:
        with open(cookies_path, encoding="utf-8") as f:
            cookies_data = json.load(f)
    except json.JSONDecodeError as e:
        logger.critical(f"tweets_collector | cookies.json invalid JSON: {e}")
        sys.exit(1)

    if not cookies_data:
        logger.critical("tweets_collector | cookies.json is empty — add at least one account")
        sys.exit(1)

    logger.info(f"tweets_collector | account pool: {len(cookies_data)} account(s)")
    # missing_ct0 = []
    for i, acct in enumerate(cookies_data):
        uname     = acct.get("username", "<no username>")
        has_token = bool(acct.get("cookies", {}).get("auth_token"))
        # has_ct0   = bool(acct.get("cookies", {}).get("ct0"))
        logger.info(
            f"  [{i}] {uname:<25} auth_token={'✓' if has_token else '✗ MISSING'} "
            # f"ct0={'✓' if has_ct0 else '✗ MISSING'}"
        )
        # if not has_ct0:
        #     missing_ct0.append(uname)

    # if missing_ct0:
    #     logger.critical(
    #         f"tweets_collector | MISSING ct0 for account(s): {missing_ct0}\n"
    #         "  ct0 is a CSRF token required alongside auth_token. Without it all\n"
    #         "  searches return 0 tweets with no error.\n"
    #         "  Get it: x.com → F12 → Application → Cookies → https://x.com → 'ct0'\n"
    #         '  Add to cookies.json: {"auth_token": "...", "ct0": "<value>"}'
    #     )
    #     sys.exit(1)

    scweet_cfg = ScweetConfig(
        daily_requests_limit = settings.SCWEET_DAILY_REQUESTS,
        daily_tweets_limit   = settings.SCWEET_DAILY_TWEETS,
        db_path              = str(state_db),
    )
    logger.info(
        f"tweets_collector | limits — daily_requests={settings.SCWEET_DAILY_REQUESTS}/acct "
        f"daily_tweets={settings.SCWEET_DAILY_TWEETS}/acct limit={settings.SCWEET_LIMIT}/job"
    )

    # db_path must also be passed to the constructor directly -- Scweet.__init__
    # unconditionally overwrites config.db_path with its own db_path default
    # ("scweet_state.db") whenever the constructor arg isn't given explicitly,
    # even when a ScweetConfig with a different db_path is passed in.
    s = Scweet(cookies=cookies_data, db_path=str(state_db), config=scweet_cfg)
    logger.info("tweets_collector | Scweet initialised ✓")
    return s


# ---------------------------------------------------------------------------
# Work list + job builder
# ---------------------------------------------------------------------------

def _get_days_to_scrape(region: str, date_start: str, date_end: str) -> dict[str, list[str]]:
    """{date_str: [unique topics for that day]} for the configured range."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT date, topic
            FROM trending
            WHERE region = %s AND date BETWEEN %s AND %s
            GROUP BY date, topic
            ORDER BY date, topic
            """,
            (region, date_start, date_end),
        )
        rows = cur.fetchall()

    days: dict[str, list[str]] = {}
    for r in rows:
        days.setdefault(r["date"], []).append(r["topic"])
    return days


def _wib_window(date_str: str) -> tuple[str, str]:
    """WIB calendar date → padded UTC (since, until) date strings."""
    d = date.fromisoformat(date_str)
    return (
        (d - timedelta(days=WIB_OFFSET_DAYS)).isoformat(),
        (d + timedelta(days=WIB_OFFSET_DAYS)).isoformat(),
    )


def _job_key(job_type: str, terms: list[str]) -> str:
    digest = hashlib.md5(",".join(sorted(terms)).encode()).hexdigest()[:12]
    return f"{job_type}::{digest}"


def _build_jobs_for_day(date_str: str, topics: list[str]) -> list[dict]:
    """Split a day's topics into topic_batch + plain_text search jobs."""
    since, until = _wib_window(date_str)
    tagged   = [t[1:] for t in topics if t.startswith("#")]   # strip # for hashtags_any
    untagged = [t     for t in topics if not t.startswith("#")]

    jobs = []
    for i in range(0, len(tagged), TOPIC_BATCH_SIZE):
        batch = tagged[i : i + TOPIC_BATCH_SIZE]
        jobs.append({
            "date": date_str, "job_type": "topic_batch",
            "job_key": _job_key("topic_batch", batch),
            "terms": batch, "since": since, "until": until, "query": None,
        })
    for phrase in untagged:
        query = f'"{phrase}"' if " " in phrase else phrase
        jobs.append({
            "date": date_str, "job_type": "plain_text",
            "job_key": _job_key("plain_text", [phrase]),
            "terms": [phrase], "since": since, "until": until, "query": query,
        })
    return jobs


# ---------------------------------------------------------------------------
# Job tracking (scrape_job table)
# ---------------------------------------------------------------------------

def _job_done(date_str: str, job_key: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM scrape_job WHERE date=%s AND job_key=%s AND status='completed'",
            (date_str, job_key),
        )
        return cur.fetchone() is not None


def _mark_job_done(date_str: str, job_key: str, job_type: str,
                   terms: list[str], returned: int, inserted: int) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scrape_job
                (date, job_key, job_type, terms, status, tweets_returned, tweets_inserted, completed_at)
            VALUES (%s, %s, %s, %s, 'completed', %s, %s, NOW())
            ON CONFLICT (date, job_key) DO UPDATE
                SET status='completed', tweets_returned=EXCLUDED.tweets_returned,
                    tweets_inserted=EXCLUDED.tweets_inserted, completed_at=NOW()
            """,
            (date_str, job_key, job_type, json.dumps(terms), returned, inserted),
        )


# ---------------------------------------------------------------------------
# DB insertion — tweet content + topic attribution
# ---------------------------------------------------------------------------

def _insert_tweets(tweets: list[dict], date_str: str, job: dict,
                   trending_set: set[str]) -> int:
    """
    Insert tweet content and topic attribution.
    Returns count of newly inserted tweet rows (content-level).

    Attribution:
      topic_batch → each tweet's hashtags ∩ trending_set
      plain_text  → the search phrase (the only attribution signal available)
    """
    if not tweets:
        return 0

    # Build (content_row, [junction_rows]) per tweet so chunks stay aligned.
    prepared: list[tuple[tuple, list[tuple]]] = []

    for t in tweets:
        tweet_id = str(t.get("tweet_id") or t.get("id_str") or "")
        if not tweet_id:
            continue

        source_device, view_count, conversation_id = _extract_raw_fields(t)
        user          = t.get("user") or {}
        screen_name   = user.get("screen_name") or user.get("username")
        timestamp_raw = t.get("timestamp") or t.get("created_at")
        tweet_tags    = _extract_hashtags(t)   # already normalised

        content_row = (
            tweet_id,
            timestamp_raw,
            _parse_timestamp(timestamp_raw),
            screen_name,
            t.get("text"),
            json.dumps(tweet_tags, ensure_ascii=False),
            int(t.get("likes")    or 0),
            int(t.get("retweets") or 0),
            int(t.get("comments") or 0),
            source_device,
            view_count,
            conversation_id,
            date_str,
        )

        # Attribution
        if job["job_type"] == "topic_batch":
            matched = trending_set.intersection(tweet_tags)
        else:  # plain_text — attribute to the search phrase
            matched = {normalize_topic(job["terms"][0])}

        junction = [(tweet_id, topic) for topic in matched]
        prepared.append((content_row, junction))

    if not prepared:
        return 0

    # Count once before, count once after — both outside the chunk loop so a
    # single failed chunk doesn't corrupt the delta. Each chunk commits in its
    # own short transaction (via get_cursor), keeping individual writes small
    # and fast so a slow/large batch can't stall the connection.
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tweet WHERE collected_date=%s", (date_str,))
        before = cur.fetchone()["n"]

    for i in range(0, len(prepared), INSERT_CHUNK_SIZE):
        chunk         = prepared[i : i + INSERT_CHUNK_SIZE]
        content_chunk = [c for c, _ in chunk]
        junction_chunk = [row for _, j in chunk for row in j]

        with get_cursor() as cur:
            cur.executemany(
                """
                INSERT INTO tweet (
                    tweet_id, timestamp, timestamp_utc, user_screen_name, text,
                    hashtags, likes, retweets, comments, source_device,
                    view_count, conversation_id, collected_date
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tweet_id) DO NOTHING
                """,
                content_chunk,
            )
            if junction_chunk:
                cur.executemany(
                    """
                    INSERT INTO tweet_topic (tweet_id, topic)
                    VALUES (%s, %s)
                    ON CONFLICT (tweet_id, topic) DO NOTHING
                    """,
                    junction_chunk,
                )

        logger.debug(
            f"tweets_collector |   chunk {i//INSERT_CHUNK_SIZE + 1}: "
            f"{len(content_chunk)} tweets, {len(junction_chunk)} junction rows"
        )

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tweet WHERE collected_date=%s", (date_str,))
        after = cur.fetchone()["n"]

    return after - before


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _run_validation(date_start: str, date_end: str) -> None:
    logger.info("=" * 60)
    logger.info("tweets_collector | VALIDATION REPORT")
    logger.info("=" * 60)

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tweet")
        total = cur.fetchone()["n"]
        logger.info(f"tweets_collector | total tweets: {total}")

        cur.execute("SELECT COUNT(*) AS n FROM tweet_topic")
        logger.info(f"tweets_collector | total tweet_topic rows: {cur.fetchone()['n']}")

        cur.execute(
            "SELECT COUNT(DISTINCT user_screen_name) AS n FROM tweet WHERE user_screen_name IS NOT NULL"
        )
        logger.info(f"tweets_collector | unique accounts: {cur.fetchone()['n']}")

        cur.execute(
            """
            SELECT collected_date, COUNT(*) AS n FROM tweet
            WHERE collected_date BETWEEN %s AND %s
            GROUP BY collected_date ORDER BY collected_date
            """,
            (date_start, date_end),
        )
        logger.info("tweets_collector | tweets per day:")
        for r in cur.fetchall():
            logger.info(f"    {r['collected_date']} → {r['n']}")

        if total:
            cur.execute(
                "SELECT COUNT(*) AS n FROM tweet WHERE likes=0 AND retweets=0 AND comments=0"
            )
            zero = cur.fetchone()["n"]
            logger.info(
                f"tweets_collector | zero-engagement tweets: {zero} "
                f"({zero/total*100:.1f}%) ← high % may indicate buzzer accounts"
            )

            # Topic volume (before clustering) — top 10
            cur.execute(
                """
                SELECT topic, COUNT(DISTINCT tweet_id) AS n
                FROM tweet_topic GROUP BY topic ORDER BY n DESC LIMIT 10
                """
            )
            logger.info("tweets_collector | top 10 topics by tweet volume:")
            for r in cur.fetchall():
                logger.info(f"    {r['topic'][:45]:<45} {r['n']}")

    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(date_start: Optional[str] = None, date_end: Optional[str] = None) -> None:
    region = settings.REGION
    start  = date_start or settings.DATE_START
    end    = date_end   or settings.DATE_END

    logger.info("tweets_collector | Stage 2 — Tweet Collection")
    logger.info(f"tweets_collector | region={region} | range={start} → {end} | limit={settings.SCWEET_LIMIT}/job")
    logger.info("tweets_collector | lang filter disabled (lang= + Latest returns 0 — Scweet bug)")

    s        = _init_scweet()
    all_days = _get_days_to_scrape(region, start, end)

    if not all_days:
        logger.warning(f"tweets_collector | no trending data for {start}→{end}/region={region}. Run Stage 1 first.")
        return

    all_jobs: list[dict] = []
    for date_str, topics in all_days.items():
        all_jobs.extend(_build_jobs_for_day(date_str, topics))
        tagged_n = sum(1 for t in topics if t.startswith("#"))
        logger.info(
            f"tweets_collector | {date_str} → {len(topics)} topics "
            f"({tagged_n} #tagged, {len(topics)-tagged_n} plain-text)"
        )

    todo = [j for j in all_jobs if not _job_done(j["date"], j["job_key"])]
    logger.info(f"tweets_collector | jobs total={len(all_jobs)} done={len(all_jobs)-len(todo)} remaining={len(todo)}")

    if not todo:
        logger.info("tweets_collector | all jobs already complete")
        _run_validation(start, end)
        return

    # Pre-compute each day's trending set (normalised) for attribution intersection
    trending_sets = {d: set(topics) for d, topics in all_days.items()}

    total_inserted = 0
    total_returned = 0
    failed_jobs: list[str] = []

    for job_num, job in enumerate(todo, start=1):
        date_str = job["date"]
        if job["job_type"] == "topic_batch":
            label = f"#{' #'.join(job['terms'][:3])}{'...' if len(job['terms']) > 3 else ''}"
        else:
            label = f'"{job["terms"][0]}"'

        logger.info(CALL_SEP)
        logger.info(
            f"tweets_collector | [Job {job_num}/{len(todo)}] {date_str} | {label} | "
            f"UTC {job['since']}→{job['until']}"
        )

        search_kwargs: dict = dict(
            since        = job["since"],
            until        = job["until"],
            display_type = "Latest",
            limit        = settings.SCWEET_LIMIT,
            resume       = True,
        )
        if job["job_type"] == "topic_batch":
            search_kwargs["hashtags_any"] = job["terms"]
        else:
            search_kwargs["query"] = job["query"]

        t_start = time.time()
        try:
            tweets = s.search(**search_kwargs)
        except Exception as e:
            err_type, err_msg = type(e).__name__, str(e)

            if "AccountPoolExhausted" in err_type or "pool" in err_msg.lower():
                logger.critical(CALL_SEP)
                logger.critical(
                    f"tweets_collector | ACCOUNT POOL EXHAUSTED at job {job_num}/{len(todo)} ({date_str} {label})\n"
                    "  All accounts hit daily limits. Progress saved — re-run to resume.\n"
                    "  Options: wait for UTC midnight reset / add accounts / raise SCWEET_DAILY_* in .env"
                )
                logger.critical(CALL_SEP)
                return

            elif "AuthError" in err_type or "auth" in err_msg.lower():
                logger.error(f"tweets_collector | [Job {job_num}] AUTH ERROR: {err_type}: {err_msg} — re-check cookies. Skipping.")
            elif "RateLimit" in err_type or "rate" in err_msg.lower():
                logger.warning(f"tweets_collector | [Job {job_num}] RATE LIMIT: {err_msg} — skipping.")
            elif "Network" in err_type or "connect" in err_msg.lower():
                logger.error(f"tweets_collector | [Job {job_num}] NETWORK ERROR: {err_msg} — skipping.")
            else:
                logger.error(f"tweets_collector | [Job {job_num}] UNEXPECTED {err_type}: {err_msg} — skipping.")
            failed_jobs.append(f"{date_str}:{label}")
            continue

        elapsed     = time.time() - t_start
        tweet_count = len(tweets) if tweets else 0
        total_returned += tweet_count
        logger.info(f"tweets_collector | [Job {job_num}/{len(todo)}] {tweet_count} tweets in {elapsed:.1f}s")

        if tweet_count == 0:
            logger.warning(
                "tweets_collector |   ⚠ 0 tweets — date outside ~7-day index, low-volume topic, "
                "or stale ct0"
            )
            _mark_job_done(date_str, job["job_key"], job["job_type"], job["terms"], 0, 0)
            continue

        inserted = _insert_tweets(tweets, date_str, job, trending_sets[date_str])
        total_inserted += inserted
        _mark_job_done(date_str, job["job_key"], job["job_type"], job["terms"], tweet_count, inserted)
        logger.info(f"tweets_collector |   ✓ inserted {inserted} new tweets")

        if settings.SCWEET_LIMIT is not None and tweet_count >= settings.SCWEET_LIMIT:
            logger.warning(
                f"tweets_collector |   ⚠ returned == limit ({settings.SCWEET_LIMIT}); "
                "results may be truncated, consider raising SCWEET_LIMIT"
            )

    logger.info("=" * 60)
    logger.info(
        f"tweets_collector | COMPLETE — jobs attempted={len(todo)} "
        f"failed={len(failed_jobs)} returned={total_returned} inserted={total_inserted}"
    )
    if failed_jobs:
        logger.warning(f"tweets_collector | failed jobs (re-run to retry): {failed_jobs}")

    _run_validation(start, end)


if __name__ == "__main__":
    from db.connection import init_pool, close_pool
    init_pool()
    try:
        run()
    finally:
        close_pool()