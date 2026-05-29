from utils.logger import logger
from utils.llm.client import llm
from db.repositories.trending_repo import get_unique_topics_by_date
from db.repositories.cluster_repo import save_clusters, get_recent_clusters
from pipeline.clustering.prompt import SYSTEM_PROMPT, build_user_prompt

def _extract_clusters(raw: dict | list) -> list[dict]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("clusters", [])
    else:
        raise ValueError(f"clusterer | unexpected LLM output type: {type(raw)} | {raw}")

    return [
        {"label": item["label"].strip(), "topics": item["topics"]}
        for item in items
        if item.get("label") and item.get("topics")
    ]

def run(date: str) -> None:
    topics = get_unique_topics_by_date(date)
    if not topics:
        logger.warning(f"clusterer | date={date} | no topics found")
        return

    logger.info(f"clusterer | date={date} | clustering {len(topics)} topics")

    recent = get_recent_clusters(date, days=2)

    seen_labels: set[str] = set()
    existing_clusters = []
    for c in reversed(recent):
        if c.cluster_label not in seen_labels:
            existing_clusters.append({"label": c.cluster_label, "topics": c.topics})
            seen_labels.add(c.cluster_label)

    logger.debug(f"clusterer | date={date} | {len(existing_clusters)} existing labels as context")

    response = llm.chat(
        system=SYSTEM_PROMPT,
        prompt=build_user_prompt(topics, existing_clusters or None),
        temperature=0.1,
        json_mode=True,
    )

    clusters = _extract_clusters(response.content)
    save_clusters(date, clusters)
    logger.info(f"clusterer | date={date} | done, {len(clusters)} clusters saved")