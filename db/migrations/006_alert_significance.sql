-- Migration: 006_alert_significance.sql
-- Menyimpan signifikansi statistik korelasi per alert.
--
-- p_value: probabilitas satu-arah bahwa korelasi sekuat ini (atau lebih
-- negatif) muncul murni dari noise, dihitung dari korelasi + jumlah data
-- point aktual yang dipakai (n bisa kecil, 6-25 titik per jam).
-- p_value_adjusted: p_value di atas setelah dikoreksi Benjamini-Hochberg
-- (FDR) lintas semua pasangan cluster yang diuji pada tanggal yang sama --
-- makin banyak pasangan diuji hari itu, makin ketat koreksinya.
--
-- Keduanya HANYA disimpan untuk visibilitas/tuning (dashboard, score_breakdown)
-- -- tidak dipakai sebagai gate di detector.py. scorer.py memakainya sebagai
-- faktor kepercayaan kontinu (1 - p_value_adjusted) pada skor korelasi.
--
-- Nullable karena alert lama (sebelum migrasi ini) tidak punya nilai ini.

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS p_value          FLOAT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS p_value_adjusted FLOAT;
