"""Data lifecycle: retention/disposal and data-subject rights (access + erasure) with a suppression list."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.data.database import Database
from app.governance.policy import retention_days


def _now() -> datetime:
    return datetime.now(timezone.utc)


def subject_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()


class RetentionService:
    # table -> timestamp column compared against the cut-off (all ISO-8601 strings, which sort chronologically)
    _TABLES = {"analyses": "created_at", "llm_egress_ledger": "ts", "reviewer_decisions": "created_at"}

    def __init__(self, db: Database, settings):
        self.db, self.settings = db, settings

    def purge(self, dry_run: bool = True) -> dict:
        days = retention_days(self.settings)
        now, report = _now(), {}
        with self.db.connect() as conn:
            for table, col in self._TABLES.items():
                cutoff = (now - timedelta(days=days[table])).isoformat()
                n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} < ?", (cutoff,)).fetchone()[0]
                if n and not dry_run:
                    conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
                report[table] = {"retention_days": days[table], "cutoff": cutoff, "expired_rows": n, "deleted": 0 if dry_run else n}
            report["mcp_audit"] = self._purge_audit(conn, now - timedelta(days=days["mcp_audit"]), dry_run, days["mcp_audit"])
        return {"dry_run": dry_run, "tables": report}

    @staticmethod
    def _purge_audit(conn, cutoff: datetime, dry_run: bool, days: int) -> dict:
        """Audit rows are append-only; expired ones go through a gated delete that leaves a hash checkpoint."""
        iso = cutoff.isoformat(timespec="milliseconds")
        # Only a contiguous expired prefix may go: the chain cannot have holes, and nothing newer may be removed.
        first_live = conn.execute("SELECT MIN(id) FROM mcp_audit WHERE ts >= ?", (iso,)).fetchone()[0]
        last = conn.execute(
            "SELECT id, hash FROM mcp_audit WHERE ts < ? AND id < COALESCE(?, 9223372036854775807) ORDER BY id DESC LIMIT 1",
            (iso, first_live),
        ).fetchone()
        n = conn.execute("SELECT COUNT(*) FROM mcp_audit WHERE id <= ?", (last["id"],)).fetchone()[0] if last else 0
        out = {"retention_days": days, "cutoff": iso, "expired_rows": n, "deleted": 0}
        if last and not dry_run:
            conn.execute("INSERT INTO audit_purge_gate VALUES (?)", (_now().isoformat(),))
            try:
                conn.execute("DELETE FROM mcp_audit WHERE id <= ?", (last["id"],))
                conn.execute(
                    "INSERT INTO mcp_audit_checkpoint (id, last_purged_id, last_hash, purged_at) VALUES (1,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET last_purged_id=excluded.last_purged_id, last_hash=excluded.last_hash,"
                    " purged_at=excluded.purged_at",
                    (last["id"], last["hash"], _now().isoformat()),
                )
            finally:
                conn.execute("DELETE FROM audit_purge_gate")
            out["deleted"] = n
        return out


class SubjectRights:
    """Access and erasure for a data subject, identified by their (pseudonymous) reviewer id."""

    def __init__(self, db: Database, suppression_file: Path):
        self.db, self.suppression_file = db, suppression_file

    def export(self, user_id: str, limit: int = 200) -> dict:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT r.id, r.product_id, p.title AS product_title, r.rating, r.title, r.text, r.ts, r.verified, r.helpful"
                " FROM reviews r LEFT JOIN products p ON p.id = r.product_id WHERE r.user_id = ? ORDER BY r.ts LIMIT ?",
                (user_id, limit),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM reviews WHERE user_id = ?", (user_id,)).fetchone()[0]
            flagged = conn.execute(
                "SELECT COUNT(DISTINCT a.product_id) FROM analyses a JOIN reviews r ON r.product_id = a.product_id WHERE r.user_id = ?",
                (user_id,),
            ).fetchone()[0]
        return {
            "subject_hash": subject_hash(user_id),
            "review_count": total,
            "returned": len(rows),
            "analyses_referencing_subject": flagged,
            "reviews": [dict(r) for r in rows],
            "processing_notes": "Reviews are used to score listings for review manipulation; identifiers are pseudonymous.",
        }

    def erase(self, user_id: str, reference: str, requested_by: str, dry_run: bool = True) -> dict:
        h = subject_hash(user_id)
        with self.db.connect() as conn:
            products = [r[0] for r in conn.execute("SELECT DISTINCT product_id FROM reviews WHERE user_id = ?", (user_id,))]
            n = conn.execute("SELECT COUNT(*) FROM reviews WHERE user_id = ?", (user_id,)).fetchone()[0]
            marks = ",".join("?" * len(products)) or "''"
            stale = conn.execute(f"SELECT COUNT(*) FROM analyses WHERE product_id IN ({marks})", products).fetchone()[0]
            result = {"dry_run": dry_run, "subject_hash": h, "reviews_to_delete": n, "analyses_to_invalidate": stale,
                      "affected_products": len(products), "reference": reference}  # fmt: skip
            if dry_run:
                return result
            conn.execute("DELETE FROM reviews WHERE user_id = ?", (user_id,))
            conn.execute(f"DELETE FROM analyses WHERE product_id IN ({marks})", products)  # derived data embedding the subject
            conn.execute("UPDATE products SET review_count = (SELECT COUNT(*) FROM reviews WHERE product_id = products.id)"
                         f" WHERE id IN ({marks})", products)  # fmt: skip
            conn.execute(
                "INSERT INTO erasure_requests (subject_hash, reference, requested_by, reviews_deleted, analyses_invalidated, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (h, reference, requested_by, n, stale, _now().isoformat(timespec="seconds")),
            )
        self._suppress(h)
        return {**result, "reviews_deleted": n, "analyses_invalidated": stale, "suppression_file": str(self.suppression_file)}

    def _suppress(self, h: str) -> None:
        """Hash list read by scripts/build_dataset.py so an erased subject is not re-ingested on rebuild."""
        self.suppression_file.parent.mkdir(parents=True, exist_ok=True)
        existing = set(self.suppression_file.read_text().split()) if self.suppression_file.exists() else set()
        if h not in existing:
            with self.suppression_file.open("a") as fh:
                fh.write(h + "\n")
