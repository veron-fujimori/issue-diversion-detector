from datetime import date, datetime, timedelta, timezone
import plotly.graph_objects as go
import streamlit as st
from db.repositories.alert_repo import Alert
from db.repositories.cluster_repo import get_clusters_by_date
from db.repositories.volume_repo import get_volumes_grouped_by_cluster

WIB = timezone(timedelta(hours=7))

WINDOW_HOURS = 48

SCORE_COMPONENT_KEYS = [
    "correlation", "spike", "coordinated",
]

PALETTE = [
    "#4C78A8", "#E45756", "#72B7B2", "#F58518", "#54A24B",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
]


def date_picker(label: str = "Detection date", default_offset_days: int = 1) -> str:
    default_date = date.today() - timedelta(days=default_offset_days)
    selected = st.date_input(label, value=default_date, max_value=date.today())
    return selected.isoformat()


def alert_selector(alerts: list[Alert]) -> Alert | None:
    if not alerts:
        st.info("No alerts for this date.")
        return None

    def _format(a: Alert) -> str:
        score = f"{a.confidence_score:.1f}" if a.confidence_score is not None else "-"
        flag  = "FLAGGED" if (a.confidence_score or 0) >= 60 else "UNFLAGGED"
        return f"#{a.id} | {a.rising_cluster_label} -> {a.falling_cluster_label} | score={score} ({flag})"

    default_index = 0
    selected_id   = st.session_state.get("selected_alert_id")
    if selected_id is not None:
        for i, a in enumerate(alerts):
            if a.id == selected_id:
                default_index = i
                break

    chosen = st.selectbox("Select alert", options=alerts, index=default_index, format_func=_format)
    st.session_state["selected_alert_id"] = chosen.id
    return chosen


def _window_for_date(target_date: str) -> tuple[datetime, datetime]:
    day_end = datetime.fromisoformat(target_date).replace(
        hour=0, minute=0, second=0, tzinfo=WIB
    ) + timedelta(days=1)
    return day_end - timedelta(hours=WINDOW_HOURS), day_end


def render_volume_bar(clusters_data: list[dict]) -> None:
    sorted_data = sorted(clusters_data, key=lambda x: x["total"], reverse=True)

    fig = go.Figure(go.Bar(
        x=[d["label"] for d in sorted_data],
        y=[d["total"] for d in sorted_data],
        marker_color="#4C78A8",
        text=[f"{d['total']:,}" for d in sorted_data],
        textposition="outside",
    ))

    fig.update_layout(
        title="Total Tweets by Cluster",
        xaxis=dict(title="Cluster", tickangle=-30),
        yaxis=dict(title="Total Tweets", rangemode="tozero"),
        height=400,
        margin=dict(b=120),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_volume_timeseries(clusters_data: list[dict]) -> None:
    fig = go.Figure()

    for i, d in enumerate(clusters_data):
        color = PALETTE[i % len(PALETTE)]
        fig.add_trace(go.Scatter(
            x=d["slots"],
            y=d["counts"],
            name=d["label"],
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=5),
        ))

    fig.update_layout(
        title="Hourly Volume Timeseries",
        xaxis=dict(title="Time", tickformat="%H:%M\n%d-%b"),
        yaxis=dict(title="Tweet Count", rangemode="tozero"),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.01,
        ),
        height=460,
        margin=dict(r=220),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_volume_explorer(target_date: str) -> None:
    clusters = get_clusters_by_date(target_date)

    if not clusters:
        st.info(
            f"No clusters for {target_date}. "
            "Check whether the clustering pipeline has been run."
        )
        return

    window_start, window_end = _window_for_date(target_date)
    volumes = get_volumes_grouped_by_cluster(start=window_start, end=window_end)

    clusters_data = []
    for c in clusters:
        vols  = sorted(volumes.get(c.id, []), key=lambda v: v.slot_start)
        slots  = [v.slot_start for v in vols]
        counts = [v.tweet_count for v in vols]
        total  = sum(counts)
        clusters_data.append({
            "label":  c.cluster_label,
            "slots":  slots,
            "counts": counts,
            "total":  total,
        })

    all_zero = all(d["total"] == 0 for d in clusters_data)
    if all_zero:
        st.warning(
            "All slots have 0 tweets. This likely means a mismatch between "
            "`clusters.topics` and `tweet_topic.topic`. "
            "Run the following queries to confirm:\n\n"
            "```sql\n"
            "SELECT DISTINCT topic FROM tweet_topic LIMIT 20;\n"
            "SELECT DISTINCT unnest(topics) FROM clusters LIMIT 20;\n"
            "```"
        )

    st.caption(f"{len(clusters_data)} clusters")

    render_volume_bar(clusters_data)

    st.divider()

    clusters_with_slots = [d for d in clusters_data if d["slots"]]
    if clusters_with_slots:
        render_volume_timeseries(clusters_with_slots)
    else:
        st.info("No timeseries data to display.")


def render_displacement_chart(alert: Alert) -> None:
    if alert.window_start is not None and alert.window_end is not None:
        window_start, window_end = alert.window_start, alert.window_end
        window_label = "detection window"
    else:
        window_start, window_end = _window_for_date(alert.detected_at)
        window_label = "48-hour window — legacy alert, no stored window"

    volumes = get_volumes_grouped_by_cluster(start=window_start, end=window_end)

    rising_vols  = sorted(volumes.get(alert.rising_cluster_id, []),  key=lambda v: v.slot_start)
    falling_vols = sorted(volumes.get(alert.falling_cluster_id, []), key=lambda v: v.slot_start)

    if not rising_vols and not falling_vols:
        st.warning("No volume data for this window.")
        return

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=[v.slot_start for v in rising_vols],
        y=[v.tweet_count for v in rising_vols],
        name=f"{alert.rising_cluster_label} (rising)",
        line=dict(color="#E45756", width=2),
        yaxis="y1",
    ))

    fig.add_trace(go.Scatter(
        x=[v.slot_start for v in falling_vols],
        y=[v.tweet_count for v in falling_vols],
        name=f"{alert.falling_cluster_label} (falling)",
        line=dict(color="#4C78A8", width=2),
        yaxis="y2",
    ))

    fig.update_layout(
        title=f"Volume Displacement Pattern ({window_label})",
        xaxis=dict(title="Time", tickformat="%H:%M\n%d-%b"),
        yaxis=dict(
            title=dict(text=alert.rising_cluster_label, font=dict(color="#E45756")),
            tickfont=dict(color="#E45756"),
            rangemode="tozero",
        ),
        yaxis2=dict(
            title=dict(text=alert.falling_cluster_label, font=dict(color="#4C78A8")),
            tickfont=dict(color="#4C78A8"),
            overlaying="y",
            side="right",
            rangemode="tozero",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=440,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_score_breakdown(alert: Alert) -> None:
    if not alert.score_breakdown:
        st.info("This alert has not been scored yet.")
        return

    breakdown = alert.score_breakdown
    labels, scores, maxes = [], [], []

    for key in SCORE_COMPONENT_KEYS:
        comp = breakdown.get(key)
        if comp is None:
            continue
        labels.append(key.replace("_", " ").title())
        scores.append(comp["score"])
        maxes.append(comp["max"])

    fig = go.Figure()

    fig.add_trace(go.Bar(
        y=labels, x=scores,
        name="Score achieved",
        orientation="h",
        marker_color="#E45756",
        text=[f"{s:.1f}" for s in scores],
        textposition="inside",
    ))

    fig.add_trace(go.Bar(
        y=labels, x=[m - s for m, s in zip(maxes, scores)],
        name="Remaining to max",
        orientation="h",
        marker_color="#2a2a2a",
    ))

    total   = breakdown["total"]
    flagged = breakdown["flagged"]
    thresh  = breakdown["threshold"]

    fig.update_layout(
        title=(
            f"Score Breakdown — {total:.1f} / {thresh:.0f} "
            f"{'🔴 FLAGGED' if flagged else '✓ below threshold'}"
        ),
        barmode="stack",
        xaxis=dict(title="Points", range=[0, 100]),
        height=340,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
    )

    st.plotly_chart(fig, use_container_width=True)

    corr = breakdown.get("correlation")
    if corr and corr.get("p_value") is not None:
        st.caption(
            f"📊 Correlation significance: p={corr['p_value']:.4f}, "
            f"p_adj={corr['p_value_adjusted']:.4f} (Benjamini-Hochberg across that "
            f"day's candidates) | confidence factor {corr['confidence_factor']:.2f}x "
            f"applied to the correlation score"
        )
    elif corr:
        st.caption("📊 No significance data for this alert (legacy alert, predates p-value tracking).")