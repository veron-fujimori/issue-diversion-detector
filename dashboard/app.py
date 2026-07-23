import streamlit as st
from dashboard.helpers import (
    date_picker,
    alert_selector,
    render_volume_explorer,
    render_displacement_chart,
    render_score_breakdown,
)
from db.connection import init_pool
from db.repositories.alert_repo import get_alerts_by_date

st.set_page_config(
    page_title="Issue Diversion Detector",
    layout="wide",
)

@st.cache_resource
def _get_pool():
    init_pool()
    return True

_get_pool()

st.title("Issue Diversion Dashboard")

tab_volume, tab_overview, tab_detail = st.tabs(["Volume Explorer", "Overview", "Detail"])

with tab_volume:
    volume_date = date_picker("Date", default_offset_days=1)
    render_volume_explorer(volume_date)

with tab_overview:
    selected_date = date_picker()
    alerts        = get_alerts_by_date(selected_date)

    if not alerts:
        st.info(f"No alerts for {selected_date}.")
    else:
        flagged_count = sum(1 for a in alerts if (a.confidence_score or 0) >= 60)

        col1, col2 = st.columns(2)
        col1.metric("Total Alerts", len(alerts))
        col2.metric("Flagged (>= 60)", flagged_count)

        st.divider()

        sorted_alerts = sorted(
            alerts,
            key=lambda a: a.confidence_score or 0,
            reverse=True,
        )

        for alert in sorted_alerts:
            score = alert.confidence_score
            if score is None:
                score_str  = "not yet scored"
                flag_label = "pending"
            else:
                score_str  = f"{score:.1f}"
                flag_label = "🔴 FLAGGED" if score >= 60 else "UNFLAGGED"

            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 3, 2])

                with c1:
                    st.markdown(f"**Rising:** {alert.rising_cluster_label}")
                    st.caption(f"Spike {alert.spike_magnitude:.2f}x")

                with c2:
                    st.markdown(f"**Falling:** {alert.falling_cluster_label}")
                    st.caption(f"Correlation {alert.correlation:.3f} | lag {alert.lag_hours}h")

                with c3:
                    st.markdown(f"**Score:** {score_str}")
                    st.caption(flag_label)

                if st.button("View details", key=f"btn_{alert.id}"):
                    st.session_state["selected_alert_id"]        = alert.id
                    st.session_state["selected_date_for_detail"] = selected_date
                    st.info("Switch to the 'Detail' tab to see the full breakdown.")

with tab_detail:
    detail_date       = st.session_state.get("selected_date_for_detail", selected_date)
    alerts_for_detail = get_alerts_by_date(detail_date)

    st.caption(f"Showing alerts for date: {detail_date}")

    chosen_alert = alert_selector(alerts_for_detail)

    if chosen_alert is not None:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Confidence Score",  f"{chosen_alert.confidence_score or 0:.1f}")
        m2.metric("Correlation",       f"{chosen_alert.correlation:.3f}")
        m3.metric("Lag (hours)",       chosen_alert.lag_hours)
        m4.metric("Spike Magnitude",   f"{chosen_alert.spike_magnitude:.2f}x")

        st.divider()
        render_displacement_chart(chosen_alert)

        st.divider()
        render_score_breakdown(chosen_alert)