-- Migration: 004_alerts.sql
-- Menyimpan hasil deteksi displacement antar pasangan cluster.
-- Setiap baris merepresentasikan satu pasangan cluster yang dicurigai
-- mengalami pengalihan isu, beserta detail skornya.

CREATE TABLE IF NOT EXISTS alerts (
    id                    SERIAL       PRIMARY KEY,
    detected_at           DATE         NOT NULL,

    -- Cluster yang mengalami spike (naik mendadak)
    rising_cluster_id     INTEGER      NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    rising_cluster_label  VARCHAR(255) NOT NULL,

    -- Cluster yang mengalami decay (turun bersamaan)
    falling_cluster_id    INTEGER      NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    falling_cluster_label VARCHAR(255) NOT NULL,

    -- Sinyal dari detector (ikut masuk ke skor akhir)
    lag_hours             INTEGER      NOT NULL,
    correlation           FLOAT        NOT NULL,
    spike_magnitude       FLOAT        NOT NULL,

    -- Hasil akhir scoring (diisi oleh scorer)
    confidence_score      FLOAT        DEFAULT NULL,  -- 0-100
    score_breakdown       JSONB        DEFAULT NULL,

    created_at            TIMESTAMPTZ  DEFAULT NOW(),

    UNIQUE (detected_at, rising_cluster_id, falling_cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_detected_at     ON alerts(detected_at);
CREATE INDEX IF NOT EXISTS idx_alerts_rising_cluster  ON alerts(rising_cluster_id);
CREATE INDEX IF NOT EXISTS idx_alerts_falling_cluster ON alerts(falling_cluster_id);
CREATE INDEX IF NOT EXISTS idx_alerts_confidence      ON alerts(confidence_score);