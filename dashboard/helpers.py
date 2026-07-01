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


# ── FILTERS ──────────────────────────────────────────────────────────

def date_picker(label: str = "Tanggal deteksi", default_offset_days: int = 1) -> str:
    default_date = date.today() - timedelta(days=default_offset_days)
    selected = st.date_input(label, value=default_date, max_value=date.today())
    return selected.isoformat()


def alert_selector(alerts: list[Alert]) -> Alert | None:
    if not alerts:
        st.info("Tidak ada alert untuk tanggal ini.")
        return None

    def _format(a: Alert) -> str:
        score = f"{a.confidence_score:.1f}" if a.confidence_score is not None else "-"
        flag  = "FLAGGED" if (a.confidence_score or 0) >= 60 else "ok"
        return f"#{a.id} | {a.rising_cluster_label} -> {a.falling_cluster_label} | score={score} ({flag})"

    default_index = 0
    selected_id   = st.session_state.get("selected_alert_id")
    if selected_id is not None:
        for i, a in enumerate(alerts):
            if a.id == selected_id:
                default_index = i
                break

    chosen = st.selectbox("Pilih alert", options=alerts, index=default_index, format_func=_format)
    st.session_state["selected_alert_id"] = chosen.id
    return chosen


# ── WINDOW ───────────────────────────────────────────────────────────

def _window_for_date(target_date: str) -> tuple[datetime, datetime]:
    day_end = datetime.fromisoformat(target_date).replace(
        hour=0, minute=0, second=0, tzinfo=WIB
    ) + timedelta(days=1)
    return day_end - timedelta(hours=WINDOW_HOURS), day_end


# ── VOLUME EXPLORER ───────────────────────────────────────────────────

def render_volume_bar(clusters_data: list[dict]) -> None:
    """
    Bar chart: total volume tweet per cluster untuk periode yang dipilih.
    Diurutkan descending supaya cluster paling aktif langsung terlihat.
    Tujuan: orientasi cepat — siapa yang ramai, siapa yang sepi.
    """
    sorted_data = sorted(clusters_data, key=lambda x: x["total"], reverse=True)

    fig = go.Figure(go.Bar(
        x=[d["label"] for d in sorted_data],
        y=[d["total"] for d in sorted_data],
        marker_color="#4C78A8",
        text=[f"{d['total']:,}" for d in sorted_data],
        textposition="outside",
    ))

    fig.update_layout(
        title="Total Volume Tweet per Cluster",
        xaxis=dict(title="Cluster", tickangle=-30),
        yaxis=dict(title="Total Tweet", rangemode="tozero"),
        height=400,
        margin=dict(b=120),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_volume_timeseries(clusters_data: list[dict], target_date: str) -> None:
    """
    Multi-line timeseries: volume per slot 4 jam, nilai absolut.
    Semua cluster dalam satu chart — user bisa klik legend untuk
    hide/show cluster tertentu sehingga perbandingan skala bisa
    diatur sendiri tanpa perlu normalisasi.
    Tujuan: lihat KAPAN pergerakan terjadi dan siapa yang bergerak.
    """
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
        title=f"Timeseries Volume per Slot 4 Jam — window 48 jam s/d {target_date}",
        xaxis=dict(title="Waktu", tickformat="%H:%M\n%d-%b"),
        yaxis=dict(title="Jumlah Tweet", rangemode="tozero"),
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
    st.caption("Tip: klik nama cluster di legenda untuk sembunyikan/tampilkan.")


def render_volume_explorer(target_date: str) -> None:
    """
    Entry point tab Volume Explorer.
    Ambil data sekali, render dua chart: bar total + timeseries.
    """
    clusters = get_clusters_by_date(target_date)

    if not clusters:
        st.info(
            f"Tidak ada cluster untuk tanggal {target_date}. "
            "Cek apakah clustering pipeline sudah dijalankan."
        )
        return

    window_start, window_end = _window_for_date(target_date)
    volumes = get_volumes_grouped_by_cluster(start=window_start, end=window_end)

    # Susun data per cluster — include cluster tanpa volume (total=0)
    # supaya terlihat cluster mana yang memang tidak punya data
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
            "Semua slot berisi 0 tweet. Kemungkinan ada mismatch antara "
            "nilai di kolom `topics` (tabel `clusters`) dengan "
            "`collected_for_hashtag` (tabel `tweet`). "
            "Jalankan query berikut di DB untuk konfirmasi:\n\n"
            "```sql\n"
            "SELECT DISTINCT collected_for_hashtag FROM tweet LIMIT 20;\n"
            "SELECT DISTINCT unnest(topics) FROM clusters LIMIT 20;\n"
            "```"
        )

    st.caption(f"{len(clusters_data)} cluster | window 48 jam s/d {target_date}")

    render_volume_bar(clusters_data)

    st.divider()

    # Hanya render timeseries untuk cluster yang punya slot data
    clusters_with_slots = [d for d in clusters_data if d["slots"]]
    if clusters_with_slots:
        render_volume_timeseries(clusters_with_slots, target_date)
    else:
        st.info("Tidak ada data timeseries untuk ditampilkan.")


# ── TAB DETAIL ────────────────────────────────────────────────────────

def render_displacement_chart(alert: Alert) -> None:
    """
    Dual-axis timeseries: rising vs falling cluster dalam window 48 jam.
    Dua sumbu Y supaya perbedaan skala tidak mendistorsi pola visual.
    Ini chart utama untuk membuktikan pola displacement ke audiens.
    """
    window_start, window_end = _window_for_date(alert.detected_at)
    volumes = get_volumes_grouped_by_cluster(start=window_start, end=window_end)

    rising_vols  = sorted(volumes.get(alert.rising_cluster_id, []),  key=lambda v: v.slot_start)
    falling_vols = sorted(volumes.get(alert.falling_cluster_id, []), key=lambda v: v.slot_start)

    if not rising_vols and not falling_vols:
        st.warning("Tidak ada data volume untuk window ini.")
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
        title="Pola Displacement Volume (window 48 jam)",
        xaxis=dict(title="Waktu", tickformat="%H:%M\n%d-%b"),
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
    """
    Horizontal stacked bar: skor aktual vs sisa-menuju-maksimum per komponen.
    Membuktikan ke audiens bahwa skor bukan black box —
    setiap komponen terlihat kontribusinya secara eksplisit.
    """
    if not alert.score_breakdown:
        st.info("Alert ini belum di-scoring.")
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
        name="Skor diperoleh",
        orientation="h",
        marker_color="#E45756",
        text=[f"{s:.1f}" for s in scores],
        textposition="inside",
    ))

    fig.add_trace(go.Bar(
        y=labels, x=[m - s for m, s in zip(maxes, scores)],
        name="Sisa menuju maks",
        orientation="h",
        marker_color="#2a2a2a",
    ))

    total   = breakdown["total"]
    flagged = breakdown["flagged"]
    thresh  = breakdown["threshold"]

    fig.update_layout(
        title=(
            f"Score Breakdown — {total:.1f} / {thresh:.0f} "
            f"{'🔴 FLAGGED' if flagged else '✓ di bawah threshold'}"
        ),
        barmode="stack",
        xaxis=dict(title="Poin", range=[0, 100]),
        height=340,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
    )

    st.plotly_chart(fig, use_container_width=True)