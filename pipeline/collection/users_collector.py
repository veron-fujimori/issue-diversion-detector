"""
pipeline/collection/users_collector.py — Stage 2b: User Profile Collection

Fetches profiles (via Scweet get_user_info) for every account that appears in
the tweet table but does not yet have a row in the "user" table. Run after the
tweets collector; enables the analyzer's account-level coordination signals
(new-account, low-followers, follower/following ratio).

Run standalone:
    python -m pipeline.collection.users_collector

Resume:     Safe to re-run. Only accounts missing a user row are fetched.
Idempotent: Yes — ON CONFLICT (user_id) DO NOTHING.
"""

import sys
from datetime import datetime
from typing import Optional

from config.settings import settings
from db.connection import get_cursor
from utils.logger import logger

# ---------------------------------------------------------------------------
# Scweet import
# ---------------------------------------------------------------------------
try:
    from Scweet import Scweet, ScweetConfig
    logger.info("users_collector | Scweet imported successfully")
except ImportError as e:
    logger.critical(
        "users_collector | Scweet not installed.\n"
        "  Install: pip install git+https://github.com/Altimis/Scweet.git\n"
        f"  Error: {e}"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _parse_created_at(ts: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Parse a Twitter account creation date string.
    Returns (iso_string_or_None, raw_string). The ISO form is stored in the
    TIMESTAMPTZ column; the raw form is kept for audit.
    """
    if not ts:
        return None, None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(ts, fmt).isoformat(), ts
        except (ValueError, TypeError):
            continue
    logger.debug(f"users_collector | could not parse created_at: {ts!r}")
    return None, ts


# ---------------------------------------------------------------------------
# Scweet initialisation (mirrors tweets_collector; ct0 not required for now)
# ---------------------------------------------------------------------------

def _init_scweet() -> Scweet:
    cookies_path = settings.SCWEET_COOKIES_FILE
    state_db     = settings.SCWEET_STATE_DB

    if not cookies_path.exists():
        logger.critical(f"users_collector | cookies file not found: {cookies_path}")
        sys.exit(1)

    import json
    try:
        with open(cookies_path, encoding="utf-8") as f:
            cookies_data = json.load(f)
    except json.JSONDecodeError as e:
        logger.critical(f"users_collector | cookies.json invalid JSON: {e}")
        sys.exit(1)

    if not cookies_data:
        logger.critical("users_collector | cookies.json is empty")
        sys.exit(1)

    logger.info(f"users_collector | account pool: {len(cookies_data)} account(s)")
    for i, acct in enumerate(cookies_data):
        uname     = acct.get("username", "<no username>")
        has_token = bool(acct.get("cookies", {}).get("auth_token"))
        logger.info(f"  [{i}] {uname:<25} auth_token={'✓' if has_token else '✗ MISSING'}")
        if not has_token:
            logger.critical(f"users_collector | account '{uname}' missing auth_token")
            sys.exit(1)

    scweet_cfg = ScweetConfig(
        daily_requests_limit = settings.SCWEET_DAILY_REQUESTS,
        daily_tweets_limit   = settings.SCWEET_DAILY_TWEETS,
        db_path              = str(state_db),
    )
    s = Scweet(cookies=cookies_data, config=scweet_cfg)
    logger.info("users_collector | Scweet initialised ✓")
    return s


# ---------------------------------------------------------------------------
# Work list
# ---------------------------------------------------------------------------

def _get_usernames_needing_profiles() -> list[str]:
    """Distinct tweet authors that have no row in the user table yet."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT t.user_screen_name
            FROM tweet t
            LEFT JOIN "user" u ON u.screen_name = t.user_screen_name
            WHERE t.user_screen_name IS NOT NULL
              AND u.screen_name IS NULL
            ORDER BY t.user_screen_name
            """
        )
        return [r["user_screen_name"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Field mapping + insertion
# ---------------------------------------------------------------------------

def _map_user_record(u: dict) -> Optional[tuple]:
    """
    Map a Scweet user record to the "user" table column order.
    Returns None if the record lacks a usable screen_name.
    """
    screen_name = u.get("username") or u.get("screen_name")
    if not screen_name:
        return None

    created_iso, created_raw = _parse_created_at(u.get("created_at"))

    return (
        str(u.get("user_id") or u.get("id_str") or ""),
        screen_name,
        u.get("name"),
        u.get("description") or "",
        u.get("location"),
        created_iso,
        created_raw,
        int(u.get("followers_count") or 0),
        int(u.get("following_count") or u.get("friends_count") or 0),
        int(u.get("statuses_count") or 0),
        int(u.get("favourites_count") or 0),
        int(u.get("media_count") or 0),
        int(u.get("listed_count") or 0),
        int(bool(u.get("verified"))),
        int(bool(u.get("blue_verified"))),
        int(bool(u.get("protected"))),
        u.get("url"),
    )


def _insert_users(records: list[dict]) -> int:
    """Insert user rows. Returns count of newly inserted rows."""
    rows = [r for r in (_map_user_record(u) for u in records) if r is not None]
    if not rows:
        return 0

    with get_cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM "user"')
        before = cur.fetchone()["n"]

        cur.executemany(
            """
            INSERT INTO "user" (
                user_id, screen_name, display_name, description, location,
                created_at, created_at_raw, followers_count, following_count,
                statuses_count, favourites_count, media_count, listed_count,
                verified, blue_verified, protected, url
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            rows,
        )

        cur.execute('SELECT COUNT(*) AS n FROM "user"')
        after = cur.fetchone()["n"]

    return after - before


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _run_validation() -> None:
    logger.info("=" * 60)
    logger.info("users_collector | VALIDATION REPORT")
    logger.info("=" * 60)

    with get_cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM "user"')
        total = cur.fetchone()["n"]
        logger.info(f"users_collector | total user profiles: {total}")

        # Coverage: tweet authors with vs without a profile
        cur.execute(
            """
            SELECT COUNT(DISTINCT t.user_screen_name) AS n
            FROM tweet t
            LEFT JOIN "user" u ON u.screen_name = t.user_screen_name
            WHERE t.user_screen_name IS NOT NULL AND u.screen_name IS NULL
            """
        )
        missing = cur.fetchone()["n"]
        logger.info(f"users_collector | authors still missing a profile: {missing}")

        if total:
            cur.execute('SELECT COUNT(*) AS n FROM "user" WHERE created_at IS NULL')
            logger.info(f"users_collector | profiles with NULL created_at: {cur.fetchone()['n']}")

            cur.execute('SELECT COUNT(*) AS n FROM "user" WHERE followers_count < 50')
            low = cur.fetchone()["n"]
            logger.info(f"users_collector | profiles with <50 followers: {low} ({low/total*100:.1f}%)")

    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    logger.info("users_collector | Stage 2b — User Profile Collection")

    usernames = _get_usernames_needing_profiles()
    total = len(usernames)
    logger.info(f"users_collector | accounts needing profiles: {total}")

    if not total:
        logger.info("users_collector | all authors already have profiles — nothing to do")
        _run_validation()
        return

    s          = _init_scweet()
    batch_size = settings.SCWEET_USER_INFO_BATCH
    inserted_total = 0

    for i in range(0, total, batch_size):
        batch     = usernames[i : i + batch_size]
        batch_num = i // batch_size + 1
        logger.info(
            f"users_collector | batch {batch_num} — fetching {len(batch)} accounts "
            f"({i+1}–{min(i+batch_size, total)} of {total})"
        )

        try:
            records = s.get_user_info(usernames=batch)
        except Exception as e:
            err_type = type(e).__name__
            if "AccountPoolExhausted" in err_type or "pool" in str(e).lower():
                logger.critical(
                    "users_collector | ACCOUNT POOL EXHAUSTED. Tweet data intact. "
                    "Re-run to finish profiles after quota reset."
                )
                sys.exit(1)
            logger.error(f"users_collector | batch {batch_num} error: {err_type}: {e} — skipping")
            continue

        if not records:
            logger.warning(f"users_collector | batch {batch_num} returned 0 records")
            continue

        inserted = _insert_users(records)
        inserted_total += inserted
        logger.info(f"users_collector | batch {batch_num} — inserted {inserted} new profiles")

    logger.info(f"users_collector | complete — total inserted: {inserted_total}")
    _run_validation()


if __name__ == "__main__":
    from db.connection import init_pool, close_pool
    init_pool()
    try:
        run()
    finally:
        close_pool()