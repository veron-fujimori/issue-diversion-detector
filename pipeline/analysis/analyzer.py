import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db.repositories.alert_repo import Alert
from db.repositories.tweet_repo import get_all_tweets_by_topics_and_date
from utils.logger import logger

_STOPWORDS_SET           = set(StopWordRemoverFactory().get_stop_words())
_HASHTAG_MENTION_PATTERN = re.compile(r"[#@]\w+")
_STEMMER                 = StemmerFactory().create_stemmer()
_STEM_CACHE: dict[str, str] = {}

SIMILARITY_THRESHOLD      = 0.7
BURST_MIN_TWEETS          = 3
BURST_WINDOW_MINUTES      = 10
SIMILAR_TWEET_MIN_MATCHES = 3
MIN_VIEWS_FOR_ENGAGEMENT  = 1000
LOW_ENGAGEMENT_RATE       = 0.01
NEW_ACCOUNT_DAYS          = 30
LOW_FOLLOWERS_THRESHOLD   = 50
TOTAL_CONDITIONS          = 5
MIN_SCORE_FOR_AUDIT_TRAIL = 0.4

@dataclass
class AnalysisResult:
    alert_id: int
    coordinated_ratio: float
    sample_size: int
    account_count: int           = 0
    flagged_accounts: list[dict] = field(default_factory=list)

def _stem(word: str) -> str:
    if word not in _STEM_CACHE:
        _STEM_CACHE[word] = _STEMMER.stem(word)
    return _STEM_CACHE[word]

def _clean_text(text: str) -> str:
    text   = _HASHTAG_MENTION_PATTERN.sub("", text.lower())
    tokens = [
        _stem(t)
        for t in text.split()
        if t.isalpha() and t not in _STOPWORDS_SET
    ]
    return " ".join(tokens)

def _find_similar_pairs(texts: list[str], screen_names: list[str]) -> list[int]:
    n           = len(texts)
    match_count = [0] * n
    cleaned     = [_clean_text(t) for t in texts]

    try:
        tfidf_matrix = TfidfVectorizer().fit_transform(cleaned)
    except ValueError:
        return match_count

    if tfidf_matrix.shape[1] == 0:
        return match_count

    sim_matrix = cosine_similarity(tfidf_matrix)

    for i in range(n):
        for j in range(i + 1, n):
            if screen_names[i] == screen_names[j]:
                continue
            if sim_matrix[i, j] >= SIMILARITY_THRESHOLD:
                match_count[i] += 1
                match_count[j] += 1

    return match_count

def _compute_burst_membership(timestamps: list) -> list[bool]:
    n        = len(timestamps)
    in_burst = [False] * n
    if n < BURST_MIN_TWEETS:
        return in_burst

    window = timedelta(minutes=BURST_WINDOW_MINUTES)
    left   = 0
    for right in range(n):
        while timestamps[right] - timestamps[left] > window:
            left += 1
        if right - left + 1 >= BURST_MIN_TWEETS:
            for k in range(left, right + 1):
                in_burst[k] = True
    return in_burst

def _is_low_engagement(tweet: dict) -> bool | None:
    views = tweet["view_count"] or 0
    if views < MIN_VIEWS_FOR_ENGAGEMENT:
        return None
    likes    = tweet["likes"] or 0
    retweets = tweet["retweets"] or 0
    return (likes + retweets) / views < LOW_ENGAGEMENT_RATE

def _is_new_account(created_at, reference_date: str) -> bool:
    if created_at is None:
        return False
    ref    = datetime.fromisoformat(reference_date).date()
    cutoff = ref - timedelta(days=NEW_ACCOUNT_DAYS)
    return created_at.date() >= cutoff

def _is_low_followers(followers_count) -> bool:
    if followers_count is None:
        return False
    return followers_count < LOW_FOLLOWERS_THRESHOLD

def run(alert: Alert, rising_topics: list[str]) -> AnalysisResult:
    tweets = get_all_tweets_by_topics_and_date(rising_topics, alert.detected_at)

    if not tweets:
        logger.warning(
            f"analyzer | alert_id={alert.id} | no tweets found | "
            f"rising='{alert.rising_cluster_label}'"
        )
        return AnalysisResult(
            alert_id=alert.id,
            coordinated_ratio=0.0,
            sample_size=0,
            account_count=0,
        )

    n            = len(tweets)
    texts        = [t["text"] or "" for t in tweets]
    screen_names = [t["user_screen_name"] for t in tweets]
    timestamps   = [t["timestamp"] for t in tweets]

    similar_match_count = _find_similar_pairs(texts, screen_names)

    indexed_by_time = sorted(
        [(i, ts) for i, ts in enumerate(timestamps) if ts is not None],
        key=lambda pair: pair[1],
    )
    timestamps_sorted  = [ts for _, ts in indexed_by_time]
    burst_flags_sorted = _compute_burst_membership(timestamps_sorted)
    burst_by_idx       = {
        indexed_by_time[k][0]: burst_flags_sorted[k]
        for k in range(len(indexed_by_time))
    }

    low_engagement_flags = [_is_low_engagement(t) for t in tweets]

    accounts: dict[str, dict] = {}
    for i, t in enumerate(tweets):
        screen_name = t["user_screen_name"]
        if screen_name not in accounts:
            accounts[screen_name] = {
                "created_at":         t["account_created_at"],
                "followers":          t["followers_count"],
                "has_burst":          False,
                "has_template":       False,
                "has_low_engagement": False,
                "tweet_count":        0,
            }
        acc = accounts[screen_name]
        acc["tweet_count"] += 1

        if burst_by_idx.get(i, False):
            acc["has_burst"] = True
        if similar_match_count[i] >= SIMILAR_TWEET_MIN_MATCHES:
            acc["has_template"] = True
        if low_engagement_flags[i] is True:
            acc["has_low_engagement"] = True

    account_scores:    list[float] = []
    account_details:   list[dict]  = []

    for screen_name, acc in accounts.items():
        conditions_met = 0
        reasons        = []

        if _is_new_account(acc["created_at"], alert.detected_at):
            conditions_met += 1
            reasons.append("new_account")

        if _is_low_followers(acc["followers"]):
            conditions_met += 1
            reasons.append("low_followers")

        if acc["has_burst"]:
            conditions_met += 1
            reasons.append("burst")

        if acc["has_template"]:
            conditions_met += 1
            reasons.append("template")

        if acc["has_low_engagement"]:
            conditions_met += 1
            reasons.append("low_engagement")

        account_score = conditions_met / TOTAL_CONDITIONS
        account_scores.append(account_score)

        if account_score >= MIN_SCORE_FOR_AUDIT_TRAIL:
            account_details.append({
                "screen_name":    screen_name,
                "account_score":  round(account_score, 2),
                "conditions_met": conditions_met,
                "reasons":        reasons,
                "tweet_count":    acc["tweet_count"],
            })

    account_count = len(accounts)
    coordinated_ratio = (
        sum(account_scores) / account_count if account_count > 0 else 0.0
    )

    result = AnalysisResult(
        alert_id=alert.id,
        coordinated_ratio=coordinated_ratio,
        sample_size=n,
        account_count=account_count,
        flagged_accounts=sorted(
            account_details,
            key=lambda x: x["account_score"],
            reverse=True,
        ),
    )

    logger.info(
        f"analyzer | alert_id={alert.id} | '{alert.rising_cluster_label}' | "
        f"tweets={result.sample_size} | accounts={result.account_count} | "
        f"coordinated_ratio={result.coordinated_ratio:.3f}"
    )

    return result