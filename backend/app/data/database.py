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
-- Governance tables (MCP). The audit log is append-only and hash-chained for tamper evidence.
CREATE TABLE IF NOT EXISTS audit_purge_gate (opened_at TEXT);
CREATE TABLE IF NOT EXISTS mcp_audit_checkpoint (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_purged_id INTEGER NOT NULL,
    last_hash TEXT NOT NULL,
    purged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT,
    principal TEXT NOT NULL,
    role TEXT NOT NULL,
    transport TEXT NOT NULL,
    method TEXT NOT NULL,
    target TEXT,
    args TEXT,
    outcome TEXT NOT NULL,
    detail TEXT,
    duration_ms INTEGER,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS mcp_audit_no_update BEFORE UPDATE ON mcp_audit
BEGIN SELECT RAISE(ABORT, 'mcp_audit is append-only'); END;
DROP TRIGGER IF EXISTS mcp_audit_no_delete;
-- Deletion is only possible inside the retention routine, which opens the gate and leaves a checkpoint.
CREATE TRIGGER mcp_audit_no_delete BEFORE DELETE ON mcp_audit
WHEN (SELECT COUNT(*) FROM audit_purge_gate) = 0
BEGIN SELECT RAISE(ABORT, 'mcp_audit is append-only outside the retention routine'); END;
CREATE TABLE IF NOT EXISTS reviewer_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT NOT NULL,
    principal TEXT NOT NULL,
    role TEXT NOT NULL,
    session_id TEXT,
    analysis_created_at TEXT NOT NULL,
    risk_score REAL NOT NULL,
    tier TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- Data-governance tables
CREATE TABLE IF NOT EXISTS governance_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_egress_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    processor TEXT NOT NULL,
    model TEXT,
    purpose TEXT NOT NULL,
    data_classes TEXT NOT NULL,
    bytes_sent INTEGER NOT NULL,
    redactions INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS erasure_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_hash TEXT NOT NULL,
    reference TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    reviews_deleted INTEGER NOT NULL,
    analyses_invalidated INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_product ON reviewer_decisions(product_id);
"""


class Database:
    """Thin SQLite wrapper: one short-lived connection per unit of work."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
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
