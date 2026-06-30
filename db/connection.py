from contextlib import contextmanager
from typing import Generator
import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor
from config.settings import settings
from utils.logger import logger

_pool: pg_pool.ThreadedConnectionPool | None = None

def init_pool(min_conn: int = 2, max_conn: int = 3) -> None:
    global _pool

    if _pool is not None:
        return

    try:
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=min_conn,
            maxconn=max_conn,
            dsn=settings.db_dsn,
            options="-c TimeZone=Asia/Jakarta",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )

        conn = _pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW TimeZone")
                tz = cur.fetchone()[0]
                logger.info(f"DB pool initialized ({min_conn}-{max_conn} connections) | timezone={tz}")
        finally:
            _pool.putconn(conn)
    except psycopg2.OperationalError as e:
        logger.error(f"Gagal konek ke database: {e}")
        raise

def _get_pool() -> pg_pool.ThreadedConnectionPool:
    if _pool is None:
        init_pool()
    return _pool

@contextmanager
def get_conn() -> Generator:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

@contextmanager
def get_cursor(cursor_factory=RealDictCursor) -> Generator:
    with get_conn() as conn:
        cursor = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
        finally:
            cursor.close()

def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("DB pool closed")