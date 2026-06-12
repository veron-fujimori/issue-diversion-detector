-- Migration: 002_clusters.sql
-- Menyimpan hasil clustering trending topic per hari

CREATE TABLE IF NOT EXISTS clusters (
    id            SERIAL PRIMARY KEY,
    date          DATE         NOT NULL,
    cluster_label VARCHAR(255) NOT NULL,
    topics        TEXT[]       NOT NULL,
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

-- Index untuk query berdasarkan tanggal (paling sering dipakai)
CREATE INDEX IF NOT EXISTS idx_clusters_date ON clusters(date);