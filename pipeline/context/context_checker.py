from dataclasses import dataclass
from db.repositories.alert_repo import Alert
from pipeline.context.prompt import SYSTEM_PROMPT, build_prompt
from utils.llm.client import llm
from utils.logger import logger

@dataclass
class ContextCheckResult:
    independent_event: bool
    confidence: float
    reasoning: str
    grounded: bool = True

def run(alert: Alert, rising_topics: list[str]) -> ContextCheckResult:
    prompt = build_prompt(
        rising_label=alert.rising_cluster_label,
        rising_topics=rising_topics,
        falling_label=alert.falling_cluster_label,
        date=alert.detected_at,
    )

    try:
        response = llm.chat_with_search(prompt=prompt, system=SYSTEM_PROMPT)
        data = response.content

        if not response.grounded:
            logger.warning(
                f"context_checker | alert_id={alert.id} | "
                f"NOT grounded (no web_search_call) — fail-safe, not suppressing"
            )
            return ContextCheckResult(
                independent_event=False, confidence=0.0,
                reasoning="LLM did not perform an actual web search", grounded=False,
            )

        result = ContextCheckResult(
            independent_event=bool(data.get("independent_event", False)),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=str(data.get("reasoning", "")),
            grounded=True,
        )

    except Exception as e:
        logger.error(f"context_checker | alert_id={alert.id} | FAILED, fail-safe | {e}")
        result = ContextCheckResult(
            independent_event=False, confidence=0.0,
            reasoning=f"check failed: {e}", grounded=False,
        )

    logger.info(
        f"context_checker | alert_id={alert.id} | '{alert.rising_cluster_label}' | "
        f"independent={result.independent_event} | confidence={result.confidence:.2f} | "
        f"grounded={result.grounded}"
    )
    return result