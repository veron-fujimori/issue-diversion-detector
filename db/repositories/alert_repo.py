from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from db.connection import get_cursor
from utils.logger import logger
import json

@dataclass
class Alert:
    id: int
    detected_at: str
    rising_cluster_id: int
    rising_cluster_label: str
    falling_cluster_id: int
    falling_cluster_label: str
    lag_hours: int
    correlation: float
    spike_magnitude: float
    confidence_score: Optional[float]
    score_breakdown: Optional[dict]
    # Window aktual yang dipakai detector untuk hitung korelasi/spike pasangan
    # ini. None untuk alert lama (sebelum migrasi 005) — analyzer fallback ke
    # rentang detected_at satu hari penuh kalau ini None.
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None

def save_alert(
    detected_at: str,
    rising_cluster_id: int,
    rising_cluster_label: str,
    falling_cluster_id: int,
    falling_cluster_label: str,
    lag_hours: int,
    correlation: float,
    spike_magnitude: float,
    window_start: datetime,
    window_end: datetime,
) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO alerts (
                detected_at,
                rising_cluster_id, rising_cluster_label,
                falling_cluster_id, falling_cluster_label,
                lag_hours, correlation, spike_magnitude,
                window_start, window_end
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (detected_at, rising_cluster_id, falling_cluster_id)
            DO UPDATE SET
                lag_hours       = EXCLUDED.lag_hours,
                correlation     = EXCLUDED.correlation,
                spike_magnitude = EXCLUDED.spike_magnitude,
                window_start    = EXCLUDED.window_start,
                window_end      = EXCLUDED.window_end,
                created_at      = NOW()
            RETURNING id
            """,
            (
                detected_at,
                rising_cluster_id, rising_cluster_label,
                falling_cluster_id, falling_cluster_label,
                lag_hours, correlation, spike_magnitude,
                window_start, window_end,
            ),
        )
        row = cur.fetchone()

    alert_id = row["id"]
    logger.debug(
        f"alert_repo | saved alert_id={alert_id} | "
        f"rising='{rising_cluster_label}' -> falling='{falling_cluster_label}' | "
        f"lag={lag_hours}h | corr={correlation:.3f}"
    )
    return alert_id

def update_score(alert_id: int, confidence_score: float, score_breakdown: dict) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE alerts
            SET confidence_score = %s,
                score_breakdown  = %s::jsonb
            WHERE id = %s
            """,
            (confidence_score, json.dumps(score_breakdown), alert_id),
        )

def get_alerts_by_date(detected_at: str) -> list[Alert]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id, detected_at,
                rising_cluster_id, rising_cluster_label,
                falling_cluster_id, falling_cluster_label,
                lag_hours, correlation, spike_magnitude,
                confidence_score, score_breakdown,
                window_start, window_end
            FROM alerts
            WHERE detected_at = %s
            ORDER BY correlation ASC
            """,
            (detected_at,),
        )
        rows = cur.fetchall()

    return [
        Alert(
            id=row["id"],
            detected_at=str(row["detected_at"]),
            rising_cluster_id=row["rising_cluster_id"],
            rising_cluster_label=row["rising_cluster_label"],
            falling_cluster_id=row["falling_cluster_id"],
            falling_cluster_label=row["falling_cluster_label"],
            lag_hours=row["lag_hours"],
            correlation=row["correlation"],
            spike_magnitude=row["spike_magnitude"],
            confidence_score=row["confidence_score"],
            score_breakdown=dict(row["score_breakdown"]) if row["score_breakdown"] else None,
            window_start=row["window_start"],
            window_end=row["window_end"],
        )
        for row in rows
    ]

def get_alerts_pending_scoring(detected_at: str) -> list[Alert]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id, detected_at,
                rising_cluster_id, rising_cluster_label,
                falling_cluster_id, falling_cluster_label,
                lag_hours, correlation, spike_magnitude,
                confidence_score, score_breakdown,
                window_start, window_end
            FROM alerts
            WHERE detected_at = %s
              AND confidence_score IS NULL
            ORDER BY correlation ASC
            """,
            (detected_at,),
        )
        rows = cur.fetchall()

    return [
        Alert(
            id=row["id"],
            detected_at=str(row["detected_at"]),
            rising_cluster_id=row["rising_cluster_id"],
            rising_cluster_label=row["rising_cluster_label"],
            falling_cluster_id=row["falling_cluster_id"],
            falling_cluster_label=row["falling_cluster_label"],
            lag_hours=row["lag_hours"],
            correlation=row["correlation"],
            spike_magnitude=row["spike_magnitude"],
            confidence_score=row["confidence_score"],
            score_breakdown=dict(row["score_breakdown"]) if row["score_breakdown"] else None,
            window_start=row["window_start"],
            window_end=row["window_end"],
        )
        for row in rows
    ]