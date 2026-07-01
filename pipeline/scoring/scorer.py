from utils.logger import logger
from db.repositories.alert_repo import Alert, update_score
from pipeline.analysis.analyzer import AnalysisResult

W_CORRELATION = 20
W_SPIKE       = 15
W_COORDINATED = 65

_TOTAL_WEIGHT = W_CORRELATION + W_SPIKE + W_COORDINATED
assert _TOTAL_WEIGHT == 100, f"Total bobot harus 100, sekarang {_TOTAL_WEIGHT}."

DIVERSION_THRESHOLD = 60.0


def _score_correlation(correlation: float) -> float:
    normalized = max(0.0, (-correlation - 0.6) / 0.4)
    return round(normalized * W_CORRELATION, 2)


def _score_spike(spike_magnitude: float) -> float:
    normalized = min(1.0, max(0.0, (spike_magnitude - 2.0) / 8.0))
    return round(normalized * W_SPIKE, 2)


def _score_ratio(ratio: float, weight: int) -> float:
    return round(min(1.0, max(0.0, ratio)) * weight, 2)


def compute(alert: Alert, analysis: AnalysisResult) -> tuple[float, dict]:
    s_correlation = _score_correlation(alert.correlation)
    s_spike       = _score_spike(alert.spike_magnitude)
    s_coordinated = _score_ratio(analysis.coordinated_ratio, W_COORDINATED)

    total = round(s_correlation + s_spike + s_coordinated, 2)

    breakdown = {
        "correlation": {
            "score": s_correlation,
            "max":   W_CORRELATION,
            "raw":   round(alert.correlation, 4),
        },
        "spike": {
            "score": s_spike,
            "max":   W_SPIKE,
            "raw":   round(alert.spike_magnitude, 4),
        },
        "coordinated": {
            "score":              s_coordinated,
            "max":                W_COORDINATED,
            "raw":                round(analysis.coordinated_ratio, 4),
            "account_count":      analysis.account_count,
            "mean_account_score": round(analysis.mean_account_score, 4),
        },
        "total":            total,
        "threshold":        DIVERSION_THRESHOLD,
        "flagged":          total >= DIVERSION_THRESHOLD,
        "sample_size":      analysis.sample_size,
        "flagged_accounts": analysis.flagged_accounts,
    }

    return total, breakdown


def run(alert: Alert, analysis: AnalysisResult) -> float:
    if analysis.sample_size == 0:
        logger.warning(
            f"scorer | alert_id={alert.id} | sample_size=0 | "
            f"rising='{alert.rising_cluster_label}' | "
            f"skor hanya dari detector (maks {W_CORRELATION + W_SPIKE} poin)"
        )

    total, breakdown = compute(alert, analysis)

    update_score(
        alert_id=alert.id,
        confidence_score=total,
        score_breakdown=breakdown,
    )

    flag = "FLAGGED" if breakdown["flagged"] else "ok"
    logger.info(
        f"scorer | alert_id={alert.id} | "
        f"rising='{alert.rising_cluster_label}' | "
        f"score={total:.1f}/{DIVERSION_THRESHOLD} | "
        f"accounts={analysis.account_count} | "
        f"mean_score={analysis.mean_account_score:.3f} | "
        f"{flag}"
    )

    return total