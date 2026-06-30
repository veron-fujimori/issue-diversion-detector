-- Migration: 001_init.sql
-- Baseline schema for the narrative-displacement pipeline.

-- ── Trending Topics ──
-- One row per (region, date, time_slot, rank).
-- A topic may appear in many slots across a day; deduplication for search is handled in the collector.
CREATE TABLE IF NOT EXISTS trending (
    id          SERIAL  PRIMARY KEY,
    region      TEXT    NOT NULL,
    date        TEXT    NOT NULL,        -- archive date key, e.g. '2026-05-24'
    time_slot   TEXT    NOT NULL,        -- on-the-hour slot, e.g. '08:00'
    rank        INTEGER NOT NULL,
    topic       TEXT    NOT NULL,        -- raw trending term (hashtag or phrase), normalized
    UNIQUE (region, date, time_slot, rank)
);

CREATE INDEX IF NOT EXISTS idx_trending_topic ON trending(topic);
CREATE INDEX IF NOT EXISTS idx_trending_date  ON trending(date);

-- ── Raw tweets from Scweet (Stage 2 output) ──
-- One immutable row per tweet (tweet_id is the natural key). 
-- Content is never duplicated and never mutated after insert.
-- Topic attribution lives in the tweet_topic junction table, not here.
CREATE TABLE IF NOT EXISTS tweet (
    tweet_id            TEXT        PRIMARY KEY,
    timestamp           TEXT,                       -- raw string from Scweet (audit trail)
    timestamp_utc       TIMESTAMPTZ,                -- parsed UTC instant; used for slot volume queries
    user_screen_name    TEXT,
    text                TEXT,
    hashtags            TEXT,                       -- JSON list of ALL hashtags found in the tweet text
    likes               INTEGER     DEFAULT 0,
    retweets            INTEGER     DEFAULT 0,
    comments            INTEGER     DEFAULT 0,
    source_device       TEXT,
    view_count          INTEGER,
    conversation_id     TEXT,
    collected_date      TEXT                        -- date key the collection job ran for
);

CREATE INDEX IF NOT EXISTS idx_tweet_timestamp_utc  ON tweet(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_tweet_collected_date ON tweet(collected_date);
CREATE INDEX IF NOT EXISTS idx_tweet_user           ON tweet(user_screen_name);

-- ── Tweet ↔ trending-topic attribution (junction) ───────────────────────────
-- One row per (tweet, trending topic it matched).
-- Populated during fetch: each Scweet search inserts its tweets here tagged with every trending topic the tweet matched. 
-- The composite PK makes re-matches idempotent — a tweet returned by several searches accumulates one junction row per distinct topic.
CREATE TABLE IF NOT EXISTS tweet_topic (
    tweet_id    TEXT NOT NULL REFERENCES tweet(tweet_id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    PRIMARY KEY (tweet_id, topic)
);

CREATE INDEX IF NOT EXISTS idx_tweet_topic_topic    ON tweet_topic(topic);
CREATE INDEX IF NOT EXISTS idx_tweet_topic_tweet_id ON tweet_topic(tweet_id);

-- ── Scrape job tracking (Stage 2 resume) ──
-- One row per search job (a topic batch or a single plain-text phrase) per date.
-- Lets an interrupted collection resume without re-fetching completed jobs.
CREATE TABLE IF NOT EXISTS scrape_job (
    id              SERIAL      PRIMARY KEY,
    date            TEXT        NOT NULL,
    job_key         TEXT        NOT NULL,
    job_type        TEXT        NOT NULL,           -- 'topic_batch' | 'plain_text'
    terms           TEXT        NOT NULL,           -- JSON list of the job's search terms
    status          TEXT        NOT NULL DEFAULT 'pending',
    tweets_returned INTEGER     DEFAULT 0,
    tweets_inserted INTEGER     DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (date, job_key)
);

CREATE INDEX IF NOT EXISTS idx_scrape_job_date   ON scrape_job(date);
CREATE INDEX IF NOT EXISTS idx_scrape_job_status ON scrape_job(status);