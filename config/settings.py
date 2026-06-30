from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (config/settings.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    # ── LLM (clustering / classification) ──
    GROQ_API_KEY: str
    GROQ_MODEL: str

    # ── Collection scope ──
    REGION: str = "indonesia"
    DATE_START: str                       # 'YYYY-MM-DD'
    DATE_END: str                         # 'YYYY-MM-DD'
    TREND_INTERVAL: int = 4               # hours between trending slots (00:00, 04:00, ...)

    # lang filter is currently DISABLED: combining lang='id' with display_type='Latest' returns 0 tweets (Scweet/Twitter bug). 
    # Kept here for future use; empty string means "no language filter".
    LANG: str = ""

    # ── Trending archive ──
    TRENDING_BASE_URL: str = "https://archive.twitter-trending.com"

    # ── Scweet limits ──
    SCWEET_LIMIT: int = 500               # max tweets per search job
    SCWEET_DAILY_REQUESTS: int = 30       # page requests per account per day
    SCWEET_DAILY_TWEETS: int = 600        # tweets per account per day
    SCWEET_USER_INFO_BATCH: int = 20      # accounts per get_user_info batch

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.DB_HOST} "
            f"port={self.DB_PORT} "
            f"dbname={self.DB_NAME} "
            f"user={self.DB_USER} "
            f"password={self.DB_PASSWORD}"
        )

    # ── Derived filesystem paths ──
    # Defined as properties (not env fields) so they are always consistent
    # relative to the project root. Directories are created on access.
    @property
    def DATA_DIR(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR

    @property
    def TRENDING_DIR(self) -> Path:
        p = DATA_DIR / "raw" / "trending"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def ACCOUNTS_DIR(self) -> Path:
        p = DATA_DIR / "accounts"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def SCWEET_COOKIES_FILE(self) -> Path:
        return self.ACCOUNTS_DIR / "cookies.json"

    @property
    def SCWEET_STATE_DB(self) -> Path:
        return self.ACCOUNTS_DIR / "scweet_state.db"

settings = Settings()