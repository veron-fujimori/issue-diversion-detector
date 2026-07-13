from config.settings import settings
from utils.logger import logger
from db.repositories.alert_repo import Alert, update_score
from pipeline.analysis.analyzer import AnalysisResult
from pipeline.context.context_checker import ContextCheckResult

W_CORRELATION = 20
W_SPIKE       = 15
W_COORDINATED = 65

_TOTAL_WEIGHT = W_CORRELATION + W_SPIKE + W_COORDINATED
assert _TOTAL_WEIGHT == 100, f"Total bobot harus 100, sekarang {_TOTAL_WEIGHT}."

DIVERSION_THRESHOLD = 60.0

# Titik nol skor korelasi WAJIB sama dengan gate deteksi di detector.py.
# Sebelumnya floor di-hardcode -0.6 terpisah dari settings.CORRELATION_THRESHOLD
# (-0.2) yang dipakai detector.py sebagai gate -> alert dengan korelasi antara
# -0.2 dan -0.6 lolos deteksi tapi selalu dapat 0 poin di sini. Dengan floor
# = settings.CORRELATION_THRESHOLD, dua ambang itu sekarang satu sumber kebenaran.
_CORR_SCORE_FLOOR   = settings.CORRELATION_THRESHOLD   # skor mulai dari titik gate
_CORR_SCORE_CEILING = -1.0                              # korelasi negatif sempurna
_CORR_SCORE_SPAN    = _CORR_SCORE_FLOOR - _CORR_SCORE_CEILING
assert _CORR_SCORE_SPAN > 0, (
    f"CORRELATION_THRESHOLD ({_CORR_SCORE_FLOOR}) harus > -1.0 supaya span skor valid."
)


def _score_correlation(correlation: float) -> float:
    normalized = (_CORR_SCORE_FLOOR - correlation) / _CORR_SCORE_SPAN
    normalized = min(1.0, max(0.0, normalized))
    return round(normalized * W_CORRELATION, 2)


def _score_spike(spike_magnitude: float) -> float:
    normalized = min(1.0, max(0.0, (spike_magnitude - 2.0) / 8.0))
    return round(normalized * W_SPIKE, 2)


def _score_ratio(ratio: float, weight: int) -> float:
    return round(min(1.0, max(0.0, ratio)) * weight, 2)


def _suppression_factor(context: ContextCheckResult | None) -> float:
    if context is None or not context.grounded or not context.independent_event:
        return 1.0
    if context.confidence < settings.CONTEXT_CHECK_MIN_CONFIDENCE:
        return 1.0
    reduction = settings.CONTEXT_CHECK_MAX_SUPPRESSION * context.confidence
    return round(1.0 - reduction, 3)


def compute(
    alert: Alert,
    analysis: AnalysisResult,
    context: ContextCheckResult | None = None,
) -> tuple[float, dict]:
    s_correlation = _score_correlation(alert.correlation)
    s_spike       = _score_spike(alert.spike_magnitude)
    s_coordinated = _score_ratio(analysis.coordinated_ratio, W_COORDINATED)

    raw_total = round(s_correlation + s_spike + s_coordinated, 2)
    factor    = _suppression_factor(context)
    total     = round(raw_total * factor, 2)

    breakdown = {
        "correlation": {
            "score": s_correlation, "max": W_CORRELATION,
            "raw": round(alert.correlation, 4),
            "floor": _CORR_SCORE_FLOOR, "ceiling": _CORR_SCORE_CEILING,
        },
        "spike": {
            "score": s_spike, "max": W_SPIKE,
            "raw": round(alert.spike_magnitude, 4),
        },
        "coordinated": {
            "score": s_coordinated, "max": W_COORDINATED,
            "raw": round(analysis.coordinated_ratio, 4),
            "account_count": analysis.account_count,
        },
        "context_check": {
            "independent_event":  context.independent_event if context else None,
            "confidence":         context.confidence if context else None,
            "reasoning":          context.reasoning if context else None,
            "grounded":           context.grounded if context else None,
            "suppression_factor": factor,
        },
        "raw_total_before_suppression": raw_total,
        "total":            total,
        "threshold":        DIVERSION_THRESHOLD,
        "flagged":          total >= DIVERSION_THRESHOLD,
        "sample_size":      analysis.sample_size,
        "flagged_accounts": analysis.flagged_accounts,
    }

    return total, breakdown


def run(
    alert: Alert,
    analysis: AnalysisResult,
    context: ContextCheckResult | None = None,
) -> float:
    if analysis.sample_size == 0:
        logger.warning(
            f"scorer | alert_id={alert.id} | sample_size=0 | "
            f"rising='{alert.rising_cluster_label}' | "
            f"skor hanya dari detector (maks {W_CORRELATION + W_SPIKE} poin)"
        )

    total, breakdown = compute(alert, analysis, context)

    update_score(
        alert_id=alert.id,
        confidence_score=total,
        score_breakdown=breakdown,
    )

    flag = "FLAGGED" if breakdown["flagged"] else "ok"
    logger.info(
        f"scorer | alert_id={alert.id} | rising='{alert.rising_cluster_label}' | "
        f"raw={breakdown['raw_total_before_suppression']:.1f} -> final={total:.1f}/{DIVERSION_THRESHOLD} | "
        f"suppression={breakdown['context_check']['suppression_factor']} | {flag}"
    )

    return total