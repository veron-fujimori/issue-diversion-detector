from datetime import datetime, timedelta, timezone
from itertools import combinations
from scipy import stats
from scipy.stats import false_discovery_control
from config.settings import settings
from db.repositories.alert_repo import save_alert
from db.repositories.cluster_repo import get_clusters_by_date
from db.repositories.volume_repo import get_volumes_grouped_by_cluster
from utils.logger import logger

WIB = timezone(timedelta(hours=7))
WINDOW_HOURS = 48
LAG_SLOTS = [0, 1, 2, 3]
CORRELATION_THRESHOLD = settings.CORRELATION_THRESHOLD
SPIKE_RATIO_THRESHOLD = settings.SPIKE_RATIO_THRESHOLD
MIN_DATA_POINTS = 6
CORR_WINDOW_HOURS = 12

def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2 or len(y) != n:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)

def _apply_lag_pair(a, b, lag):
    if lag == 0:
        return a, b
    n = len(a)
    if lag >= n:
        return [], []
    return a[: n - lag], b[lag:]

def _spike_ratio(series):
    if not series or max(series) == 0:
        return 0.0
    mean_val = sum(series) / len(series)
    if mean_val == 0:
        return 0.0
    return max(series) / mean_val

def _peak_slot_index(series):
    if not series or max(series) == 0:
        return 0
    return series.index(max(series))

def _trim_around_peak(series_a, series_b, peak_idx):
    """Potong kedua series ke window sama panjang di sekitar peak_idx.
    hi dibatasi oleh series TERPENDEK — bug sebelumnya cuma cek len(series_a),
    bisa bikin series_a & series_b keluar dengan panjang beda dan index waktu
    jadi gak sejajar lagi setelah di-zip di _pearson.

    Balikin juga (lo, hi) supaya caller bisa map index balik ke timestamp asli
    di `timeline` (dipakai untuk isi alerts.window_start/window_end)."""
    half_window = CORR_WINDOW_HOURS // settings.VOLUME_INTERVAL_HOURS
    shortest = min(len(series_a), len(series_b))
    lo = max(0, peak_idx - half_window)
    hi = min(shortest, peak_idx + half_window + 1)
    return series_a[lo:hi], series_b[lo:hi], lo, hi

def _best_lagged_correlation(series_a, series_b):
    best_corr = 1.0
    best_lag = 0
    best_n = 0
    for lag_slot in LAG_SLOTS:
        a1, b1 = _apply_lag_pair(series_a, series_b, lag_slot)
        if len(a1) >= MIN_DATA_POINTS:
            corr = _pearson(a1, b1)
            if corr < best_corr:
                best_corr, best_lag, best_n = corr, lag_slot * settings.VOLUME_INTERVAL_HOURS, len(a1)
        if lag_slot == 0:
            continue
        b2, a2 = _apply_lag_pair(series_b, series_a, lag_slot)
        if len(a2) >= MIN_DATA_POINTS:
            corr = _pearson(a2, b2)
            if corr < best_corr:
                best_corr, best_lag, best_n = corr, -(lag_slot * settings.VOLUME_INTERVAL_HOURS), len(a2)
    return best_corr, best_lag, best_n


def _one_tailed_pvalue(r: float, n: int) -> float:
    """
    P(korelasi senegatif ini atau lebih, murni dari noise) — one-tailed
    karena kita cuma peduli arah negatif (displacement), bukan korelasi
    ekstrem di kedua arah. Pakai t-distribution standar; df = n - 2.
    """
    if n < 3:
        return 1.0
    df = n - 2
    if r <= -1.0:
        return 0.0
    if r >= 1.0:
        return 1.0
    t = r * (df ** 0.5) / ((1 - r ** 2) ** 0.5)
    return float(stats.t.cdf(t, df))

def _merge_series_by_label(
    clusters_today, clusters_prev, volumes_by_cluster_id: dict
) -> tuple[dict[str, list[float]], dict[str, int], list]:
    """
    Gabungkan volume dari cluster_id hari ini + kemarin yang punya cluster_label
    sama, jadi satu series kontinu terurut waktu. label_to_today_id dipakai
    untuk save_alert (FK butuh id yang real, kita pakai id milik hari ini).

    Semua label di-reindex ke SATU `timeline` bersama (union semua slot_start
    yang muncul di window ini), bukan cuma di-sort sesuai slot_start-nya
    sendiri-sendiri. Sebelumnya label yang cuma ada hari ini (24 slot) dan
    label yang ada 2 hari (48 slot) dibandingkan pakai index yang sama di
    _trim_around_peak/_pearson — index yang sama itu ternyata nunjuk ke jam
    yang beda di real time, jadi korelasi dihitung dari data yang gak
    simultan tanpa ketahuan. Dengan timeline bersama + 0-fill di slot yang
    gak ada datanya, index i sekarang selalu nunjuk jam yang sama untuk
    semua label yang dibandingkan.
    """
    label_to_ids: dict[str, list[int]] = {}
    label_to_today_id: dict[str, int] = {}

    for c in clusters_prev:
        label_to_ids.setdefault(c.cluster_label, []).append(c.id)
    for c in clusters_today:
        label_to_ids.setdefault(c.cluster_label, []).append(c.id)
        label_to_today_id[c.cluster_label] = c.id

    label_slot_counts: dict[str, dict] = {}
    all_slots: set = set()
    for label, ids in label_to_ids.items():
        merged: dict = {}
        for cid in ids:
            for v in volumes_by_cluster_id.get(cid, []):
                merged[v.slot_start] = merged.get(v.slot_start, 0.0) + v.tweet_count
        if merged:
            label_slot_counts[label] = merged
            all_slots.update(merged.keys())

    timeline = sorted(all_slots)
    series_map = {
        label: [slot_counts.get(t, 0.0) for t in timeline]
        for label, slot_counts in label_slot_counts.items()
    }

    return series_map, label_to_today_id, timeline

def run(date: str) -> None:
    clusters_today = get_clusters_by_date(date)
    if not clusters_today:
        logger.warning(f"detector | date={date} | no clusters found")
        return

    prev_date = (datetime.fromisoformat(date) - timedelta(days=1)).date().isoformat()
    clusters_prev = get_clusters_by_date(prev_date)

    day_end = datetime.fromisoformat(date).replace(
        hour=0, minute=0, second=0, tzinfo=WIB
    ) + timedelta(days=1)
    query_start = day_end - timedelta(hours=WINDOW_HOURS)

    logger.info(
        f"detector | date={date} | window {query_start} -> {day_end} | "
        f"{len(clusters_today)} clusters today, {len(clusters_prev)} clusters yesterday"
    )

    volumes_by_cluster_id = get_volumes_grouped_by_cluster(start=query_start, end=day_end)
    if not volumes_by_cluster_id:
        logger.warning(f"detector | date={date} | no volume data in window")
        return

    series_map, label_to_today_id, timeline = _merge_series_by_label(
        clusters_today, clusters_prev, volumes_by_cluster_id
    )

    labels_today = [c.cluster_label for c in clusters_today if c.cluster_label in series_map]
    if len(labels_today) < 2:
        logger.info(f"detector | date={date} | not enough clusters with data to compare")
        return

    candidates: list[dict] = []
    skipped_dead_zone = 0

    for label_a, label_b in combinations(labels_today, 2):
        series_a = series_map[label_a]
        series_b = series_map[label_b]

        spike_a = _spike_ratio(series_a)
        spike_b = _spike_ratio(series_b)
        if max(spike_a, spike_b) < SPIKE_RATIO_THRESHOLD:
            continue

        peak_idx = _peak_slot_index(series_a) if spike_a >= spike_b else _peak_slot_index(series_b)
        trimmed_a, trimmed_b, lo, hi = _trim_around_peak(series_a, series_b, peak_idx)

        if not trimmed_a or not trimmed_b or max(trimmed_a) == 0 or max(trimmed_b) == 0:
            skipped_dead_zone += 1
            continue

        best_corr, best_lag, best_n = _best_lagged_correlation(trimmed_a, trimmed_b)
        if best_corr > CORRELATION_THRESHOLD:
            continue

        # lag_hours sign dinormalisasi relatif ke rising/falling (bukan ke
        # label_a/label_b, yang urutannya cuma kebetulan dari itertools.combinations).
        # Konvensi: positif = rising mendahului falling (diversion muncul duluan/
        # bersamaan), negatif = falling mendahului rising (reaksi klasik menutupi
        # isu yang sudah viral duluan).
        if spike_a >= spike_b:
            rising_label, falling_label, spike_magnitude = label_a, label_b, spike_a
            lag_hours = best_lag
        else:
            rising_label, falling_label, spike_magnitude = label_b, label_a, spike_b
            lag_hours = -best_lag

        rising_id  = label_to_today_id[rising_label]
        falling_id = label_to_today_id[falling_label]

        # Window aktual yang dipakai untuk hitung korelasi/spike pasangan ini —
        # dipakai analyzer supaya tweet yang dianalisis konsisten dengan window
        # deteksi (bisa merentang ke "kemarin" kalau peak jatuh sebelum tengah malam).
        alert_window_start = timeline[lo]
        alert_window_end   = timeline[hi - 1] + timedelta(hours=settings.VOLUME_INTERVAL_HOURS)

        candidates.append({
            "rising_id": rising_id,
            "rising_label": rising_label,
            "falling_id": falling_id,
            "falling_label": falling_label,
            "lag_hours": lag_hours,
            "correlation": best_corr,
            "spike_magnitude": spike_magnitude,
            "window_start": alert_window_start,
            "window_end": alert_window_end,
            "p_value": _one_tailed_pvalue(best_corr, best_n),
        })

    if not candidates:
        logger.info(
            f"detector | date={date} | done | 0 alerts | "
            f"{skipped_dead_zone} pairs skipped (dead zone)"
        )
        return

    # Koreksi multiple-comparison: banyak pasangan diuji per hari, jadi p-value
    # mentah di-adjust pakai Benjamini-Hochberg (FDR) supaya alert dengan
    # korelasi lemah dari window data yang tipis gak dipercaya sama kayak alert
    # dengan bukti yang benar-benar kuat secara statistik. Disimpan untuk
    # visibilitas/scoring -- TIDAK dipakai sebagai gate di sini.
    adjusted_p_values = false_discovery_control(
        [c["p_value"] for c in candidates], method="bh"
    )

    for candidate, p_adjusted in zip(candidates, adjusted_p_values):
        logger.info(
            f"detector | ALERT | rising='{candidate['rising_label']}' | "
            f"falling='{candidate['falling_label']}' | lag={candidate['lag_hours']}h | "
            f"corr={candidate['correlation']:.3f} | spike={candidate['spike_magnitude']:.2f}x | "
            f"p={candidate['p_value']:.4f} | p_adj={p_adjusted:.4f} | "
            f"window={candidate['window_start']} -> {candidate['window_end']}"
        )

        save_alert(
            detected_at=date,
            rising_cluster_id=candidate["rising_id"],
            rising_cluster_label=candidate["rising_label"],
            falling_cluster_id=candidate["falling_id"],
            falling_cluster_label=candidate["falling_label"],
            lag_hours=candidate["lag_hours"],
            correlation=candidate["correlation"],
            spike_magnitude=candidate["spike_magnitude"],
            window_start=candidate["window_start"],
            window_end=candidate["window_end"],
            p_value=candidate["p_value"],
            p_value_adjusted=float(p_adjusted),
        )

    logger.info(
        f"detector | date={date} | done | {len(candidates)} alerts | "
        f"{skipped_dead_zone} pairs skipped (dead zone)"
    )