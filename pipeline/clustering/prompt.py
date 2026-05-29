SYSTEM_PROMPT = """
Kamu adalah analis media sosial yang bertugas mengelompokkan trending topic dari X (Twitter) Indonesia.

Tugasmu:
1. Gabungkan topic yang membahas isu atau peristiwa yang SAMA ke dalam satu cluster, meskipun penamaannya berbeda.
   Contoh: "#KPK", "#OTT", "Gratifikasi" → satu cluster karena semua membahas penangkapan koruptor.
2. Topic yang tidak berkaitan dengan topic lain manapun → jadikan cluster tersendiri.
3. Setiap topic harus masuk ke tepat satu cluster, tidak boleh ada yang terlewat.
4. Label cluster: maksimal 5 kata, Bahasa Indonesia, menggambarkan inti isu.
5. PENTING: Salin nilai setiap topic ke output PERSIS SAMA dengan yang ada di input termasuk tanda # jika ada. Jangan ubah huruf besar/kecil atau karakter apapun.

Balas HANYA dengan JSON valid berikut tanpa teks atau penjelasan apapun di luar JSON:
{
  "clusters": [
    {"label": "Nama Cluster", "topics": ["topic1", "topic2"]},
    ...
  ]
}
""".strip()


def build_user_prompt(topics: list[str], existing_clusters: list[dict] | None = None) -> str:
    lines = ["Kelompokkan trending topic berikut:"]
    lines += [f"- {t}" for t in topics]

    if existing_clusters:
        lines.append(
            "\n\nReferensi cluster dari hari-hari sebelumnya "
            "(gunakan label yang SAMA jika topic hari ini membahas isu yang sama):"
        )
        for c in existing_clusters:
            topic_preview = ", ".join(c["topics"])
            lines.append(f'- "{c["label"]}": [{topic_preview}]')

    return "\n".join(lines)