"""
db/migrate.py — apply all SQL migrations in db/migrations/ in filename order.

Each .sql file is expected to be idempotent (CREATE TABLE IF NOT EXISTS,
CREATE INDEX IF NOT EXISTS, etc.), so this runner simply applies every file
on each run. Already-existing objects are skipped by Postgres. There is no
migration-tracking table — re-running is safe and is the intended workflow.

Files are applied in lexical filename order, so number your migrations with
zero-padded prefixes (001_, 002_, ...). Each file is applied atomically: if
any statement in a file fails, that file's transaction is rolled back (via
get_cursor's context manager) and the error is re-raised immediately.

Run:
    python -m db.migrate
"""

import sys
from pathlib import Path

from db.connection import get_cursor, init_pool, close_pool
from utils.logger import logger

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _find_migrations() -> list[Path]:
    """Return all .sql files in db/migrations/, sorted by filename."""
    if not MIGRATIONS_DIR.exists():
        logger.error(f"migrate | migrations dir not found: {MIGRATIONS_DIR}")
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)
    return files


def _apply_file(path: Path) -> None:
    """
    Apply a single .sql file. The whole file is sent as one execute() call,
    so it runs inside one transaction (get_cursor commits on success, rolls
    back on error). Raises on failure so the caller can stop the run.
    """
    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        logger.warning(f"migrate | {path.name} is empty — skipping")
        return

    with get_cursor() as cur:
        cur.execute(sql)
    logger.info(f"migrate | applied {path.name}")


def run() -> None:
    files = _find_migrations()
    if not files:
        logger.warning("migrate | no .sql migration files found — nothing to do")
        return

    logger.info(f"migrate | found {len(files)} migration file(s) in {MIGRATIONS_DIR}")
    for f in files:
        logger.info(f"migrate | applying {f.name} ...")
        try:
            _apply_file(f)
        except Exception as e:
            logger.error(f"migrate | FAILED on {f.name}: {e}")
            raise

    logger.info(f"migrate | all {len(files)} migration(s) applied successfully")


def main() -> None:
    init_pool()
    try:
        run()
    finally:
        close_pool()


if __name__ == "__main__":
    main()