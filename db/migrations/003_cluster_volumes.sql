-- Migration: 003_cluster_volumes.sql
-- Menyimpan volume tweet per cluster per slot waktu 4 jam.
-- slot_start adalah timestamp awal dari window 4 jam tersebut (misal: 2024-11-01 20:00:00+07).
-- Dengan satu kolom timestamp, timeseries bersifat kontinu dan tidak putus di tengah malam.

CREATE TABLE IF NOT EXISTS cluster_volumes (
    id          SERIAL      PRIMARY KEY,
    cluster_id  INTEGER     NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    slot_start  TIMESTAMPTZ NOT NULL,
    tweet_count INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (cluster_id, slot_start)
);

CREATE INDEX IF NOT EXISTS idx_cluster_volumes_cluster_id ON cluster_volumes(cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_volumes_slot_start ON cluster_volumes(slot_start);