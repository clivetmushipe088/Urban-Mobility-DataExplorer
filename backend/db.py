import sqlite3
from contextlib import contextmanager

import config

TABLES = ("zones", "trips", "exclusion_log")

@contextmanager
def get_connection(path=None):
    """Yeild a sqlite connection with dict-like rows and foriegn key on alwys closes it."""
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()    


def init_db(reset: bool = False) -> None:
    """Create the database file and tables. reset=True deletes the existing file first"""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if reset and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    with get_connection() as conn:
        conn.executescript(config.SCHEMA_PATH.read_text())
        conn.commit()


def table_counts() -> dict:
    """Row count per table, or None if a table is missing"""
    counts = {}
    with get_connection() as conn:
        for table in TABLES:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = None
    return counts


def is_db_ready() -> bool:
    """True when the DB file Exists and both zones and trips contain rows"""
    if not config.DB_PATH.exists():
        return False
    counts = table_counts()
    return bool(counts.get("zones")) and bool(counts.get("trips"))