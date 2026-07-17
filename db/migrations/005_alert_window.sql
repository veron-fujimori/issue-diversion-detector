-- Migration: 005_alert_window.sql
-- Menyimpan window waktu aktual yang dipakai detector untuk menghitung
-- korelasi/spike per alert. WINDOW_HOURS di detector bisa merentang lintas
-- hari (peak bisa jatuh di "kemarin" kalau spike-nya sudah mulai sebelum
-- tengah malam), jadi analyzer butuh window ini -- bukan cuma detected_at --
-- supaya tweet yang dianalisis konsisten dengan tweet yang dipakai detector
-- untuk menghitung korelasi/spike-nya.
--
-- Nullable karena alert lama (sebelum migrasi ini) tidak punya window_start/
-- window_end; analyzer fallback ke rentang detected_at satu hari penuh kalau
-- kolom ini NULL.

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS window_end   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_alerts_window_start ON alerts(window_start);
