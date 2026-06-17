from datetime import datetime, timedelta, timezone
from itertools import combinations
from utils.logger import logger
from db.repositories.cluster_repo import get_clusters_by_date
from db.repositories.volume_repo import get_volumes_grouped_by_cluster
from db.repositories.alert_repo import save_alert

WIB = timezone(timedelta(hours=7))
WINDOW_HOURS = 48
LAG_SLOTS = [0, 1, 2, 3]
CORRELATION_THRESHOLD = -0.6
SPIKE_RATIO_THRESHOLD = 2.0
MIN_DATA_POINTS = 6

def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5

    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)

def _apply_lag_pair(
    a: list[float], b: list[float], lag: int
) -> tuple[list[float], list[float]]:
    if lag == 0:
        return a, b
    n = len(a)
    if lag >= n:
        return [], []
    return a[: n - lag], b[lag:]

def _spike_ratio(series: list[float]) -> float:
    if not series or max(series) == 0:
        return 0.0
    mean_val = sum(series) / len(series)
    if mean_val == 0:
        return 0.0
    return max(series) / mean_val

def _best_lagged_correlation(
    series_a: list[float], series_b: list[float]
) -> tuple[float, int]:
    best_corr = 1.0
    best_lag = 0

    for lag_slot in LAG_SLOTS:
        a1, b1 = _apply_lag_pair(series_a, series_b, lag_slot)
        if len(a1) >= MIN_DATA_POINTS:
            corr = _pearson(a1, b1)
            if corr < best_corr:
                best_corr = corr
                best_lag = lag_slot * 4

        if lag_slot == 0:
            continue

        b2, a2 = _apply_lag_pair(series_b, series_a, lag_slot)
        if len(a2) >= MIN_DATA_POINTS:
            corr = _pearson(a2, b2)
            if corr < best_corr:
                best_corr = corr
                best_lag = -(lag_slot * 4)
    return best_corr, best_lag


def run(date: str) -> None:
    clusters_today = get_clusters_by_date(date)
    if not clusters_today:
        logger.warning(f"detector | date={date} | no clusters found")
        return

    day_end = datetime.fromisoformat(date).replace(
        hour=0, minute=0, second=0, tzinfo=WIB
    ) + timedelta(days=1)

    window_start = day_end - timedelta(hours=WINDOW_HOURS)

    logger.info(
        f"detector | date={date} | "
        f"window {window_start.strftime('%Y-%m-%d %H:%M')} -> {day_end.strftime('%Y-%m-%d %H:%M')} | "
        f"{len(clusters_today)} clusters"
    )

    volumes_by_cluster = get_volumes_grouped_by_cluster(
        start=window_start,
        end=day_end,
    )

    if not volumes_by_cluster:
        logger.warning(f"detector | date={date} | no volume data in window")
        return

    series_map: dict[int, list[float]] = {
        cluster_id: [
            float(v.tweet_count)
            for v in sorted(vols, key=lambda v: v.slot_start)
        ]
        for cluster_id, vols in volumes_by_cluster.items()
    }

    label_map: dict[int, str] = {c.id: c.cluster_label for c in clusters_today}

    cluster_ids_today = [c.id for c in clusters_today if c.id in series_map]

    if len(cluster_ids_today) < 2:
        logger.info(f"detector | date={date} | not enough clusters to compare")
        return

    alerts_found = 0

    for id_a, id_b in combinations(cluster_ids_today, 2):
        series_a = series_map[id_a]
        series_b = series_map[id_b]

        spike_a = _spike_ratio(series_a)
        spike_b = _spike_ratio(series_b)

        if max(spike_a, spike_b) < SPIKE_RATIO_THRESHOLD:
            continue

        best_corr, best_lag = _best_lagged_correlation(series_a, series_b)

        if best_corr > CORRELATION_THRESHOLD:
            continue

        if spike_a >= spike_b:
            rising_id, falling_id = id_a, id_b
            spike_magnitude = spike_a
        else:
            rising_id, falling_id = id_b, id_a
            spike_magnitude = spike_b

        rising_label  = label_map.get(rising_id, f"cluster_{rising_id}")
        falling_label = label_map.get(falling_id, f"cluster_{falling_id}")

        logger.info(
            f"detector | ALERT | rising='{rising_label}' | falling='{falling_label}' | "
            f"lag={best_lag}h | corr={best_corr:.3f} | spike={spike_magnitude:.2f}x"
        )

        save_alert(
            detected_at=date,
            rising_cluster_id=rising_id,
            rising_cluster_label=rising_label,
            falling_cluster_id=falling_id,
            falling_cluster_label=falling_label,
            lag_hours=best_lag,
            correlation=best_corr,
            spike_magnitude=spike_magnitude,
        )
        alerts_found += 1

    logger.info(f"detector | date={date} | done | {alerts_found} alerts saved")