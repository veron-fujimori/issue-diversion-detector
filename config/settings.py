from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = PROJECT_ROOT / "data"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    OPENAI_API_KEY: str
    OPENAI_MODEL: str

    REGION: str = "indonesia"
    DATE_START: str
    DATE_END: str
    TREND_INTERVAL: int = 1
    LANG: str = ""

    VOLUME_INTERVAL_HOURS: int = 1
    CORRELATION_THRESHOLD: float = -0.2
    SPIKE_RATIO_THRESHOLD: float = 2.0

    TRENDING_BASE_URL: str = "https://archive.twitter-trending.com"

    CONTEXT_CHECK_ENABLED: bool = False
    CONTEXT_CHECK_MAX_SUPPRESSION: float = 0.5
    CONTEXT_CHECK_MIN_CONFIDENCE: float = 0.6

    SCWEET_LIMIT: Optional[int] = None

    SCWEET_DAILY_REQUESTS: int = 30
    SCWEET_DAILY_TWEETS: int = 600
    SCWEET_API_PAGE_SIZE: int = 20
    SCWEET_USER_INFO_BATCH: int = 20

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.DB_HOST} "
            f"port={self.DB_PORT} "
            f"dbname={self.DB_NAME} "
            f"user={self.DB_USER} "
            f"password={self.DB_PASSWORD}"
        )

    @property
    def DATA_DIR(self) -> Path:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        return _DATA_DIR

    @property
    def TRENDING_DIR(self) -> Path:
        path = self.DATA_DIR / "raw" / "trending"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def ACCOUNTS_DIR(self) -> Path:
        path = self.DATA_DIR / "accounts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def SCWEET_COOKIES_FILE(self) -> Path:
        return self.ACCOUNTS_DIR / "cookies.json"

    @property
    def SCWEET_STATE_DB(self) -> Path:
        return self.ACCOUNTS_DIR / "scweet_state.db"

settings = Settings()