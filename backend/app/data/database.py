import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    store TEXT,
    avg_rating REAL,
    rating_count INTEGER,
    price REAL,
    image_url TEXT,
    features TEXT,
    review_count INTEGER NOT NULL DEFAULT 0,
    spike_ratio REAL NOT NULL DEFAULT 0,
    is_focus INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    product_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    rating REAL NOT NULL,
    title TEXT,
    text TEXT,
    ts INTEGER NOT NULL,
    verified INTEGER NOT NULL,
    helpful INTEGER NOT NULL,
    has_images INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);
CREATE INDEX IF NOT EXISTS idx_products_store ON products(store);
CREATE TABLE IF NOT EXISTS baselines (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    product_id TEXT PRIMARY KEY,
    risk_score REAL NOT NULL,
    tier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class Database:
    """Thin SQLite wrapper: one short-lived connection per unit of work."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
