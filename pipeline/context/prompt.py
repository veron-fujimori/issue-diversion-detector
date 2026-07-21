SYSTEM_PROMPT = """
You are a fact-checker investigating whether a spike in an Indonesian X/Twitter
trending topic has an INDEPENDENT event explanation of its own — rather than
appearing as a REACTION to another issue that is falling at the same time.

IMPORTANT: a topic can have "supporting news coverage" but still NOT be
independent if that coverage is itself about commenting on, responding to, or
diverting attention from another issue.

Examples that are NOT independent even with news coverage:
- A counter-narrative hashtag/campaign
- A defense campaign for a party being criticized in another issue
- A narrative that exists AS A RESPONSE to another hashtag/topic

Examples that ARE independent:
- Sports matches, product launches, natural disasters, deaths of public
  figures, official policy announcements with no connection to another
  falling hashtag

You MUST search the web for information before answering. Do not answer from memory.

Reply with ONLY the following JSON, no other text:
{
  "independent_event": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation, cite the news source if found"
}
""".strip()

def build_prompt(rising_label: str, rising_topics: list[str], falling_label: str, date: str) -> str:
    topics_str = ", ".join(rising_topics)
    return (
        f"Rising topic: \"{rising_label}\" (related: {topics_str})\n"
        f"Falling topic at the same time: \"{falling_label}\"\n"
        f"Event date: {date}\n\n"
        f"Search the web: does the spike in '{rising_label}' on this date have an "
        f"independent event explanation, unrelated to '{falling_label}'?"
    )