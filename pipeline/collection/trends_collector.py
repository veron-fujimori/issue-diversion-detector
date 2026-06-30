"""
pipeline/collection/trends_collector.py — Trending Topic Collection

Fetches fully-rendered pages from the trending archive (data is injected by
JavaScript, so plain HTTP requests cannot be used) via a headless Edge browser.
One browser instance is reused across all days to minimise startup overhead.

Parsed entries are normalised (NFC + casefold) and written to the `trending`
table, keyed on (region, date, time_slot, rank).

Run standalone:
    python -m pipeline.collection.trends_collector

Or via the orchestrator (see pipeline.orchestrator).
"""

import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from config.settings import settings
from db.connection import get_cursor
from utils.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAGE_LOAD_TIMEOUT = 20    # seconds to wait for tek_tablo to appear
FETCH_DELAY       = 2.0   # polite delay between live fetches (seconds)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalize_topic(topic: str) -> str:
    """
    Normalise a trending term for consistent matching across languages.
    NFC composes equivalent Unicode sequences; casefold is the Unicode-aware
    lowercase suitable for caseless comparison. Must be applied identically
    here (Stage 1 insert) and in the tweet collector (extraction + junction
    insert), or topic matching will silently fail.
    """
    return unicodedata.normalize("NFC", topic.strip()).casefold()


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _date_range(start: str, end: str):
    """Yield date objects from start to end inclusive."""
    current = date.fromisoformat(start)
    stop    = date.fromisoformat(end)
    while current <= stop:
        yield current
        current += timedelta(days=1)


def _archive_url(d: date, region: str) -> str:
    """Build archive URL: {base}/{region}/DD-MM-YYYY"""
    return f"{settings.TRENDING_BASE_URL}/{region}/{d.strftime('%d-%m-%Y')}"


def _cache_path(d: date) -> Path:
    """Local cache path: data/raw/trending/YYYY-MM-DD.html"""
    return settings.TRENDING_DIR / f"{d.isoformat()}.html"


# ---------------------------------------------------------------------------
# Browser driver (one instance for the whole run)
# ---------------------------------------------------------------------------

def _init_driver() -> webdriver.Edge:
    """
    Initialise a headless Edge browser.
    webdriver-manager auto-downloads the matching EdgeDriver version.
    """
    logger.info("trends_collector | initialising headless Edge browser...")
    edge_options = Options()
    edge_options.add_argument("--headless")
    edge_options.add_argument("--log-level=3")
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")

    driver = webdriver.Edge(
        service=Service(EdgeChromiumDriverManager().install()),
        options=edge_options,
    )
    logger.info("trends_collector | browser ready")
    return driver


def _fetch_rendered_html(driver: webdriver.Edge, url: str) -> Optional[str]:
    """
    Load URL, wait for JavaScript to inject trend data, return page source.
    Returns None on failure.
    """
    try:
        driver.get(url)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.CLASS_NAME, "tek_tablo"))
        )
        return driver.page_source
    except Exception as exc:
        logger.warning(f"trends_collector | browser fetch failed for {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _parse_time_slots(html: str, interval_hours: int) -> list[dict]:
    """
    Parse all trending entries from a single day's rendered HTML.
    Only on-the-hour slots that are multiples of interval_hours are kept.
    Returns list of {time_slot, rank, topic}.
    """
    soup = BeautifulSoup(html, "html.parser")
    time_blocks = soup.find_all("div", class_="tek_tablo")
    logger.debug(f"trends_collector | found {len(time_blocks)} tek_tablo blocks")

    if not time_blocks:
        logger.warning("trends_collector | no tek_tablo blocks — page may not have rendered")
        return []

    results = []
    for block in time_blocks:
        time_tag = block.find("div", class_="trend_baslik611")
        if not time_tag:
            continue

        raw_time = time_tag.get_text(strip=True)
        try:
            time_obj = datetime.strptime(raw_time, "%H:%M")
        except ValueError:
            logger.debug(f"trends_collector | could not parse time: {raw_time!r}")
            continue

        # Interval filter: on-the-hour multiples only
        if time_obj.minute != 0 or time_obj.hour % interval_hours != 0:
            continue

        time_slot = f"{time_obj.hour:02d}:00"

        for row in block.find_all("tr", class_="tr_table"):
            rank_td  = row.find("td",   class_="sira611")
            topic_td = row.find("span", class_="word_ars")
            if not rank_td or not topic_td:
                continue

            raw_text = topic_td.get_text(strip=True)
            if not raw_text:
                continue

            try:
                rank = int(rank_td.get_text(strip=True))
            except ValueError:
                continue

            results.append({
                "time_slot": time_slot,
                "rank":      rank,
                "topic":     normalize_topic(raw_text),
            })

    return results


# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------

def _insert_trends(entries: list[dict], date_str: str, region: str) -> int:
    """
    INSERT ... ON CONFLICT DO NOTHING into trending.
    Returns number of newly inserted rows.
    """
    if not entries:
        return 0

    rows = [
        (region, date_str, e["time_slot"], e["rank"], e["topic"])
        for e in entries
    ]

    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM trending WHERE date=%s AND region=%s",
            (date_str, region),
        )
        before = cur.fetchone()["n"]

        cur.executemany(
            """
            INSERT INTO trending (region, date, time_slot, rank, topic)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

        cur.execute(
            "SELECT COUNT(*) AS n FROM trending WHERE date=%s AND region=%s",
            (date_str, region),
        )
        after = cur.fetchone()["n"]

    return after - before


# ---------------------------------------------------------------------------
# Per-day processing
# ---------------------------------------------------------------------------

def _process_day(d: date, region: str, interval_hours: int, driver: webdriver.Edge) -> dict:
    """Fetch (or load from cache), parse, and insert one day's trends."""
    date_str   = d.isoformat()
    cache_file = _cache_path(d)

    status = {
        "date":          date_str,
        "source":        None,
        "slots_found":   0,
        "rows_inserted": 0,
        "skipped":       0,
        "error":         None,
    }

    # ── Load from cache or fetch live ─────────────────────────────────────
    if cache_file.exists():
        logger.info(f"trends_collector | [{date_str}] loading from cache")
        try:
            html = cache_file.read_text(encoding="utf-8")
            status["source"] = "cache"
        except Exception as exc:
            logger.error(f"trends_collector | [{date_str}] failed to read cache: {exc}")
            status["error"] = str(exc)
            return status
    else:
        url = _archive_url(d, region)
        logger.info(f"trends_collector | [{date_str}] fetching {url}")
        html = _fetch_rendered_html(driver, url)

        if html is None:
            status["error"] = "fetch_failed"
            return status

        if "tek_tablo" not in html:
            logger.warning(f"trends_collector | [{date_str}] rendered HTML missing tek_tablo — saving for inspection")
            cache_file.write_text(html, encoding="utf-8")
            status["error"] = "unexpected_html"
            return status

        try:
            cache_file.write_text(html, encoding="utf-8")
            logger.debug(f"trends_collector | [{date_str}] saved cache: {cache_file}")
        except Exception as exc:
            logger.warning(f"trends_collector | [{date_str}] could not save cache: {exc}")

        status["source"] = "fetch"
        time.sleep(FETCH_DELAY)

    # ── Parse ─────────────────────────────────────────────────────────────
    entries = _parse_time_slots(html, interval_hours)
    status["slots_found"] = len(entries)

    if not entries:
        logger.warning(f"trends_collector | [{date_str}] no entries parsed — check cache file")
        return status

    # ── Insert ────────────────────────────────────────────────────────────
    inserted = _insert_trends(entries, date_str, region)
    status["rows_inserted"] = inserted
    status["skipped"]       = len(entries) - inserted

    logger.info(
        f"trends_collector | [{date_str}] {len(entries)} parsed → "
        f"{inserted} inserted, {len(entries) - inserted} skipped"
    )
    return status


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

def _run_validation(region: str, start: str, end: str, interval: int) -> None:
    logger.info("=" * 60)
    logger.info("trends_collector | VALIDATION REPORT")
    logger.info("=" * 60)

    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM trending WHERE region=%s AND date BETWEEN %s AND %s",
            (region, start, end),
        )
        total = cur.fetchone()["n"]
        logger.info(f"trends_collector | total rows: {total}")

        days          = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        slots_per_day = 24 // interval
        expected      = days * slots_per_day * 10
        pct           = (total / expected * 100) if expected else 0
        logger.info(
            f"trends_collector | expected (upper bound): {expected} "
            f"({days} days × {slots_per_day} slots × 10) | coverage: {pct:.1f}%"
        )

        cur.execute(
            "SELECT date, COUNT(*) AS n FROM trending WHERE region=%s AND date BETWEEN %s AND %s GROUP BY date",
            (region, start, end),
        )
        rows_by_day = {r["date"]: r["n"] for r in cur.fetchall()}
        zero_days = [
            d.isoformat() for d in _date_range(start, end)
            if d.isoformat() not in rows_by_day
        ]
        if zero_days:
            logger.warning(f"trends_collector | days with NO data ({len(zero_days)}): {zero_days}")
        else:
            logger.info("trends_collector | days with NO data: 0 ✓")

        cur.execute(
            "SELECT COUNT(*) AS n FROM trending WHERE (topic IS NULL OR topic='') "
            "AND region=%s AND date BETWEEN %s AND %s",
            (region, start, end),
        )
        logger.info(f"trends_collector | empty topic rows: {cur.fetchone()['n']}")

        cur.execute(
            """
            SELECT topic, COUNT(*) AS n
            FROM trending WHERE region=%s AND date BETWEEN %s AND %s
            GROUP BY topic ORDER BY n DESC LIMIT 10
            """,
            (region, start, end),
        )
        logger.info("trends_collector | top 10 topics by trending frequency:")
        for r in cur.fetchall():
            logger.info(f"    {r['topic'][:45]:<45}  {r['n']} appearances")

    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(date_start: Optional[str] = None, date_end: Optional[str] = None) -> None:
    """
    Collect trending topics for the given date range.
    Falls back to settings.DATE_START / settings.DATE_END if not provided.
    """
    region   = settings.REGION
    start    = date_start or settings.DATE_START
    end      = date_end   or settings.DATE_END
    interval = settings.TREND_INTERVAL

    logger.info("trends_collector | Stage 1 — Trending Topic Collection")
    logger.info(f"trends_collector | region={region} | range={start} → {end} | interval={interval}h")

    all_dates = list(_date_range(start, end))
    logger.info(f"trends_collector | processing {len(all_dates)} days...")

    driver  = _init_driver()
    results = []
    failed  = []

    try:
        for d in all_dates:
            status = _process_day(d, region, interval, driver)
            results.append(status)
            if status["error"]:
                failed.append(status["date"])
    finally:
        driver.quit()
        logger.debug("trends_collector | browser closed")

    total_inserted = sum(r["rows_inserted"] for r in results)
    total_parsed   = sum(r["slots_found"]   for r in results)
    cached_days    = sum(1 for r in results if r["source"] == "cache")
    fetched_days   = sum(1 for r in results if r["source"] == "fetch")

    logger.info("trends_collector | run complete")
    logger.info(f"trends_collector | days={len(all_dates)} cache={cached_days} fetched={fetched_days} failed={len(failed)}")
    logger.info(f"trends_collector | parsed={total_parsed} inserted={total_inserted}")

    if failed:
        logger.warning(f"trends_collector | failed days: {failed}")

    _run_validation(region, start, end, interval)


if __name__ == "__main__":
    from db.connection import init_pool, close_pool
    init_pool()
    try:
        run()
    finally:
        close_pool()